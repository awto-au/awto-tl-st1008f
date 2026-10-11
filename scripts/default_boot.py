#!/usr/bin/env python3
"""default_boot — OpenWrt on our 7.3 kernel as the default boot, recovery OpenWrt as fallback (#73).

Design + layout: docs/DEFAULT-BOOT.md; steps: docs/DEFAULT-BOOT-OPS.md.
- check:   host only. Validate the three images in tmp/tftp/ (uImage header + data CRC, slot fit,
           split-layout DTB inside the kernel) and print every flash write `install` would do.
- test:    RAM-boot the OpenWrt-on-7.3 initramfs (`ramload openwrt-ours`), then check at its shell:
           STP on, uci defaults, /proc/mtd split layout, devmem, bootok. No flash writes.
- status:  read-only at a running OpenWrt shell: mtd layout, stock env flag, attempt record, bootok log.
- install primary|recovery, revert: FLASH WRITES. Refused without --i-have-owner-approval; without it
           they only print the plan. primary: sysupgrade -n from the RAM-booted test image.
           recovery: mtd write from the running flash primary. revert: firmware region from --backup.
- Log: tmp/logs/default_boot.log
"""

import argparse
import functools
import hashlib
import http.server
import lzma
import re
import struct
import subprocess
import sys
import threading
import time
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import OW_PROMPT, SERVER_IP, TFTP_ROOT, Console  # noqa: E402
from uboot_chain_env import set_policy  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/default_boot.log"
PORT = 8008
RTK_MAGIC, IH_MAGIC, HDR = 0x93030000, 0x27051956, 64
# name: (file in tmp/tftp, flash offset or None, slot size); docs/DEFAULT-BOOT.md "Flash layout"
IMAGES = {
    # track-1 RAM image (scripts/build_openwrt.py) built on 7.3 with openwrt/default-boot/
    "test": ("openwrt-ours-initramfs.bin", None, 0x1000000),  # bootm limit of our U-Boot
    "primary": ("openwrt-73-sysupgrade.bin", 0x300000, 0x1600000),
    "recovery": ("openwrt-recovery-initramfs.bin", 0x1900000, 0x700000),
}
DTB_MARKS = (b"recovery\0", b"bootrec@e000000\0")  # split-layout DTS (openwrt/default-boot/0001)
APPROVAL = "--i-have-owner-approval"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def check_image(name: str) -> list[str]:
    """Problems with tmp/tftp/<image>; empty = good."""
    fname, _, slot = IMAGES[name]
    p = TFTP_ROOT / fname
    if not p.exists():
        return [f"{fname}: missing (track-1 OpenWrt build)"]
    img = p.read_bytes()
    magic, hcrc, _, size = struct.unpack(">IIII", img[:16])
    hdr = bytearray(img[:HDR])
    hdr[4:8] = b"\0\0\0\0"
    bad = []
    if magic not in (RTK_MAGIC, IH_MAGIC):
        bad.append(f"{fname}: magic {magic:#x}")
    if zlib.crc32(hdr) != hcrc:
        bad.append(f"{fname}: header CRC")
    if zlib.crc32(img[HDR:HDR + size]) != struct.unpack(">I", img[24:28])[0]:
        bad.append(f"{fname}: data CRC")
    if len(img) > slot:
        bad.append(f"{fname}: {len(img)} B > slot {slot} B")
    try:  # OpenWrt kernel-lzma: kernel + appended DTB, LZMA-alone
        kern = lzma.decompress(img[HDR:HDR + size], format=lzma.FORMAT_ALONE)
        dtb = kern[kern.rfind(b"\xd0\x0d\xfe\xed"):]  # appended DTB = last FDT magic
        bad += [f"{fname}: kernel DTB lacks {m[:-1].decode()!r} (not the split layout)"
                for m in DTB_MARKS if m not in dtb]
    except lzma.LZMAError as e:
        bad.append(f"{fname}: LZMA {e}")
    log(f"  {fname}: {len(img)} B, slot {slot} B, {'OK' if not bad else 'BAD'}")
    return bad


