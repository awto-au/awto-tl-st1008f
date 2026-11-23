#!/usr/bin/env python3
"""openwrt_sysupgrade_ssh — sysupgrade a running flash OpenWrt over SSH, config kept (sw1: no console).

- Owner 2026-10-13: sw1 is reflashed only when the owner requests it.
- Image: `--image PATH` (default: the local upstream-layout sysupgrade image, as openwrt_install.py).
- Image vs box: A/B slots need compat 2.0 and size <= IMAGE_SIZE 14848k (docs/DEFAULT-BOOT.md#ab-slots).
- `--dry-run`: read-only ssh (board, mtd, revision) + all checks, prints the commands, no backup/upload.
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
SLOT_MAX = 14848 * 1024  # IMAGE_SIZE := 14848k, docs/DEFAULT-BOOT.md#ab-slots
FIRMWARE = (0x300000, 0x1D00000)  # upstream layout: 0x300000 to the end of the 32 MiB chip
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
# default-config address of a fresh slot: new host key, and the DHCP address may carry a stale known_hosts entry of another unit
SSH_FRESH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
             "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
CMD_S = 30     # one SSH command: sysupgrade -T / -b ~2-5 s on a 1 GHz MIPS; x6 for a loaded box
HTTP_PORT = 8008  # as default_boot.fetch
PUSH_S = 60    # 6 MB over 1G LAN, dropbear cipher on MIPS: wget of the same file took 4.7 s on sw2; x12
# drop off: the unit stays reachable through the whole flash write, until the reboot
# (docs/OPENWRT-BUILD-OPS.md sysupgrade timing); x1.25
DOWN_S = 105   # write of an 11.3 MB image to the drop-off measured 81 s (sw1, 2026-11-20); x1.25
BLOCK = 0x10000          # W25Q256 erase sector
SLOT_SIZE = SLOT_MAX     # 14848 KiB per A/B slot
ERASE_S_PER_BLOCK = 0.21  # tail erase via mtd write of 0xff: 59 blocks in 12.4 s on sw2 (2026-11-20)
# back: flash write worst 264 s (datasheet, as openwrt_install) + reboot to network ~50 s (sw2); x1.25
UP_S = 390


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, cap: float = CMD_S, data: bytes | None = None, fresh: bool = False) -> str:
    r = subprocess.run([*(SSH_FRESH if fresh else SSH), f"root@{ip}", cmd], input=data, capture_output=True, timeout=cap)
    if r.returncode:
        raise SystemExit(f"FAIL ssh {cmd[:60]!r}: rc {r.returncode} {r.stderr.decode(errors='replace').strip()[:300]}")
    return r.stdout.decode(errors="replace")


def ping(ip: str) -> bool:
    return subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True).returncode == 0


def neighbour_ip(mac: str, not_ip: str) -> str | None:
    """An IPv4 address (other than not_ip) the host's neighbour table holds for this MAC; read only."""
    r = subprocess.run(["ip", "-4", "neigh", "show"], capture_output=True, text=True, timeout=5)
    net = not_ip.rsplit(".", 1)[0] + "."  # same /24 only: 192.168.1.1 (U-Boot window) is a stale entry for the same MAC
    for ln in r.stdout.splitlines():
        f = ln.split()
        if "lladdr" in f and f[f.index("lladdr") + 1].lower() == mac and f[0] != not_ip and f[0].startswith(net):
            return f[0]
    return None


SNIFF_S = 4  # one ARP from a booting DHCP unit (announce/probe/flood) arrives within ~1-2 s of link-up; x2


