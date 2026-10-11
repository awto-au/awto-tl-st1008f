#!/usr/bin/env python3
"""sdk_feature_map — every RTL930x (Longan) SDK API and hardware feature group vs who uses it.

- Inputs: GPL SDK `github.com/reyalo/Realtek` `sources/` (`--sdk` / env REALTEK_SRC; default private/ sparse clone,
  needs include/rtk, src/rtk, include/dal, src/dal, include/hal, src/hal, system/include/hwp checked out),
  optional olliver 3.5.0 (env OLLIVER_SDK), stock TL-ST1008F `rtk.ko`, ST5008F v2 `core`, OpenWrt realtek tree
  (`--openwrt`), our U-Boot port + kernel patches.
- API: `dal_mapper_t` slots; implemented = assigned by `dal_longan_*Mapper_init`, else `dal_common_unavail`
  (RT_ERR_CHIP_NOT_SUPPORTED). Same for mango/cypress/maple. `Applicable:` chip list from `src/rtk/*.c`.
- Use: stock = callers in `rtk.ko` outside the SDK layers; managed = callers in ST5008F `core` (`jal` targets
  resolved through `.dynsym`) outside the SDK layers.
- HW: registers/tables per `CONFIG_SDK_CHIP_FEATURE_*` group; referenced by SDK code (name), OpenWrt / ours (offset).
- Output `tmp/sdk_feature_map/sdk_feature_map.json`, `api.csv`, `regs.csv`, `tables.md`;
  `--write-doc` regenerates the marked block in docs/SDK-FEATURE-MAP.md. Log `tmp/logs/sdk_feature_map.log`.
"""

import argparse
import csv
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sdk_feature_map.log"
OUT = ROOT / "tmp/sdk_feature_map"
PRIV = ROOT / "private"
DEF_SDK = os.environ.get("REALTEK_SRC", str(PRIV / "reyalo-Realtek/sources"))
STOCK_KO = PRIV / "mtd-backup-20261008-145913/stock-extract/initramfs-1/lib/modules/3.18.24/kernel/drivers/net/switch/rtk/rtk.ko"
MGD_CORE = PRIV / "china/st5008f-v2-extracted/rootfs/usrImage/app/sbin/core"
DEF_OWRT = ROOT / "tmp/openwrt-build/target/linux/realtek/files-6.18"
OURS = [ROOT / "uboot-port/board/tplink/tl-st1008f", ROOT / "openwrt/patches"]
DOC = ROOT / "docs/SDK-FEATURE-MAP.md"
CHIPS = ("longan", "mango", "cypress", "maple")  # 9300, 9310, 8390, 8380
SDK_PREFIX = re.compile(r"^(rtk_|dal_|_dal_|hal_|_hal_|rt_|drv_|_drv_|phy_|reg_|table_|osal_|ioal_|hwp_|rtdrv_|"
                        r"sds_|_sds_|mac_|_mac_|_rtk_|rtl\d|_rtl\d|ext_|diag_|cparser_|rtcore_|rtnic_|nic_|bitop_|"
                        r"rtk\w*Mapper|__)")


def log(msg=""):
    print(msg)
    with LOG.open("a") as f:
        f.write(msg + "\n")


def rd(p):
    try:
        return Path(p).read_text(errors="replace")
    except OSError:
        return ""


def strip_dead(text):
    """Drop `#if 0` / `#if CODE_TBC` regions (CODE_TBC is never defined), keeping any #else branch."""
    out, stack = [], []  # stack of (dead_if, in_else)
    for ln in text.splitlines():
        s = ln.strip()
        if re.match(r"#\s*if", s):
            stack.append([bool(re.match(r"#\s*if\s+(0|CODE_TBC)\b", s)), False])
        elif re.match(r"#\s*else", s) and stack:
            stack[-1][1] = True
        elif re.match(r"#\s*endif", s) and stack:
            stack.pop()
            continue
        dead = any(d and not e for d, e in stack)
        if not dead:
            out.append(ln)
    return "\n".join(out)


