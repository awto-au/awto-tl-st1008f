#!/usr/bin/env python3
"""openwrt_install — sysupgrade the bench unit's flash with the local upstream-layout OpenWrt (#98, #91).

- Needs a RAM-booted OpenWrt at the console (`./dev.py ramload openwrt-ours-6.18`) with the bench
  address (`./dev.py openwrt-static-ip`): the image comes over host HTTP (default_boot.fetch, md5).
- Image: tmp/openwrt-build/bin/.../tplink_tl-st1008f-v2-squashfs-sysupgrade.bin (local OpenWrt main,
  kernel 6.18, upstream layout: `firmware` = 0x300000-end, as sw1). Refused unless its metadata names
  tplink,tl-st1008f-v2 and the running kernel shows `firmware` = 29 MiB (not the option-A split).
- `sysupgrade -T`, then `sysupgrade -n` (no config kept); console policy `pass` so stock autoboot
  (`bootcmd boota`) boots the new flash OpenWrt; then bridge STP on + forward_delay 2 (saved).
- Writes only `firmware` (flash_guard). Log: tmp/logs/openwrt_install.log
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_guard  # noqa: E402
from boards import BENCH_IP  # noqa: E402
from default_boot import fetch, mtd_index, sh  # noqa: E402
from st1008_ramload import OW_PROMPT, OW_READY, ROOT, TFTP_ROOT, Console, openwrt_stp  # noqa: E402
from uboot_chain_env import set_policy  # noqa: E402

LOG = ROOT / "tmp/logs/openwrt_install.log"
SRC = ROOT / "tmp/openwrt-build/bin/targets/realtek/rtl930x/openwrt-realtek-rtl930x-tplink_tl-st1008f-v2-squashfs-sysupgrade.bin"
NAME = "ow-su.bin"  # short: default_boot.sh caps console lines at 60 chars
FIRMWARE = (0x300000, 0x1D00000)  # upstream layout: 0x300000 to the end of the 32 MiB chip
# erase + program ~6 MB: datasheet worst 96 x 2 s + 24k pages x 3 ms = 264 s; + stock + kernel boot
# to the shell ~45 s; x1.25 (as default_boot install)
UPGRADE_CAP_S = 390


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def check_image() -> None:
    raw = SRC.read_bytes()
    m = re.search(rb'\{ *"metadata_version".*\}', raw[-4096:])
    meta = json.loads(m.group(0)) if m else {}
    if "tplink,tl-st1008f-v2" not in meta.get("supported_devices", []):
        raise SystemExit(f"FAIL: {SRC.name}: metadata does not name tplink,tl-st1008f-v2")
    if len(raw) > FIRMWARE[1]:
        raise SystemExit(f"FAIL: image {len(raw)} B > firmware {FIRMWARE[1]:#x}")
    log(f"image {SRC.name} {len(raw)} B, {meta.get('version', {})}")
    shutil.copy2(SRC, TFTP_ROOT / NAME)


def after_reboot(con) -> None:
    """New flash OpenWrt at its console: activate, first-boot sync, STP saved."""
    # first Enter only activates the console (a command sent with it is dropped, #113); prompt < 1 s
    con.run("", OW_PROMPT, 3, "OpenWrt shell")
    # first boot formats the JFFS2 overlay: a sync blocked 67 s on sw2 (2026-10-12, ~23 MiB free); x1.3
    sh(con, "sync; echo SYNC_OK", r"\nSYNC_OK", cap=90)
    openwrt_stp(con)
    # new install = new dropbear host key; ssh tools then accept the new one (accept-new)
    subprocess.run(["ssh-keygen", "-R", BENCH_IP], capture_output=True, timeout=5)  # local file edit


def main() -> int:
    if sys.argv[1:] == ["--after-reboot"]:  # resume: the upgrade + reboot already ran
        after_reboot(Console())
        log("PASS: after-reboot steps, STP on (saved)")
        return 0
    flash_guard.check_range(*FIRMWARE, "openwrt-install firmware")  # #81: never the stock area
    flash_guard.check_mtd("firmware", "openwrt-install")
    check_image()
    con = Console()
    sh(con, "dmesg -n 1")
    mtd_index(con, "firmware", FIRMWARE[1])  # running kernel: upstream layout, 29 MiB firmware
    fetch(con, NAME, "/tmp/f.bin")
    sh(con, "sysupgrade -T /tmp/f.bin && echo T_OK", r"\nT_OK", cap=10)
    set_policy("pass")  # the reboot must run stock autoboot, not stop at its prompt
    try:
        mark = con.size()
        con.send("sysupgrade -n /tmp/f.bin")
        con.expect(r"U-Boot 2011\.12", UPGRADE_CAP_S, mark, "sysupgrade -> reboot", boot_ok=True)
        con.expect(OW_READY, 90, mark, "flash OpenWrt console", boot_ok=True)  # stock boota + kernel ~45 s; x2
    finally:
        set_policy("hold")
    after_reboot(con)
    log("PASS: flash OpenWrt installed, STP on (saved)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
