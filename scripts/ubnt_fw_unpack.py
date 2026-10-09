#!/usr/bin/env python3
"""Split a Ubiquiti UBNT firmware .bin into its PART payloads and scan each for embedded images.

- Layout per OpenWrt `mkfwimage`: "UBNT" + 256-byte version + crc/pad, then PART blocks
  (magic, name[16], pad[12], memaddr, index, baseaddr, entryaddr, data_size, part_size; BE u32),
  each followed by crc+pad (8 bytes).
- Writes `<out>/<index>-<name>.bin` and lists gzip/xz/lzma/uImage/FIT/squashfs offsets in each.
- Log: tmp/logs/ubnt_fw_unpack.log
"""

import argparse
import gzip
import logging
import lzma
import math
import struct
import sys
import zlib
from pathlib import Path

PART_HDR = struct.Struct(">4s16s12sIIIIII")
MAGICS = {
    b"\x1f\x8b\x08": "gzip",
    b"\xfd7zXZ\x00": "xz",
    b"\x5d\x00\x00\x80\x00": "lzma",
    b"\x27\x05\x19\x56": "uImage",
    b"\xd0\x0d\xfe\xed": "FIT/DTB",
    b"hsqs": "squashfs",
    b"\x07\x07\x07\x07": "cpio-ascii?",
    b"070701": "cpio-newc",
}

log = logging.getLogger("ubnt_fw_unpack")


def scan(data: bytes) -> list[tuple[int, str]]:
    hits = lzma_alone_hits(data)
    for magic, name in MAGICS.items():
        start = 0
        while (i := data.find(magic, start)) != -1:
            hits.append((i, name))
            start = i + 1
    return sorted(hits)


def lzma_alone_hits(data: bytes) -> list[tuple[int, str]]:
    """LZMA-alone headers with unknown size: props<225, power-of-2 dict, 8x 0xff.

    - Catches non-default lc/lp/pb (e.g. 0x6d) that a fixed 0x5d magic misses.
    """
    hits = []
    start = 0
    while (i := data.find(b"\xff" * 8, start)) != -1:
        start = i + 1
        h = i - 5
        if h < 0 or data[h] >= 225:
            continue
        d = int.from_bytes(data[h + 1 : h + 5], "little")
        if d >= 0x1000 and d & (d - 1) == 0 and data[i + 8] == 0:
            hits.append((h, "lzma-alone"))
    return hits


def unpack(fw: Path, out: Path) -> None:
    data = fw.read_bytes()
    if data[:4] != b"UBNT":
        raise SystemExit(f"{fw}: no UBNT magic")
    log.info("version: %s", data[4:260].split(b"\0", 1)[0].decode(errors="replace"))
    out.mkdir(parents=True, exist_ok=True)
    pos = data.find(b"PART")
    while pos != -1 and pos + PART_HDR.size <= len(data):
        magic, name, _, mem, idx, base, entry, dsize, psize = PART_HDR.unpack_from(data, pos)
        if magic != b"PART":
            break
        name_s = name.split(b"\0", 1)[0].decode(errors="replace") or "noname"
        body = data[pos + PART_HDR.size : pos + PART_HDR.size + dsize]
        dest = out / f"{idx:02d}-{name_s}.bin"
        dest.write_bytes(body)
        log.info("PART @0x%x %-10s idx=%d mem=0x%x base=0x%x entry=0x%x data=%d part=%d -> %s",
                 pos, name_s, idx, mem, base, entry, dsize, psize, dest.name)
        for off, kind in scan(body)[:40]:
            log.info("    +0x%08x %s", off, kind)
        if body[:4] == b"\x27\x05\x19\x56":
            payload = body[64:]
            comp = body[31]  # ih_comp: 0 none, 1 gzip, 3 lzma
            dec = {0: bytes, 1: gzip.decompress,
                   3: lambda b: lzma.LZMADecompressor(lzma.FORMAT_ALONE).decompress(b)}
            raw = dec[comp](payload)
            dest.with_suffix(".img").write_bytes(raw)
            log.info("    uImage '%s' comp=%d -> %s (%d bytes)",
                     body[32:64].split(b"\0", 1)[0].decode(errors="replace"), comp,
                     dest.with_suffix(".img").name, len(raw))
            for off, kind in scan(raw)[:40]:
                log.info("        +0x%08x %s", off, kind)
                if kind in ("xz", "gzip", "lzma-alone"):
                    extract_stream(kind, raw[off:], dest.with_suffix(f".{kind}@{off:x}"))
        pos = data.find(b"PART", pos + PART_HDR.size + dsize)


def extract_stream(kind: str, blob: bytes, dest: Path) -> None:
    """Decompress one xz/gzip stream (e.g. the kernel's built-in initramfs); trailing bytes ignored."""
    try:
        if kind == "xz":
            raw = lzma.LZMADecompressor(lzma.FORMAT_XZ).decompress(blob)
        elif kind == "lzma-alone":
            raw = lzma.LZMADecompressor(lzma.FORMAT_ALONE).decompress(blob)
        else:
            raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(blob)
    except (lzma.LZMAError, zlib.error) as e:
        log.info("            %s: not a valid stream (%s)", kind, e)
        return
    dest.write_bytes(raw)
    log.info("            %s -> %s (%d bytes)", kind, dest.name, len(raw))


def entropy_map(path: Path, block: int = 0x10000) -> None:
    """Log Shannon entropy (bits/byte) per block; runs >7.9 are compressed or encrypted payloads."""
    data = path.read_bytes()
    prev = None
    for off in range(0, len(data), block):
        chunk = data[off : off + block]
        counts = [0] * 256
        for b in chunk:
            counts[b] += 1
        h = -sum(c / len(chunk) * math.log2(c / len(chunk)) for c in counts if c)
        band = "high" if h > 7.9 else "zero" if h < 0.5 else "mid"
        if band != prev:
            log.info("entropy %s +0x%08x %s (%.2f)", path.name, off, band, h)
            prev = band


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("firmware", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--entropy", type=Path, help="only print an entropy map of this file")
    ap.add_argument("--block", type=lambda s: int(s, 0), default=0x10000, help="entropy block size")
    args = ap.parse_args()
    Path("tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler("tmp/logs/ubnt_fw_unpack.log", mode="w")])
    if args.entropy:
        entropy_map(args.entropy, args.block)
    else:
        unpack(args.firmware, args.out)


if __name__ == "__main__":
    main()
