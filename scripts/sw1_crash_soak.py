#!/usr/bin/env python3
"""sw1_crash_soak — sustained ASIC-routed traffic through sw1 + sw2 while polling sw1's SoC temperature and uptime once a second (#186).

- Starts nat_bench setup + `offload --onlink 1` (sw2 routes VLAN 991 <-> 992 in the ASIC, ~9 Gbit/s through sw1's DAC, CPUs idle), then
  repeats `nat_bench run --secs RUN_S -P 4` up to MAX_RUNS times.
- Poll thread: every 1 s `ssh sw1 "cut -d. -f1 /proc/uptime; cat thermal_zone0/temp"`; the last good reading before sw1 stops answering is the
  temperature at the crash. Log: tmp/logs/sw1_crash_soak.log (poll line per second, run results).
- Stops at the first poll miss run (5 s without an answer = crash or hang), at MAX_RUNS, or at Ctrl-C; always sets offload back to 0 and tears the bench down.
- Limits: RUN_S 20 s per run x MAX_RUNS 15 = 5 min; crashes seen after 25 s to 28 min (#186), so 5 min of load is the cap per attempt.
Usage: python3 scripts/sw1_crash_soak.py [--runs 15] [--secs 20]
"""
import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sw1_crash_soak.log"
SW1, SW2 = "192.168.25.48", "192.168.25.56"
SSH = ["ssh", "-o", "ConnectTimeout=2", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
stop = threading.Event()
lock = threading.Lock()
last = {"t": None, "up": None, "temp": None, "dead_since": None}
prev = {}


def log(msg):
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    with lock:
        print(line, flush=True)
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(line + "\n")


REMOTE = ("cut -d. -f1 /proc/uptime; cat /sys/class/thermal/thermal_zone0/temp; "
          "cat /sys/class/net/eth0/statistics/rx_packets /sys/class/net/eth0/statistics/tx_packets "
          "/sys/class/net/eth0/statistics/rx_dropped /sys/class/net/eth0/statistics/rx_errors; "
          "awk '/ eth0$/{print $2, $3}' /proc/interrupts; awk '/NET_RX/{print $2, $3}' /proc/softirqs; "
          "cut -d' ' -f1 /proc/loadavg; grep -E '^(MemFree|Slab)' /proc/meminfo | tr -s ' ' | cut -d' ' -f2")


def poll():
    """Per second: uptime, SoC temp, eth0 rx/tx pps, rx drops/errors, eth0 IRQs/s per CPU, NET_RX softirqs/s per CPU, load, MemFree, Slab (kB)."""
    while not stop.is_set():
        t0 = time.time()
        try:
            r = subprocess.run([*SSH, f"root@{SW1}", REMOTE], capture_output=True, text=True, timeout=4)
            f = r.stdout.split()
            ok = r.returncode == 0 and len(f) >= 13
        except subprocess.TimeoutExpired:
            ok = False
        if ok:
            v = [float(x) for x in f]
            up, temp, rx, tx, rxd, rxe, i0, i1, s0, s1, load, memfree, slab = v[0], v[1] / 1000, v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12]
            last.update(t=time.time(), up=int(up), temp=temp, dead_since=None)
            if prev:
                dt = max(time.time() - prev["t"], 0.5)
                log(f"sw1 up {int(up)} {temp:.1f}C eth0 rx {(rx - prev['rx']) / dt:.0f} tx {(tx - prev['tx']) / dt:.0f} pps drop {rxd:.0f} err {rxe:.0f} | "
                    f"irq/s cpu0 {(i0 - prev['i0']) / dt:.0f} cpu1 {(i1 - prev['i1']) / dt:.0f} | netrx/s {(s0 - prev['s0']) / dt:.0f} {(s1 - prev['s1']) / dt:.0f} | "
                    f"load {load} free {memfree:.0f}k slab {slab:.0f}k")
            prev.update(t=time.time(), rx=rx, tx=tx, i0=i0, i1=i1, s0=s0, s1=s1)
        else:
            last["dead_since"] = last["dead_since"] or time.time()
            log("poll sw1 NO ANSWER")
            if time.time() - last["dead_since"] > 5:  # 5 s of silence: crash or hang (a poll answers in < 1 s normally)
                log(f"SW1 DOWN: last good reading up {last['up']} s, temp {last['temp']} C")
                stop.set()
                return
        rest = 1 - (time.time() - t0)
        if rest > 0:
            stop.wait(rest)


def sh(cmd, tmo):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=tmo, cwd=ROOT)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=15)
    ap.add_argument("--secs", type=int, default=20)
    a = ap.parse_args()
    log(f"=== soak: {a.runs} x {a.secs} s, offload on-link on sw2")
    sh([sys.executable, "scripts/nat_bench.py", "setup"], 90)
    sh([sys.executable, "scripts/nat_bench.py", "mode", "route"], 40)
    sh([sys.executable, "scripts/nat_bench.py", "offload", "--onlink", "1"], 40)
    th = threading.Thread(target=poll, daemon=True)
    th.start()
    try:
        for i in range(1, a.runs + 1):
            if stop.is_set():
                break
            try:
                r = sh([sys.executable, "scripts/nat_bench.py", "run", "--secs", str(a.secs), "-P", "4", *(["--reverse"] if i % 2 == 0 else [])],
                       a.secs * 3 + 30)
                m = [ln for ln in (r.stdout + r.stderr).splitlines() if "RESULT" in ln]
                log(f"run {i}: " + (m[0].split("RESULT ", 1)[1][:60] if m else "no result"))
            except subprocess.TimeoutExpired:
                log(f"run {i}: timeout (sw1 down?)")
                break
    finally:
        stop.set()
        th.join(5)
        subprocess.run(["sudo", "-n", "pkill", "-x", "iperf3"], check=False)  # root-owned clients in the bench namespaces block the next setup
        try:
            sh([sys.executable, "scripts/nat_bench.py", "offload", "--onlink", "0"], 30)
            sh([sys.executable, "scripts/nat_bench.py", "teardown"], 60)
        except subprocess.TimeoutExpired:
            log("cleanup timed out; bench may need nat_bench teardown after sw1 returns")
    log(f"done; last good sw1 reading up {last['up']} s temp {last['temp']} C")


if __name__ == "__main__":
    main()
