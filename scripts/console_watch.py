#!/usr/bin/env python3
"""console_watch — follow the switch console log live; flag error-looking lines as they arrive.

- Read-only: tails private/serial/st1008-console.log (written by switch_console_daemon.py).
- Lines matching boot_log_check DENY (panic, WARNING, fail, -Exxx, …) are shown red; an allowlisted
  `known #NN` (open defect) yellow; `benign #NN` (reviewed harmless) plain; daemon [TX] markers dim. Full verdict: ./dev.py check-log.
- Log: tmp/logs/console_watch.log (flagged lines only).
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import boot_log_check as blc  # noqa: E402

LOG = blc.ROOT / "tmp/logs/console_watch.log"
RED, YEL, DIM, OFF = "\033[31;1m", "\033[33m", "\033[2m", "\033[0m"
POLL_S = 0.2  # tail poll: console is ~1.1 kB/s at 115200; 200 ms keeps display lag below a line


def tagged(allow) -> list:
    """(pattern, reason, kind) of every entry that lets a DENY-word line pass (known or benign)."""
    return [(p, r, k) for rules in allow.values() for p, r, k in rules if k]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", type=Path, default=blc.DEFAULT_CONSOLE)
    ap.add_argument("--lines", type=int, default=200, help="history lines shown at start")
    a = ap.parse_args()
    known = tagged(blc.load_allow(blc.DEFAULT_ALLOW))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    out = LOG.open("a")

    def show(raw: str) -> None:
        text = blc.apply_bs(blc.KERNEL_TS.sub("", blc.DAEMON_TS.sub("", raw))).strip()
        if raw.startswith("[TX ") or raw.startswith("[daemon]"):
            print(f"{DIM}{raw}{OFF}")
        elif blc.DENY.search(text):
            hit = next(((r, k) for p, r, k in known if p.fullmatch(text)), None)
            if hit and hit[1] == "benign":  # reviewed harmless: only contains a DENY word
                print(raw)
                return
            print(f"{YEL}{raw}   <- {hit[0]}{OFF}" if hit else f"{RED}{raw}{OFF}")
            out.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {'KNOWN' if hit else 'FLAG'} {raw}\n")
            out.flush()
        else:
            print(raw)

    with a.log.open("r", errors="replace") as fh:
        hist = fh.readlines()[-a.lines:]
        for ln in hist:
            show(ln.rstrip("\n"))
        buf = ""
        while True:
            chunk = fh.read()
            if not chunk:
                if a.log.stat().st_size < fh.tell():  # log rotated/truncated: reopen from start
                    fh.seek(0)
                time.sleep(POLL_S)
                continue
            buf += chunk
            *lines, buf = buf.split("\n")
            for ln in lines:
                show(ln)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
