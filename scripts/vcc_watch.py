#!/usr/bin/env python3
"""vcc_watch — 10 ms SFP Vcc (3.3 V cage rail) sampling on a switch via scripts/tools/vccsample.c (#186).

- Builds tmp/vccsample if missing (`build_fastsample.py vccsample`), copies it to /tmp on the box, runs it over ssh.
- Box prints one summary line per second (sweeps, late ticks, slowest sweep, per-cage min/max/changes) + DIP lines.
- Loss: no line for LOSS_S = unit down or ssh dropped; logged, run fails.
- Log: tmp/logs/vcc_watch_<ip>.log
"""

from __future__ import annotations

import argparse
import select
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BIN = ROOT / "tmp" / "vccsample"
LOSS_S = 3  # box prints every 1 s; 3 missed lines = down, not a slow I2C sweep (worst seen ~0.1 s)
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "ServerAliveInterval=2", "-o", "BatchMode=yes"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ip")
    ap.add_argument("--secs", type=int, default=60)
    ap.add_argument("--period-ms", type=int, default=10)
    ap.add_argument("--dip-mv", type=int, default=30, help="dip = sample this far below the previous second's mean")
    ap.add_argument("--slow", default="p1", help="cages read once per second (10G-T module: ~9 ms per read)")
    a = ap.parse_args()
    log_path = ROOT / "tmp" / "logs" / f"vcc_watch_{a.ip}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a")

    def out(msg: str) -> None:
        line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    if not BIN.exists() and subprocess.call([sys.executable, str(ROOT / "scripts" / "build_fastsample.py"), "vccsample"]):
        out("FAIL: build of tmp/vccsample")
        return 2
    if subprocess.call(["scp", "-O", "-q", str(BIN), f"root@{a.ip}:/tmp/vccsample"]):
        out("FAIL: copy to the box")
        return 2
    out(f"start {a.ip}: period {a.period_ms} ms, {a.secs} s, dip {a.dip_mv} mV, slow {a.slow}")
    p = subprocess.Popen([*SSH, f"root@{a.ip}", f"/tmp/vccsample {a.period_ms} {a.secs} {a.dip_mv} {a.slow}"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    dips = late = sweeps = 0
    while True:
        r, _, _ = select.select([p.stdout], [], [], LOSS_S)
        if not r:
            out(f"LOSS: no line for {LOSS_S} s: box down or ssh dropped")
            p.kill()
            return 2
        line = p.stdout.readline()
        if not line:
            break
        line = line.rstrip()
        out(line)
        dips += line.startswith("DIP")
        if line.startswith("S "):
            f = dict(kv.split("=", 1) for kv in line.split()[1:5])
            sweeps += int(f["n"])
            late += int(f["late"])
    rc = p.wait()
    out(f"done rc {rc}: {sweeps} sweeps, {late} late, {dips} dips")
    return 1 if dips else (2 if rc else 0)


if __name__ == "__main__":
    sys.exit(main())
