#!/usr/bin/env python3
"""flash_openwrt_watch — boot the FLASH OpenWrt as an unattended power-up would, and watch it (#43).

- Power cycle → stock prompt (autoboot caught, NO `rtk network on`, no laser mask) → `boota`.
- At the shell: every --every s log uptime (a drop = reboot), bridge stp_state, lan* STP port
  states, SoC temperature. Run `./dev.py storm-watch` alongside: it is the kill switch.
- Log: tmp/logs/flash_openwrt_watch.log
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import OW_PROMPT, ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/flash_openwrt_watch.log"
STATE = {"0": "disabled", "1": "listening", "2": "learning", "3": "forwarding", "4": "blocking"}
PORTS = "grep . /sys/class/net/lan*/brport/state"  # < 60 chars: no echo-check path
TEMP = "cat /sys/class/thermal/thermal_zone0/temp"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--minutes", type=float, default=10)
    ap.add_argument("--every", type=float, default=30, help="sample period, s")
    ap.add_argument("--attach", action="store_true", help="flash OpenWrt already running: just sample")
    a = ap.parse_args()
    if a.attach:
        return watch(Console(), a)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "stock", "--no-network"],
                       timeout=30)  # relay + daemon restart + banner ~6 s; 30 s names a hang
    if r.returncode:
        return r.returncode
    con = Console()
    t0 = time.monotonic()
    # "Please press Enter": RAM initramfs ~25 s; flash adds squashfs + overlay mount and was
    # reported slow: cap 120 s, expiry logged by expect
    con.run("boota", r"Please press Enter to activate", 120, "flash OpenWrt booted")
    log(f"flash OpenWrt console up after {time.monotonic() - t0:.0f}s")
    con.run("", OW_PROMPT, 3, "shell")
    return watch(con, a)


def watch(con: Console, a: argparse.Namespace) -> int:
    con.run("dmesg -n 1", OW_PROMPT, 1, "console loglevel 1")
    end = time.monotonic() + a.minutes * 60
    last_up = 0.0
    while time.monotonic() < end:
        try:
            _, up = con.run("cat /proc/uptime", r"\n([\d.]+) [\d.]+\r?\n" + OW_PROMPT, 2, "uptime")
            _, stp = con.run("cat /sys/class/net/switch/bridge/stp_state", OW_PROMPT, 2, "stp")
            _, ports = con.run(PORTS, OW_PROMPT, 2, "port states")
            _, temp = con.run(TEMP, r"\n(\d+)\r?\n" + OW_PROMPT, 2, "temp")
        except SystemExit as e:  # no shell: rebooted or hung
            log(f"NO SHELL: {str(e)[:200]}")
            time.sleep(a.every)
            continue
        u = float(re.search(r"\n([\d.]+) ", up).group(1))
        st = re.findall(r"/sys/class/net/(lan\d)/brport/state:(\d)", ports)
        stp_v = re.search(r"\n([0-2])\r?\n", stp)
        t = int(re.search(r"\n(\d+)\r?\n", temp).group(1)) / 1000
        log(f"up {u:.0f}s{' (REBOOTED)' if u < last_up else ''} stp_state "
            f"{stp_v.group(1) if stp_v else '?'} temp {t:.0f}C ports "
            + " ".join(f"{p}={STATE.get(s, s)}" for p, s in st))
        last_up = u
        time.sleep(a.every)  # sample period (argument); console is otherwise idle
    return 0


if __name__ == "__main__":
    sys.exit(main())
