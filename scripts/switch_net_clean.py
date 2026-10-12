#!/usr/bin/env python3
"""switch_net_clean — reset the running OpenWrt switch's port config to plain bridge ports, over SSH.

- Deletes UCI interfaces bound to a single lanN port (LuCI "unmanaged" leftovers) and per-port
  device sections that force speed/autoneg; keeps `switch` bridge, `lan_vlan`, `lan`, `switch.1`.
- `uci commit network`, `/etc/init.d/network reload`, then prints the remaining config.
- `--dry-run` lists what would go. Log: tmp/logs/switch_net_clean.log
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/switch_net_clean.log"
SSH_S = 5  # LAN dropbear connect ~1 s; x5
# Section refs to delete: interfaces whose device is one lanN; device sections naming one lanN.
FIND = r"""
for s in $(uci -X -q show network | sed -n "s/^network\.\([^.=]*\)=interface$/\1/p"); do
  d=$(uci -q get network.$s.device); case "$d" in lan[0-9]) echo "network.$s";; esac; done
for s in $(uci -X -q show network | sed -n "s/^network\.\([^.=]*\)=device$/\1/p"); do
  n=$(uci -q get network.$s.name); case "$n" in lan[0-9]) echo "network.$s";; esac; done
"""


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, limit: int) -> str:
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes", f"root@{ip}", cmd],
                       capture_output=True, text=True, timeout=limit)
    if r.returncode:
        raise SystemExit(f"FAIL ssh: rc {r.returncode} {r.stderr.strip()}")
    return r.stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default="192.168.25.48")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    # uci show on a ~2 KB config: well under 1 s; 15 s limit = connect + margin
    refs = ssh(a.ip, FIND, 15).split()
    for r in refs:
        log(f"{'would delete' if a.dry_run else 'delete'} {r}: {ssh(a.ip, f'uci -q show {r} | tr \"\\n\" \" \"', 15)}")
    if not refs:
        log("nothing to clean")
    if refs and not a.dry_run:
        # network reload re-applies bridge + ports: ~3-5 s on this box; 30 s limit names a hang
        ssh(a.ip, "; ".join(f"uci delete {r}" for r in refs) + "; uci commit network; /etc/init.d/network reload", 30)
        log("committed + network reloaded")
    log("remaining:\n" + ssh(a.ip, "uci show network", 15))
    return 0


if __name__ == "__main__":
    sys.exit(main())
