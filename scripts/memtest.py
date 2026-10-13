#!/usr/bin/env python3
"""memtest — U-Boot DRAM pattern test with an error map, optionally after a turbo profile (#48 #103).

- Power-cycle + `ramload uboot-mainline --stock-clocks`, `turbo PROFILE` (if given), then
  `memtest` (board/.../memtest.c): addr, walk1, walk0, check, icheck, rand; low (minus U-Boot) and
  high 256 MiB; uncached then cached; one pass each.
- Summary per unit: errors, sticky (re-read = same wrong value: stored wrong, write side) vs read errors,
  failing bits -> DQ d = word bits d, d + 16 (x16, 2 beats/word; byte lane d / 8), bank/row/col
  histograms (assumed decode in memtest.c).
- Log: tmp/logs/memtest.log; one JSON line per run: tmp/logs/memtest.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/memtest.log"
JSONL = ROOT / "tmp/logs/memtest.jsonl"
PROMPT = r"\r?\nst1008f-mainline # "
BOOT_S = 120  # power cycle + network on + TFTP ~25 s; x1.25 + relay retries (clocks_cycle.py)
TURBO_S = 3   # SRAM-routine changes ~ms + ~2 KB console output (clocks_cycle.py STEP_S)
# one unit = 1 pattern x 1 region x 1 mode, 256 MiB; slowest = uncached at stock clocks
# (docs/DRAM.md "Memtest"), x1.25; error-heavy units take longer: the timeout names the unit
UNIT_S = 14
UNITS = 24    # 6 patterns x 2 regions x 2 modes


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def dq_summary(bits: list[int]) -> str:
    """bits[b] = failing count of word bit b -> 'DQ3 (lane 0) 12+40' per DQ with any errors."""
    out = []
    for d in range(16):
        hi, lo = bits[d + 16], bits[d]
        if hi or lo:
            out.append(f"DQ{d}(L{d // 8}) {hi}+{lo}")
    return ", ".join(out) or "-"


def parse(text: str) -> list[dict]:
    units, cur = [], None
    for ln in text.splitlines():
        if m := re.search(r"memtest: S (\w+) (\w+) (\w+) (\d+) MiB (\d+) ms errs (\d+) sticky (\d+) "
                          r"xor ([0-9a-f]{8}) first ([0-9a-f]{8}) last ([0-9a-f]{8})", ln):
            cur = dict(region=m[1], mode=m[2], test=m[3], mib=int(m[4]), ms=int(m[5]), errs=int(m[6]),
                       sticky=int(m[7]), xor=m[8], first=m[9], last=m[10])
            units.append(cur)
        elif cur and (m := re.search(r"memtest: (bits31\.\.0|bank|row/2048|col/128)((?: \d+)+)", ln)):
            cur[m[1].replace("31..0", "")] = [int(x) for x in m[2].split()]
    return units


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clocks", default="", help="turbo profile, e.g. cpu=1400,ddr=662,sram=500 (default: stock)")
    ap.add_argument("--log", type=int, default=16, help="error lines printed per unit")
    ap.add_argument("--mib", type=int, default=0, help="first N MiB of each region only (quick check)")
    ap.add_argument("--no-boot", action="store_true", help="board already at our prompt")
    ap.add_argument("--args", default="", help="extra memtest args, e.g. 'low uncached'")
    ap.add_argument("--console-rate", type=int, default=921600,
                    help="console rate for the run (console_speed.py; 115200 = no switch); back to 115200 after")
    a = ap.parse_args()

    if not a.no_boot:
        r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "uboot-mainline",
                            "--stock-clocks"], capture_output=True, text=True, timeout=BOOT_S)
        if r.returncode not in (0, 1):  # 1 = boot log UNKNOWN only: prompt usable
            log(f"FAIL boot: {(r.stdout + r.stderr).strip().splitlines()[-1:]}")
            return 1
    con = Console()
    con.run("", PROMPT, 2, "our prompt")
    if a.clocks:
        _, out = con.run(f"turbo {a.clocks}", r"clocks: turbo (OK|reverted|FAIL|refused)[^\n]*" + PROMPT,
                         TURBO_S, f"turbo {a.clocks}")
        t = re.search(r"clocks: turbo [^\r\n]*", out)[0]
        log(t)
        if "turbo OK" not in t:
            return 1
    cmd = f"memtest log={a.log}" + (f" mib={a.mib}" if a.mib else "") + (f" {a.args}" if a.args else "")
    fast = a.console_rate != 115200
    if fast:
        import console_speed
        fast = console_speed.set_rate(a.console_rate)
        log(f"console at {a.console_rate}: {'yes' if fast else 'no, staying at 115200'}")
    mark = con.send_checked(cmd, chunk=4) if fast else con.size()  # 1-byte UART FIFO at fast rates
    if not fast:
        con.send(cmd)
    t0 = time.monotonic()
    seen = 0
    while True:  # one wait per unit: a hang names the unit it stopped in
        m, text = con.expect(r"memtest: (done [^\r\n]*|interrupted|high bank not mappable)" if seen >= UNITS
                             else r"(?s)(memtest: S [^\n]*\n.*?){%d}|memtest: done[^\r\n]*" % (seen + 1),
                             UNIT_S, mark, f"memtest unit {seen + 1}")
        if "memtest: done" in text or "interrupted" in text or "not mappable" in text:
            break
        seen += 1
    con.expect(PROMPT, 2, mark, "prompt")
    if fast:
        import console_speed
        console_speed.set_rate(115200)
    units = parse(text)
    for u in units:
        line = (f"{u['region']:4} {u['mode']:8} {u['test']:6} {u['ms']:6} ms  errs {u['errs']:8} "
                f"sticky {u['sticky']:8}")
        if u["errs"]:
            line += f"  xor {u['xor']}  {dq_summary(u.get('bits', [0] * 32))}  bank {u.get('bank')}"
        log(line)
    for e in re.findall(r"memtest: E [^\r\n]*", text)[:40]:
        log("  " + e[9:])
    total = sum(u["errs"] for u in units)
    log(f"RESULT clocks={a.clocks or 'stock'} errors {total} in {time.monotonic() - t0:.0f} s "
        f"({len(units)} units)")
    with JSONL.open("a") as fh:
        fh.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "clocks": a.clocks or "stock",
                             "mib": a.mib, "units": units,
                             "errors": re.findall(r"memtest: E ([^\r\n]*)", text)}) + "\n")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
