#!/usr/bin/env python3
"""switch_vlan — tagged bench VLANs on a running OpenWrt bridge `switch`, over SSH, hitless.

- `show`: uci bridge-vlan sections + `bridge vlan show`.
- `add VIDS --ports P,Q`: runtime `bridge vlan add dev P vid V` (tagged, no pvid) + one uci
  `bridge-vlan` section per VID (device switch, ports P:t Q:t), `uci commit network`. No network
  reload (a reload drops every port for seconds: sw1 2026-10-12 at uptime 438 s). Idempotent.
- `remove VIDS --ports P,Q`: the reverse.
- Mgmt ping after each step; lost -> runtime revert of this call, exit 1. VLAN 1 never touched.
- Owner approval for sw1: 991/992 on lan4 + lan5 (#96). Log: tmp/logs/switch_vlan.log
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/switch_vlan.log"
SSH_S = 5   # dropbear connect ~1 s on the LAN; x5
PING_S = 1  # LAN RTT < 1 ms; 1 s per probe names a dead host quickly


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str) -> str:
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes", f"root@{ip}", cmd],
                       capture_output=True, text=True, timeout=SSH_S * 3)  # connect + < 1 s of uci/bridge
    if r.returncode:
        raise SystemExit(f"FAIL ssh {ip}: rc {r.returncode} {r.stderr.strip()} ({cmd[:80]})")
    return r.stdout


def ping(ip: str) -> bool:
    return subprocess.run(["ping", "-c", "3", "-i", "0.2", "-W", str(PING_S), ip], capture_output=True).returncode == 0


def sections(ip: str, vid: int) -> list[str]:
    out = ssh(ip, "uci -q show network | grep '=bridge-vlan$' | cut -d= -f1 | cut -d. -f2 | "
                  "while read s; do echo \"$s $(uci -q get network.$s.device) $(uci -q get network.$s.vlan)\"; done")
    return [ln.split()[0] for ln in out.splitlines() if ln.split()[1:] == ["switch", str(vid)]]


def stats(ip: str, port: str) -> None:
    log(ssh(ip, f"ethtool -S {port} | grep -v ': 0$'").rstrip())


def show(ip: str) -> None:
    log(ssh(ip, "uci -q show network | grep bridge-vlan -A0; uci -q show network | grep -E \"\\.(vlan|ports)=\"; "
                "bridge -d vlan show; bridge link; echo fdb:; bridge fdb show br switch | grep -v permanent | "
                "grep -E 'vlan (99[12])|00:02:c9:56:ff:e2|3a:de:0a:91:10:d0'").rstrip())


def runtime(ip: str, op: str, vids: list[int], ports: list[str]) -> None:
    cmds = "; ".join(f"bridge vlan {op} dev {p} vid {v}" for v in vids for p in ports)
    ssh(ip, cmds + " 2>/dev/null; true")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("op", choices=["show", "stats", "add", "remove"])
    ap.add_argument("vids", nargs="?", default="", help="comma list, e.g. 991,992")
    ap.add_argument("--ports", default="", help="comma list, e.g. lan4,lan5")
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    if a.op == "show":
        show(a.ip)
        return 0
    if a.op == "stats":  # read-only: non-zero MIB counters of each --ports port
        for p in a.ports.split(","):
            stats(a.ip, p)
        return 0
    vids = [int(v) for v in a.vids.split(",") if v]
    ports = [p for p in a.ports.split(",") if p]
    if not vids or not ports or 1 in vids:
        log("usage: add|remove VIDS --ports P,Q (VLAN 1 is never touched)")
        return 2
    if not ping(a.ip):
        log(f"FAIL: mgmt {a.ip} not answering before the change")
        return 1
    if a.op == "add":
        runtime(a.ip, "add", vids, ports)
        if not ping(a.ip):
            runtime(a.ip, "del", vids, ports)
            log(f"FAIL: mgmt {a.ip} lost after runtime add; reverted")
            return 1
        for v in vids:
            if sections(a.ip, v):
                log(f"uci bridge-vlan {v}: present")
                continue
            plist = " ".join(f"add_list network.@bridge-vlan[-1].ports='{p}:t';" for p in ports)
            ssh(a.ip, f"uci add network bridge-vlan >/dev/null; uci set network.@bridge-vlan[-1].device='switch'; "
                      f"uci set network.@bridge-vlan[-1].vlan='{v}'; " + plist.replace("add_list", "uci add_list"))
            log(f"uci bridge-vlan {v}: added ({','.join(p + ':t' for p in ports)})")
    else:
        runtime(a.ip, "del", vids, ports)
        for v in vids:
            for s in sections(a.ip, v):
                ssh(a.ip, f"uci delete network.{s}")
                log(f"uci bridge-vlan {v}: removed ({s})")
    ssh(a.ip, "uci commit network")
    ok = ping(a.ip)
    log(("PASS" if ok else "FAIL") + f" {a.op} {vids} on {ports}; mgmt {a.ip} {'answers' if ok else 'LOST'}")
    show(a.ip)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
