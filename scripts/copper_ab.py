#!/usr/bin/env python3
"""copper_ab — does U-Boot's module-PHY handling change the copper link Linux gets? (#178 A/B, sw2 lan2 / GLC-T)

One arm per run; each reboots sw2, then logs lan2's 88E1111 state at 30 s and 60 s Linux uptime.
- arm `quick`: sw2 reboots by ssh and U-Boot runs the M2 quick path (cage 1 only), autoboot to Linux.
- arm `full`: same reboot, ESC at the U-Boot window, then the FULL `rtk network on` (all cages, copper PHY init), then `boot`.
- Linux side per sample: uptime, lan2 carrier, PHY regs BMCR(0) BMSR(1) ANAR(4) LPA(5), first `lan2: Link is Up` time.
- Needs the console daemon (switch_console_daemon.py). Delays: waits only for sw2 (ssh up cap 200 s, console prompts).
- Log: tmp/logs/copper_ab.log

Usage: python3 scripts/copper_ab.py quick|full [--ip 192.168.25.56]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import st1008_ramload as rl  # noqa: E402

LOG = ROOT / "tmp/logs/copper_ab.log"
CONSOLE_LOG = ROOT / "logs/serial/st1008-console.log"
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
WINDOW_CAP_S = 60   # reboot ~5 s + U-Boot to the window ~5 s (quick path); x5 for a slow boot
UP_CAP_S = 200      # Linux boot to ssh ~60 s (sw2 first boots up to ~110 s)
SAMPLE_AT = (30, 60)
SAMPLE = r'''up=$(cut -d" " -f1 /proc/uptime); echo "uptime $up carrier=$(cat /sys/class/net/lan2/carrier)"
for r in 0 1 4 5; do printf "reg$r=%s " "$(phytool read lan2/0x16/$r)"; done; echo
dmesg | grep -E "lan2: Link is Up" | head -2 | cut -c1-90; dmesg | grep -c "lan2: Link is Down"'''


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, cap: float = 10) -> subprocess.CompletedProcess:
    return subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=cap)


def console_size() -> int:
    return CONSOLE_LOG.stat().st_size


def wait_console(pattern: bytes, since: int, cap: float) -> bool:
    t0 = time.monotonic()
    while time.monotonic() - t0 < cap:
        with CONSOLE_LOG.open("rb") as fh:
            fh.seek(since)
            if pattern in fh.read():
                return True
        time.sleep(0.05)  # poll the console log for the U-Boot window line
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("arm", choices=["quick", "full"])
    ap.add_argument("--ip", default="192.168.25.56")
    a = ap.parse_args()
    since = console_size()
    old_up = float(ssh(a.ip, "cut -d' ' -f1 /proc/uptime", 5).stdout.strip())  # the reboot is done when uptime drops below this
    log(f"== arm {a.arm}: reboot {a.ip} (uptime {old_up:.0f} s)")
    subprocess.Popen([*SSH, f"root@{a.ip}", "sync; reboot -f"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if a.arm == "full":
        if not wait_console(b"Autoboot in", since, WINDOW_CAP_S):
            log("FAIL: no 'Autoboot in' within the window cap")
            return 1
        subprocess.run([sys.executable, str(ROOT / "scripts/switch_console.py"), "esc"], capture_output=True, timeout=10)
        con = rl.Console()
        for cmd, cap in (("rtk network on", 30), ("boot", 15)):
            if cmd == "boot":
                subprocess.run([sys.executable, str(ROOT / "scripts/switch_console.py"), "send", "boot"], capture_output=True, timeout=cap)
            else:
                con.run(cmd, r"st1008f-mainline # ", cap, cmd, checked=True)
        log("full arm: ESC, full rtk network on, boot")
    # wait for Linux ssh
    t0 = time.monotonic()
    while time.monotonic() - t0 < UP_CAP_S:
        try:
            r = ssh(a.ip, "cut -d' ' -f1 /proc/uptime", 5)
            if r.returncode == 0 and r.stdout.strip() and float(r.stdout.strip()) < old_up:
                break
        except (subprocess.TimeoutExpired, ValueError):
            pass
        time.sleep(1)  # poll sw2 ssh while it boots
    else:
        log(f"FAIL: sw2 not reachable within {UP_CAP_S} s")
        return 1
    for target in SAMPLE_AT:
        while True:
            try:
                r = ssh(a.ip, "cut -d' ' -f1 /proc/uptime", 5)
                up = float(r.stdout.strip())
            except (subprocess.TimeoutExpired, ValueError):
                up = 0.0
            if up >= target:
                break
            time.sleep(1)  # wait for the Linux uptime of the sample point
        out = ssh(a.ip, SAMPLE, 15).stdout.strip()
        log(f"[{a.arm} @ >= {target} s]\n{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
