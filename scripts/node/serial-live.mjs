import fs from 'node:fs';
import { execFileSync } from 'node:child_process';
import { setTimeout as delay } from 'node:timers/promises';

// Historical helper (Node), kept as used 2026-10-07/08; new tooling is Python. See scripts/README.md.
// Run from the repo root. SERIAL_PORT=/dev/serial/by-id/<adapter> is required.
function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} in the environment (see scripts/README.md)`);
  return value;
}

const port = requiredEnv('SERIAL_PORT');
const directory = 'private/serial';
fs.mkdirSync(directory, { recursive: true });
const baud = Number(process.argv[2] || 115200);
if (!Number.isInteger(baud) || ![38400, 115200].includes(baud)) {
  throw new Error('Baud rate must be 38400 or 115200');
}
execFileSync('stty', [
  '-F', port, String(baud), 'raw', '-echo', 'cs8', '-cstopb', '-parenb',
  '-ixon', '-ixoff', '-crtscts',
]);
const filename = `${directory}/live.log`;
const statusFile = `${directory}/live.status.json`;
const fd = fs.openSync(port, fs.constants.O_RDONLY | fs.constants.O_NOCTTY | fs.constants.O_NONBLOCK);
const log = fs.openSync(filename, 'a');
const state = { pid: process.pid, port, baud, filename, state: 'reading', bytes: 0, startedAt: new Date().toISOString() };
let running = true;
process.once('SIGTERM', () => { running = false; });
process.once('SIGINT', () => { running = false; });
function status() {
  fs.writeFileSync(statusFile, JSON.stringify({ ...state, updated: new Date().toISOString() }, null, 2) + '\n');
}
try {
  status();
  console.log(`Receive-only UART capture active: ${filename}`);
  const buffer = Buffer.alloc(8192);
  let heartbeat = Date.now();
  while (running) {
    try {
      const n = fs.readSync(fd, buffer, 0, buffer.length, null);
      if (n) {
        if (fs.writeSync(log, buffer, 0, n) !== n) throw new Error('Incomplete capture write');
        state.bytes += n;
        process.stdout.write(buffer.subarray(0, n));
      }
    } catch (error) {
      if (!['EAGAIN', 'EWOULDBLOCK'].includes(error.code)) throw error;
    }
    if (Date.now() - heartbeat >= 1000) {
      status();
      heartbeat = Date.now();
    }
    await delay(20);
  }
  state.state = 'stopped';
} catch (error) {
  state.state = 'failed';
  state.error = error.message;
  throw error;
} finally {
  fs.fsyncSync(log);
  fs.closeSync(log);
  fs.closeSync(fd);
  status();
}
