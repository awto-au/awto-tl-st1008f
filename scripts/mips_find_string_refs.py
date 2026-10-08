#!/usr/bin/env python3
"""mips_find_string_refs — locate code/data references to strings in a raw MIPS32 BE image.

Ghidra's MIPS constant-reference analyzer misses lui/addiu pairs when the two
halves are far apart or the code was not disassembled. This scans a flat image:
- pointer words equal to the string VA (data tables),
- addiu/ori with the matching low16 immediate preceded (within --window insns)
  by a lui of the matching high16.

Usage:
    mips_find_string_refs.py <image.bin> <base_va_hex> "<string>" ["<string>" ...]
Prints: string VA, then each hit as VA + kind. Log: tmp/logs/mips_find_string_refs.log
"""

from __future__ import annotations

import argparse
import struct
import sys
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/mips_find_string_refs.log"


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def find_refs(img: bytes, base: int, va: int, window: int) -> list[tuple[int, str]]:
    hits: list[tuple[int, str]] = []
    # data pointers
    ptr = struct.pack(">I", va)
    i = img.find(ptr)
    while i != -1:
        if i % 4 == 0:
            hits.append((base + i, "ptr"))
        i = img.find(ptr, i + 1)
    lo = va & 0xFFFF
    hi = va >> 16
    if lo >= 0x8000:          # addiu sign-extends: lui gets hi+1
        hi_addiu = hi + 1
    else:
        hi_addiu = hi
    n = len(img) // 4
    words = struct.unpack(f">{n}I", img[: n * 4])
    for idx, w in enumerate(words):
        op = w >> 26
        imm = w & 0xFFFF
        if imm != lo:
            continue
        if op == 0x09:        # addiu
            want = hi_addiu
        elif op == 0x0D:      # ori
            want = hi
        else:
            continue
        rs = (w >> 21) & 0x1F
        for back in range(1, window + 1):
            if idx - back < 0:
                break
            p = words[idx - back]
            if (p >> 26) == 0x0F and ((p >> 16) & 0x1F) == rs and (p & 0xFFFF) == want:
                hits.append((base + idx * 4, "addiu" if op == 0x09 else "ori"))
                break
    return hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("base", type=lambda s: int(s, 16))
    ap.add_argument("strings", nargs="+")
    ap.add_argument("--window", type=int, default=64)
    args = ap.parse_args()
    img = Path(args.image).read_bytes()
    for s in args.strings:
        off = img.find(s.encode("latin1"))
        if off == -1:
            log(f'"{s}": NOT FOUND')
            continue
        va = args.base + off
        log(f'"{s}" @ 0x{va:08x}')
        for hva, kind in find_refs(img, args.base, va, args.window):
            log(f"  ref 0x{hva:08x} {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
