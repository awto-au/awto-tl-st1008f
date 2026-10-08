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
const setFiber10g = process.argv[2] === '--fiber10g-port0';
if (process.argv.length > 3 || (process.argv[2] && !setFiber10g)) {
  throw new Error('Usage: node boot-interrupt.mjs [--fiber10g-port0]');
}
execFileSync('stty', [
  '-F', port, '115200', 'raw', '-echo', 'cs8', '-cstopb', '-parenb',
  '-ixon', '-ixoff', '-crtscts',
]);

const filename = `${directory}/live.log`;
const statusFile = `${directory}/live.status.json`;
const fd = fs.openSync(port, fs.constants.O_RDWR | fs.constants.O_NOCTTY | fs.constants.O_NONBLOCK);
const log = fs.openSync(filename, 'a');
const state = { pid: process.pid, port, baud: 115200, filename, state: 'waiting-for-autoboot-prompt', bytes: 0 };
let running = true;
let tail = '';
let commandDeadline = 0;

function status() {
  fs.writeFileSync(statusFile, JSON.stringify({ ...state, updated: new Date().toISOString() }, null, 2) + '\n');
}

process.once('SIGTERM', () => { running = false; });
process.once('SIGINT', () => { running = false; });

try {
  status();
  console.log(`Watching ${port} at 115200. On the autoboot prompt only, will send one ESC byte. Log: ${filename}`);
  const buffer = Buffer.alloc(8192);
  let heartbeat = Date.now();

  while (running) {
    try {
      const n = fs.readSync(fd, buffer, 0, buffer.length, null);
      if (n) {
        const received = buffer.subarray(0, n);
        if (fs.writeSync(log, received) !== n) throw new Error('Incomplete capture write');
        state.bytes += n;
        process.stdout.write(received);

        const text = tail + received.toString('latin1');
        if (state.state === 'waiting-for-autoboot-prompt' && text.includes('Hit Esc key to stop autoboot:')) {
          const esc = Buffer.from([0x1b]);
          if (fs.writeSync(fd, esc) !== 1) throw new Error('Incomplete Escape write');
          fs.writeSync(log, Buffer.from('\n[TX] ESC sent after autoboot prompt\n'));
          state.state = 'escape-sent-waiting-for-uboot-prompt';
          console.log('\nDetected autoboot prompt; sent one ESC byte.');
          status();
        }
        if (state.state === 'escape-sent-waiting-for-uboot-prompt' && text.includes('RTL9300#')) {
          state.state = 'uboot-prompt-detected';
          if (setFiber10g) {
            const command = Buffer.from('rtk 10g 0 fiber10g\r');
            fs.writeSync(log, Buffer.from('\n[TX] rtk 10g 0 fiber10g\n'));
            if (fs.writeSync(fd, command) !== command.length) throw new Error('Incomplete media command write');
            state.state = 'waiting-for-media-command-response';
            commandDeadline = Date.now() + 15000;
            tail = '';
          } else {
            tail = text.slice(-96);
          }
          status();
        } else {
          if (state.state === 'waiting-for-media-command-response' && text.includes('RTL9300#')) {
            state.state = 'media-command-returned-to-prompt';
            status();
          }
          tail = text.slice(-96);
        }
      }
    } catch (error) {
      if (!['EAGAIN', 'EWOULDBLOCK'].includes(error.code)) throw error;
    }

    if (state.state === 'waiting-for-media-command-response' && Date.now() >= commandDeadline) {
      state.state = 'media-command-timeout';
      state.error = 'No U-Boot prompt within 15 seconds of media command; no retry sent';
      fs.writeSync(log, Buffer.from(`\n[ERROR] ${state.error}\n`));
      console.error(state.error);
      status();
    }
    if (Date.now() - heartbeat >= 1000) {
      status();
      heartbeat = Date.now();
    }
    await delay(5);
  }
  if (state.state === 'waiting-for-autoboot-prompt' || state.state === 'escape-sent-waiting-for-uboot-prompt') {
    state.state = 'stopped-before-uboot-prompt';
  }
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
