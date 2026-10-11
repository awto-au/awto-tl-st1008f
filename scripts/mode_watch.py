#!/usr/bin/env python3
"""mode_watch — live M1/M2/M3 switch position from the running OpenWrt, printed on every change (#8, #64).

- One SSH session to the switch streams gpio 17/18/19 from /sys/kernel/debug/gpio every 1 s (stock rtk.ko polls at 1 s).
- Prints pins, the vendor pattern (stock rtk.ko decode, pins 17/18/19) and the position (pins 18/19).
- Ctrl-C to stop. Log: tmp/logs/mode_watch.log
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import SWITCH_IP  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/mode_watch.log"
REMOTE = ("while :; do grep -E 'gpio-(17|18|19) ' /sys/kernel/debug/gpio; echo .; "
          "sleep 1; done")  # BusyBox: whole seconds only, no usleep; = stock's 1 s poll


def vendor_pattern(p17: int, p18: int, p19: int) -> int:
    """custom_judge_pattern_mode 0x0020c240, verbatim."""
    if p17 == 1:
        if p18 == 0:
            return 2 if p19 == 1 else 3
    elif p17 == 0 and p18 == 1:
        return 1 if p19 == 1 else 3
    return 3


def position(p18: int, p19: int) -> str:
    return {(1, 1): "M1", (0, 1): "M2", (1, 0): "M3"}.get((p18, p19), "invalid")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=SWITCH_IP)
    a = ap.parse_args()
    # ConnectTimeout 3 s: LAN handshake < 0.5 s; expiry = switch not up / no OpenWrt
    cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "-o", "ServerAliveInterval=2",
           "-o", "ServerAliveCountMax=2", f"root@{a.ip}", REMOTE]
    log(f"watching mode switch on {a.ip} (slide it; Ctrl-C to stop)")
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    pins, last = {}, None
    try:
        for line in proc.stdout:
            m = re.match(r"\s*gpio-(\d+)\s.*\b(lo|hi)\b", line)
            if m:
                pins[int(m.group(1))] = 1 if m.group(2) == "hi" else 0
                continue
            if line.strip() != "." or len(pins) != 3:
                continue
            p = (pins[17], pins[18], pins[19])
            if p != last:
                log(f"switch {position(p[1], p[2])}   pins 17/18/19 = {p[0]}/{p[1]}/{p[2]}   "
                    f"vendor pattern {vendor_pattern(*p)}")
                last = p
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
    if proc.wait() not in (0, -15, 255) and last is None:
        log("FAIL: no pin data (is flash OpenWrt up at the switch IP?)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
