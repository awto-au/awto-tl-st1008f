#!/usr/bin/env python3
"""irq_check — per-CPU IRQ routing and latency on the running mainline 7.3 kernel, over SSH (#73).

- `snap <label>`: /proc/interrupts + /proc/irq/N/{smp_affinity,effective_affinity} -> tmp/logs/irq-<label>.json.
- `diff <a> <b>`: per-IRQ per-CPU count deltas between two snaps (+ ERR/spurious).
- `pin <name> <mask>`: smp_affinity of the IRQ whose action name is <name> (e.g. eth0) = hex <mask>.
- `latency <label> [--secs S] [--load]`: timerlat (per-CPU timer IRQ + thread latency) then irqsoff
  max, S s each; --load runs one nic-bench tcp-P4 alongside. Needs `build-kernel --latency`.
- Log: tmp/logs/irq_check.log. Board: `./dev.py nic-bench boot` first (SSH at nat_bench.SW_IP).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/irq_check.log"
sys.path.insert(0, str(ROOT / "scripts"))
import nat_bench  # noqa: E402

TRACE = "/sys/kernel/tracing"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def snap(label: str) -> dict:
    # one SSH round trip: /proc reads are instant; nat_bench.sw carries the SSH timeout
    out = nat_bench.sw("cat /proc/interrupts; echo ===; for d in /proc/irq/[0-9]*; do "
                       "echo ${d##*/} $(cat $d/smp_affinity) $(cat $d/effective_affinity 2>/dev/null); done")
    tbl, aff = out.split("===")
    lines = tbl.strip().splitlines()
    ncpu = len(lines[0].split())
    irqs = {}
    for ln in lines[1:]:
        f = ln.split()
        if not f:
            continue
        key = f[0].rstrip(":")
        counts = [int(x) for x in f[1:1 + ncpu] if x.isdigit()]
        irqs[key] = {"counts": counts, "desc": " ".join(f[1 + len(counts):])}
    for ln in aff.strip().splitlines():
        f = ln.split()
        if len(f) >= 2 and f[0] in irqs:
            irqs[f[0]]["smp_affinity"] = f[1]
            irqs[f[0]]["effective_affinity"] = f[2] if len(f) > 2 else "?"
    d = {"label": label, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "ncpu": ncpu, "irqs": irqs}
    (ROOT / f"tmp/logs/irq-{label}.json").write_text(json.dumps(d, indent=1))
    log(f"snap {label}: {ncpu} CPUs")
    for k, v in irqs.items():
        log(f"  {k:>4} {str(v['counts']):>22} aff {v.get('smp_affinity', '-'):>3} "
            f"eff {v.get('effective_affinity', '-'):>3}  {v['desc']}")
    return d


def diff(a: str, b: str) -> int:
    A = json.loads((ROOT / f"tmp/logs/irq-{a}.json").read_text())["irqs"]
    B = json.loads((ROOT / f"tmp/logs/irq-{b}.json").read_text())["irqs"]
    log(f"diff {a} -> {b}")
    for k, v in B.items():
        old = A.get(k, {"counts": [0] * len(v["counts"])})["counts"]
        dl = [x - y for x, y in zip(v["counts"], old)]
        if any(dl):
            log(f"  {k:>4} {str(dl):>22}  eff {v.get('effective_affinity', '-'):>3}  {v['desc']}")
    return 0


def pin(name: str, mask: str) -> int:
    d = snap("pin-before")
    hit = [k for k, v in d["irqs"].items() if k.isdigit() and v["desc"].split()[-1] == name]
    if len(hit) != 1:
        log(f"pin: IRQ named {name!r}: {hit or 'none'}")
        return 1
    nat_bench.sw(f"echo {mask} > /proc/irq/{hit[0]}/smp_affinity")
    log(f"pin: irq {hit[0]} ({name}) smp_affinity={mask}: "
        + nat_bench.sw(f"cat /proc/irq/{hit[0]}/smp_affinity /proc/irq/{hit[0]}/effective_affinity").replace("\n", " "))
    return 0


def tracer(name: str, secs: int, load: bool) -> str:
    nat_bench.sw(f"echo 0 > {TRACE}/tracing_on; echo nop > {TRACE}/current_tracer; echo > {TRACE}/trace; "
                 f"echo 0 > {TRACE}/tracing_max_latency; echo {name} > {TRACE}/current_tracer; "
                 f"echo 1 > {TRACE}/tracing_on")
    bench = None
    if load:  # one tcp-P4 nic-bench test (10 s) as load; secs should cover it
        bench = subprocess.Popen([sys.executable, str(ROOT / "scripts/nat_bench.py"), "run", "--secs",
                                  str(secs), "-P", "4"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t_end = time.monotonic() + secs
    while time.monotonic() < t_end:
        time.sleep(1)  # sampling window only; the board-side tracer does the timing
    if bench:
        bench.wait(timeout=secs + 30)  # iperf ends at secs; +30 s names a hang in nat_bench
    nat_bench.sw(f"echo 0 > {TRACE}/tracing_on")
    return name


def latency(label: str, secs: int, load: bool) -> int:
    avail = nat_bench.sw(f"cat {TRACE}/available_tracers")
    if "timerlat" not in avail or "irqsoff" not in avail:
        log(f"latency: tracers missing ({avail.strip()}): boot `build-kernel --latency`")
        return 1
    res = {"label": label, "load": load, "secs": secs}
    tracer("timerlat", secs, load)
    # timerlat trace lines: "#<n> context irq timer_latency <ns> ns" / "thread ..."
    out = nat_bench.sw(f"cat {TRACE}/trace", tmo=30)
    for cpu_ctx in ("irq", "thread"):
        per = {}
        for m in re.finditer(r"\[(\d+)\].*context\s+" + cpu_ctx + r" timer_latency\s+(\d+) ns", out):
            per.setdefault(int(m[1]), []).append(int(m[2]))
        res[cpu_ctx] = {c: {"n": len(v), "min_us": min(v) / 1e3, "avg_us": sum(v) / len(v) / 1e3,
                            "max_us": max(v) / 1e3} for c, v in sorted(per.items())}
    tracer("irqsoff", secs, load)
    res["irqsoff_max_us"] = int(nat_bench.sw(f"cat {TRACE}/tracing_max_latency").strip())
    res["irqsoff_trace_head"] = nat_bench.sw(f"head -20 {TRACE}/trace", tmo=30)
    nat_bench.sw(f"echo nop > {TRACE}/current_tracer")
    (ROOT / f"tmp/logs/irqlat-{label}.json").write_text(json.dumps(res, indent=1))
    log(f"latency {label} (load={load}, {secs} s each):")
    for ctx in ("irq", "thread"):
        for c, s in res[ctx].items():
            log(f"  timerlat {ctx:6} cpu{c}: n {s['n']} min {s['min_us']:.1f} avg {s['avg_us']:.1f} "
                f"max {s['max_us']:.1f} us")
    log(f"  irqsoff max {res['irqsoff_max_us']} us")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snap").add_argument("label")
    d = sub.add_parser("diff")
    d.add_argument("a")
    d.add_argument("b")
    p = sub.add_parser("pin")
    p.add_argument("name")
    p.add_argument("mask")
    lt = sub.add_parser("latency")
    lt.add_argument("label")
    lt.add_argument("--secs", type=int, default=10)
    lt.add_argument("--load", action="store_true")
    a = ap.parse_args()
    if a.cmd == "snap":
        snap(a.label)
        return 0
    if a.cmd == "diff":
        return diff(a.a, a.b)
    if a.cmd == "pin":
        return pin(a.name, a.mask)
    return latency(a.label, a.secs, a.load)


if __name__ == "__main__":
    sys.exit(main())