def c_files(d):
    return sorted(Path(d).glob("*.c")) if Path(d).is_dir() else []


def func_bodies(text):
    """Top-level C function name -> body (column-0 name, brace-matched)."""
    out = {}
    for m in re.finditer(r"^(?:[A-Za-z_][\w \t\*]*[ \t\*])?(\w+)\s*\([^;{]*?\)\s*\{", text, re.M | re.S):
        i, depth = m.end(), 1
        while depth and i < len(text):
            depth += {"{": 1, "}": -1}.get(text[i], 0)
            i += 1
        out[m.group(1)] = text[m.end():i]
    return out


# ---------- API layer ----------
def mapper_slots(sdk):
    txt = rd(sdk / "include/dal/dal_mapper.h")
    return re.findall(r"\(\*(\w+)\)\s*\(", txt)


def mapper_assign(sdk, chip):
    """slot -> (dal function, preprocessor guard or '')."""
    res = {}
    for f in [sdk / "src/dal/dal_phy.c"] if chip == "phy" else c_files(sdk / f"src/dal/{chip}"):
        stack = []
        for ln in strip_dead(rd(f)).splitlines():
            s = ln.strip()
            if re.match(r"#\s*if", s):
                stack.append(s)
            elif re.match(r"#\s*endif", s) and stack:
                stack.pop()
            m = re.match(r"pMapper->(\w+)\s*=\s*(\w+)\s*;", s)
            if m:
                guard = " && ".join(g for g in stack if "BOOTLOADER" not in g)
                res[m.group(1)] = (m.group(2), guard)
    return res


def dal_bodies(sdk, chip):
    out = {}
    for f in c_files(sdk / f"src/dal/{chip}"):
        for k, v in func_bodies(strip_dead(rd(f))).items():
            out[k] = (f.name, v)
    return out


def classify(fn, bodies):
    if fn not in bodies:
        return "missing"
    body = bodies[fn][1]
    code = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
    if "CHIP_NOT_SUPPORTED" in code or "FEATURE_NOT_SUPPORTED" in code:
        if not re.search(r"\b(reg|table)_\w*(read|write|get|set)\b|_dal_longan_\w+\(|dal_longan_\w+\(", code):
            return "stub"
        return "partial"
    return "impl"


def rtk_api(sdk):
    """slot -> {api, applicable}."""
    out = {}
    for f in c_files(sdk / "src/rtk"):
        txt = rd(f)
        app = {}
        for m in re.finditer(r"\*\s+(rtk_\w+)\s*\n(?:.*\n){0,40}?\s*\*\s*Applicable:\s*\n\s*\*\s*([^\n]*)", txt):
            app.setdefault(m.group(1), m.group(2).strip())
        for name, body in func_bodies(txt).items():
            if not name.startswith("rtk_"):
                continue
            for slot in set(re.findall(r"RT_MAPPER\(unit\)->(\w+)", body)):
                out.setdefault(slot, {"api": name, "applicable": app.get(name, ""), "file": f.name})
    return out


# ---------- hardware groups ----------
REG_ENTRY = re.compile(r"register name\s+INT_LONGAN_(\w+?)_RTL9300 \*/\s*/\* offset address \*/\s*(0x[0-9a-fA-F]+),"
                       r"\s*/\* field numbers \*/\s*(\d+),\s*/\* port index \*/\s*(\d+),\s*(\d+),"
                       r"\s*/\* array index \*/\s*(\d+),\s*(\d+)")
TBL_ENTRY = re.compile(r"table name\s+INT_LONGAN_RTL9300_(\w+) \*/\s*/\* access table set \*/\s*(\d+),"
                       r"\s*/\* access table type \*/\s*(\d+),\s*/\* table size \*/\s*(\d+)")


