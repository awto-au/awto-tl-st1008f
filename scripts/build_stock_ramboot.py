#!/usr/bin/env python3
"""build_stock_ramboot — make a RAM-bootable (tftp+bootm) vendor-kernel image
that gives a ROOT SHELL on ttyS0 for analysis.

Why: the stock initramfs has fake /dev (0-byte regular files) and /etc/rc runs
`diag` in the foreground, so serial is silent and bootargs rdinit tricks hit the
no-controlling-terminal EOF. Fix: supply an EXTERNAL initramfs (unpacked over the
built-in one) with REAL /dev nodes + an /etc/inittab that respawns /bin/sh on
ttyS0 — busybox init allocates the controlling terminal properly (setsid +
TIOCSCTTY), which bootargs cannot.

Pieces:
1. Kernel: carve the RTK uImage from the firmware partition and re-stamp the
   magic 0x93000000 -> 0x27051956 (+ fix header CRC) so stock `bootm` accepts it.
   LZMA payload and load/entry are unchanged.
2. Ramdisk: overlay cpio (fakeroot, no root) = real /dev nodes + /etc/inittab,
   gzip, wrapped as a standard ramdisk uImage.

Outputs to tmp/tftp/: stock-kernel.uImage, shell-ramdisk.uImage
Boot (stock U-Boot): tftpboot <ka> stock-kernel.uImage; tftpboot <ra> shell-ramdisk.uImage; bootm <ka> <ra>

Usage: build_stock_ramboot.py
Log: tmp/logs/build_stock_ramboot.log
"""

from __future__ import annotations

import binascii
import struct
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/build_stock_ramboot.log"
FW = ROOT / "private/mtd-backup-20261008-145913/mtd5-firmware.bin"
OUT = ROOT / "tmp/tftp"
STAGE = ROOT / "tmp/ramboot-stage"

UIMAGE_MAGIC = 0x27051956
RTK_MAGIC = 0x93000000
# standard uImage 64-byte header: >IIIIIIIBBBB32s  (magic hcrc time size load ep
# dcrc os arch type comp name)
HDR = ">IIIIIIIBBBB32s"


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def crc32(b: bytes) -> int:
    return binascii.crc32(b) & 0xFFFFFFFF


def make_kernel_uimage() -> Path:
    raw = FW.read_bytes()
    (magic, hcrc, t, size, load, ep, dcrc, os_, arch, typ, comp, name) = \
        struct.unpack(HDR, raw[:64])
    if magic != RTK_MAGIC:
        raise SystemExit(f"firmware does not start with RTK magic: {magic:#x}")
    name_s = name.split(b"\0", 1)[0].decode("latin1")
    log(f"RTK uImage: name={name_s} size={size:#x} load={load:#x} "
        f"ep={ep:#x} os={os_} arch={arch} type={typ} comp={comp}")
    data = raw[64:64 + size]
    if crc32(data) != dcrc:
        log(f"  WARNING: data CRC mismatch (hdr {dcrc:#x} vs {crc32(data):#x})")
    else:
        log("  data CRC OK")
    # re-stamp magic -> standard; recompute hcrc over header with hcrc field = 0
    hdr0 = struct.pack(HDR, UIMAGE_MAGIC, 0, t, size, load, ep, dcrc,
                       os_, arch, typ, comp, name)
    new_hcrc = crc32(hdr0)
    hdr = struct.pack(HDR, UIMAGE_MAGIC, new_hcrc, t, size, load, ep, dcrc,
                      os_, arch, typ, comp, name)
    out = OUT / "stock-kernel.uImage"
    out.write_bytes(hdr + data)
    log(f"wrote {out} ({out.stat().st_size} B) magic->0x27051956 hcrc={new_hcrc:#x}")
    return out


def build_initramfs() -> bytes:
    """Overlay cpio: real /dev nodes + /etc/inittab. Built via fakeroot so the
    device nodes exist in the archive without needing real root."""
    if STAGE.exists():
        subprocess.run(["rm", "-rf", str(STAGE)], check=True)
    (STAGE / "dev").mkdir(parents=True)
    (STAGE / "etc").mkdir(parents=True)
    # inittab: no diag. sysinit mounts proc; respawn a login shell on ttyS0.
    # busybox init opens /dev/ttyS0 and makes it the controlling terminal.
    (STAGE / "etc/inittab").write_text(
        "::sysinit:/bin/mount -t proc proc /proc\n"
        "::sysinit:/bin/mount -t sysfs sysfs /sys\n"
        "ttyS0::respawn:-/bin/sh\n"
        "::ctrlaltdel:/bin/reboot\n"
    )
    # device nodes to create (name, type, major, minor)
    nodes = [
        ("dev/console", "c", 5, 1), ("dev/ttyS0", "c", 4, 64),
        ("dev/ttyS1", "c", 4, 65), ("dev/tty", "c", 5, 0),
        ("dev/null", "c", 1, 3), ("dev/zero", "c", 1, 5),
        ("dev/kmsg", "c", 1, 11), ("dev/ptmx", "c", 5, 2),
    ]
    mknods = "; ".join(f"mknod {STAGE}/{n} {t} {maj} {mi}"
                       for (n, t, maj, mi) in nodes)
    # Under fakeroot: make nodes, then cpio (newc) the staged tree, gzip.
    cpio = OUT / "_shell-initramfs.cpio.gz"
    script = (
        f"{mknods}; "
        f"cd {STAGE} && find . | cpio -o -H newc 2>/dev/null | gzip -9 > {cpio}"
    )
    subprocess.run(["fakeroot", "sh", "-c", script], check=True)
    blob = cpio.read_bytes()
    cpio.unlink()
    log(f"overlay initramfs: {len(blob)} B gz ({len(nodes)} dev nodes + inittab)")
    return blob


def make_ramdisk_uimage(payload: bytes) -> Path:
    name = b"stock-shell-initramfs"
    hdr0 = struct.pack(HDR, UIMAGE_MAGIC, 0, int(time.time()), len(payload),
                       0, 0, crc32(payload), 5, 5, 3, 1, name)  # os linux arch mips type ramdisk comp gzip
    hcrc = crc32(hdr0)
    hdr = struct.pack(HDR, UIMAGE_MAGIC, hcrc, int(time.time()), len(payload),
                      0, 0, crc32(payload), 5, 5, 3, 1, name)
    out = OUT / "shell-ramdisk.uImage"
    out.write_bytes(hdr + payload)
    log(f"wrote {out} ({out.stat().st_size} B) ramdisk uImage")
    return out


def main() -> int:
    log(f"=== build_stock_ramboot {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ===")
    OUT.mkdir(parents=True, exist_ok=True)
    k = make_kernel_uimage()
    r = make_ramdisk_uimage(build_initramfs())
    log("DONE. Boot in stock U-Boot:")
    log(f"  tftpboot 0x84f00000 {k.name}")
    log(f"  tftpboot 0x86000000 {r.name}")
    log("  bootm 0x84f00000 0x86000000")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
