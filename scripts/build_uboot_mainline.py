#!/usr/bin/env python3
"""build_uboot_mainline — stage uboot-port/ into a pinned mainline U-Boot tree and build stage 0.

- Scaffold (tracked): uboot-port/. Tree: tmp/u-boot-v2026.07 (override: $UBOOT_TREE), tag v2026.07.
- Stages files, patches Kconfig/Makefile hooks idempotently, builds out-of-tree (O=tmp/uboot-mainline-build).
- Outputs copied to tmp/tftp/: uboot-mainline.bin (raw, linked 0x81000000), uboot-mainline.elf.
- Toolchain: CROSS_COMPILE=mips64-linux-gnu- (GCC, MIPS32 BE via -march=mips32r2 -mabi=32).
- Log: tmp/logs/build_uboot_mainline.log. Build timeout: BUILD_TIMEOUT_S (see constant).

Usage: build_uboot_mainline.py [--clean] [--tree DIR] [--cross PREFIX]
"""

import argparse
import collections
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAFFOLD = ROOT / "uboot-port"
TREE = Path(os.environ.get("UBOOT_TREE", ROOT / "tmp/u-boot-v2026.07"))
BUILDDIR = ROOT / "tmp/uboot-mainline-build"
TFTP = ROOT / "tmp/tftp"
LOG = ROOT / "tmp/logs/build_uboot_mainline.log"
TAG = "v2026.07"
DEFCONFIG = "tplink_tl-st1008f_ram_defconfig"
CROSS = "mips64-linux-gnu-"
# Full clean build (CCACHE_DISABLE=1, -j30, 2026-10-10): 4 s. x1.5 (1 s timer granularity) = 6 s.
# Applies per make call; on expiry make is killed and logged with elapsed time.
BUILD_TIMEOUT_S = 6
TAIL_LINES = 40

# scaffold rel-path -> tree rel-path
FILES = {
    "arch/mips/dts/tplink_tl-st1008f.dts": "arch/mips/dts/tplink_tl-st1008f.dts",
    "include/configs/tplink_tl-st1008f.h": "include/configs/tplink_tl-st1008f.h",
    "configs/" + DEFCONFIG: "configs/" + DEFCONFIG,
}
DIRS = {
    "arch/mips/mach-otto": "arch/mips/mach-otto",
    "board/tplink/tl-st1008f": "board/tplink/tl-st1008f",
}

ARCH_BLOCK = """config ARCH_OTTO
	bool "Support Realtek Otto (RTL83xx/93xx) SoCs"
	select HAS_FIXED_TIMER_FREQUENCY
	select DM
	select DM_SERIAL
	select MIPS_TUNE_34KC
	select OF_CONTROL
	imply CMD_DM

"""

# (file, anchor, text, where): insert `text` before/after `anchor` unless `marker` already present.
HOOKS = [
    ("arch/mips/Kconfig", "config ARCH_JZ47XX\n", ARCH_BLOCK, "before", "config ARCH_OTTO"),
    ("arch/mips/Kconfig", 'source "arch/mips/mach-jz47xx/Kconfig"\n',
     'source "arch/mips/mach-otto/Kconfig"\n', "after", "mach-otto/Kconfig"),
    ("arch/mips/Makefile", "machine-$(CONFIG_ARCH_JZ47XX) += jz47xx\n",
     "machine-$(CONFIG_ARCH_OTTO) += otto\n", "after", "+= otto"),
    ("arch/mips/dts/Makefile", "dtb-$(CONFIG_TARGET_JZ4780_CI20) += ci20.dtb\n",
     "dtb-$(CONFIG_TARGET_TPLINK_TL_ST1008F) += tplink_tl-st1008f.dtb\n", "after", "tplink_tl-st1008f.dtb"),
]


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(cmd, cwd, env=None, timeout=BUILD_TIMEOUT_S):
    """Run cmd, tee output to stdout+LOG; kill after timeout. Returns rc (124 = timeout)."""
    log("run: " + " ".join(map(str, cmd)))
    t0 = time.time()
    tail = collections.deque(maxlen=TAIL_LINES)
    p = subprocess.Popen(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, errors="replace")
    killed = threading.Event()

    def expire():
        killed.set()
        p.kill()

    timer = threading.Timer(timeout, expire)
    timer.start()
    with LOG.open("a") as fh:
        for line in p.stdout:
            sys.stdout.write(line)
            fh.write(line)
            tail.append(line)
    rc = p.wait()
    timer.cancel()
    if killed.is_set():
        log(f"TIMEOUT: {' '.join(map(str, cmd))} exceeded {timeout} s (elapsed {time.time() - t0:.0f} s)")
        return 124
    log(f"exit {rc} ({time.time() - t0:.0f} s)")
    if rc:
        log(f"FAILED; last {len(tail)} lines:")
        for line in tail:
            log("  | " + line.rstrip("\n"))
    return rc


