#!/usr/bin/env python3
"""storm_watch — detect a broadcast storm on a host NIC and cut the switch's power relay.

- Started automatically by ./dev.py (`--guard`, singleton) for every hardware command; exits 10 min
  after the last dev.py. Agents never start it by hand.
- Samples rx_multicast_packets + rx_broadcast_packets every 1 s via the ethtool ioctl (no subprocess).
- Baseline = mean rate over the first 3 s (switch must not be storming yet).
- Trip: rate > max(--abs-pps, 20 x baseline) on 2 consecutive samples → kill: console takes every
  lan* port down, then relay off retried until it confirms. Unicast (iperf) is ignored.
- `--observe`: log the storm but only cut after --hold seconds (to prove/measure one).
- Exits after --duration s (bounded) or on trip. Log: tmp/logs/storm_watch.log
"""

import argparse
import array
import fcntl
import os
import socket
import struct
import urllib.request
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/storm_watch.log"
SAMPLE_S = 1.0  # 2 samples over the limit = 2 s; a loop here ramps over tens of seconds (#19)
BASELINE_S = 3.0
RELAY = "http://192.168.25.138/switch/relay"  # same relay as scripts/switch_power.py


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


class NicStats:
    """rx bcast+mcast via the ETHTOOL_GSTATS ioctl (no subprocess); sysfs 'multicast' omits
    broadcast on mlx4_en, so it can't see a broadcast storm."""

    GSSET_INFO, GSTRINGS, GSTATS, SS_STATS, SIOCETHTOOL = 0x37, 0x1B, 0x1D, 1, 0x8946
    WANT = ("rx_multicast_packets", "rx_broadcast_packets")

    def __init__(self, nic: str):
        self.nic, self.sock = nic.encode(), socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        info = bytearray(struct.pack("IIQI", self.GSSET_INFO, 0, 1 << self.SS_STATS, 0))
        self._ioctl(info)
        self.n = struct.unpack_from("I", info, 16)[0]
        names = bytearray(struct.pack("III", self.GSTRINGS, self.SS_STATS, self.n) + bytes(32 * self.n))
        self._ioctl(names)
        keys = [names[12 + 32 * i:44 + 32 * i].split(b"\0")[0].decode() for i in range(self.n)]
        self.idx = [keys.index(k) for k in self.WANT]

    def _ioctl(self, buf: bytearray) -> None:
        ptr = array.array("B", buf)
        ifr = struct.pack("16sP", self.nic, ptr.buffer_info()[0])
        fcntl.ioctl(self.sock.fileno(), self.SIOCETHTOOL, ifr)
        buf[:] = ptr.tobytes()

    def read(self) -> int:
        buf = bytearray(struct.pack("II", self.GSTATS, self.n) + bytes(8 * self.n))
        self._ioctl(buf)
        vals = struct.unpack_from(f"{self.n}Q", buf, 8)
        return sum(vals[i] for i in self.idx)


KILL_PORTS = "for p in /sys/class/net/lan*; do ip link set ${p##*/} down; done"
RELAY_TRY_S = 0.5  # relay answers in ~0.12 s on a quiet LAN; caps one try while the LAN floods
RELAY_TRIES = 120  # 1 min of retries; the console kill has normally stopped forwarding by then


def kill() -> bool:
    """Console first (local USB, immune to the LAN storm), then the relay until it confirms.
    2026-10-10: one relay POST timed out in the storm and nothing retried (#19)."""
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        from st1008_ramload import Console
        Console().send(KILL_PORTS)  # no-op unless an OpenWrt shell is at the prompt
        log("KILL console: lan* down sent")
    except Exception as e:  # noqa: BLE001  daemon down must not stop the relay path
        log(f"KILL console failed: {e}")
    req = urllib.request.Request(f"{RELAY}/turn_off", method="POST")
    for i in range(1, RELAY_TRIES + 1):
        t = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=RELAY_TRY_S) as r:
                log(f"KILL relay off: HTTP {r.status} on try {i}")
                return True
        except Exception as e:  # noqa: BLE001  any network error -> retry
            log(f"KILL relay try {i}/{RELAY_TRIES} failed after {time.monotonic() - t:.2f}s: {e}")
            time.sleep(max(0.0, RELAY_TRY_S - (time.monotonic() - t)))
    log(f"KILL relay FAILED {RELAY_TRIES} tries: cut switch power by hand")
    return False


