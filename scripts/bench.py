#!/usr/bin/env python3
"""bench — run the U-Boot `bench` command, store results per label, compare labels (docs/CLOCKS.md).

- `run <label>`: at the mainline prompt, record `clocks` (cpu/lx/mem/spi) + every `bench` line
  to tmp/bench/<label>.json.
- `compare [label ...]`: table of every test across labels (default: all), % vs the first.
- Log: tmp/logs/bench.log
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/bench.log"
OUT = ROOT / "tmp/bench"
PROMPT = r"\r?\nst1008f-mainline # "
# 8 tests; slowest = 4 MiB uncached flash at ~2 MB/s = 2 s; all together ~6 s at stock. x1.25 + slack
BENCH_CAP = 10


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(label: str) -> int:
    con = Console()
    _, clk = con.run("clocks", r"(?s)mem \d+ MHz.*" + PROMPT, 1, "clocks")
    rates = {k: float(v) for k, v in re.findall(r"^(cpu|lx|spi|mem) ([\d.]+) MHz", clk, re.M)}
    _, out = con.run("bench", r"bench flash_c [\d.]+ MB/s" + PROMPT, BENCH_CAP, "bench")
    res = {n: float(v) for n, v, _ in re.findall(r"^bench (\w+) ([\d.]+) (\S+)", out, re.M)}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{label}.json").write_text(json.dumps({"label": label, "clocks": rates, "bench": res,
                                                   "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")},
                                                  indent=1))
    log(f"{label}: clocks {rates} bench {res}")
    return 0


def compare(labels: list[str]) -> int:
    files = [OUT / f"{l}.json" for l in labels] if labels else sorted(OUT.glob("*.json"))
    runs = [json.loads(f.read_text()) for f in files]
    if not runs:
        log("no runs")
        return 1
    tests = list(runs[0]["bench"])
    head = f"{'test':<12}" + "".join(f"{r['label']:>16}" for r in runs)
    log(head)
    log(f"{'clocks':<12}" + "".join(f"{'%g/%g/%g' % tuple(r['clocks'].get(k, 0) for k in ('cpu', 'lx', 'mem')):>16}"
                                    for r in runs))
    for t in tests:
        base = runs[0]["bench"].get(t)
        cells = []
        for r in runs:
            v = r["bench"].get(t)
            pct = f" {v / base * 100 - 100:+.0f}%" if v and base and r is not runs[0] else ""
            cells.append(f"{v:>9.1f}{pct:>6}" if v is not None else f"{'-':>15}")
        log(f"{t:<12}" + "".join(f"{c:>16}" for c in cells))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("label")
    c = sub.add_parser("compare")
    c.add_argument("labels", nargs="*")
    a = ap.parse_args()
    return run(a.label) if a.cmd == "run" else compare(a.labels)


if __name__ == "__main__":
    sys.exit(main())
