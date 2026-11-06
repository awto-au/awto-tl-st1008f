#!/usr/bin/env python3
"""perf_push — copy the cross-built perf + its libs to sw2 /tmp/perf, optionally run a command (#148).

- perf is not an image package (apk rejects the linux-next version string); the binary comes from the build_dir.
- Rebuild needs `NO_RUST=1 NO_MYPY=1 make package/devel/perf/compile` in tmp/openwrt-build (host rustc/mypy leak in).
- `perf_push.py [--ip A.B.C.D] [-- <perf args>]`  -> run with LD_LIBRARY_PATH=/tmp/perf. Log tmp/logs/perf_push.log
"""
import argparse
import glob
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/perf_push.log"
TREE = ROOT / "tmp/openwrt-build"
SSH = ["-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("perf_args", nargs="*")
    a = ap.parse_args()
    bins = glob.glob(str(TREE / "build_dir/target-*/linux-realtek_rtl930x/linux-*/tools/perf-target-*/ipkg-*/perf/usr/bin/perf"))
    if not bins:
        log("no built perf under tmp/openwrt-build (see docstring)")
        return 1
    lib = TREE / "staging_dir/target-mips_24kc_musl/usr/lib"
    files = [bins[0]] + [str(p) for n in ("libelf.so.1", "libdw.so.1", "libtraceevent.so.1", "libz.so.1", "libfts.so.0") for p in [lib / n]]
    r = subprocess.run(["scp", "-O", *SSH, *files, f"root@{a.ip}:/tmp/"], capture_output=True, text=True,
                       timeout=60)  # ~6 MB binary + 3 libs over 1G LAN: seconds
    if r.returncode:
        log(f"scp failed: {r.stderr.strip()}")
        return 1
    log("pushed perf + libelf/libdw/libtraceevent/libz/libfts to /tmp on sw2 (run: LD_LIBRARY_PATH=/tmp /tmp/perf)")
    if a.perf_args:
        r = subprocess.run(["ssh", *SSH, f"root@{a.ip}", "LD_LIBRARY_PATH=/tmp /tmp/perf " + " ".join(a.perf_args)],
                           capture_output=True, text=True, timeout=120)  # one short perf command
        log(r.stdout + r.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