GUARD_LOCK = ROOT / "tmp/storm_guard.lock"
GUARD_IDLE_S = 600  # keep watching 10 min after the last dev.py exits (board may still forward)


def devpy_running() -> bool:
    """Any ./dev.py process alive? /proc scan, cheap at the 10 s guard check rate."""
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if b"dev.py" in Path(f"/proc/{pid}/cmdline").read_bytes():
                    return True
            except OSError:
                continue
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--nic", default="enp7s0")
    ap.add_argument("--abs-pps", type=int, default=2_000,
                    help="trip floor; house-LAN bcast+mcast idles ~5-10 pps; a loop through the "
                         "RTL930x ramps slowly (13k pps at +80 s), so 50k missed it")
    ap.add_argument("--duration", type=float, default=900, help="watch window, seconds")
    ap.add_argument("--observe", action="store_true", help="measure the storm before cutting")
    ap.add_argument("--hold", type=float, default=3.0, help="--observe: seconds of storm before cut")
    ap.add_argument("--guard", action="store_true",
                    help="singleton started by dev.py; runs until 10 min after the last dev.py exits")
    a = ap.parse_args()

    if a.guard:  # one guard at a time: hold an exclusive lock for our lifetime
        GUARD_LOCK.parent.mkdir(parents=True, exist_ok=True)
        lock = GUARD_LOCK.open("w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0
    stats = NicStats(a.nic)
    log(f"=== start nic={a.nic} abs={a.abs_pps} {'guard' if a.guard else f'duration={a.duration}s'} "
        f"observe={a.observe}")
    t0 = time.monotonic()
    prev, prev_t = stats.read(), t0
    rates: list[float] = []
    while time.monotonic() - t0 < BASELINE_S:
        time.sleep(SAMPLE_S)
        cur, now = stats.read(), time.monotonic()
        rates.append((cur - prev) / (now - prev_t))
        prev, prev_t = cur, now
    base = sum(rates) / len(rates)
    limit = max(a.abs_pps, 20 * base)
    log(f"baseline {base:.0f} pps -> trip at {limit:.0f} pps; ARMED")

    over, storm_start, peak, pps = 0, None, 0.0, 0.0
    last_busy, next_check = time.monotonic(), 0.0
    while a.guard or time.monotonic() - t0 < a.duration:
        time.sleep(SAMPLE_S)
        if a.guard and time.monotonic() >= next_check:
            next_check = time.monotonic() + 10
            if devpy_running():
                last_busy = time.monotonic()
            elif time.monotonic() - last_busy > GUARD_IDLE_S:
                log(f"=== guard idle {GUARD_IDLE_S}s after last dev.py, no storm (last {pps:.0f} pps)")
                return 0
        cur, now = stats.read(), time.monotonic()
        pps = (cur - prev) / (now - prev_t)
        prev, prev_t = cur, now
        over = over + 1 if pps > limit else 0
        if over == 1:
            log(f"high bcast+mcast {pps:.0f} pps")
        if over >= 2:
            peak = max(peak, pps)
            storm_start = storm_start or now
            if not a.observe or now - storm_start >= a.hold:
                log(f"STORM: {pps:.0f} pps (peak {peak:.0f}), {now - storm_start:.1f}s over limit")
                kill()
                return 2
    log(f"=== end, no storm in {a.duration:.0f}s (last {pps:.0f} pps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
