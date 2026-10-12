#!/usr/bin/env python3
"""linkcheck — live links and cage loops on the bench unit, from our U-Boot (`rtk linkcheck`, #97).

- `--boot`: `ramload uboot-mainline` first (power cycle); else needs our prompt.
- Per fitted cage: DDM RX with all lasers off, soft RX_LOS, MAC link, copper PHY link -> live;
  one laser at a time -> passive cage-to-cage cables; broadcast probe per live cage -> loops.
- Exit 0 OK (<= 1 live link, no loop), 3 MULTI (> 1 live link: bridging needs STP), 4 LOOP.
- `ramload` runs it before every OpenWrt boot and refuses MULTI/LOOP. Log: tmp/logs/linkcheck.log
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/linkcheck.log"
PROMPT = r"\r?\nst1008f-mainline # "
VERDICT = r"linkcheck verdict: live (\d+), loops (\d+), probe \w+ => (OK|MULTI|LOOP)"
# `rtk network on` if not yet on (~8 s) + 8 scans of 8 cages x (A0 96 B + A2 128 B at 100 kHz,
# ~25 ms) + 7 x 125 ms settle + probes 10 ms each: ~11 s worst; x1.25
CAP_S = 14
EXIT = {"OK": 0, "MULTI": 3, "LOOP": 4}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(con: Console, probe: bool = True) -> tuple[str, int, list[str]]:
    """At our prompt: run `rtk linkcheck`, log the table; returns (verdict, live, report lines)."""
    _, out = con.run("rtk linkcheck" + ("" if probe else " noprobe"), VERDICT + r"[^\n]*" + PROMPT,
                     CAP_S, "rtk linkcheck")
    lines = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("linkcheck")]
    for ln in lines:
        log(ln)
    m = re.search(VERDICT, out)
    return m.group(3), int(m.group(1)), lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--boot", action="store_true", help="ramload uboot-mainline first")
    ap.add_argument("--noprobe", action="store_true", help="skip the frame loop probe")
    a = ap.parse_args()
    if a.boot:
        r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "uboot-mainline",
                            "--stock-clocks"], timeout=120)  # power cycle + TFTP + check ~25 s; x1.25 + relay
        if r.returncode not in (0, 1):  # 1 = boot log UNKNOWN only: the prompt is still usable
            log(f"FAIL: ramload uboot-mainline rc {r.returncode}")
            return 2
    con = Console()
    con.run("", PROMPT, 2, "our prompt")
    verdict, live, _ = run(con, not a.noprobe)
    log(f"verdict {verdict}: {live} live link(s)")
    return EXIT[verdict]


if __name__ == "__main__":
    sys.exit(main())
