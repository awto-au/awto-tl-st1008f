#!/usr/bin/env python3
"""board_guard — refuse a hardware flow unless the console/relay board is sw2 (#91).

Checks (host-only, <50 ms; no console traffic):
- args: no hardware flow may target sw1's mgmt IP.
- console log: the last boot segment (since the last stock `U-Boot 2011.12` banner) must not show
  sw1's base MAC (OpenWrt/7.3 print `Using MAC 16:b0:46:e9:0d:c0`).
- ARP cache: the bench IP must not resolve to sw1's MAC.
Relay side: `switch_power.py` powers back on and fails if sw1 stops answering ping after `off`.

Usage: board_guard.py [<dev.py command> [args ...]]   exit 0 = ok, 5 = refused
Log: tmp/logs/board_guard.log
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP, SW1_IP, SW1_MAC  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONSOLE_LOG = ROOT / "private/serial/st1008-console.log"
LOG = ROOT / "tmp/logs/board_guard.log"
TAIL = 4 << 20  # bytes of console log read; one boot is <1 MiB
MAC_RE = re.compile(re.escape(SW1_MAC).replace(":", "[:-]?"), re.I)
REFUSED = 5


def log(msg: str) -> None:
    print(f"board_guard: {msg}", file=sys.stderr)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def last_boot_text() -> str:
    if not CONSOLE_LOG.exists():
        return ""
    with CONSOLE_LOG.open("rb") as fh:
        fh.seek(max(0, CONSOLE_LOG.stat().st_size - TAIL))
        text = fh.read().decode("latin-1")
    i = text.rfind("U-Boot 2011.12")
    return text[i:] if i >= 0 else text


def bench_arp_mac() -> str:
    out = subprocess.run(["ip", "neigh", "show", BENCH_IP], capture_output=True, text=True).stdout
    return " ".join(re.findall(r"lladdr (\S+)", out)).lower()


def check(argv: list[str]) -> list[str]:
    why = []
    if any(SW1_IP in a for a in argv):
        why.append(f"args target sw1 ({SW1_IP}); hardware flows are sw2-only")
    m = MAC_RE.search(last_boot_text())
    if m:
        why.append(f"console log's last boot shows sw1's MAC {SW1_MAC}: the console is on sw1")
    if SW1_MAC in bench_arp_mac():
        why.append(f"ARP: bench IP {BENCH_IP} resolves to sw1's MAC {SW1_MAC}")
    return why


def main() -> int:
    argv = sys.argv[1:]
    why = check(argv)
    for w in why:
        log(f"REFUSED {' '.join(argv)}: {w}")
    if not why:
        log(f"ok {' '.join(argv)}")
    return REFUSED if why else 0


if __name__ == "__main__":
    raise SystemExit(main())
