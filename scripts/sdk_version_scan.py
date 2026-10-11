#!/usr/bin/env python3
"""sdk_version_scan — Realtek switch SDK tree: version + Longan (RTL930x) presence; optional Longan-relevant diff.

- `scan TREE...`: per tree print RT_VERSION_SDK, SDK dir-name versions, highest `[SDK_x.y.z]` API tag,
  chip families (hal/chipdef/*), dal/longan + hal/mac + drv/nic file counts (non-empty vs 0-byte stubs).
- `diff OLD NEW`: OLD/NEW = SDK roots (dir holding include/ + system/). Reports chipdef/longan identity,
  longan feature flips, rtk API added/removed, system/drv + private/drv file/function changes, new hw profiles.
- Vendor GPL drops ship some trees as 0-byte .c + prebuilt .o: "stub" counts show that.
- Log: tmp/logs/sdk_version_scan.log. Offline only. Doc: docs/SDK-SOURCES.md.
"""

import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sdk_version_scan.log"
TAG_RE = re.compile(rb"\[SDK_(\d+)\.(\d+)\.(\d+)\]")
DIRVER_RE = re.compile(r"(rtk-ms-sdk-[\d.]+|realtek_v[\d.]+|rtk-ms-phyOnly-[\d.]+)")
FUNC_RE = re.compile(r"^(?:static\s+)?(?:[A-Za-z_][\w\s\*]*?)\b([A-Za-z_]\w*)\s*\([^;]*$", re.M)
API_RE = re.compile(r"^(rtk_\w+)\s*\(", re.M)


def log(msg=""):
    print(msg)
    with LOG.open("a") as f:
        f.write(msg + "\n")


def files(base, pat):
    return sorted(p for p in Path(base).rglob(pat) if p.is_file()) if Path(base).is_dir() else []


def stub_count(paths):
    paths = list(paths)
    return f"{sum(1 for p in paths if p.stat().st_size > 0)} real / {sum(1 for p in paths if p.stat().st_size == 0)} stub"


def scan(tree):
    tree = Path(tree)
    log(f"== {tree}")
    for v in files(tree, "rt_version.h"):
        m = re.search(r'RT_VERSION_SDK\s+(.*)', v.read_text(errors="replace"))
        log(f"  RT_VERSION_SDK {m.group(1).strip() if m else '?'}  ({v.relative_to(tree)})")
    dirvers = sorted({m.group(1) for p in tree.rglob("*") if p.is_dir() for m in [DIRVER_RE.search(p.name)] if m})
    log(f"  dir-name versions: {', '.join(dirvers) or '-'}")
    tags = set()
    for p in list(files(tree, "*.h")) + list(files(tree, "*.c")):
        if "include/rtk" in str(p) or "/src/rtk/" in str(p):
            tags.update(TAG_RE.findall(p.read_bytes()))
    top = max((tuple(int(x) for x in t) for t in tags), default=None)
    log(f"  highest [SDK_x.y.z] tag in rtk API: {'.'.join(map(str, top)) if top else '-'}")
    fams = sorted({p.name for c in tree.rglob("chipdef") if c.is_dir() for p in c.iterdir() if p.is_dir()})
    log(f"  chipdef families: {', '.join(fams) or '-'}")
    for label, pat in [("dal/longan *.c", "dal/longan/*.c"), ("hal/chipdef/longan *.h", "chipdef/longan/*.h"),
                       ("hal/mac *.c", "hal/mac/*.c"), ("drv/nic/nic_rtl9300.c", "drv/nic/nic_rtl9300.c")]:
        hits = [p for p in tree.rglob(pat.split("/")[-1]) if p.is_file() and pat.rsplit("/", 1)[0] in str(p.parent)]
        log(f"  {label}: {stub_count(hits) if hits else 'absent'}")


def norm_diff_lines(a, b):
    r = subprocess.run(["diff", "-w", "-I", r"\$Revision", "-I", r"\$Date", str(a), str(b)],
                       capture_output=True, text=True, errors="replace")  # local text diff, sub-second
    return sum(1 for ln in r.stdout.splitlines() if ln[:1] in "<>")


def funcs(path):
    t = path.read_text(errors="replace") if path.exists() else ""
    return {m.group(1) for m in FUNC_RE.finditer(t) if m.group(1) not in ("if", "for", "while", "switch", "return")}


