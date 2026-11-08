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
- Bench variant (`--bench` or env ST1008F_INITRAMFS_BENCH=1; default off, image unchanged): musl loader path
  `/tmp:/lib:/usr/lib` (perf_push.py libs found without LD_LIBRARY_PATH) + dropbear ed25519 host key made
  in the background at boot (first ssh does not stall on keygen). docs/PLAIN-KERNEL-TESTS.md.
- `--owrt-userland` (NAT-STACK-TESTS.md): nft/ip/tc/ethtool/dropbear + musl and their libs copied from the OpenWrt
  buildroot's root-realtek (the image under test), instead of the 24.10.7 ipks; iperf3 + libatomic stay from 24.10.7 (the
  OpenWrt image has neither). Adds /etc/fw4-b.nft (mainline/fw4-b.nft, loaded by nat_bench.py).
  Output st1008f-initramfs-bench-owrt.cpio.xz + initramfs-owrt.config.
- Log: tmp/logs/mainline_initramfs.log
"""

import argparse
import hashlib
import lzma
import os
import re
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
# fraglist GRO on the CPU port, as OpenWrt does: +45 % NAT/flowtable forwarding (docs/NAT-HISTORY.md)
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


OWRT_ROOT = ROOT / "tmp/openwrt-build/staging_dir/target-mips_24kc_musl/root-realtek"
OWRT_BINS = ["usr/sbin/nft", "usr/libexec/ip-full", "usr/libexec/tc-full", "usr/sbin/ethtool",
             "usr/sbin/dropbear", "usr/bin/dropbearkey", "lib/ld-musl-mips-sf.so.1"]
OWRT_LIBDIRS = ["lib", "usr/lib"]
FW4_B = ROOT / "mainline/fw4-b.nft"


def owrt_staged(root: Path = OWRT_ROOT) -> dict:
    """OWRT_BINS + the DT_NEEDED closure from root's lib dirs -> {path: ("file", bytes, mode) | ("link", target, 0)}.
    Libraries keep their soname symlinks (a symlink target is staged too)."""
    import subprocess
    out, todo = {}, list(OWRT_BINS)

    def add(rel: str) -> None:
        src = root / rel
        if rel in out:
            return
        if src.is_symlink():
            tgt = os.readlink(src)
            out[rel] = ("link", tgt, 0)
            add(os.path.normpath(os.path.join(os.path.dirname(rel), tgt)))
        elif src.is_file():
            out[rel] = ("file", src.read_bytes(), src.stat().st_mode & 0o777)
            if rel.endswith(".so") or ".so." in rel or rel in OWRT_BINS:
                todo.append(rel)
        else:
            raise SystemExit(f"owrt-userland: {rel} missing in {root}")

    seen = set()
    while todo:
        rel = todo.pop(0)
        if rel in seen:
            continue
        seen.add(rel)
        add(rel)
        real = root / rel
        if real.is_symlink():
            continue
        r = subprocess.run(["readelf", "-d", str(real)], capture_output=True, text=True)
        for need in re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", r.stdout):
            if need.startswith("libc.so"):
                need = "ld-musl-mips-sf.so.1"  # musl: libc.so is the loader
            hit = next((f"{d}/{need}" for d in OWRT_LIBDIRS if (root / d / need).exists()), None)
            if not hit:
                raise SystemExit(f"owrt-userland: {rel} needs {need}: not in {OWRT_LIBDIRS} of {root}")
            todo.append(hit)
    libc = out.get("lib/ld-musl-mips-sf.so.1")
    if libc:
        out.setdefault("lib/libc.so", ("link", "ld-musl-mips-sf.so.1", 0))
    return out


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


BENCH_INIT = """# bench variant: host key now (ed25519 keygen is fast), dropbear -R covers any other type
(dropbearkey -t ed25519 -f /etc/dropbear/dropbear_ed25519_host_key >/dev/null 2>&1 &)
"""
BENCH_LD_PATH = b"/tmp\n/lib\n/usr/lib\n"


def build(bench: bool | None = None, owrt: bool = False) -> Path:
    if bench is None:
        bench = os.environ.get("ST1008F_INITRAMFS_BENCH") == "1"
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
    init = INIT
    if bench:  # before the final `exec setsid cttyhack sh`
        init = init.replace("cd /root\n", BENCH_INIT + "cd /root\n", 1)
    c.file("init", init.encode())
    staged = initramfs_tools.staged_files()
    if owrt:  # the 24.10.7 set minus everything but iperf3 (+ its lib), then the OpenWrt image's own tools
        staged = {k: v for k, v in staged.items() if "iperf" in k or "libatomic" in k}
        staged.update(owrt_staged())
    for name, (kind, data, mode) in sorted(staged.items()):
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
        c.symlink(name, target.replace("tc-tiny", "tc-full") if owrt else target)
    if owrt:
        c.file("etc/fw4-b.nft", FW4_B.read_bytes(), 0o644)
    if bench:
        c.file("etc/ld-musl-mips-sf.path", BENCH_LD_PATH, 0o644)
    cpio = c.finish()
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / ("st1008f-initramfs-bench-owrt.cpio.xz" if owrt else
                 "st1008f-initramfs-bench.cpio.xz" if bench else "st1008f-initramfs.cpio.xz")
    # kernel XZ decoder: CRC32 check, LZMA2 only
    out.write_bytes(lzma.compress(cpio, format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC32,
                                  filters=[{"id": lzma.FILTER_LZMA2, "preset": 9}]))
    cfg = OUT / ("initramfs-owrt.config" if owrt else "initramfs.config")
    cfg.write_text(f'CONFIG_INITRAMFS_SOURCE="{out}"\n')
    log(f"{out}: cpio {len(cpio)} B -> xz {out.stat().st_size} B, "
        f"sha256 {hashlib.sha256(out.read_bytes()).hexdigest()[:16]}")
    return cfg


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bench", action="store_true", help="bench variant (see module docstring)")
    ap.add_argument("--owrt-userland", action="store_true", help="tools from the OpenWrt buildroot (see module docstring)")
    a = ap.parse_args()
    build(True if a.bench else None, a.owrt_userland)
