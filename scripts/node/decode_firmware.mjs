#!/usr/bin/env node
/**
 * Offline decoder for the acquired SX3008F/ST5008/ST5008F update containers.
 * Run with node --openssl-legacy-provider; supply the official DesDecode.c,
 * an original update BIN, and a new output filename. Never flash the output.
 */
import crypto from 'node:crypto';
import fs from 'node:fs';

const args = process.argv.slice(2);
if (args.length !== 3) {
  console.error('Usage: node --openssl-legacy-provider decode_firmware.mjs DesDecode.c input.bin output.bin');
  process.exit(2);
}

const [sourcePath, inputPath, outputPath] = args;
const sourceBytes = fs.readFileSync(sourcePath);
const source = sourceBytes.toString('utf8');
function readArray(name) {
  const match = source.match(new RegExp(
    `unsigned char ${name}\\[\\]\\s*=\\s*\\{([^}]+)\\}`,
  ));
  if (!match) throw new Error(`Missing ${name} in vendor source`);
  const values = match[1].match(/0x[0-9a-f]+/gi);
  if (!values || values.length !== 8) {
    throw new Error(`Expected eight bytes in ${name}`);
  }
  return Buffer.from(values.map(value => {
    const byte = Number.parseInt(value, 16);
    if (byte > 255) throw new Error(`Invalid byte in ${name}`);
    return byte;
  }));
}

const crcTable = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit++) {
    value = (value & 1) ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  return value >>> 0;
});
function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) {
    value = crcTable[(value ^ byte) & 255] ^ (value >>> 8);
  }
  return (value ^ 0xffffffff) >>> 0;
}
function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

const input = fs.readFileSync(inputPath);
if (input.length < 2656 || input.length % 8 !== 0) {
  throw new Error('Input is too short or not DES block-aligned');
}
const decipher = crypto.createDecipheriv('des-cbc', readArray('des_key'), readArray('des_iv'));
decipher.setAutoPadding(false);
const decoded = Buffer.concat([decipher.update(input), decipher.final()]);
const offsets = [512, 2560].filter(offset => (
  decoded.subarray(offset, offset + 4).toString('ascii') === 'hsqs'
  && decoded.readUInt16LE(offset + 28) === 4
  && decoded.readUInt16LE(offset + 30) === 0
));
if (offsets.length !== 1) {
  throw new Error('Expected one SquashFS v4.0 at a supported container offset');
}
const rootfsOffset = offsets[0];
const rootfsBytes = decoded.readBigUInt64LE(rootfsOffset + 40);
const sizesOffset = rootfsOffset === 2560 ? 236 : 232;
const rootfsAllocatedBytes = decoded.readUInt32BE(sizesOffset);
const kernelBytes = decoded.readUInt32BE(sizesOffset + 4);
const kernelOffset = rootfsOffset + rootfsAllocatedBytes;
const kernelEnd = kernelOffset + kernelBytes;
if (rootfsBytes < 96n || rootfsBytes > BigInt(rootfsAllocatedBytes)
    || kernelBytes < 64 || kernelEnd > decoded.length) {
  throw new Error('Invalid filesystem/kernel bounds');
}

const magic = decoded.readUInt32BE(kernelOffset);
const kernel = { offset: kernelOffset, bytes: kernelBytes, magic: `0x${magic.toString(16)}` };
if (magic === 0x27051956 || magic === 0x93000000) {
  const header = Buffer.from(decoded.subarray(kernelOffset, kernelOffset + 64));
  const expectedHeaderCrc = header.readUInt32BE(4);
  header.writeUInt32BE(0, 4);
  const payloadBytes = header.readUInt32BE(12);
  if (payloadBytes + 64 !== kernelBytes || crc32(header) !== expectedHeaderCrc) {
    throw new Error('Kernel header size or CRC mismatch');
  }
  const payload = decoded.subarray(kernelOffset + 64, kernelEnd);
  if (crc32(payload) !== header.readUInt32BE(24)) {
    throw new Error('Kernel payload CRC mismatch');
  }
  Object.assign(kernel, {
    headerCrcValid: true,
    payloadCrcValid: true,
    architectureId: header[29],
    compressionId: header[31],
    load: `0x${header.readUInt32BE(16).toString(16)}`,
    entry: `0x${header.readUInt32BE(20).toString(16)}`,
  });
} else if (magic === 0xd00dfeed) {
  if (decoded.readUInt32BE(kernelOffset + 4) !== kernelBytes) {
    throw new Error('FIT container size mismatch');
  }
  kernel.format = 'FIT; embedded image hashes require separate validation';
} else {
  throw new Error(`Unsupported kernel magic ${kernel.magic}`);
}

fs.writeFileSync(outputPath, decoded, { flag: 'wx' });
console.log(JSON.stringify({
  input: inputPath,
  output: outputPath,
  inputSha256: sha256(input),
  outputSha256: sha256(decoded),
  vendorSourceSha256: sha256(sourceBytes),
  imageName: decoded.subarray(32, 232).toString('ascii').split('\0')[0],
  size: decoded.length,
  rootfs: {
    offset: rootfsOffset,
    bytesUsed: rootfsBytes.toString(),
    allocatedBytes: rootfsAllocatedBytes,
    compressionId: decoded.readUInt16LE(rootfsOffset + 20),
  },
  kernel,
  trailingContainerBytes: decoded.length - kernelEnd,
}, null, 2));