def diff(old, new):
    old, new = Path(old), Path(new)
    log(f"== diff OLD {old}\n        NEW {new}")
    cd = "include/hal/chipdef/longan"
    for f in sorted({p.name for p in (old / cd).glob("*.h")} | {p.name for p in (new / cd).glob("*.h")}):
        a, b = old / cd / f, new / cd / f
        st = "only OLD" if not b.exists() else "only NEW" if not a.exists() else \
            "identical" if a.read_bytes() == b.read_bytes() else f"{norm_diff_lines(a, b)} lines differ"
        log(f"  {cd}/{f}: {st}")
    fd = "rtk_longan_uboot_feature_def.h"
    if (old / cd / fd).exists() and (new / cd / fd).exists():
        def flags(p):
            return {n: d for d, n in re.findall(r"#(define|undef) (CONFIG_SDK_CHIP_FEATURE_\w+)", p.read_text())}
        fa, fb = flags(old / cd / fd), flags(new / cd / fd)
        for k in sorted(fb):
            if fa.get(k) != fb[k]:
                log(f"  feature {k}: {fa.get(k)} -> {fb[k]}")
    oa = {p.name for p in (old / "include/hal/chipdef").iterdir() if p.is_dir()}
    na = {p.name for p in (new / "include/hal/chipdef").iterdir() if p.is_dir()}
    log(f"  chipdef families added: {sorted(na - oa)} removed: {sorted(oa - na)}")
    api_o = {m for p in (old / "include/rtk").glob("*.h") for m in API_RE.findall(p.read_text(errors='replace'))}
    api_n = {m for p in (new / "include/rtk").glob("*.h") for m in API_RE.findall(p.read_text(errors='replace'))}
    log(f"  rtk API: OLD {len(api_o)} NEW {len(api_n)}; added {len(api_n - api_o)} removed {len(api_o - api_n)}")
    appl = {}
    for p in (new / "include/rtk").glob("*.h"):
        for m in re.finditer(r"Function Name:\s*\n\s*\*\s*(rtk_\w+)(.*?)\*/", p.read_text(errors="replace"), re.S):
            a = re.search(r"Applicable:\s*\n\s*\*\s*(.*)", m.group(2))
            appl[m.group(1)] = a.group(1).strip() if a else "?"
    for n in sorted(api_n - api_o):
        log(f"    + {n}  [{appl.get(n, '?')}]{'  <-- 9300' if '9300' in appl.get(n, '') else ''}")
    for n in sorted(api_o - api_n):
        log(f"    - {n}")
    for sub in ["system/drv", "system/include/private/drv"]:
        ro = {p.relative_to(old / sub) for p in files(old / sub, "*.[ch]")}
        rn = {p.relative_to(new / sub) for p in files(new / sub, "*.[ch]")}
        low = {str(x).lower() for x in ro}
        for x in sorted(rn - ro):
            if str(x).lower() not in low:
                log(f"  {sub}: NEW file {x}")
        for x in sorted(ro - rn):
            if str(x).lower() not in {str(y).lower() for y in rn}:
                log(f"  {sub}: gone {x}")
        for x in sorted(ro & rn):
            if not re.search(r"9300|nic\.c|nic_rx|swcore|intr\.c|i2c\.c|gpio\.c|l2ntfy\.c|watchdog|uart", str(x)):
                continue
            n = norm_diff_lines(old / sub / x, new / sub / x)
            if n:
                fo, fn = funcs(old / sub / x), funcs(new / sub / x)
                log(f"  {sub}/{x}: {n} lines; +fn {sorted(fn - fo)} -fn {sorted(fo - fn)}")
    # NEW drops ship dal/longan as prebuilt .o only (U-Boot subset): compare nm symbols vs OLD .c definitions
    for o in sorted((new.parent if new.name == "sdk" else new).rglob("dal/longan/*.o")):
        c = old / "src/dal/longan" / (o.stem + ".c")
        if not c.exists():
            log(f"  dal/longan {o.name}: no OLD source")
            continue
        r = subprocess.run(["nm", str(o)], capture_output=True, text=True)  # local ELF, sub-second
        fo = {ln.split()[-1].split(".")[0] for ln in r.stdout.splitlines() if ln.split()[-2:-1] in (["T"], ["t"])}
        fc = funcs(c)
        log(f"  dal/longan {o.name} (.o, debug_info): +fn {sorted(fo - fc)} ; not in .o {sorted(fc - fo)}")
    hp = "system/include/hwp/hw_profiles"
    ho = {p.name.lower() for p in files(old / hp, "*.c")}
    hn = {p.name.lower() for p in files(new / hp, "*.c")}
    log(f"  hw_profiles added: {sorted(hn - ho)}")
    log(f"  hw_profiles removed: {sorted(ho - hn)}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    s = sp.add_parser("scan")
    s.add_argument("trees", nargs="+")
    d = sp.add_parser("diff")
    d.add_argument("old")
    d.add_argument("new")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("")
    if a.cmd == "scan":
        for t in a.trees:
            scan(t)
    else:
        diff(a.old, a.new)


if __name__ == "__main__":
    main()
