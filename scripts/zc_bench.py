#!/usr/bin/env python3
"""zc_bench — stack path vs in-place forward (300-39, #148): one UDP flow natlan -> natwan through sw2.

- Needs the 7.3 image with 300-39 (RAM boot, picks clocks) and the nat-bench setup (`nat-bench setup`, `mode route`).
- Receiver truth = rx_packets of the natwan interface (iperf's loss figure is not used), per run:
  forwarded kpps, the driver's zc counters, CPU busy.
- Traffic: tmp/udpblast (scripts/tools/udpblast.c, `gcc -O2 -o tmp/udpblast scripts/tools/udpblast.c`), no handshake (NAT-safe).
- `zc_bench.py [--secs N] [--flows N] [--len B] [--nat] [--perf]`. Log tmp/logs/zc_bench.log
- `--perf`: perf record on VPE1 during the fast run (needs `perf_push.py` first) -> tmp/logs/perf_<len>.txt
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


def cpu_stat():
    out = nb.sw("grep -E '^cpu[01] ' /proc/stat")
    r = {}
    for ln in out.splitlines():
        f = [int(x) for x in ln.split()[1:9]]
        r[ln.split()[0]] = (sum(f), f[3] + f[4])
    return r


def busy(c0, c1):
    return "/".join(f"{100 - 100 * (c1[k][1] - c0[k][1]) / max(1, c1[k][0] - c0[k][0]):.0f}" for k in ("cpu0", "cpu1"))


PERF = False
SSHO = ["-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]


def perf_start(secs):
    # sample all CPUs at 2 kHz (-C 1 and -D record nothing with a workload on this perf; the report filters VPE1) until stdin closes: the workload `read` returns and perf exits cleanly
    # (no --timeout in this perf; SIGINT is ignored and SIGTERM leaves an unfinished file)
    cmd = f"LD_LIBRARY_PATH=/tmp /tmp/perf record -q -a -e cpu-clock -F 2000 -o /tmp/perf.data -- sh -c 'read x'"
    return subprocess.Popen(["ssh", *SSHO, f"root@{nb.SW_IP}", cmd], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def perf_report(p, ln):
    p.communicate(timeout=60)  # closes stdin: the workload ends, perf writes the file (~10k samples, under a second)
    r = subprocess.run(["ssh", *SSHO, f"root@{nb.SW_IP}",
                        "LD_LIBRARY_PATH=/tmp /tmp/perf report -i /tmp/perf.data --stdio --no-children --cpu 1 --sort sym 2>&1 | head -45"],
                       capture_output=True, text=True, timeout=120)  # symbol resolution of a ~10k sample file
    (ROOT / f"tmp/logs/perf_{ln}.txt").write_text(r.stdout)
    log(f"perf report -> tmp/logs/perf_{ln}.txt")


def run(label, secs, flows, ln):
    dev = f"{nb.HOST_NIC}.992"
    a, za, c0 = rx(dev), zc(), cpu_stat()
    pp = perf_start(secs) if PERF and label.startswith("zc") else None
    t = time.time()
    r = subprocess.run(["sudo", "-n", "ip", "netns", "exec", "natlan", str(ROOT / "tmp/udpblast"), "10.99.1.2", "10.99.2.2",
                        "5201", str(ln), str(secs), str(flows)], capture_output=True, text=True,
                       timeout=secs * 3 + 30)  # the sender stops itself at `secs`; x3 for a slow start
    wall = time.time() - t
    if pp:
        perf_report(pp, ln)
    b, zb, c1 = rx(dev), zc(), cpu_stat()
    m = None
    sent = re.search(r"sent (\d+)", r.stdout)
    # forwarded rate over the iperf window (secs + 2 s ramp); the dumps after it are idle
    kpps = (b - a) / secs / 1000
    d = {k: zb[k] - za[k] for k in zb}
    log(f"{label}: natwan rx {b - a} pkts = {kpps:.1f} kpps ({kpps * 1000 * (ln + 46) * 8 / 1e6:.0f} Mbit/s on the wire) | "
        f"zc_fwd {d['zc_fwd']} miss {d['zc_miss']} busy {d['zc_busy']} ring0 {d['ring0_frames']} ring1 {d['ring1_frames']} | "
        f"busy VPE0/VPE1 {busy(c0, c1)}% (incl. ~2 s ramp/idle) | sent {sent.group(1) if sent else '?'} wall {wall:.0f}s")
    return kpps


def run_tcp(label, secs, reverse):
    """iperf3 TCP P4 through the switch (the bench's own run): goodput + the driver counters."""
    za = zc()
    cmd = ["./dev.py", "nat-bench", "run", "--secs", str(secs), "-P", "4", "--label", label] + (["--reverse"] if reverse else [])
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=secs * 6 + 60)  # run + ramp + dumps, x6
    zb = zc()
    m = re.search(r"RESULT \S+: ([\d.]+) Mbit/s \{[^}]*\} \| eth0 rx ([\d.]+) Mbit/s (\d+) pps", r.stdout)
    d = {k: zb[k] - za[k] for k in zb}
    log(f"{label}{' (reverse)' if reverse else ''}: iperf3 TCP P4 {m.group(1) if m else '?'} Mbit/s | eth0 stack rx {m.group(3) if m else '?'} pps | "
        f"zc_fwd {d['zc_fwd']} miss {d['zc_miss']} busy {d['zc_busy']} ring1 {d['ring1_frames']}")
    return float(m.group(1)) if m else 0.0


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
    ap.add_argument("--tcp", action="store_true", help="iperf3 TCP through both directions (needs --nat parameters; implies --nat)")
    ap.add_argument("--nat", action="store_true", help="source NAT the flow: 10.99.1.2 -> 10.99.2.1, port + 1000")
    ap.add_argument("--napi", choices=["irq", "split", "irq1"], default="irq",
                    help="irq1 = no thread, NIC IRQ + softirq poll on VPE1 (no scheduler in the path); split = threaded NAPI, ring1 (fast path) thread on VPE1, other on VPE0")
    ap.add_argument("--perf", action="store_true", help="perf record VPE1 during the fast run (perf_push.py first)")
    a = ap.parse_args()
    global PERF
    PERF = a.perf
    if a.napi == "irq1":
        nb.sw("echo 0 > /sys/class/net/eth0/threaded; echo 2 > /proc/irq/$(awk '/eth0/{print +$1}' /proc/interrupts)/smp_affinity")
        log("napi: softirq on VPE1, irq affinity " + nb.sw("cat /proc/irq/$(awk '/eth0/{print +$1}' /proc/interrupts)/smp_affinity"))
    if a.napi == "split":
        nb.sw("echo 1 > /sys/class/net/eth0/threaded; i=0; for t in $(ps | awk '/napi\\/eth0/{print $1}'); do "
              "taskset -p $((2 >> (i % 2))) $t >/dev/null; i=$((i+1)); done")
        log("napi: threaded, kthreads split over VPE0/VPE1: " + nb.sw("ps | grep 'napi/eth0'").replace("\n", " "))
    if a.tcp:
        a.nat = True
    nb.sw(f"echo {NATWAN_MAC} > {P}/zc_dmac; echo 992 > {P}/zc_vid; echo 5201 > {P}/zc_dport; echo 1 > {P}/zc_ring; "
          "echo 'l3_net_route 1' > /sys/kernel/debug/rteth/rxq")
    nb.sw(f"echo 0 > {P}/zc")
    if a.tcp:
        nb.sw(f"echo 10,99,2,1 > {P}/zc_sip; echo 1000 > {P}/zc_sport_add; echo 2,153,0,0,9,145 > {P}/zc_rmac; "
              f"echo 991 > {P}/zc_rvid; echo 10,99,1,2 > {P}/zc_rip")
        res = {}
        for rev in (False, True):
            nb.sw(f"echo 0 > {P}/zc")
            b0 = run_tcp("stack", a.secs, rev)
            nb.sw(f"echo 1 > {P}/zc")
            b1 = run_tcp("zc+nat", a.secs, rev)
            log(f"TCP {'reverse' if rev else 'forward'}: zc / stack = {b1 / b0:.1f}x" if b0 else "no baseline")
        nb.sw(f"echo 0 > {P}/zc; echo 0 > {P}/zc_sport_add")
        return
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
