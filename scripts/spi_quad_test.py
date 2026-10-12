#!/usr/bin/env python3
"""spi_quad_test — read-only quad test of the SPI-NOR mmio window at our U-Boot prompt (#61).

- SFCR2 0xb8001204 sets the window read op (layout: docs/CLOCKS.md § Controller modes). Stock: Dual I/O 0xBB.
- Per mode: write SFCR2, whole-chip `crc32 b4000000 2000000` (uncached window), `bench` flash lines,
  then stock SFCR2 back. PASS for a mode = CRC equal to the Dual I/O reference.
- Dummy field = 2-clock units (Realtek SDK flash_spi.c): 0xEB = 2 mode + 4 dummy clocks -> 3;
  0x6B = 8 dummy clocks -> 4. W25Q256JVFIQ: QE fixed 1, so no status-register write.
- Needs `./dev.py ramload uboot-mainline` first. A hang -> power cycle. Log: tmp/logs/spi_quad_test.log
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from bench import BENCH_CAP  # noqa: E402
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/spi_quad_test.log"
PROMPT = r"\r?\nst1008f-mainline # "
SFCR2 = 0xB8001204
STOCK = 0xBBC14A00  # Dual I/O, size 6, addr x2, dummy 2 (4 clk), data x2, 4-byte address
CHIP = 0x2000000


def sfcr2(cmd: int, addr_io: int, dummy: int, data_io: int) -> int:
    """cmd_io x1; addr/data io code 0 x1, 1 x2, 2 x4; keep size 6 and 4-byte address bit 9."""
    return cmd << 24 | 6 << 21 | addr_io << 16 | dummy << 13 | data_io << 11 | 1 << 9


MODES = {
    "dual-io-bb": STOCK,
    "quad-out-6b": sfcr2(0x6B, 0, 4, 2),
    "quad-io-eb": sfcr2(0xEB, 2, 3, 2),
}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run_mode(con: Console, name: str, val: int) -> tuple[str, float, dict]:
    con.run(f"mw.l {SFCR2:x} {val:08x}", PROMPT, 1, f"SFCR2 {name}")
    _, out = con.run(f"md.l {SFCR2:x} 1", r"b8001204: [0-9a-f]{8}[^\n]*" + PROMPT, 1, "SFCR2 readback")
    rb = re.search(r"b8001204: ([0-9a-f]{8})", out).group(1)
    # whole chip at 25.5 MHz Dual I/O measured 16.6 s; quad <= that; x1.25 + 1 s poll slack
    t0 = time.monotonic()
    _, out = con.run(f"crc32 b4000000 {CHIP:x}", r"==> ([0-9a-f]{8})" + PROMPT, 16.6 * 1.25 + 1, f"chip CRC {name}")
    secs = time.monotonic() - t0
    crc = re.search(r"==> ([0-9a-f]{8})", out).group(1)
    _, out = con.run("bench", r"bench flash_c [\d.]+ MB/s[^\n]*" + PROMPT, BENCH_CAP, f"bench {name}")
    fl = {k: float(v) for k, v in re.findall(r"bench (flash_u?c) ([\d.]+) MB/s", out)}
    log(f"{name}: SFCR2 {rb}, chip CRC {crc} in {secs:.1f} s (host-timed, {CHIP / secs / 1e6:.2f} MB/s), "
        f"bench {fl}")
    return crc, secs, fl


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("modes", nargs="*", default=["quad-out-6b", "quad-io-eb"], choices=list(MODES)[1:])
    a = ap.parse_args()
    con = Console()
    con.run("", PROMPT, 2, "our prompt")
    _, out = con.run(f"md.l {SFCR2:x} 1", r"b8001204: [0-9a-f]{8}[^\n]*" + PROMPT, 1, "SFCR2")
    orig = int(re.search(r"b8001204: ([0-9a-f]{8})", out).group(1), 16)
    if orig != STOCK:
        log(f"FAIL: SFCR2 {orig:08x} != stock {STOCK:08x}; not touching it")
        return 1
    res = {}
    try:
        ref, _, _ = run_mode(con, "dual-io-bb", STOCK)
        for m in a.modes:
            res[m] = run_mode(con, m, MODES[m])[0] == ref
    finally:
        con.run(f"mw.l {SFCR2:x} {orig:08x}", PROMPT, 1, "SFCR2 restore")
        _, out = con.run(f"crc32 b4000000 {CHIP:x}", r"==> ([0-9a-f]{8})" + PROMPT, 16.6 * 1.25 + 1, "CRC after restore")
    back = re.search(r"==> ([0-9a-f]{8})", out).group(1)
    log(f"restored SFCR2 {orig:08x}, chip CRC {back} ({'= ref' if back == ref else 'MISMATCH'})")
    for m, ok in res.items():
        log(f"{m}: {'PASS (CRC = Dual I/O)' if ok else 'FAIL (CRC differs)'}")
    return 0 if all(res.values()) and back == ref else 1


if __name__ == "__main__":
    sys.exit(main())
