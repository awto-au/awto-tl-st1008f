#!/usr/bin/env python3
"""dump_flash_mdb — read an RTL9300 flash range over U-Boot `md.b` serial.

Drives the switch_console_daemon socket (must be at the RTL9300# prompt). No
ymodem-SEND exists in this U-Boot, so console `md.b` hex is the only way out;
baud is the only speed lever (set it with `switch_console.py baud` after U-Boot
accepts `setenv baudrate`). Verifies with the target's own `crc32` over the
range, so a few bytes corrupted at high baud fail the check rather than passing
silently.

Flash is memory-mapped at 0xb4000000. Partitions (from the live boot log):
    LOADER   0x000000-0x0e0000      RUNTIME  0x300000-0x1180000  (~15.2 MB)
    BDINFO   0x0e0000-0x0f0000      RUNTIME2 0x1180000-0x2000000
    SYSINFO  0x0f0000-0x100000
    JFFS2CFG 0x100000-0x200000      whole    0x000000-0x2000000   (32 MB)
    JFFS2LOG 0x200000-0x300000

Usage (dump RUNTIME, the kernel+rootfs):
    dump_flash_mdb.py --start 0x300000 --len 0xe80000 --out private/stock-runtime/runtime.bin
Resumes if --out.partial exists. Add --no-verify to skip the crc32 check.
Log: tmp/logs/dump_flash_mdb.log
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import socket
import sys
import time
from pathlib import Path

RUNTIME_SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()))
SOCK = RUNTIME_SOCK / "tio-st1008.daemon.sock"
FLASH_BASE = 0xB4000000
CHUNK = 0x1000  # 4 KiB per md.b — balances prompt overhead vs response size

RUN_LOG = Path(__file__).resolve().parent.parent / "tmp/logs/dump_flash_mdb.log"
# md.b prints ~80 chars per 16 bytes ("aaaaaaaa: " + 16*"xx " + ASCII + CRLF) = 5 chars/byte.
MD_CHARS_PER_BYTE = 5
DAEMON_SETTLE = 0.4  # daemon returns 0.3 s after output stops, plus prompt echo

LINE_RE = re.compile(rb"^([0-9a-fA-F]{8}):\s((?:[0-9a-fA-F]{2}\s){1,16})")
CRC_RE = re.compile(rb"==>\s*([0-9a-fA-F]{8})")
PROMPT = b"RTL9300#"


def _req(d: dict, wait: float) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(wait + 15)
    s.connect(str(SOCK))
    s.sendall((json.dumps(d) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        c = s.recv(1 << 16)
        if not c:
            break
        buf += c
    s.close()
    return json.loads(buf.decode())


def _cmd(line: str, wait: float) -> bytes:
    """Send a U-Boot command line, return captured console bytes (incl reply)."""
    r = _req({"op": "send", "data": base64.b64encode((line).encode()).decode(),
              "secs": wait}, wait)
    if not r.get("ok"):
        raise RuntimeError(r.get("error", "send failed"))
    return base64.b64decode(r.get("captured", ""))


def _at_prompt() -> bool:
    cap = _cmd("\r", 1.0)
    return PROMPT in cap


def parse_mdb(blob: bytes, base_addr: int, count: int) -> bytes:
    """Parse md.b console output into `count` bytes starting at base_addr.
    Verifies each line's address is contiguous; raises on gap/garble."""
    out = bytearray()
    expect = base_addr
    for m in LINE_RE.finditer(blob):
        addr = int(m.group(1), 16)
        if addr != (expect & 0xFFFFFFFF):
            # tolerate the first line if md echoes a different base; else gap
            if out:
                raise ValueError(f"address gap: got {addr:08x} expected {expect & 0xFFFFFFFF:08x}")
        hexs = m.group(2).split()
        out += bytes(int(h, 16) for h in hexs)
        expect = addr + len(hexs)
    if len(out) < count:
        raise ValueError(f"short read: parsed {len(out)} of {count} bytes")
    return bytes(out[:count])


def md_wait(n: int, baud: int) -> float:
    """Response window for `md.b` of n bytes: serial time at 10 bits/char, x1.25."""
    return n * MD_CHARS_PER_BYTE * 10 / baud * 1.25 + DAEMON_SETTLE


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


def target_crc(addr: int, length: int, wait: float = 60.0) -> str | None:
    cap = _cmd(f"crc32 {addr:x} {length:x}\r", wait)
    m = CRC_RE.search(cap)
    return m.group(1).decode().lower() if m else None


def host_crc32(data: bytes) -> str:
    import zlib
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", type=lambda x: int(x, 0), required=True,
                    help="flash offset (e.g. 0x300000)")
    ap.add_argument("--len", type=lambda x: int(x, 0), required=True,
                    help="length in bytes (e.g. 0xe80000)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args()
    _tee_output(RUN_LOG)

    if not SOCK.exists():
        print("daemon socket absent; start switch_console_daemon.py", file=sys.stderr)
        return 2
    if not _at_prompt():
        print("not at RTL9300# prompt. Power-cycle; the daemon auto-catches U-Boot, "
              "then re-run.", file=sys.stderr)
        return 3

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_suffix(out.suffix + ".partial")
    done = partial.stat().st_size if partial.exists() else 0
    done -= done % CHUNK  # resume on a chunk boundary
    fh = partial.open("r+b" if partial.exists() else "wb")
    fh.seek(done)
    fh.truncate(done)

    total = args.len
    base = FLASH_BASE + args.start
    baud = int(_req({"op": "status"}, 2.0).get("baud", 115200))
    wait = md_wait(CHUNK, baud)
    t0 = time.monotonic()
    off = done
    print(f"dumping flash {args.start:#x}..{args.start+total:#x} "
          f"(mem {base:#x}) {total} bytes, resume@{done}", flush=True)
    while off < total:
        n = min(CHUNK, total - off)
        addr = base + off
        cap = _cmd(f"md.b {addr:x} {n:x}\r", wait=wait)
        try:
            data = parse_mdb(cap, addr, n)
        except ValueError as exc:
            print(f"\nparse error at {addr:#x} (window {wait:.2f}s @ {baud}): {exc}; "
                  f"retrying once", flush=True)
            cap = _cmd(f"md.b {addr:x} {n:x}\r", wait=wait)
            data = parse_mdb(cap, addr, n)
        fh.write(data)
        fh.flush()
        off += n
        if off % 0x40000 == 0 or off >= total:
            el = time.monotonic() - t0
            rate = (off - done) / el if el else 0
            eta = (total - off) / rate if rate else 0
            print(f"  {off}/{total} ({100*off//total}%)  {rate/1024:.1f} KB/s  "
                  f"eta {eta:.0f}s", flush=True)
    fh.close()
    partial.rename(out)
    data = out.read_bytes()
    print(f"read {len(data)} bytes -> {out}", flush=True)

    if not args.no_verify:
        hc = host_crc32(data)
        tc = target_crc(base, total)
        print(f"host crc32 = {hc}   target crc32 = {tc}", flush=True)
        if tc and hc == tc:
            print("VERIFIED: host and target CRC32 match.", flush=True)
        else:
            print("CRC MISMATCH — dump is corrupt (likely baud errors). "
                  "Lower baud and re-run.", flush=True)
            return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
