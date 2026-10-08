#!/usr/bin/env node
/**
 * Read a verified RTL9300 U-Boot flash map using md.b only.
 * Usage: node serial_flash_backup.mjs serial-by-path new-output-directory [--loader-only]
 * Configure 115200 8N1 first and stop all other users of this serial port.
 * Performs two complete reads, checks U-Boot CRC32 and exact equality,
 * then carves the seven partitions. No flash writes or boot commands.
 */
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';

const BASE = 0xb4000000;
const FLASH_SIZE = 0x2000000;
const CHUNK = 0x4000;
const PARTITIONS = [
  ['loader', 0, 0xe0000],
  ['bdinfo', 0xe0000, 0x10000],
  ['sysinfo', 0xf0000, 0x10000],
  ['jffs2-cfg', 0x100000, 0x100000],
  ['jffs2-log', 0x200000, 0x100000],
  ['runtime1', 0x300000, 0xe80000],
  ['runtime2', 0x1180000, 0xe80000],
];
const table = Array.from({ length: 256 }, (_, index) => {
  let value = index;
  for (let bit = 0; bit < 8; bit++) {
    value = (value & 1) ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
  }
  return value >>> 0;
});
function crc32(buffer) {
  let value = 0xffffffff;
  for (const byte of buffer) value = table[(value ^ byte) & 255] ^ (value >>> 8);
  return ((value ^ 0xffffffff) >>> 0).toString(16).padStart(8, '0');
}
function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

export function parseDump(text, address, length) {
  const output = Buffer.alloc(length);
  let offset = 0;
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^([0-9a-f]{8}): ((?:[0-9a-f]{2} ){15}[0-9a-f]{2})(?:\s|$)/i);
    if (!match) continue;
    if (Number.parseInt(match[1], 16) !== address + offset || offset + 16 > length) {
      throw new Error(`Missing, duplicated or out-of-order dump row at ${offset}`);
    }
    Buffer.from(match[2].split(' ').map(byte => Number.parseInt(byte, 16))).copy(output, offset);
    offset += 16;
  }
  if (offset !== length) throw new Error(`Incomplete dump: ${offset}/${length} bytes`);
  return output;
}

