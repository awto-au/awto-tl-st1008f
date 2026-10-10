#!/usr/bin/env python3
"""Read SFP ID EEPROM (0x50) and DDM (0x51) from stock U-Boot `rtk i2c`, via the console daemon.

- Needs `rtk network on` done this boot (registers `rtk i2c` dev 0-7 = cage 1-8 EEPROM @0x50).
- `probe`: byte 0 of each cage (0x03 = SFP present).
- `dump --dev N`: 256 bytes @0x50 → private/sfp/<ts>/cageN-a0.bin + SFF-8472 decode.
- `ddm --dev N --intf I --sda S`: create dev 10 @0x51 with `rtk i2c init hw`, read A2 bytes 0-111,
  decode temp/Vcc/bias/TX/RX (internal calibration). `--chip 0x50` first to validate the mapping.
- Read-only: never `rtk i2c write` to a module. Log: tmp/logs/st1008_sfp_ddm.log
"""

import argparse
import base64
import json
import logging
import math
import os
import re
import socket
import sys
import time
from pathlib import Path

SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "tio-st1008.daemon.sock"
# Reply window per command: echo + "data 0xNN" + prompt ≈ 50 B at 115200 ≈ 5 ms, I2C byte read
# @100 kHz < 1 ms. The daemon returns as soon as output settles; 0.3 s caps a stalled reply.
REPLY_CAP_S = 0.3
LINE_MAX = 200  # chars per batched line; limits above (read_block)
# Batch reply: ~200 B echo + ~11 B per "data 0xNN" line ≈ 330 B ≈ 30 ms at 115200; 0.5 s cap.
BATCH_CAP_S = 0.5
SCRATCH_DEV = 10  # free `rtk i2c` id (0-7 cages, 8 expander, 9 unused-as-probe)
DATA_RE = re.compile(rb"data 0x([0-9a-fA-F]+)")

log = logging.getLogger("st1008_sfp_ddm")


def send(cmd: str, cap: float = REPLY_CAP_S) -> bytes:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(cap + 5)  # daemon reply = cap + socket overhead
    s.connect(str(SOCK))
    req = {"op": "send", "data": base64.b64encode(cmd.encode() + b"\r").decode(), "secs": cap}
    s.sendall((json.dumps(req) + "\n").encode())
    buf = b""
    while b"\n" not in buf:
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    s.close()
    rep = json.loads(buf)
    if not rep.get("ok"):
        raise RuntimeError(f"daemon: {rep}")
    return base64.b64decode(rep.get("captured", ""))


def i2c_read(dev: int, reg: int) -> int | None:
    for attempt in (1, 2):
        out = send(f"rtk i2c read {dev} {reg}")
        m = DATA_RE.search(out)
        if m:
            return int(m.group(1), 16)
        if b"FAIL" in out:
            log.info("dev %d reg %d: %s", dev, reg, out.decode(errors="replace").strip().splitlines()[-2:])
            return None
        log.info("dev %d reg %d: no data within %.1fs (attempt %d)", dev, reg, REPLY_CAP_S, attempt)
    return None


def read_block(dev: int, n: int) -> bytes | None:
    """Batched `cmd; cmd; …` lines. Stock U-Boot rejects lines >256 chars and the UART drops input
    past ~240 (no flow control), so batches stay under LINE_MAX; reply count is checked per batch."""
    out = bytearray()
    reg = 0
    while reg < n:
        cmds = []
        while reg + len(cmds) < n:
            nxt = cmds + [f"rtk i2c read {dev} {reg + len(cmds)}"]
            if len("; ".join(nxt)) > LINE_MAX:
                break
            cmds = nxt
        for attempt in (1, 2):
            vals = [int(v, 16) for v in DATA_RE.findall(send("; ".join(cmds), BATCH_CAP_S))]
            if len(vals) == len(cmds):
                break
            log.info("dev %d regs %d-%d: %d/%d replies (attempt %d)",
                     dev, reg, reg + len(cmds) - 1, len(vals), len(cmds), attempt)
        else:
            return None
        out += bytes(vals)
        reg += len(cmds)
    return bytes(out)


def text(b: bytes) -> str:
    return b.decode("ascii", errors="replace").strip()


