#!/usr/bin/env python3
"""Find the RTL9300 NIC ring-size tables (txRingIdSize[2] + rxRingIdSize[32]) in vendor ELF binaries.

- SDK layout (nic_rtl9300.c): rx[32] and tx[2] uint32 arrays; the compiler may place either first.
- Scans every PROGBITS data section for 34 consecutive big-endian words in 1..4096 and prints them.
- Usage: ./scripts/vendor_nic_values.py <elf> [...]   Log: tmp/logs/vendor_nic_values.log
"""
import struct
import sys
import time
from pathlib import Path

from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/vendor_nic_values.log"
RUN = 34


def scan(path, out):
    with open(path, "rb") as fh:
        elf = ELFFile(fh)
        for sec in elf.iter_sections():
            if sec["sh_type"] != "SHT_PROGBITS" or sec["sh_flags"] & 0x4:  # skip code (SHF_EXECINSTR)
                continue
            data = sec.data()
            words = struct.unpack(f">{len(data) // 4}I", data[: len(data) // 4 * 4])
            i = 0
            while i + RUN <= len(words):
                if all(1 <= w <= 4096 for w in words[i:i + RUN]):
                    j = i + RUN
                    while j < len(words) and 1 <= words[j] <= 4096:
                        j += 1
                    out(f"{path.name} {sec.name}+0x{i * 4:x} (addr 0x{sec['sh_addr'] + i * 4:x}) "
                        f"n={j - i}: {list(words[i:j])}")
                    i = j
                else:
                    i += 1


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as lf:
        def out(msg):
            line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
            print(line)
            lf.write(line + "\n")
        for p in sys.argv[1:]:
            out(f"scan {p}")
            scan(Path(p), out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
