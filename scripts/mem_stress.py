#!/usr/bin/env python3
"""mem_stress — fill-verify most of RAM from the mainline 7.3 initramfs shell (#27).

- Board at `st1008f-linux # ` (`./dev.py ramload uboot-mainline --then mainline-kernel`).
- Checks /proc/meminfo (MemTotal, HighTotal), then: tmpfs of MemFree - RESERVE_MB, a 16 MiB
  /dev/urandom seed, copies until full; md5 of every copy vs the seed, PASSES times.
- tmpfs pages are GFP_HIGHUSER_MOVABLE: highmem fills first, then lowmem; HighFree is logged.
- Fails on any md5 mismatch, a short fill, or Oops/BUG/oom in dmesg. Log: tmp/logs/mem_stress.log
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mem_stress.log"
sys.path.insert(0, str(ROOT / "scripts"))
from st1008_ramload import Console  # noqa: E402

P = r"st1008f-linux # "
SEED_MB = 16
RESERVE_MB = 48  # left for the kernel (lowmem slab, page tables, initramfs tools)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(con: Console, cmd: str, pattern: str, cap: float, what: str):
    """Linux tty echo of long lines carries line-wrap escapes, so no echo check (8250 FIFO, no loss seen)."""
    mark = con.size()
    con.send(cmd)
    return con.expect(pattern, cap, mark, what)


def meminfo(con: Console) -> dict[str, int]:
    _, out = sh(con, "grep -E 'Mem|High|Low' /proc/meminfo", P, 3, "meminfo")
    return {k: int(v) for k, v in re.findall(r"(\w+):\s+(\d+) kB", out)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--passes", type=int, default=2)
    ap.add_argument("--min-total-kb", type=int, default=480000, help="MemTotal floor (512 MiB minus kernel)")
    a = ap.parse_args()
    con = Console()
    con.run("dmesg -n 1", P, 3, "console loglevel 1")
    mi = meminfo(con)
    log(f"meminfo: MemTotal {mi.get('MemTotal')} kB, HighTotal {mi.get('HighTotal')} kB, "
        f"LowTotal {mi.get('LowTotal')} kB, MemFree {mi.get('MemFree')} kB")
    ok = mi.get("MemTotal", 0) >= a.min_total_kb
    size = (mi["MemFree"] // 1024 - RESERVE_MB) // SEED_MB * SEED_MB
    n = size // SEED_MB - 1  # seed takes one slot
    sh(con, f"mkdir -p /mnt/ms; mount -t tmpfs -o size={size}m tmpfs /mnt/ms; echo M-OK", r"M-OK\s", 3, "tmpfs")
    # 16 MiB urandom + md5: 1.0 s measured (#27); 3 s cap
    _, out = sh(con, f"dd if=/dev/urandom of=/mnt/ms/seed bs=1M count={SEED_MB} 2>&1; md5sum /mnt/ms/seed",
                     r"([0-9a-f]{32})\s+/mnt/ms/seed", 3, "seed")
    seed = re.search(r"([0-9a-f]{32})\s+/mnt/ms/seed", out).group(1)
    t0 = time.monotonic()
    # fill of ~430 MiB: 3.5 s measured (#27); 10 s cap
    _, out = sh(con, f"i=0; while [ $i -lt {n} ]; do cp /mnt/ms/seed /mnt/ms/c$i || break; i=$((i+1)); done;"
                     " echo FILL-DONE $i", r"FILL-DONE (\d+)", 10, "fill")
    filled = int(re.search(r"FILL-DONE (\d+)", out).group(1))
    mi2 = meminfo(con)
    log(f"fill: {filled}/{n} copies x {SEED_MB} MiB = {(filled + 1) * SEED_MB} MiB in {time.monotonic() - t0:.1f} s; "
        f"MemFree {mi2.get('MemFree')} kB, HighFree {mi2.get('HighFree')} kB")
    ok &= filled == n
    for p in range(1, a.passes + 1):
        t0 = time.monotonic()
        # md5sum of ~430 MiB at CPU 1 GHz: 11 s measured (#27); 20 s cap
        _, out = sh(con, f"md5sum /mnt/ms/c* | awk -v s={seed} '$1!=s{{b++}} END{{print \"VERIFY bad=\" b+0 \" n=\" NR}}'",
                         r"VERIFY bad=(\d+) n=(\d+)", 20, f"verify pass {p}")
        m = re.search(r"VERIFY bad=(\d+) n=(\d+)", out)
        bad, cnt = int(m.group(1)), int(m.group(2))
        log(f"verify pass {p}: {cnt} copies, {bad} bad, {time.monotonic() - t0:.1f} s")
        ok &= bad == 0 and cnt == filled
    sh(con, "umount /mnt/ms; echo U-OK", r"U-OK\s", 5, "umount")
    _, out = sh(con, "dmesg | grep -ciE 'oops|bug:|out of memory|oom-kill'", r"\n(\d+)\s", 3, "dmesg scan")
    errs = int(re.search(r"\n(\d+)\s", out).group(1))
    log(f"dmesg oops/bug/oom lines: {errs}")
    ok &= errs == 0
    log("RESULT " + ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
