#!/usr/bin/env python3
"""flash_speed_step — SPI-NOR clock ladder at the mainline prompt (#32): SFCR divider, integrity, speed.

- SFCR 0xb8001200 bits 31:29 = D -> SPI clock = NOR clock 153.125 MHz / (2 x (D + 1)); stock D = 2 (/6).
- Baseline: whole-chip `crc32 0xb4000000 0x2000000` at the stock divider. Each step: write D (other
  bits kept), whole-chip CRC must equal the baseline, then `bench` flash lines. Mismatch -> stock D
  restored and the ladder stops. A hang -> power cycle (`./dev.py ramload uboot-mainline`).
- Read-only on the flash. W25Q256JV rating: FAST_READ 133 MHz, READ 03h 50 MHz (sources/README.md).
- Log: tmp/logs/flash_speed_step.log
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/flash_speed_step.log"
PROMPT = r"\r?\nst1008f-mainline # "
SFCR = 0xB8001200
NOR_MHZ = 153.125
STOCK_D = 2
CHIP = 0x2000000


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sfcr(con: Console) -> int:
    _, out = con.run(f"md.l {SFCR:x} 1", r"b8001200: ([0-9a-f]{8})" + PROMPT, 1, "SFCR")
    return int(re.search(r"b8001200: ([0-9a-f]{8})", out).group(1), 16)


def set_d(con: Console, base: int, d: int) -> None:
    con.run(f"mw.l {SFCR:x} {(base & 0x1fffffff) | (d << 29):08x}", PROMPT, 1, f"SFCR D={d}")


def chip_crc(con: Console, d: int) -> str:
    # 32 MiB at the SPI clock, 1 bit/clock + command overhead; stock /6 measured 16.6 s (~2 MB/s).
    # Expected = 16.6 s x (d + 1) / 3; x1.25 + 1 s poll slack.
    cap = 16.6 * (d + 1) / 3 * 1.25 + 1
    _, out = con.run(f"crc32 b4000000 {CHIP:x}", r"==> ([0-9a-f]{8})" + PROMPT, cap, f"chip CRC D={d}")
    return re.search(r"==> ([0-9a-f]{8})", out).group(1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("divs", nargs="*", type=int, default=[1, 0], help="D values to try, in order")
    a = ap.parse_args()
    con = Console()
    base = sfcr(con)
    if (base >> 29) != STOCK_D:
        log(f"FAIL: SFCR {base:#010x} D={base >> 29}, expected stock D={STOCK_D}; power cycle first")
        return 1
    t = time.monotonic()
    ref = chip_crc(con, STOCK_D)
    log(f"baseline D={STOCK_D} ({NOR_MHZ / 6:.1f} MHz): CRC {ref} in {time.monotonic() - t:.1f}s")
    for d in a.divs:
        set_d(con, base, d)
        t = time.monotonic()
        try:
            got = chip_crc(con, d)
        except SystemExit as e:
            log(f"FAIL D={d}: {str(e)[:160]} (hang? power cycle)")
            return 1
        dt = time.monotonic() - t
        mhz = NOR_MHZ / (2 * (d + 1))
        if got != ref:
            set_d(con, base, STOCK_D)
            log(f"FAIL D={d} ({mhz:.1f} MHz): CRC {got} != {ref}; stock D restored")
            return 1
        _, out = con.run("bench", r"bench flash_c [\d.]+ MB/s" + PROMPT, 10, "bench")
        fl = dict(re.findall(r"^bench (flash_\w+) ([\d.]+) MB/s", out, re.M))
        log(f"PASS D={d} ({mhz:.1f} MHz): chip CRC ok in {dt:.1f}s ({CHIP / dt / 1e6:.2f} MB/s); "
            f"bench flash_uc {fl.get('flash_uc')} flash_c {fl.get('flash_c')} MB/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
