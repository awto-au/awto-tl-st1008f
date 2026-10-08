import fs from 'node:fs';
import { setTimeout as delay } from 'node:timers/promises';

// Historical helper (Node), kept as used 2026-10-07/08; new tooling is Python. See scripts/README.md.
// Run from the repo root. SERIAL_PORT=/dev/serial/by-id/<adapter> is required.
function requiredEnv(name) {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} in the environment (see scripts/README.md)`);
  return value;
}

const port = requiredEnv('SERIAL_PORT');
const fd = fs.openSync(port, fs.constants.O_RDWR | fs.constants.O_NOCTTY | fs.constants.O_NONBLOCK);
const inspect = process.argv[2] === '--inspect-phy';
const initTest = process.argv[2] === '--init-test';
const helpOnly = process.argv[2] === '--help-only';
const log = fs.openSync(inspect
  ? 'private/serial/tx-completion-20261007.log'
  : helpOnly ? 'private/serial/rtk-help-20261007.log'
  : initTest ? 'private/serial/init-ping-test-20261007.log'
  : 'private/serial/nic-ping-test-20261007.log', 'wx');
async function command(text) {
  fs.writeSync(log, `\n[TX] ${text}\n`);
  const data = Buffer.from(text + '\r');
  if (fs.writeSync(fd, data) !== data.length) throw new Error('Incomplete serial write');
  const buffer = Buffer.alloc(8192);
  let response = '';
  const start = Date.now();
  while (Date.now() - start < 60000) {
    try {
      const n = fs.readSync(fd, buffer, 0, buffer.length, null);
      if (n) {
        fs.writeSync(log, buffer, 0, n);
        response += buffer.subarray(0, n).toString('ascii');
        if (/\r?\nRTL9300#(?: #)? $/.test(response)) {
          console.log(response);
          return response;
        }
      }
    } catch (error) {
      if (!['EAGAIN', 'EWOULDBLOCK'].includes(error.code)) throw error;
    }
    await delay(10);
  }
  throw new Error(`Serial timeout: ${text}`);
}
let changed = false;
try {
  const env = await command('printenv');
  for (const line of ['ipaddr=192.168.0.100', 'serverip=192.168.0.145', 'ethact=rtl9300#0']) {
    if (!env.split(/\r?\n/).includes(line)) throw new Error(`Environment precondition failed: ${line}`);
  }
  if (helpOnly) {
    await command('help rtk');
  } else if (inspect) {
    await command('md.l 83ff21e0 4d');
    await command('md.l 83ff84f8 4');
    await command('md.l 83df008c 30');
    await command('md.l 83fc2750 10');
    await command('md.l 83fc27e0 4');
    await command('md.l 83fa1dc4 4');
    await command('md.l 83fa3638 8');
    await command('md.l 83e63a60 10');
    await command('md.l 83df3230 10');
    await command('md.l 83df31b0 10');
    await command('md.l 83df3340 8');
    await command('md.l 83df3338 8');
    await command('md.l a3df4078 10');
    await command('md.l a3df7250 30');
  } else {
    if (initTest) {
      await command('rtk init');
      await command('rtk network on');
    }
    changed = true;
    await command(`setenv ipaddr ${requiredEnv('SWITCH_IP')}`);
    await command(`setenv serverip ${requiredEnv('HOST_IP')}`);
    await command('printenv');
    await command('md.l 83fc2750 4');
    await command(`ping ${requiredEnv('HOST_IP')}`);
    await command('md.l 83fc2750 4');
  }
} finally {
  try {
    if (changed) {
      await command('setenv ipaddr 192.168.0.100');
      await command('setenv serverip 192.168.0.145');
      const env = await command('printenv');
      if (!env.includes('ipaddr=192.168.0.100\r\n') ||
          !env.includes('serverip=192.168.0.145\r\n')) {
        throw new Error('Environment restoration verification failed');
      }
    }
  } finally {
    fs.closeSync(fd);
    fs.closeSync(log);
  }
}
