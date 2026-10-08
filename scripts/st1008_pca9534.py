#!/usr/bin/env python3
"""st1008_pca9534 — drive the TL-ST1008F SFP TX-disable expander from stock U-Boot.

- PCA9534 @0x38 on i2c-gpio SCL=GPIO22 / SDA=GPIO23 (OpenWrt DTS). tx-disable
  per cage = pin N, active-high. Power-on: all inputs (pull-up) => lasers OFF.
- Superseded by `rtk i2c write 8 ...` after `rtk network on` (docs/hardware.md, Method A).
- Works with no SDK init (where `rtk i2c`/`rtk pinGet` wedge U-Boot): bit-bangs I2C with raw
  `mw.l`/`md.l` on the RTL9300 GPIO block (0xb8003300: DIR +8, DAT +0xC, bit n = GPIO n).
- Open-drain emulation: low = DIR out + DAT 0; high = DIR in (board pull-ups).
  DAT bits 22/23 are cleared once; every bus edge is then a DIR write only.
- GPIO21 (ext. watchdog toggle pin) is an output driven 1; every word written
  preserves it. See docs/hardware.md (Method B).

Usage:
    st1008_pca9534.py probe             # GPIO regs, release bus, pull-up check
    st1008_pca9534.py read              # PCA9534 regs 0..3
    st1008_pca9534.py enable-tx [--out 0x00]   # reg1=out, reg3=0 (all outputs)
Options: --per-line N (mw per U-Boot line, default 6; use 1 if NACKs).
Log: tmp/logs/st1008_pca9534.log
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

RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()))
SOCK = RUNTIME / "tio-st1008.daemon.sock"
LOG = Path(__file__).resolve().parent.parent / "tmp/logs/st1008_pca9534.log"

GPIO_DIR = 0xB8003308
GPIO_DAT = 0xB800330C
SCL = 1 << 22
SDA = 1 << 23
PCA_ADDR = 0x38
# daemon settles ~0.35s after last byte; a 200-char echo at 115200 is ~20ms,
# so 1.0s is ~2.5x expected. Expiry = abort (no prompt => console wedged).
SEND_SECS = 1.0


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


class Console:
    def __init__(self) -> None:
        if not SOCK.exists():
            sys.exit(f"no daemon socket at {SOCK}")

    def _req(self, req: dict) -> dict:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10.0)  # daemon replies within SEND_SECS; 10x margin => daemon dead
        s.connect(str(SOCK))
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
        s.close()
        return json.loads(buf.decode()) if buf else {"ok": False, "error": "no reply"}

    def cmd(self, text: str) -> str:
        r = self._req({"op": "send", "secs": SEND_SECS,
                       "data": base64.b64encode((text + "\r").encode()).decode()})
        if not r.get("ok"):
            raise RuntimeError(f"daemon error: {r.get('error')}")
        out = base64.b64decode(r.get("captured", "")).decode("latin1")
        log(f"TX {text!r}")
        if "RTL9300#" not in out:
            log(f"NO PROMPT after {text!r}; got {out!r}")
            raise RuntimeError("console did not return to prompt - wedged?")
        return out

    def md(self, addr: int) -> int:
        out = self.cmd(f"md.l 0x{addr:08x} 1")
        m = re.search(r"%08x: ([0-9a-f]{8})" % addr, out)
        if not m:
            raise RuntimeError(f"cannot parse md output: {out!r}")
        return int(m.group(1), 16)


class BitBang:
    """Collects DIR words; flushes them as batched mw.l lines."""

    def __init__(self, con: Console, per_line: int) -> None:
        self.con = con
        self.per_line = per_line
        self.pending: list[int] = []
        dat = con.md(GPIO_DAT)
        dir_ = con.md(GPIO_DIR)
        log(f"GPIO DIR=0x{dir_:08x} DAT=0x{dat:08x}")
        if not (dir_ & (1 << 21)) or not (dat & (1 << 21)):
            raise RuntimeError("GPIO21 (watchdog) not output-high as expected; refusing")
        self.base = dir_ & ~(SCL | SDA)        # everything else preserved
        # release both lines first, then make sure DAT bits are 0 for later lows
        con.cmd(f"mw.l 0x{GPIO_DIR:08x} 0x{self.base:08x}")
        con.cmd(f"mw.l 0x{GPIO_DAT:08x} 0x{(dat & ~(SCL | SDA)):08x}")
        idle = con.md(GPIO_DAT)
        log(f"bus released: DAT=0x{idle:08x} SCL={(idle >> 22) & 1} SDA={(idle >> 23) & 1}")
        if (idle & (SCL | SDA)) != (SCL | SDA):
            raise RuntimeError("SCL/SDA not pulled high when released - no pull-ups?")
        self.scl_lo = False
        self.sda_lo = False

    def _emit(self) -> None:
        self.pending.append(self.base | (SCL if self.scl_lo else 0) | (SDA if self.sda_lo else 0))
        if len(self.pending) >= self.per_line:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        line = "; ".join(f"mw.l 0x{GPIO_DIR:08x} 0x{w:08x}" for w in self.pending)
        self.pending = []
        self.con.cmd(line)

    def scl(self, hi: bool) -> None:
        self.scl_lo = not hi
        self._emit()

    def sda(self, hi: bool) -> None:
        self.sda_lo = not hi
        self._emit()

    def sample_sda(self) -> int:
        self.flush()
        return (self.con.md(GPIO_DAT) >> 23) & 1

    # --- I2C primitives (bus idle: both high) ---
    def start(self) -> None:
        self.sda(True); self.scl(True); self.sda(False); self.scl(False)

    def stop(self) -> None:
        self.sda(False); self.scl(True); self.sda(True)

    def write_byte(self, b: int) -> bool:
        for i in range(7, -1, -1):
            self.sda(bool((b >> i) & 1)); self.scl(True); self.scl(False)
        self.sda(True)          # release for ACK
        self.scl(True)
        ack = self.sample_sda() == 0
        self.scl(False)
        return ack

    def read_byte(self, ack: bool) -> int:
        v = 0
        self.sda(True)
        for _ in range(8):
            self.scl(True)
            v = (v << 1) | self.sample_sda()
            self.scl(False)
        self.sda(not ack)       # ACK = drive low
        self.scl(True); self.scl(False)
        self.sda(True)
        return v


def pca_write(bb: BitBang, reg: int, val: int) -> bool:
    bb.start()
    a1 = bb.write_byte(PCA_ADDR << 1)
    a2 = bb.write_byte(reg)
    a3 = bb.write_byte(val)
    bb.stop(); bb.flush()
    log(f"PCA9534 write reg{reg}=0x{val:02x} acks addr={a1} reg={a2} data={a3}")
    return a1 and a2 and a3


def pca_read(bb: BitBang, reg: int) -> int | None:
    bb.start()
    a1 = bb.write_byte(PCA_ADDR << 1)
    a2 = bb.write_byte(reg)
    bb.start()                              # repeated start
    a3 = bb.write_byte((PCA_ADDR << 1) | 1)
    v = bb.read_byte(ack=False)
    bb.stop(); bb.flush()
    ok = a1 and a2 and a3
    log(f"PCA9534 read reg{reg} -> 0x{v:02x} acks addr={a1} reg={a2} rd={a3}")
    return v if ok else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["probe", "read", "enable-tx"])
    ap.add_argument("--out", type=lambda s: int(s, 0), default=0x00,
                    help="reg1 output value for enable-tx (bit N=1 disables cage N+1 laser)")
    ap.add_argument("--per-line", type=int, default=6)
    args = ap.parse_args()

    con = Console()
    bb = BitBang(con, args.per_line)
    if args.action == "probe":
        return 0
    if args.action == "read":
        for r in range(4):
            pca_read(bb, r)
        return 0
    # enable-tx: output value first (power-on reg1=0xff), then config -> outputs
    ok = pca_write(bb, 1, args.out) and pca_write(bb, 3, 0x00)
    r1 = pca_read(bb, 1)
    r3 = pca_read(bb, 3)
    log(f"enable-tx done: acks_ok={ok} reg1=0x{r1 if r1 is not None else -1:02x} reg3=0x{r3 if r3 is not None else -1:02x}")
    return 0 if (ok and r3 == 0 and r1 == args.out) else 1


if __name__ == "__main__":
    sys.exit(main())
