#!/usr/bin/env python3
"""bounce — take one sw2 port down, hold, bring it up, report carrier time (default sw2-lan2).

- Linux admin down/up over SSH; the kernel SFP code asserts TX-disable on down.
- No per-module power rail exists (3.3 V SFP rail unswitched, #30), so this is the deepest bounce.
- GLC-T ignores TX-disable (docs/hardware.md); GLC-T-TX PHY needs it released to answer (#178).
- Refuses lan1 (mgmt uplink to sw1). Log: tmp/logs/bounce.log

Usage: python3 scripts/bounce.py [lan2] [--ip IP]
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
LOG = ROOT / "tmp/logs/bounce.log"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
DOWN_S = 2     # hold down: partner PHY must see link loss (>1 s link_fail_inhibit) and the module settle
UP_CAP_S = 15  # module init + PHY probe ~2 s + 1G copper autoneg 3-5 s, x3; expiry = FAIL logged
UP = r'''
p={P}; t0=$(cut -d' ' -f1 /proc/uptime); ip link set $p up
while :; do t=$(cut -d' ' -f1 /proc/uptime)
  [ "$(cat /sys/class/net/$p/carrier 2>/dev/null)" = 1 ] && break
  [ $(echo "$t $t0" | awk '{{print ($1-$2 > {CAP})}}') = 1 ] && {{ echo "R FAIL $(echo "$t $t0" | awk '{{print $1-$2}}')"; exit 0; }}
done
echo "R OK $(echo "$t $t0" | awk '{{print $1-$2}}') $(cat /sys/class/net/$p/speed)"
'''


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, cap: float) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=cap)
    if r.returncode:
        raise RuntimeError(f"ssh rc={r.returncode}: {r.stderr.strip()[:120]}")
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("port", nargs="?", default="lan2")
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    port = a.port.removeprefix("sw2-")
    if not re.fullmatch(r"lan[1-8]", port):
        log(f"FAIL: {a.port}: expected lan1..lan8")
        return 2
    if port == "lan1":
        log("FAIL: sw2-lan1 is the mgmt uplink (to sw1): refused")
        return 2
    try:
        ssh(a.ip, f"ip link set {port} down", 10)
        log(f"sw2-{port}: down, hold {DOWN_S} s (partner must see link loss)")
        time.sleep(DOWN_S)
        out = ssh(a.ip, UP.format(P=port, CAP=UP_CAP_S), UP_CAP_S + 10)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        log(f"FAIL: sw2-{port}: {e}")
        return 1
    m = re.search(r"R (OK|FAIL) ([\d.]+)(?: (\S+))?", out)
    if not m:
        log(f"FAIL: sw2-{port}: no result: {out.strip()[:120]}")
        return 1
    if m[1] == "OK":
        log(f"OK: sw2-{port} carrier after {float(m[2]):.1f} s, {m[3]} Mb/s")
        return 0
    log(f"FAIL: sw2-{port} no carrier within {UP_CAP_S} s (waited {float(m[2]):.1f} s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
