#!/usr/bin/env python3
"""sfp_firstattach_capture — warm-reboot sw2 with phylink/phy/sfp dynamic debug on from early boot, then dump the copper module PHY (#178).

- Installs a temporary /etc/init.d/zz_dyndbg (START=02) on sw2: enables dyndbg for phylink.c, phy.c, phy_device.c, marvell.c, sfp.c, sfp-bus.c.
  Netdev attach happens ~20 s after boot (netifd), later than the init script, so the first attach is captured.
- `reboot` (software), waits for ssh, then collects dmesg + module PHY regs 0/1/4/5/0x1b + `ethtool lan2`. Removes the init script afterwards.
- Wait = ping -W 1 paced loop; cap 120 s (sw2 boot to ssh ~25 s, x1.25 + U-Boot chain 2 s window = ~40 s; 3x measured backstop).
- Output: tmp/logs/sfp_firstattach.log, tmp/logs/sfp_firstattach.dmesg. sw2 only; warn the US-48 session before running (lan7 drops).

Usage: python3 scripts/sfp_firstattach_capture.py [--ip IP] [--bus smbus:sfp-p2] [--lan lan2]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sfp_firstattach.log"
DMESG = ROOT / "tmp/logs/sfp_firstattach.dmesg"
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
INIT = """#!/bin/sh /etc/rc.common
START=02
start() {
	ctl=/sys/kernel/debug/dynamic_debug/control
	for f in phylink.c phy.c phy_device.c marvell.c sfp.c sfp-bus.c; do echo "file $f +p" > $ctl; done
}
"""
REGS = "for r in 0 1 4 5 0x1b; do echo reg $r $(mdio {bus} phy 0x16 raw $r 2>&1 | head -1); done"
BOOT_CAP_S = 120


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, cap: float = 30) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=cap)
    return r.stdout + r.stderr


def alive(ip: str) -> bool:
    return subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True).returncode == 0


def wait(ip: str, up: bool, cap: float) -> float | None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < cap:
        if alive(ip) == up:
            return time.monotonic() - t0  # ping -W 1 paces the loop
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("--bus", default="smbus:sfp-p2")
    ap.add_argument("--lan", default="lan2")
    a = ap.parse_args()
    ssh(a.ip, f"cat > /etc/init.d/zz_dyndbg <<'EOF'\n{INIT}EOF\nchmod +x /etc/init.d/zz_dyndbg; /etc/init.d/zz_dyndbg enable")
    log("installed zz_dyndbg; rebooting sw2 (software)")
    ssh(a.ip, "reboot")
    if wait(a.ip, False, 20) is None:
        log("FAIL sw2 did not go down in 20 s")
        return 1
    t = wait(a.ip, True, BOOT_CAP_S)
    if t is None:
        log(f"FAIL sw2 not back in {BOOT_CAP_S} s")
        return 1
    log(f"sw2 answers ping {t:.0f} s after going down")
    ssh(a.ip, "true", 15)
    dm = ssh(a.ip, "dmesg", 30)
    DMESG.write_text(dm)
    log("kernel lines saved: " + str(DMESG))
    log("module PHY:\n" + ssh(a.ip, REGS.format(bus=a.bus)).strip())
    log(f"ethtool {a.lan}: " + " | ".join(ln.strip() for ln in ssh(a.ip, f"ethtool {a.lan}").splitlines() if "Link detected" in ln or "Speed" in ln))
    ssh(a.ip, "/etc/init.d/zz_dyndbg disable; rm -f /etc/init.d/zz_dyndbg")
    log("removed zz_dyndbg")
    return 0


if __name__ == "__main__":
    sys.exit(main())
