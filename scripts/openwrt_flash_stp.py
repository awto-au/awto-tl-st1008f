#!/usr/bin/env python3
"""openwrt_flash_stp — turn bridge STP on in the FLASH OpenWrt's config, from RAM-booted OpenWrt (#43).

- Flash OpenWrt (sysupgrade 2026-10-08, default config) bridges every port, no STP: each
  unattended boot loops the house LAN. Its config lives in the JFFS2 overlay `rootfs_data`.
- Run at a RAM-booted OpenWrt shell (`./dev.py ramload openwrt`): mount rootfs_data, `uci -c
  <overlay>/upper/etc/config` set network.switch.stp=1, verify, sync, unmount.
- Refuses if the overlay has no etc/config/network (flash OpenWrt never booted to first-boot).
- Log: tmp/logs/openwrt_flash_stp.log
"""

import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import OW_PROMPT, Console  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/openwrt_flash_stp.log"
MNT = "/tmp/ov"
CFG = f"{MNT}/upper/etc/config"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(con: Console, cmd: str, want: str = "", cap: float = 2) -> str:
    """One shell command (< 60 chars: BusyBox line editing mangles the echo of longer lines)."""
    assert len(cmd) <= 60, cmd
    _, out = con.run(cmd, (want + r"[\s\S]*?" if want else "") + OW_PROMPT, cap, cmd)
    return out


def main() -> int:
    con = Console()
    sh(con, "dmesg -n 1")
    out = sh(con, "grep rootfs_data /proc/mtd", r"mtd\d+:")
    n = re.search(r"mtd(\d+):", out).group(1)
    sh(con, f"mkdir -p {MNT}")
    # JFFS2 mount may scan all of rootfs_data: ~23 MiB at ~2 MB/s SPI read = 12 s, x1.25
    sh(con, f"mount -t jffs2 /dev/mtdblock{n} {MNT} && echo MNT_OK", r"\nMNT_OK", cap=15)
    if not re.search(r"\nCFG_OK\r?\n", sh(con, f"test -f {CFG}/network && echo CFG_OK")):
        sh(con, f"umount {MNT}")
        log(f"FAIL: no {CFG}/network on rootfs_data (mtd{n}); nothing written")
        return 1
    before = sh(con, f"uci -c {CFG} show network.switch", r"network\.switch=")
    log("before: " + " ".join(re.findall(r"network\.switch[.\w]*=\S+", before)))
    sh(con, f"uci -c {CFG} set network.switch.stp=1")
    sh(con, f"uci -c {CFG} commit network")
    sh(con, f"uci -c {CFG} get network.switch.stp", r"\n1\r?\n")
    # sync: a few KiB of nodes; worst case one 64 KiB block erase (W25Q256 max 2 s) x1.25 + poll
    sh(con, f"sync; umount {MNT} && echo UMNT_OK", r"\nUMNT_OK", cap=3)
    log(f"PASS: flash OpenWrt network.switch.stp=1 (rootfs_data mtd{n}, overlay synced + unmounted)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
