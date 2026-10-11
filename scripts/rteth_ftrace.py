#!/usr/bin/env python3
"""rteth_ftrace — function_graph timing of the CPU-port NIC path under load (#65, #67 option 2).

- Mainline 7.3 initramfs over SSH (same transport as nat_bench.py); `nat-bench setup` + `mode` first.
- Traces the graph roots (default rteth_poll_rx, rteth_start_xmit) to --depth, while
  `nat_bench.py run <load args>` forwards traffic; then aggregates per (depth, function):
  calls, total/avg µs, and µs per eth0 RX packet.
- Tracer overhead: every traced entry/exit costs time and inflates its callers. Depth 1 = root totals
  with the least overhead; deeper = relative breakdown only.
- Usage: rteth_ftrace.py [--depth 1] [--roots f,g] [--load "--secs 8 -P 4"]
- Log: tmp/logs/rteth_ftrace.log; raw trace: tmp/rteth_ftrace/<stamp>-d<depth>.txt
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/rteth_ftrace.log"
RAW = ROOT / "tmp/rteth_ftrace"
sys.path.insert(0, str(ROOT / "scripts"))
import nat_bench  # noqa: E402  (SSH transport + counters)

TR = "/sys/kernel/tracing"  # tracefs, mounted by /init
# graph line: " 0)   1.234 us    |      foo();"  or  " 0) + 12.345 us   |    } /* foo */"
LINE = re.compile(r"^\s*\d+\)\s+[+!#*@$ ]?\s*([\d.]+) us\s+\|(\s*)(?:([\w.]+)\(\);|\} /\* ([\w.]+) \*/)")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


OPEN = re.compile(r"^\s*\d+\)\s+\|(\s*)([\w.]+)\(\) \{")


def parse(text: str, roots: list[str]) -> tuple[dict, int]:
    """(depth, func) -> [calls, total_us], only inside a root's graph (other tasks leak into the
    buffer despite set_graph_function); depth from the indent (2 spaces per level)."""
    agg: dict = collections.defaultdict(lambda: [0, 0.0])
    lines, inside = 0, None
    for ln in text.splitlines():
        if (o := OPEN.match(ln)) and o.group(2) in roots and len(o.group(1)) <= 2:
            inside = o.group(2)
            continue
        m = LINE.match(ln)
        if not m:
            continue
        us, indent, leaf, closed = float(m.group(1)), m.group(2), m.group(3), m.group(4)
        depth = max(1, (len(indent) - 1) // 2 + 1)
        name = leaf or closed
        if depth == 1:
            if name not in roots:
                inside = None
                continue
            inside = None  # a root leaf (depth 1) or a root's closing line
        elif inside is None:
            continue
        e = agg[(depth, name)]
        e[0] += 1
        e[1] += us
        lines += 1
    return agg, lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--depth", type=int, default=1)
    ap.add_argument("--roots", default="rteth_poll_rx,rteth_start_xmit")
    ap.add_argument("--load", default="--secs 3 -P 4", help="nat_bench.py run arguments")
    ap.add_argument("--buf-kb", type=int, default=16384, help="per-CPU trace buffer (UP: one CPU); overrun -> partial")
    a = ap.parse_args()
    roots = a.roots.split(",")
    log(f"=== rteth_ftrace depth {a.depth} roots {roots} load '{a.load}'")
    filt = "".join(f"echo {r} >> set_graph_function && " for r in roots)  # one name per write
    nat_bench.sw(f"cd {TR} && echo 0 > tracing_on && echo nop > current_tracer && "
                 f"echo {a.buf_kb} > buffer_size_kb && echo > set_graph_function && {filt}"
                 f"echo {a.depth} > max_graph_depth && echo function_graph > current_tracer && "
                 f"echo funcgraph-tail > trace_options && echo funcgraph-irqs > trace_options && "
                 f"echo > trace && echo 1 > tracing_on")
    s0 = nat_bench.snap()
    env = dict(os.environ, NAT_BENCH_TAG=f"ftrace-d{a.depth}")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/nat_bench.py"), "run", *shlex.split(a.load)],
                       capture_output=True, text=True, env=env, timeout=120)  # load run is <= ~30 s
    nat_bench.sw(f"echo 0 > {TR}/tracing_on")
    s1 = nat_bench.snap()
    for ln in r.stdout.splitlines():
        if "RESULT" in ln:
            log(f"load: {ln.split('RESULT', 1)[1].strip()}")
    # trace text: a few MB over SSH at LAN speed, < 10 s even with a busy switch CPU
    text = nat_bench.sw(f"cat {TR}/trace", tmo=60)
    overrun = nat_bench.sw(f"grep -E 'overrun|dropped' {TR}/per_cpu/cpu0/stats; true")
    nat_bench.sw(f"cd {TR} && echo nop > current_tracer && echo > set_graph_function && echo 1408 > buffer_size_kb")
    RAW.mkdir(parents=True, exist_ok=True)
    raw = RAW / f"{time.strftime('%Y%m%d-%H%M%S')}-d{a.depth}.txt"
    raw.write_text(text)
    agg, n = parse(text, roots)
    rxp = (s1["eth0"]["rx_packets"] - s0["eth0"]["rx_packets"]) % 2**32
    txp = (s1["eth0"]["tx_packets"] - s0["eth0"]["tx_packets"]) % 2**32
    log(f"trace {raw.relative_to(ROOT)}: {n} graph lines; eth0 rx {rxp} tx {txp} pkts in the window; "
        f"{' '.join(overrun.split())}")
    log(f"{'depth':>5} {'function':40} {'calls':>9} {'total ms':>10} {'avg us':>8} {'us/rx pkt':>9}")
    for (depth, fn), (calls, tot) in sorted(agg.items(), key=lambda kv: (kv[0][0], -kv[1][1])):
        if depth > a.depth or tot < 1000 and depth > 1:  # hide < 1 ms below the roots
            continue
        log(f"{depth:>5} {fn:40} {calls:>9} {tot / 1000:>10.1f} {tot / calls:>8.2f} "
            f"{tot / rxp if rxp else 0:>9.2f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
