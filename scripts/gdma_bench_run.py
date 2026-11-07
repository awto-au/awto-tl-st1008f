#!/usr/bin/env python3
"""gdma_bench_run — push kmod/gdma_bench.ko to the plain bench kernel and run it N times (#62). Log tmp/logs/gdma_bench_run.log

- `gdma_bench_run.py [--ip A] [--runs 3] [--iters 200]`; prints one table row per length per run.
- Caps: ssh connect 5 s; one insmod = ~1 s bench + overhead, stall cap 20 s (a bad GDMA write can lock the bus: ssh goes silent).
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/gdma_bench_run.log"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--iters", type=int, default=200)
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ko = ROOT / "kmod/gdma_bench/gdma_bench.ko"
    with ko.open("rb") as f:
        subprocess.run([*SSH, f"root@{a.ip}", "cat > /tmp/gdma_bench.ko"], stdin=f, check=True, timeout=20)
    out_all = []
    for n in range(a.runs):
        r = subprocess.run([*SSH, f"root@{a.ip}", f"dmesg -c >/dev/null; insmod /tmp/gdma_bench.ko iters={a.iters} 2>&1 | tail -n 1; dmesg | grep -E 'gdma_bench|rtl9300-gdma'"],
                           capture_output=True, text=True, timeout=20)
        rows = re.findall(r"gdma_bench: len +(\d+) iters \d+: gdma (\d+) ns/xfer \((\d+) MB/s\) cpu memcpy (\d+) ns \((\d+) MB/s\) bad (\d+) fails (\d+) xfer (\d+) ns", r.stdout)
        line = f"run {n + 1}: " + " | ".join(f"{l}B {int(x) / 1000:.1f}us (loop {int(g) / 1000:.1f}) bad{b} f{f}" for l, g, _, _, _, b, f, x in rows)
        if not rows:
            line += " NO ROWS: " + (r.stdout + r.stderr).strip()[-300:]
        print(line, flush=True)
        out_all.append(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {line}\n")
    with LOG.open("a") as f:
        f.writelines(out_all)


if __name__ == "__main__":
    sys.exit(main())
