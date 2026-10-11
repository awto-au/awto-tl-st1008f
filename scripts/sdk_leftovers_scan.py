#!/usr/bin/env python3
"""sdk_leftovers_scan — offline scan of Realtek RTL93xx SDK drops and vendor firmware for leftovers (debug/test/disabled code).

- Inputs: GPL SDK clone (`github.com/reyalo/Realtek` `sources/`; `--sdk` or env REALTEK_SRC), optional
  `olliver/realtek_sdk` clone (`--olliver`), stock TL-ST1008F extract and ST5008F v2 extract under `private/`.
- Reports per section (see docs/SDK-LEFTOVERS.md): markers in Longan code, ext_9300 diag verbs, 9300-enabled
  debug verbs, ASIC drop-reason counters, SerDes eye/PRBS regs, auto-recover regs, rtdrv/rtcore capability checks,
  chip-rev branches, U-Boot test commands vs stock loader, vendor-binary symbol/string presence, managed-firmware
  static keys and auth (fingerprints only, never key material), internal leaks (counts only).
- Output: `tmp/sdk_leftovers/scan.json`; log `tmp/logs/sdk_leftovers_scan.log`. No hardware access.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sdk_leftovers_scan.log"
OUT = ROOT / "tmp/sdk_leftovers/scan.json"
PRIV = ROOT / "private"
STOCK = PRIV / "mtd-backup-20261008-145913/stock-extract/initramfs-1"
STOCK_KO = STOCK / "lib/modules/3.18.24/kernel"
STOCK_LOADER = PRIV / "stock-loader-20261007/loader.bin"
MGD = PRIV / "china/st5008f-v2-extracted"
# mirrors of github.com/reyalo/Realtek (sources/) and olliver/realtek_sdk; default = private/ copies
DEF_SDK = os.environ.get("REALTEK_SRC", str(PRIV / "reyalo-Realtek/sources"))
DEF_OLLIVER = os.environ.get("OLLIVER_SDK", str(PRIV / "olliver-realtek_sdk"))
DBG_CNTR_BASE = 0xB5B8  # STAT_PRVTE_DROP_COUNTER0, stride 4 (swcore_rtl9300.h)


def log(msg=""):
    print(msg)
    with LOG.open("a") as f:
        f.write(msg + "\n")


def rd(p):
    try:
        return Path(p).read_text(errors="replace")
    except OSError:
        return ""


def strings(path, n=4):
    """Printable ASCII runs, like `strings -n`; pure Python so it works on any ELF/blob."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return []
    return [m.group().decode() for m in re.finditer(rb"[\x20-\x7e]{%d,}" % n, data)]


def nm_syms(path, dyn=False):
    try:
        r = subprocess.run(["nm", "-D" if dyn else "-a", str(path)], capture_output=True, text=True, timeout=10)  # nm on a 5 MB .ko: <1 s
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"[nm] {path}: {type(e).__name__} (limit 10 s)")
        return set()
    return {ln.split()[-1] for ln in r.stdout.splitlines() if ln.strip()}


def nm_undef(path):
    try:
        r = subprocess.run(["nm", "-u", str(path)], capture_output=True, text=True, timeout=10)  # nm on a 5 MB .ko: <1 s
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"[nm] {path}: {type(e).__name__} (limit 10 s)")
        return set()
    return {ln.split()[-1] for ln in r.stdout.splitlines() if ln.strip()}


# ---------- sections ----------
def markers(sdk):
    """TODO/FIXME/#if 0/workaround in Longan/9300 files (both SDK trees)."""
    pat = {"todo_fixme_hack": re.compile(r"\b(TODO|FIXME|HACK)\b"), "if0": re.compile(r"^\s*#\s*if\s+0\b"),
           "workaround": re.compile(r"workaround", re.I), "zyxel": re.compile(r"zyxel", re.I)}
    res = {}
    for tree in ("rtk-xgs1210", "rtk-dms1250"):
        base = sdk / tree
        hits = {k: [] for k in pat}
        for f in base.rglob("*.[ch]"):
            n = f.name.lower()
            if not ("longan" in n or "9300" in n or "930x" in n):
                continue
            for i, ln in enumerate(rd(f).splitlines(), 1):
                for k, rx in pat.items():
                    if rx.search(ln):
                        hits[k].append(f"{f.relative_to(sdk)}:{i}: {ln.strip()[:120]}")
        res[tree] = {k: {"count": len(v), "items": v[:60]} for k, v in hits.items()}
        log(f"[markers] {tree}: " + ", ".join(f"{k}={len(v)}" for k, v in hits.items()))
    return res


def ext9300_verbs(sdk):
    cli = sdk / "rtk-dms1250/src/app/diag_v2/config/ext/ext_9300.cli"
    verbs = [ln.strip() for ln in rd(cli).splitlines() if ln.strip() and not ln.startswith("//") and not ln.startswith("#")]
    log(f"[ext_9300] {len(verbs)} verbs in {cli.relative_to(sdk)}")
    return verbs


