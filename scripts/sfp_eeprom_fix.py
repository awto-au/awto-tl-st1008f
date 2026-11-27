#!/usr/bin/env python3
"""sfp_eeprom_fix — repair the space-padded A0h EEPROM of Cisco-clone GLC-SX-MM modules in sw2 cages (owner OK 2026-11-21).

Per module, via ssh + i2c-tools on sw2 (SMBus byte access, no bus scan, known cage buses only):
- find the bus by serial number (reads bytes 68-83 on the candidate buses 2-5)
- dump 256 B to private/sfp-eeprom/<SN>-before.hex; refuse unless vendor CISCO-FINISAR, PN GLC-SX-MM, CC_BASE/CC_EXT valid
- write connector (byte 2) = 0x07 first, then 0x20 padding -> 0x00 (3-5, 7-10, 13-19, 37-39, 64-67), byte 36 = 0x00,
  byte 11 = 0x01, byte 12 = 0x0d; byte 6 and the ASCII fields stay; CC_BASE (63) and CC_EXT (95) last
- read every byte back; on any mismatch restore the whole dump. After-dump -> <SN>-after.hex
- Recipe from the US-48 session (scripts/sfp_eeprom_fix.py, awto-au/awto-unifi-us48 branch wip/sfp-1g-unit0).
- Log: tmp/logs/sfp_eeprom_fix.log. Caps: ssh 60 s per dump, 10 s per byte write (24C02 page write 5 ms).

Usage: python3 scripts/sfp_eeprom_fix.py --sn H33A655 [--sn ...] [--dry-run] [--ip IP]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sfp_eeprom_fix.log"
OUT = ROOT / "private/sfp-eeprom"
BUSES = (2, 3, 4, 5)  # cage SMBus candidates (sw2 lan3..lan6); verified by serial number
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
PAD_RANGES = [(3, 5), (7, 10), (13, 19), (37, 39), (64, 67)]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(ip: str, cmd: str, cap: float = 60) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=cap)
    return r.stdout + r.stderr


def dump(ip: str, bus: int) -> bytes | None:
    out = sh(ip, f"i2cdump -y {bus} 0x50 b 2>&1")
    rows = {}
    for ln in out.splitlines():
        m = re.match(r"^([0-9a-f]{2}): ((?:[0-9a-f]{2} ){16})", ln)
        if m:
            rows[int(m.group(1), 16)] = bytes(int(x, 16) for x in m.group(2).split())
    if sorted(rows) != list(range(0, 256, 16)):
        return None
    return b"".join(rows[k] for k in sorted(rows))


def hexfile(path: Path, buf: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"0x{o:04x}: {' '.join(f'{b:02x}' for b in buf[o:o + 16])}\n" for o in range(0, len(buf), 16)))


def ascii_(buf: bytes, a: int, n: int) -> str:
    return buf[a:a + n].decode("ascii", "replace").strip()


def find_bus(ip: str, sn: str) -> int | None:
    for b in BUSES:
        out = sh(ip, "for o in " + " ".join(str(o) for o in range(68, 84)) + f"; do i2cget -y {b} 0x50 $o b 2>/dev/null; done")
        try:
            text = "".join(chr(int(x, 16)) for x in out.split())
        except ValueError:
            continue
        if text.strip() == sn:
            return b
    return None


def plan(buf: bytes) -> dict[int, int]:
    new = bytearray(buf)
    new[2] = 0x07
    for a, b in PAD_RANGES:
        for i in range(a, b + 1):
            if new[i] == 0x20:
                new[i] = 0x00
    new[36] = 0x00
    new[11] = 0x01
    new[12] = 0x0D
    new[63] = sum(new[0:63]) & 0xFF
    new[95] = sum(new[64:95]) & 0xFF
    order = [2] + [i for i in range(256) if i not in (2, 63, 95) and new[i] != buf[i]] + [63, 95]
    return {i: new[i] for i in order if new[i] != buf[i]}


def write_bytes(ip: str, bus: int, writes: dict[int, int]) -> None:
    for off, val in writes.items():
        out = sh(ip, f"i2cset -y {bus} 0x50 {off} 0x{val:02x} b 2>&1", 10)
        if out.strip():
            log(f"  write [{off}] error: {out.strip()}")
        time.sleep(0.02)  # EEPROM write cycle 5 ms (24C02), x4 margin is NOT added: spec value -> 20 ms covers ssh round trip anyway


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--sn", action="append", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    rc = 0
    for sn in a.sn:
        bus = find_bus(a.ip, sn)
        if bus is None:
            log(f"{sn}: FAIL no cage bus has this serial")
            rc = 1
            continue
        before = dump(a.ip, bus)
        if before is None:
            log(f"{sn}: FAIL dump on bus {bus} incomplete")
            rc = 1
            continue
        hexfile(OUT / f"{sn}-before.hex", before)
        vend, pn = ascii_(before, 20, 16), ascii_(before, 40, 16)
        cb, ce = sum(before[0:63]) & 0xFF == before[63], sum(before[64:95]) & 0xFF == before[95]
        log(f"{sn}: bus {bus} vendor={vend!r} pn={pn!r} cc_base={cb} cc_ext={ce}")
        if vend != "CISCO-FINISAR" or pn != "GLC-SX-MM" or not (cb and ce):
            log(f"{sn}: REFUSED (vendor/PN/checksum check failed)")
            rc = 1
            continue
        writes = plan(before)
        log(f"{sn}: {len(writes)} byte writes: " + " ".join(f"[{k}]=0x{v:02x}" for k, v in writes.items()))
        if a.dry_run or not writes:
            continue
        write_bytes(a.ip, bus, writes)
        after = dump(a.ip, bus)
        want = bytearray(before)
        for k, v in writes.items():
            want[k] = v
        if after is None or bytes(after) != bytes(want):
            bad = [i for i in range(256) if after is None or after[i] != want[i]]
            log(f"{sn}: MISMATCH at {bad[:20]}; restoring the dump")
            write_bytes(a.ip, bus, {i: before[i] for i in range(256) if after is None or after[i] != before[i]})
            rc = 1
            continue
        hexfile(OUT / f"{sn}-after.hex", after)
        log(f"{sn}: OK, read back matches; dumps in {OUT}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
