#!/usr/bin/env python3
"""stack_results — tmp/controlled/rows.jsonl -> markdown tables (cell | A | B | C | note) per clock set; stdout.

- Value per cell: mean (min-max) of ok reps; Mbit/s for TCP cells, kpps for UDP cells. `n/a` = stack lacks the path, `-` = not run.
"""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROWS = ROOT / "tmp/controlled/rows.jsonl"


def fmt(rs):
    if not rs:
        return "-"
    key = "mbps" if "mbps" in rs[0] else "kpps"
    v = [r[key] for r in rs]
    s = f"{statistics.mean(v):.1f} ({min(v):.1f}-{max(v):.1f})"
    return s + (f" n={len(v)}" if len(v) != 3 else "")


def main():
    rows = [json.loads(x) for x in ROWS.read_text().splitlines()]
    for clk in ("common", "final"):
        sel = [r for r in rows if r["clk"] == clk and r["profile"] == "clean"]
        if not sel:
            continue
        cells = list(dict.fromkeys(r["cell"] for r in sel))
        print(f"\n### {clk} clocks\n\n| cell | A | B | C | note |\n|---|---|---|---|---|")
        for c in cells:
            out, notes = [], []
            for s in "ABC":
                allr = [r for r in sel if r["cell"] == c and r["stack"] == s]
                ok = [r for r in allr if r["ok"]]
                out.append(fmt(ok))
                if len(ok) < len(allr):
                    notes.append(f"{s}: {len(allr) - len(ok)} failed rep(s)")
                if any(r.get("bad_console") for r in allr):
                    notes.append(f"{s}: console fault")
            print(f"| {c} | " + " | ".join(out) + " | " + "; ".join(notes) + " |")


if __name__ == "__main__":
    sys.exit(main())
