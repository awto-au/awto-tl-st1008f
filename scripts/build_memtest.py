#!/usr/bin/env python3
"""build_memtest — cross-build scripts/tools/memtest.c (static musl, BE MIPS) with the OpenWrt buildroot toolchain -> tmp/memtest. Log: tmp/logs/build_memtest.log"""
import glob
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
gcc = sorted(glob.glob(str(ROOT / "tmp/openwrt-build/staging_dir/toolchain-mips_24kc*/bin/mips-openwrt-linux-musl-gcc")))
if not gcc:
    sys.exit("no buildroot toolchain: run scripts/build_openwrt.py first")
r = subprocess.run([gcc[0], "-O2", "-static", "-Wall", "-o", str(ROOT / "tmp/memtest"), str(ROOT / "scripts/tools/memtest.c")], capture_output=True, text=True)
(ROOT / "tmp/logs").mkdir(parents=True, exist_ok=True)
(ROOT / "tmp/logs/build_memtest.log").write_text(r.stdout + r.stderr)
print(r.stderr or "built tmp/memtest")
sys.exit(r.returncode)