def grouped(text, entry_re):
    out, grp = [], ""
    for chunk in re.split(r"(#if defined\(CONFIG_SDK_CHIP_FEATURE_\w+\))", text):
        m = re.match(r"#if defined\(CONFIG_SDK_CHIP_FEATURE_(\w+)\)", chunk)
        if m:
            grp = m.group(1)
            continue
        for e in entry_re.finditer(chunk):
            out.append((grp,) + e.groups())
    return out


def sdk_ref_names(sdk):
    """LONGAN_<NAME>r / t identifiers referenced per SDK layer."""
    layers = {"dal": [sdk / "src/dal/longan"], "hal": [sdk / "src/hal/mac", sdk / "src/hal/common"],
              "system": [sdk / "system/drv", sdk / "system/linux/rtdrv", sdk / "system/linux/rtcore"],
              "diag": [sdk / "src/app/diag_v2/src"]}
    out = {}
    for layer, dirs in layers.items():
        regs, tbls = set(), set()
        for d in dirs:
            for f in Path(d).rglob("*.c") if d.is_dir() else []:
                t = rd(f)
                regs |= set(re.findall(r"\bLONGAN_(\w+?)r\b", t))
                tbls |= set(re.findall(r"\bLONGAN_(\w+?)t\b", t))
        out[layer] = (regs, tbls)
    return out


HEX = re.compile(r"0x([0-9a-fA-F]{3,8})\b")


def offsets_in(paths, filt=None, patch=False):
    """Switch-core offsets (0x0000-0xFFFF or 0xBB00xxxx) found in source files."""
    offs, names = set(), set()
    for p in paths:
        files = [p] if p.is_file() else [f for f in p.rglob("*") if f.suffix in (".c", ".h", ".patch")]
        for f in files:
            for ln in rd(f).splitlines():
                if patch and f.suffix == ".patch" and not ln.startswith("+"):
                    continue
                if filt and not filt(f, ln):
                    continue
                names |= set(re.findall(r"RTL930X_(\w+)", ln))
                for h in HEX.findall(ln):
                    v = int(h, 16)
                    if 0xBB000000 <= v <= 0xBB00FFFF:
                        offs.add(v & 0xFFFF)
                    elif len(h) <= 4 and v >= 0x100 and v % 4 == 0:
                        offs.add(v)
    return offs, names


def owrt_filter(f, ln):
    return "930" in f.name or "930" in ln or "otto" in f.name and "930" in ln


# ---------- binaries ----------
def objdump(path, reloc):
    args = ["nice", "-n", "19", "llvm-objdump", "-d", "--no-show-raw-insn"] + (["-r"] if reloc else []) + [str(path)]
    try:  # 19 MB MIPS binary disassembles in ~3 s
        return subprocess.run(args, capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"[objdump] {path}: {type(e).__name__} (limit 60 s)")
        return ""


def call_graph(dis, addr2name=None):
    """callee -> set(callers). Callers from `<name>:` labels; callees from `jal 0xADDR <name>` or R_MIPS_26 sym."""
    g, cur = defaultdict(set), None
    for ln in dis.splitlines():
        m = re.match(r"^[0-9a-f]+ <([\w.$]+)>:", ln)
        if m:
            cur = m.group(1)
            continue
        m = re.search(r"\bjal\s+0x([0-9a-f]+)(?: <([\w.$]+)>)?", ln)
        if m and cur:
            a = int(m.group(1), 16)  # +8: linker la-stub in front of a PIC function called from non-PIC code
            tgt = (addr2name or {}).get(a) or (addr2name or {}).get(a + 8) if addr2name else m.group(2)
            if tgt:
                g[tgt].add(cur)
            continue
        m = re.search(r"R_MIPS_(?:26|LO16)\s+([\w$]+)$", ln)  # rtk.ko is -mlong-calls: lui/addiu/jalr
        if m and cur and not m.group(1).startswith("$"):
            g[m.group(1)].add(cur)
    return g


def stock_use():
    if not STOCK_KO.exists():
        log(f"[stock] missing {STOCK_KO}")
        return {}, set()
    dis = objdump(STOCK_KO, True)
    g = call_graph(dis)
    defined = set(re.findall(r"^[0-9a-f]+ <(\w+)>:", dis, re.M))
    return g, defined


