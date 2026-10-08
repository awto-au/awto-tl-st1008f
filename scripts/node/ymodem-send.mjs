import fs from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';

// Historical helper (Node), kept as used 2026-10-07/08; new tooling is Python. See scripts/README.md.
// Run from the repo root. SERIAL_PORT=/dev/serial/by-id/<adapter> is required.
function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} in the environment (see scripts/README.md)`);
  return value;
}

const directory = 'private/serial';
fs.mkdirSync(directory, { recursive: true });
const log = fs.openSync(`${directory}/ymodem-protocol-20261007.log`, 'wx');
const fd = fs.openSync(requiredEnv('SERIAL_PORT'),
  fs.constants.O_RDWR | fs.constants.O_NOCTTY | fs.constants.O_NONBLOCK);
const image = fs.readFileSync(process.env.IMAGE || 'private/openwrt/openwrt-25.12.4-realtek-rtl930x-tplink_tl-st1008f-v2-initramfs-kernel.bin');
let queue = [];
const state = { pid: process.pid, state: 'waiting', acknowledgedBytes: 0, totalBytes: image.length };
function record(text) {
  fs.writeSync(log, `${new Date().toISOString()} ${text}\n`);
}
function status() {
  fs.writeFileSync(`${directory}/ymodem-protocol-20261007.status.json`, JSON.stringify(state, null, 2) + '\n');
}
async function readByte(timeout = 12000) {
  const start = Date.now(), buffer = Buffer.alloc(4096);
  while (Date.now() - start < timeout) {
    if (queue.length) return queue.shift();
    try {
      const n = fs.readSync(fd, buffer, 0, buffer.length, null);
      if (n) queue.push(...buffer.subarray(0, n));
    } catch (error) {
      if (!['EAGAIN', 'EWOULDBLOCK'].includes(error.code)) throw error;
    }
    await delay(5);
  }
  throw new Error('YMODEM response timeout');
}
async function write(data) {
  let offset = 0;
  while (offset < data.length) {
    try {
      offset += fs.writeSync(fd, data, offset, data.length - offset);
    } catch (error) {
      if (!['EAGAIN', 'EWOULDBLOCK'].includes(error.code)) throw error;
      await delay(5);
    }
  }
}
function packet(number, data) {
  let crc = 0;
  for (const byte of data) {
    crc ^= byte << 8;
    for (let i = 0; i < 8; i++) crc = (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1;
    crc &= 0xffff;
  }
  return Buffer.concat([Buffer.from([data.length === 1024 ? 2 : 1, number & 255, 255 - (number & 255)]),
    data, Buffer.from([crc >> 8, crc & 255])]);
}
async function expect(value) {
  for (let i = 0; i < 128; i++) {
    const byte = await readByte();
    if (byte === value) return;
    record(`Unexpected byte while waiting for ${value}: ${byte}`);
    if (byte === 24) throw new Error('Receiver cancelled');
  }
  throw new Error('Expected protocol byte not received');
}
async function sendPacket(number, data) {
  for (let attempt = 0; attempt < 5; attempt++) {
    await write(packet(number, data));
    const byte = await readByte();
    if (byte === 6) return;
    record(`Block ${number}, attempt ${attempt}, response ${byte}`);
    if (![21, 67].includes(byte)) throw new Error(`Unexpected receiver response ${byte}`);
  }
  throw new Error(`Block ${number} never acknowledged`);
}
try {
  status();
  await expect(67);
  const header = Buffer.alloc(128);
  header.write(`initramfs.bin\0${image.length}\0`);
  await sendPacket(0, header);
  record('Header ACK received');
  await expect(67);
  state.state = 'transferring';
  for (let offset = 0, number = 1; offset < image.length; offset += 1024, number++) {
    const data = Buffer.alloc(1024, 26);
    image.copy(data, 0, offset, Math.min(offset + 1024, image.length));
    await sendPacket(number, data);
    state.acknowledgedBytes = Math.min(offset + 1024, image.length);
    if (number % 64 === 0 || state.acknowledgedBytes === image.length) {
      status();
      record(`ACK verified ${state.acknowledgedBytes}/${image.length}`);
    }
  }
  await write(Buffer.from([4]));
  let reply = await readByte();
  if (reply === 21) {
    await write(Buffer.from([4]));
    reply = await readByte();
  }
  if (reply !== 6) throw new Error(`EOT not acknowledged: ${reply}`);
  await expect(67);
  await sendPacket(0, Buffer.alloc(128));
  state.state = 'transferred-not-booted';
  record('Transfer acknowledged; bootm NOT sent');
  status();
} catch (error) {
  state.state = 'failed';
  state.error = error.message;
  record(error.message);
  status();
  throw error;
} finally {
  fs.closeSync(fd);
  fs.closeSync(log);
}
