#!/usr/bin/env python3
"""switch_power — power-cycle the ST1008F via its ESPHome relay.

Controls the relay at 192.168.25.138 (`switch/relay`; ON = switch powered).
Local device control on the house LAN (ESPHome REST API) — not web research,
so a direct POST is used (the playwrong rule targets external pages).

The off->on gap: the switch's power rails need to discharge for a clean reset,
and a single off+on call doesn't register the on. Default 1.0 s (user-specified;
caps discharge well under that on this board).

Usage:
  switch_power.py cycle [--gap 1.0]   # off, wait gap, on
  switch_power.py off
  switch_power.py on
Log: tmp/logs/switch_power.log
"""

from __future__ import annotations

import argparse
import time
import urllib.request
from pathlib import Path

RELAY = "http://192.168.25.138/switch/relay"
LOG = Path(__file__).resolve().parent.parent / "tmp/logs/switch_power.log"


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def post(action: str) -> int:
    req = urllib.request.Request(f"{RELAY}/{action}", method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:  # 5 s: LAN POST, ~instant
        return r.status


def state() -> str:
    with urllib.request.urlopen(RELAY, timeout=5) as r:
        return r.read().decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("op", choices=["cycle", "off", "on"])
    ap.add_argument("--gap", type=float, default=1.0,
                    help="off->on discharge gap seconds (power-rail reset)")
    a = ap.parse_args()
    if a.op in ("off", "cycle"):
        log(f"relay off -> {post('turn_off')}")
    if a.op == "cycle":
        time.sleep(a.gap)  # power-rail discharge; user-specified, reason above
        log(f"waited {a.gap}s (discharge)")
    if a.op in ("on", "cycle"):
        log(f"relay on -> {post('turn_on')}")
    log(f"state: {state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
