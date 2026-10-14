#!/usr/bin/env python3
"""build_xdp_tool — static `st1008f-xdp` (tools/xdp/st1008f_xdp.c) for the board, #140.

- Compiler: the local OpenWrt buildroot's musl toolchain, as scripts/build_perf.py.
- Output: tmp/xdp/st1008f-xdp (pushed by `./dev.py xdp-test`). Log: tmp/logs/build_xdp_tool.log
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/build_xdp_tool.log"
TC_GLOB = "tmp/openwrt-build/staging_dir/toolchain-mips_24kc_*_musl"
SRC = ROOT / "tools/xdp/st1008f_xdp.c"
OUT = ROOT / "tmp/xdp/st1008f-xdp"
CC_S = 60  # one small C file: < 2 s; 60 s names a broken toolchain


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    tcs = sorted(ROOT.glob(TC_GLOB))
    if not tcs:
        log(f"FAIL: no musl toolchain at {TC_GLOB} (run ./dev.py build-openwrt once)")
        return 1
    tc = tcs[-1]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PATH": f"{tc / 'bin'}:{os.environ['PATH']}", "STAGING_DIR": str(tc.parent)}
    r = subprocess.run(["mips-openwrt-linux-musl-gcc", "-O2", "-Wall", "-static", "-s", "-o", str(OUT), str(SRC)],
                       env=env, capture_output=True, text=True, timeout=CC_S)
    if r.returncode:
        log(f"FAIL: {r.stderr.strip()[-600:]}")
        return 1
    log(f"OK: {OUT.relative_to(ROOT)} {OUT.stat().st_size} B")
    return 0


if __name__ == "__main__":
    sys.exit(main())
