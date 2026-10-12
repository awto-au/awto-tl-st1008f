#!/usr/bin/env python3
"""turbo — apply a clock profile at our U-Boot prompt, any mode (#46).

- Default: power-cycle with the saved chain, ESC in our 2 s window (uboot_chain_env prompt), then
  `turbo` (stored st1008f_turbo) or `turbo <k=v ...>` (ad hoc, env untouched). `--no-cycle` = already
  at our prompt. `show` = stored profile + live clocks.
- PASS = `clocks: turbo OK`; a FAIL is reverted by U-Boot and printed with its reason.
- No flash or env writes. Log: tmp/logs/turbo.log
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402
from uboot_chain_env import OURS_PROMPT, prompt, turbo_problem  # noqa: E402

LOG = ROOT / "tmp/logs/turbo.log"
RESULT = r"clocks: turbo (OK|reverted) = [^\n]*|turbo: [^\n]*nothing changed|clocks: turbo refused[^\n]*"
# PLL + DDR change from SRAM ~ms; output <= ~60 lines incl. a revert (~0.5 s at 115200) + daemon
# send/poll ~0.1 s = 0.6 s expected; x1.25 -> 1 s (rounded up)
TURBO_S = 1


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("profile", nargs="?", help="cpu=1400,ddr=662,lx=306,sram=500 | show (default: stored profile)")
    ap.add_argument("--no-cycle", action="store_true", help="already at our st1008f-mainline prompt")
    a = ap.parse_args()
    if a.profile not in (None, "show") and (why := turbo_problem(a.profile)):
        log(f"FAIL: {a.profile}: {why}")
        return 1
    if not a.no_cycle and prompt():
        return 2
    con = Console()
    con.run("", OURS_PROMPT, 2, "our prompt")
    if a.profile == "show":
        _, out = con.run("turbo show", r"(?s)turbo: live[^\n]*" + OURS_PROMPT, 1, "turbo show")
        for ln in re.findall(r"turbo: [^\r\n]*", out):
            log(ln)
        return 0
    cmd = "turbo" + ("" if a.profile is None else " " + a.profile.replace(",", " "))
    _, out = con.run(cmd, rf"(?s)({RESULT}).*?{OURS_PROMPT}", TURBO_S, cmd)
    m = re.search(RESULT, out)
    ok = m.group(0).startswith("clocks: turbo OK")
    log(f"{'PASS' if ok else 'FAIL'} {cmd}: {m.group(0)}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
