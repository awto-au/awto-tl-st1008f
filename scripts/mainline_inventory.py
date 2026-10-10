#!/usr/bin/env python3
"""Compare OpenWrt's realtek target (files/patches) against a mainline Linux ref.

Inputs (both under tmp/, gitignored):
  tmp/openwrt     sparse clone of openwrt/openwrt (target/linux/realtek, target/linux/generic)
  tmp/linux.git   blobless bare clone of torvalds/linux (needs the --ref tag)
Outputs: markdown tables on stdout and in tmp/logs/mainline_inventory.log
"""
import argparse
import email
import email.policy
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mainline_inventory.log"

# OpenWrt files-6.18 path -> mainline analogue (same driver, possibly renamed)
ANALOGUE = {
    "drivers/net/mdio/mdio-realtek-otto.c": "drivers/net/mdio/mdio-realtek-rtl9300.c",
}
# mainline drivers that OpenWrt gets from kernel.org (no files-6.18 copy); path in mainline
UPSTREAM_DRIVERS = {
    "irqchip": "drivers/irqchip/irq-realtek-rtl.c",
    "timer": "drivers/clocksource/timer-rtl-otto.c",
    "gpio": "drivers/gpio/gpio-realtek-otto.c",
    "watchdog": "drivers/watchdog/realtek_otto_wdt.c",
    "spi-nor ctrl": "drivers/spi/spi-realtek-rtl.c",
    "i2c master": "drivers/i2c/busses/i2c-rtl9300.c",
    "mdio (eth)": "drivers/net/mdio/mdio-realtek-rtl9300.c",
    "mips board": "arch/mips/generic/board-realtek.c",
    "mips dts": "arch/mips/boot/dts/realtek/rtl930x.dtsi",
    "i2c-gpio": "drivers/i2c/busses/i2c-gpio.c",
    "pca953x": "drivers/gpio/gpio-pca953x.c",
    "sfp": "drivers/net/phy/sfp.c",
    "phy rtl8221b etc": "drivers/net/phy/realtek/realtek_main.c",
}
# mainline presence probes for series OpenWrt carries from generic/pending
PROBES = {
    "phylink fwnode PCS provider": "include/linux/pcs/pcs-provider.h",
    "phylink fwnode PCS consumer": "include/linux/pcs/pcs.h",
    "phy-common-props": "include/linux/phy/phy-common-props.h",
    "DSA tag RTL otto": "net/dsa/tag_rtl_otto.c",
    "DSA rtl83xx": "drivers/net/dsa/rtl83xx/Kconfig",
    "rtl838x eth": "drivers/net/ethernet/realtek/rtl838x_eth.c",
    "pcs-rtl-otto": "drivers/net/pcs/pcs-rtl-otto.c",
    "realtek thermal": "drivers/thermal/realtek-thermal.c",
    "otto_table": "drivers/soc/realtek/otto_table.c",
    "clk-rtl83xx": "drivers/clk/realtek/clk-rtl83xx.c",
    "mdio-smbus": "drivers/net/mdio/mdio-smbus.c",
    "mdio otto aux": "drivers/net/mdio/mdio-realtek-otto-aux.c",
    "mdio otto serdes": "drivers/net/mdio/mdio-realtek-otto-serdes.c",
    "mdio otto (renamed)": "drivers/net/mdio/mdio-realtek-otto.c",
    "mach-rtl-otto asm hdr": "arch/mips/include/asm/mach-rtl-otto/mach-rtl-otto.h",
}
# subject renamed on merge: OpenWrt patch subject -> mainline subject
SUBJECT_ALIAS = {
    "gpio: regmap: Bypass cache for shadowed outputs": "gpio: regmap: Bypass cache for aliased inputs",
}


def out(s=""):
    print(s)
    with LOG.open("a") as f:
        f.write(s + "\n")


def git(gitdir, *args, check=False):
    r = subprocess.run(["git", "--git-dir", str(gitdir), *args],
                       capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"git {args}: {r.stderr}")
    return r.stdout.strip() if r.returncode == 0 else ""


def exists(gd, ref, path):
    r = subprocess.run(["git", "--git-dir", str(gd), "cat-file", "-e", f"{ref}:{path}"],
                       capture_output=True)
    return r.returncode == 0


def lines(gd, ref, path):
    r = subprocess.run(["git", "--git-dir", str(gd), "show", f"{ref}:{path}"],
                       capture_output=True)
    return r.stdout.count(b"\n") if r.returncode == 0 else 0


