#!/usr/bin/env python3
"""Minimal TFTP server for netbooting the switch from stock U-Boot.

- RRQ: device downloads from us (U-Boot `tftpboot` of the OpenWrt initramfs).
- WRQ: device uploads to us (e.g. a future `tftpput` or busybox `tftp -p`).
- blksize / tsize option negotiation (RFC 2348/2349).
- TFTP ACKs every block: a transfer completes or fails loudly, never truncates silently.

Serves and accepts only inside --root. A filename escaping it is refused.

Run: scripts/tftpd.py                    # serves tmp/tftp on udp/69 (needs root or CAP_NET_BIND_SERVICE)
     scripts/tftpd.py --port 6969 --once # unprivileged; exit after one transfer
Log: tmp/logs/tftpd.log
"""

from __future__ import annotations

import argparse
import socket
import struct
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOGS = REPO / "tmp/logs"
TFTP_ROOT = REPO / "tmp/tftp"


def rel(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(REPO))
    except ValueError:
        return str(p)

RRQ, WRQ, DATA, ACK, ERROR, OACK = 1, 2, 3, 4, 5, 6

# Binding 69 needs root or CAP_NET_BIND_SERVICE. Stock U-Boot `tftpboot` always uses 69;
# --port is for clients that accept another port (busybox tftp).
DEFAULT_PORT = 69

# Per-packet wait. Set to U-Boot 2011.12's own TFTP retransmit timer (net/tftp.c,
# TIMEOUT 5000 ms) so a lost packet is resent by the client before we give up.
# Expiry: retransmit up to MAX_RETRIES, then log the block number and abort.
SOCK_TIMEOUT = 5.0
# Retransmits before giving up on a block. TFTP's own reliability mechanism.
MAX_RETRIES = 5


def log(msg, level="INFO"):
    line = f"{datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}  {level:<5} {msg}"
    print(line, flush=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    with (LOGS / "tftpd.log").open("a") as fh:
        fh.write(line + "\n")


def parse_request(data: bytes) -> tuple[int, str, str, dict[str, str]]:
    opcode = struct.unpack(">H", data[:2])[0]
    parts = data[2:].split(b"\x00")
    filename = parts[0].decode("ascii", "replace")
    mode = parts[1].decode("ascii", "replace").lower() if len(parts) > 1 else "octet"
    opts: dict[str, str] = {}
    rest = [p for p in parts[2:] if p]
    for i in range(0, len(rest) - 1, 2):
        opts[rest[i].decode("ascii", "replace").lower()] = rest[i + 1].decode(
            "ascii", "replace"
        )
    return opcode, filename, mode, opts


def safe_path(root: Path, filename: str) -> Path | None:
    p = (root / filename.lstrip("/")).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return None
    return p


def send_error(sock, addr, code: int, msg: str) -> None:
    sock.sendto(struct.pack(">HH", ERROR, code) + msg.encode() + b"\x00", addr)


def handle_wrq(root: Path, addr, filename: str, opts: dict) -> bool:
    """Device uploads to us."""
    dest = safe_path(root, filename)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(SOCK_TIMEOUT)
    if dest is None:
        send_error(sock, addr, 2, "outside root")
        sock.close()
        log(f"REFUSED write of {filename!r} - escapes root", "ERROR")
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)

    blksize = int(opts.get("blksize", 512))
    ack_opts = {}
    if "blksize" in opts:
        ack_opts["blksize"] = str(blksize)
    if "tsize" in opts:
        ack_opts["tsize"] = opts["tsize"]

    if ack_opts:
        pkt = struct.pack(">H", OACK)
        for k, v in ack_opts.items():
            pkt += k.encode() + b"\x00" + v.encode() + b"\x00"
        sock.sendto(pkt, addr)
    else:
        sock.sendto(struct.pack(">HH", ACK, 0), addr)

    total, expect = 0, 1
    with dest.open("wb") as fh:
        while True:
            for attempt in range(MAX_RETRIES):
                try:
                    data, peer = sock.recvfrom(blksize + 4)
                    break
                except TimeoutError:
                    if attempt == MAX_RETRIES - 1:
                        log(f"  timeout waiting for block {expect}", "ERROR")
                        sock.close()
                        return False
            op, blk = struct.unpack(">HH", data[:4])
            if op != DATA:
                log(f"  unexpected opcode {op}", "ERROR")
                sock.close()
                return False
            payload = data[4:]
            if blk == expect:
                fh.write(payload)
                total += len(payload)
                expect = (expect + 1) & 0xFFFF
            sock.sendto(struct.pack(">HH", ACK, blk), peer)
            if len(payload) < blksize:
                break
    sock.close()
    log(f"  received {total} B -> {rel(dest)}")
    return True


