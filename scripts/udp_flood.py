#!/usr/bin/env python3
"""udp_flood — send UDP to HOST:9 (discard) as fast as one Python process can; CPU-port load on a unit (#186).
Usage: udp_flood.py HOST [--secs 15] [--len 64]. Log: tmp/logs/udp_flood.log"""
import argparse
import socket
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("host")
ap.add_argument("--secs", type=float, default=15)
ap.add_argument("--len", type=int, default=64)
a = ap.parse_args()
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
buf = b"\x01" * a.len
end = time.monotonic() + a.secs  # run length chosen by the caller
n = 0
while time.monotonic() < end:
    for _ in range(1000):
        s.sendto(buf, (a.host, 9))
    n += 1000
log = Path(__file__).resolve().parent.parent / "tmp/logs/udp_flood.log"
log.parent.mkdir(parents=True, exist_ok=True)
msg = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a.host} len {a.len}: {n} packets in {a.secs} s = {n / a.secs:.0f} pps"
with log.open("a") as f:
    f.write(msg + "\n")
print(msg)
