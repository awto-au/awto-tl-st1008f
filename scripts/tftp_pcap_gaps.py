#!/usr/bin/env python3
"""tftp_pcap_gaps — where a TFTP transfer to the switch stalled: lost DATA (board RX) or lost ACK (board TX).

- Input: a host pcap taken with `tcpdump -i any ... host <switch>` (needs In/Out direction, `-i any`).
- For every gap > GAP_S between packets of one transfer, prints the packets around it with opcode + block.
  Lost DATA n: board re-ACKs n-1 after its timeout. Lost ACK n: ACK n first appears after the gap.
- Log: tmp/logs/tftp_pcap_gaps.log. Usage: tftp_pcap_gaps.py <pcap> [--gap S]
"""

import argparse
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/tftp_pcap_gaps.log"
GAP_S = 1.0  # TFTP lock-step on a LAN: ms per block; a 1 s gap is a timeout (U-Boot: 5 s)
OPS = {1: "RRQ", 2: "WRQ", 3: "DATA", 4: "ACK", 5: "ERR", 6: "OACK"}


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def packets(pcap: str):
    # local file decode; 30 s names a stuck tcpdump
    out = subprocess.run(["tcpdump", "-nn", "-tt", "-x", "-r", pcap], capture_output=True, text=True,
                         timeout=30).stdout
    cur = None
    for line in out.splitlines():
        if not line.startswith("\t"):
            if cur:
                yield cur
            m = re.match(r"(\d+\.\d+)\s+\S+\s+(In|Out)\s+IP (\S+) > (\S+): UDP", line)
            cur = [float(m.group(1)), m.group(2), m.group(3), m.group(4), ""] if m else None
        elif cur:
            cur[4] += "".join(line.split(":", 1)[1].split())
    if cur:
        yield cur


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pcap")
    ap.add_argument("--gap", type=float, default=GAP_S)
    a = ap.parse_args()
    prev = None
    gaps = {"lost DATA (board RX)": 0, "lost ACK (board TX)": 0, "other": 0}
    for t, d, src, dst, hexs in packets(a.pcap):
        udp = hexs[56:] if hexs.startswith("45") else hexs[2 * 44:]  # IPv4 20 B + UDP 8 B
        op, blk = int(udp[0:4], 16), int(udp[4:8], 16)
        cur = (t, d, OPS.get(op, op), blk)
        if prev and t - prev[0] > a.gap:
            if prev[2] == "DATA" and cur[2] == "ACK" and cur[3] == prev[3] - 1:
                kind = "lost DATA (board RX)"
            elif prev[2] == "DATA" and cur[2] == "ACK" and cur[3] == prev[3]:
                kind = "lost ACK (board TX)"
            else:
                kind = "other"
            gaps[kind] += 1
            log(f"gap {t - prev[0]:.2f} s: {prev[1]} {prev[2]} {prev[3]} -> {d} {cur[2]} {cur[3]}: {kind}")
        prev = cur
    log(f"gaps: {gaps}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
