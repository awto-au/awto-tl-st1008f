#!/usr/bin/env python3
"""switch_console_daemon — pyserial owner of the TL-ST1008F serial console.

tio drops this PL2303 when launched without a real terminal stdin (it reads
EOF and reports "Disconnected"); pyserial holds it. Contract: ONE owner holds
the tty, a reader thread mirrors everything to the on-disk log, and a unix
socket is the one control channel (send bytes / BREAK / change baud / read
echo). Nothing else opens the tty.

Why a daemon and not the client opening the port each call: repeated open/close
on this adapter is exactly what wedged the previous CH341 session. One long-held
handle, many short client connections.

Protocol (newline-delimited JSON on the unix socket, one request per connect):
    {"op":"send","data":"<base64>"}      inject raw bytes
    {"op":"break"}                        tcsendbreak() — a real UART BREAK
    {"op":"baud","baud":1500000}          reopen tty at new baud (no daemon drop)
    {"op":"read","secs":2.0}              return log bytes captured over window
    {"op":"status"}                       {"baud":..,"bytes":..,"dev":..}
    {"op":"ping"}                         {"ok":true}
Each send/break/read reply: {"ok":true,"captured":"<base64 of new log bytes>"}.

Run (keep it in the background):
    scripts/switch_console_daemon.py --dev /dev/serial/by-id/<adapter> --baud 115200
--dev defaults to $ST1008_SERIAL, else the generic PL2303 by-id name.
Log: private/serial/st1008-console.log (--log to change).
Stop: send {"op":"quit"} or kill the pid in <sockdir>/tio-st1008.daemon.pid.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import serial  # pyserial

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()))
SOCK_PATH = RUNTIME / "tio-st1008.daemon.sock"
PID_PATH = RUNTIME / "tio-st1008.daemon.pid"
DEV = os.environ.get(
    "ST1008_SERIAL",
    "/dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller-if00-port0",
)
LOG = Path(__file__).resolve().parent.parent / "private/serial/st1008-console.log"


class Owner:
    def __init__(self, dev: str, baud: int, log: Path):
        self.dev = dev
        self.baud = baud
        self.log = log
        self._ser: serial.Serial | None = None
        self._lock = threading.Lock()  # guards the serial handle across reopen
        self._stop = threading.Event()
        self._logfh = log.open("ab", buffering=0)
        # --- always-on U-Boot autoboot catch ---------------------------
        # The reader thread sees every byte, so banner detection lives here,
        # not in a separate armed script racing the 1 s window. When the
        # autoboot banner appears the daemon sends ESC itself, lands at the
        # RTL9300# prompt, and then applies the policy:
        #   "hold"  — stay at the prompt, let an operator/script decide.
        #   "boota" — issue `boota` to boot the stock kernel normally.
        #   "<cmd>" — any U-Boot command string to run, then (optionally) boota.
        # Set via the "policy" op. Default holds.
        self.autoboot_policy = "hold"
        self.at_prompt = threading.Event()
        self._rx_tail = b""                 # rolling RX tail for banner match
        self._last_catch = 0.0              # debounce repeated banner hits
        self._dumping = False               # reader pauses during a bulk dump
        self._open()
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    AUTOBOOT_BANNER = b"Hit Esc key to stop autoboot"
    PROMPT = b"RTL9300#"
    ESC = b"\x1b"

    def _open(self):
        with self._lock:
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
            # timeout small so the reader loop stays responsive; no DTR/RTS
            # games — pyserial defaults keep this PL2303 stable.
            self._ser = serial.Serial(self.dev, self.baud, timeout=0.1)
            stamp = f"\n[daemon] open {self.dev} @ {self.baud} 8N1 {time.strftime('%FT%T%z')}\n"
            self._logfh.write(stamp.encode())

    def _read_loop(self):
        while not self._stop.is_set():
            try:
                if self._dumping:
                    time.sleep(0.05)  # dump owns the serial reads; stand down
                    continue
                # Only read what's actually waiting, and hold the lock just for
                # the read itself. The old `ser.read(n or 1)` did a BLOCKING
                # read(1) under the lock whenever the buffer was empty, hogging
                # the lock ~timeout each idle loop and starving client writes.
                with self._lock:
                    ser = self._ser
                    n = ser.in_waiting if ser else 0
                    data = ser.read(n) if (ser and n) else b""
                if data:
                    self._logfh.write(data)
                    self._watch(data)
                else:
                    time.sleep(0.01)  # nothing waiting; yield without the lock
            except Exception as exc:
                self._logfh.write(f"\n[daemon] read error: {exc}\n".encode())
                time.sleep(0.2)

    def _watch(self, data: bytes):
        """Banner detection on the live RX stream. Keep a short rolling tail so
        a banner split across two reads still matches."""
        self._rx_tail = (self._rx_tail + data)[-256:]
        if self.PROMPT in self._rx_tail:
            self.at_prompt.set()
        if self.AUTOBOOT_BANNER in self._rx_tail:
            now = time.monotonic()
            if now - self._last_catch < 3.0:
                return  # debounce: one banner burst prints the countdown twice
            self._last_catch = now
            self._rx_tail = b""  # consume so we don't re-fire on the same banner
            self._catch_autoboot()

    def _catch_autoboot(self):
        """Fire ESC into the ~1 s window, then apply the autoboot policy."""
        self._logfh.write(b"\n[daemon] autoboot banner seen -> sending ESC\n")
        with self._lock:
            self._ser.write(self.ESC)
            self._ser.flush()
        # tiny settle so U-Boot prints the prompt; bounded, not a hardware wait
        time.sleep(0.15)
        with self._lock:
            self._ser.write(b"\r")
            self._ser.flush()
        self.at_prompt.set()
        policy = self.autoboot_policy
        self._logfh.write(f"\n[daemon] at RTL9300#; policy={policy!r}\n".encode())
        if policy and policy != "hold":
            # policy is a U-Boot command line to run (e.g. "boota", or a
            # setenv + boota sequence joined by ';'). Give the prompt a beat.
            time.sleep(0.2)
            self._mark_tx(f"<policy> {policy}")
            with self._lock:
                self._ser.write(policy.encode() + b"\r")
                self._ser.flush()

    # --- operations ---------------------------------------------------
    def _mark_tx(self, label: str):
        """Write a visible TX marker to the log so a tail shows both sides."""
        self._logfh.write(f"\n[TX {time.strftime('%T')}] {label}\n".encode())

    def send(self, raw: bytes):
        # Log what we inject (printable form) so the tail shows input + output.
        shown = raw.decode("utf-8", "replace").replace("\r", "\\r").replace("\n", "\\n")
        self._mark_tx(repr(shown))
        with self._lock:
            self._ser.write(raw)
            self._ser.flush()

    def send_break(self, dur: float = 0.3):
        # tcsendbreak via pyserial: a real line BREAK, dur seconds.
        self._mark_tx(f"<BREAK {dur}s>")
        with self._lock:
            self._ser.send_break(dur)

    def break_cmd(self, cmd: bytes, dur: float = 0.25):
        # BREAK then the SysRq command byte with NO gap (same lock hold), so
        # the 8250 console treats `cmd` as the SysRq key. Two separate ops add
        # socket+scheduling latency that can miss the window.
        self._mark_tx(f"<BREAK {dur}s>+{cmd!r}")
        with self._lock:
            self._ser.send_break(dur)
            self._ser.write(cmd)
            self._ser.flush()

    def set_baud(self, baud: int):
        self.baud = baud
        self._open()  # reopen; daemon + socket stay up

    # --- bulk flash dump (runs inside the daemon; keeps hex OUT of the log) --
    def dump_range(self, mem_addr: int, length: int, out_path: str,
                   chunk: int = 0x1000, resume: bool = True) -> dict:
        """md.b the given memory range into out_path.partial, parsing hex to raw
        bytes here. The reader thread is paused for the duration (we own reads
        directly), and only a periodic progress line goes to the log — the 15 MB
        of hex never touches it. Returns {bytes, host_crc32, path}.
        """
        import re
        import zlib
        line_re = re.compile(rb"([0-9a-fA-F]{8}):\s((?:[0-9a-fA-F]{2}\s?){1,16})")
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        partial = out.with_suffix(out.suffix + ".partial")
        done = (partial.stat().st_size if (resume and partial.exists()) else 0)
        done -= done % chunk
        self._logfh.write(
            f"\n[daemon] dump {mem_addr:#x} len {length:#x} -> {out_path} resume@{done}\n".encode())
        self._dumping = True
        try:
            fh = partial.open("r+b" if partial.exists() else "wb")
            fh.seek(done); fh.truncate(done)
            off = done
            with self._lock:
                self._ser.reset_input_buffer()
            t0 = time.monotonic()
            while off < length:
                n = min(chunk, length - off)
                addr = mem_addr + off
                data = self._md_block(addr, n, line_re)
                fh.write(data); fh.flush()
                off += n
                if off % 0x80000 == 0 or off >= length:
                    el = time.monotonic() - t0
                    rate = (off - done) / el if el else 0
                    self._logfh.write(
                        f"[daemon] dump {off}/{length} ({100*off//length}%) "
                        f"{rate/1024:.1f} KB/s\n".encode())
            fh.close()
            raw = partial.read_bytes()
            partial.rename(out)
            return {"bytes": len(raw),
                    "host_crc32": f"{zlib.crc32(raw) & 0xFFFFFFFF:08x}",
                    "path": str(out)}
        finally:
            self._dumping = False

    def _md_block(self, addr: int, n: int, line_re) -> bytes:
        """Send one md.b, read directly until the prompt returns, parse to bytes.
        Retries once on a short/garbled block."""
        out = bytearray()
        for _ in (1, 2):  # one retry on a short/garbled block
            with self._lock:
                self._ser.reset_input_buffer()
                self._ser.write(f"md.b {addr:x} {n:x}\r".encode())
                self._ser.flush()
                buf = b""
                # read until prompt or a bounded cap (block time scales w/ baud)
                cap_end = time.monotonic() + max(4.0, n / (self.baud / 20))
                while time.monotonic() < cap_end:
                    chunk = self._ser.read(4096)
                    if chunk:
                        buf += chunk
                        if self.PROMPT in buf[-40:]:
                            break
            out = bytearray()
            for m in line_re.finditer(buf):
                out += bytes(int(h, 16) for h in m.group(2).split())
            if len(out) >= n:
                return bytes(out[:n])
        raise RuntimeError(f"md.b {addr:#x} short: {len(out)}/{n} bytes")

    def logsize(self) -> int:
        try:
            return self.log.stat().st_size
        except OSError:
            return 0

    def close(self):
        self._stop.set()
        with self._lock:
            if self._ser:
                try:
                    self._ser.close()
                except Exception:
                    pass
        try:
            self._logfh.close()
        except Exception:
            pass


def _capture_after(owner: Owner, mark: int, secs: float) -> bytes:
    """Return log bytes written after `mark`, waiting up to `secs` for output
    to appear and settle. Bounded — this is the response window, not a hang
    guard."""
    end = time.monotonic() + secs
    last = owner.logsize()
    stable = 0
    while time.monotonic() < end:
        size = owner.logsize()
        if size > last:
            last = size
            stable = 0
        elif size > mark:
            stable += 1
            if stable > 6:
                break
        time.sleep(0.05)
    with owner.log.open("rb") as fh:
        fh.seek(mark)
        return fh.read()


def _capture_until(owner: Owner, mark: int, marker: bytes, cap_secs: float) -> bytes:
    """Return log bytes after `mark`, waiting until `marker` appears in the new
    output or `cap_secs` elapses. Robust for md.b: the block is done exactly
    when the prompt returns, regardless of how long the bytes took."""
    end = time.monotonic() + cap_secs
    while time.monotonic() < end:
        with owner.log.open("rb") as fh:
            fh.seek(mark)
            new = fh.read()
        if marker in new:
            return new
        time.sleep(0.02)
    with owner.log.open("rb") as fh:
        fh.seek(mark)
        return fh.read()


def serve(owner: Owner):
    if SOCK_PATH.exists():
        SOCK_PATH.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCK_PATH))
    srv.listen(8)
    srv.settimeout(0.5)
    PID_PATH.write_text(str(os.getpid()))

    def shutdown(*_):
        owner.close()
        try:
            srv.close()
        except Exception:
            pass
        for p in (SOCK_PATH, PID_PATH):
            try:
                p.unlink()
            except OSError:
                pass
        os._exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    while True:
        try:
            conn, _ = srv.accept()
        except socket.timeout:
            continue
        except OSError:
            break
        with conn:
            try:
                conn.settimeout(10)
                buf = b""
                while b"\n" not in buf:
                    chunk = conn.recv(4096)
                    if not chunk:
                        break
                    buf += chunk
                if not buf:
                    continue
                req = json.loads(buf.decode())
                op = req.get("op")
                reply: dict = {"ok": True}
                if op == "ping":
                    pass
                elif op == "status":
                    reply.update(baud=owner.baud, bytes=owner.logsize(), dev=owner.dev,
                                 policy=owner.autoboot_policy,
                                 at_prompt=owner.at_prompt.is_set())
                elif op == "policy":
                    # Set what the daemon does when it auto-catches the autoboot
                    # banner: "hold", "boota", or any U-Boot command line.
                    owner.autoboot_policy = str(req.get("policy", "hold"))
                    reply["policy"] = owner.autoboot_policy
                elif op == "clear_prompt":
                    owner.at_prompt.clear()
                    reply["at_prompt"] = False
                elif op == "send":
                    mark = owner.logsize()
                    owner.send(base64.b64decode(req["data"]))
                    cap = _capture_after(owner, mark, float(req.get("secs", 2.0)))
                    reply["captured"] = base64.b64encode(cap).decode()
                elif op == "break":
                    mark = owner.logsize()
                    owner.send_break(float(req.get("dur", 0.3)))
                    cap = _capture_after(owner, mark, float(req.get("secs", 2.0)))
                    reply["captured"] = base64.b64encode(cap).decode()
                elif op == "break_cmd":
                    mark = owner.logsize()
                    owner.break_cmd(base64.b64decode(req["cmd"]),
                                    float(req.get("dur", 0.25)))
                    cap = _capture_after(owner, mark, float(req.get("secs", 2.0)))
                    reply["captured"] = base64.b64encode(cap).decode()
                elif op == "baud":
                    owner.set_baud(int(req["baud"]))
                    reply["baud"] = owner.baud
                elif op == "dump_range":
                    # Bulk flash dump runs entirely in the daemon: hex parsed to
                    # raw bytes here, only progress to the log. Long-running;
                    # the client sets a generous read timeout.
                    res = owner.dump_range(int(req["mem_addr"]), int(req["length"]),
                                           req["out"], int(req.get("chunk", 0x1000)),
                                           bool(req.get("resume", True)))
                    reply.update(res)
                elif op == "read":
                    mark = owner.logsize()
                    cap = _capture_after(owner, mark, float(req.get("secs", 3.0)))
                    reply["captured"] = base64.b64encode(cap).decode()
                elif op == "quit":
                    conn.sendall((json.dumps({"ok": True}) + "\n").encode())
                    shutdown()
                else:
                    reply = {"ok": False, "error": f"unknown op {op!r}"}
                conn.sendall((json.dumps(reply) + "\n").encode())
            except Exception as exc:
                try:
                    conn.sendall((json.dumps({"ok": False, "error": str(exc)}) + "\n").encode())
                except Exception:
                    pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--dev", default=DEV)
    ap.add_argument("--log", type=Path, default=LOG)
    ap.add_argument("--policy", default="hold",
                    help="autoboot catch policy: hold | boota | <uboot cmd>")
    args = ap.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    owner = Owner(args.dev, args.baud, args.log)
    owner.autoboot_policy = args.policy
    serve(owner)
    return 0


if __name__ == "__main__":
    sys.exit(main())
