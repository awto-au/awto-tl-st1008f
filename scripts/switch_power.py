#!/usr/bin/env python3
"""switch_power — power-cycle the ST1008F via its ESPHome relay.

Controls the relay at 192.168.25.49 (`switch/relay`; ON = switch powered).
IP from the house LAN IP registry (host `st1008f-1-relay`), DHCP-reserved.
Local device control on the house LAN (ESPHome REST API) — not web research,
so a direct POST is used (the playwrong rule targets external pages).

The off->on gap: the switch's power rails need to discharge for a clean reset,
and a single off+on call doesn't register the on. Default 1.0 s (user-specified;
caps discharge well under that on this board).

Relay reboots come up OFF (#84): every on/off logs the relay's ESPHome uptime before/after and
records it in tmp/relay_uptime.json; `check` flags a reboot (uptime below the recorded one plus
elapsed time) and the state; `check --fix` powers on once after a reboot that left it OFF.

Usage:
  switch_power.py cycle [--gap 1.0]   # off, wait gap, on
  switch_power.py off
  switch_power.py on
  switch_power.py check [--fix]       # exit 3 = relay rebooted since the last record
off/cycle: if sw1 answered ping before `off` and not after, relay back on, exit 4 (#91 tripwire).
Log: tmp/logs/switch_power.log
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HOST = "http://192.168.25.49"
RELAY = f"{HOST}/switch/relay"
UPTIME = f"{HOST}/sensor/uptime"
ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/switch_power.log"
STAMP = ROOT / "tmp/relay_uptime.json"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import SW1_IP  # noqa: E402
SW1_DOWN = 4  # exit: relay `off` took sw1 down (#91)


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


def uptime() -> float | None:
    try:
        with urllib.request.urlopen(UPTIME, timeout=5) as r:  # 5 s: LAN GET, ~instant
            return float(json.loads(r.read())["value"])
    except (OSError, ValueError, KeyError) as e:
        log(f"relay uptime read failed: {e}")
        return None


def sw1_up() -> bool:
    """3 pings 0.2 s apart, 0.3 s reply wait: LAN RTT <1 ms; ~0.7 s total."""
    return subprocess.call(["ping", "-q", "-c", "3", "-i", "0.2", "-W", "0.3", SW1_IP],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def record(tag: str) -> float | None:
    up = uptime()
    log(f"relay uptime {tag}: {up} s")
    if up is not None:
        STAMP.write_text(json.dumps({"wall": time.time(), "uptime": up}))
    return up


def check(fix: bool) -> int:
    up, st = uptime(), state()
    rebooted = False
    if up is not None and STAMP.exists():
        rec = json.loads(STAMP.read_text())
        # sensor updates every 60 s and lagged ~8 % of wall time (2026-10-12): 0.8 x elapsed - 60 s
        rebooted = up < rec["uptime"] + 0.8 * (time.time() - rec["wall"]) - 60
    on = '"state":"ON"' in st
    if rebooted:
        boot = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() - up))
        log(f"relay rebooted -> {'ON' if on else 'OFF'} (uptime {up:.0f} s, booted ~{boot}; #84)")
        if fix and not on:
            log(f"relay on (after reboot) -> {post('turn_on')}")
    else:
        log(f"relay check ok: uptime {up} s, {st}")
    if up is not None:
        STAMP.write_text(json.dumps({"wall": time.time(), "uptime": up}))
    return 3 if rebooted else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("op", choices=["cycle", "off", "on", "check"])
    ap.add_argument("--fix", action="store_true", help="check: power on once if a reboot left it OFF")
    ap.add_argument("--gap", type=float, default=1.0,
                    help="off->on discharge gap seconds (power-rail reset)")
    a = ap.parse_args()
    if a.op == "check":
        return check(a.fix)
    record("before")
    if a.op in ("off", "cycle"):
        sw1_before = sw1_up()
        log(f"relay off -> {post('turn_off')}")
        if sw1_before and not sw1_up():  # relay feeds sw1, not sw2: restore at once
            log(f"ERROR sw1 {SW1_IP} stopped answering after relay off: relay on -> {post('turn_on')} (#91)")
            return SW1_DOWN
        if not sw1_before:
            log(f"WARN sw1 {SW1_IP} not answering before off: relay tripwire inactive")
    if a.op == "cycle":
        time.sleep(a.gap)  # power-rail discharge; user-specified, reason above
        log(f"waited {a.gap}s (discharge)")
    if a.op in ("on", "cycle"):
        log(f"relay on -> {post('turn_on')}")
    record("after")
    log(f"state: {state()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
