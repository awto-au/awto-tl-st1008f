#!/usr/bin/env python3
"""st1008_uboot_funcmap — name TL-ST1008F stock U-Boot (loader.bin) functions by
aligning against the reyalo dms1250 reference (System.map + u-boot ELF).

No hardware. Read-only static analysis.

Two independent alignment methods (they cross-check each other):
  string-xref  a function is anchored in BOTH builds by a byte-identical lui/addiu
               (or ori, or data-pointer) load of the SAME string; backscan to the
               `addiu sp,sp,-X` prologue = function start in each build.
  content-match take the reference function's bytes, mask the low-16 of every
               address-bearing insn (lui/addiu/ori/lw/sw/branch) and the target of
               j/jal (these are relocated and differ build-to-build), and search our
               text for the masked signature. Robust for functions TP-Link did not
               edit; fails (by design) on the few it customised (rtk_network_on).

Address maps (both verified against known prologues):
  ours     VA = file_off - 0x5080 + 0x83f00000   (loader.bin main text @ file 0x5080)
  dms1250  .dram ELF section @ file 0x5040, VA 0x83f00000, size 0xbedd8; carries the
           full named symbol table at the SAME relocated VA as System.map.

The build offset is REGION-DEPENDENT (TP-Link inserted/removed code): e.g. main_loop
-0x3c4, do_rtk +0x4a8, rtk_network_on -0x1d88, sds cluster ~-0x85f0. So a map address
is NOT convertible by a single constant; each target is resolved on its own anchor.

Usage:
  st1008_uboot_funcmap.py align              # alignment anchors (string-xref)
  st1008_uboot_funcmap.py resolve NAME...    # map symbol -> our VA (content-match)
Inputs: ST1008_LOADER (default private/stock-loader-20261007/loader.bin),
        REALTEK_SRC (default private/reyalo-Realtek/sources).
Log: tmp/logs/st1008_uboot_funcmap.log
"""
from __future__ import annotations

import argparse
import bisect
import os
import re
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OURS = Path(os.environ.get("ST1008_LOADER", ROOT / "private/stock-loader-20261007/loader.bin"))
# Clone of github.com/reyalo/Realtek; override with REALTEK_SRC=<clone>/sources.
REF_DIR = Path(os.environ.get("REALTEK_SRC", ROOT / "private/reyalo-Realtek/sources")) / "uboot-dms1250"
REF_ELF = REF_DIR / "u-boot"
REF_MAP = REF_DIR / "System.map"
LOG = ROOT / "tmp/logs/st1008_uboot_funcmap.log"

BASE = 0x83F00000
OUR_FOFF = 0x5080
REF_DRAM_FOFF = 0x5040
REF_DRAM_SIZE = 0xBEDD8
ADDIU_SP = 0x27BD0000


def log(msg: str = "") -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{msg}\n")


def load() -> tuple[bytes, bytes]:
    ours = OURS.read_bytes()[OUR_FOFF:]
    ref = REF_ELF.read_bytes()[REF_DRAM_FOFF:REF_DRAM_FOFF + REF_DRAM_SIZE]
    return ours, ref


def words(buf: bytes) -> tuple[int, ...]:
    n = len(buf) // 4
    return struct.unpack(f">{n}I", buf[: n * 4])


def mask_insn(w: int) -> int:
    op = w >> 26
    if op in (0x02, 0x03):              # j / jal -> opcode only
        return w & 0xFC000000
    if op in (0x0F, 0x09, 0x0D, 0x23, 0x2B, 0x24, 0x25, 0x28, 0x29, 0x08, 0x0C,
              0x04, 0x05, 0x01, 0x06, 0x07):   # addr-imm ops + branches -> drop imm16
        return w & 0xFFFF0000
    return w


def prologue_back(ws: tuple[int, ...], va: int, max_back: int = 8000) -> int | None:
    i = (va - BASE) // 4
    for b in range(max_back):
        j = i - b
        if j < 0:
            return None
        w = ws[j]
        if (w & 0xFFFF0000) == ADDIU_SP and (w & 0x8000):
            return BASE + j * 4
    return None


