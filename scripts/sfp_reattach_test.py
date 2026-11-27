#!/usr/bin/env python3
"""sfp_reattach_test — does the copper module PHY lose its config after a long TX-disable? (#178, kernel fix analysis)

Reproduces what a warm reboot does to a copper SFP without rebooting: the netdev goes down (kernel asserts TX-disable),
stays down for HOLD s, comes up (TX-disable released, PHY probed and configured by phylib), then the PHY's BMCR/BMSR
are polled for WATCH s with a 0.1 s step and every change is logged with its time since `up`. The kernel SFP state
machine's own messages (dynamic debug on sfp.c) are collected for the same window.
- Reads the PHY through the raw MDIO bus (`mdio smbus:sfp-pN phy 0x16`), so it works before the netdev PHY attaches.
- Touches only the named port (sw2 lan2 by default = the sw1<->sw2 routed test link). Dynamic debug is switched back off.
- Log: tmp/logs/sfp_reattach_test.log

Usage: python3 scripts/sfp_reattach_test.py [--hold 15] [--watch 12] [--lan lan2] [--bus smbus:sfp-p2] [--ip IP]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sfp_reattach_test.log"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
POLL = r'''t0=$(cut -d" " -f1 /proc/uptime); last=""; i=0
while [ $i -lt {n} ]; do
  u=$(cut -d" " -f1 /proc/uptime); b=$(mdio {bus} phy 0x16 0 2>&1 | head -1); s=$(mdio {bus} phy 0x16 1 2>&1 | head -1)
  cur="bmcr=$b bmsr=$s"
  if [ "$cur" != "$last" ]; then echo "+$(echo "$u $t0" | awk '{{printf "%.2f", $1-$2}}')s $cur"; last="$cur"; fi
  i=$((i+1))
done'''


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, cap: float = 60) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=cap)
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hold", type=float, default=15, help="seconds the netdev stays down (TX-disable asserted)")
    ap.add_argument("--watch", type=float, default=12, help="seconds of PHY polling after up")
    ap.add_argument("--lan", default="lan2")
    ap.add_argument("--bus", default="smbus:sfp-p2")
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    ctl = "/sys/kernel/debug/dynamic_debug/control"
    ssh(a.ip, f"echo 'file sfp.c +p' > {ctl}; echo 'file sfp-bus.c +p' > {ctl}; dmesg -c >/dev/null")
    ssh(a.ip, f"ip link set {a.lan} down")
    log(f"{a.lan} down, hold {a.hold:.0f} s")
    time.sleep(a.hold)  # the variable under test: how long TX-disable stays asserted
    out = ssh(a.ip, f"ip link set {a.lan} up; " + POLL.format(n=int(a.watch * 8), bus=a.bus), a.watch * 3 + 30)
    log(f"after up ({a.watch:.0f} s):\n{out.strip()}")
    dm = ssh(a.ip, "dmesg | grep -E 'sfp|lan2|phy' | cut -c1-140 | head -40")
    log(f"kernel:\n{dm.strip()}")
    ssh(a.ip, f"echo 'file sfp.c -p' > {ctl}; echo 'file sfp-bus.c -p' > {ctl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
