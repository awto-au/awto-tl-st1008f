#!/usr/bin/env python3
"""storm_watch — detect a broadcast storm on a host NIC and cut the switch's power relay.

- Samples `ethtool -S <nic>` rx_multicast_packets + rx_broadcast_packets every 0.5 s.
- Baseline = mean rate over the first 3 s (switch must not be storming yet).
- Trip: rate > max(--abs-pps, 20 x baseline) on 2 consecutive samples → kill: console takes every
  lan* port down, then relay off retried until it confirms. Unicast (iperf) is ignored.
- `--observe`: log the storm but only cut after --hold seconds (to prove/measure one).
- Exits after --duration s (bounded) or on trip. Log: tmp/logs/storm_watch.log
"""

import argparse
import subprocess
import urllib.request
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/storm_watch.log"
SAMPLE_S = 0.5  # detection latency ≈ 2 samples = 1 s
BASELINE_S = 3.0
RELAY = "http://192.168.25.138/switch/relay"  # same relay as scripts/switch_power.py


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def bcast_mcast(nic: str) -> int:
    out = subprocess.run(["ethtool", "-S", nic], capture_output=True, text=True,
                         timeout=2).stdout  # ethtool is local + instant; 2 s names a hang
    tot = 0
    for line in out.splitlines():
        k, _, v = line.strip().partition(":")
        if k in ("rx_multicast_packets", "rx_broadcast_packets"):
            tot += int(v)
    return tot


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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--nic", default="enp7s0")
    ap.add_argument("--abs-pps", type=int, default=2_000,
                    help="trip floor; house-LAN bcast+mcast idles ~5-10 pps; a loop through the "
                         "RTL930x ramps slowly (13k pps at +80 s), so 50k missed it")
    ap.add_argument("--duration", type=float, default=900, help="watch window, seconds")
    ap.add_argument("--observe", action="store_true", help="measure the storm before cutting")
    ap.add_argument("--hold", type=float, default=3.0, help="--observe: seconds of storm before cut")
    a = ap.parse_args()

    log(f"=== start nic={a.nic} abs={a.abs_pps} duration={a.duration}s observe={a.observe}")
    t0 = time.monotonic()
    prev, prev_t = bcast_mcast(a.nic), t0
    rates: list[float] = []
    while time.monotonic() - t0 < BASELINE_S:
        time.sleep(SAMPLE_S)
        cur, now = bcast_mcast(a.nic), time.monotonic()
        rates.append((cur - prev) / (now - prev_t))
        prev, prev_t = cur, now
    base = sum(rates) / len(rates)
    limit = max(a.abs_pps, 20 * base)
    log(f"baseline {base:.0f} pps -> trip at {limit:.0f} pps; ARMED")

    over, storm_start, peak = 0, None, 0.0
    while time.monotonic() - t0 < a.duration:
        time.sleep(SAMPLE_S)
        cur, now = bcast_mcast(a.nic), time.monotonic()
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
