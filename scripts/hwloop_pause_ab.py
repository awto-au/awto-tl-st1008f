#!/usr/bin/env python3
"""hwloop_pause_ab — does 802.3x pause on the 10G path stop the lan1 ingress drops in the line-rate loop test? (#182, owner OK 2026-11-21)

- Per round and mode: set pause on sw1 lan4, sw1 lan5 and sw2 lan1 (`ethtool -A rx/tx on|off`), then
  `iperf_hwloop.py --only tcp-bidir` (unpaced TCP both directions: the case that loses frames at 10G -> 1G).
- The host NIC (enp8s0) already has RX/TX pause on; it is not changed.
- Always restores pause off on the three ports (finally); the original state is printed first.
- Output lines of each run (rates, retransmits, load, counter deltas) go to tmp/logs/hwloop_pause_ab.log.
- Caps: one hwloop run = setup + DUR 8 s + teardown; measured ~45 s, cap 150 s (the script's own WATCHDOG_S) per run.

Usage: python3 scripts/hwloop_pause_ab.py [--rounds 3] [--sw1 IP] [--sw2 IP]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/hwloop_pause_ab.log"
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-o", "LogLevel=ERROR"]
RUN_CAP_S = 150


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=20)
    return (r.stdout + r.stderr).strip()


def set_pause(ports: list[tuple[str, str]], on: bool) -> None:
    v = "on" if on else "off"
    for ip, lan in ports:
        out = ssh(ip, f"ethtool -A {lan} rx {v} tx {v} 2>&1; ethtool -a {lan} | tail -2 | tr '\\n\\t' '  '")
        log(f"  pause {v}: {ip} {lan}: {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--sw1", default="192.168.25.48")
    ap.add_argument("--sw2", default="192.168.25.56")
    a = ap.parse_args()
    ports = [(a.sw1, "lan4"), (a.sw1, "lan5"), (a.sw2, "lan1")]
    for ip, lan in ports:
        log(f"original {ip} {lan}: " + ssh(ip, f"ethtool -a {lan} | tail -2 | tr '\\n\\t' '  '"))
    try:
        for rnd in range(1, a.rounds + 1):
            for on in (False, True):
                set_pause(ports, on)
                log(f"round {rnd} pause {'ON' if on else 'off'}: hwloop tcp-bidir")
                r = subprocess.run([sys.executable, str(ROOT / "scripts/iperf_hwloop.py"), "--only", "tcp-bidir", "--dur", "8"],
                                   capture_output=True, text=True, timeout=RUN_CAP_S)
                for ln in r.stdout.splitlines():
                    if "tcp-bidir" in ln or "counter deltas" in ln or "ABORT" in ln:
                        log(f"  [{'ON' if on else 'off'} r{rnd}] {ln.split(' ', 1)[-1][:300]}")
                if r.returncode:
                    log(f"  hwloop rc {r.returncode}: {r.stderr.strip()[-200:]}")
    finally:
        set_pause(ports, False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