def mgd_use():
    if not MGD_CORE.exists():
        log(f"[mgd] missing {MGD_CORE}")
        return {}, set(), []
    r = subprocess.run(["readelf", "-W", "--dyn-syms", str(MGD_CORE)], capture_output=True, text=True, timeout=30)
    a2n, defined = {}, set()
    for ln in r.stdout.splitlines():
        p = ln.split()
        if len(p) >= 8 and p[3] == "FUNC" and p[6] != "UND":
            a2n[int(p[1], 16)] = p[7]
            defined.add(p[7])
    g = call_graph(objdump(MGD_CORE, False), a2n)
    drv = sorted(n for n in defined if re.match(r"^(drv|subDrv)\w*(Realtek|Longan|Rtk)", n))
    return g, defined, drv


def outside(callers):
    return sorted(c for c in callers if not SDK_PREFIX.match(c))


# ---------- capacity ----------
def capacity(sdk):
    txt = rd(sdk / "src/hal/chipdef/chipdef.c")
    m = re.search(r"rtl9300_capacityInfo =\s*\{.*?#else(.*?)#endif", txt, re.S)
    return dict(re.findall(r"\.(\w+)\s*=\s*([^,]+),", m.group(1))) if m else {}


# ---------- main ----------
# SDK module -> HW feature groups (for the summary table)
MOD_HW = {
    "vlan": ["802_1Q_VLAN___QINQ", "VLAN_PROFILE", "_IEEE802_1V__PROTOCOL_BASED_VLAN", "VLAN_RANGE_CHECK", "VLAN_TRANSLATION"],
    "l2": ["MAC_FORWARDING_CONTROL", "L2_ENTRY_NOTIFICATION", "L2_MISC_", "PORT_ISOLATION"],
    "l3": ["LAYER_3_ROUTING"], "ipmc": ["LAYER_3_ROUTING"], "mcast": ["LAYER_3_ROUTING"],
    "trunk": ["LINK_AGGREGATION"], "stp": ["SPANNING_TREE"], "mirror": ["MIRRORING", "RSPAN", "SFLOW"],
    "rate": ["STORM_CONTROL__B_M_UM_DLF_", "INGRESS_BANDWIDTH_CONTROL", "EGRESS_BANDWIDTH_CONTROL", "METER_MARKER"],
    "qos": ["INGRESS_PRIORITY_DECISION", "SCHEDULING___QUEUE_MANAGEMENT", "REMARKING", "CONGESTION_AVOIDANCE", "802_1QAV"],
    "flowctrl": ["FLOWCONTROL___BACKPRESSURE"], "trap": ["RMA", "APPLICATION_TRAP"],
    "stat": ["MIB_CONTROL", "MIB_COUNTER", "PRIVATE_COUNTER", "DEBUG_COUNTER"],
    "pie": ["PIE_TEMPLATE", "RANGE_CHECK__PORT_VLAN_IP_L4PORT_"], "acl": ["ACL"], "sec": ["ATTACK_PREVENTION"],
    "oam": ["OAM", "RLDP___RLPP"], "eee": ["POWER_SAVING"], "led": ["LED"], "sds": ["PHY___SERDES"],
    "port": ["MAC_CONTROL", "INTERFACE"], "switch": ["DEVICE_CONTROL", "CHIP_INFORMATION", "HW_MISC_", "MISC"],
    "stack": ["DEVICE_CONTROL"], "diag": ["DEBUGGING__ALE__LOOPBACK__DROP_MECHANISM__FC_AND_QM_", "PARSER_HSB", "MODIFIER_HSA", "HSM"],
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sdk", default=DEF_SDK)
    ap.add_argument("--openwrt", default=str(DEF_OWRT))
    ap.add_argument("--write-doc", action="store_true")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.write_text("")
    src = Path(a.sdk)
    xgs, dms = src / "rtk-xgs1210", src / "rtk-dms1250"
    olliver = os.environ.get("OLLIVER_SDK")
    log(f"sdk={src} olliver={olliver or 'absent'}")

    slots = mapper_slots(xgs)
    assign = {c: mapper_assign(xgs, c) for c in CHIPS}
    assign_dms = mapper_assign(dms, "longan")
    phy = mapper_assign(xgs, "phy")  # dal_mgmt hooks dal_phy first, chip mapper overrides
    bodies = dal_bodies(xgs, "longan")
    api = rtk_api(xgs)
    sg, sdef = stock_use()
    mg, mdef, mdrv = mgd_use()
    log(f"slots={len(slots)} longan={len(assign['longan'])} mango={len(assign['mango'])} "
        f"cypress={len(assign['cypress'])} maple={len(assign['maple'])} dms_longan={len(assign_dms)}")

    rows = []
    for s in slots:
        mod = s.split("_")[0] or "init"
        lf, guard = assign["longan"].get(s, ("", ""))
        info = api.get(s, {})
        rapi = info.get("api", "")
        st_callers = outside(sg.get(rapi, set())) if rapi else []
        mg_callers = outside(mg.get(rapi, set())) if rapi else []
        rows.append({
            "slot": s, "module": mod, "rtk_api": rapi, "applicable": info.get("applicable", ""),
            "longan": lf, "longan_guard": guard, "longan_state": classify(lf, bodies) if lf else ("phy" if s in phy else "unavail"),
            "phy": phy.get(s, ("", ""))[0],
            "dms_longan": assign_dms.get(s, ("", ""))[0],
            "mango": assign["mango"].get(s, ("", ""))[0], "cypress": assign["cypress"].get(s, ("", ""))[0],
            "maple": assign["maple"].get(s, ("", ""))[0],
            "stock_ko_has_dal": bool(lf) and lf in sdef, "stock_callers": st_callers[:8],
            "mgd_has_dal": bool(lf) and lf in mdef, "mgd_callers": mg_callers[:8], "mgd_ncallers": len(mg_callers),
        })

    # HW groups
    regs = grouped(rd(xgs / "src/hal/chipdef/longan/rtk_longan_reg_list.c"), REG_ENTRY)
    tbls = grouped(rd(xgs / "src/hal/chipdef/longan/rtk_longan_table_list.c"), TBL_ENTRY)
    refs = sdk_ref_names(xgs)
    if dms.exists():  # 3.8.0 adds references (e.g. PIE_GLB_HIT_INDICATION in dal_longan_acl.c)
        for k, v in sdk_ref_names(dms).items():
            refs[k] = (refs[k][0] | v[0], refs[k][1] | v[1])
    ow = Path(a.openwrt)
    ow_offs, ow_names = offsets_in([ow / "drivers", ow / "net"], owrt_filter) if ow.exists() else (set(), set())
    our_offs, our_names = offsets_in([p for p in OURS if p.exists()], patch=True)
    reg_rows = []
    for grp, name, off, nf, p0, p1, a0, a1 in regs:
        o = int(off, 16)
        reg_rows.append({"group": grp, "reg": name, "off": f"0x{o:04X}", "fields": int(nf),
                         "ports": f"{p0}-{p1}" if p1 != "0" else "", "array": f"{a0}-{a1}" if a1 != "0" else "",
                         **{f"sdk_{k}": name in v[0] for k, v in refs.items()},
                         "openwrt": o in ow_offs or name in ow_names, "ours": o in our_offs or name in our_names})
    tbl_rows = [{"group": g, "table": n, "size": int(sz), "set": int(st), "type": int(ty),
                 **{f"sdk_{k}": n in v[1] for k, v in refs.items()}} for g, n, st, ty, sz in tbls]
    grp = defaultdict(lambda: Counter())
    for r in reg_rows:
        c = grp[r["group"]]
        c["regs"] += 1
        c["dal"] += r["sdk_dal"]
        c["any_sdk"] += r["sdk_dal"] or r["sdk_hal"] or r["sdk_system"] or r["sdk_diag"]
        c["openwrt"] += r["openwrt"]
        c["ours"] += r["ours"]
    for t in tbl_rows:
        grp[t["group"]]["tables"] += 1

    # module summary
    mods = defaultdict(Counter)
    for r in rows:
        m = mods[r["module"]]
        m["slots"] += 1
        m["longan"] += r["longan_state"] in ("impl", "partial", "phy")
        m["stub"] += r["longan_state"] == "stub"
        m["mango"] += bool(r["mango"] or r["phy"])  # both columns include dal_phy slots
        m["mango_only"] += bool(r["mango"]) and r["longan_state"] == "unavail"
        m["stock_use"] += bool(r["stock_callers"])
        m["mgd_use"] += bool(r["mgd_callers"])
        m["applic_9300_unimpl"] += "9300" in r["applicable"] and r["longan_state"] == "unavail"
        m["dms_extra"] += bool(r["dms_longan"]) and not r["longan"]

    cap = capacity(xgs)
    dal_init = re.findall(r"(dal_longan_\w+_init)\(unit", func_bodies(strip_dead(rd(xgs / "src/dal/longan/dal_longan_mapper.c"))).get("dal_longan_init", ""))
    res = {"counts": {"slots": len(slots), **{c: len(assign[c]) for c in CHIPS}, "dms_longan": len(assign_dms), "phy": len(phy),
                      "longan_states": Counter(r["longan_state"] for r in rows),
                      "regs": len(reg_rows), "tables": len(tbl_rows), "hw_groups": len(grp),
                      "mgd_drv_realtek_funcs": len(mdrv)},
           "modules": mods, "hw_groups": grp, "capacity": cap, "dal_longan_init": dal_init,
           "mgd_drv_funcs": mdrv, "api": rows, "regs": reg_rows, "tables": tbl_rows,
           "olliver": olliver or None}
    (OUT / "sdk_feature_map.json").write_text(json.dumps(res, indent=1, default=dict))
    for name, data in (("api.csv", rows), ("regs.csv", reg_rows), ("tables.csv", tbl_rows)):
        with (OUT / name).open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(data[0].keys()))
            w.writeheader()
            for r in data:
                w.writerow({k: (";".join(v) if isinstance(v, list) else v) for k, v in r.items()})
    md = render(res)
    (OUT / "tables.md").write_text(md)
    log(json.dumps(res["counts"], default=dict))
    if a.write_doc and DOC.exists():
        d = DOC.read_text()
        d = re.sub(r"(<!-- generated:begin -->\n).*?(<!-- generated:end -->)", lambda m: m.group(1) + md + m.group(2), d, flags=re.S)
        DOC.write_text(d)
        log(f"wrote {DOC}")


def render(res):
    out = ["### API slots per module (`dal_mapper_t`)", "",
           "| Module | Slots | Longan / Mango (incl. phy) | Stock / ST5008F use | 9300-doc but unimpl |", "|---|---|---|---|---|"]
    for k, m in sorted(res["modules"].items(), key=lambda kv: -kv[1]["slots"]):
        stub = f" ({m['stub']} stub)" if m["stub"] else ""
        out.append(f"| {k} | {m['slots']} | {m['longan']}{stub} / {m['mango']} | {m['stock_use']} / {m['mgd_use']} | "
                   f"{m['applic_9300_unimpl'] or ''} |")
    out += ["", "### HW feature groups (`CONFIG_SDK_CHIP_FEATURE_*`)", "",
            "| Group | Regs / tables | SDK refs (DAL / any) | OpenWrt | Ours |", "|---|---|---|---|---|"]
    for g, c in sorted(res["hw_groups"].items()):
        out.append(f"| {g.strip('_').lower()} | {c['regs']} / {c['tables']} | {c['dal']} / {c['any_sdk']} | "
                   f"{c['openwrt']} | {c['ours']} |")
    out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    main()
