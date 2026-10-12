#!/usr/bin/env python3
"""ddr_retrain — per-DQ read-tap retrain at a target DDR bin from probes, then a real set (#48 lead d).

- At our prompt (`./dev.py ramload uboot-mainline --stock-clocks` first). Reads the trained taps
  (DACDQ_IDX_RR 0xb8001510.., FR 0xb8001550.., cur_tap 12:8).
- Probe sweep: `clocks set mem <MHz> nosr probe <extra> dqshift S force` per S (change, canary, revert);
  the canary XOR gives the failing data bits. DQ d = word bits d and d + 16 (x16 die, 2 beats/word).
- Per DQ: centre of the longest S run where both its bits pass -> RR[d] and FR[d] = trained + centre.
- Real set: `clocks set mem <MHz> nosr <extra> rtaps <64 hex> force`, then 16 MiB crc32 + prompt.
- Read taps only (write taps stay at the 600 training). Log: tmp/logs/ddr_retrain.log
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/ddr_retrain.log"
PROMPT = r"\r?\nst1008f-mainline # "
CAP_PROBE = 2  # probe: 2 x ~2 ms routine + <= 5 KB output at 11.5 KB/s = 0.45 s; x1.25 + slack
CAP_SET = 3    # real set + DQ override lines (~4 KB)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def taps(con: Console) -> list[int]:
    out = []
    for base in (0xB8001510, 0xB8001550):
        _, t = con.run(f"md.l {base:x} 10", rf"{base + 0x30:08x}:[^\n]*" + PROMPT, 1, f"md {base:x}")
        words = [int(w, 16) for ln in re.findall(r"^[0-9a-f]{8}: ((?:[0-9a-f]{8} ?){1,4})", t, re.M)
                 for w in ln.split()]
        out += [(w >> 8) & 31 for w in words[:16]]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mhz", type=int, required=True)
    ap.add_argument("--extra", default="", help="options for every probe and the set, e.g. 'dll'")
    ap.add_argument("--shifts", default="-16,10", help="LO,HI dqshift range")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.shifts.split(","))
    con = Console()
    con.run("", PROMPT, 2, "our prompt")
    cur = taps(con)
    log(f"{a.mhz} MHz: trained taps RR {cur[:16]} FR {cur[16:]}")
    ok_by_shift: dict[int, int] = {}  # shift -> xor (0 = all pass)
    for sft in range(lo, hi + 1):
        _, out = con.run(f"clocks set mem {a.mhz} nosr probe {a.extra} dqshift {sft} force",
                         r"clocks: (?:probe (?:OK|FAIL)|mem set FAIL|no bin|mem option)[^\r\n]*" + PROMPT,
                         CAP_PROBE, f"probe {sft}")
        if "probe FAIL" in out or "mem set FAIL" in out or "no bin" in out or "mem option" in out:
            log(f"stop at dqshift {sft}: {re.search(r'clocks: (probe FAIL|mem set FAIL|no bin|mem option)[^\\r\\n]*', out).group(0)}")
            return 1
        m = re.search(r"canary (\d+) bad at the new clock[^,]*, xor ([0-9a-f]{8})", out)
        ok_by_shift[sft] = int(m.group(2), 16) if m and int(m.group(1)) else 0
    new = []
    for d in range(16):
        good = [s for s, x in sorted(ok_by_shift.items()) if not (x >> d) & 1 and not (x >> (d + 16)) & 1]
        runs, run = [], []
        for s in good:
            if run and s != run[-1] + 1:
                runs.append(run)
                run = []
            run.append(s)
        if run:
            runs.append(run)
        if not runs:
            log(f"DQ{d}: no passing shift in {lo}..{hi}")
            return 1
        best = max(runs, key=len)
        c = best[len(best) // 2]
        new.append(c)
        log(f"DQ{d}: pass {best[0]}..{best[-1]} -> shift {c}")
    rr = [min(31, max(0, cur[d] + new[d])) for d in range(16)]
    fr = [min(31, max(0, cur[16 + d] + new[d])) for d in range(16)]
    hx = "".join(f"{t:02x}" for t in rr + fr)
    try:
        _, out = con.run(f"clocks set mem {a.mhz} nosr {a.extra} rtaps {hx} force",
                         r"clocks: (?:mem set (?:OK|FAIL)[^\r\n]*)" + PROMPT, CAP_SET, "set with retrained taps")
        if "mem set OK" not in out:
            log(f"FAIL {a.mhz}: {re.search(r'clocks: mem set FAIL[^\\r\\n]*', out).group(0)}")
            return 1
        con.run("crc32 0x81000000 0x1000000", r"==> [0-9a-f]{8}" + PROMPT, 2, "crc32 16 MiB")
        con.run("echo ALIVE", r"\r?\nALIVE" + PROMPT, 2, "alive")
    except SystemExit as e:
        log(f"HANG {a.mhz}: {str(e)[:160]}")
        return 2
    log(f"PASS {a.mhz}: retrained read taps RR {rr} FR {fr}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
