#!/usr/bin/env python3
"""hidden_write_probe — owner-approved write probes for hidden RTL9303 hardware at our U-Boot prompt (#68, #62).

- Every write: switch-core volatile register on ALLOW, recorded (addr, old, new) before, readback after,
  restored at the end; power cycle (`./dev.py stock`) recovers anything. Log tmp/logs/hidden_write_probe.log,
  write journal + results tmp/hidden/hwp-<cmd>-<label>.json.
- Never written: eFuse WDATA 0xC6A0, eFuse RWOP=1 (program), PLL/AFE 0xE200-0xE2FF, DDR/SPI/GPIO/reset/WDT
  (all outside ALLOW; `wr()` refuses them).
- Commands:
  - `snapshot <label> [--lo A --hi B]`: read-only md.l of the 64 KiB switch window (0x100 words per read).
  - `diff <a> <b>`: words that differ between two snapshots.
  - `chipinfo`: CHIP_INFO_EN = 0xA, read CHIP_INFO 0x08, restore.
  - `efuse [--addrs 0-255] [--en V]`: eFuse read sequence (CMD[9]=1, RWOP[0]=0, ADDR[8:1]); RDATA 0xC6A4.
  - `chipmode <n> [--reg 7c|c6fc] [--snap]`: CHIP_MODE[3:0] = n, readback, optional full snapshot, restore.
  - `tables`: read command on free table codes (+ one used code per controller as reference); data regs
    pre-filled with 0xA5A5A5A5 so "RAM answered" is visible.
  - `dmy`: ROUTER_SMAC_SEL/SMAC pattern write + readback; every DMY register's dummy bits 1s/0s, restore.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_probe  # noqa: E402  (md(), PROMPT)
from st1008_ramload import Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/hidden_write_probe.log"
OUT = ROOT / "tmp/hidden"
hw_probe.LOG = LOG
SW = 0xBB000000
PROMPT = hw_probe.PROMPT

# --- table controllers: (name, ctrl, exec bit, cmd bit, tbl lsb, tbl width, addr mask, data base, data words,
#     used reference code, free codes) from swcore_rtl9300.h + drv_rtl9300.c rtl9300_table_read
TBL = [
    ("L2", 0xB320, 19, 18, 16, 2, 0x3FFF, 0xB334, 3, 0, [3]),
    ("CTRL_0", 0xB340, 17, 16, 12, 4, 0xFFF, 0xB344, 19, 1, list(range(9, 16))),
    ("CTRL_1 (L3)", 0xB3A0, 17, 16, 13, 3, 0x1FFF, 0xB3A4, 20, 0, [6, 7]),
    ("CTRL_2 (egress)", 0xCE04, 15, 14, 12, 2, 0xFFF, 0xCE08, 6, 0, []),
    ("HSB", 0xD600, 8, 7, 6, 1, 0x3F, 0xD604, 30, 0, [1]),
    ("HSA", 0x7880, 10, 9, 8, 1, 0xFF, 0x7884, 22, 0, [1]),
]
PATTERN = 0xA5A5A5A5
# DMY registers (swcore_rtl9300.h): addr -> dummy-bit mask. PLL/AFE dummies 0xE234/0xE288/0xE294 excluded.
DMY = {0x3BBC: ~0, 0xAB0C: ~0, 0xE178: ~0, 0x03AC: ~0, 0xC624: ~0, 0xCD28: ~0, 0x0078: 0xFFFFFFE0, 0x0230: ~0,
       0xE040: ~0, 0xB390: ~0, 0xB3F4: ~0, 0xA3A4: ~0, 0xC71C: ~0, 0xCBA0: ~0, 0x0108: ~0, 0x83CC: ~0,
       0x83D0: ~0, 0x9D00: ~0, 0x8794: ~0, 0x9760: ~0, 0x8FD4: ~0, 0xD0C4: ~0, 0x9F78: ~0, 0xA084: ~0,
       0x879C: ~0, 0xA8A4: ~0, 0xA9C4: ~0, 0xE060: ~0, 0xC318: ~0, 0xEB0C: ~0, 0x8D40: ~0, 0x8D44: ~0,
       0x9A94: ~0, 0x81D0: ~0, 0x7918: 0xFFFC0000, 0x7DBC: ~0, 0xA104: ~0, 0x7A00: ~0, 0x7F40: ~0, 0xAB40: ~0,
       0xC4E4: ~0, 0xDA60: ~0, 0xDA64: ~0, 0xB5B4: ~0, 0x9BCC: ~0, 0x7AA0: ~0, 0xA370: 0x7FFFFFE0, 0xE920: ~0,
       0xE924: ~0, 0xE928: ~0, 0xE92C: ~0, 0xD278: ~0, 0xA24C: ~0, 0xACC4: ~0, 0xACC8: ~0, 0xACCC: ~0,
       0x3254: ~0, 0xBDE4: ~0, 0xBDE8: ~0, 0xBDEC: ~0, 0xBDF0: ~0, 0xA2DC: ~0, 0xD294: ~0, 0xD298: ~0,
       0xA780: ~0, 0xA7F8: ~0, 0x9E40: ~0, 0xA1D0: ~0, 0xA198: ~0, 0xD728: ~0, 0xB518: ~0, 0xB90C: ~0,
       0xB910: ~0, 0xB914: ~0, 0xB918: ~0, 0xB578: ~0, 0xACD0: ~0, 0x7ADC: ~0, 0xDE00: ~0, 0x7AE0: ~0}
SMAC_LO, SMAC_HI = 0xCE20, 0xCF0C  # DMY_REG0/1_PKT_ENCAP: SMAC[31:0]; ROUTER_SMAC_SEL[16] + SMAC[47:32]
EF_EN, EF_CTRL, EF_WDATA, EF_RDATA = 0xC698, 0xC69C, 0xC6A0, 0xC6A4

ALLOW = {0x0008, 0x007C, 0xC6FC, EF_EN, EF_CTRL, SMAC_LO, SMAC_HI} | {d & 0xFFFF for d in DMY}
for _t in TBL:
    ALLOW |= {_t[1]} | {_t[7] + 4 * i for i in range(_t[8])}
DENY = {EF_WDATA} | set(range(0xE200, 0xE300, 4))


class Board:
    def __init__(self, cmd: str, label: str):
        self.con, self.journal, self.res = Console(), [], {}
        self.path = OUT / f"hwp-{cmd}-{label}.json"
        OUT.mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        self.path.write_text(json.dumps({"writes": self.journal, "results": self.res}, indent=1))

    def rd(self, off: int, n: int = 1) -> list[int]:
        r = hw_probe.md(self.con, SW + off, n, f"0x{off:04x}")
        if isinstance(r, str):
            self.save()
            raise SystemExit(f"HANG/ERROR reading 0x{off:04x}: {r}; recover: ./dev.py stock (power cycle)")
        return r

    def wr(self, off: int, new: int, restore: bool = True) -> int:
        """Record old, write, read back. Refuses anything not on ALLOW. Returns readback."""
        if off not in ALLOW or off in DENY:
            raise SystemExit(f"REFUSED write 0x{off:04x}: not on ALLOW")
        if off == EF_CTRL and (new & 1 or new & ~0x3FE & ~0x800):
            raise SystemExit(f"REFUSED eFuse ctrl 0x{new:08x}: only CMD[9]+ADDR[8:1] with RWOP=0")
        old = self.rd(off)[0]
        try:
            self.con.run(f"mw.l {SW + off:x} {new & 0xFFFFFFFF:08x}", PROMPT, 1, f"mw 0x{off:04x}")
        except SystemExit as e:
            self.journal.append({"addr": f"{off:04x}", "old": f"{old:08x}", "new": f"{new:08x}", "hang": str(e)})
            self.save()
            raise SystemExit(f"HANG after write 0x{off:04x}={new:08x}: {e}; recover: ./dev.py stock")
        rb = self.rd(off)[0]
        self.journal.append({"addr": f"{off:04x}", "old": f"{old:08x}", "new": f"{new & 0xFFFFFFFF:08x}",
                             "readback": f"{rb:08x}", "restore": restore})
        hw_probe.log(f"  write 0x{off:04x}: old {old:08x} new {new & 0xFFFFFFFF:08x} readback {rb:08x}")
        self.save()
        return rb

    def restore_all(self) -> None:
        """Rewrite each touched register's first recorded old value, newest first; verify."""
        first: dict[str, str] = {}
        for j in self.journal:
            if j.get("restore", True):
                first.setdefault(j["addr"], j["old"])
        for a, old in reversed(list(first.items())):
            off, v = int(a, 16), int(old, 16)
            self.con.run(f"mw.l {SW + off:x} {v:08x}", PROMPT, 1, f"restore 0x{off:04x}")
            rb = self.rd(off)[0]
            hw_probe.log(f"  restore 0x{off:04x} -> {v:08x} readback {rb:08x}{'' if rb == v else '  (differs)'}")
        self.save()


