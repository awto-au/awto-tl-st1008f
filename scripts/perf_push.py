#!/usr/bin/env python3
"""perf_push — copy perf (+ libs if dynamic) to a bench board, optionally run a command (#148). Works on OpenWrt and the plain kernel.

- Transport: `ssh "cat > file" < file` (the plain initramfs dropbear has no scp server; OpenWrt works too).
- Binary: `--perf-bin PATH`, else tmp/perf/perf (build_perf.py: static, no libs), else the OpenWrt build_dir perf
  (dynamic, musl: + libelf/libdw/libtraceevent/libz/libfts from staging_dir). Rebuild: `NO_RUST=1 NO_MYPY=1 make package/devel/perf/compile`.
- `perf_push.py [--ip A.B.C.D] [--dest /tmp] [-- <perf args>]` -> run with LD_LIBRARY_PATH=<dest>. Log tmp/logs/perf_push.log
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
LIBS = ("libelf.so.1", "libdw.so.1", "libtraceevent.so.1", "libz.so.1", "libfts.so.0")
SSH = ["-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def find_files(perf_bin):
    """(perf path, [lib paths]); libs only for the dynamic OpenWrt-built perf."""
    if perf_bin:
        return perf_bin, []
    if (ROOT / "tmp/perf/perf").exists():
        return str(ROOT / "tmp/perf/perf"), []
    bins = glob.glob(str(TREE / "build_dir/target-*/linux-realtek_rtl930x/linux-*/tools/perf-target-*/ipkg-*/perf/usr/bin/perf"))
    if not bins:
        return None, []
    lib = TREE / "staging_dir/target-mips_24kc_musl/usr/lib"
    return bins[0], [str(lib / n) for n in LIBS]


def push(ip, path, dest, mode):
    name = Path(path).name
    with open(path, "rb") as fh:  # libs are symlinks in staging_dir: open() follows them
        r = subprocess.run(["ssh", *SSH, f"root@{ip}", f"cat > {dest}/{name} && chmod {mode} {dest}/{name}"],
                           stdin=fh, capture_output=True, text=True,
                           timeout=60)  # ~6 MB binary + 3 libs over 1G LAN: seconds; dropbear cipher on MIPS is the limit
    return r.returncode, r.stderr.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("--dest", default="/tmp")
    ap.add_argument("--perf-bin", default=None)
    ap.add_argument("perf_args", nargs="*")
    a = ap.parse_args()
    perf, libs = find_files(a.perf_bin)
    if not perf:
        log("no perf: tmp/perf/perf (build_perf.py) or a built tmp/openwrt-build perf (see docstring)")
        return 1
    for f, mode in [(perf, "755")] + [(x, "644") for x in libs]:
        rc, err = push(a.ip, f, a.dest, mode)
        if rc:
            log(f"push {f} failed: {err}")
            return 1
    log(f"pushed {Path(perf).name} + {len(libs)} libs to {a.dest} on {a.ip} (run: LD_LIBRARY_PATH={a.dest} {a.dest}/perf)")
    if a.perf_args:
        r = subprocess.run(["ssh", *SSH, f"root@{a.ip}", f"LD_LIBRARY_PATH={a.dest} {a.dest}/perf " + " ".join(a.perf_args)],
                           capture_output=True, text=True, timeout=120)  # one short perf command
        log(r.stdout + r.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
