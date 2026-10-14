#!/usr/bin/env python3
"""boot_link_check — does every fitted cage link after a boot? N software reboots of sw2 (#116).

- Per round: `uboot_chain_env.py boot` (software reboot -> stock -> chain -> ours -> flash OpenWrt,
  STP enforced; its relay fallback stays the safety net), then over the serial console (not the
  network, so a dead uplink is still seen) read carrier of lan1-8 after the boot settles.
- Expected live after boot on sw2: lan1 (uplink to sw1 lan4); a missing one = the #116 symptom,
  dmesg for that cage logged. Loop cages (lan3/4/7/8) are left admin-down by linkcheck: not expected.
- Log: tmp/logs/boot_link_check.log
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/boot_link_check.log"
PROMPT = r"root@[^:\s]*:[^#]*# "
EXPECT = ["lan1"]
BOOT_S = 240   # backstop over uboot_chain_env boot's own caps: first-boot path (jffs2 format, #132) sums to ~190 s; x1.25
SETTLE_S = 20  # after STP on: SerDes bring-up of every cage done by ~40 s uptime (dmesg); x1.5 from STP-on


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=5)
    a = ap.parse_args()
    bad = 0
    for i in range(1, a.rounds + 1):
        r = subprocess.run([sys.executable, str(ROOT / "scripts/uboot_chain_env.py"), "boot"],
                           capture_output=True, text=True, timeout=BOOT_S)
        if r.returncode:
            log(f"round {i}: chain boot FAIL rc {r.returncode}: {(r.stderr.strip() or r.stdout.strip()).splitlines()[-1:]}")
            bad += 1
            continue
        con = Console()
        con.run("", PROMPT, 3, "shell")
        # short lines only: BusyBox wraps console input past ~60 chars and the echo check fails
        con.run(f"sleep {SETTLE_S}", PROMPT, SETTLE_S + 3, "settle")
        _, out = con.run("grep . /sys/class/net/lan?/carrier", PROMPT, 3, "carriers")
        up = {m[1] for m in re.finditer(r"/(lan\d)/carrier:1", out)}
        miss = [p for p in EXPECT if p not in up]
        log(f"round {i}: up {sorted(up)}; missing {miss or 'none'}")
        if miss:
            bad += 1
            for p in miss:
                _, d = con.run(f"dmesg | grep '{p}:' | tail -5", PROMPT, 3, f"dmesg {p}")
                log(f"  {p} dmesg: {' | '.join(ln.strip() for ln in d.splitlines()[1:6])}")
    log(f"result: {bad}/{a.rounds} boots with an expected cage down ({', '.join(EXPECT)})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
