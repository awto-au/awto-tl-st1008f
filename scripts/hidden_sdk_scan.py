#!/usr/bin/env python3
"""hidden_sdk_scan — offline search of the RTL9300 (longan) register/table maps for hidden or disabled features (#68).

- Inputs: GPL SDK clone (`github.com/reyalo/Realtek`, dir `sources/`; `--sdk` or env REALTEK_SRC,
  default `private/reyalo-Realtek/sources`); optional stock `rtk.ko` / ST5008F `core` / decompiles (private/).
- Reports: register address coverage + holes, table index-space gaps, unnamed bits in table entries,
  NAT-ish names, BIST memory inventory, longan vs mango (RTL9310) feature diff, stock/managed binary
  reg/table lists vs GPL, literal switch-core addresses in decompiles that no named register covers.
- Output: `tmp/hidden/sdk_scan.json` + log `tmp/logs/hidden_sdk_scan.log`. No hardware access.
"""

import argparse
import json
import os
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/hidden_sdk_scan.log"
OUT = ROOT / "tmp/hidden/sdk_scan.json"
PRIV = ROOT / "private"
STOCK_RTK = PRIV / "mtd-backup-20261008-145913/stock-extract/initramfs-1/lib/modules/3.18.24/kernel/drivers/net/switch/rtk/rtk.ko"
ST5008F_CORE = PRIV / "china/st5008f-v2-extracted/rootfs/usrImage/app/sbin/core"
DECOMPILES = [PRIV / "ghidra" / n for n in (
    "stock-rtk-full.c", "stock-rtcore-full.c", "stock-loader-named.c")] + [
    PRIV / "ghidra/vendor-nic" / n for n in ("st5008f-core.c", "st5008f-core-extra.c", "st5008f-rtcore.c")]

NATISH = re.compile(r"NAT|NAPT|(^|_)SIP|(^|_)DIP|SPORT|DPORT|L4|CSUM|CHKSUM|CHECKSUM|TUNNEL|TNL|EXT_IP|MODIF|"
                    r"REWRITE|REPLACE|_REP$|EGR_ACT|MANGLE|GRE|VXLAN|MPLS|ENCAP|DECAP|SET_FIELD|FLOW")
# MAC per-port blocks: chipdef.c rtl9300_macPpInfo (lower, upper, interval).
PP_BLOCKS = [(0x3260, 0x3A5C, 0x40), (0x3C60, 0x67DC, 0x180), (0x67E0, 0x765C, 0x60),
             (0x7660, 0x785C, 0x10), (0xE300, 0xEAFC, 0x60), (0xF080, 0xFFFC, 0x80)]
# Table access controllers: drv_rtl9300.c rtl9300_table_read groupId -> ctrl reg, TBL field width.
CTRL = {0: ("TBL_ACCESS_L2_CTRL", 2), 1: ("TBL_ACCESS_CTRL_0", 4), 2: ("TBL_ACCESS_CTRL_1", 3),
        3: ("TBL_ACCESS_CTRL_2", 2), 4: ("TBL_ACCESS_HSB_CTRL", 1), 5: ("TBL_ACCESS_HSA_CTRL", 1)}
GROUP = {
    0: ["L2_UC", "L2_MC", "L2_CAM_UC", "L2_CAM_MC", "MC_PORTMASK"],
    1: ["VLAN", "VLAN_IGR_CNVT", "VLAN_MAC_BASED", "VLAN_IP_BASED", "METER", "MSTI", "LOG", "VACL", "IACL",
        "PORT_ISO_CTRL", "LAG", "SRC_TRK_MAP"],
    2: ["L3_ROUTER_MAC", "L3_HOST_ROUTE_IPUC", "L3_HOST_ROUTE_IPMC", "L3_HOST_ROUTE_IP6UC", "L3_HOST_ROUTE_IP6MC",
        "L3_PREFIX_ROUTE_IPUC", "L3_PREFIX_ROUTE_IPMC", "L3_PREFIX_ROUTE_IP6UC", "L3_PREFIX_ROUTE_IP6MC",
        "L3_NEXTHOP", "L3_EGR_INTF_LIST", "L3_EGR_INTF"],
    3: ["UNTAG", "VLAN_EGR_CNVT", "L3_EGR_INTF_MAC", "REMARK"],
    4: ["HSB"], 5: ["HSA"],
}


def log(msg=""):
    print(msg)
    with LOG.open("a") as f:
        f.write(msg + "\n")


