#!/usr/bin/env python3
"""uimage_std_magic — copy a Realtek-magic uImage with the standard magic, for mainline `bootm`.

- OpenWrt RTL930x images use magic 0x93030000 (stock U-Boot accepts it); mainline U-Boot only
  accepts IH_MAGIC 0x27051956. Header CRC recomputed; payload and its data CRC untouched.
- Usage: scripts/uimage_std_magic.py <in> <out>. Log: tmp/logs/uimage_std_magic.log.
"""

import struct
import sys
import time
import zlib
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/uimage_std_magic.log"
IH_MAGIC, RTK_MAGIC, HDR = 0x27051956, 0x93030000, 64


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def main() -> int:
    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    img = bytearray(src.read_bytes())
    magic, _, _, size = struct.unpack(">4I", img[:16])
    if magic not in (IH_MAGIC, RTK_MAGIC) or len(img) != HDR + size:
        log(f"FAIL {src}: magic {magic:#x}, size field {size} vs file {len(img) - HDR}")
        return 1
    if zlib.crc32(img[HDR:]) != struct.unpack(">I", img[24:28])[0]:
        log(f"FAIL {src}: data CRC mismatch")
        return 1
    struct.pack_into(">II", img, 0, IH_MAGIC, 0)
    struct.pack_into(">I", img, 4, zlib.crc32(img[:HDR]))
    dst.write_bytes(img)
    log(f"{src.name} magic {magic:#x} -> {IH_MAGIC:#x}: {dst} ({len(img)} B)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
