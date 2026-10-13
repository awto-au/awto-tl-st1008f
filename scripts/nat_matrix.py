#!/usr/bin/env python3
"""nat_matrix — kernel NAT path: clocks x on-chip SRAM, one nic-bench run per cell (#65 #71 #103).

- Clocks: base = `clocks fast` (CPU 1000, DDR 650) | picks = + `turbo cpu=1375,ddr=662,lx=306,sram=500`.
- SRAM: off = kernel built `--skip 300-21` (OpenWrt default: no SRAM in Linux) | mapped = 300-21, unused |
  rings = mapped + `rtl838x_eth.sram_rings=3` (300-25: NIC RX/TX rings in SRAM; not in the default set).
- Per cell: (build if the variant changes) -> `nic-bench boot` -> `nic-bench run --tag nat-<cell> --runs 1`
  [-> `nat-perf --tag <cell>` with --perf]. Then `nic-bench table` of every cell.
- Log: tmp/logs/nat_matrix.log
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/nat_matrix.log"
PICKS = "turbo cpu=1375,ddr=662,lx=306,sram=500"
CELLS = [  # (name, kernel variant, ramload extra)
    ("off-base", "skip21", ""), ("off-picks", "skip21", f"--pre|{PICKS}"),
    ("mapped-base", "full", ""), ("mapped-picks", "full", f"--pre|{PICKS}"),
    # rings: NIC descriptor fetch from SRAM fails (RX or TX alone, docs/NAT.md); kept for re-tests
    ("rings-base", "full", "--bootargs|rtl838x_eth.sram_rings=3"),
]
DEFAULT = ["off-base", "off-picks", "mapped-base", "mapped-picks"]
BUILD_S = 1200  # incremental kernel build after a patch-set change ~1-3 min; full rebuild ~12 min; x1.25 + slack
BOOT_S = 360    # nic-bench boot: ramload ~45 s + port-up + SSH + nat-bench setup (its own 300 s ramload cap)
RUN_S = 600     # 5 tests x (10 s + setup) ~1.5 min; x1.25 + qdisc reads; 600 s names a stuck iperf
PERF_S = 180    # push + 10 s load + report


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def dev(args: list[str], cap: float, env: dict | None = None) -> int:
    r = subprocess.run([sys.executable, str(ROOT / "dev.py"), *args], timeout=cap,
                       env={**os.environ, **(env or {})}, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", nargs="*", help="cell names")
    ap.add_argument("--perf", action="store_true", help="nat-perf profile per cell")
    a = ap.parse_args()
    built = None
    done = []
    for name, variant, extra in CELLS:
        if name not in (a.only or DEFAULT):
            continue
        if variant != built:
            rc = dev(["build-kernel"] + (["--skip", "300-21"] if variant == "skip21" else []), BUILD_S)
            log(f"build {variant}: rc {rc}")
            if rc:
                return rc
            built = variant
        rc = dev(["nic-bench", "boot"], BOOT_S, {"ST1008F_RAMLOAD_EXTRA": extra})
        if rc:
            log(f"[{name}] boot failed rc {rc}; skipped")
            continue
        rc = dev(["nic-bench", "run", "--tag", f"nat-{name}", "--runs", "1"], RUN_S)
        log(f"[{name}] nic-bench rc {rc}")
        if a.perf:
            log(f"[{name}] nat-perf rc {dev(['nat-perf', '--tag', name], PERF_S)}")
        done.append(f"nat-{name}")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/nic_path_bench.py"), "table", *done],
                       capture_output=True, text=True, timeout=30)
    for ln in r.stdout.splitlines():
        log(ln.split(" ", 1)[1] if ln[:4].isdigit() else ln)
    return 0


if __name__ == "__main__":
    sys.exit(main())
