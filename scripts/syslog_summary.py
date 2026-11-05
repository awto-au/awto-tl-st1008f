#!/usr/bin/env python3
"""Per-day counts of link downs (per port), STP changes and non-info severities from tmp/syslog/<ip>/ (see syslog_fetch.py).

  python scripts/syslog_summary.py [--ip A.B.C.D]    # log: tmp/logs/syslog_summary.log
"""
import argparse
import collections
import os
import re
import subprocess
import sys
from pathlib import Path

DOWN = re.compile(r"(lan\d+|eth\d+): Link is Down")
SEV = re.compile(r"\b(kern|daemon|user|authpriv|auth|syslog)\.(warn|warning|err|crit|alert|emerg)\b")
STP = "topology change detected"
BORING = re.compile(r"aqr_gen1_read_status")


def repo_root() -> Path:
    if os.environ.get("ST1008F_REPO"):
        return Path(os.environ["ST1008F_REPO"])
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, check=True, cwd=Path(__file__).parent)
        return Path(out.stdout.strip())
    except Exception:
        return Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default="192.168.25.48")
    args = ap.parse_args()
    root = repo_root()
    lines_out = []
    sev_lines = collections.Counter()
    for f in sorted((root / "tmp" / "syslog" / args.ip).glob("*.log")):
        downs = collections.Counter()
        stp = 0
        for line in f.read_text(errors="replace").splitlines():
            m = DOWN.search(line)
            if m:
                downs[m.group(1)] += 1
            if STP in line:
                stp += 1
            if SEV.search(line):
                sev_lines[re.sub(r"\[\s*[\d.]+\]|\d+", "#", line.split(" ", 4)[-1])[:110]] += 1
        per = " ".join(f"{p}={n}" for p, n in sorted(downs.items()))
        lines_out.append(f"{f.stem}  down={sum(downs.values()):4d}  stp={stp:3d}  {per}")
    lines_out.append("--- warn+ message groups (digits folded)")
    lines_out += [f"{n:5d}  {k}" for k, n in sev_lines.most_common(25)]
    text = "\n".join(lines_out)
    print(text)
    log = root / "tmp" / "logs" / "syslog_summary.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