def release_of(gd, ref, commit):
    """First release tag containing commit, reachable from ref (rc folded into its release)."""
    d = git(gd, "describe", "--contains", "--match", "v[0-9]*", commit)
    m = re.match(r"(v\d+\.\d+)(-rc\d+)?", d)
    if not m:
        return "?"
    v = m.group(1)
    # describe --contains of an rc tag means the commit landed in that merge window
    return v if not m.group(2) else v + m.group(2)


def first_added(gd, ref, path):
    sha = git(gd, "log", ref, "--diff-filter=A", "--format=%H", "--", path).splitlines()
    return sha[-1] if sha else ""


def subject_of(patch):
    msg = email.message_from_string(patch.read_text(errors="replace"),
                                    policy=email.policy.default)
    s = str(msg.get("Subject", ""))
    s = re.sub(r"^\[PATCH[^\]]*\]\s*", "", s).strip()
    return re.sub(r"\s+", " ", s)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--openwrt", default=str(ROOT / "tmp/openwrt"))
    ap.add_argument("--linux", default=str(ROOT / "tmp/linux.git"))
    ap.add_argument("--ref", default="v7.3-rc6")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text("")
    tgt = Path(a.openwrt) / "target/linux/realtek"
    gd = a.linux
    out(f"# mainline inventory vs {a.ref} (openwrt {git(Path(a.openwrt)/'.git','rev-parse','--short','HEAD')})\n")

    out("## A. OpenWrt files-6.18 vs mainline\n")
    out("| OpenWrt file | lines | mainline analogue | in mainline | first release |")
    out("|---|---|---|---|---|")
    base = tgt / "files-6.18"
    for f in sorted(p for p in base.rglob("*") if p.is_file()):
        rel = str(f.relative_to(base))
        n = f.read_text(errors="replace").count("\n")
        ana = ANALOGUE.get(rel, rel)
        ex = exists(gd, a.ref, ana)
        rel_v = release_of(gd, a.ref, first_added(gd, a.ref, ana)) if ex else "-"
        out(f"| {rel} | {n} | {ana if ana != rel else ''} | {'yes' if ex else 'no'} | {rel_v} |")

    out("\n## B. Mainline drivers OpenWrt uses unmodified (no files-6.18 copy)\n")
    out("| role | mainline path | present | lines | first release |")
    out("|---|---|---|---|---|")
    for role, p in UPSTREAM_DRIVERS.items():
        ex = exists(gd, a.ref, p)
        out(f"| {role} | {p} | {'yes' if ex else 'no'} | {lines(gd, a.ref, p) if ex else '-'} | "
            f"{release_of(gd, a.ref, first_added(gd, a.ref, p)) if ex else '-'} |")

    out("\n## C. Probes for series carried by OpenWrt\n")
    out("| item | path | in mainline |")
    out("|---|---|---|")
    for k, p in PROBES.items():
        out(f"| {k} | {p} | {'yes' if exists(gd, a.ref, p) else 'no'} |")
    dsa_h = subprocess.run(["git", "--git-dir", gd, "show", f"{a.ref}:include/net/dsa.h"],
                           capture_output=True, text=True).stdout
    out(f"| DSA_TAG_PROTO_RTL_OTTO enum | include/net/dsa.h | {'yes' if 'RTL_OTTO' in dsa_h else 'no'} |")

    out("\n## D. patches-6.18 with a vX.Y tag in the name: is the subject in the ref?\n")
    out("| patch | claimed | in ref | landed in |")
    out("|---|---|---|---|")
    for p in sorted((tgt / "patches-6.18").glob("*.patch")):
        m = re.search(r"-v(\d+\.\d+)-", p.name)
        if not m:
            continue
        subj = SUBJECT_ALIAS.get(subject_of(p), subject_of(p))
        sha = git(gd, "log", a.ref, "-F", "--grep", subj, "--format=%H", "-n1")
        out(f"| {p.name} | v{m.group(1)} | {'yes' if sha else 'no'} | "
            f"{release_of(gd, a.ref, sha) if sha else '-'} |")

    out("\n## E. patches-6.18 not tagged with a version (OpenWrt-only or unmerged)\n")
    out("| patch | bytes |")
    out("|---|---|")
    for p in sorted((tgt / "patches-6.18").glob("*.patch")):
        if not re.search(r"-v\d+\.\d+-", p.name):
            out(f"| {p.name} | {p.stat().st_size} |")


if __name__ == "__main__":
    main()
