#!/usr/bin/env python3
"""Apply OpenWrt realtek patches (and the generic phylink-PCS series) onto a Linux tree, in order.

Reports per patch: ok | fuzz | FAIL | skipped (already upstream / not needed for RTL930x).
Also copies files-6.18/ into the tree, then optionally builds the copied drivers.
Works on a scratch copy (--work), never on tmp/linux-v7.3 itself.
Log: tmp/logs/mainline_patch_check.log
"""
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mainline_patch_check.log"

# patches that only serve other SoCs / boards (not RTL930x + SFP): skipped
SKIP = re.compile(
    r"(rtl960x|hasivo|pse-pd|rtl8231|RTL8231|pcie|-v7\.[0-3]-|-v6\.|"  # upstream by <= 7.3 or n/a
    r"723-net-mdio|820-|821-|822-|301-|308-|318-|"
    r"720-add-rtl-phy|743-net-realtek-serdes|712-|714-)"
)


CROSS = [""]
BASE = [""]
# Kconfig added on top of the stage-0 config: the OpenWrt RTL930x driver set
FP_CONFIG = """CONFIG_RTL930X=y
CONFIG_NET_DSA=y
CONFIG_NET_DSA_RTL83XX=y
CONFIG_NET_DSA_TAG_RTL_OTTO=y
CONFIG_NET_RTL838X=y
CONFIG_PCS_RTL_OTTO=y
CONFIG_MDIO_REALTEK_OTTO=y
CONFIG_MDIO_REALTEK_RTL9300=n
CONFIG_MDIO_REALTEK_OTTO_SERDES=y
CONFIG_REALTEK_OTTO_TABLE=y
CONFIG_REALTEK_THERMAL=y
CONFIG_THERMAL=y
CONFIG_THERMAL_OF=y
CONFIG_THERMAL_HWMON=y
CONFIG_PAGE_POOL=y
CONFIG_NET_SWITCHDEV=y
CONFIG_FWNODE_PCS=y
CONFIG_HWMON=y
"""


def hand_fixups(work):
    """Kconfig/Makefile hooks whose context moved in 7.3; replayed by hand after -F0 failures."""
    def edit(rel, fn):
        f = work / rel
        f.write_text(fn(f.read_text()))

    # 716 hunk 1: PARPORT dependency is gone in mainline
    edit("drivers/net/ethernet/realtek/Kconfig", lambda t: t.replace(
        "\tdepends on PCI\n\thelp\n\t  If you have a network",
        "\tdepends on PCI || MACH_REALTEK_RTL\n\thelp\n\t  If you have a network", 1)
        if "MACH_REALTEK_RTL\n\thelp\n\t  If you have a network" not in t else t)
    nic = ("config NET_RTL838X\n\ttristate \"Realtek rtl838x Ethernet MAC support\"\n"
           "\tdepends on MACH_REALTEK_RTL\n\thelp\n\t  Realtek Otto CPU-port MAC.\n\n")
    edit("drivers/net/ethernet/realtek/Kconfig", lambda t: t if "config NET_RTL838X" in t
         else t.replace("endif # NET_VENDOR_REALTEK", nic + "endif # NET_VENDOR_REALTEK", 1))
    edit("drivers/net/ethernet/realtek/Makefile", lambda t: t if "rtl838x_eth" in t else t +
         "obj-$(CONFIG_NET_RTL838X) += rtl838x_eth.o\n")
    # 721: value 32 is taken by MXL862 in 7.3, next free is 36
    edit("include/net/dsa.h", lambda t: t.replace("DSA_TAG_PROTO_RTL_OTTO_VALUE\t\t32",
                                                   "DSA_TAG_PROTO_RTL_OTTO_VALUE\t\t36"))
    # 7.x compiler_types.h defines `at_least` as `static`: rename the l3.c parameter
    edit("drivers/net/dsa/rtl83xx/l3.c", lambda t: re.sub(r"\bat_least\b", "min_plen", t))
    # 806/808: OTTO mdio + SerDes mdio entries, placed before MDIO_REGMAP
    kc = ("config MDIO_REALTEK_OTTO\n\ttristate \"Realtek Otto MDIO interface support\"\n"
          "\tdefault MACH_REALTEK_RTL\n\tdepends on MACH_REALTEK_RTL || COMPILE_TEST\n\thelp\n"
          "\t  Realtek Otto MDIO.\n\nconfig MDIO_REALTEK_OTTO_SERDES\n"
          "\ttristate \"Realtek Otto MDIO SerDes interface support\"\n"
          "\tdefault MACH_REALTEK_RTL\n\tdepends on MACH_REALTEK_RTL || COMPILE_TEST\n\thelp\n"
          "\t  Realtek Otto SerDes MDIO.\n\n")
    edit("drivers/net/mdio/Kconfig", lambda t: t if "config MDIO_REALTEK_OTTO\n" in t
         else t.replace("config MDIO_REGMAP\n", kc + "config MDIO_REGMAP\n", 1))
    edit("drivers/net/mdio/Makefile", lambda t: t if "mdio-realtek-otto.o" in t else t +
         "obj-$(CONFIG_MDIO_REALTEK_OTTO)\t+= mdio-realtek-otto.o\n"
         "obj-$(CONFIG_MDIO_REALTEK_OTTO_SERDES)\t+= mdio-realtek-otto-serdes.o\n")


