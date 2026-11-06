#!/usr/bin/env python3
"""zc_bench — stack path vs in-place forward (300-39, #148): one UDP flow natlan -> natwan through sw2.

- Needs the 7.3 image with 300-39 (RAM boot, picks clocks) and the nat-bench setup (`nat-bench setup`, `mode route`).
- Receiver truth = rx_packets of the natwan interface (iperf's loss figure is not used), per run:
  forwarded kpps, the driver's zc counters, CPU busy.
- Traffic: tmp/udpblast (scripts/tools/udpblast.c, `gcc -O2 -o tmp/udpblast scripts/tools/udpblast.c`), no handshake (NAT-safe).
- `zc_bench.py [--secs N] [--flows N] [--len B] [--nat]`. Log tmp/logs/zc_bench.log
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


def run(label, secs, flows, ln):
    dev = f"{nb.HOST_NIC}.992"
    a, za = rx(dev), zc()
    t = time.time()
    r = subprocess.run(["sudo", "-n", "ip", "netns", "exec", "natlan", str(ROOT / "tmp/udpblast"), "10.99.1.2", "10.99.2.2",
                        "5201", str(ln), str(secs), str(flows)], capture_output=True, text=True,
                       timeout=secs * 3 + 30)  # the sender stops itself at `secs`; x3 for a slow start
    wall = time.time() - t
    b, zb = rx(dev), zc()
    m = None
    sent = re.search(r"sent (\d+)", r.stdout)
    # forwarded rate over the iperf window (secs + 2 s ramp); the dumps after it are idle
    kpps = (b - a) / secs / 1000
    d = {k: zb[k] - za[k] for k in zb}
    log(f"{label}: natwan rx {b - a} pkts = {kpps:.1f} kpps ({kpps * 1000 * (ln + 46) * 8 / 1e6:.0f} Mbit/s on the wire) | "
        f"zc_fwd {d['zc_fwd']} miss {d['zc_miss']} busy {d['zc_busy']} ring0 {d['ring0_frames']} ring1 {d['ring1_frames']} | "
        f"sent {sent.group(1) if sent else '?'} wall {wall:.0f}s")
    return kpps


def verify_nat(dev_nic, secs=4):
    """Capture a few forwarded data frames on the host NIC and let tcpdump verify the checksums."""
    cap = subprocess.Popen(["sudo", "-n", "timeout", "12", "tcpdump", "-n", "-vv", "-i", dev_nic, "-c", "3", "-s", "1600",
                            "udp and greater 1000 and src host 10.99.2.1"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    subprocess.run(["sudo", "-n", "ip", "netns", "exec", "natlan", str(ROOT / "tmp/udpblast"), "10.99.1.2", "10.99.2.2", "5201",
                    "1400", str(secs), "1"], capture_output=True, text=True, timeout=60)  # short run: only the capture matters
    out = cap.communicate(timeout=30)[0]
    for ln in out.splitlines():
        if "UDP" in ln or "cksum" in ln:
            log("  wire: " + ln.strip()[:200])
    log("  checksums: " + ("BAD" if "bad" in out else "ok") if out.strip() else "  no NAT'd frames seen on the wire")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--secs", type=int, default=10)
    ap.add_argument("--flows", type=int, default=4)
    ap.add_argument("--len", type=int, default=1400)
    ap.add_argument("--nat", action="store_true", help="source NAT the flow: 10.99.1.2 -> 10.99.2.1, port + 1000")
    a = ap.parse_args()
    nb.sw(f"echo {NATWAN_MAC} > {P}/zc_dmac; echo 992 > {P}/zc_vid; echo 5201 > {P}/zc_dport; echo 1 > {P}/zc_ring; "
          "echo 'l3_net_route 1' > /sys/kernel/debug/rteth/rxq")
    nb.sw(f"echo 0 > {P}/zc")
    base = run("stack", a.secs, a.flows, a.len)
    if a.nat:
        nb.sw(f"echo 10,99,2,1 > {P}/zc_sip; echo 1000 > {P}/zc_sport_add")
    nb.sw(f"echo 1 > {P}/zc")
    fast = run("zc+nat" if a.nat else "zc", a.secs, a.flows, a.len)
    if a.nat:
        verify_nat(nb.HOST_NIC)
    nb.sw(f"echo 0 > {P}/zc; echo 0 > {P}/zc_sport_add")
    log(f"zc / stack = {fast / base:.1f}x" if base else "no baseline")


if __name__ == "__main__":
    main()
