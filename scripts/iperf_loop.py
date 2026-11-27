#!/usr/bin/env python3
"""iperf_loop — iperf3 over a cable between two ports of the SAME switch (sw2-lan3 <-> sw2-lan6), via two netns.

- Takes both ports out of the bridge, moves each into its own netns (a, b) with 10.77.0.1/30 and .2, runs iperf3
  client (a) -> server (b): TCP forward, TCP reverse, UDP at line rate. Traffic crosses the real cable.
- Always restores: ports back into init netns, netns deleted, ports re-added to bridge `switch` (even on failure).
- Needs iperf3 on the switch (`apk add iperf3`; the diag image includes it once build_openwrt.py FEED_PKGS has it).
- Log: tmp/logs/iperf_loop.log. Caps: iperf3 -t DUR + 15 s per run (connect + teardown), ssh cap = that.

Usage: python3 scripts/iperf_loop.py [--dur 10] [--a lan3] [--b lan6] [--udp-mbit 1000] [--ip IP]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/iperf_loop.log"
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(ip: str, cmd: str, cap: float) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=cap)
    return (r.stdout + r.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dur", type=int, default=10)
    ap.add_argument("--a", default="lan3")
    ap.add_argument("--b", default="lan6")
    ap.add_argument("--udp-mbit", type=int, default=1000)
    ap.add_argument("--ip", default=BENCH_IP)
    x = ap.parse_args()
    A, B, cap = x.a, x.b, x.dur + 15
    setup = (f"brctl delif switch {A} 2>/dev/null; brctl delif switch {B} 2>/dev/null; "
             f"ip netns add a; ip netns add b; ip link set {A} netns a; ip link set {B} netns b; "
             f"ip netns exec a ip addr add 10.77.0.1/30 dev {A}; ip netns exec b ip addr add 10.77.0.2/30 dev {B}; "
             f"ip netns exec a ip link set {A} up; ip netns exec b ip link set {B} up; "
             f"i=0; while [ $i -lt 100 ]; do "
             f"[ \"$(ip netns exec a cat /sys/class/net/{A}/carrier)\" = 1 ] && [ \"$(ip netns exec b cat /sys/class/net/{B}/carrier)\" = 1 ] && break; "
             f"i=$((i+1)); read -t 0.1 z </dev/zero 2>/dev/null; done; echo carrier-wait-iters=$i")
    undo = (f"killall iperf3 2>/dev/null; ip netns exec a ip link set {A} netns 1 2>/dev/null; ip netns exec b ip link set {B} netns 1 2>/dev/null; "
            f"ip netns del a 2>/dev/null; ip netns del b 2>/dev/null; ip link set {A} up; ip link set {B} up; "
            f"brctl addif switch {A}; brctl addif switch {B}; bridge link | grep -E '{A}|{B}'")
    runs = [("TCP a->b", "-c 10.77.0.2"), ("TCP b->a", "-c 10.77.0.2 -R"),
            ("UDP a->b", f"-c 10.77.0.2 -u -b {x.udp_mbit}M")]
    try:
        log(f"setup: {sh(x.ip, setup, 30)}")
        sh(x.ip, "ip netns exec b iperf3 -s -D", 10)
        for name, args in runs:
            out = sh(x.ip, f"ip netns exec a iperf3 {args} -t {x.dur} -f m 2>&1 | grep -E 'sender|receiver|error|refused|\\[ *5\\].*sec.*%' | tail -4", cap)
            log(f"{name}: {out}")
        log(f"port counters: {sh(x.ip, f'ip netns exec a ip -s link show {A} | tail -4; ip netns exec b ip -s link show {B} | tail -4', 10)}")
    finally:
        log(f"restore: {sh(x.ip, undo, 20)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