def xref(ws: tuple[int, ...], str_va: int, win: int = 160) -> list[int]:
    lo = str_va & 0xFFFF
    hi = str_va >> 16
    ha = hi + 1 if lo >= 0x8000 else hi
    out: list[int] = []
    for i, w in enumerate(ws):
        if (w & 0xFFFF) != lo:
            continue
        op = w >> 26
        want = ha if op == 0x09 else (hi if op == 0x0D else None)
        if want is None:
            continue
        rs = (w >> 21) & 0x1F
        for b in range(1, win + 1):
            if i - b < 0:
                break
            p = ws[i - b]
            if (p >> 26) == 0x0F and ((p >> 16) & 0x1F) == rs and (p & 0xFFFF) == want:
                out.append(BASE + i * 4)
                break
    pk = struct.pack(">I", str_va)
    for i, w in enumerate(ws):
        if struct.pack(">I", w) == pk:
            out.append(BASE + i * 4)
    return out


def elf_syms() -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    r = subprocess.run(["readelf", "-sW", str(REF_ELF)], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        p = line.split()
        if len(p) >= 8 and p[3] == "FUNC":
            try:
                out[p[7]] = (int(p[1], 16), int(p[2]))
            except ValueError:
                pass
    return out


def map_syms() -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for line in REF_MAP.read_text().splitlines():
        m = re.match(r"^([0-9a-f]{8}) ([TtWw]) (\S+)", line)
        if m:
            a = int(m.group(1), 16)
            if BASE <= a < BASE + REF_DRAM_SIZE:
                out.append((a, m.group(3)))
    out.sort()
    return out


PROBE_STRINGS = [
    "Please wait for PHY init-time",
    "hw_profile_list",
    "Forbid to erase LOADER partition",
    "RTL9300# ",
]


def do_align(_args) -> None:
    ours_b, ref_b = load()
    ow, rw = words(ours_b), words(ref_b)
    syms = map_syms()
    log(f"# alignment anchors  {time.strftime('%Y-%m-%dT%H:%M:%S%z')}")
    log(f"{'string':34} {'our_fn':>10} {'map_fn':>10} {'off':>8}  map_name")
    for s in PROBE_STRINGS:
        oo = OURS.read_bytes().find(s.encode())
        ro = ref_b.find(s.encode())
        if oo < 0 or ro < 0:
            log(f"{s[:33]:34} MISS our={oo >= 0} ref={ro >= 0}")
            continue
        osva = oo - OUR_FOFF + BASE
        rsva = BASE + ro
        ox, rx = xref(ow, osva), xref(rw, rsva)
        if not ox or not rx:
            log(f"{s[:33]:34} no-xref our={len(ox)} ref={len(rx)}")
            continue
        of, rf = prologue_back(ow, ox[0]), prologue_back(rw, rx[0])
        if of is None or rf is None:
            continue
        k = bisect.bisect_right([a for a, _ in syms], rf) - 1
        name = syms[k][1] if k >= 0 else "?"
        exact = "=" if k >= 0 and syms[k][0] == rf else "~"
        log(f"{s[:33]:34} 0x{of:08x} 0x{rf:08x} {rf - of:+8d}  {exact}{name}")


def content_match(name: str, esyms: dict, ow: tuple, rw: tuple) -> int | None:
    if name not in esyms:
        return None
    a, sz = esyms[name]
    nword = sz // 4
    skip = 2
    win = min(24, max(4, nword - skip - 1))
    ri = (a - BASE) // 4
    seg = [mask_insn(w) for w in rw[ri + skip: ri + skip + win]]
    L = len(seg)
    for i in range(len(ow) - L):
        if ow[i] == seg[0] and ow[i + 1] == seg[1] and \
                [mask_insn(w) for w in ow[i:i + L]] == seg:
            return prologue_back(tuple(ow), i * 4 + BASE) or (i * 4 + BASE - skip * 4)
    return None


def do_resolve(args) -> None:
    ours_b, ref_b = load()
    ow = tuple(mask_insn(w) for w in words(ours_b))
    rw = words(ref_b)
    esyms = elf_syms()
    log(f"# resolve  {time.strftime('%Y-%m-%dT%H:%M:%S%z')}")
    for name in args.names:
        r = content_match(name, esyms, ow, rw)
        mapva = esyms.get(name, (None, None))[0]
        mp = f"0x{mapva:08x}" if mapva else "not-in-ELF"
        rv = f"0x{r:08x}" if r else "NO-MATCH"
        log(f"{name:40} map {mp} -> our {rv}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("align")
    rp = sub.add_parser("resolve")
    rp.add_argument("names", nargs="+")
    args = ap.parse_args()
    {"align": do_align, "resolve": do_resolve}[args.cmd](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
