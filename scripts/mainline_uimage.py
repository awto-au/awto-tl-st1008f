#!/usr/bin/env python3
"""Wrap a mainline vmlinux + DTB as a stock-U-Boot-bootable uImage for the ST1008F.

- vmlinux → raw binary (objcopy) → append DTB (CONFIG_MIPS_RAW_APPENDED_DTB) → LZMA-alone
  (real size in header, not -1) → 64-byte legacy header with OpenWrt's RTL930x magic 0x93030000.
- Load address and entry are read from the ELF (no guessing).
- Stock U-Boot accepts magic 0x93030000 (OpenWrt 25.12 initramfs boots with it).
- Refuses a decompressed image over MAX_RAW (our U-Boot `SYS_BOOTM_LEN`, docs/UBOOT-MAINLINE.md).
- Log: tmp/logs/mainline_uimage.log
"""

import argparse
import lzma
import struct
import subprocess
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mainline_uimage.log"
MAGIC = 0x93030000
MAX_RAW = 0x1000000  # bootm decompress limit of our U-Boot; stock's is not recorded
IH_OS_LINUX, IH_ARCH_MIPS, IH_TYPE_KERNEL, IH_COMP_LZMA = 5, 5, 2, 3


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def elf_load_entry(vmlinux: Path, prefix: str) -> tuple[int, int]:
    out = subprocess.run([f"{prefix}readelf", "-h", "-l", str(vmlinux)], capture_output=True,
                         text=True, check=True).stdout
    entry = int(out.split("Entry point address:")[1].split()[0], 16)
    load = int(next(l for l in out.splitlines() if l.strip().startswith("LOAD")).split()[2], 16)
    return load, entry


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--vmlinux", type=Path, required=True)
    ap.add_argument("--dtb", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=ROOT / "tmp/tftp/mainline.bin")
    ap.add_argument("--cross", default="mips64-linux-gnu-")
    ap.add_argument("--name", default="mainline ST1008F")
    a = ap.parse_args()

    load, entry = elf_load_entry(a.vmlinux, a.cross)
    raw = a.out.with_suffix(".raw")
    a.out.parent.mkdir(parents=True, exist_ok=True)  # fresh checkout: no tmp/tftp yet
    subprocess.run([f"{a.cross}objcopy", "-O", "binary", "-R", ".reginfo", "-R", ".notes",
                    "-R", ".note", "-R", ".comment", "-R", ".mdebug", "-R", ".note.gnu.build-id",
                    "-S", str(a.vmlinux), str(raw)], check=True)
    body = raw.read_bytes()
    dtb = a.dtb.read_bytes()
    if dtb[:4] != b"\xd0\x0d\xfe\xed":
        raise SystemExit(f"{a.dtb}: not a DTB")
    image = body + dtb
    if len(image) > MAX_RAW:
        raise SystemExit(f"kernel+dtb {len(image)} B > bootm limit {MAX_RAW} B")
    comp = bytearray(lzma.compress(image, format=lzma.FORMAT_ALONE,
                                   filters=[{"id": lzma.FILTER_LZMA1, "preset": 9,
                                             "dict_size": 1 << 23}]))
    comp[5:13] = struct.pack("<Q", len(image))  # U-Boot 2011 wants the real size, not -1
    dcrc = zlib.crc32(comp) & 0xFFFFFFFF
    name = a.name.encode()[:31].ljust(32, b"\0")
    hdr = bytearray(struct.pack(">IIIIIIIBBBB32s", MAGIC, 0, int(time.time()), len(comp), load,
                                entry, dcrc, IH_OS_LINUX, IH_ARCH_MIPS, IH_TYPE_KERNEL,
                                IH_COMP_LZMA, name))
    hdr[4:8] = struct.pack(">I", zlib.crc32(hdr) & 0xFFFFFFFF)
    a.out.write_bytes(bytes(hdr) + bytes(comp))
    raw.unlink()
    log(f"{a.out}: kernel {len(body)} B + dtb {len(dtb)} B -> lzma {len(comp)} B; "
        f"load 0x{load:08x} entry 0x{entry:08x}")


if __name__ == "__main__":
    main()