def plan(what: str) -> None:
    steps = {
        "primary": ["at the RAM-booted openwrt-ours (7.3) shell (`default-boot test` first):",
                    "  wget openwrt-73-sysupgrade.bin -> /tmp, md5 == host",
                    "  sysupgrade -n: erase + write `firmware` 0x300000.. (22 MiB partition, image size only);"
                    " old overlay data past the image is not touched",
                    "  reboot -> stock -> chain -> ours: `Boot: legacy` (no recovery image yet) -> primary"],
        "recovery": ["at the flash primary shell (after the soak):",
                     "  wget openwrt-recovery-initramfs.bin -> /tmp, md5 == host",
                     "  mtd write -> `recovery` 0x1900000 (7 MiB partition, image size only); read back md5",
                     "  dual-boot active from the next chained boot (`Boot: primary (attempt 1/2)`)"],
        "revert": ["at a RAM-booted upstream OpenWrt (stock layout, `ramload openwrt`):",
                   "  wget <backup>/mtd5-firmware.bin, sha256 == backup SHA256SUMS",
                   "  mtd write -> `firmware` 0x300000 (29 MiB): flash OpenWrt 25.12.4 as backed up",
                   "  our U-Boot stays (no recovery image -> legacy single-image boot)"],
    }[what]
    log(f"plan {what}: flash writes")
    for s in steps:
        log("  " + s)


def sh(con: Console, cmd: str, want: str = "", cap: float = 2) -> str:
    assert len(cmd) <= 60, cmd  # BusyBox echoes longer lines differently (echo check fails)
    return con.run(cmd, (want + r"[\s\S]*?" if want else "") + OW_PROMPT, cap, cmd)[1]


def fetch(con: Console, fname: str, dst: str) -> str:
    """Host HTTP -> switch /tmp; md5 compared. Returns md5."""
    md5 = hashlib.md5((TFTP_ROOT / fname).read_bytes()).hexdigest()
    srv = http.server.ThreadingHTTPServer(
        (SERVER_IP, PORT), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(TFTP_ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        sh(con, f"U=http://{SERVER_IP}:{PORT}")
        # <= 7 MB over 1G/10G: < 1 s; STP holds ports 2 x 2 s forward delay after boot: 8 x 1 s
        for _ in range(8):
            if re.search(r"\nGOT_OK", sh(con, f"wget -q -O {dst} $U/{fname} && echo GOT_OK", cap=5)):
                break
            time.sleep(1)
    finally:
        srv.shutdown()
    got = re.search(r"\n([0-9a-f]{32})\s", sh(con, f"md5sum {dst}", r"[0-9a-f]{32}"))
    if not got or got.group(1) != md5:
        raise SystemExit(f"FAIL: {fname} transfer md5 {got and got.group(1)} != {md5}")
    log(f"  {fname} -> {dst}: md5 {md5}")
    return md5


def mtd_index(con: Console, part: str, size: int) -> str:
    out = sh(con, "cat /proc/mtd", r"mtd0:")
    m = re.search(rf'mtd(\d+): ([0-9a-f]{{8}}) 00010000 "{part}"', out)
    if not m or int(m.group(2), 16) != size:
        raise SystemExit(f"FAIL: no {part} of {size:#x} in /proc/mtd (wrong kernel/layout?)")
    return m.group(1)


def shell_checks(con: Console) -> int:
    """At an OpenWrt-on-7.3 shell: loop safety, config, layout, record access. Read-only."""
    fails = 0
    checks = [
        ("cat /sys/class/net/switch/bridge/stp_state", r"\n1\r?\n", "bridge STP on"),
        ("cat /sys/class/net/switch/bridge/forward_delay", r"\n200\r?\n", "forward_delay 2 s"),
        ("uci get network.lan.ipaddr", r"\n192\.168\.25\.48\r?\n", "lan .48"),
        ("uci get network.lan.gateway", r"\n192\.168\.25\.254\r?\n", "gateway .254"),
        ("grep -c recovery /proc/mtd", r"\n1\r?\n", "recovery partition"),
        ("devmem 0x0e000000 32", r"\n0x[0-9A-Fa-f]{8}\r?\n", "devmem on the record page"),
        ("uname -r", r"\n7\.3", "kernel 7.3"),
        ("pidof dropbear", r"\n\d+", "dropbear"),
    ]
    for cmd, want, what in checks:
        out = sh(con, cmd)
        ok = re.search(want, out) is not None
        fails += not ok
        log(f"  {'PASS' if ok else 'FAIL'} {what}")
    return fails


def cmd_test(_a) -> int:
    if bad := check_image("test"):
        log("FAIL: " + "; ".join(bad))
        return 1
    # ramload enforces STP on any OpenWrt image and runs check-log
    r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "openwrt-ours"], timeout=240)
    # (power-cycle ~10 s + rtk network on ~8 s + TFTP ~2 s + boot ~45 s + STP) ~70 s, x1.25 + check-log
    if r.returncode not in (0, 1):  # 1 = UNKNOWN boot-log lines: reported, checks still run
        return r.returncode
    con = Console()
    sh(con, "dmesg -n 1")
    fails = shell_checks(con)
    log(f"{'PASS' if not fails else 'FAIL'} test: {fails} failed checks; ramload rc {r.returncode}")
    return 1 if fails or r.returncode else 0