DEBUG_KW = re.compile(r"memory|test|eye|prbs|sym-err|cali|efuse|loopback|hs[abm]\b|sw_wd|batch|flashtest|testmode|table|wholedump", re.I)


def enabled_debug_verbs(sdk):
    """diag_v2 verbs whose CMD_* flag is #defined for 9300 (cmd_flag_common/rtl9300/phy) and look like debug/test."""
    d = sdk / "rtk-dms1250/src/app/diag_v2"
    flags = set()
    for h in ("cmd_flag_common.h", "cmd_flag_rtl9300.h", "cmd_flag_phy.h"):
        flags |= set(re.findall(r"^#define\s+(CMD_\w+)", rd(d / "include/flag" / h), re.M))
    out = []
    for cli in sorted((d / "config").glob("*.cli")):
        flag = None
        for ln in rd(cli).splitlines():
            m = re.match(r"#ifdef\s+(CMD_\w+)", ln)
            if m:
                flag = m.group(1)
                continue
            if ln.startswith("#endif"):
                flag = None
                continue
            if flag in flags and ln[:1].isalpha() and DEBUG_KW.search(ln):
                out.append(f"{cli.name}: {ln.strip()}")
    log(f"[diag] {len(flags)} CMD flags on for 9300; {len(out)} debug/test verbs enabled")
    return out


def dbg_counters(sdk):
    """RTL9300 drop-reason counters: hal_getDbgCntr case labels -> STAT_PRVTE_DROP_COUNTERn -> address."""
    src = rd(sdk / "rtk-dms1250/src/hal/mac/mac_debug.c")
    i = src.find("if (HWP_9300_FAMILY_ID(unit))", src.find("hal_getDbgCntr"))
    blk = src[i:src.find("#endif", i)]
    res, pend = [], []
    for m in re.finditer(r"case (RTL9300_DBG_CNTR_\w+):|LONGAN_STAT_PRVTE_DROP_COUNTER(\d+)r|(break;)", blk):
        if m.group(3):
            pend = []  # cases that fall to a bare break have no counter
        elif m.group(1):
            pend.append(m.group(1).replace("RTL9300_DBG_CNTR_", ""))
        else:
            n = int(m.group(2))
            for name in pend:
                res.append({"reason": name, "idx": n, "addr": f"0x{DBG_CNTR_BASE + 4 * n:04X}"})
            pend = []
    log(f"[dbgcntr] {len(res)} reasons -> {len({r['idx'] for r in res})} counters at 0x{DBG_CNTR_BASE:04X}..")
    return res


def sds_regs(sdk):
    src = rd(sdk / "rtk-dms1250/src/dal/longan/dal_longan_sds.c")
    eye = dict(re.findall(r"#define\s+(EYE_\w+)\s+(0x[0-9A-Fa-f]+|\d+)", src))
    funcs = re.findall(r"^(dal_longan_sds_(?:testMode_set|eyeMonitor_start|eyeParam_[gs]et|symErr_get|loopback_set|"
                       r"fiberUnidirEnable_set|leq_adapt|rxCali))\(", src, re.M)
    lines = {f: src[:src.find(f + "(")].count("\n") + 1 for f in funcs}
    log(f"[sds] {len(eye)} EYE_* defines, funcs {sorted(lines)}")
    return {"eye_defines": eye, "funcs": lines}


def auto_recover(sdk):
    h = rd(sdk / "rtk-dms1250/system/include/private/drv/swcore/swcore_rtl9300.h")
    regs = dict(re.findall(r"#define\s+RTL9300_((?:TRIG_)?AUTO_RECOVER_\w+?|IMR_AUTO_REC|ISR_AUTO_REC|"
                           r"STAT_PRVTE_DROP_COUNTER0|PKB_ACC_DEBUG_CTRL|TEST_MODE_ALE\w*?|THERMAL_METER_\w+?|"
                           r"IMR_TM_RLFD|ISR_TM_RLFD)_ADDR\s+\((0x[0-9A-Fa-f]+)\)", h))
    wa = rd(sdk / "rtk-dms1250/src/dal/longan/dal_longan_waFunc.c")
    gate = "CONFIG_SDK_WA_PKTBUF_WATCHDOG" in rd(sdk / "rtk-dms1250/src/dal/dal_waMon.c")
    log(f"[autorec] {len(regs)} regs; waFunc swQueRst={'_dal_longan_swQueRst_set' in wa}; gated={gate}")
    return {"regs": regs, "swQueRst_present": "_dal_longan_swQueRst_set" in wa, "gated_by_WA_PKTBUF_WATCHDOG": gate}


