#!/usr/bin/env python3
"""soc_regs — Realtek SDK names, fields and reset values for every RTL9300 register our code touches (#102).

- Sources (gitignored `private/` of the main checkout; provenance docs/SDK-SOURCES.md):
  - SDK 4.0.2.55154 PLR loader `platform/9300/`: register_map.h, cg/glb_pll.h, cg/mem_pll.h,
    dram_gen4_9300/memcntlr_reg.h (SoC 0xb8xxxxxx + PLL 0xbb00e2xx; struct bitfields + reset `dv`).
  - SDK 4.0.2.55154 `swcore_rtl9300.h` (switch block 0xbbxxxxxx: names, per-port strides, fields).
  - SDK 3.6.9 (DMS-1250) `rtl9300_soc_reg.h` (SoC block: alias names, fields; cross-check only).
- PLR bitfields are MIPS big-endian GCC: first member = MSB. Checked against rtl9300_soc_reg.h for
  every register both define (log: "order check").
- TOUCHED below = every register our U-Boot / Linux patches / OpenWrt patches touch, with who writes it.
  `--scan` lists literal 0xb8/0xbb addresses in our code that TOUCHED lacks.
- Output: uboot-port/board/tplink/tl-st1008f/rtl9300_regs.h, docs/REGISTERS.md (index part; the
  hand-written audit sections below the generated marker are kept). Log: tmp/logs/soc_regs.log.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/soc_regs.log"
HDR = ROOT / "uboot-port/board/tplink/tl-st1008f/rtl9300_regs.h"
DOC = ROOT / "docs/REGISTERS.md"
KEEP = "<!-- end of generated part: hand-written below, kept by scripts/soc_regs.py -->"


def main_checkout() -> Path:
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--git-common-dir"], capture_output=True,
                         text=True, check=True).stdout.strip()
    return (ROOT / out).resolve().parent


PRIV = main_checkout() / "private"
SDK402 = PRIV / "tplink-gpl-sg3218xp-m2-v2/rtk-ms-sdk-4.0.2.55154"
PLR = SDK402 / "loader/u-boot-2011.12/arch/otto40/plr/src/platform/9300"
# (path, citation label); earlier = higher priority for the primary name
PLR_FILES = [
    (PLR / "cg/glb_pll.h", "4.0.2 plr/9300/cg/glb_pll.h"),
    (PLR / "cg/mem_pll.h", "4.0.2 plr/9300/cg/mem_pll.h"),
    (PLR / "dram_gen4_9300/memcntlr_reg.h", "4.0.2 plr/9300/dram_gen4_9300/memcntlr_reg.h"),
    (PLR / "register_map.h", "4.0.2 plr/9300/register_map.h"),
]
SWCORE = (SDK402 / "sdk/system/include/private/drv/swcore/swcore_rtl9300.h", "4.0.2 swcore_rtl9300.h")
SOCREG = (PRIV / "reyalo-Realtek/sources/rtk-dms1250/system/include/soc/socdef/rtl9300_soc_reg.h",
          "3.6.9 rtl9300_soc_reg.h")

SOC, SW = 0xB8000000, 0xBB000000

# addr (KSEG1), count (array entries we use, 1 = plain), block, ours (who reads/writes on our side),
# writers (S = stock SPL/U-Boot, K = Realtek SDK/stock firmware, O = OpenWrt, U = ours U-Boot, L = ours Linux)
TOUCHED = [
    # CPU / PLL / SRAM
    (0xB8000044, 1, "cpu", "clocks_sram.S ckse_ocp0; clock.c read", "S U"),
    (0xB8000388, 1, "cpu", "never written (audit: se_dram / se_spif)", "S"),
    (0xB80003A8, 1, "cpu", "never written (audit: se_dram)", "S"),
    (0xB80003B8, 1, "cpu", "never written (audit: se_dram)", "S"),
    (0xB80003C8, 1, "cpu", "never written (audit: se_dram)", "S"),
    (0xB80003D8, 1, "cpu", "never written (audit: se_dram)", "S"),
    (0xB8000600, 1, "cpu", "rtk_crypto.c IPSEC enable", "S U"),
    (0xB8000700, 1, "cpu", "never written (audit: sram_pll_sel)", "S"),
    (0xB8004000, 4, "cpu", "clocks.c sram_load, highmem.c", "S U"),
    (0xB80040F8, 1, "cpu", "clocks_sram.S after a CPU change (#101)", "S U"),
    (0xBB000004, 1, "cpu", "not read (audit: relock choice)", "-"),
    (0xBB00E200, 1, "cpu", "clocks_sram.S relock, clocks.c lx_set", "S U"),
    (0xBB00E208, 1, "cpu", "clocks_sram.S; clock.c, OpenWrt 300-05 read", "S U"),
    (0xBB00E210, 1, "cpu", "clocks_sram.S; clock.c, OpenWrt 300-05 read", "S U"),
    (0xBB00E214, 1, "cpu", "clock.c read", "S"),
    (0xBB00E220, 1, "cpu", "clocks.c lx_set, clocks_sram.S relock", "S U"),
    # memory controller + MEM PLL
    (0xB8000234, 7, "mem", "ddr_sram.S MEM PLL change", "S U"),
    (0xB8001000, 1, "mem", "clocks fast prefetch; OpenWrt 300-04", "S U L"),
    (0xB8001004, 1, "mem", "clocks.c, highmem.c read", "S"),
    (0xB8001008, 1, "mem", "ddr_sram.S dtr_update, clocks.c refi_set", "S U"),
    (0xB800100C, 1, "mem", "ddr_sram.S dtr_update", "S U"),
    (0xB8001010, 1, "mem", "ddr_sram.S dtr_update", "S U"),
    (0xB800101C, 1, "mem", "ddr_sram.S latch/refresh/MRS, clocks.c refi_set", "S U"),
    (0xB8001040, 1, "mem", "ddr_sram.S self-refresh method", "S U"),
    (0xB8001044, 1, "mem", "clocks.c read", "S"),
    (0xB8001050, 1, "mem", "clocks set mem reg override", "S U"),
    (0xB8001054, 2, "mem", "clocks set mem reg override", "S U"),
    (0xB8001080, 1, "mem", "clocks.c read", "S"),
    (0xB8001300, 4, "mem", "clocks.c sram_load, highmem.c", "S U O"),
    (0xB8001500, 1, "mem", "ddr_sram.S PHY FIFO pointer clear", "S U"),
    (0xB8001510, 16, "mem", "clocks set mem dqshift", "S U"),
    (0xB8001550, 16, "mem", "clocks set mem dqshift", "S U"),
    (0xB8001590, 1, "mem", "clocks.c read", "S"),
    (0xB80015B0, 4, "mem", "clocks.c read; reg override", "S U"),
    (0xB80015C0, 1, "mem", "clocks.c read; reg override", "S U"),
    (0xB80015C4, 1, "mem", "clocks.c read; reg override", "S U"),
    (0xB8004220, 1, "mem", "highmem.c; OpenWrt highmem", "O U"),
    (0xB8004224, 1, "mem", "highmem.c; OpenWrt highmem", "O U"),
    # SPI-NOR
    (0xB8001200, 1, "spi", "spi-realtek-rtl.c, clock.c; OpenWrt 300-07", "S U O"),
    (0xB8001204, 1, "spi", "OpenWrt 300-07 dirmap", "S O"),
    (0xB8001208, 1, "spi", "spi-realtek-rtl.c; OpenWrt spi", "S U O"),
    (0xB800120C, 1, "spi", "spi-realtek-rtl.c; OpenWrt spi", "S U O"),
    # UART / timers / WDT / GPIO / crypto
    (0xB8002000, 1, "io", "ddr_sram.S putc", "S U"),
    (0xB8002014, 1, "io", "clocks.c uart_drain, ddr_sram.S putc", "S U"),
    (0xB8003260, 1, "io", "bootsel.c wdt; Linux realtek_otto_wdt (300-15)", "U L"),
    (0xB8003264, 1, "io", "bootsel.c wdt; Linux realtek_otto_wdt", "U L"),
    (0xB8003268, 1, "io", "bootsel.c wdt; Linux realtek_otto_wdt (300-15)", "U L"),
    (0xB8003308, 1, "io", "gpio-realtek-otto.c; Linux gpio", "S U L"),
    (0xB800330C, 1, "io", "gpio-realtek-otto.c, rtk.h; Linux gpio", "S U L"),
    (0xB800C000, 4, "io", "rtk_crypto.c", "U"),
    # switch core: NIC
    (0xBB00000C, 1, "nic", "cpu.c chip reset, rtl930x_nic.h NIC reset", "S U L"),
    (0xBB00326C + 28 * 0x40, 1, "nic", "rtl930x_nic.h CPU port", "S U L"),
    (0xBB007C60, 1, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB007C8C, 1, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB009064, 1, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB00A344, 11, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB00A3A0, 1, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB00C714, 1, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB00DF00, 32, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB00E000, 2, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB00E010, 1, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB00E01C, 1, "nic", "rtl930x_nic.h", "S U L"),
    (0xBB00E028, 1, "nic", "rtl930x_nic.h", "S U L"),
    # switch core: ports, SMI, SerDes, I2C, LED, thermal
    (0xBB000064, 1, "sw", "rtk_ours.c temp", "U O"),
    (0xBB000068, 1, "sw", "rtk_ours.c temp", "U O"),
    (0xBB00006C, 1, "sw", "rtk_ours.c temp", "U O"),
    (0xBB000070, 1, "sw", "rtk_ours.c temp", "U O"),
    (0xBB000194, 2, "sw", "rtk_sds.c SDS_MODE_SEL", "S U O"),
    (0xBB0002A0, 2, "sw", "rtk_sds.c SDS_MODE_SEL", "S U O"),
    (0xBB00036C, 1, "sw", "i2c-rtl9300.c; Linux i2c-rtl9300", "S U O"),
    (0xBB000370, 1, "sw", "i2c-rtl9300.c; Linux i2c-rtl9300", "S U O"),
    (0xBB000374, 4, "sw", "i2c-rtl9300.c; Linux i2c-rtl9300", "S U O"),
    (0xBB000384, 1, "sw", "i2c-rtl9300.c; Linux i2c-rtl9300", "S U O"),
    (0xBB0003A0, 1, "sw", "rtk.h presence pins; mainline DTS pinctrl", "S U L"),
    (0xBB0003B0, 1, "sw", "rtk_sds.c", "S U O"),
    (0xBB0003B4, 1, "sw", "rtk_sds.c", "S U O"),
    (0xBB0006A8, 1, "sw", "rtl930x_eth.c read", "-"),
    (0xBB003268, 29, "sw", "rtk_stock.c, rtk_net.c, rtl930x_nic.h", "S U O"),
    (0xBB00B340, 1, "sw", "rtk_net.c port isolation", "S U O"),
    (0xBB00B344, 1, "sw", "rtk_net.c port isolation", "S U O"),
    (0xBB00BD64, 1, "sw", "rtl930x_eth.c read", "-"),
    (0xBB00CA04, 1, "sw", "rtk_net.c", "S U O"),
    (0xBB00CA10, 1, "sw", "rtk_net.c", "S U O"),
    (0xBB00CA1C, 29, "sw", "rtk_net.c, rtl930x_nic.h", "S U O"),
    (0xBB00CA90, 1, "sw", "rtk_net.c", "S U O"),
    (0xBB00CB10, 1, "sw", "rtk_ours.c, rtl930x_eth.c, rtk_linkcheck.c read", "-"),
    (0xBB00CB18, 4, "sw", "rtk_ours.c read", "-"),
    (0xBB00CC00, 1, "sw", "rtk_net.c, rtk_led.c; OpenWrt 300-16", "S U O"),
    (0xBB00CC04, 2, "sw", "rtk_net.c", "S U"),
    (0xBB00CC10, 7, "sw", "rtk_net.c LED_SET", "S U"),
    (0xBB00CC2C, 2, "sw", "rtk_net.c", "S U"),
    (0xBB00CC34, 2, "sw", "rtk_net.c", "S U"),
    (0xBB00CC3C, 1, "sw", "rtk_net.c", "S U"),
    (0xBB00CC40, 1, "sw", "rtk_net.c", "S U"),
    (0xBB00CC44, 1, "sw", "rtk_net.c", "S U"),
    (0xBB00CC48, 1, "sw", "rtk_net.c, rtk_led.c; OpenWrt 300-16", "S U O"),
    (0xBB00CC4C, 4, "sw", "rtk_led.c, rtk_stock.c; OpenWrt 300-16", "S U O"),
    (0xBB00CC5C, 29, "sw", "rtk_led.c, rtk_stock.c; OpenWrt 300-16", "S U O"),
]

BLOCKS = {
    "cpu": "CPU / PLL / SRAM",
    "mem": "Memory controller, MEM PLL, unmapped/zone windows",
    "spi": "SPI-NOR controller",
    "io": "UART / WDT / GPIO / crypto",
    "nic": "Switch core: CPU-port NIC",
    "sw": "Switch core: ports, SMI, SerDes, I2C, LED, thermal",
}
WRITERS = {"S": "stock", "K": "SDK", "O": "OpenWrt", "U": "ours U-Boot", "L": "ours Linux"}


def log(msg: str) -> None:
    print(msg)
    with LOG.open("a") as f:
        f.write(msg + "\n")


class Reg:
    def __init__(self, name, addr, src, line):
        self.name, self.addr, self.src, self.line = name, addr, src, line
        self.fields = []  # (name, msb, lsb), MSB first
        self.reset = None
        self.stride = 0
        self.nidx = 0
        self.idx0 = 0
        self.bad = False

    @property
    def nwords(self):
        return max([m for _, m, _ in self.fields] + [31]) // 32 + 1

    @property
    def cite(self):
        return f"{self.src}:{self.line}"


FIELD_RE = re.compile(r"unsigned\s+int\s+(\w+)\s*:\s*(\d+)\s*;")
UNION_RE = re.compile(r"typedef\s+union\s*\{\s*struct\s*\{(?P<body>.*?)\}\s*f\s*;\s*unsigned\s+int\s+v\s*;\s*\}\s*"
                      r"(?P<name>\w+)_T\s*;", re.S)
RESERVED = re.compile(r"^(mbz|mbo|no_use|dont_care|reserved|dummy)", re.I)


def parse_plr(path: Path, label: str) -> list[Reg]:
    text = path.read_text(errors="replace")
    out = []
    ms = list(UNION_RE.finditer(text))
    for i, m in enumerate(ms):
        name = m["name"]
        tail = text[m.end(): ms[i + 1].start() if i + 1 < len(ms) else len(text)]
        a = re.search(rf"#define\s+{name}(?:ar\s+\(|rv\s+\(\*\(\(regval\))\s*(0x[0-9A-Fa-f]+)", tail)
        if not a:
            continue
        r = Reg(name, int(a[1], 16) | 0xA0000000, label, text.count("\n", 0, m.start()) + 1)
        d = re.search(rf"#define\s+{name}dv\s+\((0x[0-9A-Fa-f]+)\)", tail)
        r.reset = int(d[1], 16) if d else None
        bit = 32
        for fn, w in FIELD_RE.findall(m["body"]):
            w = int(w)
            r.fields.append((fn, bit - 1, bit - w))
            bit -= w
        r.bad = bit != 0
        out.append(r)
    return out


DEF_RE = re.compile(r"#define\s+RTL9300_(\w+)_ADDR(?:\(([\w, ]+)\))?\s+(.*?)\s*(?:/\*(.*?)\*/)?\s*$")
OFF_RE = re.compile(r"#define\s+RTL9300_(\w+)_OFFSET\s+\((\d+)\)")
MASK_RE = re.compile(r"#define\s+RTL9300_(\w+)_MASK\s+\((0x[0-9A-Fa-f]+)\s*<<")


def parse_swdef(path: Path, label: str, base: int) -> list[Reg]:
    """RTL9300_<REG>_ADDR[(params)] + _<FIELD>_OFFSET/_MASK. Indexed: last param = entry index."""
    out, cur, offs = [], None, {}
    for ln, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        m = DEF_RE.match(line.strip())
        if m:
            name, params, expr, cmt = m.groups()
            params = [x.strip() for x in params.split(",")] if params else []
            lo = {}
            for p in params:
                rng = re.search(rf"{p}:\s*(\d+)-(\d+)", cmt or "")
                lo[p] = (int(rng[1]), int(rng[2])) if rng else (0, 0)
            env = {p: lo[p][0] for p in params}
            expr_py = expr.replace("/", "//")
            cur = Reg(name, base + eval(expr_py, {}, env), label, ln)
            if params:
                last = params[-1]
                cur.idx0 = lo[last][0]
                cur.nidx = lo[last][1] - lo[last][0] + 1
                cur.stride = eval(expr_py, {}, dict(env, **{last: env[last] + 1})) - (cur.addr - base)
            out.append(cur)
            offs = {}
            continue
        if not cur:
            continue
        m = OFF_RE.match(line.strip())
        if m and m[1].startswith(cur.name + "_"):
            offs[m[1]] = int(m[2])
            continue
        m = MASK_RE.match(line.strip())
        if m and m[1] in offs:
            lsb, w = offs[m[1]], int(m[2], 16).bit_length()
            cur.fields.append((m[1][len(cur.name) + 1:], lsb + w - 1, lsb))
    for r in out:
        r.fields.sort(key=lambda f: -f[1])
    return out


def load():
    plr = []
    for p, label in PLR_FILES:
        plr += parse_plr(p, label)
    sw = parse_swdef(*SWCORE, SW)
    soc = parse_swdef(*SOCREG, SOC)
    return plr, sw, soc


STEP = {0xB8004000: 0x10, 0xB8001300: 0x10}  # TOUCHED arrays whose SDK entries are not 4 bytes apart


def lookup(regs, addr):
    """(reg, index or None, field or None) for addr: exact base, entry of an indexed register, or a
    word of a multi-word register (word 0 = most significant, SDK reg.c rule)."""
    hits = []
    for r in regs:
        if r.addr == addr:
            return (r, r.idx0 if r.stride else None, None)
        if not (r.stride or r.nwords > 1):
            continue
        st = r.stride or r.nwords * 4
        off = addr - r.addr
        if 0 <= off < max(r.nidx, 1) * st:
            i, rem = divmod(off, st)
            if rem == 0 and r.nwords == 1:
                hits.append((0, (r, i + r.idx0, None)))
            elif rem < r.nwords * 4:
                lo = (r.nwords - 1 - rem // 4) * 32
                f = [x for x in r.fields if lo <= x[2] and x[1] < lo + 32]
                hits.append((1, (r, i + r.idx0 if r.stride else None, f[0][0] if f else f"word{rem // 4}")))
    return min(hits, key=lambda h: h[0])[1] if hits else None


def order_check(plr, sw, soc):
    """PLR bitfields (first member = MSB) vs the OFFSET/MASK headers, same address; also the LSB-first
    reading, which must agree less often if MSB-first is right."""
    other = {r.addr: r for r in soc + sw if [f for f in r.fields if f[1] - f[2] < 31]}
    msb = lsb = n = 0
    for r in plr:
        s = other.get(r.addr)
        if not s or r.bad:
            continue
        sf = {(m, l) for _, m, l in s.fields}
        pf = {(m, l) for x, m, l in r.fields if not RESERVED.match(x)}
        rf = {(31 - l, 31 - m) for m, l in pf}
        n += 1
        msb += len(sf & pf)
        lsb += len(sf & rf)
        if not (sf <= pf or pf <= sf):
            log(f"order check: {r.name} {r.addr:#010x} {r.src}:{r.line} vs {s.src}:{s.line}: "
                f"only-PLR {sorted(pf - sf)} only-other {sorted(sf - pf)}")
    log(f"order check: {n} registers in both; field positions matching MSB-first {msb}, LSB-first {lsb}")
    return msb > lsb


def build_rows(plr, sw, soc):
    srcs = ([r for r in plr if not r.bad], sw, soc)

    def find(a):
        return [lookup(x, a) for x in srcs]

    rows = []

    def add(addr, hits, block, ours, writers, array=None):
        prim = next((h for h in hits if h), None)
        aliases = []
        for h in hits:
            if h and h is not prim and h[0].name != prim[0].name and h[0].name not in [x.name for x in aliases]:
                aliases.append(h[0])
        if prim is None:
            log(f"NO SDK NAME: {addr:#010x} ({ours})")
        fsrc = None
        if prim and prim[2] is None:
            # fields: the 4.0.2 source (PLR or swcore) naming the most fields; 3.6.9 only as fallback
            def nf(h):
                return len([f for f in h[0].fields if not RESERVED.match(f[0]) and f[1] - f[2] < 31]) \
                    if h and h[2] is None else 0
            best = max(hits[:2], key=nf)
            fsrc = best[0] if nf(best) else (hits[2][0] if nf(hits[2]) else prim[0])
        reset = next((h[0].reset for h in hits if h and h[0].reset is not None and h[2] is None), None)
        rows.append(dict(addr=addr, block=block, ours=ours, writers=writers, prim=prim, aliases=aliases,
                         fsrc=fsrc, reset=reset, array=array))

    for addr, count, block, ours, writers in TOUCHED:
        step = STEP.get(addr, 4)
        first = find(addr)
        p = next((h for h in first if h), None)
        ix = next((h for h in first if h and h[0].stride), None)
        if count == 1 or ix:
            add(addr, first, block, ours, writers, (count, ix[0].stride) if count > 1 and ix else None)
            continue
        elems = [find(addr + k * step) for k in range(count)]
        if p and not any(any(e) for e in elems[1:]):
            add(addr, first, block, ours, writers, (count, step))  # SDK defines entry 0 only
            continue
        for k, e in enumerate(elems):
            add(addr + k * step, e, block, ours, writers)
    return rows


def cname(s):
    return re.sub(r"\W", "_", s).upper()


def disp(r):
    if not r["prim"]:
        return "no SDK name"
    reg, i, f = r["prim"]
    s = reg.name + (f"({i})" if i is not None and (r["array"] is None or f) else "")
    return s + (f".{f}" if f else "")


def field_list(r):
    f = r["fsrc"]
    return [(n, m, l) for n, m, l in f.fields if not RESERVED.match(n)] if f else []


def gen_header(rows) -> str:
    out = ["/* SPDX-License-Identifier: GPL-2.0+ */",
           "/* RTL9300 registers our code touches: Realtek SDK names, fields, reset values (#102).",
           " * Generated by scripts/soc_regs.py from the SDK headers (docs/REGISTERS.md); do not edit.",
           " * SoC / PLL: KSEG1 address. Rows marked (sw): offset from 0xbb000000, for sw_r/sw_w.",
           " * <NAME>(i): entry i of an indexed register (SDK index, e.g. port). */",
           "#ifndef __RTL9300_REGS_H", "#define __RTL9300_REGS_H", "", "#include <linux/bitops.h>", ""]
    done = set()
    for blk, title in BLOCKS.items():
        out.append(f"/* ---- {title} ---- */")
        for r in [x for x in rows if x["block"] == blk and x["prim"]]:
            reg, i, f = r["prim"]
            sw = r["addr"] >= SW
            n = "RTL9300_" + cname(reg.name) + (f"_{cname(f)}" if f else "")
            if n in done:
                continue
            done.add(n)
            off = SW if sw else 0
            al = ", ".join(x.name for x in r["aliases"])
            out.append(f"/* {reg.cite}" + (f"; alias {al}" if al else "") + (" (sw)" if sw else "") + " */")
            if reg.stride or r["array"]:
                st = reg.stride or r["array"][1]
                idx = f"(i) - {reg.idx0}" if reg.stride and reg.idx0 else "(i)"
                word = (r["addr"] - reg.addr) % st if f else 0
                out.append(f"#define {n}(i)\t({reg.addr - off + word:#x} + ({idx}) * {st:#x})")
            else:
                out.append(f"#define {n}\t{r['addr'] - off:#x}")
            if r["reset"] is not None:
                out.append(f"#define {n}_RESET\t{r['reset']:#010x}")
            seen = set()
            for fn, m, l in field_list(r):
                fm = f"{n}_{cname(fn)}"
                if fm in seen:
                    fm += f"_{l}"
                seen.add(fm)
                nw = r["fsrc"].nwords
                w = f"\t/* word {nw - 1 - l // 32} (+{4 * (nw - 1 - l // 32)}) */" if nw > 1 else ""
                m, l = m % 32, l % 32
                out.append(f"#define  {fm}\t" + (f"BIT({l})" if m == l else f"GENMASK({m}, {l})") + w)
            out.append("")
    out += ["#endif", ""]
    return "\n".join(out)


def fmt_fields(r):
    if r["prim"] and r["prim"][2]:
        return f"one word of a {r['prim'][0].nwords}-word register"
    return ", ".join(f"{n} {m}" if m == l else f"{n} {m}:{l}" for n, m, l in field_list(r)) or "—"


def gen_doc(rows, old: str) -> str:
    out = ["# RTL9300 registers we touch", "",
           "Generated by scripts/soc_regs.py (#102) down to the marker; edit the script's `TOUCHED` table.",
           "",
           "- Names, newest SDK first: 4.0.2.55154 PLR loader `platform/9300/` (SoC, PLL) and"
           " `swcore_rtl9300.h` (switch core); 3.6.9 `rtl9300_soc_reg.h` = aliases. [SDK-SOURCES.md](SDK-SOURCES.md).",
           "- Same names + `GENMASK` fields as C: `uboot-port/board/tplink/tl-st1008f/rtl9300_regs.h`.",
           "- Writers: stock = stock SPL / U-Boot / `rtk` commands; OpenWrt = upstream driver; ours = this repo.",
           "- Fields MSB first, `name msb:lsb`, reserved left out. Reset = PLR `dv` (switch core: none in the SDK).",
           ""]
    for blk, title in BLOCKS.items():
        out += [f"## {title}", ""]
        for r in [x for x in rows if x["block"] == blk]:
            arr = f" [0..{r['array'][0] - 1}] step {r['array'][1]:#x}" if r["array"] else ""
            out += [f"### `{r['addr']:#010x}` {disp(r)}{arr}", ""]
            src = [r["prim"][0].cite] if r["prim"] else []
            src += [f"alias {a.name} ({a.cite})" for a in r["aliases"]]
            if r["reset"] is not None:
                src.append(f"reset `{r['reset']:#010x}`")
            if src:
                out.append("- " + "; ".join(src))
            out.append(f"- Fields: {fmt_fields(r)}")
            wr = ", ".join(WRITERS[w] for w in r["writers"].split() if w in WRITERS) or "read only"
            out += [f"- Writers: {wr}. Ours: {r['ours']}", ""]
    out.append(KEEP)
    tail = old.split(KEEP, 1)[1] if KEEP in old else "\n"
    return "\n".join(out) + tail


SCAN_DIRS = ["uboot-port", "shared", "openwrt/patches", "mainline"]
LIT_RE = re.compile(r"0x(?:b8|bb|18|1b)[0-9a-f]{6}\b", re.I)
# not registers: block bases (otto.h) and DTR0 values in clocks.c that look like 0xbbxxxxxx
SCAN_IGNORE = {0xB8003200, 0xB8003300, 0xBB70000A, 0xBB75593A, 0xBB755A3A, 0xBB755B3A}


def scan(rows):
    have = set()
    for r in rows:
        n, st = r["array"] or (1, 4)
        have |= {r["addr"] + i * st for i in range(n)}
    miss = {}
    for d in SCAN_DIRS:
        for p in (ROOT / d).rglob("*"):
            if p.suffix not in (".c", ".h", ".S", ".patch", ".dts", ".dtsi"):
                continue
            for ln, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
                for m in LIT_RE.findall(line):
                    a = int(m, 16) | 0xA0000000
                    if a & 0xFF000000 in (0xB8000000, 0xBB000000) and a not in have and a & 0xFFFF \
                            and a not in SCAN_IGNORE:
                        miss.setdefault(a, []).append(f"{p.relative_to(ROOT)}:{ln}")
    for a, where in sorted(miss.items()):
        log(f"scan: {a:#010x} not in TOUCHED: {', '.join(where[:3])}")
    log(f"scan: {len(miss)} literal addresses outside TOUCHED")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--scan", action="store_true", help="list literal register addresses missing from TOUCHED")
    ap.add_argument("--check", action="store_true", help="fail if the generated files are stale")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    for p in [f for f, _ in PLR_FILES] + [SWCORE[0], SOCREG[0]]:
        if not p.exists():
            log(f"ERROR: missing SDK source {p.relative_to(PRIV.parent)} (docs/SDK-SOURCES.md)")
            return 2
    plr, sw, soc = load()
    log(f"parsed: PLR {len(plr)} ({sum(r.bad for r in plr)} with bitfields != 32 bits),"
        f" swcore {len(sw)}, soc_reg {len(soc)}")
    for r in plr:
        if r.bad:
            log(f"PLR bitfields not 32 bits: {r.name} {r.addr:#010x} {r.cite}")
    if not order_check(plr, sw, soc):
        log("ERROR: LSB-first matches the OFFSET/MASK headers better than MSB-first")
        return 2
    rows = build_rows(plr, sw, soc)
    if a.scan:
        scan(rows)
    hdr = gen_header(rows)
    doc = gen_doc(rows, DOC.read_text() if DOC.exists() else "")
    if a.check:
        stale = [p for p, t in ((HDR, hdr), (DOC, doc)) if not p.exists() or p.read_text() != t]
        for p in stale:
            log(f"stale: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    HDR.write_text(hdr)
    DOC.write_text(doc)
    log(f"wrote {HDR.relative_to(ROOT)} and {DOC.relative_to(ROOT)}: {len(rows)} registers,"
        f" {sum(1 for r in rows if not r['prim'])} without an SDK name")
    return 0


if __name__ == "__main__":
    sys.exit(main())
