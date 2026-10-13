#!/usr/bin/env python3
"""build_selftest — target files of st1008f-selftest (#108, docs/SELFTEST.md) that are not plain text.

- st1008f-stx (openwrt/selftest/st1008f-stx.c): static MIPS32 BE musl binary from the OpenWrt
  toolchain (tmp/openwrt-build/staging_dir/toolchain-*; `--toolchain DIR` = its bin/ dir). Static:
  the same file runs on OpenWrt and the mainline initramfs (OpenWrt 24.10 libc there).
- cpu.xz + cpu.md5: deterministic pseudo-text (CPU_KIB) as XZ/LZMA2, CRC32 check (BusyBox unxz).
- Output tree: tmp/selftest/root/ (usr/libexec/st1008f-stx, usr/share/st1008f-selftest/cpu.*).
- Consumers: build_openwrt.py (files/ overlay), mainline_initramfs.py (staged()).
- Log: tmp/logs/build_selftest.log
"""

import argparse
import hashlib
import lzma
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/build_selftest.log"
SRC = ROOT / "openwrt/selftest/st1008f-stx.c"
OUT = ROOT / "tmp/selftest/root"
STX = "usr/libexec/st1008f-stx"
SHARE = "usr/share/st1008f-selftest"
CPU_KIB = 512        # xz input: ~30 ms per decode at 800 MHz (estimate), many loops per CPU budget
CC_S = 60            # one ~400-line file at -Os: < 2 s; 60 s names a stuck toolchain


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def toolchain(arg: str | None) -> Path:
    if arg:
        d = Path(arg)
    else:
        dirs = sorted(ROOT.glob("tmp/openwrt-build/staging_dir/toolchain-mips_24kc_*_musl/bin"))
        if not dirs:
            raise SystemExit("no OpenWrt toolchain in tmp/openwrt-build: run ./dev.py build-openwrt once, "
                             "or pass --toolchain .../staging_dir/toolchain-*/bin")
        d = dirs[-1]
    cc = d / "mips-openwrt-linux-musl-gcc"
    if not cc.exists():
        raise SystemExit(f"{cc}: missing")
    return cc


def cpu_data() -> bytes:
    """Word salad from a fixed xorshift32: literals + matches, like real decompress work."""
    words = [bytes(f"w{i:x}{'abcdefghij'[i % 10] * (i % 7)}", "ascii") for i in range(1500)]
    x, out = 0x1008f, bytearray()
    while len(out) < CPU_KIB * 1024:
        x ^= (x << 13) & 0xffffffff
        x ^= x >> 17
        x ^= (x << 5) & 0xffffffff
        out += words[x % len(words)] + (b"\n" if x & 0xf == 0 else b" ")
    return bytes(out[:CPU_KIB * 1024])


def build(tc: str | None = None) -> Path:
    cc = toolchain(tc)
    (OUT / STX).parent.mkdir(parents=True, exist_ok=True)
    (OUT / SHARE).mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "STAGING_DIR": str(cc.parent.parent.parent)}  # silences the toolchain warning
    cmd = [str(cc), "-static", "-Os", "-Wall", "-Wextra", "-Werror", "-s", "-o", str(OUT / STX), str(SRC)]
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=CC_S)
    if r.returncode:
        raise SystemExit(f"FAIL cc: {r.stderr}")
    data = cpu_data()
    xz = lzma.compress(data, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32,
                       filters=[{"id": lzma.FILTER_LZMA2, "preset": 6}])
    (OUT / SHARE / "cpu.xz").write_bytes(xz)
    (OUT / SHARE / "cpu.md5").write_text(hashlib.md5(data).hexdigest() + "\n")
    log(f"{STX} {(OUT / STX).stat().st_size} B ({cc.name}); cpu.xz {len(xz)} B -> {len(data)} B, "
        f"md5 {hashlib.md5(data).hexdigest()}")
    return OUT


def staged() -> dict[str, tuple[bytes, int]]:
    """path in the target root -> (bytes, mode); built tree must exist."""
    if not (OUT / STX).exists():
        raise SystemExit(f"missing {OUT / STX}: run scripts/build_selftest.py first")
    return {STX: ((OUT / STX).read_bytes(), 0o755),
            f"{SHARE}/cpu.xz": ((OUT / SHARE / "cpu.xz").read_bytes(), 0o644),
            f"{SHARE}/cpu.md5": ((OUT / SHARE / "cpu.md5").read_bytes(), 0o644)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--toolchain", help="OpenWrt toolchain bin/ dir (default: tmp/openwrt-build)")
    a = ap.parse_args()
    build(a.toolchain)
    return 0


if __name__ == "__main__":
    sys.exit(main())