def cap_checks(sdk):
    """rtdrv (setsockopt) and rtcore (ioctl) entry points: any capable() check?"""
    res = {}
    for rel in ("system/linux/rtdrv/rtdrv_netfilter.c", "system/linux/rtdrv/ext/rtdrv_netfilter_ext_9300.c",
                "system/linux/rtcore/rtcore_drv.c"):
        s = rd(sdk / "rtk-dms1250" / rel)
        res[rel] = {"capable": len(re.findall(r"\bcapable\s*\(", s)),
                    "nf_register_sockopt": "nf_register_sockopt" in s,
                    "mem_write_ops": re.findall(r"case (RTDRV_DEBUG_MEM_WRITE|RTDRV_REG_REGISTER_SET|RTCORE_REG_WRITE):", s)}
    for k in ("rtdrv.ko", "rtcore.ko"):
        hits = list(STOCK_KO.rglob(k)) + list((MGD / "initramfs").rglob(k)) if MGD.exists() else list(STOCK_KO.rglob(k))
        for p in hits:
            u = nm_undef(p)
            res[str(p.relative_to(ROOT))] = {"imports_capable": any("capable" in x for x in u),
                                             "imports_nf_register_sockopt": "nf_register_sockopt" in u}
    log(f"[cap] {json.dumps(res)}")
    return res


def chip_rev(sdk):
    out = []
    for f in (sdk / "rtk-dms1250").rglob("*.c"):
        n = f.name
        if not ("longan" in n or "9300" in n):
            continue
        for i, ln in enumerate(rd(f).splitlines(), 1):
            if re.search(r"HWP_CHIP_REV|IF_CHIP_TYPE_1", ln):
                out.append(f"{f.relative_to(sdk)}:{i}: {ln.strip()[:140]}")
    log(f"[chiprev] {len(out)} branches in longan/9300 files")
    return out


def uboot_tests(sdk):
    bc = rd(sdk / "uboot-dms1250/board/Realtek/rtl9300/board_cmd.c")
    cmds = re.findall(r"U_BOOT_CMD\(\s*(\w+),", bc)
    s = set(strings(STOCK_LOADER, 3))
    pres = {c: c in s for c in cmds}
    log(f"[uboot] rtl9300 board_cmd.c test cmds {cmds}; in stock loader: {[c for c, v in pres.items() if v]}")
    return pres


def stock_bins():
    res = {}
    want = ["dal_longan_port_pktbuf_watchdog", "dal_longan_port_serdes_watchdog", "dal_longan_sds_eyeMonitor_start",
            "dal_longan_sds_testMode_set", "dal_longan_sds_symErr_get", "debug_mem_write", "pktbuf_rw_test",
            "_cal_para_efuse_write", "do_rtdrv_ext_set_ctl", "hal_getDbgCntr"]
    for p in sorted(STOCK_KO.rglob("rt*.ko")):
        syms = nm_syms(p)
        res[p.name] = {w: w in syms for w in want}
    diag = STOCK / "bin/diag"
    s = set(strings(diag, 3))
    res["diag_tokens"] = {t: t in s for t in ("pktgen", "qc", "loopback-test", "phy-cali", "write-efuse", "eye-monitor",
                                              "rx-cali", "prbs31", "flashtest", "batch", "unittest")}
    log(f"[stock] {json.dumps(res)}")
    return res


def managed():
    """ST5008F v2 1.2.0: static keys (type + modulus fingerprint only), empty-password accounts, debug-shell auth."""
    res = {}
    data = MGD / "rootfs/usrImage/data"
    for f in sorted(list(data.glob("*.key")) + list(data.glob("*key*.pem")) + list((MGD / "initramfs/etc/ssh").glob("ssh_host_*_key"))):
        head = rd(f).splitlines()[:1]
        res[str(f.relative_to(ROOT))] = {"pem_header": head[0] if head and head[0].startswith("-----") else "none",
                                         "sha256_prefix": hashlib.sha256(f.read_bytes()).hexdigest()[:12]}
    sh = rd(MGD / "initramfs/etc/shadow")
    res["shadow_empty_pw_accounts"] = [ln.split(":")[0] for ln in sh.splitlines() if ln.count(":") > 1 and ln.split(":")[1] == ""]
    cli = set(strings(MGD / "rootfs/usrImage/app/sbin/cli_server", 4))
    res["cli_tokens"] = {t: t in cli for t in ("debug shell", "debug bcm-cli", "BCM CLI for debug", "Authorized code: %s ",
                                               "/tplink/exe/data/normal-shell-pub-key.pem", "rsa_verify fail")}
    core = MGD / "rootfs/usrImage/app/sbin/core"
    cs = strings(core, 6)
    res["core_cparser_cmds"] = sum(1 for x in cs if x.startswith("cparser_cmd_"))
    res["core_risky_cmds"] = sorted({x for x in cs if re.match(r"cparser_cmd_(debug_set_memory|debug_flashtest|serdes_eye_monitor|"
                                                                 r"serdes_set_sdsId_10g_prbs)", x)})
    log(f"[managed] keys={len([k for k in res if k.startswith('private')])} empty_pw={res['shadow_empty_pw_accounts']} "
        f"core_cparser={res['core_cparser_cmds']}")
    return res


