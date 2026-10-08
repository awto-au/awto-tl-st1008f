#!/usr/bin/env python3
"""catch_uboot — watch the console log for the autoboot prompt and fire ESC.

The RTL9300 U-Boot prints "Hit Esc key to stop autoboot:" with bootdelay=1, so
the interrupt window is ~1 second — too tight for human timing. This watches
the daemon's log (tail), and the instant the prompt appears sends ESC through
the daemon, then a CR, and confirms the RTL9300# prompt. Arm it, THEN power-
cycle the switch.

Bounded by --wait seconds (default 180): that is how long to wait for YOU to
power-cycle, not a hardware timeout. On catching the prompt it exits 0 with the
prompt confirmed, or 3 if ESC was sent but no RTL9300# followed, or 2 on wait
timeout (you did not power-cycle in time).

    scripts/catch_uboot.py --wait 180

Superseded by the daemon's built-in auto-catch (`--policy hold`); kept for a
daemon started with a policy that boots. Log: tmp/logs/catch_uboot.log
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
import time
from pathlib import Path

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()))
SOCK = RUNTIME / "tio-st1008.daemon.sock"
ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "private/serial/st1008-console.log"  # written by switch_console_daemon.py
RUN_LOG = ROOT / "tmp/logs/catch_uboot.log"
PROMPT_MARK = b"Hit Esc key to stop autoboot"
UBOOT = b"RTL9300#"
ESC = b"\x1b"


def _send(raw: bytes, secs: float = 1.5) -> bytes:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(secs + 10)
    s.connect(str(SOCK))
    s.sendall((json.dumps({"op": "send",
                           "data": base64.b64encode(raw).decode(),
                           "secs": secs}) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        c = s.recv(65536)
        if not c:
            break
        buf += c
    s.close()
    r = json.loads(buf.decode())
    return base64.b64decode(r.get("captured", "")) if r.get("ok") else b""


class _Tee:
    """Mirror text writes to the run log (stdout+stderr)."""

    def __init__(self, stream, fh):
        self.stream, self.fh = stream, fh

    def write(self, s):
        self.fh.write(s)
        self.fh.flush()
        return self.stream.write(s)

    def flush(self):
        self.stream.flush()

    def __getattr__(self, name):
        return getattr(self.stream, name)


def _tee_output(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = path.open("a")
    fh.write(f"\n# {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {' '.join(sys.argv)}\n")
    sys.stdout, sys.stderr = _Tee(sys.stdout, fh), _Tee(sys.stderr, fh)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wait", type=float, default=180.0,
                    help="seconds to wait for you to power-cycle")
    args = ap.parse_args()
    _tee_output(RUN_LOG)

    if not SOCK.exists():
        print("daemon not running; start switch_console_daemon.py first", file=sys.stderr)
        return 2
    if not LOG.exists():
        print("no log yet", file=sys.stderr)
        return 2

    start = LOG.stat().st_size  # only watch for NEW prompt output
    print(f"armed: watching for autoboot prompt. POWER-CYCLE THE SWITCH NOW "
          f"(waiting up to {args.wait:.0f}s)...", flush=True)
    end = time.monotonic() + args.wait
    fh = LOG.open("rb")
    fh.seek(start)
    pending = b""
    while time.monotonic() < end:
        chunk = fh.read()
        if not chunk:
            time.sleep(0.02)  # 20ms poll — well inside the 1s window
            continue
        pending += chunk
        if PROMPT_MARK in pending:
            # fire ESC immediately, then a CR, and look for the prompt
            cap = _send(ESC, secs=1.0)
            cap += _send(b"\r", secs=1.0)
            tail = cap[-300:]
            if UBOOT in cap or UBOOT in pending[-200:]:
                print("CAUGHT: RTL9300# prompt reached.", flush=True)
                sys.stdout.buffer.write(b"--- capture ---\n" + cap + b"\n")
                return 0
            # one more CR in case the prompt banner lagged
            cap2 = _send(b"\r", secs=1.0)
            if UBOOT in cap2:
                print("CAUGHT (second CR): RTL9300# prompt reached.", flush=True)
                sys.stdout.buffer.write(cap2)
                return 0
            print("ESC sent at prompt but RTL9300# not confirmed yet; "
                  "check the log / try `switch_console.py send --raw $'\\r'`.",
                  flush=True)
            sys.stdout.buffer.write(b"--- capture ---\n" + cap + cap2 + b"\n")
            return 3
    print("wait elapsed; no autoboot prompt seen (switch not power-cycled?).",
          flush=True)
    return 2


if __name__ == "__main__":
    sys.exit(main())