async function main() {
  const args = process.argv.slice(2);
  if (args.length !== 2 && !(args.length === 3 && args[2] === '--loader-only')) {
    throw new Error('Usage: node serial_flash_backup.mjs port new-output-directory [--loader-only]');
  }
  const [port, directory] = args;
  const loaderOnly = args[2] === '--loader-only';
  const SIZE = loaderOnly ? 0xe0000 : FLASH_SIZE;
  const prefix = loaderOnly ? 'loader' : 'full-flash';
  fs.mkdirSync(directory);
  const fd = fs.openSync(port, fs.constants.O_RDWR | fs.constants.O_NOCTTY | fs.constants.O_NONBLOCK);
  const log = fs.openSync(path.join(directory, 'serial.log'), 'wx');
  const state = {
    pid: process.pid, port, started: new Date().toISOString(), state: 'starting',
    flashBase: '0xb4000000', flashBytes: SIZE, pass: 0, bytesReadThisPass: 0,
    scope: loaderOnly ? 'LOADER partition only; not a full-flash backup' : 'full flash',
    method: 'U-Boot md.b; two reads with target CRC32 and byte equality',
  };
  let interrupted = false;
  process.once('SIGTERM', () => { interrupted = true; });
  process.once('SIGINT', () => { interrupted = true; });
  function status() {
    fs.writeFileSync(path.join(directory, 'status.json'), JSON.stringify(state, null, 2) + '\n');
  }
  async function command(text) {
    if (interrupted) throw new Error('Backup interrupted; partial data preserved');
    fs.writeSync(log, `\n[TX ${new Date().toISOString()}] ${text}\n`);
    const data = Buffer.from(text + '\r');
    if (fs.writeSync(fd, data) !== data.length) throw new Error('Incomplete serial transmission');
    const start = Date.now(), buffer = Buffer.alloc(65536);
    let response = '';
    while (Date.now() - start < 180000) {
      if (interrupted) throw new Error('Backup interrupted; partial data preserved');
      try {
        const bytes = fs.readSync(fd, buffer, 0, buffer.length, null);
        if (bytes) {
          fs.writeSync(log, buffer, 0, bytes);
          response += buffer.subarray(0, bytes).toString('ascii');
          if (/\r?\nRTL9300#(?: #)? $/.test(response)) return response;
          if (response.length > 200000) throw new Error('Unexpectedly large command response');
        }
      } catch (error) {
        if (error.code !== 'EAGAIN' && error.code !== 'EWOULDBLOCK') throw error;
      }
      await delay(10);
    }
    throw new Error(`Timed out waiting for U-Boot after ${text}`);
  }
  async function targetCrc() {
    const response = await command(`crc32 b4000000 ${SIZE.toString(16)}`);
    const match = response.match(/CRC32 for [0-9a-f]+ \.\.\. [0-9a-f]+ ==> ([0-9a-f]{8})/i);
    if (!match) throw new Error('Unrecognised target CRC response');
    return match[1].toLowerCase();
  }
  try {
    status();
    const help = await command('help crc32');
    if (!help.includes('checksum')) throw new Error('Unexpected bootloader command response');
    const reads = [];
    for (let pass = 1; pass <= 2; pass++) {
      state.pass = pass;
      state.bytesReadThisPass = 0;
      state.state = 'reading';
      const expected = await targetCrc();
      state.targetCrc32 = expected;
      status();
      const partial = path.join(directory, `${prefix}-read${pass}.bin.partial`);
      const output = fs.openSync(partial, 'wx');
      const passStart = Date.now();
      try {
        for (let offset = 0; offset < SIZE; offset += CHUNK) {
          const address = BASE + offset;
          const response = await command(`md.b ${address.toString(16)} ${CHUNK.toString(16)}`);
          const data = parseDump(response, address, CHUNK);
          if (fs.writeSync(output, data) !== data.length) throw new Error('Incomplete backup file write');
          state.bytesReadThisPass = offset + CHUNK;
          state.secondsThisPass = (Date.now() - passStart) / 1000;
          state.estimatedSecondsRemainingThisPass =
            state.secondsThisPass * (SIZE - state.bytesReadThisPass) / state.bytesReadThisPass;
          status();
          if (offset % 0x100000 === 0) {
            fs.fsyncSync(output);
            console.log(`Pass ${pass}: ${state.bytesReadThisPass}/${SIZE} bytes`);
          }
        }
        fs.fsyncSync(output);
      } finally {
        fs.closeSync(output);
      }
      const bytes = fs.readFileSync(partial);
      if (bytes.length !== SIZE || crc32(bytes) !== expected || await targetCrc() !== expected) {
        throw new Error(`Pass ${pass}: target/host CRC or size mismatch; partial file retained`);
      }
      const filename = partial.replace(/\.partial$/, '');
      fs.renameSync(partial, filename);
      reads.push({ file: filename, size: bytes.length, sha256: sha256(bytes), crc32: expected });
    }
    const first = fs.readFileSync(reads[0].file), second = fs.readFileSync(reads[1].file);
    if (!first.equals(second)) throw new Error('Two full reads differ; no verified backup declared');
    const selectedPartitions = loaderOnly ? PARTITIONS.slice(0, 1) : PARTITIONS;
    const partitions = selectedPartitions.map(([name, offset, size]) => {
      const bytes = first.subarray(offset, offset + size);
      const file = path.join(directory, `${name}.bin`);
      fs.writeFileSync(file, bytes, { flag: 'wx' });
      return { name, file, offset, size, sha256: sha256(bytes) };
    });
    fs.writeFileSync(path.join(directory, 'manifest.json'),
      JSON.stringify({ reads, identical: true, partitions, scope: state.scope, method: state.method }, null, 2) + '\n');
    state.state = 'complete';
    status();
    console.log(`Two reads match; CRCs verified; ${partitions.length} partition(s) preserved. Scope: ${state.scope}`);
  } catch (error) {
    state.state = 'failed';
    state.error = error.message;
    status();
    throw error;
  } finally {
    fs.closeSync(log);
    fs.closeSync(fd);
  }
}

if (process.argv[1] && import.meta.url === new URL(`file://${path.resolve(process.argv[1])}`).href) {
  main().catch(error => { console.error(error); process.exitCode = 1; });
}
