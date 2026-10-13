#!/usr/bin/env python3
"""sram_alias_probe — does the on-chip SRAM window hide high DRAM after the zone-3 remap? (#107)

- Power-cycle + `ramload uboot-mainline --stock-clocks`, `highmem map` (zone-3 remap: Linux phys
  0x20000000.. = DRAM 0x10000000..; window 0xc0000000 uncached), then UMSAR0/SRAMSAR0 = --bus
  (64 KiB, PLR values, as kernel 300-21); `--no-unmap`: SRAM segment only, UMSAR0 stays 0.
- Write a marker to SRAM (KSEG1 of --bus) and a different one to the high-DRAM word at Linux phys
  0x20000000 + (--bus - 0x10000000); read both back. Alias = the high-DRAM write shows in SRAM
  (or the SRAM write in high DRAM): the unmap segment matches the DRAM-side address.
- Also writes the words just below and just above the window in high DRAM (must stay DRAM).
- A hang on the high-DRAM write inside the window = collision (2026-10-13, bus 0x1f000000: hang).
- Log: tmp/logs/sram_alias_probe.log
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/sram_alias_probe.log"
PROMPT = r"\r?\nst1008f-mainline # "
BOOT_S = 120  # power cycle + network on + TFTP ~25 s; x1.25 + relay retries (clocks_cycle.py)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def md(con: Console, addr: int) -> int:
    _, out = con.run(f"md.l {addr:x} 1", rf"{addr:08x}: ([0-9a-f]{{8}})[^\n]*" + PROMPT, 1, f"md {addr:x}")
    return int(re.search(rf"{addr:08x}: ([0-9a-f]{{8}})", out)[1], 16)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bus", type=lambda s: int(s, 0), default=0x1F000000, help="SRAM window bus address")
    ap.add_argument("--no-boot", action="store_true")
    ap.add_argument("--no-unmap", action="store_true",
                    help="SRAM segment only (size, base, then addr+enable); UMSAR0 left 0 (#107 option 1)")
    a = ap.parse_args()
    if not a.no_boot:
        r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "uboot-mainline",
                            "--stock-clocks"], capture_output=True, text=True, timeout=BOOT_S)
        if r.returncode not in (0, 1):
            log(f"FAIL boot: {(r.stdout + r.stderr).strip().splitlines()[-1:]}")
            return 2
    con = Console()
    con.run("", PROMPT, 2, "our prompt")
    con.run("highmem map", r"highmem: \d+ MiB[^\n]*" + PROMPT, 1, "highmem map")
    seq = [(0xB8004004, 9), (0xB8004008, 0x00030000), (0xB8004000, a.bus | 1)]  # enable last
    if not a.no_unmap:
        seq = [(0xB8001300, a.bus | 1), (0xB8001304, 9)] + seq
    for reg, val in seq:
        con.run(f"mw.l {reg:x} {val:x}", PROMPT, 1, f"mw {reg:x}")
    sram = 0xA0000000 | a.bus
    high = 0xC0000000 + (a.bus - 0x10000000)  # Linux phys 0x20000000 + off -> window 0xc0000000 + off
    for off in (-4, 0x10000):  # just outside the 64 KiB window: must stay plain DRAM
        con.run(f"mw.l {high + off:x} 3c3c{off & 0xffff:04x}", PROMPT, 1, f"high DRAM {off:+#x}")
        v = md(con, high + off)
        log(f"high DRAM {high + off:#010x}: {v:08x} ({'ok' if v == 0x3C3C0000 | off & 0xFFFF else 'WRONG'})")
    con.run(f"mw.l {sram:x} 5a5a1111", PROMPT, 1, "sram marker")
    try:  # one mw at the prompt: echo + prompt in ~ms; 1 s names a bus hang
        con.run(f"mw.l {high:x} a5a52222", PROMPT, 1, "high-DRAM marker")
    except SystemExit:
        log(f"bus {a.bus:#010x}: write to high DRAM {high:#010x} hangs the CPU -> COLLISION "
            f"(unmap/SRAM segment matches DRAM {a.bus:#010x}, = Linux phys {a.bus + 0x10000000:#010x})")
        return 1
    s, h = md(con, sram), md(con, high)
    alias = s == 0xA5A52222 or h == 0x5A5A1111
    log(f"bus {a.bus:#010x}: SRAM {sram:#010x} reads {s:08x} (wrote 5a5a1111), high DRAM {high:#010x} "
        f"reads {h:08x} (wrote a5a52222) -> {'ALIAS' if alias else 'separate'}")
    return 1 if alias else 0


if __name__ == "__main__":
    sys.exit(main())