def decode_a0(a0: bytes) -> None:
    log.info("  identifier 0x%02x  connector 0x%02x  encoding 0x%02x", a0[0], a0[2], a0[11])
    log.info("  compliance %s", a0[3:11].hex())
    log.info("  bitrate nominal %d00 Mbd", a0[12])
    log.info("  vendor '%s'  PN '%s'  rev '%s'", text(a0[20:36]), text(a0[40:56]), text(a0[56:60]))
    log.info("  OUI %s  wavelength %d nm", a0[37:40].hex(":"), int.from_bytes(a0[60:62], "big"))
    sn = text(a0[68:84])
    log.info("  SN %s  date '%s'", sn, text(a0[84:92]))
    dt = a0[92]
    log.info("  diag type 0x%02x: DDM %s, %s calibration, addr-change %s",
             dt, "yes" if dt & 0x40 else "no", "external" if dt & 0x10 else "internal",
             "required" if dt & 0x04 else "no")
    log.info("  enhanced 0x%02x  SFF-8472 compliance 0x%02x", a0[93], a0[94])
    cc = sum(a0[0:63]) & 0xFF
    log.info("  CC_BASE %s (calc 0x%02x, stored 0x%02x)", "ok" if cc == a0[63] else "BAD", cc, a0[63])


def dbm(mw: float) -> str:
    return f"{10 * math.log10(mw):.2f} dBm" if mw > 0 else "-inf dBm"


def decode_a2(a2: bytes) -> None:
    u16 = lambda o: int.from_bytes(a2[o:o + 2], "big")  # noqa: E731
    t = int.from_bytes(a2[96:98], "big", signed=True) / 256
    vcc = u16(98) * 100e-6
    bias = u16(100) * 2e-3
    tx = u16(102) * 1e-4
    rx = u16(104) * 1e-4
    log.info("  temp %.2f C  Vcc %.4f V  bias %.3f mA", t, vcc, bias)
    log.info("  TX %.4f mW (%s)  RX %.4f mW (%s)", tx, dbm(tx), rx, dbm(rx))
    log.info("  status/control 0x%02x  alarms %s  warnings %s", a2[110], a2[112:114].hex() if len(a2) > 113 else "-",
             a2[116:118].hex() if len(a2) > 117 else "-")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="op", required=True)
    sub.add_parser("probe")
    d = sub.add_parser("dump")
    d.add_argument("--dev", type=int, required=True)
    g = sub.add_parser("ddm")
    g.add_argument("--dev", type=int, required=True, help="cage index 0-7 (for file naming)")
    g.add_argument("--intf", type=int, required=True)
    g.add_argument("--sda", type=int, required=True)
    g.add_argument("--chip", type=lambda s: int(s, 0), default=0x51)
    g.add_argument("--freq", type=int, default=0, help="0-3; 0 assumed 100 kHz = SFF-8472 base rate")
    g.add_argument("--count", type=int, default=120)
    args = ap.parse_args()

    Path("tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.StreamHandler(sys.stdout),
                                  logging.FileHandler("tmp/logs/st1008_sfp_ddm.log")])
    log.info("=== %s %s", time.strftime("%Y-%m-%dT%H:%M:%S%z"), " ".join(sys.argv[1:]))
    out_dir = Path("private/sfp") / time.strftime("%Y%m%d-%H%M%S")

    if args.op == "probe":
        for dev in range(8):
            v = i2c_read(dev, 0)
            log.info("cage %d (dev %d): byte0 %s", dev + 1, dev,
                     "absent/fail" if v is None else f"0x{v:02x}{' SFP' if v == 3 else ''}")
    elif args.op == "dump":
        a0 = read_block(args.dev, 256)
        if a0 is None:
            sys.exit(1)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"cage{args.dev + 1}-a0.bin").write_bytes(a0)
        log.info("cage %d A0 -> %s", args.dev + 1, out_dir / f"cage{args.dev + 1}-a0.bin")
        decode_a0(a0)
    elif args.op == "ddm":
        init = f"rtk i2c init hw {SCRATCH_DEV} {args.intf} {args.sda} 8 0x{args.chip:x} {args.freq} 0"
        log.info("%s -> %s", init, send(init, 1.0).decode(errors="replace").strip().splitlines()[1:])
        blk = read_block(SCRATCH_DEV, args.count)
        if blk is None:
            sys.exit(1)
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"cage{args.dev + 1}-chip{args.chip:02x}-intf{args.intf}-sda{args.sda}.bin"
        (out_dir / name).write_bytes(blk)
        log.info("-> %s ; first 16: %s", out_dir / name, blk[:16].hex(" "))
        if args.chip == 0x51 and len(blk) >= 106:
            decode_a2(blk)


if __name__ == "__main__":
    main()