# ---------- GPL parsing ----------
REG_RE = re.compile(r"/\* offset address \*/\s+(0x[0-9A-Fa-f]+),\s*/\* field numbers \*/\s+(\d+),\s*"
                    r"/\* port index \*/\s+(\d+),\s*(\d+),\s*/\* array index \*/\s+(\d+),\s*(\d+),\s*"
                    r"/\* portlist index \*/\s+(\d+),\s*/\* bit offset \*/\s+(\d+),\s*"
                    r"/\* register fields \*/\s+(\w+)_RTL9300_FIELDS", re.S)
RFIELDS_RE = re.compile(r"rtk_regField_t (\w+)_RTL9300_FIELDS\[\] =\s*\{(.*?)\n\};", re.S)
RFIELD_RE = re.compile(r"/\* name \*/\s+LONGAN_(\w+)f,\s*/\* lsp \*/\s+(\d+),\s*/\* len \*/\s+(\d+)", re.S)
TAB_RE = re.compile(r"/\* table name\s+INT_LONGAN_RTL9300_(\w+) \*/\s*/\* access table set \*/\s+(\d+),\s*"
                    r"/\* access table type \*/\s+(\d+),\s*/\* table size \*/\s+(\d+),\s*"
                    r"/\* total data registers \*/\s+(\d+)", re.S)
TFIELDS_RE = re.compile(r"rtk_tableField_t RTL9300_(\w+)_FIELDS\[\] =\s*\{(.*?)\n\};", re.S)
TFIELD_RE = re.compile(r"/\* name\s+LONGAN_(\w+)tf \*/\s*/\* lsp \*/\s+(\d+),\s*/\* len \*/\s+(\d+)", re.S)


def gpl_regs(sdk, tree):
    d = sdk / tree / "src/hal/chipdef/longan"
    regs = {}
    for m in REG_RE.finditer((d / "rtk_longan_reg_list.c").read_text(errors="replace")):
        off, fn, lp, hp, la, ha, pl, bo, name = m.groups()
        regs[name] = dict(offset=int(off, 16), field_num=int(fn), lport=int(lp), hport=int(hp),
                          larray=int(la), harray=int(ha), portlist=int(pl), bit_offset=int(bo))
    for m in RFIELDS_RE.finditer((d / "rtk_longan_regField_list.c").read_text(errors="replace")):
        if m.group(1) in regs:
            regs[m.group(1)]["fields"] = [(n, int(l), int(w)) for n, l, w in RFIELD_RE.findall(m.group(2))]
    return regs


def gpl_tables(sdk, tree):
    d = sdk / tree / "src/hal/chipdef/longan"
    tabs = {}
    for m in TAB_RE.finditer((d / "rtk_longan_table_list.c").read_text(errors="replace")):
        tabs[m.group(1)] = dict(set=int(m.group(2)), type=int(m.group(3)), size=int(m.group(4)),
                                datareg=int(m.group(5)))
    for m in TFIELDS_RE.finditer((d / "rtk_longan_tableField_list.c").read_text(errors="replace")):
        if m.group(1) in tabs:
            tabs[m.group(1)]["fields"] = [(n, int(l), int(w)) for n, l, w in TFIELD_RE.findall(m.group(2))]
    return tabs


# ---------- address coverage (hal/mac/reg.c _reg_addr_find) ----------
def pp_block(addr):
    for lo, hi, iv in PP_BLOCKS:
        if lo <= addr <= hi:
            return iv
    return None


