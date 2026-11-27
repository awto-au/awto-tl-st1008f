#!/usr/bin/env python3
"""port_sample — timed sampling of sw2 ports: carrier, RX/TX packets+bytes, ParserErrors, MacDiscards, SerDes 1/29 + 2/5.

- One ssh per sample; a line is printed and logged for every sample (wall-clock ISO 8601 with offset).
- Read-only: touches no port state. Port -> SerDes map from the lanN list: lan3=4, lan4=5, lan5=6, lan6=7.
- Log: tmp/logs/port_sample.log. Caps: ssh 8 s per sample (one ssh = 3 ethtool/sds reads, ~1 s).

Usage: python3 scripts/port_sample.py [--ports lan4,lan5] [--every 2] [--for 60] [--ip IP]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/port_sample.log"
SDS = {"lan3": 4, "lan4": 5, "lan5": 6, "lan6": 7}
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
CMD = (r'''n={n}; s={s}; d=/sys/class/net/$n/statistics
echo "$n c=$(cat /sys/class/net/$n/carrier 2>/dev/null) rx=$(cat $d/rx_packets)/$(cat $d/rx_bytes)B tx=$(cat $d/tx_packets)/$(cat $d/tx_bytes)B'''
       r''' $(ethtool -S $n | grep -E "ParserErrors|rx_MacDiscards" | tr -d " " | tr "\n" " ")'''
       r''' 1/29=$(st1008f-sds rd $s 1 29 | sed "s/.*= //") 2/5=$(st1008f-sds rd $s 2 5 | sed "s/.*= //")"''')


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ports", default="lan4,lan5")
    ap.add_argument("--every", type=float, default=2)
    ap.add_argument("--for", dest="dur", type=float, default=60)
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    ports = a.ports.split(",")
    t_end = time.monotonic() + a.dur
    while time.monotonic() < t_end:
        t0 = time.monotonic()
        for p in ports:
            r = subprocess.run([*SSH, f"root@{a.ip}", CMD.format(n=p, s=SDS[p])], capture_output=True, text=True, timeout=8)
            log(r.stdout.strip() or f"{p} FAIL: {r.stderr.strip()}")
        time.sleep(max(0.0, a.every - (time.monotonic() - t0)))  # fixed sampling period
    return 0


if __name__ == "__main__":
    sys.exit(main())
