#!/usr/bin/env python3
"""openwrt_static_ip — give the running OpenWrt its registry address, static (no DHCP, no drift).

- awto-dan docs/network/ip-registry.toml: bench sw2 = st1008f-2-mgmt 192.168.25.56/24 (scripts/boards.py), gw + DNS .254.
- On the FLASH OpenWrt `uci commit` persists in its overlay; on a RAM boot it lasts until power-off.
- Shows `network.lan` before/after, then `/etc/init.d/network reload`. Log: tmp/logs/openwrt_static_ip.log
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import OW_PROMPT, SWITCH_IP, Console  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/openwrt_static_ip.log"
GW = "192.168.25.254"  # registry: gateway + DNS


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(con: Console, cmd: str, cap: float = 2) -> str:
    assert len(cmd) <= 60, cmd  # BusyBox echoes longer lines differently (echo check fails)
    return con.run(cmd, OW_PROMPT, cap, cmd)[1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=SWITCH_IP)
    a = ap.parse_args()
    con = Console()
    sh(con, "dmesg -n 1")
    before = sh(con, "uci show network.lan")
    log("before: " + " ".join(re.findall(r"network\.lan\.\w+=\S+", before)))
    if "network.lan=interface" not in before:
        log("FAIL: no network.lan interface section; nothing changed")
        return 1
    for k, v in (("proto", "static"), ("ipaddr", a.ip), ("netmask", "255.255.255.0"),
                 ("gateway", GW), ("dns", GW)):
        sh(con, f"uci set network.lan.{k}='{v}'")
    sh(con, "uci commit network")
    # flush the JFFS2 overlay now: a power cut 5 s after an unsynced commit lost it (2026-10-11)
    # sync = a few KiB of nodes, worst case one 64 KiB erase (W25Q256 max 2 s) x1.25 + poll
    sh(con, "sync", cap=3)
    # netifd reload re-applies interfaces; returns in ~1 s, the address appears within ~2 s
    sh(con, "/etc/init.d/network reload", cap=5)
    for _ in range(5):  # 5 x 1 s; expected within ~2 s of the reload
        out = sh(con, "ip -4 -o addr show")
        ok = f"{a.ip}/24" in out
        if ok:
            break
        time.sleep(1)
    log(f"{'PASS' if ok else 'FAIL'}: {a.ip}/24 {'present' if ok else 'missing'}; "
        + " ".join(re.findall(r"inet (\S+)", out)))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
