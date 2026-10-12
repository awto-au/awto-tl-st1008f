#!/usr/bin/env python3
"""power_boot — power the bench unit (sw2) via the relay and report how far it boots, from the console log.

- Checks the USB-serial adapter exists, restarts the console daemon (policy pass: no catch),
  relay on, then follows private/serial/st1008-console.log and reports each stage as it appears:
  stock banner, our U-Boot banner, Linux banner, userspace prompt.
- `--off-first`: relay off before on (a real power cycle). Log: tmp/logs/power_boot.log
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/power_boot.log"
CONSOLE = ROOT / "private/serial/st1008-console.log"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_CONSOLE  # noqa: E402
DEV = Path(BENCH_CONSOLE)
STAGES = [("stock U-Boot", "U-Boot 2011.12"), ("our U-Boot", "U-Boot 20"), ("Linux", "Linux version"),
          ("userspace", "Please press Enter")]
# Power-on -> userspace prompt ~35 s measured 2026-10-12 (sw1 via the chain); limit 45 s (x1.25, rounded)
BOOT_S = 45
POLL_S = 0.5  # log grows ~1 kB/s at 115200; 0.5 s keeps stage times to +-0.5 s


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def dev(*args: str) -> int:
    return subprocess.run([sys.executable, str(ROOT / "dev.py"), *args]).returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--off-first", action="store_true")
    a = ap.parse_args()
    if not DEV.exists():
        log(f"FAIL: serial adapter {DEV.name} not present (unplugged from the host?)")
        return 1
    if a.off_first and dev("power", "off"):
        return 1
    if dev("console-restart") or dev("power", "on"):
        return 1
    start, t0, seen = CONSOLE.stat().st_size, time.monotonic(), 0
    while time.monotonic() - t0 < BOOT_S and seen < len(STAGES):
        text = CONSOLE.read_bytes()[start:].decode("utf-8", "replace")
        while seen < len(STAGES) and STAGES[seen][1] in text:
            log(f"{STAGES[seen][0]} at {time.monotonic() - t0:.1f} s")
            seen += 1
        if "reopen failed" in text:
            log("FAIL: console daemon lost the adapter (reopen failed)")
            return 1
        time.sleep(POLL_S)
    tail = CONSOLE.read_bytes()[start:].decode("utf-8", "replace").strip().splitlines()[-15:]
    log("console tail:\n" + "\n".join(tail))
    if seen < len(STAGES):
        log(f"FAIL: reached {STAGES[seen - 1][0] if seen else 'nothing'} after {BOOT_S} s (limit)")
        return 1
    log("PASS: booted to userspace")
    return 0


if __name__ == "__main__":
    sys.exit(main())
