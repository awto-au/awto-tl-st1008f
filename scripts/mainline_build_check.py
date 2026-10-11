#!/usr/bin/env python3
"""Build-check the mainline ST1008F v2 DTS and Kconfig fragment against a Linux tree.

Needs: tmp/linux-v7.3 (shallow clone of v7.3-rc6), a mips big-endian cross gcc
(default prefix mips64-linux-gnu-, -mabi=32 multilib). Log: tmp/logs/mainline_build_check.log
Steps: OpenWrt realtek board patches (300-01..03 + mach-rtl-otto headers) and ours
(openwrt/patches/*.patch, e.g. 300-04 DRAM prefetch, #53), each skipped if already applied;
install DTS + dts Makefile line, 32r2_defconfig + fragment, build vmlinux and the dtb.
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mainline_build_check.log"
DTS = "tplink-tl-st1008f-v2"
OWRT = ROOT / "tmp/openwrt/target/linux/realtek"
PATCHES = [*sorted((OWRT / "patches-6.18").glob("300-0[1-3]-*.patch")),
           *sorted((ROOT / "openwrt/patches").glob("*.patch"))]
HDR = "arch/mips/include/asm/mach-rtl-otto"


def apply_patches(tree):
    """Derived state: reset every file the series touches to git, then apply it all fresh."""
    touched = set()
    for p in PATCHES:
        touched |= {ln[6:].split("\t")[0].strip() for ln in p.read_text().splitlines()
                    if ln.startswith("+++ b/")}
    if run(["git", "checkout", "--", *sorted(touched)], tree):
        sys.exit("git checkout of the patched files failed, see log")
    for f in tree.glob("arch/mips/**/*.rej"):
        f.unlink()
    for f in tree.glob("arch/mips/**/*.orig"):
        f.unlink()
    shutil.rmtree(tree / HDR, ignore_errors=True)
    shutil.copytree(OWRT / "files-6.18" / HDR, tree / HDR)
    for p in PATCHES:
        if run(["patch", "-p1", "--forward", "--batch", "-i", str(p)], tree):
            sys.exit(f"{p.name} does not apply, see log")


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
    ap.add_argument("--tree", default=str(ROOT / "tmp/linux-v7.3"))
    ap.add_argument("--out", default=str(ROOT / "tmp/build-mips"))
    ap.add_argument("--cross", default="mips64-linux-gnu-")
    ap.add_argument("--jobs", default="16")
    ap.add_argument("--dtb-only", action="store_true")
    a = ap.parse_args()
    tree, out = Path(a.tree), Path(a.out)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("")

    apply_patches(tree)
    dts_dir = tree / "arch/mips/boot/dts/realtek"
    (dts_dir / f"{DTS}.dts").write_text((ROOT / f"mainline/{DTS}.dts").read_text())
    mk = dts_dir / "Makefile"
    line = f"dtb-$(CONFIG_MACH_REALTEK_RTL)\t+= {DTS}.dtb\n"
    if line not in mk.read_text():
        mk.write_text(mk.read_text() + line)

    base = ["make", "-C", str(tree), "ARCH=mips", f"CROSS_COMPILE={a.cross}", f"O={out}"]
    if run(base + ["32r2_defconfig"], tree):
        sys.exit("defconfig failed, see log")
    merge = tree / "scripts/kconfig/merge_config.sh"
    if run([str(merge), "-m", "-O", str(out), str(out / ".config"),
            str(ROOT / "mainline/st1008f-v2.config")], tree):
        sys.exit("merge_config failed, see log")
    if run(base + ["olddefconfig"], tree):
        sys.exit("olddefconfig failed, see log")
    targets = [f"realtek/{DTS}.dtb"] if a.dtb_only else ["vmlinux", f"realtek/{DTS}.dtb"]
    rc = run(base + [f"-j{a.jobs}", *targets], tree)
    print("build", "OK" if rc == 0 else f"FAILED ({rc})", "- log:", LOG)
    sys.exit(rc)


if __name__ == "__main__":
    main()
