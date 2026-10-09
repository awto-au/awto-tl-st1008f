#!/usr/bin/env python3
"""build_hello_payload — build the minimal MIPS32r2-BE boot payload.

Toolchain: clang (MIPS BE codegen) + ld.lld + llvm-objcopy — no GCC cross-
toolchain needed. Output: firmware/hello/hello.bin (raw, load+go at 0x81000000)
and hello.elf (for objdump). Also copies hello.bin into tmp/tftp/ for RAM boot.

Test (stock U-Boot, via the serial daemon):
  tftpboot 0x81000000 hello.bin ; go 0x81000000
Expect the "=== awto boot payload ===" banner on UART0.

Usage: build_hello_payload.py
Log: tmp/logs/build_hello_payload.log
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "firmware/hello"
LOG = ROOT / "tmp/logs/build_hello_payload.log"
TFTP = ROOT / "tmp/tftp"

CFLAGS = [
    "--target=mips-linux-gnu", "-march=mips32r2", "-EB",
    "-ffreestanding", "-nostdlib", "-fno-pic", "-mno-abicalls",
    "-fno-builtin", "-Wall", "-Wextra",
]


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def run(cmd: list[str]) -> None:
    log("  $ " + " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if r.stdout.strip():
        log(r.stdout.strip())
    if r.returncode != 0:
        log(r.stderr.strip())
        raise SystemExit(f"command failed ({r.returncode})")
    if r.stderr.strip():
        log(r.stderr.strip())


def main() -> int:
    log(f"=== build_hello_payload {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ===")
    start_o = SRC / "start.o"
    main_o = SRC / "main.o"
    elf = SRC / "hello.elf"
    binf = SRC / "hello.bin"

    run(["clang", *CFLAGS, "-c", str(SRC / "start.S"), "-o", str(start_o)])
    run(["clang", *CFLAGS, "-O2", "-c", str(SRC / "main.c"), "-o", str(main_o)])
    run(["ld.lld", "-T", str(SRC / "link.ld"), "-o", str(elf),
         str(start_o), str(main_o)])
    run(["llvm-objcopy", "-O", "binary", str(elf), str(binf)])

    size = binf.stat().st_size
    log(f"wrote {binf} ({size} bytes)")
    # sanity: entry must be 0x81000000 and first insn the sp setup
    dis = subprocess.run(["llvm-objdump", "-d", str(elf)],
                         capture_output=True, text=True, timeout=30).stdout
    head = "\n".join(l for l in dis.splitlines()
                     if "_start" in l or "lui" in l)[:400]
    log("entry disasm:\n" + head)
    TFTP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binf, TFTP / "hello.bin")
    log(f"copied to {TFTP / 'hello.bin'}")
    log("DONE. Boot: tftpboot 0x81000000 hello.bin ; go 0x81000000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
