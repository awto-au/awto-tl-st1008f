#!/usr/bin/env python3
"""sds_snap — read-only SerDes/optics snapshots of one switch port at given local times (sw1 lan6 / SerDes 7 default).

- Waits (host sleep, bounded) until each HH:MM:SS local time, then one ssh: carrier, DDM rx power, SerDes 10GR PCS
  link (5/0 twice), latched block lock (5/1), latched RX link (4/1), RX equaliser (rxeq), `SerDes N` kernel lines.
- Reads only. Note: 5/1 and 4/1 are latched-on-read registers (clear on read, docs/SDS-TOOLS.md).
- Waiting for a peer's agreed time slot is the only delay; a time in the past is sampled immediately; cap 10 min total.
- Log: tmp/logs/sds_snap.log

Usage: python3 scripts/sds_snap.py 22:18:45 22:19:15 [--ip 192.168.25.48] [--lan lan6] [--sds 7]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sds_snap.log"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
CAP_S = 600  # a peer's slot is minutes away; longer = a typo in the time
CMD = r'''date +%T; echo "carrier=$(cat /sys/class/net/{lan}/carrier) oper=$(cat /sys/class/net/{lan}/operstate)"
ethtool -m {lan} | grep -E "Receiver signal|Laser output power  "
for i in 1 2; do echo "pcs_link(5/0)=$(st1008f-sds rd {sds} 5 0)"; done
echo "blocklock_latched(5/1)=$(st1008f-sds rd {sds} 5 1) rxlink_latched(4/1)=$(st1008f-sds rd {sds} 4 1)"
st1008f-sds rxeq {sds} 2>&1 | head -4
dmesg | grep "SerDes {sds}" | tail -4 | cut -c1-150'''


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def wait_until(hms: str) -> None:
    h, m, s = (int(x) for x in hms.split(":"))
    now = time.localtime()
    target = time.mktime((now.tm_year, now.tm_mon, now.tm_mday, h, m, s, 0, 0, -1))
    delay = target - time.time()
    if delay > CAP_S:
        sys.exit(f"FAIL: {hms} is {delay:.0f} s away (cap {CAP_S} s)")
    if delay > 0:
        time.sleep(delay)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("times", nargs="+", help="local HH:MM:SS")
    ap.add_argument("--ip", default="192.168.25.48")
    ap.add_argument("--lan", default="lan6")
    ap.add_argument("--sds", default="7")
    a = ap.parse_args()
    for hms in a.times:
        wait_until(hms)
        r = subprocess.run([*SSH, f"root@{a.ip}", CMD.format(lan=a.lan, sds=a.sds)], capture_output=True, text=True, timeout=30)
        log(f"== snapshot {hms} {a.ip} {a.lan} SerDes {a.sds} (rc {r.returncode})\n{r.stdout.strip()}\n{r.stderr.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
