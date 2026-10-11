#!/usr/bin/env python3
"""Build the stage-0 initramfs for the mainline kernel: static BusyBox + /init -> shell on the console.

- BusyBox: `sources/busybox/busybox-mips` (static, MIPS-I o32 BE, musl), sha256-checked; URL in
  sources/README.md. Fetch it with playwrong's download tool if missing.
- Output: tmp/initramfs/st1008f-initramfs.cpio.xz (newc, mtime 0, uid/gid 0: byte-identical per input)
  + tmp/initramfs/initramfs.config (CONFIG_INITRAMFS_SOURCE, merged by mainline_build_check.py).
- xz inside, not raw cpio: keeps the uImage raw size under the bootm limit (mainline_uimage.py).
- /init: mount proc/sys/devtmpfs/debugfs, print INIT_MARKER, shell with PROMPT on the console.
- Log: tmp/logs/mainline_initramfs.log
"""

import hashlib
import lzma
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mainline_initramfs.log"
OUT = ROOT / "tmp/initramfs"
BUSYBOX = ROOT / "sources/busybox/busybox-mips"
BUSYBOX_URL = "https://busybox.net/downloads/binaries/1.31.0-defconfig-multiarch-musl/busybox-mips"
BUSYBOX_SHA256 = "c3fed048a70d5529f95820c5abb77553efc276a89a8608414ca03e53d6bedd1d"
INIT_MARKER = "st1008f-initramfs: up"
PROMPT = "st1008f-linux # "

INIT = f"""#!/bin/sh
/bin/busybox --install -s
export PATH=/sbin:/bin:/usr/sbin:/usr/bin HOME=/root PS1='{PROMPT}'
mount -t proc proc /proc
mount -t sysfs sysfs /sys
mount -t devtmpfs devtmpfs /dev
mount -t debugfs debugfs /sys/kernel/debug
echo "{INIT_MARKER} (Linux $(uname -r))"
cd /root
exec setsid cttyhack sh
"""

DIRS = ["bin", "sbin", "usr", "usr/bin", "usr/sbin", "dev", "proc", "sys", "tmp", "root", "mnt"]


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


class Cpio:
    """newc writer; fixed inode numbers, mtime 0, owner root."""

    def __init__(self) -> None:
        self.buf = bytearray()
        self.ino = 1

    def _entry(self, name: str, mode: int, data: bytes = b"", rdev: tuple[int, int] = (0, 0)) -> None:
        nm = name.encode() + b"\0"
        fields = [self.ino, mode, 0, 0, 1, 0, len(data), 0, 0, rdev[0], rdev[1], len(nm), 0]
        self.ino += 1
        self.buf += b"070701" + b"".join(b"%08X" % f for f in fields) + nm
        self.buf += b"\0" * (-len(self.buf) % 4) + data
        self.buf += b"\0" * (-len(self.buf) % 4)

    def dir(self, name: str) -> None:
        self._entry(name, 0o040755)

    def file(self, name: str, data: bytes, perm: int = 0o755) -> None:
        self._entry(name, 0o100000 | perm, data)

    def symlink(self, name: str, target: str) -> None:
        self._entry(name, 0o120777, target.encode())

    def chardev(self, name: str, major: int, minor: int, perm: int = 0o600) -> None:
        self._entry(name, 0o020000 | perm, rdev=(major, minor))

    def finish(self) -> bytes:
        self._entry("TRAILER!!!", 0)
        return bytes(self.buf)


def build() -> Path:
    if not BUSYBOX.exists():
        raise SystemExit(f"missing {BUSYBOX.relative_to(ROOT)}: download {BUSYBOX_URL} "
                         f"(playwrong download tool), sha256 {BUSYBOX_SHA256}")
    bb = BUSYBOX.read_bytes()
    if hashlib.sha256(bb).hexdigest() != BUSYBOX_SHA256:
        raise SystemExit(f"{BUSYBOX.relative_to(ROOT)}: sha256 mismatch (bad download?)")
    c = Cpio()
    for d in DIRS:
        c.dir(d)
    c.chardev("dev/console", 5, 1)  # kernel opens it before /init; devtmpfs is mounted later
    c.file("bin/busybox", bb)
    c.symlink("bin/sh", "busybox")
    c.file("init", INIT.encode())
    cpio = c.finish()
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / "st1008f-initramfs.cpio.xz"
    # kernel XZ decoder: CRC32 check, LZMA2 only
    out.write_bytes(lzma.compress(cpio, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32,
                                  filters=[{"id": lzma.FILTER_LZMA2, "preset": 9}]))
    (OUT / "initramfs.config").write_text(f'CONFIG_INITRAMFS_SOURCE="{out}"\n')
    log(f"{out}: cpio {len(cpio)} B -> xz {out.stat().st_size} B, "
        f"sha256 {hashlib.sha256(out.read_bytes()).hexdigest()[:16]}")
    return OUT / "initramfs.config"


if __name__ == "__main__":
    build()
