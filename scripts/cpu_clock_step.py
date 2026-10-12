#!/usr/bin/env python3
"""cpu_clock_step — one CPU PLL experiment at the mainline U-Boot prompt (#38, docs/CLOCKS.md (a)).

- `clocks set cpu <e208> <e210> <relock> force` (SRAM routine), then `clocks`, then the timer check:
  `sleep 5` vs host clock. CP0 Count = CPU/2, so the measured rate IS the real CPU clock.
- Pass = locked, prompt back, decoded cpu MHz within 1 % of the measured rate.
- A hang means power cycle (`./dev.py ramload uboot-mainline`); nothing touches flash.
- Log: tmp/logs/cpu_clock_step.log.
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/cpu_clock_step.log"
PROMPT = r"\r?\nst1008f-mainline # "
SLEEP_S = 5


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("e210", help="0xbb00e210 value (DIVN2), e.g. 0x6b439e13 = /3")
    ap.add_argument("e208", nargs="+", help="one or more 0xbb00e208 values; ladder stops at the first fail")
    ap.add_argument("--relock", type=int, default=0, choices=(0, 1))
    a = ap.parse_args()
    con = Console()
    for e208 in a.e208:
        try:
            if not step(con, e208, a.e210, a.relock):
                return 1
        except SystemExit as e:  # hang: no prompt after the PLL write -> power cycle needed
            log(f"FAIL e208={e208} e210={a.e210}: {str(e)[:160]}")
            return 1
    return 0


def step(con: Console, e208: str, e210: str, relock: int) -> bool:
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "prompt present")
    # routine: lock poll <= 100000 iterations (~0.1 s even at a 10 MHz alternate clock) + settle
    _, out = con.run(f"clocks set cpu {e208} {e210} {relock} force",
                     r"clocks: (locked after \d+ polls[^\r\n]*|CPU PLL did not lock.*)" + PROMPT, 2, "pll set")
    log(re.search(r"clocks: (locked after \d+ polls|CPU PLL did not lock[^\r\n]*)", out).group(0))
    _, out = con.run("clocks", r"(?s)mem \d+ MHz.*" + PROMPT, 1, "clocks")
    m = re.search(r"cpu ([\d.]+) MHz.*src (\w+)", out)
    dec = float(m.group(1))
    mark = con.size()
    t0 = time.monotonic()
    con.send(f"sleep {SLEEP_S}; echo TIMER_DONE")
    # cap: a 2x rate error (wrong divider) still finishes inside 2 x SLEEP_S
    con.expect(r"\r?\nTIMER_DONE", SLEEP_S * 2 + 1, mark, f"sleep {SLEEP_S}")
    dt = time.monotonic() - t0
    real = dec * SLEEP_S / dt  # U-Boot assumes decoded/2; Count runs at real/2
    ok = abs(real / dec - 1) <= 0.01 and m.group(2) == "pll"
    log(f"{'PASS' if ok else 'FAIL'} e208={e208} e210={e210}: decoded cpu {dec} MHz ({m.group(2)}), "
        f"sleep {SLEEP_S} took {dt:.3f}s -> real cpu {real:.1f} MHz")
    return ok


if __name__ == "__main__":
    sys.exit(main())
