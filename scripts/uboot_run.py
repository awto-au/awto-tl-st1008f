#!/usr/bin/env python3
"""uboot_run — run U-Boot commands on sw2 once, then boot Linux again (one command, no hand-typed console steps).

- ssh sw2: request the one-shot netboot window (devmem 0x0e000014, #114) and reboot; works in M1 and M2.
- Waits for `Autoboot in` on the console log, sends ESC, runs each command at the `st1008f-mainline # ` prompt
  (echo-checked, `rtk network on quick` already done by the window), prints the output, then `boot`.
- Log: tmp/logs/uboot_run.log. Caps: window 60 s (reboot ~5 s + U-Boot ~5 s, x5), command 20 s, Linux ssh 200 s.

Usage: python3 scripts/uboot_run.py [--ip IP] [--stay] "rtk sfp 1" "rtk sfp 2" ...
  --stay  leave the unit at the U-Boot prompt (no `boot`).
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
from boards import BENCH_IP  # noqa: E402

LOG = ROOT / "tmp/logs/uboot_run.log"
CONSOLE_LOG = ROOT / "logs/serial/st1008-console.log"
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
WINDOW_CAP_S = 60
CMD_CAP_S = 20
UP_CAP_S = 200


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmds", nargs="+")
    ap.add_argument("--ip", default=BENCH_IP)
    ap.add_argument("--stay", action="store_true")
    a = ap.parse_args()
    since = CONSOLE_LOG.stat().st_size
    subprocess.Popen([*SSH, f"root@{a.ip}", "devmem 0x0e000014 32 0x4e575251; sync; reboot -f"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    log(f"reboot {a.ip} with the window requested")
    t0 = time.monotonic()
    while time.monotonic() - t0 < WINDOW_CAP_S:
        with CONSOLE_LOG.open("rb") as fh:
            fh.seek(since)
            if b"Autoboot in" in fh.read():
                break
        time.sleep(0.05)  # poll the console log for the U-Boot window line
    else:
        log(f"FAIL: no 'Autoboot in' within {WINDOW_CAP_S} s")
        return 1
    subprocess.run([sys.executable, str(ROOT / "scripts/switch_console.py"), "esc"], capture_output=True, timeout=10)
    con = rl.Console()
    for cmd in a.cmds:
        _, out = con.run(cmd, r"st1008f-mainline # ", CMD_CAP_S, cmd, checked=True)
        log(f"$ {cmd}\n{out.split(chr(10), 2)[-1].strip()}")
    if a.stay:
        return 0
    subprocess.run([sys.executable, str(ROOT / "scripts/switch_console.py"), "send", "boot"], capture_output=True, timeout=20)
    t0 = time.monotonic()
    while time.monotonic() - t0 < UP_CAP_S:
        r = subprocess.run([*SSH, f"root@{a.ip}", "true"], capture_output=True, timeout=8)
        if r.returncode == 0:
            log(f"Linux back after {time.monotonic() - t0:.0f} s")
            return 0
        time.sleep(1)  # poll sw2 ssh while it boots
    log(f"FAIL: sw2 not reachable within {UP_CAP_S} s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
