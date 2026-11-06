#!/usr/bin/env python3
"""zc_bench — stack path vs in-place forward (300-39, #148): one UDP flow natlan -> natwan through sw2.

- Needs the 7.3 image with 300-39 (RAM boot, picks clocks) and the nat-bench setup (`nat-bench setup`, `mode route`).
- Receiver truth = rx_packets of the natwan interface (iperf's loss figure is not used), per run:
  forwarded kpps, the driver's zc counters, CPU busy.
- `zc_bench.py [--secs N] [--udp MBPS] [--len B]`. Log tmp/logs/zc_bench.log
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nat_bench as nb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/zc_bench.log"
P = "/sys/module/rtl838x_eth/parameters"
NATWAN_MAC = "2,153,0,0,9,146"  # 02:99:00:00:09:92, the nat-bench natwan netns


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def rx(dev):
    r = subprocess.run(["sudo", "-n", "ip", "netns", "exec", "natwan", "cat", f"/sys/class/net/{dev}/statistics/rx_packets"],
                       capture_output=True, text=True, timeout=10)
    return int(r.stdout.strip() or 0)


def zc():
    out = nb.sw("grep -E '^zc_|^ring' /sys/kernel/debug/rteth/rxq")
    return {ln.split()[0]: int(ln.split()[1]) for ln in out.splitlines()}


def run(label, secs, udp, ln):
    dev = f"{nb.HOST_NIC}.992"
    a, za = rx(dev), zc()
    t = time.time()
    r = subprocess.run(["./dev.py", "nat-bench", "run", "--secs", str(secs), "--udp", str(udp), "--len", str(ln), "--label", label],
                       cwd=ROOT, capture_output=True, text=True, timeout=secs * 6 + 60)  # run + ramp + dumps, x6
    wall = time.time() - t
    b, zb = rx(dev), zc()
    m = re.search(r"cpu0 (\{[^}]*\}) cpu1 (\{[^}]*\})", r.stdout)
    # forwarded rate over the iperf window (secs + 2 s ramp); the dumps after it are idle
    kpps = (b - a) / (secs + 2) / 1000
    d = {k: zb[k] - za[k] for k in zb}
    log(f"{label}: natwan rx {b - a} pkts = {kpps:.1f} kpps ({kpps * 1000 * (ln + 46) * 8 / 1e6:.0f} Mbit/s on the wire) | "
        f"zc_fwd {d['zc_fwd']} miss {d['zc_miss']} busy {d['zc_busy']} ring0 {d['ring0_frames']} ring1 {d['ring1_frames']} | "
        f"cpu {m.group(1) if m else '?'} wall {wall:.0f}s")
    return kpps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=int, default=10)
    ap.add_argument("--udp", type=int, default=900)
    ap.add_argument("--len", type=int, default=1400)
    a = ap.parse_args()
    nb.sw(f"echo {NATWAN_MAC} > {P}/zc_dmac; echo 992 > {P}/zc_vid; echo 5201 > {P}/zc_dport; echo 1 > {P}/zc_ring; "
          "echo 'l3_net_route 1' > /sys/kernel/debug/rteth/rxq")
    nb.sw(f"echo 0 > {P}/zc")
    base = run("stack", a.secs, a.udp, a.len)
    nb.sw(f"echo 1 > {P}/zc")
    fast = run("zc", a.secs, a.udp, a.len)
    nb.sw(f"echo 0 > {P}/zc")
    log(f"zc / stack = {fast / base:.1f}x" if base else "no baseline")


if __name__ == "__main__":
    main()
