#!/usr/bin/env python3
"""spi_linux_ladder — fastest SPI-NOR clock Linux reads correctly (#50). Read-only on the flash.

- Per step: `ramload uboot-mainline --then openwrt --spi D:CODE` (our U-Boot sets SFCR D / NOR code,
  then bootm's the RAM OpenWrt: no flash filesystem mounted, nothing written), then at the shell
  `md5sum /dev/mtdblockN` of the 29 MiB `firmware` partition through Linux's SPI driver.
- First step = stock SPI (baseline md5). Each later step must match; the ladder stops at the first
  mismatch. Time per read = Linux flash throughput. Log: tmp/logs/spi_linux_ladder.log
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import OW_PROMPT, ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/spi_linux_ladder.log"
PART_MIB = 29  # firmware partition 0x1d00000
STEPS = ["2:6", "1:6", "0:6", "0:5", "0:4", "0:3"]  # 25.5, 38.3, 76.6, 87.5, 102.1, 122.5 MHz


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def mhz(step: str) -> float:
    d, code = (int(x) for x in step.split(":"))
    return 2450 / (2 * (code + 2)) / (2 * (d + 1))


def read_firmware(con: Console) -> tuple[str, float]:
    con.run("dmesg -n 1", OW_PROMPT, 1, "quiet", checked=True)
    n = re.search(r'mtd(\d+): \S+ \S+ "firmware"', con.run("cat /proc/mtd", OW_PROMPT, 2, "mtd")[1]).group(1)
    t = time.monotonic()
    # 29 MiB through PIO SPI: ~1 MB/s worst case at stock 25.5 MHz = 30 s; x1.25 + boot noise
    _, out = con.run(f"md5sum /dev/mtdblock{n}", r"\n([0-9a-f]{32})\s" + r"[\s\S]*?" + OW_PROMPT, 45, "md5")
    return re.search(r"\n([0-9a-f]{32})\s", out).group(1), time.monotonic() - t


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("steps", nargs="*", default=STEPS, help="D:CODE, first = baseline")
    a = ap.parse_args()
    ref = None
    for step in a.steps:
        # a harness failure (console glitch, e.g. a garbled tftp size line) gets one retry; an md5 mismatch none
        for attempt in (1, 2):
            r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "uboot-mainline",
                                "--then", "openwrt", "--spi", step], timeout=180)  # boot ~70 s; x2.5 slack
            try:
                h, dt = read_firmware(Console())
                break
            except SystemExit as e:
                log(f"{'RETRY' if attempt == 1 else 'FAIL'} {step} ({mhz(step):.1f} MHz): boot rc "
                    f"{r.returncode}, {str(e)[:160]}")
        else:
            return 1
        rate = PART_MIB * 1.048576 / dt
        if ref is None:
            ref = h
            log(f"baseline {step} ({mhz(step):.1f} MHz): md5 {h}, {dt:.1f}s ({rate:.2f} MB/s)")
            continue
        ok = h == ref
        log(f"{'PASS' if ok else 'FAIL'} {step} ({mhz(step):.1f} MHz): md5 {h}{'' if ok else ' != ' + ref}, "
            f"{dt:.1f}s ({rate:.2f} MB/s)")
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
