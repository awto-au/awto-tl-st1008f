#!/usr/bin/env python3
"""link_bounce — failure rate of 10G link bring-up on sw2 (#116): bounce a cage pair N times over SSH.

- Default pair lan7 + lan8 (sw2 fibre loop 7 <-> 8, out of the bridge by linkcheck): never touches the
  mgmt uplink or the house switch. Per round: both down, both up, poll carrier every 0.1 s on the
  board (BusyBox usleep absent: a tight read loop with a 10 s cap), record the time each comes up.
- A round where a port has no carrier after the cap = a failed bring-up (the #116 symptom).
- Log: tmp/logs/link_bounce.log
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/link_bounce.log"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
UP_CAP_S = 10   # 10G SR bring-up: SerDes config + RX calibration ~1-2 s per port (dmesg); x5
DOWN_S = 1      # both ports down before the next up: partner sees loss of light
ROUND = r'''
a={A}; b={B}; ip link set $a down; ip link set $b down; sleep {DOWN}
t0=$(cut -d' ' -f1 /proc/uptime); ip link set $a up; ip link set $b up; ta=""; tb=""
while :; do t=$(cut -d' ' -f1 /proc/uptime)
  [ -z "$ta" ] && [ "$(cat /sys/class/net/$a/carrier 2>/dev/null)" = 1 ] && ta=$t
  [ -z "$tb" ] && [ "$(cat /sys/class/net/$b/carrier 2>/dev/null)" = 1 ] && tb=$t
  [ -n "$ta" ] && [ -n "$tb" ] && break
  [ $(echo "$t $t0" | awk '{{print ($1-$2 > {CAP})}}') = 1 ] && break
done
echo "R $t0 ${{ta:--}} ${{tb:--}}"
'''


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP)
    ap.add_argument("--pair", nargs=2, default=["lan7", "lan8"])
    ap.add_argument("--rounds", type=int, default=20)
    a = ap.parse_args()
    if "lan1" in a.pair:
        log("FAIL: lan1 is the mgmt uplink (to sw1): refused")
        return 2
    cmd = ROUND.format(A=a.pair[0], B=a.pair[1], DOWN=DOWN_S, CAP=UP_CAP_S)
    fails, times = 0, []
    for i in range(1, a.rounds + 1):
        r = subprocess.run([*SSH, f"root@{a.ip}", cmd], capture_output=True, text=True, timeout=UP_CAP_S + DOWN_S + 15)
        m = re.search(r"R ([\d.]+) (\S+) (\S+)", r.stdout)
        if not m:
            log(f"round {i}: no result ({r.stderr.strip()[:120]})")
            fails += 1
            continue
        t0 = float(m[1])
        res = [f"{float(x) - t0:.1f}" if x != "-" else "FAIL" for x in (m[2], m[3])]
        fails += res.count("FAIL") > 0
        times += [float(x) for x in res if x != "FAIL"]
        log(f"round {i}: {a.pair[0]} {res[0]} s, {a.pair[1]} {res[1]} s")
    rng = f"{min(times):.1f}-{max(times):.1f} s" if times else "-"
    log(f"result: {fails}/{a.rounds} rounds with a port not up in {UP_CAP_S} s; link-up {rng}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
