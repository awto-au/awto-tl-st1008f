#!/usr/bin/env python3
"""ddr_retrain — per-DQ read-tap retrain at a target DDR bin from probes, then a real set (#48 lead d).

- At our prompt (`./dev.py ramload uboot-mainline --stock-clocks` first). Reads the trained taps
  (DACDQ_IDX_RR 0xb8001510.., FR 0xb8001550.., cur_tap 12:8).
- Probe sweep: `clocks set mem <MHz> nosr probe <extra> dqshift S force` per S (change, canary, revert);
  the canary XOR gives the failing data bits. DQ d = word bits d and d + 16 (x16 die, 2 beats/word).
- Per DQ: centre of the longest S run where both its bits pass -> RR[d] and FR[d] = trained + centre.
- Real set: `clocks set mem <MHz> nosr <extra> rtaps <64 hex> force`, then 16 MiB crc32 + prompt.
- Then write taps (`--write`): probes with the retrained read taps + `wdqshift S`; the routine's write test
  (write + read back at the new clock) XOR gives failing bits; per DQ the centre -> `wtaps <32 hex>`.
- Log: tmp/logs/ddr_retrain.log
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


def regs(con: Console) -> list[int]:
    out = []
    for base in (0xB8001510, 0xB8001550):
        _, t = con.run(f"md.l {base:x} 10", rf"{base + 0x30:08x}:[^\n]*" + PROMPT, 1, f"md {base:x}")
        out += [int(w, 16) for ln in re.findall(r"^[0-9a-f]{8}: ((?:[0-9a-f]{8} ?){1,4})", t, re.M)
                for w in ln.split()][:16]
    return out


def windows(xors: dict[int, int], name: str) -> list[int] | None:
    """Per DQ d (word bits d, d + 16): centre of the longest passing run of shifts; None = no window."""
    out = []
    for d in range(16):
        good = [s for s, x in sorted(xors.items()) if not (x >> d) & 1 and not (x >> (d + 16)) & 1]
        runs, run = [], []
        for s in good:
            if run and s != run[-1] + 1:
                runs.append(run)
                run = []
            run.append(s)
        if run:
            runs.append(run)
        if not runs:
            log(f"{name} DQ{d}: no passing shift")
            return None
        best = max(runs, key=len)
        out.append(best[len(best) // 2])
        log(f"{name} DQ{d}: pass {best[0]}..{best[-1]} -> shift {out[-1]}")
    return out


def probe(con: Console, cmd: str, what: str) -> tuple[str, int, int] | None:
    _, out = con.run(cmd, r"clocks: (?:probe (?:OK|FAIL)|mem set FAIL|no bin|mem option)[^\r\n]*" + PROMPT,
                     CAP_PROBE, what)
    if "probe FAIL" in out or "mem set FAIL" in out or "no bin" in out or "mem option" in out:
        log(f"stop at {what}: {re.search(r'clocks: (probe FAIL|mem set FAIL|no bin|mem option)[^\r\n]*', out).group(0)}")
        return None
    m = re.search(r"canary (\d+) bad at the new clock[^,]*, xor ([0-9a-f]{8})", out)
    w = re.search(r"write test (\d+) bad at the new clock, xor ([0-9a-f]{8})", out)
    return (out, int(m.group(2), 16) if m and int(m.group(1)) else 0,
            int(w.group(2), 16) if w and int(w.group(1)) else 0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mhz", type=int, required=True)
    ap.add_argument("--extra", default="", help="options for every probe and the set, e.g. 'dll'")
    ap.add_argument("--shifts", default="-16,10", help="LO,HI dqshift range")
    ap.add_argument("--write", action="store_true", help="also retrain the write taps")
    a = ap.parse_args()
    lo, hi = (int(x) for x in a.shifts.split(","))
    con = Console()
    con.run("", PROMPT, 2, "our prompt")
    live = regs(con)
    cur = [(w >> 8) & 31 for w in live]
    log(f"{a.mhz} MHz: trained read taps RR {cur[:16]} FR {cur[16:]}, write taps {[(w >> 24) & 31 for w in live[:16]]}")
    rd: dict[int, int] = {}
    for sft in range(lo, hi + 1):
        r = probe(con, f"clocks set mem {a.mhz} nosr probe {a.extra} dqshift {sft} force", f"read {sft}")
        if r is None:
            return 1
        rd[sft] = r[1]
    new = windows(rd, "read")
    if new is None:
        return 1
    rr = [min(31, max(0, cur[d] + new[d])) for d in range(16)]
    fr = [min(31, max(0, cur[16 + d] + new[d])) for d in range(16)]
    hx = "".join(f"{t:02x}" for t in rr + fr)
    wtaps = ""
    if a.write:
        wcur = [(w >> 24) & 31 for w in live[:16]]
        wr: dict[int, int] = {}
        for sft in range(-16, 17):
            r = probe(con, f"clocks set mem {a.mhz} nosr probe {a.extra} rtaps {hx} wdqshift {sft} force",
                      f"write {sft}")
            if r is None:
                return 1
            wr[sft] = r[2] | r[1]
        wnew = windows(wr, "write")
        if wnew is None:
            return 1
        wt = [min(31, max(0, wcur[d] + wnew[d])) for d in range(16)]
        wtaps = " wtaps " + "".join(f"{t:02x}" for t in wt)
        log(f"write taps {wcur} -> {wt}")
    try:
        _, out = con.run(f"clocks set mem {a.mhz} nosr {a.extra} rtaps {hx}{wtaps} force",
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