def cmd_status(_a) -> int:
    con = Console()
    sh(con, "dmesg -n 1")
    for cmd in ("cat /proc/mtd", "fw_printenv st1008f_boot", "devmem 0x0e000004 32",
                "logread -e st1008f-bootok | tail -3", "uname -r"):
        log(f"  $ {cmd}\n{sh(con, cmd)}")
    return 0


def cmd_check(_a) -> int:
    bad = [b for n in IMAGES for b in check_image(n)]
    for w in ("primary", "recovery"):
        plan(w)
    for b in bad:
        log(f"  BAD {b}")
    return 1 if bad else 0


def cmd_install(a) -> int:
    plan(a.what)
    if not a.approved:
        log(f"refused: flash writes need {APPROVAL} (owner approval, CLAUDE.md hazards)")
        return 2
    if bad := check_image(a.what):
        log("FAIL: " + "; ".join(bad))
        return 1
    con = Console()
    sh(con, "dmesg -n 1")
    if a.what == "primary":
        mtd_index(con, "recovery", IMAGES["recovery"][2])  # running kernel has the split layout
        fetch(con, IMAGES["primary"][0], "/tmp/p.bin")
        set_policy("run bootcmd")  # the reboot must run the saved chain, not stop at stock
        try:
            mark = con.size()
            con.send("sysupgrade -n /tmp/p.bin")
            # erase+program ~6 MB: datasheet worst 96 x 2 s + 24k pages x 3 ms = 264 s; + boot ~45 s; x1.25
            con.expect(r"Boot:  legacy", 390, mark, "sysupgrade -> reboot -> ours (legacy)", boot_ok=True)
            con.expect(r"Please press Enter to activate", 60, mark, "flash primary console", boot_ok=True)
        finally:
            set_policy("hold")
        return 1 if shell_checks(con) else 0
    if a.what == "recovery":
        n = mtd_index(con, "recovery", IMAGES["recovery"][2])
        md5 = fetch(con, IMAGES["recovery"][0], "/tmp/r.bin")
        # ~5.4 MB: worst 83 x 2 s erase + 21k pages x 3 ms = 229 s, x1.25
        sh(con, "mtd write /tmp/r.bin recovery && echo MTD_OK", r"\nMTD_OK", cap=290)
        size = (TFTP_ROOT / IMAGES["recovery"][0]).stat().st_size
        rb = sh(con, f"head -c {size} /dev/mtdblock{n} | md5sum", r"[0-9a-f]{32}", cap=10)
        ok = md5 in rb
        log(f"{'PASS' if ok else 'FAIL'} recovery written, read-back md5 {'==' if ok else '!='} {md5}")
        return 0 if ok else 1
    return 2


def cmd_revert(a) -> int:
    plan("revert")
    if not a.approved:
        log(f"refused: flash writes need {APPROVAL}")
        return 2
    fw = Path(a.backup) / "mtd5-firmware.bin"
    sums = (Path(a.backup) / "SHA256SUMS").read_text()
    sha = hashlib.sha256(fw.read_bytes()).hexdigest()
    if sha not in sums or fw.stat().st_size != 0x1d00000:
        log(f"FAIL: {fw} sha256/size does not match the backup manifest")
        return 1
    con = Console()
    sh(con, "dmesg -n 1")
    mtd_index(con, "firmware", 0x1d00000)  # stock layout kernel: whole 29 MiB writable
    copy = TFTP_ROOT / "revert-firmware.bin"  # fetch() serves tmp/tftp only
    copy.write_bytes(fw.read_bytes())
    fetch(con, copy.name, "/tmp/f.bin")
    # 29 MiB: worst 464 x 2 s + 118k pages x 3 ms = 1282 s, x1.25
    sh(con, "mtd write /tmp/f.bin firmware && echo MTD_OK", r"\nMTD_OK", cap=1600)
    log("PASS revert: firmware region restored from backup; power-cycle boots it (legacy)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("test")
    sub.add_parser("status")
    p = sub.add_parser("install")
    p.add_argument("what", choices=["primary", "recovery"])
    p.add_argument(APPROVAL, dest="approved", action="store_true")
    p = sub.add_parser("revert")
    p.add_argument("--backup", required=True, help="private/mtd-backup-<ts>/ taken before install")
    p.add_argument(APPROVAL, dest="approved", action="store_true")
    a = ap.parse_args()
    log(f"=== default-boot {' '.join(sys.argv[1:])}")
    return {"check": cmd_check, "test": cmd_test, "status": cmd_status, "install": cmd_install,
            "revert": cmd_revert}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