# --- commands --------------------------------------------------------------------------------------------
def snapshot(label: str, lo: int, hi: int) -> int:
    b, words, step = Board("snap", label), {}, 0x100
    t0 = time.monotonic()
    for a in range(lo, hi, step * 4):
        n = min(step, (hi - a) // 4)
        for i, w in enumerate(b.rd(a, n)):
            words[f"{a + 4 * i:04x}"] = f"{w:08x}"
        b.res = words
        b.save()
    hw_probe.log(f"snapshot {label}: {len(words)} words 0x{lo:04x}-0x{hi - 4:04x} in {time.monotonic() - t0:.0f}s, "
                 f"{sum(v != '00000000' for v in words.values())} nonzero -> {b.path.name}")
    return 0


def diff(a: str, c: str) -> int:
    wa = json.loads((OUT / f"hwp-snap-{a}.json").read_text())["results"]
    wc = json.loads((OUT / f"hwp-snap-{c}.json").read_text())["results"]
    d = [k for k in sorted(set(wa) & set(wc)) if wa[k] != wc[k]]
    hw_probe.log(f"diff {a} -> {c}: {len(d)} words differ")
    for k in d:
        hw_probe.log(f"  0x{k}: {wa[k]} -> {wc[k]}")
    return 0


def chipinfo(label: str) -> int:
    b = Board("chipinfo", label)
    old = b.rd(0x08)[0]
    rb = b.wr(0x08, (old & ~(0xF << 16)) | (0xA << 16))
    b.res = {"CHIP_INFO_before": f"{old:08x}", "CHIP_INFO_en": f"{rb:08x}",
             "RL_VID": rb >> 28, "RL_ID": f"{rb & 0xFFFF:04x}", "bits27_20": f"{rb >> 20 & 0xFF:02x}"}
    b.restore_all()
    hw_probe.log(f"chipinfo: {b.res}")
    return 0


def parse_range(s: str) -> list[int]:
    out = []
    for p in s.split(","):
        lo, _, hi = p.partition("-")
        out += list(range(int(lo, 0), int(hi or lo, 0) + 1))
    return out


def efuse(label: str, addrs: list[int], en: int | None) -> int:
    b = Board("efuse", label)
    st = b.rd(EF_EN, 4)
    b.res["before"] = {"EN": f"{st[0]:08x}", "CTRL": f"{st[1]:08x}", "WDATA": f"{st[2]:08x}", "RDATA": f"{st[3]:08x}"}
    if en is not None:
        b.wr(EF_EN, en)
    data = {}
    for a in addrs:
        if not 0 <= a <= 0xFF:
            raise SystemExit(f"eFuse addr {a} outside ADDR[8:1]")
        ctrl = (1 << 9) | (a << 1)  # CMD=1, RWOP=0 (read); 8390 U-Boot rtl8396_efusRead_config: same fields
        if a == addrs[0]:  # journaled (old value restored at the end)
            b.wr(EF_CTRL, ctrl)
            w = b.rd(EF_CTRL, 3)
        else:  # fast path: one line = write + read CTRL/WDATA/RDATA
            if ctrl & 1 or ctrl & ~0x3FE:
                raise SystemExit("eFuse ctrl outside CMD+ADDR: refused")
            _, txt = b.con.run(f"mw.l {SW + EF_CTRL:x} {ctrl:08x}; md.l {SW + EF_CTRL:x} 3", PROMPT, 1,
                               f"efuse {a}")
            w = [int(x, 16) for m in re.finditer(r"[0-9a-f]{8}:((?: [0-9a-f]{8})+)", txt)
                 for x in m.group(1).split()]
            if len(w) < 3:
                raise SystemExit(f"eFuse {a}: parsed {len(w)} words")
        c, rd = w[0], w[2]
        data[a] = {"ctrl": f"{c:08x}", "rdata": f"{rd & 0xFFFF:04x}"}
        if c >> 10 & 1:
            hw_probe.log(f"  eFuse {a}: BUSY still set (ctrl {c:08x})")
        b.res["data"] = data
        b.save()
    b.res["after"] = [f"{x:08x}" for x in b.rd(EF_EN, 4)]
    b.restore_all()
    words = [int(data[a]["rdata"], 16) for a in addrs]
    hw_probe.log(f"efuse {label}: {len(words)} words, {sum(1 for w in words if w)} nonzero; ctrl after first "
                 f"{data[addrs[0]]['ctrl']}")
    for i in range(0, len(addrs), 8):
        hw_probe.log("  " + " ".join(f"{a:02x}:{data[a]['rdata']}" for a in addrs[i:i + 8]))
    return 0


CHIPMODE_WATCH = [(0x04, 1, "MODEL_NAME_INFO"), (0x7C, 1, "BONDING_REDEFINE_REG"), (0x84, 1, "SDS_VERSION"),
                  (0x194, 2, "SDS_MODE_SEL_0/3"), (0x228, 1, "BOND_DBG"), (0x2A0, 2, "SDS_MODE_SEL_1/2"),
                  (0xC6FC, 1, "MAC_EFUSE_CTRL"), (0xC7C8, 1, "CODE_PROTECT_STATE")]


def chipmode(label: str, n: int, reg: int, snap: bool) -> int:
    b = Board("chipmode", label)
    if snap:  # same-boot reference: 0x460-0x650 and 0x31d4-0x31e0 differ between boots (power-up SRAM)
        snapshot(f"{label}-pre", 0, 0x10000)
    b.res["before"] = {name: [f"{x:08x}" for x in b.rd(o, k)] for o, k, name in CHIPMODE_WATCH}
    old = b.rd(reg)[0]
    rb = b.wr(reg, (old & ~0xF) | (n & 0xF))
    b.res["after"] = {name: [f"{x:08x}" for x in b.rd(o, k)] for o, k, name in CHIPMODE_WATCH}
    b.res["write_stuck"] = (rb & 0xF) == n
    b.save()
    for name in b.res["before"]:
        if b.res["before"][name] != b.res["after"][name]:
            hw_probe.log(f"  CHANGED {name}: {b.res['before'][name]} -> {b.res['after'][name]}")
    if snap:
        snapshot(f"{label}", 0, 0x10000)
    b.restore_all()
    hw_probe.log(f"chipmode {label}: reg 0x{reg:04x} {old:08x} -> wrote CHIP_MODE={n}, readback {rb:08x}, "
                 f"stuck={b.res['write_stuck']}")
    return 0


def tables(label: str, ctl: str | None, codes: list[int] | None) -> int:
    """A code whose EXEC never clears locks that controller (data regs too) until power cycle:
    test such codes one per boot with --ctl/--codes."""
    b = Board("tables", label)
    for name, ctrl, ex, cm, tl, tw, am, dbase, dn, ref, free in TBL:
        if ctl and not name.startswith(ctl):
            continue
        for code in codes if codes is not None else [ref] + free:
            if code >= 1 << tw:
                continue
            key = f"{name} code {code}"
            for i in range(dn):  # pre-fill: a RAM that answers overwrites the pattern
                b.wr(dbase + 4 * i, PATTERN)
            cmd = (1 << ex) | (code << tl) | 0  # CMD=0 (read), ADDR=0
            assert not cmd >> cm & 1
            try:
                b.con.run(f"mw.l {SW + ctrl:x} {cmd:08x}", PROMPT, 1, f"{key} read cmd")
            except SystemExit as e:
                b.res[key] = {"hang": str(e)}
                b.save()
                raise SystemExit(f"HANG on {key}; recover: ./dev.py stock")
            c = b.rd(ctrl)[0]
            d = b.rd(dbase, dn)
            b.res[key] = {"cmd": f"{cmd:08x}", "ctrl_after": f"{c:08x}", "exec_cleared": not c >> ex & 1,
                          "data": [f"{x:08x}" for x in d], "pattern_kept": sum(x == PATTERN for x in d)}
            hw_probe.log(f"  {key}: ctrl {c:08x} exec {'cleared' if not c >> ex & 1 else 'STUCK'}, "
                         f"{b.res[key]['pattern_kept']}/{dn} data words still pattern, nonzero "
                         f"{[f'{x:08x}' for x in d if x and x != PATTERN][:6]}")
            b.save()
            if c >> ex & 1:
                hw_probe.log(f"  {key}: EXEC stuck; skipping the rest of {name}")
                break
    b.restore_all()
    return 0


def dmy(label: str) -> int:
    b = Board("dmy", label)
    smac = {}
    for v_lo, v_hi in ((0x12345678, 0x0001ABCD), (0xFFFFFFFF, 0xFFFFFFFF)):
        smac[f"{v_lo:08x}/{v_hi:08x}"] = [f"{b.wr(SMAC_LO, v_lo):08x}", f"{b.wr(SMAC_HI, v_hi):08x}"]
    b.res["smac"] = smac
    impl = {}
    for off, mask in DMY.items():
        if off in (SMAC_LO, SMAC_HI):
            continue
        mask &= 0xFFFFFFFF
        old = b.rd(off)[0]
        r1 = b.wr(off, old | mask)
        r0 = b.wr(off, old & ~mask)
        impl[f"{off:04x}"] = {"old": f"{old:08x}", "ones": f"{r1:08x}", "zeros": f"{r0:08x}",
                              "rw_bits": f"{(r1 ^ r0) & mask:08x}"}
        b.res["dmy"] = impl
        b.save()
    b.restore_all()
    hw_probe.log(f"dmy {label}: SMAC {smac}")
    for k, v in impl.items():
        if v["rw_bits"] != "00000000" or v["old"] != "00000000":
            hw_probe.log(f"  DMY 0x{k}: old {v['old']} rw-bits {v['rw_bits']} (1s->{v['ones']} 0s->{v['zeros']})")
    hw_probe.log(f"  {sum(v['rw_bits'] == 'ffffffff' for v in impl.values())}/{len(impl)} DMY regs fully R/W")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("snapshot")
    s.add_argument("label")
    s.add_argument("--lo", type=lambda x: int(x, 0), default=0)
    s.add_argument("--hi", type=lambda x: int(x, 0), default=0x10000)
    s = sp.add_parser("diff")
    s.add_argument("a")
    s.add_argument("b")
    s = sp.add_parser("chipinfo")
    s.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    s = sp.add_parser("efuse")
    s.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    s.add_argument("--addrs", default="0-255")
    s.add_argument("--en", type=lambda x: int(x, 0))
    s = sp.add_parser("chipmode")
    s.add_argument("n", type=int)
    s.add_argument("--reg", choices=["7c", "c6fc"], default="7c")
    s.add_argument("--snap", action="store_true")
    s.add_argument("--label")
    s = sp.add_parser("tables")
    s.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    s.add_argument("--ctl", help="controller name prefix: L2, CTRL_0, CTRL_1, CTRL_2, HSB, HSA")
    s.add_argument("--codes", help="codes to try (default: reference + free), e.g. 10-15")
    s = sp.add_parser("dmy")
    s.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    a = ap.parse_args()
    hw_probe.log(f"=== hidden_write_probe {' '.join(sys.argv[1:])}")
    if a.cmd == "snapshot":
        return snapshot(a.label, a.lo, a.hi)
    if a.cmd == "diff":
        return diff(a.a, a.b)
    if a.cmd == "chipinfo":
        return chipinfo(a.label)
    if a.cmd == "efuse":
        return efuse(a.label, parse_range(a.addrs), a.en)
    if a.cmd == "chipmode":
        return chipmode(a.label or f"mode{a.n}-{a.reg}", a.n, int(a.reg, 16), a.snap)
    if a.cmd == "tables":
        return tables(a.label, a.ctl, parse_range(a.codes) if a.codes else None)
    return dmy(a.label)


if __name__ == "__main__":
    sys.exit(main())
