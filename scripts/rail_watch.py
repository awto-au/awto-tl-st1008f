#!/usr/bin/env python3
"""rail_watch — board rails (1 s loop + I2C reads of every hwmon file) + temps over SSH: SFP DDM Vcc (3.3 V cage rail) per cage, SoC temp, module temps (#186).

- One ssh session runs a busybox loop on the box; the host stamps each line.
- Loss: no line for LOSS_S = unit down; logged with the last sample, then reconnects until --secs runs out.
- Log: tmp/logs/rail_watch_<ip>.log (every sample); end summary = min/max per sensor.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOSS_S = 5  # loop prints every 1 s; 5 missed ticks = unit down, not ssh jitter
REMOTE = r"""while :; do l="up=$(cut -d' ' -f1 /proc/uptime)"
for h in /sys/class/hwmon/hwmon*; do n=$(cat $h/name); v=$(cat $h/in0_input 2>/dev/null); t=$(cat $h/temp1_input 2>/dev/null)
l="$l $n:t=$t${v:+,v=$v}"; done; echo "$l"; sleep 1; done"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ip")
    ap.add_argument("--secs", type=int, default=7200)
    a = ap.parse_args()
    log_path = ROOT / "tmp" / "logs" / f"rail_watch_{a.ip}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("a")

    def out(msg: str) -> None:
        line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    lo: dict[str, int] = {}
    hi: dict[str, int] = {}
    end = time.monotonic() + a.secs
    out(f"start {a.ip} for {a.secs} s")
    while time.monotonic() < end:
        p = subprocess.Popen(["ssh", "-o", "ConnectTimeout=3", "-o", "ServerAliveInterval=2", f"root@{a.ip}", REMOTE],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        last = [time.monotonic(), ""]

        def reader() -> None:
            for line in p.stdout:
                line = line.strip()
                last[0], last[1] = time.monotonic(), line
                out(line)
                for f in line.split()[1:]:
                    name, _, kv = f.partition(":")
                    for item in kv.split(","):
                        k, _, v = item.partition("=")
                        if v.lstrip("-").isdigit():
                            key = f"{name}.{k}"
                            lo[key] = min(lo.get(key, int(v)), int(v))
                            hi[key] = max(hi.get(key, int(v)), int(v))

        th = threading.Thread(target=reader, daemon=True)
        th.start()
        while time.monotonic() < end and p.poll() is None and time.monotonic() - last[0] < LOSS_S:
            th.join(0.5)
        if time.monotonic() >= end:
            p.kill()
            break
        p.kill()
        out(f"LOSS: no sample for {time.monotonic() - last[0]:.1f} s (limit {LOSS_S} s); last: {last[1]}")
        while time.monotonic() < end and subprocess.call(["ping", "-c1", "-W1", a.ip], stdout=subprocess.DEVNULL) != 0:
            pass
        out("back on ping, reconnecting")
    for k in sorted(lo):
        out(f"summary {k} min={lo[k]} max={hi[k]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
