#!/usr/bin/env python3
"""xfer_check — push a known file into a switch's /tmp N times over ssh, md5 each copy, locate flipped bytes (#186: one bit flip seen in an 11 MB image pushed to sw1).
- Per round: ssh `cat > /tmp/xc.bin` (CPU RX path, TCP), `md5sum`; on mismatch pull the file back and diff (offset, expected, got).
- A round that gets no answer in CMD_S s stops the run (unit crashed). Log: tmp/logs/xfer_check_<ip>.log
Usage: python3 scripts/xfer_check.py IP [--rounds 8] [--size-mb 8]
"""
import argparse
import hashlib
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
CMD_S = 60  # 8 MB push measured ~4 s on sw2 (flash tool, 2026-11-20); x15 for a loaded box


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ip")
    ap.add_argument("--rounds", type=int, default=8)
    ap.add_argument("--size-mb", type=int, default=8)
    a = ap.parse_args()
    log = (ROOT / f"tmp/logs/xfer_check_{a.ip}.log").open("a")

    def say(m):
        line = f"{time.strftime('%H:%M:%S')} {a.ip} {m}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    data = os.urandom(a.size_mb << 20)
    want = hashlib.md5(data).hexdigest()
    bad = 0
    for i in range(1, a.rounds + 1):
        try:
            subprocess.run([*SSH, f"root@{a.ip}", "cat > /tmp/xc.bin"], input=data, capture_output=True, timeout=CMD_S, check=True)
            got = subprocess.run([*SSH, f"root@{a.ip}", "md5sum /tmp/xc.bin"], capture_output=True, text=True, timeout=CMD_S, check=True).stdout.split()[0]
        except (subprocess.SubprocessError, IndexError) as e:
            say(f"round {i}: FAILED ({type(e).__name__}): unit crashed or unreachable")
            return 2
        if got == want:
            say(f"round {i}: ok")
            continue
        bad += 1
        back = subprocess.run([*SSH, f"root@{a.ip}", "cat /tmp/xc.bin"], capture_output=True, timeout=CMD_S).stdout
        d = [k for k in range(min(len(back), len(data))) if back[k] != data[k]]
        say(f"round {i}: MISMATCH {len(d)} bytes (pulled back {len(back)} of {len(data)}): " +
            ", ".join(f"0x{k:x} {data[k]:02x}->{back[k]:02x}" for k in d[:8]))
    say(f"done: {bad} of {a.rounds} rounds corrupted")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
