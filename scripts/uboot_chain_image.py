#!/usr/bin/env python3
"""uboot_chain_image — self-checking slot image of our U-Boot for flash `jffs2-log` (#105).

- Slot = 512 KiB = the stock `cp.b` length: u-boot.bin at 0 (runs at 0x81000000), 0xff pad,
  trailer at SLOT - 0x40. Code stays at offset 0, so an older chain env (no check) still boots it.
- Trailer: magic, image size, image CRC32, build name; last word = CRC32 of slot[0:SLOT-4]
  (zlib CRC32 = stock U-Boot `crc32`, HISTORY.md 2026-10-08).
- Stock check (no hush, no `crc32 -v`): `crc32 0x81000000 0x7fffc 0x80ffff00;
  cmp.l 0x80ffff00 0x8107fffc 1` fails on a mismatch -> `run` stops before `go`.
- CLI: `make IN OUT [--name N]`, `check FILE`. Log: tmp/logs/uboot_chain_image.log
"""

import argparse
import struct
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/uboot_chain_image.log"
SLOT = 0x80000           # stock bootcmd copy length (scripts/uboot_chain_env.py)
TRAILER = SLOT - 0x40    # image must end before this
MAGIC = b"ST1008F-UBOOT\x00\x01\x00"  # 16 bytes; last two = format version 1.0
LOAD = 0x81000000        # TEXT_BASE; stock copies the slot here
SCRATCH = 0x80ffff00     # stock `crc32` result word, below LOAD


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def make(image: bytes, name: str) -> bytes:
    if len(image) > TRAILER:
        raise SystemExit(f"FAIL: u-boot.bin {len(image)} B > {TRAILER:#x} (slot {SLOT:#x} minus trailer)")
    nm = name.encode()[:31].ljust(32, b"\x00")
    body = image + b"\xff" * (TRAILER - len(image))
    body += MAGIC + struct.pack(">II", len(image), zlib.crc32(image)) + nm + b"\xff" * 4
    assert len(body) == SLOT - 4
    return body + struct.pack(">I", zlib.crc32(body))


def check(slot: bytes) -> tuple[bool, str]:
    """(ok, detail) for a slot read back from flash or built locally."""
    if len(slot) < SLOT:
        return False, f"{len(slot)} B < slot {SLOT:#x}"
    slot = slot[:SLOT]
    want, = struct.unpack(">I", slot[-4:])
    got = zlib.crc32(slot[:-4])
    if got != want:
        return False, f"slot CRC32 {got:08x} != trailer {want:08x} (no chain image or corrupt)"
    t = slot[TRAILER:]
    if t[:16] != MAGIC:
        return False, f"trailer magic {t[:16]!r}"
    size, icrc = struct.unpack(">II", t[16:24])
    if size > TRAILER or zlib.crc32(slot[:size]) != icrc:
        return False, f"image size {size} / CRC {icrc:08x} inconsistent"
    name = t[24:56].split(b"\x00")[0].decode(errors="replace")
    return True, f"slot CRC32 {want:08x}, image {size} B CRC32 {icrc:08x}, {name}"


def stock_check_cmd() -> str:
    """Stock U-Boot commands: fail (cmp rc 1) unless the slot copied to LOAD carries its CRC."""
    return (f"crc32 0x{LOAD:08x} 0x{SLOT - 4:x} 0x{SCRATCH:08x}; "
            f"cmp.l 0x{SCRATCH:08x} 0x{LOAD + SLOT - 4:08x} 1")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="op", required=True)
    m = sub.add_parser("make")
    m.add_argument("src")
    m.add_argument("dst")
    m.add_argument("--name", default="")
    c = sub.add_parser("check")
    c.add_argument("file")
    a = ap.parse_args()
    if a.op == "make":
        img = Path(a.src).read_bytes()
        out = make(img, a.name or Path(a.src).name)
        Path(a.dst).write_bytes(out)
        ok, detail = check(out)
        log(f"{'PASS' if ok else 'FAIL'} make {a.dst}: {detail}")
        return 0 if ok else 1
    ok, detail = check(Path(a.file).read_bytes())
    log(f"{'PASS' if ok else 'FAIL'} check {a.file}: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
