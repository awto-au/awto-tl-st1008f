#!/usr/bin/env python3
"""stack_results — tmp/controlled/truenas-static/rows.jsonl -> markdown tables (cell | A | B | C | note) per clock set; stdout.

- Value per cell: mean (min-max) of ok reps; Mbit/s for TCP cells, kpps for UDP cells. `n/a` = stack lacks the path, `-` = not run.
"""
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROWS = ROOT / "tmp/controlled/truenas-static/rows.jsonl"


def fmt(rs):
    if not rs:
        return "-"
    key = "mbps" if "mbps" in rs[0] else "kpps"
    v = [r[key] for r in rs]
    s = f"{statistics.mean(v):.1f} ({min(v):.1f}-{max(v):.1f})"
    return s + (f" n={len(v)}" if len(v) != 3 else "")


def irq_note(clk, rows):
    stacks = sorted({r["stack"] for r in rows if r["ok"]})
    if "A" not in stacks or not ({"B", "C"} & set(stacks)):
        return ""
    values = {}
    for stack in stacks:
        path = ROWS.parent / f"snap-{clk}" / f"stack_snapshot-{stack}.json"
        if not path.exists():
            return f"**NOT EVALUATED:** IRQ snapshot missing for {stack}; see the comparison gate."
        values[stack] = json.loads(path.read_text()).get("irq_affinity")
    if not all(values.values()):
        return "**NOT EVALUATED:** IRQ affinity missing from a snapshot; see the comparison gate."
    if len(set(values.values())) > 1:
        return ("**NOT CONTROLLED:** IRQ affinity differs: " + "; ".join(f"{s} `{v}`" for s, v in values.items())
                + ". See the gate for other differences.")
    return ""


def main():
    rows = [json.loads(x) for x in ROWS.read_text().splitlines()]
    for clk in ("common", "final"):
        sel = [r for r in rows if r["clk"] == clk and r["profile"] == "clean"]
        if not sel:
            continue
        cells = list(dict.fromkeys(r["cell"] for r in sel))
        print(f"\n### {clk} clocks\n")
        if note := irq_note(clk, sel):
            print(note + "\n")
        if any(r["stack"] == "A" and r["ok"] for r in sel):
            print("A switch-side CPU percentages are not comparable (CP0 timer is uncorrected).\n")
        print("| cell | A | B | C | note |\n|---|---|---|---|---|")
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
