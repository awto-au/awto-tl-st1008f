#!/usr/bin/env python3
"""uboot_chain_install — put our U-Boot into flash `jffs2-log` from the running flash OpenWrt (#47 A).

- Checks: `jffs2-log` exists in /proc/mtd, is not mounted, and is all 0xff (unused) unless --overwrite.
- Transfer: host HTTP (this script, one file, bound to SERVER_IP) -> switch `wget`; md5 on both ends.
- `mtd write <file> jffs2-log`, then read back the image length and compare md5.
- Does NOT touch the stock env (bootcmd change is a separate step, #47).
- Log: tmp/logs/uboot_chain_install.log
"""

import argparse
import functools
import hashlib
import http.server
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_guard  # noqa: E402
from st1008_ramload import OW_PROMPT, SERVER_IP, SWITCH_IP, TFTP_ROOT, Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/uboot_chain_install.log"
IMAGE = TFTP_ROOT / "uboot-mainline.bin"
PART, PART_SIZE = "jffs2-log", 0x100000
PORT = 8008


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(con: Console, cmd: str, want: str = "", cap: float = 2) -> str:
    assert len(cmd) <= 60, cmd  # BusyBox echoes longer lines differently (echo check fails)
    return con.run(cmd, (want + r"[\s\S]*?" if want else "") + OW_PROMPT, cap, cmd)[1]


SSH_S = 5  # dropbear connect ~1 s on the LAN; x5


def ssh(ip: str, cmd: str, cap: float, stdin: bytes | None = None) -> str:
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes", f"root@{ip}", cmd],
                       input=stdin, capture_output=True, timeout=cap)
    if r.returncode:
        raise SystemExit(f"FAIL ssh {ip}: rc {r.returncode} {r.stderr.decode(errors='replace').strip()} ({cmd[:60]})")
    return r.stdout.decode(errors="replace")


def install_ssh(ip: str, data: bytes, md5: str) -> int:
    """Running OpenWrt over SSH (sw1 has no console): replaces OUR older U-Boot in jffs2-log only."""
    n = re.search(rf'mtd(\d+): 00100000 00010000 "{PART}"', ssh(ip, "cat /proc/mtd", SSH_S * 2)).group(1)
    if f"mtdblock{n} " in ssh(ip, "mount", SSH_S * 2):
        log(f"FAIL: mtd{n} ({PART}) is mounted on {ip}")
        return 1
    # only over an older copy of ours: its banner string must be in the first 600 KB (~0.1 s read)
    if ssh(ip, f"head -c 600000 /dev/mtdblock{n} | grep -c -a 'U-Boot 20'; true", SSH_S * 2).strip() in ("", "0"):
        log(f"FAIL: {PART} (mtd{n}) on {ip} does not hold our U-Boot; refusing")
        return 1
    ssh(ip, "cat > /tmp/u.bin", SSH_S * 3, stdin=data)  # ~460 KB over the LAN: < 1 s
    got = ssh(ip, "md5sum /tmp/u.bin", SSH_S * 2).split()[0]
    if got != md5:
        log(f"FAIL: transfer md5 {got} != {md5}")
        return 1
    # mtd write = erase up to 8 x 64 KiB blocks (W25Q256 max 2 s each) + ~460 KB program: ~18 s worst, x1.25
    ssh(ip, f"mtd write /tmp/u.bin {PART}", 25)
    rb = ssh(ip, f"head -c {len(data)} /dev/mtdblock{n} | md5sum", SSH_S * 2).split()[0]
    ok = rb == md5
    log(f"{'PASS' if ok else 'FAIL'}: {PART} (mtd{n}, flash 0x200000) read-back md5 {rb}"
        f"{'' if ok else ' != ' + md5}; switch {ip} (ssh)")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--overwrite", action="store_true", help="partition may hold an older copy of ours")
    ap.add_argument("--ssh", metavar="IP", help="install over SSH on a running OpenWrt (no console; "
                    "replaces an older copy of ours only)")
    a = ap.parse_args()
    data = IMAGE.read_bytes()
    md5 = hashlib.md5(data).hexdigest()
    log(f"image {IMAGE.name}: {len(data)} B md5 {md5}")
    if len(data) > PART_SIZE:
        log(f"FAIL: image larger than {PART} ({PART_SIZE:#x})")
        return 1
    flash_guard.check_mtd(PART, "uboot-chain-install")  # #81, before any console command
    flash_guard.check_range(0x200000, len(data), "uboot-chain-install")
    if a.ssh:
        return install_ssh(a.ssh, data, md5)
    con = Console()
    sh(con, "dmesg -n 1")
    n = re.search(rf'mtd(\d+): 00100000 00010000 "{PART}"', sh(con, "cat /proc/mtd", r"mtd0:")).group(1)
    if f"mtdblock{n} " in sh(con, "mount"):
        log(f"FAIL: mtd{n} ({PART}) is mounted")
        return 1
    # unused = whole partition 0xff: hexdump collapses repeats to `*`; 1 MiB at ~22 MB/s < 0.1 s
    blank = "" if a.overwrite else sh(con, f"hexdump -C /dev/mtdblock{n} | head -4", r"\n00100000")
    if not a.overwrite and not re.search(r"00000000  (ff ){8} (ff ){8}.*\n\*\r?\n00100000", blank):
        log(f"FAIL: {PART} (mtd{n}) is not blank; refusing (use --overwrite only for our own image)")
        return 1
    srv = http.server.ThreadingHTTPServer(
        (SERVER_IP, PORT), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(TFTP_ROOT)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        # ~300 KB over the LAN: well under 1 s; cap 5 s names a routing/firewall problem
        sh(con, f"U=http://{SERVER_IP}:{PORT}")
        # right after boot STP holds the ports: listen + learn = 2 x 15 s forward delay; x1.25 = 8 x 5 s
        for _ in range(8):
            if re.search(r"\nGOT_OK", sh(con, f"wget -q -O /tmp/u.bin $U/{IMAGE.name} && echo GOT_OK", cap=5)):
                break
            time.sleep(5)
    finally:
        srv.shutdown()
    got = re.search(r"\n([0-9a-f]{32})\s", sh(con, "md5sum /tmp/u.bin", r"[0-9a-f]{32}"))
    if not got or got.group(1) != md5:
        log(f"FAIL: transfer md5 {got and got.group(1)} != {md5}")
        return 1
    # mtd write = erase 5 x 64 KiB blocks (W25Q256 max 2 s each) + ~300 KB program; ~11 s worst, x1.25
    sh(con, f"mtd write /tmp/u.bin {PART} && echo MTD_OK", r"\nMTD_OK", cap=15)
    rb = sh(con, f"head -c {len(data)} /dev/mtdblock{n} | md5sum", r"[0-9a-f]{32}")
    rb_md5 = re.search(r"\n([0-9a-f]{32})\s", rb).group(1)
    ok = rb_md5 == md5
    log(f"{'PASS' if ok else 'FAIL'}: {PART} (mtd{n}, flash 0x200000) read-back md5 {rb_md5}"
        f"{'' if ok else ' != ' + md5}; switch {SWITCH_IP}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
