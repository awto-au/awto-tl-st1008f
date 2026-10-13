#!/usr/bin/env python3
"""openwrt_syslog — send a running OpenWrt's log to the TrueNAS syslog receiver over SSH (#115).

- Receiver: TrueNAS custom app `syslog` (syslog-ng 4.11.0, UDP 514 + TCP 601) on 192.168.25.64,
  one file per sender IP per day under dataset p3/syslog (`<ip>/<YYYY>-<MM>-<DD>.log`; both
  switches report hostname `OpenWrt`, so the path uses the source IP; docs/SYSLOG.md).
- Sets `system.@system[0].log_ip/log_port/log_proto` (persistent, uci commit), restarts `log`,
  sends a tagged test line, then checks the receiver file grew (TrueNAS API `filesystem.stat`; the API has no file read).
- Any unit (NET_MANAGE): config only, no power/console/flash. Log: tmp/logs/openwrt_syslog.log
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/openwrt_syslog.log"
RECEIVER = "192.168.25.64"  # TrueNAS mgmt (truenas.local)
PORT, PROTO = 514, "udp"
TRUENAS = ROOT.parent / "awto-terminal"  # house infra repo: scripts/truenas.py + .venv
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
CMD_S = 20      # uci + log restart on the switch < 2 s; x10 for a loaded box
ARRIVE_S = 10   # UDP to the receiver on the same LAN + syslog-ng file write < 1 s; poll 1/s


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=CMD_S)
    if r.returncode:
        raise SystemExit(f"FAIL ssh {cmd[:50]!r}: rc {r.returncode} {r.stderr.strip()[:200]}")
    return r.stdout


def truenas(method: str, params: list) -> object:
    r = subprocess.run([str(TRUENAS / ".venv/bin/python"), "scripts/truenas.py", "call", method, json.dumps(params)],
                       cwd=TRUENAS, capture_output=True, text=True, timeout=30)
    if r.returncode:
        raise SystemExit(f"FAIL truenas {method}: {r.stderr.strip()[:200]}")
    return json.loads(r.stdout)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    host = ssh(a.ip, "uci get system.@system[0].hostname").strip()
    ssh(a.ip, f"uci set system.@system[0].log_ip='{RECEIVER}'; uci set system.@system[0].log_port='{PORT}'; "
              f"uci set system.@system[0].log_proto='{PROTO}'; uci commit system; /etc/init.d/log restart")
    path = f"/mnt/p3/syslog/{a.ip}/{time.strftime('%Y-%m-%d', time.gmtime())}.log"  # switch clock = UTC

    def size() -> int:
        try:
            return int(truenas("filesystem.stat", [path])["size"])
        except SystemExit:
            return -1  # not created yet

    before = size()
    tag = f"st1008f-syslog-test-{int(time.time())}"
    ssh(a.ip, f"sleep 1; logger -t st1008f-syslog '{tag} from {a.ip}'")  # 1 s: logd reopening its remote socket
    log(f"{a.ip} ({host}): log_ip {RECEIVER}:{PORT}/{PROTO} set, test line {tag} sent")
    t0 = time.monotonic()
    while time.monotonic() - t0 < ARRIVE_S:
        now = size()
        if now > before:
            log(f"PASS: {path} grew {max(before, 0)} -> {now} B ({time.monotonic() - t0:.1f} s)")
            return 0
        time.sleep(1)  # poll interval: the write lands < 1 s after the send
    log(f"FAIL: {path} did not grow in {ARRIVE_S} s (size {before})")
    return 1

if __name__ == "__main__":
    sys.exit(main())
