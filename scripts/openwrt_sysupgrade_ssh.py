#!/usr/bin/env python3
"""openwrt_sysupgrade_ssh — sysupgrade a running flash OpenWrt over SSH, config kept (sw1: no console).

- Owner 2026-10-13: sw1 is reflashed only when the owner requests it.
- Image: the local upstream-layout sysupgrade image (same file as openwrt_install.py).
- Refused unless the board is tplink,tl-st1008f-v2 with the upstream 29 MiB `firmware` or the A/B slots (#117).
- Config backup first (`sysupgrade -b`) -> private/sysupgrade-backup/<ip>-<ts>.tar.gz (gitignored).
- Image pushed over SSH stdin (dropbear has no sftp-server), md5 both ends, `sysupgrade -T`, then
  `sysupgrade` (config kept) detached; waits for the unit to drop off and come back, checks the new
  revision and STP, then runs switch_check.py.
- Writes only `firmware` / the inactive A/B slot (flash_guard). Log: tmp/logs/openwrt_sysupgrade_ssh.log
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_guard  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/openwrt_sysupgrade_ssh.log"
SRC = ROOT / "tmp/openwrt-build/bin/targets/realtek/rtl930x/openwrt-realtek-rtl930x-tplink_tl-st1008f-v2-squashfs-sysupgrade.bin"
BACKUP = ROOT / "private/sysupgrade-backup"
FIRMWARE = (0x300000, 0x1D00000)  # upstream layout: 0x300000 to the end of the 32 MiB chip
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
CMD_S = 30     # one SSH command: sysupgrade -T / -b ~2-5 s on a 1 GHz MIPS; x6 for a loaded box
PUSH_S = 60    # 6 MB over 1G LAN, dropbear cipher on MIPS: wget of the same file took 4.7 s on sw2; x12
# drop off: the unit stays reachable through the whole flash write, until the reboot
# (docs/OPENWRT-BUILD-OPS.md sysupgrade timing); x1.25
DOWN_S = 80
# back: flash write worst 264 s (datasheet, as openwrt_install) + reboot to network ~50 s (sw2); x1.25
UP_S = 390


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, cap: float = CMD_S, data: bytes | None = None) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], input=data, capture_output=True, timeout=cap)
    if r.returncode:
        raise SystemExit(f"FAIL ssh {cmd[:60]!r}: rc {r.returncode} {r.stderr.decode(errors='replace').strip()[:300]}")
    return r.stdout.decode(errors="replace")


def ping(ip: str) -> bool:
    return subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True).returncode == 0


def wait(ip: str, up: bool, cap: float, what: str) -> float:
    t0 = time.monotonic()
    while time.monotonic() - t0 < cap:
        if ping(ip) == up:
            return time.monotonic() - t0
    raise SystemExit(f"TIMEOUT {cap:.0f} s waiting for {what} ({ip})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", required=True)
    ap.add_argument("--force", action="store_true",
                    help="sysupgrade -F: image compat change (1.0 single firmware -> 2.0 A/B, #117), config kept")
    a = ap.parse_args()
    flash_guard.check_range(*FIRMWARE, "openwrt-sysupgrade-ssh firmware")  # #81: never the stock area
    flash_guard.check_mtd("firmware", "openwrt-sysupgrade-ssh")
    raw = SRC.read_bytes()
    m = re.search(rb'\{ *"metadata_version".*\}', raw[-4096:])
    meta = json.loads(m.group(0)) if m else {}
    # a compat_version bump moves the board list to new_supported_devices (#117: 2.0 = A/B)
    if "tplink,tl-st1008f-v2" not in meta.get("new_supported_devices", meta.get("supported_devices", [])):
        raise SystemExit(f"FAIL: {SRC.name}: metadata does not name tplink,tl-st1008f-v2")
    rev = meta.get("version", {}).get("revision", "?")
    md5 = hashlib.md5(raw).hexdigest()
    log(f"{a.ip}: image {len(raw)} B, revision {rev}, md5 {md5}")

    board = ssh(a.ip, "cat /tmp/sysinfo/board_name").strip()
    if board != "tplink,tl-st1008f-v2":
        raise SystemExit(f"FAIL: board {board!r}")
    # upstream single 29 MiB `firmware`, or A/B (#117: the box writes its inactive slot)
    mtd = ssh(a.ip, "grep -E '\"firmware(_a|_b)?\"' /proc/mtd")
    if f"{FIRMWARE[1]:08x}" not in mtd and not ("firmware_a" in mtd and "firmware_b" in mtd):
        raise SystemExit(f"FAIL: firmware partitions neither upstream nor A/B: {mtd.strip()}")
    before = ssh(a.ip, ". /etc/openwrt_release; echo $DISTRIB_REVISION").strip()
    log(f"  running {before}; board {board}; {mtd.strip()}")

    BACKUP.mkdir(parents=True, exist_ok=True)
    out = BACKUP / f"{a.ip}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    ssh(a.ip, "sysupgrade -b /tmp/cfg.tar.gz")
    r = subprocess.run([*SSH, f"root@{a.ip}", "cat /tmp/cfg.tar.gz"], capture_output=True, timeout=CMD_S)
    if r.returncode or len(r.stdout) < 1024:
        raise SystemExit(f"FAIL: config backup ({len(r.stdout)} B)")
    out.write_bytes(r.stdout)
    log(f"  config backup {len(r.stdout)} B -> {out.relative_to(ROOT)}")

    ssh(a.ip, "cat > /tmp/f.bin", PUSH_S, data=raw)
    got = ssh(a.ip, "md5sum /tmp/f.bin").split()[0]
    if got != md5:
        raise SystemExit(f"FAIL: md5 on the box {got} != {md5}")
    F = "-F " if a.force else ""
    ssh(a.ip, f"sysupgrade {F}-T /tmp/f.bin")
    log("  pushed, md5 ok, sysupgrade -T ok; upgrading (config kept)")
    subprocess.run([*SSH, f"root@{a.ip}", f"sysupgrade {F}/tmp/f.bin </dev/null >/dev/null 2>&1 &"],
                   capture_output=True, timeout=CMD_S)
    t = wait(a.ip, False, DOWN_S, "the unit to drop off (upgrade started)")
    log(f"  off the network after {t:.0f} s")
    t = wait(a.ip, True, UP_S, "the unit to answer ping (flash write + boot)")
    log(f"  answers ping after {t:.0f} s")
    after = ""
    t0 = time.monotonic()
    while time.monotonic() - t0 < CMD_S:  # dropbear starts after network (S21, #114)
        try:
            after = ssh(a.ip, ". /etc/openwrt_release; echo $DISTRIB_REVISION", 10).strip()
            break
        except (SystemExit, subprocess.TimeoutExpired):
            continue
    if after != rev:
        raise SystemExit(f"FAIL: running revision {after!r}, expected {rev}")
    stp = ssh(a.ip, "cat /sys/class/net/switch/bridge/stp_state").strip()
    log(f"  running {after}, bridge STP {stp}")
    if stp != "1":
        raise SystemExit("FAIL: bridge STP off after the upgrade")
    rc = subprocess.call([sys.executable, str(ROOT / "scripts/switch_check.py"), "--ip", a.ip, "--wait", "50"])
    log(f"{'PASS' if rc == 0 else 'FAIL'}: {a.ip} {before} -> {after}, config kept, switch-check rc {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