def check_tree() -> None:
    if not (TREE / "Makefile").exists():
        sys.exit(f"missing U-Boot tree {TREE}; create with: git clone -s -n <awto-uboot clone> {TREE} "
                 f"&& git -C {TREE} checkout --detach {TAG}")
    desc = subprocess.run(["git", "describe", "--tags", "--exact-match", "HEAD"], cwd=TREE,
                          capture_output=True, text=True, timeout=10).stdout.strip()
    if desc != TAG:
        sys.exit(f"{TREE} is at {desc or 'unknown'}, expected {TAG}")


def stage() -> None:
    # Tree is a plain mainline checkout; reset tracked files so removed hooks do not linger.
    subprocess.run(["git", "checkout", "--", "."], cwd=TREE, check=True, timeout=60)
    for src, dst in FILES.items():
        d = TREE / dst
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(SCAFFOLD / src, d)
        log(f"staged {dst}")
    for src, dst in DIRS.items():
        d = TREE / dst
        if d.is_dir():
            shutil.rmtree(d)
        shutil.copytree(SCAFFOLD / src, d)
        log(f"staged {dst}/")
    for rel, anchor, text, where, marker in HOOKS:
        p = TREE / rel
        txt = p.read_text()
        if marker in txt:
            continue
        if anchor not in txt:
            sys.exit(f"ABORT: anchor {anchor!r} not in {rel}: tree is not {TAG}-shaped")
        new = text + anchor if where == "before" else anchor + text
        p.write_text(txt.replace(anchor, new, 1))
        log(f"patched {rel} ({marker})")


def build(cross: str) -> int:
    env = dict(os.environ, CROSS_COMPILE=cross, ARCH="mips")
    o = f"O={BUILDDIR}"
    BUILDDIR.mkdir(parents=True, exist_ok=True)
    if run(["make", o, DEFCONFIG], TREE, env):
        return 1
    rc = run(["make", o, f"-j{os.cpu_count() or 4}"], TREE, env)
    binp = BUILDDIR / "u-boot.bin"
    if rc or not binp.exists():
        log("BUILD FAILED")
        return rc or 1
    TFTP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binp, TFTP / "uboot-mainline.bin")
    shutil.copy2(BUILDDIR / "u-boot", TFTP / "uboot-mainline.elf")
    log(f"BUILD OK: uboot-mainline.bin = {binp.stat().st_size} bytes -> {TFTP}")
    log("load: tftpboot 0x81000000 uboot-mainline.bin ; go 0x81000000")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="remove the build dir first")
    ap.add_argument("--cross", default=CROSS)
    a = ap.parse_args()
    log(f"=== build_uboot_mainline {TAG} cross={a.cross} ===")
    check_tree()
    if a.clean:
        shutil.rmtree(BUILDDIR, ignore_errors=True)
        log("removed build dir")
    stage()
    return build(a.cross)


if __name__ == "__main__":
    raise SystemExit(main())
