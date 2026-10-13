#!/usr/bin/env python3
"""Build the stage-0 initramfs for the mainline kernel: static BusyBox + /init -> shell on the console.

- BusyBox: `sources/busybox/busybox-mips` (static, MIPS-I o32 BE, musl), sha256-checked; URL in
  sources/README.md. Fetch it with playwrong's download tool if missing.
- Output: tmp/initramfs/st1008f-initramfs.cpio.xz (newc, mtime 0, uid/gid 0: byte-identical per input)
  + tmp/initramfs/initramfs.config (CONFIG_INITRAMFS_SOURCE, merged by mainline_build_check.py).
- xz inside, not raw cpio: keeps the uImage raw size under the bootm limit (mainline_uimage.py).
- NAT test tools (nft, iperf3, ethtool, tc, ip, dropbear): OpenWrt 24.10.7 packages via initramfs_tools.py;
  /sbin/ip and /sbin/tc point at them (BusyBox --install does not overwrite existing links).
- st1008f-selftest (#108, docs/SELFTEST.md): script from openwrt/linkcheck/files + helper/data from
  scripts/build_selftest.py (run it first); /init starts it in the background with bootargs st1008f.selftest=1.
- /init: mount proc/sys/devtmpfs/debugfs, print INIT_MARKER, shell with PROMPT on the console.
  No network config: every port stays down and unbridged until a script brings one up (#16).
- Log: tmp/logs/mainline_initramfs.log
"""

import hashlib
import lzma
import time
from pathlib import Path

import build_selftest
import initramfs_tools

ROOT = Path(__file__).resolve().parent.parent
SELFTEST = ROOT / "openwrt/linkcheck/files/usr/sbin/st1008f-selftest"
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
mount -t tracefs tracefs /sys/kernel/tracing  # not debug/tracing: that automount is deprecated
mkdir -p /dev/pts && mount -t devpts devpts /dev/pts
echo "{INIT_MARKER} (Linux $(uname -r))"
# userspace up: release U-Boot's led_boot=latch pattern (an error latch stays, #9)
L=/sys/devices/platform/st1008f-leds
grep -q '^booting' $L/state 2>/dev/null && echo 1 > $L/clear
cd /root
# serial console has no size; ash would wrap its echo at 80 columns and split logged commands
for t in /dev/ttyS0 /dev/console; do stty -F $t cols 4096 rows 100 2>/dev/null; done
# boot self-test (#108) only with bootargs st1008f.selftest=1: console flows expect a quiet prompt
grep -q 'st1008f[.]selftest=1' /proc/cmdline && (st1008f-selftest --quiet --console >/dev/null 2>&1 &)
exec setsid cttyhack sh
"""

# One cage at a time (house LAN loop, 2026-10-10): refuses while another lanX is up or a bridge exists.
PORT_UP = """#!/bin/sh
# port-up <cage 1-8> [addr/len] [vlan-id]: bring up lan<cage> only (laser on via SFP TX-disable release)
n=$1; addr=$2; vid=$3
case "$n" in [1-8]) ;; *) echo "usage: port-up <cage 1-8> [addr/len] [vlan-id]"; exit 2;; esac
for d in /sys/class/net/*; do
  [ -d "$d/bridge" ] && { echo "refused: bridge ${d##*/} exists"; exit 1; }
done
for d in /sys/class/net/lan*; do
  l=${d##*/}; [ "$l" = "lan$n" ] && continue
  ip -o link show "$l" | grep -q '[<,]UP[,>]' && { echo "refused: $l is up (one cage at a time)"; exit 1; }
done
ip link set eth0 up && ip link set "lan$n" up || exit 1
# fraglist GRO on the CPU port, as OpenWrt does: +45 % NAT/flowtable forwarding (docs/NAT.md)
ethtool -K eth0 rx-gro-list on; ethtool -K "lan$n" rx-gro-list on
dev=lan$n
if [ -n "$vid" ]; then
  ip link add link "lan$n" name "lan$n.$vid" type vlan id "$vid" && ip link set "lan$n.$vid" up || exit 1
  dev=lan$n.$vid
fi
[ -n "$addr" ] && ip addr add "$addr" dev "$dev"
# SSH for scripts/nat_bench.py: root, blank password, like the flash OpenWrt
pidof dropbear >/dev/null || dropbear -R -B
ip -br link show "lan$n"; ip -br addr show "$dev"
"""

DIRS = ["bin", "sbin", "lib", "usr", "usr/bin", "usr/sbin", "usr/lib", "usr/libexec", "dev", "proc", "sys",
        "tmp", "root", "mnt", "var", "var/run", "run"]
TOOL_LINKS = {"sbin/ip": "/usr/libexec/ip-full", "sbin/tc": "/usr/libexec/tc-tiny"}


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
    for name, (kind, data, mode) in sorted(initramfs_tools.staged_files().items()):
        if kind == "link":
            c.symlink(name, data)
        else:
            c.file(name, data, mode)
    c.file("usr/sbin/port-up", PORT_UP.encode())
    # st1008f-selftest (#108): the OpenWrt overlay script + build_selftest.py helper/data
    c.dir("usr/share")
    c.dir("usr/share/st1008f-selftest")
    c.file("usr/sbin/st1008f-selftest", SELFTEST.read_bytes())
    for name, (data, mode) in sorted(build_selftest.staged().items()):
        c.file(name, data, mode)
    c.dir("etc")
    c.dir("etc/dropbear")  # -R writes host keys here on first connect
    c.file("etc/passwd", b"root::0:0:root:/root:/bin/sh\n", 0o644)
    c.file("etc/group", b"root:x:0:\n", 0o644)
    c.file("etc/shells", b"/bin/sh\n", 0o644)
    for name, target in TOOL_LINKS.items():
        c.symlink(name, target)
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