def sniff_ip(mac: str, not_ip: str) -> str | None:
    """Source IPv4 of an ARP frame sent by this MAC, on any NIC (the host has several NICs in the unit's /24 and its
    neighbour table stays empty for a unit it never talked to: 2026-11-21 sw1 came up on DHCP .118, not found)."""
    p = subprocess.Popen(["sudo", "-n", "tcpdump", "-nn", "-e", "-p", "-l", "-i", "any", "arp"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    try:
        out, _ = p.communicate(timeout=SNIFF_S)
    except subprocess.TimeoutExpired:
        subprocess.run(["sudo", "-n", "pkill", "-TERM", "-P", str(p.pid)], check=False, timeout=5)  # sudo's child
        out = p.communicate(timeout=3)[0]
    for ln in (out or "").splitlines():
        if re.search(rf"ifindex \d+ {mac} ", ln.lower()):  # source MAC of the frame
            m = re.search(r"tell (\d+\.\d+\.\d+\.\d+)|Reply (\d+\.\d+\.\d+\.\d+) is-at", ln)
            ip = (m.group(1) or m.group(2)) if m else None
            if ip and ip != not_ip:
                return ip
    return None


def wait(ip: str, up: bool, cap: float, what: str) -> float:
    t0 = time.monotonic()
    while time.monotonic() - t0 < cap:
        if ping(ip) == up:
            return time.monotonic() - t0
    raise SystemExit(f"TIMEOUT {cap:.0f} s waiting for {what} ({ip})")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", required=True)
    ap.add_argument("--image", type=Path, default=SRC, help="sysupgrade image (default: the upstream-layout build)")
    ap.add_argument("--dry-run", action="store_true", help="read-only checks and the printed commands; no backup, no upload")
    ap.add_argument("--pull", action="store_true",
                    help="the unit fetches the image over host HTTP (:8008, this one file) instead of an SSH push: "
                         "no ssh crypto load during the transfer (sw1, 2026-11-06: two SSH pushes stalled it)")
    ap.add_argument("--force", action="store_true",
                    help="sysupgrade -F: image compat change (1.0 single firmware -> 2.0 A/B, #117), config kept")
    a = ap.parse_args()
    flash_guard.check_range(*FIRMWARE, "openwrt-sysupgrade-ssh firmware")  # #81: never the stock area
    flash_guard.check_mtd("firmware", "openwrt-sysupgrade-ssh")
    src = a.image if a.image.is_absolute() else (Path.cwd() / a.image if (Path.cwd() / a.image).exists() else ROOT / a.image)
    if not src.is_file():
        raise SystemExit(f"FAIL: image {src} not found")
    raw = src.read_bytes()
    m = re.search(rb'\{ *"metadata_version".*\}', raw[-4096:])
    meta = json.loads(m.group(0)) if m else {}
    # a compat_version bump moves the board list to new_supported_devices (#117: 2.0 = A/B)
    if "tplink,tl-st1008f-v2" not in meta.get("new_supported_devices", meta.get("supported_devices", [])):
        raise SystemExit(f"FAIL: {src.name}: metadata does not name tplink,tl-st1008f-v2")
    rev = meta.get("version", {}).get("revision", "?")
    md5 = hashlib.md5(raw).hexdigest()
    compat = str(meta.get("compat_version", "1.0"))
    log(f"{a.ip}: image {src} {len(raw)} B, revision {rev}, compat {compat}, md5 {md5}")

    board = ssh(a.ip, "cat /tmp/sysinfo/board_name").strip()
    if board != "tplink,tl-st1008f-v2":
        raise SystemExit(f"FAIL: board {board!r}")
    # upstream single 29 MiB `firmware`, or A/B (#117: the box writes its inactive slot)
    mtd = ssh(a.ip, "grep -E '\"firmware(_a|_b)?\"' /proc/mtd")
    if f"{FIRMWARE[1]:08x}" not in mtd and not ("firmware_a" in mtd and "firmware_b" in mtd):
        raise SystemExit(f"FAIL: firmware partitions neither upstream nor A/B: {mtd.strip()}")
    ab = "firmware_a" in mtd and "firmware_b" in mtd
    if ab and compat != "2.0":
        raise SystemExit(f"FAIL: box has A/B slots, image compat {compat} (needs 2.0): a 1.0 image must never be flashed")
    if ab and len(raw) > SLOT_MAX:
        raise SystemExit(f"FAIL: image {len(raw)} B > slot {SLOT_MAX} B (14.5 MiB)")
    if not ab and compat == "2.0" and not a.force:
        raise SystemExit("FAIL: single-firmware box, compat 2.0 image: needs --force (#117)")
    F = "-F " if a.force else ""
    log(f"  commands: sysupgrade {F}-T /tmp/f.bin; sysupgrade {F}/tmp/f.bin (config kept)")
    before = ssh(a.ip, ". /etc/openwrt_release; echo $DISTRIB_REVISION").strip()
    log(f"  running {before}; board {board}; {mtd.strip()}")

    if a.dry_run:
        log(f"DRY-RUN ok: {a.ip} {before} -> {rev}; nothing uploaded")
        return 0
    mac = ssh(a.ip, "cat /sys/class/net/switch/address").strip().lower()
    boot0 = ssh(a.ip, "cat /proc/sys/kernel/random/boot_id").strip()
    BACKUP.mkdir(parents=True, exist_ok=True)
    out = BACKUP / f"{a.ip}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    ssh(a.ip, "sysupgrade -b /tmp/cfg.tar.gz")
    r = subprocess.run([*SSH, f"root@{a.ip}", "cat /tmp/cfg.tar.gz"], capture_output=True, timeout=CMD_S)
    if r.returncode or len(r.stdout) < 1024:
        raise SystemExit(f"FAIL: config backup ({len(r.stdout)} B)")
    out.write_bytes(r.stdout)
    log(f"  config backup {len(r.stdout)} B -> {out.relative_to(ROOT)}")

    def pull():
        """The unit fetches the image over host HTTP (no ssh crypto load: ssh pushes to sw1 stall, 2026-11-06 and 2026-11-23)."""
        import functools
        import http.server
        import shutil
        import threading
        serve = ROOT / "tmp/sysup-serve"
        shutil.rmtree(serve, ignore_errors=True)
        serve.mkdir(parents=True)
        (serve / "f.bin").write_bytes(raw)  # a directory with only the image
        route = subprocess.run(["ip", "-o", "route", "get", a.ip], capture_output=True, text=True, timeout=5).stdout
        src = re.search(r" src (\S+)", route).group(1)  # our address on the unit's LAN
        srv = http.server.ThreadingHTTPServer((src, HTTP_PORT), functools.partial(
            http.server.SimpleHTTPRequestHandler, directory=str(serve)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            ssh(a.ip, f"wget -q -O /tmp/f.bin http://{src}:{HTTP_PORT}/f.bin", PUSH_S)
        finally:
            srv.shutdown()
            shutil.rmtree(serve, ignore_errors=True)

    if a.pull:
        pull()
    else:
        try:
            ssh(a.ip, "cat > /tmp/f.bin", PUSH_S, data=raw)
        except (SystemExit, subprocess.TimeoutExpired) as e:
            log(f"  ssh push failed ({str(e)[:80]}); falling back to the host-HTTP pull")
            pull()
    got = ssh(a.ip, "md5sum /tmp/f.bin").split()[0]
    if got != md5:
        raise SystemExit(f"FAIL: md5 on the box {got} != {md5}")
    ssh(a.ip, f"sysupgrade {F}-T /tmp/f.bin")
    if ab:
        # The idle slot's tail (past the new image) is the new overlay. JFFS2 would erase it at the first boot
        # (flash reads stall ~25 s, selftest steps time out): blank it now, while the unit is still online.
        cur = re.search(r"booted: (\w)", ssh(a.ip, "st1008f-slot")).group(1)
        idle = "b" if cur == "a" else "a"
        flash_guard.check_mtd(f"firmware_{idle}", "openwrt-sysupgrade-ssh overlay pre-erase")
        off = -(-len(raw) // BLOCK) * BLOCK
        n = (SLOT_SIZE - off) // BLOCK
        t0 = time.monotonic()
        ssh(a.ip, f"dd if=/dev/zero bs=64k count={n} 2>/dev/null | tr '\\000' '\\377' > /tmp/ff && "
                  f"mtd -f -p {off} write /tmp/ff firmware_{idle} >/dev/null 2>&1; r=$?; rm -f /tmp/ff; exit $r",
            n * ERASE_S_PER_BLOCK * 1.25 + 5)
        log(f"  slot {idle}: overlay area 0x{off:x}+{n} blocks blanked in {time.monotonic() - t0:.0f} s (unit online)")
    log("  pushed, md5 ok, sysupgrade -T ok; upgrading (config kept)")
    # Launch detached and check it ran: a plain `&` over ssh once left no sysupgrade process (2026-11-23, sw1) and the
    # script waited blind. Up to 3 tries; each checks /tmp/su.log (written by sysupgrade at once) or an unreachable unit.
    for attempt in range(1, 4):
        subprocess.run([*SSH, f"root@{a.ip}", f"rm -f /tmp/su.log; setsid sh -c 'sysupgrade {F}/tmp/f.bin >/tmp/su.log 2>&1' "
                        "</dev/null >/dev/null 2>&1 &"], capture_output=True, timeout=CMD_S)
        started = False
        for _ in range(8):  # 8 x ~1 s: sysupgrade writes its first line within 1 s of start
            time.sleep(1)
            try:
                st = ssh(a.ip, "cat /tmp/su.log 2>/dev/null; ps | grep -q '[s]ysupgrade' && echo RUNNING", 5)
            except (SystemExit, subprocess.TimeoutExpired):
                started = True  # unit already going down
                break
            if "upgrade:" in st or "RUNNING" in st:
                started = True
                break
        log(f"  sysupgrade launch try {attempt}: {'started' if started else 'NOT started'}")
        if started:
            break
    else:
        raise SystemExit(f"FAIL: sysupgrade did not start on {a.ip} in 3 tries; /tmp/su.log: {ssh(a.ip, 'cat /tmp/su.log 2>&1', 5)[:300]}")
    t = wait(a.ip, False, DOWN_S, "the unit to drop off (upgrade started)")
    log(f"  off the network after {t:.0f} s")
    t0 = time.monotonic()
    restored = False
    after = ""
    # "Back" = the unit answers ssh with a boot_id different from the one read before the upgrade: a ping seen
    # just before the unit goes down must not count (the final check once ran against the old system).
    while True:
        if time.monotonic() - t0 > UP_S:
            raise SystemExit(f"TIMEOUT {UP_S} s waiting for a new boot on {a.ip} (flash write + boot)")
        if ping(a.ip):
            try:  # dropbear starts after network (S21, #114)
                after, boot1 = ssh(a.ip, ". /etc/openwrt_release; echo $DISTRIB_REVISION; "
                                         "cat /proc/sys/kernel/random/boot_id", 10).split()
            except (SystemExit, subprocess.TimeoutExpired, ValueError):
                continue
            if boot1 != boot0:
                break
            continue
        if not restored:
            # The new A/B slot can boot with default config (DHCP address) although config is kept: find the unit
            # by MAC in the neighbour table / ARP sniff, put the backup back, wait for the real address.
            other = neighbour_ip(mac, a.ip) or sniff_ip(mac, a.ip)
            if other and ping(other):
                try:
                    ssh(other, "cat > /tmp/b.tgz; echo etc/uci-defaults/10_disable_services > /tmp/x; "
                               "tar -xzf /tmp/b.tgz -C / -X /tmp/x; (/etc/init.d/network restart >/dev/null 2>&1 &)",
                        CMD_S, data=out.read_bytes(), fresh=True)
                    log(f"  up at {other} with default config after {time.monotonic() - t0:.0f} s: backup restored, network restarted")
                    restored = True
                except (SystemExit, subprocess.TimeoutExpired) as e:
                    log(f"  restore via {other} failed: {e}")
    log(f"  new boot answers ssh after {time.monotonic() - t0:.0f} s")
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
