#!/usr/bin/env python3
"""switch_check — is the running OpenWrt usable as a managed switch? Network only, no serial.

- ping management IP, then SSH: release, kernel, uptime, bridge + STP state, per-port link/STP
  state, management address, LuCI / uhttpd present, sysupgrade available.
- PASS = ping + SSH + bridge with STP on + at least one port forwarding + mgmt IP present.
- `--wait S`: poll ping up to S seconds first (after a power-up). Log: tmp/logs/switch_check.log
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/switch_check.log"
PING_S = 1     # LAN RTT < 1 ms; 1 s per probe names a dead host quickly
SSH_S = 5      # dropbear handshake on the 1 GHz MIPS ~1 s measured interactively; x5 margin for first keygen
REMOTE = r"""
. /etc/openwrt_release; echo "release=$DISTRIB_DESCRIPTION"
echo "kernel=$(uname -r)"; echo "uptime=$(cut -d. -f1 /proc/uptime)s"
for b in $(ls /sys/class/net); do [ -d /sys/class/net/$b/bridge ] && echo "bridge=$b stp=$(cat /sys/class/net/$b/bridge/stp_state)"; done
bridge link | sed -n 's/^[0-9]*: \([^:@]*\).*<\([^>]*\)>.* state \([a-z]*\).*/port=\1 flags=\2 stp=\3/p'
for p in /sys/class/net/lan*; do n=$(basename $p); echo "link=$n carrier=$(cat $p/carrier 2>/dev/null) speed=$(cat $p/speed 2>/dev/null) duplex=$(cat $p/duplex 2>/dev/null)"; done
for p in /sys/class/net/lan*; do n=$(basename $p); [ "$(cat $p/carrier 2>/dev/null)" = 1 ] && ethtool $n 2>/dev/null | grep -A3 -E 'Link partner advertised link modes|^\s+Port:|Supported link modes' | tr -s ' \t' ' ' | sed "s/^/eth $n:/"; ethtool -m $n 2>/dev/null | grep -E 'Vendor PN|Transceiver type|Identifier' | tr -s ' ' | sed "s/^/mod $n:/"; done
dmesg | grep -iE 'sfp|pcs|phylink|link (is )?(up|down)' | tail -20 | sed 's/^/dmesg=/'
echo "mgmt=$(uci -q get network.lan.proto) $(uci -q get network.lan.ipaddr)"
[ -d /www/luci-static ] && echo luci=yes || echo luci=no
pgrep uhttpd >/dev/null && echo uhttpd=yes || echo uhttpd=no
command -v sysupgrade >/dev/null && echo sysupgrade=yes || echo sysupgrade=no
"""


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ping(ip: str) -> bool:
    return subprocess.run(["ping", "-c", "1", "-W", str(PING_S), ip], capture_output=True).returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default="192.168.25.48")
    ap.add_argument("--wait", type=float, default=0, help="poll ping up to S s (power-up: ~35 s to OpenWrt)")
    a = ap.parse_args()
    t0 = time.monotonic()
    while not ping(a.ip):
        if time.monotonic() - t0 >= a.wait:
            log(f"FAIL ping {a.ip}: no reply after {time.monotonic() - t0:.0f} s (limit {a.wait:.0f} s)")
            return 1
    log(f"ping {a.ip} OK after {time.monotonic() - t0:.0f} s")
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes",
                        "-o", "StrictHostKeyChecking=accept-new", f"root@{a.ip}", REMOTE],
                       capture_output=True, text=True, timeout=SSH_S * 3)  # connect + ~1 s of commands
    if r.returncode:
        log(f"FAIL ssh root@{a.ip}: rc {r.returncode} {r.stderr.strip()}")
        return 1
    out = r.stdout.strip().splitlines()
    for ln in out:
        log(ln)
    stp_on = any(ln.startswith("bridge=") and ln.endswith("stp=1") for ln in out)
    fwd = any(ln.startswith("port=") and ln.endswith("stp=forwarding") for ln in out)
    mgmt = any(ln.startswith("mgmt=") and a.ip in ln or ln.startswith("mgmt=dhcp") for ln in out)
    ok = stp_on and fwd and mgmt
    log(f"{'PASS' if ok else 'FAIL'}: bridge STP on {stp_on}, a port forwarding {fwd}, mgmt address {mgmt}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
