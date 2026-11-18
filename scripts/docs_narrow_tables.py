#!/usr/bin/env python3
"""docs_narrow_tables — rewrite Markdown tables wider than 5 columns as per-row blocks (#89).

Owner rule: tables <= 5 short columns; the preview cuts the right column. Each row of a wide table becomes
  - **<first cell>**: <header2> <cell2>; <header3> <cell3>; ...
Empty cells and "-" cells are dropped; nothing else is lost. Escaped pipes stay.
Usage: docs_narrow_tables.py [--apply] FILE...   (default: dry run, prints a count per file)
Log: tmp/logs/docs_narrow_tables.log
"""

import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/docs_narrow_tables.log"
MAX_COLS = 5
SEP = re.compile(r"^\|[\s:|-]+\|$")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def cells(line: str) -> list[str]:
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip().strip("|"))]


def convert(lines: list[str]) -> tuple[list[str], int]:
    out, i, n = [], 0, 0
    in_fence = False
    while i < len(lines):
        ln = lines[i]
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and ln.startswith("|") and i + 1 < len(lines) and SEP.match(lines[i + 1]) and len(cells(ln)) > MAX_COLS:
            head = cells(ln)
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                j += 1
            for row in lines[i + 2:j]:
                c = cells(row)
                c += [""] * (len(head) - len(c))
                parts = [f"{head[k]} {c[k]}" for k in range(1, len(head)) if c[k] not in ("", "-", "—")]
                first = c[0][2:-2] if c[0].startswith("**") and c[0].endswith("**") and len(c[0]) > 4 else c[0]
                out.append(f"- **{first}**" + (": " + "; ".join(parts) if parts else ""))
            n += 1
            i = j
            continue
        out.append(ln)
        i += 1
    return out, n


def main() -> int:
    apply = "--apply" in sys.argv
    files = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not files:
        print(__doc__)
        return 2
    total = 0
    for f in files:
        p = Path(f)
        text = p.read_text()
        new, n = convert(text.split("\n"))
        total += n
        log(f"{f}: {n} wide table(s){' -> rewritten' if apply and n else ''}")
        if apply and n:
            p.write_text("\n".join(new))
    log(f"total {total} table(s), {'applied' if apply else 'dry run'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
