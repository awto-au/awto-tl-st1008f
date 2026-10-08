#!/usr/bin/env python3
"""st1008_mtd_backup — copy every MTD partition off a RAM-booted OpenWrt TL-ST1008F.

Read-only on the device (`cat /dev/mtdN`). Per partition: pull over SSH, sha256 on
device and host, size vs /proc/mtd. Also writes full-flash.bin (concatenation, in
mtd order) when the partitions cover the chip contiguously.

Usage:
    scripts/st1008_mtd_backup.py [--host <switch-ip>] [--out DIR]

Default --host is the OpenWrt initramfs LAN address. Default --out is
private/mtd-backup-<YYYYMMDD-HHMMSS>/. Log: tmp/logs/st1008_mtd_backup.log
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/st1008_mtd_backup.log"
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
            # LAN host, sub-ms RTT; 5 s is generous for TCP+key exchange.
            "-o", "ConnectTimeout=5"]
FLASH_SIZE = 0x2000000  # 32 MiB SPI NOR (docs/hardware.md)
_log_fh = None


def log(msg: str):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    _log_fh.write(line + "\n")
    _log_fh.flush()


def ssh(host: str, cmd: str, timeout: float) -> bytes:
    return subprocess.run(["ssh", *SSH_OPTS, f"root@{host}", cmd], check=True,
                          capture_output=True, timeout=timeout).stdout


def main() -> int:
    global _log_fh
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="192.168.1.1")
    ap.add_argument("--out", type=Path,
                    default=ROOT / "private" / f"mtd-backup-{time.strftime('%Y%m%d-%H%M%S')}")
    args = ap.parse_args()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    _log_fh = LOG.open("a")
    args.out.mkdir(parents=True, exist_ok=True)
    log(f"host={args.host} out={args.out}")

    proc_mtd = ssh(args.host, "cat /proc/mtd", timeout=10).decode()
    (args.out / "proc_mtd.txt").write_text(proc_mtd)
    parts = [(int(n), int(sz, 16), name) for n, sz, name in
             re.findall(r'^mtd(\d+): ([0-9a-f]+) [0-9a-f]+ "([^"]+)"', proc_mtd, re.M)]
    if not parts:
        log("no partitions parsed from /proc/mtd")
        return 1

    ok = True
    sums = []
    for n, size, name in parts:
        dst = args.out / f"mtd{n}-{name}.bin"
        # NOR read over 10G LAN is SPI-bound; ~2 MB/s floor -> size/2e6 s, x1.25, min 10 s.
        limit = max(10.0, size / 2e6 * 1.25)
        t0 = time.monotonic()
        try:
            data = ssh(args.host, f"cat /dev/mtd{n}ro", timeout=limit)
            dev_sum = ssh(args.host, f"sha256sum /dev/mtd{n}ro", timeout=limit).split()[0].decode()
        except subprocess.TimeoutExpired:
            log(f"mtd{n} {name}: TIMEOUT after {time.monotonic() - t0:.1f}s (limit {limit:.1f}s)")
            ok = False
            continue
        dst.write_bytes(data)
        host_sum = hashlib.sha256(data).hexdigest()
        good = len(data) == size and host_sum == dev_sum
        ok &= good
        sums.append(f"{host_sum}  {dst.name}")
        log(f"mtd{n} {name}: {len(data):#x}/{size:#x} bytes "
            f"{time.monotonic() - t0:.1f}s sha256 {host_sum} "
            f"{'OK' if good else f'MISMATCH device={dev_sum}'}")

    total = sum(sz for _, sz, _ in parts)
    if ok and total == FLASH_SIZE:
        full = b"".join((args.out / f"mtd{n}-{name}.bin").read_bytes() for n, _, name in parts)
        (args.out / "full-flash.bin").write_bytes(full)
        sums.append(f"{hashlib.sha256(full).hexdigest()}  full-flash.bin")
        log(f"full-flash.bin {len(full):#x} bytes")
    else:
        log(f"full-flash.bin skipped: ok={ok} total={total:#x} expected {FLASH_SIZE:#x}")

    (args.out / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    log("DONE ok" if ok else "DONE with errors")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
