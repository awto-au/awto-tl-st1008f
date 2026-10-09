#!/usr/bin/env python3
"""Names-ledger tooling for the stock loader decompile (see tmp/re/loader-names.md).

  build            loader-names.md rows -> loader-names.sym
  apply            copy Ghidra project to scratch, run ApplyNames + DecompileAll
  rank [N]         most-called bare FUN_ in the named dump (naming candidates)
  ctx <va|name>    callers, callees, strings, MMIO constants of one function
  stats            named / bare counts (functions at VA >= 0x83f00000)

Ledger row:  | 0x83f..... | name | conf | rationale |   conf: C confirmed, I inferred, S speculative
"""
import os, re, shutil, subprocess, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MD = f"{ROOT}/tmp/re/loader-names.md"
SYM = f"{ROOT}/tmp/re/loader-names.sym"
PROJ = f"{ROOT}/private/ghidra"
SCRATCH = f"{ROOT}/tmp/ghidra-scratch"
FULL = f"{PROJ}/stock-loader-full.c"
NAMED = f"{PROJ}/stock-loader-named.c"
LOG = f"{ROOT}/tmp/logs/loader_names.log"
HEAD = "/home/dan/.local/bin/analyzeHeadless"
TEXT_LO = 0x83f00000

ROW = re.compile(r"^\|\s*(0x[0-9a-fA-F]{8})\s*\|\s*([A-Za-z_][\w]*)\s*\|\s*([CIS])\s*\|(.*)\|\s*$")


AUTO = f"{ROOT}/tmp/re/loader-names-auto.md"
BIN = f"{ROOT}/private/stock-loader-20261007/loader.bin"


def ledger():
    d = {}
    for path in (AUTO, MD):  # manual ledger wins
      if not os.path.exists(path):
        continue
      for ln in open(path):
        m = ROW.match(ln)
        if m:
            d[int(m.group(1), 16)] = (m.group(2), m.group(3), m.group(4).strip())
    return d


_bin = None


def cstr(va):
    global _bin
    if _bin is None:
        _bin = open(BIN, "rb").read()
    o = va - 0x83f00000 + 0x5080
    return _bin[o:_bin.index(b"\0", o)].decode("latin1")


def fn_strings(body):
    return [cstr(int(s, 16)) for s in re.findall(r"\bs_\w+?_(83f[a-f0-9]{5})\b", body)]


def san(t, n=40):
    return re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_")[:n]


REGIONS = [
 (0x83f00000, "boot_early"), (0x83f01000, "norsf"), (0x83f02800, "bootm"), (0x83f03b00, "memcmd"),
 (0x83f05a00, "envcmd"), (0x83f06f00, "console"), (0x83f07a00, "malloc"), (0x83f08a00, "image"),
 (0x83f09400, "cli"), (0x83f0a400, "xymodem"), (0x83f0b800, "libc"), (0x83f0dd40, "lzma"),
 (0x83f0fb28, "zlib"), (0x83f12000, "net"), (0x83f14f00, "sysinfo"), (0x83f16c00, "rtkcmd"),
 (0x83f1a16c, "hwprofile"), (0x83f1c2cc, "ioal_nic"), (0x83f1f408, "gpio_spi_i2c"),
 (0x83f22000, "hal_reg"), (0x83f2d794, "hal_probe"), (0x83f31bbc, "dal_phy"),
 (0x83f3f06c, "phy_common"), (0x83f42794, "phy8218b"), (0x83f43cac, "phy8218d"),
 (0x83f4d5a4, "phy8214c"), (0x83f4da9c, "phy_sds_if"), (0x83f5b638, "phy_rxcal"),
 (0x83f66b5c, "mac_drv_reg"), (0x83f6812c, "mac_drv_nicdbg"), (0x83f68604, "mac_drv_sds"),
 (0x83f6bc10, "mac_drv_smi_phy"), (0x83f6f828, "mac_drv_led"), (0x83f6fe8c, "dal_longan_init"),
 (0x83f74338, "dal_longan_port"), (0x83f7a310, "dal_longan_l2"), (0x83f80df4, "dal_longan_flowctrl"),
 (0x83f81e3c, "dal_longan_stack"), (0x83f838fc, "dal_longan_trunk"), (0x83f87690, "dal_longan_eee"),
 (0x83f8b4ac, "sds_rxcal"), (0x83f8ebe4, "dal_longan_sds"), (0x83f90798, "hal_serdes"),
 (0x83fb3c00, "data")]


