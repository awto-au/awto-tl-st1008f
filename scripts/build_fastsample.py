#!/usr/bin/env python3
"""build_fastsample — cross-build scripts/tools/<name>.c (static musl, BE MIPS; default fastsample) with the OpenWrt
buildroot toolchain -> tmp/<name>. Usage: build_fastsample.py [name]. Log: tmp/logs/build_<name>.log"""
import glob
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
name = sys.argv[1] if len(sys.argv) > 1 else "fastsample"
gcc = sorted(glob.glob(str(ROOT / "tmp/openwrt-build/staging_dir/toolchain-mips_24kc*/bin/mips-openwrt-linux-musl-gcc")))
if not gcc:
    sys.exit("no buildroot toolchain: run scripts/build_openwrt.py first")
r = subprocess.run([gcc[0], "-O2", "-static", "-Wall", "-o", str(ROOT / f"tmp/{name}"), str(ROOT / f"scripts/tools/{name}.c")],
                   capture_output=True, text=True)
(ROOT / "tmp/logs").mkdir(parents=True, exist_ok=True)
(ROOT / f"tmp/logs/build_{name}.log").write_text(r.stdout + r.stderr)
print(r.stderr or f"built tmp/{name}")
sys.exit(r.returncode)
