#!/usr/bin/env python3
"""st1008_stock_extract — unpack the stock TL-ST1008F RUNTIME image from a full-flash dump.

RUNTIME @ 0x300000 = legacy uImage layout with Realtek magic 0x93000000, LZMA kernel.
Outputs: vmlinux, each embedded cpio (gzip/xz/plain) as initramfs-N/, any squashfs
found after the kernel as squashfs-N.bin + extracted tree.

Usage:
    scripts/st1008_stock_extract.py FULL_FLASH.bin [--out DIR]

Log: tmp/logs/st1008_stock_extract.log
"""

from __future__ import annotations

import argparse
import gzip
import lzma
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/st1008_stock_extract.log"
RUNTIME_OFF, RUNTIME_LEN = 0x300000, 0xE80000  # stock "RUNTIME" mtd, boot log
HDR_LEN = 0x40
RTK_MAGIC = 0x93000000
_log_fh = None


def log(msg: str):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    _log_fh.write(line + "\n")
    _log_fh.flush()


def extract_cpio(blob: bytes, dst: Path):
    dst.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["cpio", "-idm", "--no-absolute-filenames", "--quiet"],
                       input=blob, cwd=dst, capture_output=True)
    log(f"cpio -> {dst} rc={r.returncode} {r.stderr.decode(errors='replace').strip()[:200]}")


def find_initramfs(vmlinux: bytes, out: Path):
    n = 0
    # plain newc cpio
    i = vmlinux.find(b"070701")
    if i >= 0:
        log(f"plain cpio at vmlinux+{i:#x}")
        extract_cpio(vmlinux[i:], out / f"initramfs-{n}")
        n += 1
    # compressed cpio candidates
    for magic, kind in ((b"\x1f\x8b\x08", "gzip"), (b"\xfd7zXZ\x00", "xz"),
                        (b"\x5d\x00\x00", "lzma")):
        start = 0
        while (i := vmlinux.find(magic, start)) >= 0:
            start = i + 1
            try:
                if kind == "gzip":
                    data = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(vmlinux[i:])
                else:
                    fmt = lzma.FORMAT_XZ if kind == "xz" else lzma.FORMAT_ALONE
                    data = lzma.LZMADecompressor(format=fmt).decompress(vmlinux[i:])
            except (zlib.error, lzma.LZMAError, EOFError):
                continue
            if data.startswith(b"070701"):
                log(f"{kind} cpio at vmlinux+{i:#x}, {len(data):#x} bytes")
                extract_cpio(data, out / f"initramfs-{n}")
                n += 1
    return n


def main() -> int:
    global _log_fh
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("flash", type=Path)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out = args.out or args.flash.parent / "stock-extract"
    out.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    _log_fh = LOG.open("a")

    rt = args.flash.read_bytes()[RUNTIME_OFF:RUNTIME_OFF + RUNTIME_LEN]
    magic, hcrc, ts, size, load, ep, dcrc, os_, arch, typ, comp = struct.unpack(
        ">IIIIIIIBBBB", rt[:32])
    name = rt[32:HDR_LEN].split(b"\0")[0].decode()
    payload = rt[HDR_LEN:HDR_LEN + size]
    crc_ok = zlib.crc32(payload) == dcrc
    log(f"magic={magic:#x} name={name} size={size:#x} load={load:#x} ep={ep:#x} "
        f"ts={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ts))} comp={comp} "
        f"data_crc {'OK' if crc_ok else 'BAD'}")
    if magic != RTK_MAGIC or not crc_ok:
        log("unexpected header/CRC; stopping")
        return 1

    vmlinux = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE).decompress(payload)
    (out / "vmlinux.bin").write_bytes(vmlinux)
    log(f"vmlinux {len(vmlinux):#x} bytes")
    cmdline = [s for s in vmlinux.split(b"\0") if b"console=" in s]
    log(f"console= strings: {cmdline[:5]}")
    log(f"initramfs found: {find_initramfs(vmlinux, out)}")

    tail = rt[HDR_LEN + size:]
    start, n = 0, 0
    while (i := tail.find(b"hsqs", start)) >= 0:
        start = i + 4
        sq = out / f"squashfs-{n}.bin"
        sq.write_bytes(tail[i:])
        dst = out / f"squashfs-{n}"
        r = subprocess.run(["unsquashfs", "-f", "-d", str(dst), str(sq)], capture_output=True)
        log(f"squashfs at RUNTIME+{HDR_LEN + size + i:#x} -> {dst} rc={r.returncode}")
        n += 1
    used = len(tail.rstrip(b"\xff"))
    log(f"after kernel: {used:#x} non-0xFF bytes, squashfs found: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
