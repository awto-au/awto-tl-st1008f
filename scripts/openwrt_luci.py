#!/usr/bin/env python3
"""openwrt_luci — install the LuCI web UI on the running OpenWrt from the internet (apk), over SSH.

- Checks default route + DNS + overlay space, `apk update`, `apk add luci`, starts uhttpd,
  then fetches http://127.0.0.1/ on the box (local check; the page itself is LAN-only).
- Persists in the JFFS2 overlay; a sysupgrade without `-n` keeps it. Log: tmp/logs/openwrt_luci.log
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/openwrt_luci.log"
SSH_S = 5        # dropbear connect on the LAN ~1 s; x5
APK_S = 300      # luci + deps ~3-6 MB over the internet + unpack on the 1 GHz MIPS: ~2-4 min; x1.25
STEPS = [
    ("route+dns", "ip route | grep -q '^default' && nslookup downloads.openwrt.org >/dev/null && echo OK", SSH_S * 3),
    ("space", "df -k /overlay | awk 'NR==2{print $4\" KiB free\"; exit ($4<8000)}'", SSH_S * 3),
    ("apk update", "apk update 2>&1 | tail -2", 120),  # index fetch ~5-20 s; x5 for a slow mirror
    ("apk add luci", "apk add luci 2>&1 | tail -4", APK_S),
    ("uhttpd", "/etc/init.d/uhttpd enable; /etc/init.d/uhttpd restart; pgrep uhttpd >/dev/null && echo running", 30),
    ("http", "wget -qO- http://127.0.0.1/ | grep -o -m1 'cgi-bin/luci' || echo NO-LUCI-LINK", 30),
]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default="192.168.25.48")
    a = ap.parse_args()
    for name, cmd, limit in STEPS:
        t0 = time.monotonic()
        try:
            r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes", f"root@{a.ip}", cmd],
                               capture_output=True, text=True, timeout=limit)
        except subprocess.TimeoutExpired:
            log(f"FAIL {name}: no result after {limit} s (limit)")
            return 1
        out = (r.stdout + r.stderr).strip().replace("\n", " | ")
        log(f"{name}: rc {r.returncode} {time.monotonic() - t0:.0f} s: {out}")
        if r.returncode or "NO-LUCI-LINK" in out:
            log(f"FAIL {name}")
            return 1
    log(f"PASS: LuCI at http://{a.ip}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
