#!/usr/bin/env python3
"""sds_ssh — run `st1008f-sds` on a switch over ssh (#136). Reads by default; log tmp/logs/sds_ssh.log.

Usage: sds_ssh.py [--ip IP] [--force] rd|wr|rxeq|readapt|link|symerr|idle|cal SDS [args]
- Default IP: sw2 (BENCH_IP). sw1 only on owner OK (its kernel may lack the 300-35 debugfs).
- SerDes N = lan(N-1). `wr`, `readapt`, `cal` change state: refused unless --force (the wrapper also refuses on a port with carrier).
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/sds_ssh.log"
WRITES = {"wr", "readapt", "cal"}
CAP_S = 20  # cal runs the full RX calibration: up to 3 attempts, seconds each


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("cmd")
    ap.add_argument("args", nargs="*")
    a = ap.parse_args()
    if a.cmd in WRITES and not a.force:
        sys.exit(f"{a.cmd} changes SerDes state: pass --force")
    ip = a.ip or BENCH_IP
    remote = " ".join(["st1008f-sds", *(["--force"] if a.force else []), a.cmd, *a.args])
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR", f"root@{ip}", remote],
                       capture_output=True, text=True, timeout=CAP_S)
    out = (r.stdout + r.stderr).strip()
    print(out)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {ip} {remote} rc={r.returncode}\n{out}\n")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
