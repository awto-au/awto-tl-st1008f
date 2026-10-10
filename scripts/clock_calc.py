#!/usr/bin/env python3
"""clock_calc — RTL930x clock tree calculator (host only, no hardware access).

- `decode FILE`: decode an `md.l` dump (bb00e200.., b8000200.., b8001000..) like U-Boot `clocks`.
- `cpu-table` / `mem-table`: the stock preloader tables (loader.bin file 0x4a20/0x4a34, 0x4930..0x49e4).
- `cpu MHZ`: PLL settings for a CPU target, VCO kept inside the range stock uses (2400-3200 MHz).
- `dtr MHZ`: DTR0/1/2 for a MEM clock from the stock DTR bins + tRFC rule.
Formulas and sources: docs/CLOCKS.md. Log: tmp/logs/clock_calc.log.
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/clock_calc.log"
REF_MHZ = 25.0

# Stock preloader tables [BIN] (index i = (MHz - 400) / 25 and (MHz - 250) / 25)
CPU_N = [46, 49, 52, 55, 58, 50, 53, 55, 46, 48, 50, 52, 54, 56, 58, 60, 62]
CPU_D = [4, 4, 4, 4, 4, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2]
MEM_240 = [0x120f0000 + i * 0x02000000 for i in range(15)]
MEM_23C = [0x26222400, 0x26222400, 0x26222520, 0x26222520, 0x26222520, 0x26622520, 0x26622520,
           0x26a23720, 0x26a23720, 0x26a23740, 0x26a23740, 0x26a33840, 0x26a33840, 0x26a33860,
           0x26a33860]
MEM_238 = [0x4000018f] * 6 + [0x400001ef] + [0x4000018f] * 7 + [0x400001ef]
MEM_234 = [0x8407f] * 6 + [0x7f] + [0x8407f] * 2 + [0xc607f] * 4 + [0xc807f, 0x7f]
# DTR bins @ file 0x3320: MHz -> (DTR0, DTR1, DTR2 base); tRFC ns @ 0x338c by die size
DTR = {650: (0x99655838, 0x0909061F, 0x00019000), 600: (0x99644838, 0x0808061F, 0x00016000),
       550: (0x98644738, 0x0808051E, 0x00014000), 500: (0x77533D26, 0x0707031B, 0x00013000),
       450: (0x67533D26, 0x07070418, 0x00011000), 400: (0x56433B25, 0x05050315, 0x0000F000),
       350: (0x55422925, 0x05050312, 0x0000D000), 300: (0x55422825, 0x05050210, 0x0000B000),
       200: (0x43411524, 0x0303010A, 0x00008000)}
TRFC_NS = {512: 90, 1024: 110, 2048: 160, 4096: 260, 8192: 350}  # Mbit per die


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(msg + "\n")


def f(v: int, hi: int, lo: int) -> int:
    return (v >> lo) & ((1 << (hi - lo + 1)) - 1)


def vco(ctrl0: int) -> float:
    ref = REF_MHZ * (4 if ctrl0 & 4 else 1)
    return ref * (f(ctrl0, 11, 4) + 2) * 2 / (1 << (ctrl0 & 3))


def load(path: str) -> dict:
    regs = {}
    for line in Path(path).read_text().splitlines():
        m = re.match(r"\s*([0-9a-f]{8}):((?:\s+[0-9a-f]{8})+)", line)
        if m:
            base = int(m.group(1), 16)
            for i, w in enumerate(m.group(2).split()):
                regs[base + 4 * i] = int(w, 16)
    return regs


def dtr_text(d0: int, d1: int, d2: int, mhz: float) -> str:
    t = {"CL": f(d0, 31, 28), "tWR": f(d0, 27, 24), "CWL": f(d0, 23, 20), "tRTP": f(d0, 19, 16),
         "tWTR": f(d0, 15, 12), "tRP": f(d1, 28, 24), "tRCD": f(d1, 20, 16), "tRRD": f(d1, 12, 8),
         "tFAW": f(d1, 4, 0), "tRFC": f(d2, 27, 20), "tRAS": f(d2, 17, 12)}
    t = {k: v + 1 for k, v in t.items()}
    t["tREFI"] = (f(d0, 11, 8) + 1) << (f(d0, 7, 4) + 5)
    return ", ".join(f"{k} {v} ({v * 1000 / mhz:.1f} ns)" for k, v in t.items())


def decode(path: str) -> None:
    r = load(path)
    e208, e210, e214, e220 = (r[0xbb00e200 + o] for o in (8, 0x10, 0x14, 0x20))
    cpu = vco(e208) / (f(e210, 6, 4) + 2)
    sw = vco(e214)
    lx = sw / (2 * (f(e220, 12, 9) + 2))
    nor = sw / (2 * (f(e220, 16, 13) + 2))
    mem = REF_MHZ * (f(r[0xb8000240], 31, 24) + 2) / (2 << f(r[0xb800023c], 15, 14))
    log(f"cpu {cpu:.3f} MHz (vco {vco(e208):.0f}), timer {cpu / 2:.3f} MHz")
    log(f"lx {lx:.3f} MHz, nor {nor:.3f} MHz (sw vco {sw:.0f}); uart div@115200 "
        f"{round(lx * 1e6 / 16 / 115200)}")
    if 0xb8001200 in r:
        log(f"spi {nor / (2 * (f(r[0xb8001200], 31, 29) + 1)):.3f} MHz")
    log(f"mem {mem:.3f} MHz (DDR3-{2 * mem:.0f})")
    if 0xb8001008 in r:
        log("dtr " + dtr_text(r[0xb8001008], r[0xb800100c], r[0xb8001010], mem))


def cpu_table() -> None:
    for i, (n, d) in enumerate(zip(CPU_N, CPU_D)):
        v = REF_MHZ * (n + 2) * 2
        log(f"req {400 + 25 * i} MHz: ncode {n} divn2 {d} -> vco {v:.0f} cpu {v / (d + 2):.3f}")


def mem_table() -> None:
    for i in range(15):
        mhz = REF_MHZ * ((MEM_240[i] >> 24) + 2) / (2 << f(MEM_23C[i], 15, 14))
        log(f"req {250 + 25 * i} MHz: 234 {MEM_234[i]:08x} 238 {MEM_238[i]:08x} "
            f"23c {MEM_23C[i]:08x} 240 {MEM_240[i]:08x} -> {mhz:.1f} MHz")


def cpu(target: float, e208: int, e210: int) -> None:
    cands = []
    for d in range(8):
        for n in range(256):
            v = REF_MHZ * (n + 2) * 2
            if 2400 <= v <= 3200:
                cands.append((abs(v / (d + 2) - target), d, n, v))
    for _, d, n, v in sorted(cands)[:4]:
        n208 = (e208 & ~(0xff << 4) & ~(3 << 25)) | n << 4
        n210 = (e210 & ~(7 << 4)) | d << 4
        log(f"cpu {v / (d + 2):.3f} MHz: ncode {n} divn2 {d} (vco {v:.0f}) -> "
            f"0xbb00e208 = 0x{n208:08x}, 0xbb00e210 = 0x{n210:08x}"
            + ("" if d in CPU_D else "  [divn2 code never used by stock: SPEC]"))


def dtr(mhz: int, die_mbit: int) -> None:
    if mhz not in DTR:
        sys.exit(f"no stock DTR bin for {mhz} MHz (bins {sorted(DTR)})")
    d0, d1, base = DTR[mhz]
    d2 = ((mhz * TRFC_NS[die_mbit] // 1000 + 5) << 20) | base
    log(f"DTR0 0x{d0:08x} DTR1 0x{d1:08x} DTR2 0x{d2:08x}")
    log("dtr " + dtr_text(d0, d1, d2, mhz))


def main() -> int:
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    sp.add_parser("decode").add_argument("file")
    sp.add_parser("cpu-table")
    sp.add_parser("mem-table")
    c = sp.add_parser("cpu")
    c.add_argument("mhz", type=float)
    c.add_argument("--e208", type=lambda s: int(s, 0), default=0x000003e8, help="live value")
    c.add_argument("--e210", type=lambda s: int(s, 0), default=0x6b439e23, help="live value")
    d = sp.add_parser("dtr")
    d.add_argument("mhz", type=int)
    d.add_argument("--die-mbit", type=int, default=4096, choices=sorted(TRFC_NS))
    a = ap.parse_args()
    log(f"=== clock_calc {' '.join(sys.argv[1:])} ===")
    if a.cmd == "decode":
        decode(a.file)
    elif a.cmd == "cpu-table":
        cpu_table()
    elif a.cmd == "mem-table":
        mem_table()
    elif a.cmd == "cpu":
        cpu(a.mhz, a.e208, a.e210)
    else:
        dtr(a.mhz, a.die_mbit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
