#!/usr/bin/env python3
"""Build the mainline ST1008F v2 kernel: linux-next (kernel_base.py) + forward-ported OpenWrt realtek drivers (#16).

Needs: the kernel_base.py tree (default PIN linux-next tag -> tmp/linux-next, checked out on demand;
KERNEL_BASE=v7.3-rc6 -> tmp/linux-v7.3), tmp/openwrt at OWRT_COMMIT, mips big-endian cross gcc
(default mips64-linux-gnu-, -mabi=32). Log: tmp/logs/mainline_build_check.log
Derived tree state, rebuilt each run (patched files reset via git, copied/created files deleted):
- OWRT_VERBATIM patches-6.18, OWRT_FILES from files-6.18, then kernel_base.patches() (ours and
  forward-ports, 300-04..; per-base copies in openwrt/patches-<base>/). Status of every OpenWrt patch/file: docs/MAINLINE-PORT.md.
- DTS + dts Makefile line; allnoconfig + mainline/st1008f-v2.config (MT SMP, both VPEs: default)
  (+ st1008f-v2-up.config with --up, + st1008f-v2-nohighmem.config with --no-highmem,
  + st1008f-v2-latency.config with --latency) + generated
  initramfs fragment (mainline_initramfs.py); olddefconfig; fail if a fragment option did not
  survive (a later fragment wins); build vmlinux + dtb at nice 19, -j8 max.
- Out dir: tmp/build-mips[-v7.3-rc6][-nohighmem][-up][-lat] (out_dir(); dev.py build-kernel uses the same).
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import kernel_base
import mainline_initramfs

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mainline_build_check.log"
DTS = "tplink-tl-st1008f-v2"
OWRT = ROOT / "tmp/openwrt/target/linux/realtek"
OWRT_FILES_DIR = OWRT / "files-6.18"
# OpenWrt commit the verbatim patches/files and our forward-ports are taken against (#16).
OWRT_COMMIT = "53ec2d05a487e6011cfa096de9211d15197c501b"
# Applied verbatim from OpenWrt realtek patches-6.18; status of every patch: docs/MAINLINE-PORT.md.
OWRT_VERBATIM = ["300-01", "300-02", "300-03", "309", "330", "331", "712", "714", "718", "722"]
# Copied verbatim from files-6.18; 7.3 API fixes on top are in openwrt/patches/300-10.
OWRT_FILES = [
    "arch/mips/include/asm/mach-rtl-otto",
    "drivers/net/dsa/rtl83xx",
    "drivers/net/ethernet/realtek/rtl838x_eth.c",
    "drivers/net/ethernet/realtek/rtl838x_eth.h",
    "drivers/net/mdio/mdio-realtek-otto.c",
    "drivers/net/mdio/mdio-realtek-otto-serdes.c",
    "drivers/net/pcs/pcs-rtl-otto.c",
    "drivers/soc/realtek",
    "drivers/thermal/realtek-thermal.c",
    "include/linux/soc/realtek/otto_table.h",
    "net/dsa/tag_rtl_otto.c",
]
# tree rel-path -> repo source: OS-independent cores shared with U-Boot (#83); copied before the patches
SHARED_FILES = {
    "drivers/net/ethernet/realtek/rtl930x_nic.h": ROOT / "shared/rtl930x-nic/rtl930x_nic.h",
    "drivers/net/dsa/rtl83xx/rtl930x_storm.h": ROOT / "shared/rtl930x-storm/rtl930x_storm.h",  # 300-26
}
PATCHES = [*(next((OWRT / "patches-6.18").glob(f"{n}-*.patch")) for n in OWRT_VERBATIM),
           *kernel_base.patches()]


def owrt_commit():
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=OWRT, capture_output=True, text=True)
    return r.stdout.strip()


def owrt_copied():
    """Tree-relative paths of every file OWRT_FILES copies."""
    out = set()
    for rel in OWRT_FILES:
        src = OWRT_FILES_DIR / rel
        for f in [src] if src.is_file() else src.rglob("*"):
            if f.is_file():
                out.add(str(f.relative_to(OWRT_FILES_DIR)))
    return out


def apply_patches(tree, upto=None, skip=()):
    """Derived state: reset every file the series touches to git, then copy + apply it all fresh.
    upto: stop before the first patch whose name starts with it (patch_rebase.py)."""
    touched, created = set(), set()
    for p in PATCHES:
        lines = p.read_text().splitlines()
        for prev, ln in zip(lines, lines[1:]):
            if ln.startswith("+++ b/"):
                (created if prev.startswith("--- /dev/null") else touched).add(
                    ln[6:].split("\t")[0].strip())
    copied = owrt_copied() | set(SHARED_FILES)
    for f in created | copied:  # not in git: delete so the copy/patch re-creates them
        (tree / f).unlink(missing_ok=True)
    if run(["git", "checkout", "--", *sorted(touched - copied - created)], tree):
        sys.exit("git checkout of the patched files failed, see log")
    for f in touched | created:
        for suf in (".rej", ".orig"):
            (tree / (f + suf)).unlink(missing_ok=True)
    for rel in OWRT_FILES:
        src, dst = OWRT_FILES_DIR / rel, tree / rel
        if src.is_dir():
            shutil.rmtree(dst, ignore_errors=True)
            shutil.copytree(src, dst)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for rel, src in SHARED_FILES.items():
        shutil.copy2(src, tree / rel)
    for p in PATCHES:
        if upto and p.name.startswith(upto):
            return
        if any(p.name.startswith(k) for k in skip):  # --skip: A/B bisects (#107)
            print(f"skip {p.name}")
            continue
        if run(["patch", "-p1", "--forward", "--batch", "-i", str(p)], tree):
            sys.exit(f"{p.name} does not apply, see log")


def check_fragments(config: Path, fragments: list[Path]) -> list[str]:
    """Fragment lines olddefconfig dropped or changed (unmet depends, typos); a later fragment wins."""
    have = {}
    for ln in config.read_text().splitlines():
        if m := re.fullmatch(r"(CONFIG_\w+)=(.*)", ln):
            have[m.group(1)] = m.group(2)
    want = {}
    for frag in fragments:
        for ln in frag.read_text().splitlines():
            if m := re.fullmatch(r"(CONFIG_\w+)=(.*)", ln.strip()):
                want[m.group(1)] = (m.group(2), ln.strip())
            elif m := re.fullmatch(r"# (CONFIG_\w+) is not set", ln.strip()):
                want[m.group(1)] = (None, ln.strip())
    return [f"{ln}  (got {have.get(k, 'not set')})" for k, (v, ln) in want.items() if have.get(k) != v]


def out_dir(no_highmem: bool, up: bool, lat: bool = False) -> Path:
    base = kernel_base.selected()  # fallback base gets its own out dir: no mixed-tree objects
    return ROOT / ("tmp/build-mips" + ("" if kernel_base.is_next(base) else f"-{base}")
                   + ("-nohighmem" if no_highmem else "") + ("-up" if up else "") + ("-lat" if lat else ""))


def run(cmd, cwd):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with LOG.open("a") as f:
        f.write(f"[{stamp}] $ {' '.join(map(str, cmd))}\n")
        f.flush()
        r = subprocess.run(cmd, cwd=cwd, stdout=f, stderr=subprocess.STDOUT)
        f.write(f"[exit {r.returncode}]\n")
    return r.returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default=None, help="default: kernel_base tree (checked out on demand)")
    ap.add_argument("--cross", default="mips64-linux-gnu-")
    ap.add_argument("--jobs", default="8", help="owner: at most 8, keep host cores free")
    ap.add_argument("--dtb-only", action="store_true")
    ap.add_argument("--apply-only", action="store_true", help="copy + patch the tree, no config/build")
    ap.add_argument("--out", default=None, help="default: out_dir() from the flags")
    ap.add_argument("--up", action="store_true", help="merge mainline/st1008f-v2-up.config (one VPE; A/B, #16)")
    ap.add_argument("--no-highmem", action="store_true",
                    help="merge mainline/st1008f-v2-nohighmem.config (256 MiB reference, #27)")
    ap.add_argument("--latency", action="store_true",
                    help="merge mainline/st1008f-v2-latency.config (irqsoff/timerlat tracers; not for benches, #73)")
    ap.add_argument("--skip", action="append", default=[], metavar="PREFIX",
                    help="leave out patches whose name starts with PREFIX (A/B bisect, e.g. 300-21)")
    ap.add_argument("--w1", action="store_true",
                    help="after the build, rebuild the objects our openwrt/patches touch with W=1; warnings fail")
    a = ap.parse_args()
    a.out = a.out or str(out_dir(a.no_highmem, a.up, a.latency))
    os.nice(19)  # owner: builds yield to interactive host work
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("")
    tree, out = Path(a.tree) if a.tree else kernel_base.checkout(), Path(a.out)
    print(f"kernel base {kernel_base.selected()}: {tree.relative_to(ROOT) if tree.is_relative_to(ROOT) else tree}")
    if (c := owrt_commit()) != OWRT_COMMIT:
        sys.exit(f"tmp/openwrt is at {c or '?'}; patches are against {OWRT_COMMIT}")

    apply_patches(tree, skip=a.skip)
    if a.apply_only:
        return
    dts_dir = tree / "arch/mips/boot/dts/realtek"
    (dts_dir / f"{DTS}.dts").write_text((ROOT / f"mainline/{DTS}.dts").read_text())
    mk = dts_dir / "Makefile"
    line = f"dtb-$(CONFIG_MACH_REALTEK_RTL)\t+= {DTS}.dtb\n"
    if line not in mk.read_text():
        mk.write_text(mk.read_text() + line)

    base = ["make", "-C", str(tree), "ARCH=mips", f"CROSS_COMPILE={a.cross}", f"O={out}"]
    if run(base + ["allnoconfig"], tree):
        sys.exit("allnoconfig failed, see log")
    frags = [ROOT / "mainline/st1008f-v2.config",
             *([ROOT / "mainline/st1008f-v2-up.config"] if a.up else []),
             *([ROOT / "mainline/st1008f-v2-nohighmem.config"] if a.no_highmem else []),
             *([ROOT / "mainline/st1008f-v2-latency.config"] if a.latency else []), mainline_initramfs.build()]
    merge = tree / "scripts/kconfig/merge_config.sh"
    if run([str(merge), "-m", "-O", str(out), str(out / ".config"), *map(str, frags)], tree):
        sys.exit("merge_config failed, see log")
    if run(base + ["olddefconfig"], tree):
        sys.exit("olddefconfig failed, see log")
    if bad := check_fragments(out / ".config", frags):
        sys.exit("fragment options dropped by olddefconfig:\n  " + "\n  ".join(bad))
    ny = sum(1 for ln in (out / ".config").read_text().splitlines() if ln.endswith("=y"))
    print(f"config: {ny} =y (allnoconfig + fragments)")
    targets = [f"realtek/{DTS}.dtb"] if a.dtb_only else ["vmlinux", f"realtek/{DTS}.dtb"]
    rc = run(base + [f"-j{a.jobs}", *targets], tree)
    nwarn = LOG.read_text(errors="replace").count("warning:")
    print("build", "OK" if rc == 0 else f"FAILED ({rc})", f"- {nwarn} warning lines - log:", LOG)
    if rc == 0 and a.w1:
        rc = w1_check(base, tree, out, a.jobs)
    sys.exit(rc)


def w1_check(base, tree, out, jobs):
    """Rebuild the objects of every .c our openwrt/patches series touches with W=1; any warning fails."""
    srcs = sorted({ln[6:].split("\t")[0].strip() for p in kernel_base.patches()
                   for ln in p.read_text().splitlines() if ln.startswith("+++ b/") and ln.split("\t")[0].endswith(".c")})
    objs = [s[:-2] + ".o" for s in srcs if (out / (s[:-2] + ".o")).exists()]
    start = len(LOG.read_text(errors="replace"))
    rc = run(base + [f"-j{jobs}", "W=1", *objs], tree)
    warn = [ln for ln in LOG.read_text(errors="replace")[start:].splitlines() if "warning:" in ln]
    for ln in warn:
        print("  W=1:", ln.replace(str(tree) + "/", ""))
    print(f"W=1: {len(objs)} objects of our patches ({len(srcs) - len(objs)} .c not built in this config), "
          f"{len(warn)} warnings, make rc {rc}")
    return rc or (1 if warn else 0)


if __name__ == "__main__":
    main()
