#!/usr/bin/env python3
"""Unpack a TP-Link `OW`-magic web asset bundle (webImage.z / webImage.decoded).

Format (all integers big-endian u32):
- Optional LZMA-alone wrapper (`5d 00 00 80 00`), as in `usrImage/data/webImage.z`.
- Header: magic `OW` x16 (32 bytes), version (=1), file count N.
- N entries of 140 bytes: name[128] (NUL-padded, absolute path), size, offset, flags (seen: 0).
- Data at `offset` (absolute in the bundle), 4-byte aligned, stored uncompressed.
- Parse only, never execute. Run with `python3 -I`.
- Log: tmp/logs/tplink_ow_unpack.log
"""

import argparse
import json
import logging
import lzma
import struct
import sys
from pathlib import Path

MAGIC = b"OW" * 16
ENTRY = struct.Struct(">128sIII")
log = logging.getLogger("tplink_ow_unpack")


def load(path: Path) -> bytes:
    data = path.read_bytes()
    if data[:5] == b"\x5d\x00\x00\x80\x00":
        data = lzma.decompress(data, format=lzma.FORMAT_ALONE)
        log.info("lzma-alone unwrapped: %d bytes", len(data))
    return data


def parse(data: bytes) -> list[dict]:
    if data[:32] != MAGIC:
        raise ValueError("no OW magic")
    version, count = struct.unpack_from(">II", data, 32)
    log.info("version %d, %d entries", version, count)
    out, pos = [], 40
    for _ in range(count):
        name, size, off, flags = ENTRY.unpack_from(data, pos)
        pos += ENTRY.size
        name = name.rstrip(b"\0").decode("utf-8", "replace")
        if off + size > len(data):
            raise ValueError(f"{name}: data past end ({off:#x}+{size:#x})")
        out.append({"name": name, "size": size, "offset": off, "flags": flags})
    return out


def safe_rel(name: str) -> Path:
    parts = [p for p in Path(name).parts if p not in ("/", "..", ".")]
    return Path(*parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("bundle", type=Path)
    ap.add_argument("out", type=Path, help="output directory (put it under private/)")
    ap.add_argument("--list", action="store_true", help="list only, write nothing")
    a = ap.parse_args()
    Path("tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.FileHandler("tmp/logs/tplink_ow_unpack.log", "w"),
                                  logging.StreamHandler()])
    data = load(a.bundle)
    entries = parse(data)
    flags = sorted({e["flags"] for e in entries})
    log.info("total payload %d bytes; flags seen %s", sum(e["size"] for e in entries), flags)
    for e in entries:
        log.info("%8d %#9x %s", e["size"], e["offset"], e["name"])
        if a.list:
            continue
        dst = a.out / safe_rel(e["name"])
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data[e["offset"]:e["offset"] + e["size"]])
    if not a.list:
        (a.out / "manifest.json").write_text(json.dumps(entries, indent=1))
        log.info("wrote %d files to %s", len(entries), a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
