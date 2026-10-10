#!/usr/bin/env python3
"""build_uboot — build the standalone awto u-boot (RAM bring-up harness).

Clean-room, no stock code. Toolchain: clang (MIPS32r2 BE) + ld.lld +
llvm-objcopy (no GCC cross-toolchain). Output: uboot/awto-uboot.{elf,bin};
bin also copied to tmp/tftp/ for RAM boot during bring-up.

Usage: build_uboot.py
Log: tmp/logs/build_uboot.log
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "uboot"
LOG = ROOT / "tmp/logs/build_uboot.log"
TFTP = ROOT / "tmp/tftp"

CFLAGS = [
    "--target=mips-linux-gnu", "-march=mips32r2", "-EB",
    "-ffreestanding", "-nostdlib", "-fno-pic", "-mno-abicalls",
    "-fno-builtin", "-Os", "-Wall", "-Wextra", "-std=c11",
    f"-I{SRC}",
]
CSRC = ["uart.c", "main.c"]
ASRC = ["start.S"]
LINK = SRC / "link-ram.ld"


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or r.stderr.strip():
        log("  $ " + " ".join(cmd))
        if r.stderr.strip():
            log(r.stderr.strip())
    if r.returncode != 0:
        raise SystemExit(f"command failed ({r.returncode})")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baud", type=int, default=115200)
    a = ap.parse_args()
    log(f"=== build_uboot baud={a.baud} {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ===")
    cflags = CFLAGS + [f"-DUART_BAUD={a.baud}u"]
    objs = []
    for s in ASRC + CSRC:
        o = SRC / (s + ".o")
        run(["clang", *cflags, "-c", str(SRC / s), "-o", str(o)])
        objs.append(str(o))
    elf = SRC / "awto-uboot.elf"
    binf = SRC / "awto-uboot.bin"
    run(["ld.lld", "-T", str(LINK), "-o", str(elf), *objs])
    run(["llvm-objcopy", "-O", "binary", str(elf), str(binf)])
    log(f"wrote {binf} ({binf.stat().st_size} bytes)")

    dis = subprocess.run(["llvm-objdump", "-d", str(elf)],
                         capture_output=True, text=True, timeout=30).stdout
    for line in dis.splitlines():
        if "<_start>:" in line or line.strip().startswith("81000000:"):
            log("  " + line.strip())
    TFTP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binf, TFTP / "awto-uboot.bin")
    log(f"copied to {TFTP / 'awto-uboot.bin'}")
    log("DONE. RAM boot: tftpboot 0x81000000 awto-uboot.bin ; go 0x81000000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