def region(va):
    r = REGIONS[0][1]
    for lo, nm in REGIONS:
        if va >= lo:
            r = nm
    return r


def cmd_autoseed():
    """Rule-derived names for function families; manual ledger overrides."""
    fns = load(FULL)
    manual = {}
    for ln in open(MD):
        m = ROW.match(ln)
        if m:
            manual[int(m.group(1), 16)] = m.group(2)
    out = {}
    seen = collections.Counter()

    def put(va, name, conf, why):
        if va in manual or va in out:
            return
        seen[name] += 1
        if seen[name] > 1:
            name = f"{name}_{va & 0xffffff:06x}"
        out[va] = (name, conf, why)

    for va, (n, sz, b) in sorted(fns.items()):
        if not bare(n) or va < TEXT_LO:
            continue
        ss = fn_strings(b)
        ids = [t for t in ss if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{5,}", t) and "_" in t and t != "RX_CAL"]
        if ids:
            put(va, ids[0], "C", "function-name string in body")
            continue
        m = [re.search(r"start_([\d.]+)", t) for t in ss]
        m = [x for x in m if x]
        if "RX_CAL" in ss and m:
            put(va, "rxcal_start_" + m[0].group(1).replace(".", "_"), "C", "RX_CAL log string start_x")
            continue
        if "RX_CAL" in ss:
            fm = [t for t in ss if t.startswith("%s,%d : ")]
            if fm:
                put(va, "rxcal_" + san(fm[0].split(":", 1)[1].split("%")[0].split(":")[0] or "step", 24), "I", "RX_CAL log string")
                continue
        if any("MIIM semaphore lock" in t for t in ss):
            sl = re.findall(r"\+ (0x[0-9a-f]+)\)\)\s*\(", b)
            put(va, "phy_op_" + (sl[0] if sl else "x"), "S", "MIIM-locked PHY driver vtable slot")
    for va, (n, sz, b) in sorted(fns.items()):
        if bare(n) and va >= TEXT_LO:
            m = re.search(r"\(&PTR_\w*?_(83fa[0-9a-f]{4})\)\[\*\(int \*\)\(&DAT_83fa1dc4", b)
            if m:
                put(va, "nic_dispatch_" + m.group(1)[-4:], "I", "indirect call via per-NIC-type ops table 0x83fa1dc4")
    for va, (n, sz, b) in sorted(fns.items()):
        if bare(n) and va >= TEXT_LO and sz < 520 and "FUN_83f228c8" in b + "hal_get_ctrl":
            m = re.search(r"\+ 4\) \+ 0x18\) \+ (0x[0-9a-f]+)\)", b)
            if m and ("hal_get_ctrl" in b or "FUN_83f228c8" in b):
                put(va, "mac_drv_op_" + m.group(1)[2:], "S", "dispatch via chip->mac_ops slot " + m.group(1))
    for va, (n, sz, b) in sorted(fns.items()):
        if bare(n) and va >= TEXT_LO and va not in out and va not in manual and 0x83f31bbc <= va < 0x83f3f06c:
            cs = [c for c in set(CALL.findall(b)) if c.startswith("FUN_83f")]
            ops = [out[int(c[4:], 16)][0] for c in cs if int(c[4:], 16) in out and out[int(c[4:], 16)][0].startswith("phy_op_")]
            if ops:
                put(va, "dal_phy_api_" + ops[0][7:], "S", "locked wrapper around " + ops[0])
    # thunks follow their target
    for va, (n, sz, b) in fns.items():
        if n.startswith("thunk_FUN_"):
            t = int(n[10:], 16)
            tn = out.get(t, (None,))[0] or manual.get(t)
            if tn:
                put(va, "thunk_" + tn, "I", "thunk")
    for va, (n, sz, b) in sorted(fns.items()):
        if bare(n) and va >= TEXT_LO and va not in out and va not in manual and va < 0x83fb3c00:
            put(va, f"s_{region(va)}_{va & 0xffffff:06x}", "S", "region tag only")
    with open(AUTO, "w") as f:
        f.write("# auto-derived (scripts/loader_names.py autoseed); do not edit\n\n| va | name | conf | rationale |\n|---|---|---|---|\n")
        for va in sorted(out):
            f.write(f"| 0x{va:08x} | {out[va][0]} | {out[va][1]} | {out[va][2]} |\n")
    print(len(out), "auto rows ->", AUTO)


def cmd_build():
    d = ledger()
    with open(SYM, "w") as f:
        for va in sorted(d):
            f.write(f"{d[va][0]}\t0x{va:08x}\n")
    print(f"{len(d)} entries -> {SYM}")


def cmd_apply():
    cmd_build()
    if os.path.exists(SCRATCH):
        shutil.rmtree(SCRATCH)
    os.makedirs(SCRATCH)
    for e in ("stock-loader-mapped.gpr", "stock-loader-mapped.rep"):
        s = f"{PROJ}/{e}"
        (shutil.copytree if os.path.isdir(s) else shutil.copy)(s, f"{SCRATCH}/{e}")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    out = f"{ROOT}/tmp/stock-loader-named.c"
    # per-function decompile bound lives in DecompileAll (60 s); whole run ~minutes
    args = [HEAD, SCRATCH, "stock-loader-mapped", "-process", "loader.bin", "-noanalysis",
            "-scriptPath", f"{ROOT}/scripts/ghidra",
            "-postScript", "ApplyNames.java", SYM,
            "-postScript", "DecompileAll.java", out]
    with open(LOG, "w") as lg:
        r = subprocess.run(args, stdout=lg, stderr=subprocess.STDOUT)
    print("headless rc", r.returncode, "log", LOG)
    if r.returncode == 0 and os.path.exists(out):
        shutil.move(out, NAMED)
        print("->", NAMED)


FUNC = re.compile(r"^// FUNC (0x[0-9a-f]+) (\S+) size=(\d+)$", re.M)


def load(path=None):
    txt = open(path or (NAMED if os.path.exists(NAMED) else FULL)).read()
    ms = list(FUNC.finditer(txt))
    fns = {}
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(txt)
        fns[int(m.group(1), 16)] = (m.group(2), int(m.group(3)), txt[m.end():end])
    return fns


CALL = re.compile(r"\b([A-Za-z_]\w*)\(")


def graph(fns):
    names = {v[0]: va for va, v in fns.items()}
    callers = collections.defaultdict(set)
    callees = {}
    for va, (n, sz, body) in fns.items():
        cs = set()
        for c in CALL.findall(body):
            if c in names and c != n:
                cs.add(c)
                callers[c].add(n)
        callees[n] = cs
    return names, callers, callees


TAG = re.compile(r"^s_[a-z0-9_]+_[0-9a-f]{6}$")


def bare(n):
    """Bare = default FUN_ name or a region-tag-only placeholder."""
    return n.startswith("FUN_") or n.startswith("thunk_FUN_") or bool(TAG.match(n))


def cmd_stats():
    fns = {va: v for va, v in load().items() if va >= TEXT_LO}
    nb = sum(1 for v in fns.values() if bare(v[0]))
    print(f"funcs >= 0x83f00000: {len(fns)}  named: {len(fns) - nb}  bare: {nb}")


def cmd_rank(n=40):
    fns = load()
    names, callers, _ = graph(fns)
    rows = [(len(callers[v[0]]), va, v[0], v[1]) for va, v in fns.items()
            if bare(v[0]) and va >= TEXT_LO]
    rows.sort(reverse=True)
    for c, va, nm, sz in rows[:n]:
        print(f"{c:4d} callers  0x{va:08x} {nm} size={sz}")


STR = re.compile(r'"((?:[^"\\]|\\.){3,})"')
MMIO = re.compile(r"0x(?:b[b8f]|a[0-9a-f]|b4)[0-9a-f]{6}\b")


def cmd_ctx(arg, full=False):
    fns = load()
    names, callers, callees = graph(fns)
    va = int(arg, 16) if arg.startswith("0x") else names[arg]
    n, sz, body = fns[va]
    print(f"{n} @0x{va:08x} size={sz}")
    print("callers:", ", ".join(sorted(callers[n]))[:600])
    print("callees:", ", ".join(sorted(callees[n]))[:600])
    print("strings:", [s for s in STR.findall(body)][:12])
    print("mmio:", sorted(set(MMIO.findall(body))))
    if full:
        print(body)


def cmd_add(txt):
    """stdin lines: <va6|va8> <name> <C|I|S> [why...] -> appended to loader-names.md"""
    have = ledger()
    n = 0
    with open(MD, "a") as f:
        for ln in txt.splitlines():
            t = ln.split(None, 3)
            if len(t) < 3 or ln.startswith("#"):
                continue
            va = int(t[0], 16)
            va = va if va > 0xffffff else 0x83000000 + va
            f.write(f"| 0x{va:08x} | {t[1]} | {t[2]} | {t[3] if len(t) > 3 else ''} |\n")
            n += 1
    print(n, "rows added")


def cmd_peek(vas, maxc=700):
    """Compact bodies (no blank/decl lines) for quick reading."""
    fns = load()
    for va in vas:
        va = va if va > 0xffffff else 0x83000000 + va
        n, sz, b = fns[va]
        ls = [l.strip() for l in b.splitlines() if l.strip() and not re.match(r"^(undefined\d?|u?int|char|byte|ushort|code|void|short|long)\b[^=(]*;$", l.strip())]
        print(f"== {va & 0xffffff:06x} {n} {sz}\n" + " ".join(ls)[:maxc])


def cmd_brief(lo, hi):
    """One line per bare function in [lo,hi): size, #callers, strings, callees."""
    fns = load()
    names, callers, callees = graph(fns)
    for va, (n, sz, b) in sorted(fns.items()):
        if not bare(n) or not lo <= va < hi:
            continue
        ss = [san(t, 30) for t in fn_strings(b) if not t.startswith("Err:0x%x:sem")][:2]
        cn = sorted(callees[n], key=lambda x: bare(x))
        cs = [re.sub(r"^s_([a-z0-9_]+)_([0-9a-f]{6})$", r"~\2", c) for c in cn][:5]
        mm = sorted(set(MMIO.findall(b)))[:2]
        print(f"{va & 0xffffff:06x} {sz:4d} c{len(callers[n]):<3d} {ss} {','.join(cs)} {mm if mm else ''}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a:
        print(__doc__)
    elif a[0] == "build":
        cmd_build()
    elif a[0] == "add":
        cmd_add(sys.stdin.read())
    elif a[0] == "peek":
        cmd_peek([int(x, 16) for x in a[1:]])
    elif a[0] == "brief":
        cmd_brief(int(a[1], 16), int(a[2], 16))
    elif a[0] == "autoseed":
        cmd_autoseed()
    elif a[0] == "apply":
        cmd_apply()
    elif a[0] == "stats":
        cmd_stats()
    elif a[0] == "rank":
        cmd_rank(int(a[1]) if len(a) > 1 else 40)
    elif a[0] == "ctx":
        cmd_ctx(a[1], len(a) > 2)
