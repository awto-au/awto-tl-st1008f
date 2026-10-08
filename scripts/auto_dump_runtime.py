#!/usr/bin/env python3
"""auto_dump_runtime — wait for the daemon to auto-catch U-Boot, then dump
RUNTIME from the user's own flash, earning high baud with a small probe first.

Sequence once at RTL9300#:
  1. Probe baud: try `setenv baudrate 1500000`; if U-Boot accepts, switch the
     daemon baud, confirm the prompt still answers, and CRC a 64 KiB probe
     block at 1.5M. Pass -> full dump at 1.5M. Fail/reject -> stay 115200.
  2. Full RUNTIME dump (0x300000..0x1180000) via dump_flash_mdb.py, CRC-verified.

No power control exists for this switch, so step 0 is: wait (bounded by --wait,
default 1800s) for YOU to power-cycle; the daemon fires ESC itself.

Superseded by the OpenWrt RAM-boot backup (st1008_mtd_backup.py).
Output: private/stock-runtime-<YYYYMMDD-HHMMSS>/runtime.bin. Log: tmp/logs/auto_dump_runtime.log
"""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

RUN = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()))
SOCK = RUN / "tio-st1008.daemon.sock"
HERE = Path(__file__).resolve().parent
OUTDIR = HERE.parent / "private" / f"stock-runtime-{time.strftime('%Y%m%d-%H%M%S')}"
RUN_LOG = HERE.parent / "tmp/logs/auto_dump_runtime.log"
RUNTIME_START, RUNTIME_LEN = 0x300000, 0xE80000
FLASH_BASE = 0xB4000000
PROMPT = b"RTL9300#"
CRC_RE = re.compile(rb"==>\s*([0-9a-fA-F]{8})")


def req(d: dict, wait: float = 5.0) -> dict:
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


def cmd(line: str, wait: float = 2.0) -> bytes:
    r = req({"op": "send", "data": base64.b64encode(line.encode()).decode(), "secs": wait}, wait)
    return base64.b64decode(r.get("captured", "")) if r.get("ok") else b""


def at_prompt() -> bool:
    return PROMPT in cmd("\r", 1.0)


def target_crc(mem_addr: int, length: int, wait: float = 30.0) -> str | None:
    cap = cmd(f"crc32 {mem_addr:x} {length:x}\r", wait)
    m = CRC_RE.search(cap)
    return m.group(1).decode().lower() if m else None


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
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--wait", type=float, default=1800.0,
                    help="seconds to wait for you to power-cycle")
    args = ap.parse_args()
    _tee_output(RUN_LOG)

    if not SOCK.exists():
        print("daemon not running", file=sys.stderr)
        return 2

    print(f"waiting for U-Boot catch (POWER-CYCLE THE SWITCH; up to {args.wait:.0f}s)...",
          flush=True)
    end = time.monotonic() + args.wait
    while time.monotonic() < end:
        st = req({"op": "status"})
        if st.get("at_prompt") and at_prompt():
            break
        time.sleep(0.5)
    else:
        print("no U-Boot prompt within wait window (not power-cycled?)", flush=True)
        return 3
    print("AT RTL9300#. Probing baud...", flush=True)

    baud = 115200
    # --- earn 1.5M -----------------------------------------------------
    cap = cmd("setenv baudrate 1500000\r", 2.0)
    if b"not supported" in cap or b"Baudrate" in cap and b"not" in cap:
        print("U-Boot rejected 1500000; staying at 115200.", flush=True)
        cmd("setenv baudrate 115200\r", 1.0)
    else:
        # U-Boot prints "## Switch baudrate to 1500000 bps and press ENTER ..."
        # Switch the daemon, then send ENTER at the new rate to confirm.
        req({"op": "baud", "baud": 1500000})
        time.sleep(0.3)
        cap = cmd("\r", 1.5)
        if PROMPT in cap:
            # CRC a 64 KiB probe block to prove the link is clean at 1.5M
            probe_mem = FLASH_BASE + RUNTIME_START
            tc = target_crc(probe_mem, 0x10000)
            # dump the same block via the dumper's parser path: quick inline
            ok = _probe_block(probe_mem, 0x10000, tc)
            if ok:
                baud = 1500000
                print("1.5M probe VERIFIED; full dump at 1.5M.", flush=True)
            else:
                print("1.5M probe failed CRC; reverting to 115200.", flush=True)
                req({"op": "baud", "baud": 1500000})  # ensure we talk to switch
                cmd("setenv baudrate 115200\r", 1.0)
                req({"op": "baud", "baud": 115200})
                cmd("\r", 1.0)
        else:
            print("prompt lost after baud switch; reverting to 115200.", flush=True)
            req({"op": "baud", "baud": 115200})
            cmd("\r", 1.0)

    # --- full RUNTIME dump --------------------------------------------
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out = OUTDIR / "runtime.bin"
    print(f"dumping RUNTIME at {baud} baud -> {out}", flush=True)
    rc = subprocess.call([sys.executable, str(HERE / "dump_flash_mdb.py"),
                          "--start", hex(RUNTIME_START), "--len", hex(RUNTIME_LEN),
                          "--out", str(out)])
    return rc


def _probe_block(mem_addr: int, length: int, want_crc: str | None) -> bool:
    """Dump a small block via md.b and compare to the target crc32."""
    import zlib
    from importlib import util
    spec = util.spec_from_file_location("dmb", str(HERE / "dump_flash_mdb.py"))
    dmb = util.module_from_spec(spec)
    spec.loader.exec_module(dmb)
    data = bytearray()
    off = 0
    while off < length:
        n = min(0x1000, length - off)
        cap = cmd(f"md.b {mem_addr+off:x} {n:x}\r", 6.0)
        try:
            data += dmb.parse_mdb(cap, mem_addr + off, n)
        except Exception as exc:
            print(f"  probe parse error: {exc}", flush=True)
            return False
        off += n
    hc = f"{zlib.crc32(bytes(data)) & 0xFFFFFFFF:08x}"
    print(f"  probe host crc={hc} target crc={want_crc}", flush=True)
    return bool(want_crc) and hc == want_crc


if __name__ == "__main__":
    sys.exit(main())