def leaks(sdk, olliver):
    pats = {"coverity_url": r"172\.21\.12\.139", "internal_wiki": r"172\.21\.68\.36", "internal_svn": r"cadinfo\.realtek",
            "home_paths": r"/home/[a-z_]+/"}
    res = {}
    roots = [sdk] + ([olliver] if olliver.exists() else [])
    for k, p in pats.items():
        try:
            r = subprocess.run(["rg", "-c", "-I", "--no-messages", p, *map(str, roots)], capture_output=True, text=True, timeout=30)  # rg over both trees measured <10 s
            res[k] = sum(int(x.rsplit(":", 1)[-1]) for x in r.stdout.split())
        except (OSError, subprocess.TimeoutExpired, ValueError) as e:
            log(f"[leaks] rg {k}: {type(e).__name__} (limit 30 s)")
            res[k] = None
    ppt = olliver / "loader/u-boot-2011.12/ddr_cli_tools/DRAM_Bring_Up_Conf_130610.ppt"
    res["dram_bringup_ppt"] = ppt.exists()
    res["stray_8051_rtl8213_func"] = (sdk / "rtk-xgs1210/unittest/sdk/rtl8213_func.c").exists()
    log(f"[leaks] {res}")
    return res


SHELL_RE = r"(?i)(cli_bcm.*|wmcli_bcm.*|cli_shellAuth|wmcli_shellAuth|cli_bcmshellTp)"


def decompile_shell():
    """Ghidra headless: ST5008F cli_server debug-shell auth + bcm-cli handlers -> private/ghidra/sdk-leftovers/ (never published).
    Bound 90 s: whole decompile measured ~40 s warm (tmp/logs/sdk_leftovers_ghidra_cli.log), x1.25 plus JVM cold start; expiry logged, section None."""
    out = PRIV / "ghidra/sdk-leftovers"
    out.mkdir(parents=True, exist_ok=True)
    out_c = out / "st5008f-cli-shell.c"
    cmd = ["nice", "-n", "19", "analyzeHeadless", str(out), "proj-cli", "-import",
           str(MGD / "rootfs/usrImage/app/sbin/cli_server"), "-overwrite", "-scriptPath", str(ROOT / "scripts/ghidra"),
           "-postScript", "DecompileMatching.java", str(out_c), SHELL_RE, "-deleteProject"]
    try:
        with (ROOT / "tmp/logs/sdk_leftovers_ghidra_cli.log").open("w") as fh:
            subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=90)
    except subprocess.TimeoutExpired:
        log("[decompile] TIMEOUT after 90 s (cli_server analysis)")
        return None
    c = rd(out_c)
    res = {"funcs": re.findall(r"// FUNC 0x[0-9a-f]+ (\w+)", c),
           "shellAuth_time_seeded_rand": "srand(__seed)" in c and "time(" in c,
           "shellAuth_rsa_verify": "RsaSSL_Verify" in c,
           "bcmCli_calls_shellAuth": "shellAuth" in c.split("wmcli_bcmCli", 1)[-1].split("// FUNC", 1)[0]}
    log(f"[decompile] {res}")
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sdk", default=DEF_SDK)
    ap.add_argument("--olliver", default=DEF_OLLIVER)
    ap.add_argument("--decompile", action="store_true", help="also run the Ghidra cli_server shell-auth decompile (about 1-2 min)")
    a = ap.parse_args()
    sdk, oll = Path(a.sdk), Path(a.olliver)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("")
    if not (sdk / "rtk-dms1250").exists():
        log(f"SDK tree not found at {sdk} (set --sdk or REALTEK_SRC)")
        return 1
    rep = {"markers": markers(sdk), "ext9300_verbs": ext9300_verbs(sdk), "debug_verbs_9300": enabled_debug_verbs(sdk),
           "dbg_counters": dbg_counters(sdk), "serdes": sds_regs(sdk), "auto_recover": auto_recover(sdk),
           "capability": cap_checks(sdk), "chip_rev": chip_rev(sdk), "uboot_tests": uboot_tests(sdk),
           "stock": stock_bins() if STOCK.exists() else None, "managed": managed() if MGD.exists() else None,
           "leaks": leaks(sdk, oll), "shell_decompile": decompile_shell() if a.decompile and MGD.exists() else None}
    OUT.write_text(json.dumps(rep, indent=1))
    log(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
