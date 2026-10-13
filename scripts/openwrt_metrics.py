#!/usr/bin/env python3
"""openwrt_metrics — 1 s sensor gauges from a running OpenWrt switch to Netdata on TrueNAS (statsd TCP 8125).

- Installs `st1008f-metricsd` (openwrt/linkcheck/files: SoC + per-SFP DDM temp/Vcc/bias/TX/RX
  power from hwmon, load1) + its init script live over SSH, writes /etc/st1008f-metrics.conf
  (the init script starts the daemon only when that file exists), enables and starts it.
- Same files ship in every image built by build_openwrt.py; an image without the conf stays off.
- Chosen over the Lua prometheus exporter for CPU cost: docs/MONITORING.md.
- Any unit (NET_MANAGE). Log: tmp/logs/openwrt_metrics.log
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/openwrt_metrics.log"
FILES = ROOT / "openwrt/linkcheck/files"
RECEIVER, PORT = "192.168.25.64", 8125  # Netdata statsd on TrueNAS (awto-terminal scripts/netdata_deploy.py)
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
CMD_S = 20  # file copy + procd start < 2 s; x10 for a loaded box


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, data: bytes | None = None) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], input=data, capture_output=True, timeout=CMD_S)
    if r.returncode:
        raise SystemExit(f"FAIL ssh {cmd[:50]!r}: rc {r.returncode} {r.stderr.decode(errors='replace').strip()[:200]}")
    return r.stdout.decode(errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    for rel, mode in (("usr/sbin/st1008f-metricsd", "755"), ("etc/init.d/st1008f-metricsd", "755")):
        ssh(a.ip, f"cat > /{rel}.new && chmod {mode} /{rel}.new && mv /{rel}.new /{rel}", (FILES / rel).read_bytes())
    ssh(a.ip, f"printf 'HOST={RECEIVER}\\nPORT={PORT}\\nPERIOD=1\\n' > /etc/st1008f-metrics.conf; "
              "/etc/init.d/st1008f-metricsd enable; /etc/init.d/st1008f-metricsd restart")
    out = ssh(a.ip, "sleep 3; pgrep -f st1008f-metricsd >/dev/null && echo RUNNING; ls /sys/class/hwmon | wc -l")
    ok = "RUNNING" in out
    log(f"{'PASS' if ok else 'FAIL'}: {a.ip} st1008f-metricsd -> {RECEIVER}:{PORT} every 1 s "
        f"({out.split()[-1] if out.split() else '?'} hwmon)")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
