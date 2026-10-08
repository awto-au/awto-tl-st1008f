#!/usr/bin/env python3
"""switch_console — client for the TL-ST1008F pyserial console daemon.

The daemon (scripts/switch_console_daemon.py) owns the Prolific adapter and
logs BOTH sides (TX markers + RX) to one file you can `tail -f`:

    private/serial/st1008-console.log

This client sends one request per invocation over the daemon's unix socket and
prints whatever the switch emitted in response. tio is not used — it drops this
PL2303 when launched without a terminal stdin; pyserial holds it solid.

Usage:
    switch_console.py status
    switch_console.py send "help"          # injects "help\r", prints reply
    switch_console.py send --raw $'\r'      # raw bytes, no appended CR
    switch_console.py esc                   # one ESC byte (stop autoboot)
    switch_console.py break [--dur 0.3]     # a real UART BREAK (tcsendbreak)
    switch_console.py baud 1500000          # reopen tty at new baud
    switch_console.py read --secs 3         # drain output for N secs

Start the daemon (persists in the background):
    scripts/switch_console_daemon.py --dev /dev/serial/by-id/<adapter> --baud 115200
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import sys
from pathlib import Path

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()))
SOCK = RUNTIME / "tio-st1008.daemon.sock"
LOG = "private/serial/st1008-console.log"
ESC = b"\x1b"


def _request(req: dict, read_timeout: float = 30.0) -> dict:
    if not SOCK.exists():
        print(
            f"no daemon socket at {SOCK}. The console daemon is not running.\n"
            f"Start it:\n    scripts/switch_console_daemon.py --dev /dev/serial/by-id/<adapter> --baud 115200",
            file=sys.stderr,
        )
        sys.exit(2)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(read_timeout)
    try:
        s.connect(str(SOCK))
    except OSError as exc:
        print(f"socket present but refused ({exc}); daemon likely died. Restart it.",
              file=sys.stderr)
        sys.exit(2)
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf.decode()) if buf else {"ok": False, "error": "no reply"}


def _print_capture(reply: dict):
    if not reply.get("ok"):
        print(f"error: {reply.get('error')}", file=sys.stderr)
        sys.exit(1)
    cap = reply.get("captured")
    if cap:
        sys.stdout.buffer.write(base64.b64decode(cap))
        sys.stdout.flush()
    else:
        print("(no output captured)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status")
    sub.add_parser("ping")

    sp = sub.add_parser("send")
    sp.add_argument("text")
    sp.add_argument("--raw", action="store_true", help="do not append CR")
    sp.add_argument("--secs", type=float, default=2.0)

    se = sub.add_parser("esc")
    se.add_argument("--secs", type=float, default=2.0)

    sb = sub.add_parser("break")
    sb.add_argument("--dur", type=float, default=0.3)
    sb.add_argument("--secs", type=float, default=2.0)

    sa = sub.add_parser("baud")
    sa.add_argument("baud", type=int)

    spol = sub.add_parser("policy", help="autoboot catch policy: hold|boota|<cmd>")
    spol.add_argument("policy")

    sr = sub.add_parser("read")
    sr.add_argument("--secs", type=float, default=3.0)

    args = ap.parse_args()

    if args.cmd == "status":
        r = _request({"op": "status"})
        print(json.dumps(r))
        return 0 if r.get("ok") else 1
    if args.cmd == "ping":
        print(json.dumps(_request({"op": "ping"})))
        return 0
    if args.cmd == "send":
        payload = args.text.encode("utf-8", "replace")
        if not args.raw:
            payload += b"\r"
        _print_capture(_request({"op": "send",
                                 "data": base64.b64encode(payload).decode(),
                                 "secs": args.secs}))
        return 0
    if args.cmd == "esc":
        _print_capture(_request({"op": "send",
                                 "data": base64.b64encode(ESC).decode(),
                                 "secs": args.secs}))
        return 0
    if args.cmd == "break":
        _print_capture(_request({"op": "break", "dur": args.dur, "secs": args.secs}))
        return 0
    if args.cmd == "baud":
        print(json.dumps(_request({"op": "baud", "baud": args.baud})))
        return 0
    if args.cmd == "policy":
        print(json.dumps(_request({"op": "policy", "policy": args.policy})))
        return 0
    if args.cmd == "read":
        _print_capture(_request({"op": "read", "secs": args.secs},
                                read_timeout=args.secs + 10))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