def reg_words(r):
    """Word addresses one named register covers, for every port/array index."""
    off, bo = r["offset"], r["bit_offset"]
    ports = range(r["lport"], r["hport"] + 1) if (r["lport"], r["hport"]) != (0, 0) else [None]
    arrs = range(r["larray"], r["harray"] + 1) if (r["larray"], r["harray"]) != (0, 0) else [None]

    def step(i, lo):
        if bo == 0:
            return 0
        return ((i - lo) // (32 // bo)) * 4 if bo % 32 else (i - lo) * (bo // 8)

    width = max(4, (bo // 8) if bo and bo % 32 == 0 else 4)  # a >32-bit entry spans bo/8 bytes
    iv = pp_block(off)
    words = set()
    for p in ports:
        for a in arrs:
            addr = off
            if iv is not None:
                if p is not None:
                    addr += p * iv
                if a is not None:
                    addr += step(a, r["larray"])
            elif p is not None and a is not None:
                dim1 = (((r["harray"] - r["larray"]) // (32 // bo)) + 1) * 4 if bo % 32 else \
                    (r["harray"] - r["larray"] + 1) * (bo // 8)
                addr += (p - r["lport"]) * dim1 + step(a, r["larray"])
            elif p is not None:
                addr += step(p, r["lport"])
            elif a is not None:
                addr += step(a, r["larray"])
            span = width if (p is not None or a is not None) else 4
            if p is None and a is None:
                # a single register whose fields exceed 32 bits spans several words
                top = max((l + w for _, l, w in r.get("fields", [])), default=32)
                span = 4 * ((top + 31) // 32)
            for w in range(addr, addr + span, 4):
                words.add(w)
    return words


def holes(covered, lo=0x0000, hi=0x10000, min_words=4):
    out, start = [], None
    for a in range(lo, hi, 4):
        if a not in covered:
            start = a if start is None else start
        elif start is not None:
            if (a - start) // 4 >= min_words:
                out.append((start, a - 4))
            start = None
    if start is not None and (hi - start) // 4 >= min_words:
        out.append((start, hi - 4))
    return out


def table_bits(t):
    total = t["datareg"] * 32
    used = [0] * total
    for _, l, w in t.get("fields", []):
        for b in range(l, min(l + w, total)):
            used[b] = 1
    gaps, start = [], None
    for b in range(total):
        if not used[b]:
            start = b if start is None else start
        elif start is not None:
            gaps.append((start, b - 1))
            start = None
    if start is not None:
        gaps.append((start, total - 1))
    return total, sum(used), gaps


# ---------- vendor binaries ----------
def elf_symbol_bytes(path, symbols):
    from elftools.elf.elffile import ELFFile
    out = {}
    with open(path, "rb") as f:
        e = ELFFile(f)
        tabs = [s for s in e.iter_sections() if s.header["sh_type"] in ("SHT_SYMTAB", "SHT_DYNSYM")]
        for st in tabs:
            for s in st.iter_symbols():
                if s.name in symbols and s.name not in out and s["st_size"]:
                    shndx = s["st_shndx"]
                    if isinstance(shndx, int):
                        sec = e.get_section(shndx)
                        if e.header["e_type"] == "ET_REL":
                            off = s["st_value"]
                        else:
                            off = s["st_value"] - sec["sh_addr"]
                        out[s.name] = sec.data()[off:off + s["st_size"]]
        endian = ">" if not e.little_endian else "<"
    return out, endian


def bin_lists(path):
    blobs, en = elf_symbol_bytes(path, {"rtk_longan_reg_list", "rtk_longan_table_list"})
    regs, tabs = {}, {}
    b = blobs.get("rtk_longan_reg_list", b"")
    for i in range(0, len(b) - 147, 148):  # char name[128] + rtk_reg_t (20 B)
        name = b[i:i + 128].split(b"\0")[0].decode(errors="replace")
        off, w1, w2, w3 = struct.unpack(en + "4I", b[i + 128:i + 144])
        regs[name] = dict(offset=off, field_num=w1 >> 16, lport=(w1 >> 8) & 0xFF, hport=w1 & 0xFF,
                          larray=w2 >> 16, harray=w2 & 0xFFFF, portlist=w3 >> 16, bit_offset=w3 & 0xFFFF)
    b = blobs.get("rtk_longan_table_list", b"")
    for i in range(0, len(b) - 151, 152):  # char name[128] + rtk_table_t (24 B)
        name = b[i:i + 128].split(b"\0")[0].decode(errors="replace")
        st, ty, sz, dr, fn = struct.unpack(en + "5I", b[i + 128:i + 148])
        tabs[name] = dict(set=st, type=ty, size=sz, datareg=dr, field_num=fn)
    return regs, tabs


def compare(tag, gregs, gtabs, bregs, btabs):
    keys = ("offset", "field_num", "lport", "hport", "larray", "harray", "bit_offset")
    only_bin = sorted(set(bregs) - set(gregs))
    only_gpl = sorted(set(gregs) - set(bregs))
    diff = [n for n in sorted(set(bregs) & set(gregs)) if any(bregs[n][k] != gregs[n][k] for k in keys)]
    tdiff = [n for n in sorted(set(btabs) & set(gtabs))
             if any(btabs[n][k] != gtabs[n][k] for k in ("set", "type", "size", "datareg"))]
    log(f"[{tag}] regs {len(bregs)} (GPL {len(gregs)}): only-in-binary {len(only_bin)}, only-in-GPL "
        f"{len(only_gpl)}, field/offset diffs {len(diff)}; tables {len(btabs)} (GPL {len(gtabs)}), "
        f"only-in-binary {sorted(set(btabs) - set(gtabs))}, diffs {tdiff}")
    for n in only_bin[:40]:
        log(f"  only-in-binary reg {n} @0x{bregs[n]['offset']:04x}")
    for n in diff[:40]:
        log(f"  diff {n}: bin {[bregs[n][k] for k in keys]} gpl {[gregs[n][k] for k in keys]}")
    return dict(only_bin=only_bin, only_gpl=only_gpl, diff=diff, table_only_bin=sorted(set(btabs) - set(gtabs)),
                table_diff=tdiff)


# ---------- decompile literal scan ----------
LIT_RE = re.compile(r"ioal_mem32_(?:field_)?(read|write)\(\s*[^,]+,\s*(0x[0-9a-fA-F]+)\b")
RAW_RE = re.compile(r"\b0x(bb00[0-9a-fA-F]{4}|bb01[0-9a-fA-F]{4})\b")


def scan_decompiles(covered):
    found = {}
    for p in DECOMPILES:
        if not p.exists():
            continue
        text = p.read_text(errors="replace")
        for op, a in LIT_RE.findall(text):
            v = int(a, 16)
            if v < 0x10000:
                found.setdefault(v & ~3, set()).add(f"{p.name}:{op}")
        for a in RAW_RE.findall(text):
            v = int(a, 16) & 0xFFFF
            found.setdefault(v & ~3, set()).add(f"{p.name}:raw")
    unnamed = {a: sorted(s) for a, s in sorted(found.items()) if a not in covered}
    return {f"0x{a:04x}": s for a, s in unnamed.items()}, len(found)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sdk", type=Path,
                    default=Path(os.environ.get("REALTEK_SRC", ROOT / "private/reyalo-Realtek/sources")))
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("")
    if not (a.sdk / "rtk-xgs1210").is_dir():
        sys.exit(f"SDK not found: {a.sdk} (set --sdk or REALTEK_SRC to <reyalo/Realtek clone>/sources)")
    res = {}

    regs = gpl_regs(a.sdk, "rtk-xgs1210")
    regs_d = gpl_regs(a.sdk, "rtk-dms1250")
    tabs = gpl_tables(a.sdk, "rtk-xgs1210")
    log(f"GPL xgs1210: {len(regs)} regs, {len(tabs)} tables; dms1250: {len(regs_d)} regs")
    res["xgs_vs_dms"] = compare("dms1250 vs xgs1210", regs, tabs, regs_d, gpl_tables(a.sdk, "rtk-dms1250"))

    # 1. address coverage
    covered = set()
    owner = {}
    for n, r in regs.items():
        for w in reg_words(r):
            covered.add(w)
            owner.setdefault(w, n)
    hs = holes(covered)
    log(f"\n# switch-core 0x0000-0xFFFF: {len(covered)} of 16384 words named; holes >= 4 words: {len(hs)}")
    res["holes"] = []
    for lo, hi in hs:
        before = owner.get(lo - 4, "-")
        after = owner.get(hi + 4, "-")
        res["holes"].append(dict(lo=f"0x{lo:04x}", hi=f"0x{hi:04x}", words=(hi - lo) // 4 + 1, before=before,
                                 after=after))
        log(f"  hole 0x{lo:04x}-0x{hi:04x} ({(hi - lo) // 4 + 1} words) after {before} / before {after}")

    # 2. table index space
    log("\n# table access controllers: used vs free TBL type codes")
    res["table_space"] = {}
    for g, names in GROUP.items():
        ctrl, width = CTRL[g]
        used = sorted({tabs[n]["type"] for n in names if n in tabs})
        free = [t for t in range(1 << width) if t not in used] if width else []
        res["table_space"][ctrl] = dict(width=width, used=used, free=free,
                                        tables={n: tabs[n]["type"] for n in names if n in tabs})
        log(f"  {ctrl}: TBL width {width}, used {used}, free {free} :: "
            + ", ".join(f"{n}={tabs[n]['type']}" for n in names if n in tabs))

    # 3. unnamed bits per table entry
    log("\n# table entries: named bits / total, unnamed ranges")
    res["table_bits"] = {}
    for n, t in tabs.items():
        total, used, gaps = table_bits(t)
        res["table_bits"][n] = dict(total=total, named=used, gaps=gaps, size=t["size"])
        if total - used >= 8:
            log(f"  {n}: {used}/{total} bits named, size {t['size']}, gaps {gaps}")

    # 4. NAT-ish names
    log("\n# NAT-ish register / field / table-field names (longan)")
    hits = []
    for n, r in regs.items():
        for f, l, w in r.get("fields", []):
            if NATISH.search(n) or NATISH.search(f):
                hits.append(f"reg {n}@0x{r['offset']:04x}.{f}[{l + w - 1}:{l}]")
    for n, t in tabs.items():
        for f, l, w in t.get("fields", []):
            if NATISH.search(f):
                hits.append(f"table {n}.{f}[{l + w - 1}:{l}]")
    res["natish"] = hits
    for h in hits:
        log("  " + h)

    # 5. BIST memory inventory (every on-die RAM/TCAM the chip self-tests)
    log("\n# BIST memory instances (reg fields *BIST_FAIL*/*BIST_DONE*)")
    mem = sorted({re.sub(r"_?(DRF_)?BIST_(FAIL|DONE).*$", "", f) for n, r in regs.items() if "BIST" in n
                  for f, _, _ in r.get("fields", []) if re.search(r"BIST_(FAIL|DONE)", f)})
    res["bist_mem"] = mem
    log("  " + " ".join(mem))

    # 6. mango (RTL9310) feature diff
    fd = lambda c: set(re.findall(r"#define CONFIG_SDK_CHIP_FEATURE_(\w+)", (
        a.sdk / f"rtk-xgs1210/include/hal/chipdef/{c}/rtk_{c}_feature_def.h").read_text()))
    lf, mf = fd("longan"), fd("mango")
    res["mango_only_features"], res["longan_only_features"] = sorted(mf - lf), sorted(lf - mf)
    log(f"\n# features mango-only: {sorted(mf - lf)}\n# features longan-only: {sorted(lf - mf)}")
    of = a.sdk / "rtk-xgs1210/src/dal/mango/dal_mango_openflow.c"
    if of.exists():
        sf = sorted(set(re.findall(r"OF_SET_FIELD_TYPE_(\w+)", of.read_text(errors="replace"))) - {"END", "NONE"})
        res["mango_of_set_fields"] = sf
        log(f"# mango OpenFlow set-field types: {sf}")

    # 6b. named registers no SDK code references (outside chipdef tables / swcore header)
    used = set()
    tok = re.compile(r"\b(?:LONGAN_(\w+?)r|RTL9300_(\w+?)_ADDR)\b")
    for sub in ("src", "system"):
        for p in (a.sdk / "rtk-xgs1210" / sub).rglob("*.[ch]"):
            if "chipdef" in p.parts or p.name.startswith("swcore_"):
                continue
            for m in tok.finditer(p.read_text(errors="replace")):
                used.add(m.group(1) or m.group(2))
    unused = sorted(n for n in regs if n not in used)
    res["unused_regs"] = unused
    log(f"\n# named regs with no SDK code reference: {len(unused)} of {len(regs)}")
    for n in unused:
        if NATISH.search(n) or n.startswith(("DMY_REG", "HSM", "BOND", "EFUSE", "ENCAP", "EGBW_ENCAP")):
            log(f"  {n}@0x{regs[n]['offset']:04x} " + " ".join(f[0] for f in regs[n].get('fields', [])))

    # 7. vendor binaries vs GPL
    for tag, p in (("stock rtk.ko", STOCK_RTK), ("ST5008F core", ST5008F_CORE)):
        if p.exists():
            br, bt = bin_lists(p)
            res[tag] = compare(tag, regs, tabs, br, bt)
        else:
            log(f"[{tag}] not present: skipped")

    # 8. literal addresses in decompiles not covered by a named register
    unnamed, total = scan_decompiles(covered)
    res["decompile_unnamed"] = unnamed
    log(f"\n# decompile literal switch-core addresses: {total} distinct, not covered by a named reg: {len(unnamed)}")
    for k, v in unnamed.items():
        log(f"  {k}: {', '.join(v[:4])}")

    OUT.write_text(json.dumps(res, indent=1, default=list))
    log(f"\nwrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
