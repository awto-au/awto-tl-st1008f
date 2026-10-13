#!/usr/bin/env python3
"""nat_perf — perf profile of the NAT forwarding path under a nic-bench load (#67 #65).

- Board: `./dev.py nic-bench boot` first (mainline initramfs, nat-ft, SSH up).
- Pushes tmp/perf/perf (`scripts/build_perf.py`) to /tmp/perf over SSH, starts one nic-bench workload
  (--test, nat_bench.py run) and, once iperf3 is past its omit time, `perf record -e cpu-clock -a` for --secs
  (hrtimer sampling: the 34K PMU overflow IRQ gives no samples here, #67).
- On the board: `perf report --sort sym` (kernel symbols from /proc/kallsyms) -> top symbols.
  No sampling IRQ -> falls back to `perf stat -a` counters.
- Output: tmp/logs/nat_perf-<tag>.txt (report), summary in tmp/logs/nat_perf.log
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/nat_perf.log"
PERF = ROOT / "tmp/perf/perf"
sys.path.insert(0, str(ROOT / "scripts"))
import nat_bench  # noqa: E402
from nic_path_bench import SUITE  # noqa: E402

PUSH_S = 20      # 3.3 MB over 1G SSH: < 1 s + SSH setup; 20 s names a stuck link
OMIT_S = 4       # iperf3 setup + 2 s omit (nat_bench) before sampling starts
REPORT_S = 60    # perf report on the board: ~10k samples x kallsyms lookup, seconds at 1 GHz; x1.25 + slack


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def push() -> None:
    with PERF.open("rb") as fh:
        r = subprocess.run(nat_bench.SSH + ["cat > /tmp/perf && chmod +x /tmp/perf && /tmp/perf --version"],
                           stdin=fh, capture_output=True, text=True, timeout=PUSH_S)
    if r.returncode:
        raise SystemExit(f"perf push failed: {r.stderr.strip()}")
    log(f"pushed {PERF.stat().st_size} B: {r.stdout.strip()}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", required=True, help="label for the output, e.g. picks-ddr")
    ap.add_argument("--test", default="udp64-100", choices=[s[0] for s in SUITE])
    ap.add_argument("--secs", type=int, default=5, help="perf record duration (inside the 10 s load)")
    ap.add_argument("--freq", type=int, default=2000, help="perf record -F")
    ap.add_argument("--no-push", action="store_true")
    a = ap.parse_args()
    if not PERF.exists():
        log("FAIL: tmp/perf/perf missing (python3 scripts/build_perf.py)")
        return 1
    if not a.no_push:
        push()
    args = dict(SUITE)[a.test]
    load = subprocess.Popen([sys.executable, str(ROOT / "scripts/nat_bench.py"), "run", "--label",
                             f"perf-{a.test}", *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            env=dict(os.environ, NAT_BENCH_TAG=f"perf-{a.tag}"))
    time.sleep(OMIT_S)
    rec = nat_bench.sw(f"/tmp/perf record -e cpu-clock -a -F {a.freq} -o /tmp/perf.data -- sleep {a.secs} 2>&1",
                       check=False, tmo=a.secs + 15)
    out, _ = load.communicate(timeout=90)  # iperf3 10 s + setup; 90 s as nic_path_bench
    res = [ln.split("RESULT", 1)[1].strip() for ln in out.splitlines() if "RESULT" in ln]
    log(f"[{a.tag}] load {a.test}: {res[0] if res else out[-200:]}")
    log(f"[{a.tag}] record: {' | '.join(rec.strip().splitlines()[-3:])}")
    if "sample" in rec and "Error" not in rec:
        rep = nat_bench.sw("/tmp/perf report -i /tmp/perf.data --stdio --sort sym --no-children "
                           "--percent-limit 0.5 2>&1 | grep -v '^$'", check=False, tmo=REPORT_S)
    else:
        log(f"[{a.tag}] no sampling: perf stat fallback")
        rep = nat_bench.sw(f"/tmp/perf stat -a -- sleep {a.secs} 2>&1", check=False, tmo=a.secs + 15)
    dst = ROOT / f"tmp/logs/nat_perf-{a.tag}.txt"
    dst.write_text(f"# {a.tag} {a.test} {res[0] if res else ''}\n{rec}\n{rep}")
    top = [ln.strip() for ln in rep.splitlines() if "%" in ln and not ln.startswith("#")][:15]
    for ln in top:
        log(f"[{a.tag}]   {ln}")
    log(f"[{a.tag}] report -> {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
