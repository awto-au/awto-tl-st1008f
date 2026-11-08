#!/usr/bin/env python3
"""build_iperf3_static — ONE static iperf3 for every bench stack (A/B/C), built with B's OpenWrt toolchain.

- Source: iperf-3.22.tar.gz, sha256 = PKG_HASH of feeds/packages/net/iperf3 (checked), fetched to scratch.
- Toolchain: tmp/openwrt-build staging_dir toolchain-mips_24kc_gcc-14.4.0_musl (mips_24kc musl soft-float).
- Flags = B's CONFIG_TARGET_OPTIMIZATION; `-static`, no openssl/sctp, libatomic linked statically.
- Output: tmp/stack-tools/iperf3 + iperf3.sha256 + iperf3.version (pushed to /tmp by stack_normalize.py).
- Scratch: /home/dan/st1008f-scratch/iperf-src (not /mnt/2tb: disk floor). Log: tmp/logs/build_iperf3_static.log
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "tmp/openwrt-build"
TC = BUILD / "staging_dir/toolchain-mips_24kc_gcc-14.4.0_musl"
VER = "3.22"
SHA = "1c0d0fb02c52626111d6e132db80edfbf27bbaff8bd9245df2a371dcb0b35a92"
URL = f"https://downloads.es.net/pub/iperf/iperf-{VER}.tar.gz"
SCRATCH = Path("/home/dan/st1008f-scratch/iperf-src")
OUT = ROOT / "tmp/stack-tools"
LOG = ROOT / "tmp/logs/build_iperf3_static.log"
CFLAGS = "-Os -pipe -mno-branch-likely -mips32r2 -mtune=24kc -D_GNU_SOURCE"


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(cmd, cwd, env):
    log(f"$ {' '.join(cmd)}  (cwd {cwd})")
    with LOG.open("a") as fh:
        r = subprocess.run(cmd, cwd=cwd, env=env, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if r.returncode:
        sys.exit(f"FAIL rc {r.returncode}: {' '.join(cmd)} (see {LOG})")


def main():
    SCRATCH.mkdir(parents=True, exist_ok=True)
    tgz = SCRATCH / f"iperf-{VER}.tar.gz"
    if not tgz.exists():
        sh(["curl", "-sSL", "-m", "120", "-o", str(tgz), URL], SCRATCH, os.environ)
    if hashlib.sha256(tgz.read_bytes()).hexdigest() != SHA:
        sys.exit(f"{tgz}: sha256 mismatch")
    src = SCRATCH / f"iperf-{VER}"
    if src.exists():
        shutil.rmtree(src)
    with tarfile.open(tgz) as t:
        t.extractall(SCRATCH, filter="data")
    env = dict(os.environ, STAGING_DIR=str(BUILD / "staging_dir"), PATH=f"{TC}/bin:{os.environ['PATH']}",
               CFLAGS=CFLAGS, LDFLAGS="-static", LIBS="-l:libatomic.a")
    sh(["./configure", "--host=mips-openwrt-linux-musl", "--without-openssl", "--without-sctp",
        "--disable-shared", "--enable-static", "--enable-static-bin", "--disable-profiling", "CC=mips-openwrt-linux-musl-gcc"], src, env)
    sh(["make", f"-j{os.cpu_count()}", "V=0"], src, env)
    OUT.mkdir(parents=True, exist_ok=True)
    exe = OUT / "iperf3"
    shutil.copy(src / "src/iperf3", exe)
    sh(["mips-openwrt-linux-musl-strip", str(exe)], src, env)
    digest = hashlib.sha256(exe.read_bytes()).hexdigest()
    (OUT / "iperf3.sha256").write_text(f"{digest}  iperf3\n")
    (OUT / "iperf3.version").write_text(f"iperf {VER} (tarball sha256 {SHA}), gcc 14.4.0 musl mips_24kc, flags {CFLAGS}, static\n")
    log(f"{exe}: {exe.stat().st_size} B sha256 {digest}")


if __name__ == "__main__":
    main()
