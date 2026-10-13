#!/usr/bin/env python3
"""build_perf — static `perf` for the mainline initramfs board (#67).

- Source: tools/perf of the kernel_base tree (tmp/linux-next). Compiler: the local OpenWrt buildroot's
  musl toolchain (tmp/openwrt-build/staging_dir/toolchain-mips_24kc_*_musl; `./dev.py build-openwrt` makes it).
- Minimal static build: no libelf/libdw/libtraceevent/libbpf/python/perl/slang/libunwind. Kernel symbols
  come from /proc/kallsyms on the board, which is all NIC/NAT path profiling needs.
- Output: tmp/perf/perf (copy to the board over SSH: `./dev.py perf-push`). Log: tmp/logs/build_perf.log
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/build_perf.log"
OUT = ROOT / "tmp/perf"
TREE = ROOT / "tmp/linux-next"
TC_GLOB = "tmp/openwrt-build/staging_dir/toolchain-mips_24kc_*_musl"
BUILD_S = 900  # tools/perf minimal at -j8 ~3-5 min on this host; x1.25 + configure, first build


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
    out = OUT / "build"
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PATH": f"{tc / 'bin'}:{os.environ['PATH']}", "STAGING_DIR": str(tc.parent)}
    cmd = ["nice", "-n", "19", "make", "-C", str(TREE / "tools/perf"), f"O={out}", "-j8", "ARCH=mips",
           "CROSS_COMPILE=mips-openwrt-linux-musl-", "LDFLAGS=-static", "WERROR=0",
           "NO_LIBELF=1", "NO_LIBDW=1", "NO_LIBTRACEEVENT=1", "NO_LIBBPF=1", "NO_LIBPYTHON=1",
           "NO_LIBPERL=1", "NO_SLANG=1", "NO_GTK2=1", "NO_LIBUNWIND=1", "NO_LIBNUMA=1", "NO_LIBAUDIT=1",
           "NO_LIBCRYPTO=1", "NO_LIBCAP=1", "NO_LIBBABELTRACE=1", "NO_JEVENTS=1", "NO_LIBZSTD=1",
           "NO_LZMA=1", "NO_ZLIB=1", "NO_LIBLLVM=1", "NO_CAPSTONE=1", "NO_LIBPFM4=1", "NO_SDT=1",
           "NO_DEMANGLE=1", "NO_BACKTRACE=1", "NO_AUXTRACE=1", "NO_LIBDEBUGINFOD=1",
           "NO_MYPY=1", "NO_PYLINT=1", "NO_SHELLCHECK=1", "NO_RUST=1"]  # host linters + rust test workload
    log(f"toolchain {tc.name}; make tools/perf -> {out.relative_to(ROOT)}")
    with LOG.open("a") as fh:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, env=env, timeout=BUILD_S)
    if r.returncode or not (out / "perf").exists():
        log(f"FAIL: make rc={r.returncode}; see {LOG.relative_to(ROOT)}")
        return 1
    shutil.copy2(out / "perf", OUT / "perf")
    subprocess.run([str(tc / "bin/mips-openwrt-linux-musl-strip"), str(OUT / "perf")], check=True, timeout=30)
    log(f"OK: tmp/perf/perf {(OUT / 'perf').stat().st_size} B (static, stripped)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
