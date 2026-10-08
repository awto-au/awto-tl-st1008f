import fs from 'node:fs';
import { spawn } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';

// Historical helper (Node), kept as used 2026-10-07/08; new tooling is Python. See scripts/README.md.
// Run from the repo root. SERIAL_PORT=/dev/serial/by-id/<adapter> is required.
function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} in the environment (see scripts/README.md)`);
  return value;
}

const port = requiredEnv('SERIAL_PORT');
const image = process.env.IMAGE || 'private/openwrt/openwrt-25.12.4-realtek-rtl930x-tplink_tl-st1008f-v2-initramfs-kernel.bin';
const directory = 'private/serial';
fs.mkdirSync(directory, { recursive: true });
const stamp = new Date().toISOString().replaceAll(/[-:.]/g, '').replace('T', '-').slice(0, 15);
const log = fs.openSync(`${directory}/ram-transfer-${stamp}.log`, 'wx');
const statusFile = `${directory}/ram-transfer-${stamp}.status.json`;
let fd = fs.openSync(port, fs.constants.O_RDWR | fs.constants.O_NOCTTY | fs.constants.O_NONBLOCK);
const state = { pid: process.pid, state: 'checking-prompt', image, loadAddress: '0x82000000' };
function status() {
  fs.writeFileSync(statusFile,
    JSON.stringify({ ...state, updated: new Date().toISOString() }, null, 2) + '\n');
}
async function receive(match, timeout) {
  const buffer = Buffer.alloc(8192);
  const start = Date.now();
  let text = '';
  while (Date.now() - start < timeout) {
    try {
      const n = fs.readSync(fd, buffer, 0, buffer.length, null);
      if (n) {
        fs.writeSync(log, buffer, 0, n);
        text += buffer.subarray(0, n).toString('ascii');
        if (match.test(text)) return text;
      }
    } catch (error) {
      if (!['EAGAIN', 'EWOULDBLOCK'].includes(error.code)) throw error;
    }
    await delay(20);
  }
  throw new Error('Serial response timed out');
}
function send(text) {
  fs.writeSync(log, `\n[TX] ${text}\n`);
  const data = Buffer.from(text + '\r');
  if (fs.writeSync(fd, data) !== data.length) throw new Error('Incomplete serial write');
}
try {
  status();
  send('version');
  const version = await receive(/\r?\nRTL9300#(?: #)? $/, 10000);
  if (!version.includes('3.6.6.55087')) throw new Error('Unexpected bootloader');
  send('loady 0x82000000');
  const ready = await receive(/C+$/, 15000);
  if (!ready.includes('82000000')) throw new Error('Unexpected YMODEM load address');
  fs.closeSync(fd);
  fd = fs.openSync(port, fs.constants.O_RDWR | fs.constants.O_NOCTTY);
  state.state = 'transferring';
  status();
  console.log('YMODEM transfer started; 5,383,940 bytes to RAM only.');
  const child = spawn('/usr/bin/sb', ['--ymodem', '--binary', '--verbose', image],
    { stdio: [fd, fd, log] });
  await new Promise((resolve, reject) => {
    child.once('error', reject);
    child.once('exit', (code, signal) => {
      if (code === 0) resolve();
      else reject(new Error(`YMODEM sender failed: code=${code}, signal=${signal}`));
    });
  });
  fs.closeSync(fd);
  fd = fs.openSync(port, fs.constants.O_RDWR | fs.constants.O_NOCTTY | fs.constants.O_NONBLOCK);
  send('');
  const result = await receive(/\r?\nRTL9300#(?: #)? $/, 15000);
  console.log(result);
  state.state = 'transferred-not-booted';
  status();
  console.log('Transfer finished. Image remains in RAM; bootm has NOT been sent.');
} catch (error) {
  state.state = 'failed';
  state.error = error.message;
  status();
  throw error;
} finally {
  fs.closeSync(fd);
  fs.fsyncSync(log);
  fs.closeSync(log);
}
