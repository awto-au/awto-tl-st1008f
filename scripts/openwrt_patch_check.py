#!/usr/bin/env python3
"""openwrt_patch_check — apply OpenWrt realtek 300-02/03 + our openwrt/patches/*.patch to
arch/mips/generic in tmp/linux-v7.3 (same base file as v6.18), compile board-realtek.o, restore.

- Proves our patch applies after OpenWrt's series and compiles warning-free (#53).
- The tree is restored in `finally` (git checkout of the two files, overlay header dir removed).
- Log: tmp/logs/openwrt_patch_check.log
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TREE = ROOT / "tmp/linux-v7.3"
BUILD = ROOT / "tmp/build-mips"
OWRT = ROOT / "tmp/openwrt/target/linux/realtek"
SERIES = [OWRT / "patches-6.18/300-02-enhance-realtek-board-setup.patch",
          OWRT / "patches-6.18/300-03-realtek-board-increase-fixup_fdt-buffer-to-32-KiB.patch",
          *sorted((ROOT / "openwrt/patches").glob("*.patch"))]
HDR = "arch/mips/include/asm/mach-rtl-otto"
FILES = ["arch/mips/generic/board-realtek.c", "arch/mips/generic/Platform"]
LOG = ROOT / "tmp/logs/openwrt_patch_check.log"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    for ln in (r.stdout + r.stderr).splitlines():
        log("  | " + ln)
    return r


def main() -> int:
    if run(["git", "status", "--porcelain", *FILES], TREE, 10).stdout.strip():
        log("FAIL: tree has local changes in the target files; refusing")
        return 1
    try:
        shutil.copytree(OWRT / "files-6.18" / HDR, TREE / HDR)
        for p in SERIES:
            # patch is local + instant; 10 s names a stuck prompt
            if run(["patch", "-p1", "--forward", "--batch", "-i", str(p)], TREE, 10).returncode:
                log(f"FAIL: {p.name} does not apply")
                return 1
            log(f"applied {p.name}")
        # one object, incremental build dir already configured: seconds; 300 s names a full rebuild
        r = run(["make", f"O={BUILD}", "ARCH=mips", "CROSS_COMPILE=mips64-linux-gnu-", "W=1",
                 "arch/mips/generic/board-realtek.o"], TREE, 300)
        warn = [ln for ln in (r.stdout + r.stderr).splitlines() if "warning:" in ln or "error:" in ln]
        ok = r.returncode == 0 and not warn
        log(f"{'PASS' if ok else 'FAIL'}: board-realtek.o rc {r.returncode}, {len(warn)} warnings/errors")
        return 0 if ok else 1
    finally:
        run(["git", "checkout", "--", *FILES], TREE, 10)
        shutil.rmtree(TREE / HDR, ignore_errors=True)
        log("tree restored")


if __name__ == "__main__":
    sys.exit(main())