def handle_rrq(root: Path, addr, filename: str, opts: dict) -> bool:
    """Device downloads from us (netboot)."""
    src = safe_path(root, filename)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(SOCK_TIMEOUT)
    if src is None or not src.is_file():
        send_error(sock, addr, 1, "file not found")
        sock.close()
        log(f"REFUSED read of {filename!r}", "ERROR")
        return False

    blksize = int(opts.get("blksize", 512))
    size = src.stat().st_size
    ack_opts = {}
    if "blksize" in opts:
        ack_opts["blksize"] = str(blksize)
    if "tsize" in opts:
        ack_opts["tsize"] = str(size)
    if ack_opts:
        pkt = struct.pack(">H", OACK)
        for k, v in ack_opts.items():
            pkt += k.encode() + b"\x00" + v.encode() + b"\x00"
        sock.sendto(pkt, addr)
        try:
            sock.recvfrom(1024)  # ACK 0 for the OACK
        except TimeoutError:
            log("  no ACK for OACK", "ERROR")
            sock.close()
            return False

    blk, sent = 1, 0
    with src.open("rb") as fh:
        while True:
            chunk = fh.read(blksize)
            pkt = struct.pack(">HH", DATA, blk) + chunk
            for attempt in range(MAX_RETRIES):
                sock.sendto(pkt, addr)
                try:
                    data, _ = sock.recvfrom(1024)
                    op, ablk = struct.unpack(">HH", data[:4])
                    if op == ACK and ablk == blk:
                        break
                except TimeoutError:
                    if attempt == MAX_RETRIES - 1:
                        log(f"  no ACK for block {blk}", "ERROR")
                        sock.close()
                        return False
            sent += len(chunk)
            blk = (blk + 1) & 0xFFFF
            if len(chunk) < blksize:
                break
    sock.close()
    log(f"  sent {sent} B from {rel(src)}")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--root",
        default=str(TFTP_ROOT.relative_to(REPO)),
        help="directory to serve/accept into (default tmp/tftp)",
    )
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--once", action="store_true", help="exit after one transfer")
    a = ap.parse_args()

    root = (REPO / a.root).resolve() if not Path(a.root).is_absolute() else Path(a.root)
    root.mkdir(parents=True, exist_ok=True)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("", a.port))
    except PermissionError:
        sys.exit(f"cannot bind port {a.port} (needs root for <1024). Use --port 6969.")
    log(f"tftpd on port {a.port}, root {rel(root)}")

    while True:
        data, addr = sock.recvfrom(65536)
        opcode, filename, _mode, opts = parse_request(data)
        if opcode == WRQ:
            log(f"WRQ  {filename!r} from {addr[0]} opts={opts}")
            ok = handle_wrq(root, addr, filename, opts)
        elif opcode == RRQ:
            log(f"RRQ  {filename!r} from {addr[0]} opts={opts}")
            ok = handle_rrq(root, addr, filename, opts)
        else:
            log(f"unsupported opcode {opcode} from {addr[0]}", "WARN")
            ok = False
        if a.once:
            return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
