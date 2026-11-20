#!/usr/bin/env python3
"""port_sweep — light sw2 cages ONE at a time and log what each hears (cabling finder with a remote laser on).

- All listed ports admin down first, then per port: up (1000BASE-X autoneg on for the GLC-SX-MM ports), hold HOLD s
  sampling carrier + SerDes 1/29, 2/5 every STEP s, down again. Wall-clock start/end per port.
- One port lit at a time, so no cage loop is possible. Never touches lan1/lan2/lan7.
- lan8 (FS SFP-10G-T, copper): admin up only, carrier sampled (no SerDes read: map not verified).
- Log: tmp/logs/port_sweep.log. Caps: ssh 8 s per call; hold 8 s = US-48 cage_watch window (requested).

Usage: python3 scripts/port_sweep.py [--ports lan3,lan4,lan5,lan6,lan8] [--hold 8] [--step 1] [--start-in 10] [--ip IP]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/port_sweep.log"
SDS = {"lan3": 4, "lan4": 5, "lan5": 6, "lan6": 7}
ALLOWED = {"lan3", "lan4", "lan5", "lan6", "lan8"}
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str) -> str:
    return subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=8).stdout.strip()


def sample(ip: str, p: str) -> str:
    cmd = f'echo "carrier=$(cat /sys/class/net/{p}/carrier 2>/dev/null)"'
    if p in SDS:
        s = SDS[p]
        cmd = (f'echo "carrier=$(cat /sys/class/net/{p}/carrier 2>/dev/null) 1/29=$(st1008f-sds rd {s} 1 29 | sed "s/.*= //")'
               f' 2/5=$(st1008f-sds rd {s} 2 5 | sed "s/.*= //")"')
    return ssh(ip, cmd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ports", default="lan3,lan4,lan5,lan6,lan8")
    ap.add_argument("--hold", type=float, default=8)
    ap.add_argument("--step", type=float, default=1)
    ap.add_argument("--start-in", type=float, default=0, help="seconds to wait before the first port")
    ap.add_argument("--ip", default="192.168.25.56")
    a = ap.parse_args()
    ports = a.ports.split(",")
    bad = set(ports) - ALLOWED
    if bad:
        sys.exit(f"FAIL: refusing ports {sorted(bad)} (allowed {sorted(ALLOWED)})")
    ssh(a.ip, "; ".join(f"ip link set {p} down" for p in ports))
    log(f"all down: {','.join(ports)}; first port in {a.start_in:.0f} s")
    time.sleep(a.start_in)  # US-48 asked for the first port 10 s after their start message
    for p in ports:
        ssh(a.ip, f"ip link set {p} up" + (f"; ethtool -s {p} autoneg on" if p in SDS else ""))
        log(f"{p} START")
        t0 = time.monotonic()
        while time.monotonic() - t0 < a.hold:
            log(f"{p} {sample(a.ip, p)}")
            time.sleep(a.step)  # sampling period
        ssh(a.ip, f"ip link set {p} down")
        log(f"{p} END")
    return 0


if __name__ == "__main__":
    sys.exit(main())
