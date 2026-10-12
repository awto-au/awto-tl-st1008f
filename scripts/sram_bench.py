#!/usr/bin/env python3
"""sram_bench — on-chip SRAM vs DDR latency under the mainline kernel (#103).

- Needs the initramfs shell (`./dev.py ramload mainline-kernel`), kernel with 300-21/300-22
  (CONFIG_SRAM + CONFIG_ST1008F_SRAM_BENCH, DT sram@1f000000). Read-only on the board.
- Reads /sys/kernel/debug/st1008f_sram_bench --reps times: per region (sram, ddr) and test
  (uc_rd, c_miss, c_hit, uc_wr) ns per access, min/max of 5 inside the kernel.
- Logs dmesg sram lines + /proc/iomem SRAM entry first (mapping evidence).
- PASS: every test line present for both regions on every pass (no refusal).
- Log: tmp/logs/sram_bench.log
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import st1008_ramload as rl  # noqa: E402

rl.LOG = Path(__file__).resolve().parent.parent / "tmp/logs/sram_bench.log"
P = r"st1008f-linux # "
FILE = "/sys/kernel/debug/st1008f_sram_bench"
TESTS = ("uc_rd", "c_miss", "c_hit", "uc_wr")
LINE = re.compile(r"sram_bench: (sram|ddr)\s+(\w+)\s+min ([\d.]+) ns max ([\d.]+) ns \(([\d.]+) cpu cycles\)")
# One read: 40 runs x 512 accesses at <=1 us (uncached DDR worst case) ~20 ms + ~1 KB at 115200
# baud ~90 ms = 0.11 s; cap 0.5 s = shortest console round trip the other flows use. Expiry = FAIL.
CAP_READ = 0.5


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reps", type=int, default=3, help="reads of the debugfs file (default 3)")
    a = ap.parse_args()
    con = rl.Console()
    con.note("interactive-begin")
    passes = []
    try:
        con.run("", P, 2, "shell prompt")
        con.run("dmesg -n 1", P, 1, "console loglevel 1")
        _, out = con.run("dmesg | grep -i sram; grep -i sram /proc/iomem", P, 2, "sram dmesg + iomem")
        rl.log("mapping: " + " / ".join(l.strip() for l in out.splitlines() if "sram" in l.lower()
                                         and "grep" not in l))
        for i in range(a.reps):
            _, out = con.run(f"cat {FILE}", rf"(?s)sram_bench: .*{P}", CAP_READ, f"bench pass {i + 1}")
            for l in out.splitlines():
                if "sram_bench:" in l:
                    rl.log(l.strip())
            passes.append({(m[1], m[2]): m for m in LINE.finditer(out)})
    finally:
        con.note("interactive-end")
    ok = all(len(p) == 2 * len(TESTS) for p in passes) and bool(passes)
    if ok:
        for reg in ("sram", "ddr"):
            rl.log(f"{reg}: " + ", ".join(f"{t} {min(float(p[(reg, t)][3]) for p in passes):.1f} ns"
                                          for t in TESTS))
    rl.log(f"{'PASS' if ok else 'FAIL'}: {len(passes)} passes, all {2 * len(TESTS)} lines each: {ok}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
