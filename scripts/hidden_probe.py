#!/usr/bin/env python3
"""hidden_probe — read-only probes for hidden/disabled RTL9303 hardware at the U-Boot prompt (#68).

- `md.l` only; no writes. Candidates and evidence: docs/HIDDEN-FEATURES.md.
- Default: named registers with no read side effects (bonding/eFuse status, clock gates, egress encap block,
  dummy/ECO registers, parser/lookup/modifier snapshots HSB/HSA/HSM, L3 lookup-test regs, table-access ctrl).
- `--holes`: sample words in switch-core address holes no SDK register covers (first/middle/last 4 words).
  Unknown decode: a hole word could be a clear-on-read counter; a bus hang stops the run (recover: ./dev.py stock).
- `--alias`: 4 words at 0xbb010000 / 0xbb100000 / 0xbb800000 (RTL865x/8686 gateway switch-core base). May bus-hang.
- Not here (need a write first): eFuse dump, CHIP_INFO, table reads of free TBL codes, L3 HW lookup test.
- Output: tmp/hidden_probe-<label>.json, log tmp/logs/hidden_probe.log.
- Run: `./dev.py hidden-probe [--label L] [--holes] [--alias]` at our prompt (stock `RTL9300#` also accepted);
  `--list` prints the md.l commands without touching the console.
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_probe  # noqa: E402  (md(), PROMPT, CAP_S = 1 s per read: md.l of <= 32 words is ~50 ms at 115200)
from st1008_ramload import Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
hw_probe.LOG = ROOT / "tmp/logs/hidden_probe.log"
SW = 0xBB000000

# (group, name, switch-core offset, words, what to look for)
NAMED = [
    ("id", "MODEL_NAME_INFO", 0x0004, 1, "0x93030001 = RTL9303 rev B; model chars 0"),
    ("bond", "BONDING_REDEFINE_REG", 0x007C, 1, "CHIP_MODE[3:0], EN_DRAM[4], DUMMY_BONDING_12_23[16:5]"),
    ("bond", "BOND_DBG", 0x0228, 1, "BO_24_0[24:0] = raw bonding option pads/fuses"),
    ("bond", "MAC_EFUSE_CTRL", 0xC6FC, 1, "BONDING_DEFINE_EN[17] + eFuse copy of CHIP_MODE/DUMMY_BONDING"),
    ("bond", "EFUSE_ACCESS_EN/CTRL", 0xC698, 2, "idle; CTRL_DONE[11] set if anything read the fuses"),
    ("gate", "PS_GATCLK_MASK/EN/CTRL", 0xC7A0, 3, "EN[5:0] = MAC/ALE/PKT_ENCAP/PKT_PRS/EGR/IGR; [31:6] reserved"),
    ("encap", "EGBW_ENCAP_CTRL", 0x78E0, 1, "ENCAP_CPU_TAG_FEED_BACK[0], ASSURED_DIS_ENCAP_FEED_BACK[1]"),
    ("encap", "ENCAP_SRAM_CTRL0/1", 0xC7CC, 2, "encap RAM margins: TCAM/UT/MAC/ACT/RMKOPRI/RMKIPRI/SMAC"),
    ("tbl", "TBL_ACCESS_L2_CTRL", 0xB320, 1, "TBL[17:16] of last access (free code 3)"),
    ("tbl", "TBL_ACCESS_CTRL_0", 0xB340, 1, "TBL[15:12] last access (free codes 9-15)"),
    ("tbl", "TBL_ACCESS_CTRL_1", 0xB3A0, 1, "TBL[15:13] last L3 access (free codes 6, 7)"),
    ("tbl", "TBL_ACCESS_CTRL_2", 0xCE04, 1, "TBL[13:12] last egress access (all 4 codes used)"),
    ("tbl", "TBL_ACCESS_HSA_CTRL", 0x7880, 1, "TBL[8] (code 1 free)"),
    ("tbl", "TBL_ACCESS_HSB_CTRL", 0xD600, 1, "TBL[6] (code 1 free)"),
    ("snap", "TEST_MODE_ALE_CTRL", 0xB51C, 1, "LATCH[1]/EN[0]: HSB/HSA snapshot capture"),
    ("snap", "TEST_MODE_ALE_HSA_MULTI/LOOPBACK", 0x7AA8, 2, "-"),
    ("snap", "TEST_MODE_ALE_HSB_MULTI_CTRL", 0xD72C, 1, "-"),
    ("snap", "HSB_DATA0-29 (parser output)", 0xB4A0, 30, "SIP/DIP/SPORT/DPORT of last latched packet"),
    ("snap", "HSA_DATA0-21 (modifier input)", 0xB520, 22, "TTL_DEC, L3_SA/DA_IDX; no IP/L4 rewrite field named"),
    ("snap", "HSM0_DATA0-17", 0xB7A0, 18, "ingress-stage state"),
    ("snap", "HSM1_DATA0-16", 0xB7E8, 17, "lookup-stage state"),
    ("snap", "HSM2_DATA0-27", 0xB82C, 28, "DATA27: L3_DA_REP/L3_SA_REP/L3_TTL_DEC"),
    ("snap", "HSM3_DATA0-27", 0xB89C, 28, "DATA27 + IPMC replication"),
    ("l3", "L3_HW_LU_KEY/KEY_IP/KEY_DIP/LU_CTRL", 0xAC9C, 10, "LPM test-lookup regs; SDK never uses KEY_DIP"),
    ("spg", "SPG_GLB_CTRL/TX_GRP_CTRL/GLOBAL_STS", 0x7AB0, 3, "packet generator idle = 0 (#70)"),
    ("stock", "stock-only 0x98 (link-fault mask)", 0x0098, 1, "stock rtk.ko LinkFaultMonIsrThread; no SDK name"),
    ("stock", "stock-only 0xd0 (link-fault status)", 0x00D0, 1, "stock reads then writes back (W1C): read is safe"),
]
# Every DMY_REG* (dummy/ECO) register in the GPL map; nonzero = a spare bit in use.
DMY = [0x0078, 0x0108, 0x0230, 0x03AC, 0x3254, 0x3270, 0x3BBC, 0x3D68, 0x67E0, 0x766C, 0x7918, 0x7A00, 0x7AA0,
       0x7ADC, 0x7AE0, 0x7DBC, 0x7F40, 0x81D0, 0x83CC, 0x83D0, 0x8794, 0x879C, 0x8D40, 0x8D44, 0x8FD4, 0x9760,
       0x9A94, 0x9BCC, 0x9D00, 0x9E40, 0x9F78, 0xA084, 0xA104, 0xA198, 0xA1D0, 0xA24C, 0xA2DC, 0xA370, 0xA3A4,
       0xA780, 0xA7F8, 0xA8A4, 0xA9C4, 0xAB0C, 0xAB40, 0xACC4, 0xACC8, 0xACCC, 0xACD0, 0xB390, 0xB3F4, 0xB518,
       0xB578, 0xB5B4, 0xB90C, 0xB910, 0xB914, 0xB918, 0xBDE4, 0xBDE8, 0xBDEC, 0xBDF0, 0xC318, 0xC4E4, 0xC624,
       0xC71C, 0xCBA0, 0xCD28, 0xCE20, 0xCF0C, 0xD0C4, 0xD278, 0xD294, 0xD298, 0xD728, 0xDA60, 0xDA64, 0xDD7C,
       0xDE00, 0xE040, 0xE060, 0xE178, 0xE234, 0xE288, 0xE294, 0xE920, 0xE924, 0xE928, 0xE92C, 0xEB0C]
# Holes >= 16 words outside the MAC per-port blocks (scripts/hidden_sdk_scan.py): (lo, hi) inclusive.
HOLES = [(0x0088, 0x00FC), (0x010C, 0x017C), (0x0234, 0x027C), (0x02DC, 0x035C), (0x03B8, 0x045C),
         (0x31E4, 0x323C), (0x3C08, 0x3C5C), (0x7AE4, 0x7C5C), (0x7FC4, 0x805C), (0x81D4, 0x825C),
         (0x87A0, 0x8A5C), (0x8D48, 0x8E5C), (0x9418, 0x965C), (0x985C, 0x989C), (0x9A98, 0x9ADC),
         (0x9BD0, 0x9C5C), (0x9D04, 0x9D5C), (0xA1D4, 0xA21C), (0xA254, 0xA29C), (0xA2E0, 0xA31C),
         (0xA4B4, 0xA59C), (0xA7FC, 0xA89C), (0xA8A8, 0xA93C), (0xA9C8, 0xAA1C), (0xACD4, 0xB31C),
         (0xB3F8, 0xB49C), (0xB70C, 0xB79C), (0xB91C, 0xB99C), (0xBDF4, 0xBE9C), (0xBF14, 0xC2FC),
         (0xC31C, 0xC37C), (0xC4E8, 0xC5FC), (0xC7E0, 0xC9FC), (0xCBC0, 0xCBFC), (0xCD2C, 0xCDFC),
         (0xD29C, 0xD5FC), (0xD730, 0xD7FC), (0xDA78, 0xDBFC), (0xDE04, 0xDEFC), (0xE064, 0xE0FC),
         (0xE17C, 0xE1FC), (0xE238, 0xE27C), (0xE298, 0xE91C), (0xEB10, 0xEBFC)]
ALIAS = [0xBB010000, 0xBB100000, 0xBB800000]


def decode(name: str, w: list[int]) -> str:
    v = w[0]
    if name == "BONDING_REDEFINE_REG":
        return f"CHIP_MODE={v & 0xF} EN_DRAM={v >> 4 & 1} DUMMY_BONDING=0x{v >> 5 & 0xFFF:03x}"
    if name == "MAC_EFUSE_CTRL":
        return f"BONDING_DEFINE_EN={v >> 17 & 1} CHIP_MODE={v & 0xF} DUMMY_BONDING=0x{v >> 5 & 0xFFF:03x}"
    if name == "BOND_DBG":
        return f"BO_24_0=0x{v & 0x1FFFFFF:07x}"
    if name.startswith("PS_GATCLK"):
        en = w[1]
        return "gated-clock enables " + ",".join(n for b, n in enumerate(
            ("IGR", "EGR", "PKT_PRS", "PKT_ENCAP", "ALE", "MAC")) if en >> b & 1) + \
            (f"; reserved bits set 0x{en & ~0x3F:08x}" if en & ~0x3F else "")
    if name.startswith("HSA_DATA"):
        d3 = w[3]
        return f"ROUTED_PKT={d3 >> 25 & 1} TTL_DEC={d3 >> 28 & 1} L3_SA_IDX={d3 >> 17 & 0x3F} L3_DA_IDX={d3 >> 6 & 0x7FF}"
    if name.startswith("HSB_DATA"):
        s, d, p = w[22], w[21], w[18]
        return (f"SIP {s >> 24}.{s >> 16 & 255}.{s >> 8 & 255}.{s & 255} DIP {d >> 24}.{d >> 16 & 255}."
                f"{d >> 8 & 255}.{d & 255} SPORT {p & 0xFFFF} DPORT {p >> 16}")
    return ""


def run(label: str, holes: bool, alias: bool) -> int:
    con, res, rows = Console(), {}, []
    path = ROOT / f"tmp/hidden_probe-{label}.json"

    def probe(group, name, addr, n, look) -> list[int] | None:
        r = hw_probe.md(con, addr, n, name)
        ok = not isinstance(r, str)
        res[f"{addr:08x}"] = {"group": group, "name": name, "words": [f"{x:08x}" for x in r] if ok else [],
                              "error": None if ok else r}
        path.write_text(json.dumps(res, indent=1))  # per probe: a hang keeps what came before
        if not ok:
            hw_probe.log(f"STOP at {name} 0x{addr:08x}: {r}; recover with ./dev.py stock (power cycle)")
            return None
        nz = [f"+{4 * i:x}={x:08x}" for i, x in enumerate(r) if x]
        rows.append((group, name, f"{addr:08x}", " ".join(nz[:6]) + (" .." if len(nz) > 6 else "") or "all 0",
                     decode(name, r) or look))
        return r

    total = len(NAMED) + len(DMY) + (3 * len(HOLES) if holes else 0) + (len(ALIAS) if alias else 0)
    hw_probe.log(f"hidden_probe {label}: {total} md.l reads (holes {'on' if holes else 'off'}, alias "
                 f"{'on' if alias else 'off'})")
    for g, name, off, n, look in NAMED:
        if probe(g, name, SW + off, n, look) is None:
            return report(rows, 1)
    for off in DMY:
        if probe("dmy", f"DMY 0x{off:04x}", SW + off, 1, "dummy/ECO register") is None:
            return report(rows, 1)
    if holes:
        for lo, hi in HOLES:
            mid = (lo + (hi - lo) // 2) & ~0xF
            for a in sorted({lo, max(lo, mid), max(lo, hi - 12)}):
                if probe("hole", f"hole 0x{lo:04x}-0x{hi:04x}", SW + a, 4, "no SDK name") is None:
                    return report(rows, 1)
    if alias:
        for a in ALIAS:
            if probe("alias", "outside 64 KiB switch window", a, 4, "bus error = no decode") is None:
                return report(rows, 1)
    return report(rows, 0)


def report(rows: list[tuple], rc: int) -> int:
    hw_probe.log("| group | register | addr | nonzero words | decode / look for |")
    hw_probe.log("|---|---|---|---|---|")
    for r in rows:
        hw_probe.log("| " + " | ".join(r) + " |")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--holes", action="store_true", help="also sample unnamed switch-core holes (decode unknown)")
    ap.add_argument("--alias", action="store_true", help="also read outside the 64 KiB switch window (may hang)")
    ap.add_argument("--list", action="store_true", help="print the md.l commands only (no console)")
    a = ap.parse_args()
    if a.list:
        cmds = [f"md.l {SW + o:x} {n:x}  # {name}" for _, name, o, n, _ in NAMED] + \
            [f"md.l {SW + o:x} 1  # DMY" for o in DMY]
        if a.holes:
            cmds += [f"md.l {SW + x:x} 4  # hole 0x{lo:04x}-0x{hi:04x}" for lo, hi in HOLES
                     for x in sorted({lo, max(lo, (lo + (hi - lo) // 2) & ~0xF), max(lo, hi - 12)})]
        if a.alias:
            cmds += [f"md.l {x:x} 4  # alias" for x in ALIAS]
        print("\n".join(cmds))
        return 0
    return run(a.label, a.holes, a.alias)


if __name__ == "__main__":
    sys.exit(main())