def build(work, out, jobs):
    hand_fixups(work)
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy2(BASE[0], out / ".config")
    with (out / ".config").open("a") as f:
        f.write(FP_CONFIG)
    base = ["make", "-C", str(work), "ARCH=mips", f"CROSS_COMPILE={CROSS[0]}", f"O={out}"]
    for cmd in (base + ["olddefconfig"], base + ["-k", f"-j{jobs}", "vmlinux"]):
        with LOG.open("a") as f:
            f.write("$ " + " ".join(cmd) + "\n")
            f.flush()
            r = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT)
            f.write(f"[exit {r.returncode}]\n")
    log("build done, see log")


HAND = re.compile(r"^(716|806|808)-")


def log(s=""):
    print(s)
    with LOG.open("a") as f:
        f.write(s + "\n")


def apply(tree, patch):
    """strict (fuzz 0) first, then fuzz 2; a fuzz-only apply needs a manual review of placement."""
    r = None
    for fuzz, label in (("-F0", "ok"), ("-F2", "fuzz"), ("-F3", "fuzz3")):
        base = ["patch", "-p1", "-N", fuzz, "--no-backup-if-mismatch", "-i", str(patch)]
        r = subprocess.run(base + ["--dry-run"], cwd=tree, capture_output=True, text=True)
        if r.returncode == 0:
            subprocess.run(base + ["-s"], cwd=tree, capture_output=True, text=True)
            return label, ""
    note = next((l for l in (r.stdout + r.stderr).splitlines() if "FAILED" in l), "").strip()
    return "FAIL", note


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "tmp/linux-v7.3"))
    ap.add_argument("--work", default=str(ROOT / "tmp/linux-fp"))
    ap.add_argument("--openwrt", default=str(ROOT / "tmp/openwrt"))
    ap.add_argument("--build", action="store_true", help="configure and build with make -k")
    ap.add_argument("--rebuild", action="store_true", help="skip patching, rerun fixups + build")
    ap.add_argument("--out", default=str(ROOT / "tmp/build-fp"))
    ap.add_argument("--base-config", default=str(ROOT / "tmp/build-mips/.config"))
    ap.add_argument("--cross", default="mips64-linux-gnu-")
    ap.add_argument("--jobs", default="24")
    a = ap.parse_args()
    CROSS[0] = a.cross
    BASE[0] = a.base_config
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if not a.rebuild:
        LOG.write_text("")
    work = Path(a.work)
    if a.rebuild:
        build(work, Path(a.out), a.jobs)
        return
    if not work.exists():
        subprocess.run(["cp", "-a", "--reflink=auto", a.src, a.work], check=True)
    ow = Path(a.openwrt) / "target/linux"

    seq = []
    # generic phylink fwnode-PCS series (not in mainline 7.3), then realtek patches
    seq += sorted((ow / "generic/pending-6.18").glob("737-0[1-8]-*.patch"))
    seq += sorted((ow / "realtek/patches-6.18").glob("*.patch"))

    log("| patch | result | note |")
    log("|---|---|---|")
    for p in seq:
        if p.parent.name == "patches-6.18" and SKIP.search(p.name) and not re.search(r"-v7\.4-", p.name):
            log(f"| {p.name} | skipped | upstream <=7.3 or other SoC |")
            continue
        if HAND.search(p.name):
            log(f"| {p.name} | hand | Kconfig/Makefile hook only; replayed in hand_fixups() |")
            continue
        res, note = apply(work, p)
        log(f"| {p.name} | {res} | {note} |")

    # files-6.18 overlay
    base = ow / "realtek/files-6.18"
    for f in base.rglob("*"):
        if f.is_file():
            dst = work / f.relative_to(base)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dst)
    log("\nfiles-6.18 copied over tree")
    if a.build:
        build(work, Path(a.out), a.jobs)


if __name__ == "__main__":
    sys.exit(main())
