#!/usr/bin/env python3
"""console_stats — timings mined from the console log of the boots normal work produces (no test loops).

    python3 scripts/console_stats.py reboot [--last N]   # Linux `reboot` sent -> stock U-Boot banner, s

- reboot: from the daemon's `[TX hh:mm:ss] 'reboot\\r'` marker to the next stock banner, timed by the
  first daemon timestamp after the banner (`[TX hh:mm:ss] <policy> ...` or `[daemon] ... <ISO time>`);
  resolution 1 s. Reboots where the flow gave up and power-cycled (a `[daemon] open` before the banner)
  are counted separately: their banner times the relay, not the reboot. Sizes restart_board's SOFT_S (scripts/st1008_ramload.py).
- Log: tmp/logs/console_stats.log
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/console_stats.log"
CONSOLE = ROOT / "private/serial/st1008-console.log"
TX = re.compile(r"^\[TX (\d\d:\d\d:\d\d)\]")
DAEMON_T = re.compile(r"^\[daemon\] .* (\d{4}-\d\d-\d\dT(\d\d:\d\d:\d\d))")
STOCK = "U-Boot 2011.12"
WINDOW = 400  # lines after a reboot to look for the banner: a reboot prints ~60-150 lines before it


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def secs(hms: str) -> int:
    t = datetime.strptime(hms, "%H:%M:%S")
    return t.hour * 3600 + t.minute * 60 + t.second


def reboot_times(lines: list[str]) -> tuple[list[int], int]:
    out, cut = [], 0
    for i, ln in enumerate(lines):
        m = TX.match(ln)
        if not m or "'reboot\\\\r'" not in ln and "'reboot -f\\\\r'" not in ln:
            continue
        t0 = secs(m[1])
        banner = None
        for j in range(i + 1, min(i + WINDOW, len(lines))):
            if STOCK in lines[j]:
                banner = j
                break
            if "relay" in lines[j] or lines[j].startswith("[daemon] open"):
                break  # the flow restarted the daemon for a relay power cycle: not a software reboot
        if banner is None:
            cut += 1
            continue
        for k in range(banner, min(banner + 60, len(lines))):
            t = TX.match(lines[k]) or DAEMON_T.match(lines[k])
            if t:
                dt = secs(t[1] if TX.match(lines[k]) else t[2]) - t0
                out.append(dt % 86400)
                break
    return out, cut


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("metric", choices=["reboot"])
    ap.add_argument("--last", type=int, default=0, help="only the last N reboots")
    a = ap.parse_args()
    lines = CONSOLE.read_text(errors="replace").splitlines()
    v, cut = reboot_times(lines)
    if a.last:
        v = v[-a.last:]
    if not v:
        log("reboot: no timed reboots in the console log")
        return 1
    s = sorted(v)
    log(f"reboot -> stock banner (+<=1 s to the next daemon stamp): n {len(s)}, min {s[0]} s, "
        f"median {s[len(s) // 2]} s, max {s[-1]} s; last 10: {v[-10:]}; no banner before a relay: {cut}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
