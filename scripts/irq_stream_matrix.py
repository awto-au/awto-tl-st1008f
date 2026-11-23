#!/usr/bin/env python3
"""irq_stream_matrix — eth0 IRQ on CPU0 vs CPU1 x stack (`nat-ft`) vs zero-copy x 1 / 4 / 10 TCP streams on sw2 (#185).

- One warm-up run first (first runs after a boot read low), discarded. Then REPS rounds; the IRQ order alternates per round (0,1 then 1,0)
  so a drifting system does not favour one setting. Per cell: `nat_bench run --secs SECS -P P` forward; Mbit/s from the RESULT line.
- zc cells: zc parameters as stack_compare.zc_params(tcp=True), `zc` on for the run and off after; stack cells: zc off.
- Output: table of median [min..max] per cell -> tmp/logs/irq_stream_matrix.log. A failed cell is marked `fail` and the run goes on.
- Time: 12 cells x REPS x (SECS + ~3 s). Bounds per run: SECS x 3 + 30 s. sw2 only (nat_bench refuses others).
Usage: python3 scripts/irq_stream_matrix.py [--reps 2] [--secs 10]
"""
import argparse
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import nat_bench as nb  # noqa: E402
import zc_bench as zb  # noqa: E402

LOG = ROOT / "tmp/logs/irq_stream_matrix.log"
P = zb.P
STREAMS = (1, 4, 10)


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run_cell(streams, secs):
    try:
        r = subprocess.run([sys.executable, "scripts/nat_bench.py", "run", "--secs", str(secs), "-P", str(streams)],
                           capture_output=True, text=True, timeout=secs * 3 + 30, cwd=ROOT)
    except subprocess.TimeoutExpired:
        return None
    m = re.search(r"RESULT [^:]*: ([0-9.]+) Mbit/s", r.stdout + r.stderr)
    return float(m.group(1)) if m else None


def set_irq(mask):
    nb.sw(f"echo {mask} > /proc/irq/$(awk '/ eth0$/{{sub(\":\",\"\",$1); print $1; exit}}' /proc/interrupts)/smp_affinity")


def zc_params():
    nb.sw(f"echo {zb.NATWAN_MAC} > {P}/zc_dmac; echo 992 > {P}/zc_vid; echo 5201 > {P}/zc_dport; echo 1 > {P}/zc_ring; echo 'l3_net_route 1' > /sys/kernel/debug/rteth/rxq")
    nb.sw(f"echo 0 > {P}/zc; echo 10,99,2,1 > {P}/zc_sip; echo 1000 > {P}/zc_sport_add")
    nb.sw(f"echo 2,153,0,0,9,145 > {P}/zc_rmac; echo 991 > {P}/zc_rvid; echo 10,99,1,2 > {P}/zc_rip")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--secs", type=int, default=10)
    a = ap.parse_args()
    subprocess.run(["sudo", "-n", "pkill", "-x", "iperf3"], check=False)
    subprocess.run([sys.executable, "scripts/nat_bench.py", "teardown"], capture_output=True, cwd=ROOT, timeout=90)
    for step in (["setup"], ["mode", "nat-ft"]):
        subprocess.run([sys.executable, "scripts/nat_bench.py", *step], capture_output=True, cwd=ROOT, timeout=90)
    zc_params()
    res = {}
    try:
        set_irq(2)
        log(f"warm-up {run_cell(4, a.secs)} Mbit/s (discarded)")
        for rep in range(a.reps):
            for mask in ((1, 2) if rep % 2 == 0 else (2, 1)):
                set_irq(mask)
                for path in ("stack", "zc"):
                    nb.sw(f"echo {1 if path == 'zc' else 0} > {P}/zc")
                    for s in STREAMS:
                        v = run_cell(s, a.secs)
                        res.setdefault((path, mask, s), []).append(v)
                        log(f"rep {rep + 1} irq cpu{0 if mask == 1 else 1} {path} P{s}: {v}")
    finally:
        nb.sw(f"echo 0 > {P}/zc; echo 0 > {P}/zc_sport_add; echo 3 > /proc/irq/$(awk '/ eth0$/{{sub(\":\",\"\",$1); print $1; exit}}' /proc/interrupts)/smp_affinity", check=False)
        subprocess.run(["sudo", "-n", "pkill", "-x", "iperf3"], check=False)
        subprocess.run([sys.executable, "scripts/nat_bench.py", "teardown"], capture_output=True, cwd=ROOT, timeout=90)

    def cell(k):
        v = [x for x in res.get(k, []) if x is not None]
        return f"{statistics.median(v):.0f} [{min(v):.0f}..{max(v):.0f}]" if v else "fail"
    log(f"TABLE (Mbit/s fwd, median [min..max] of {a.reps}, {a.secs} s runs, core 608 CPU 1325)")
    log("| path | IRQ | P1 | P4 | P10 |")
    for path in ("stack", "zc"):
        for mask in (1, 2):
            log(f"| {path} | cpu{0 if mask == 1 else 1} | " + " | ".join(cell((path, mask, s)) for s in STREAMS) + " |")


if __name__ == "__main__":
    main()
