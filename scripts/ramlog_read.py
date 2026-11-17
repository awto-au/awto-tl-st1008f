#!/usr/bin/env python3
"""Read the pstore RAM console kept in the bootrec page (phys 0x0e000800, 2 KiB) over SSH (#120).

Layout: persistent_ram header (sig 'DBGC', start, size) then a ring of text.
Run on the booted slot a within ~60 s of boot; the log is written to tmp/logs/ramlog_read.log.
"""
import argparse
import struct
import subprocess
import sys
from pathlib import Path

BASE = 0x0E000800
SIZE = 0x800
SIG = 0x43474244  # 'DBGC'
ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/ramlog_read.log"


def read_words(ip: str) -> list[int]:
    # SSH ConnectTimeout 3 s: LAN answer is <1 ms; 512 devmem forks finish in ~2 s, limit 20 s
    cmd = f"a={BASE}; e={BASE + SIZE}; while [ $a -lt $e ]; do devmem $a 32; a=$((a+4)); done"
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", f"root@{ip}", cmd],
                       capture_output=True, text=True, timeout=20)
    if r.returncode:
        sys.exit(f"ssh rc={r.returncode}: {r.stderr.strip()}")
    return [int(x, 16) for x in r.stdout.split()]


def decode(words: list[int]) -> str:
    raw = b"".join(struct.pack(">I", w) for w in words)  # big-endian SoC: devmem word = memory order
    sig, start, size = struct.unpack_from(">III", raw, 0)
    if sig != SIG or size > SIZE - 12:
        return f"no ramoops header (sig {sig:#x} start {start:#x} size {size:#x}); raw text:\n" + \
            raw.decode("ascii", "replace")
    data = raw[12:12 + SIZE - 12]
    if size < len(data):  # ring not full yet: text is data[:size]
        text = data[:size]
    else:  # wrapped: oldest byte at `start`
        text = data[start:] + data[:start]
    return f"ramoops sig ok, start {start} size {size}\n" + text.decode("ascii", "replace")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ip", default="192.168.25.56")
    a = ap.parse_args()
    out = decode(read_words(a.ip))
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(out)
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
