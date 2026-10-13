#!/usr/bin/env python3
"""openwrt_hostname — set a running OpenWrt's hostname to its registry box name over SSH.

- Name from `boards.HOSTNAMES` (= awto-dan ip-registry block names: st1008f-1, st1008f-2).
- `system.@system[0].hostname` + `uci commit` + `/etc/init.d/system reload` (persistent; LuCI, the
  shell prompt, LLDP and syslog `HOST` follow). Any unit (NET_MANAGE). Log: tmp/logs/openwrt_hostname.log
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP, HOSTNAMES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/openwrt_hostname.log"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
CMD_S = 20  # uci + system reload < 2 s; x10 for a loaded box


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    name = HOSTNAMES.get(a.ip)
    if not name:
        log(f"FAIL: {a.ip} not in boards.HOSTNAMES")
        return 2
    r = subprocess.run([*SSH, f"root@{a.ip}",
                        f"uci set system.@system[0].hostname='{name}'; uci commit system; "
                        "/etc/init.d/system reload; sleep 1; cat /proc/sys/kernel/hostname"],
                       capture_output=True, text=True, timeout=CMD_S)
    got = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else ""
    ok = r.returncode == 0 and got == name
    log(f"{'PASS' if ok else 'FAIL'}: {a.ip} hostname {got!r} (want {name!r}){'' if ok else ' ' + r.stderr.strip()[:200]}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
