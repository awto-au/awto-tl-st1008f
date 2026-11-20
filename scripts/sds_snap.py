#!/usr/bin/env python3
"""sds_snap — read-only SerDes/optics snapshots of one switch port at given local times (sw1 lan6 / SerDes 7 default).

- Waits (host sleep, bounded) until each HH:MM:SS local time, then one ssh: carrier, DDM rx power, SerDes 10GR PCS
  link (5/0 twice), latched block lock (5/1), latched RX link (4/1), RX equaliser (rxeq), `SerDes N` kernel lines.
- Reads only unless --invert (below). Note: 5/1 and 4/1 are latched-on-read registers (clear on read, docs/SDS-TOOLS.md).
- Waiting for a peer's agreed time slot is the only delay; a time in the past is sampled immediately; cap 10 min total.
- Log: tmp/logs/sds_snap.log

- `--invert SET RESTORE` (local times): sets the 10GR RX polarity-invert bit (6/2 bit 13, Linux config_polarity
  CFG_INV_HSI) at SET and writes the ORIGINAL 6/2 value back at RESTORE (also in a finally on any error).
  Write on the SerDes of an unused port only (sw1 lan6, 2026-11-20 US-48 xe51 test).

Usage: python3 scripts/sds_snap.py 22:18:45 22:19:15 [--ip 192.168.25.48] [--lan lan6] [--sds 7] [--invert SET RESTORE]
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


def ssh(ip: str, cmd: str) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise SystemExit(f"FAIL ssh {cmd[:50]!r}: rc {r.returncode} {r.stderr.strip()[:200]}")
    return r.stdout


def rd62(ip: str, sds: str) -> int:
    out = ssh(ip, f"st1008f-sds rd {sds} 6 2")
    return int(out.strip().split("=")[-1].strip(), 16)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("times", nargs="+", help="local HH:MM:SS")
    ap.add_argument("--ip", default="192.168.25.48")
    ap.add_argument("--lan", default="lan6")
    ap.add_argument("--sds", default="7")
    ap.add_argument("--invert", nargs=2, metavar=("SET", "RESTORE"), help="RX polarity invert window (writes 6/2)")
    a = ap.parse_args()
    events = [(t, "snap") for t in a.times]
    orig = None
    if a.invert:
        events += [(a.invert[0], "set"), (a.invert[1], "restore")]
    events.sort(key=lambda e: [int(x) for x in e[0].split(":")])
    try:
        for hms, kind in events:
            wait_until(hms)
            if kind == "set":
                orig = rd62(a.ip, a.sds)
                ssh(a.ip, f"st1008f-sds wr {a.sds} 6 2 0x{orig | (1 << 13):x}")
                log(f"== {hms} SerDes {a.sds} 6/2: {orig:#06x} -> {orig | (1 << 13):#06x} (RX invert ON)")
            elif kind == "restore":
                if orig is not None:
                    ssh(a.ip, f"st1008f-sds wr {a.sds} 6 2 0x{orig:x}")
                    log(f"== {hms} SerDes {a.sds} 6/2 restored to {orig:#06x} (readback {rd62(a.ip, a.sds):#06x})")
                    orig = None
            else:
                r = subprocess.run([*SSH, f"root@{a.ip}", CMD.format(lan=a.lan, sds=a.sds)], capture_output=True, text=True, timeout=30)
                log(f"== snapshot {hms} {a.ip} {a.lan} SerDes {a.sds} (rc {r.returncode})\n{r.stdout.strip()}\n{r.stderr.strip()}")
    finally:
        if orig is not None:  # restore on any error path
            ssh(a.ip, f"st1008f-sds wr {a.sds} 6 2 0x{orig:x}")
            log(f"== SerDes {a.sds} 6/2 restored to {orig:#06x} (finally)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
