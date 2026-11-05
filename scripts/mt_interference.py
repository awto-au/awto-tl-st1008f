#!/usr/bin/env python3
"""mt_interference — does a load on one VPE slow forwarding on the other, and by what path? (#65)

- Forwarding is confined to one VPE: threaded NAPI, the ring-0 thread pinned to VPE1, rxq `one`
  (all frames on ring 0), tx_by_cpu, noqueue. A synthetic probe (openwrt/selftest/st1008f-mtprobe.c)
  runs on VPE0 with a known memory pattern: spin (no memory) / small (L1) / chase (DRAM latency) /
  stream (DRAM bandwidth). Compare forwarding Mbit/s and the probe's own rate against each alone.
- Needs the nat-bench setup (docs/NAT-OPS.md) and the 300-38 image. Rows: tmp/logs/mt_interference.jsonl
- Log: tmp/logs/mt_interference.log
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nat_bench as nb  # noqa: E402
import nat_knobs as nk  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mt_interference.log"
ROWS = ROOT / "tmp/logs/mt_interference.jsonl"
SRC = ROOT / "openwrt/selftest/st1008f-mtprobe.c"
BIN = ROOT / "tmp/mtprobe/st1008f-mtprobe"
RUN_S = 12  # forwarding run (10 s + iperf 2 s ramp = nat-bench -O 2); probe runs RUN_S + 6 to cover setup


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def build() -> None:
    import build_selftest
    cc = build_selftest.toolchain(None)
    BIN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(cc), "-O2", "-static", "-o", str(BIN), str(SRC)], check=True, timeout=60)  # one file < 2 s
    subprocess.run(["scp", "-O", "-o", "StrictHostKeyChecking=no", str(BIN), f"root@{nb.SW_IP}:/tmp/st1008f-mtprobe"],
                   check=True, timeout=30, capture_output=True)  # 30 KB over 10G LAN
    nb.sw("chmod +x /tmp/st1008f-mtprobe")


def pin_forwarding() -> None:
    nk.apply({**nk.DEFAULTS, "napi_thread": "on", "tx_by_cpu": "1", "qdisc": "noqueue", "rxq": "one"})
    # ring-0 NAPI thread = lowest id, on VPE1; the other thread on VPE0 (idle: no frames on ring 1)
    nb.sw("ids=$(ps | awk '/napi\\/eth0/{print $NF}' | sed 's/.*-//;s/]//' | sort -n); first=$(echo $ids | cut -d' ' -f1); "
          "for t in $(ps | awk '/napi\\/eth0/{print $1\":\"$NF}'); do pid=${t%%:*}; id=${t##*-}; "
          "if [ \"${id%]}\" = \"$first\" ]; then taskset -p 2 $pid >/dev/null; else taskset -p 1 $pid >/dev/null; fi; done")


def forward() -> dict:
    n0 = sum(1 for _ in nk.BENCH_ROWS.open())
    nk.nat_bench("run", "--dst", nk.DST, "--secs", "10", "-P", "4", "--label", "mt", tag="mt_interference")
    rows = nk.BENCH_ROWS.read_text().splitlines()[n0:]
    r = json.loads(rows[-1])
    return {"mbps": r["mbps"], "cpu0": r["cpu"]["cpu0"]["busy"], "cpu1": r["cpu"]["cpu1"]["busy"]}


def main() -> int:
    build()
    pin_forwarding()
    out = []
    loads = sys.argv[1:] or ["none", "spin", "small", "chase", "stream", "alone-spin", "alone-small", "alone-chase",
                             "alone-stream"]  # args: any of these plus sram / alone-sram
    for load in loads:
        alone = load.startswith("alone-")
        mode = load.split("-")[-1] if load != "none" else None
        arg = ""
        if mode and mode.startswith("small") and mode[5:].isdigit():  # small16 = 16 KiB working set
            mode, arg = "small", mode[5:]
        if alone:  # probe with no forwarding: its unloaded rate
            nk.apply({**nk.DEFAULTS})
        elif load == "none" or load == "spin":
            pin_forwarding()
        p = None
        if mode:
            p = subprocess.Popen(["ssh", "-o", "StrictHostKeyChecking=no", f"root@{nb.SW_IP}",
                                  f"taskset 1 /tmp/st1008f-mtprobe {mode} {RUN_S + 6} {arg}"], stdout=subprocess.PIPE, text=True)
        fwd = {} if alone else forward()
        probe = p.communicate(timeout=RUN_S + 30)[0].strip() if p else ""  # probe ends by itself at RUN_S + 6
        row = {"load": load, "forward": fwd, "probe": probe}
        out.append(row)
        log(json.dumps(row))
        with ROWS.open("a") as fh:
            fh.write(json.dumps({"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **row}) + "\n")
    nk.apply({**nk.DEFAULTS})
    return 0


if __name__ == "__main__":
    sys.exit(main())
