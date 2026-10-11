#!/usr/bin/env python3
"""nic_path_bench — before/after suite for rteth NIC-path changes on the mainline 7.3 kernel (#60 #65).

- `boot`: ramload uboot-mainline --then mainline-kernel (CPU 1 GHz, cage 1) -> `port-up 1` -> SSH ->
  nat-bench setup + mode nat-ft. House LAN: one cage, no bridge; run storm-watch alongside.
- `run --tag T [--runs 3]`: per run, NAT + flowtable: TCP P4; UDP 1400 B at 600/700/900 Mbit/s offered
  (overload curve); UDP 64 B at 100 Mbit/s offered (saturating). Rows -> tmp/logs/nat_bench.jsonl
  (tag T), plus eth0 qdisc drops per test.
- `table [T ...]`: min-max per test and tag (fwd kpps = eth0 TX pps).
- Log: tmp/logs/nic_path_bench.log
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/nic_path_bench.log"
JSONL = ROOT / "tmp/logs/nat_bench.jsonl"
sys.path.insert(0, str(ROOT / "scripts"))

# (label, nat_bench run args)
SUITE = [
    ("tcp-P4", ["--secs", "10", "-P", "4"]),
    ("udp1400-600", ["--secs", "10", "-P", "1", "--udp", "600", "--len", "1400"]),
    ("udp1400-700", ["--secs", "10", "-P", "1", "--udp", "700", "--len", "1400"]),
    ("udp1400-900", ["--secs", "10", "-P", "1", "--udp", "900", "--len", "1400"]),
    ("udp64-100", ["--secs", "10", "-P", "1", "--udp", "100", "--len", "64"]),
]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def boot(ramload: bool = True) -> int:
    from st1008_ramload import Console
    if ramload:
        # power cycle + rtk network on + 2 TFTPs + boot, ~25 s measured; 300 s names a hang
        r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "uboot-mainline",
                            "--then", "mainline-kernel", "--cage", "1"], timeout=300)
        if r.returncode not in (0, 1):  # 1 = UNKNOWN boot-log lines: reviewed in the ramload output
            log(f"ramload failed rc={r.returncode}")
            return r.returncode
        con = Console()
        # kernel lines (DSA route notices) otherwise interleave with the prompt
        con.run("dmesg -n 1", r"st1008f-linux # ", 3, "console loglevel 1")
        # port-up: link + dropbear < 3 s; 10 s cap
        con.run("port-up 1 192.168.25.48/24", r"lan1@?\S*\s+(UP|DOWN|UNKNOWN|LOWERLAYERDOWN)[\s\S]*st1008f-linux # ",
                10, "port-up 1")
        con.run("ip route add default via 192.168.25.254", r"st1008f-linux # ", 3, "default route")
    import nat_bench
    t0 = time.monotonic()
    while True:  # SSH: link negotiation + dropbear key gen on first connect, ~10 s; 40 s cap
        try:
            nat_bench.sw("true", tmo=8)
            break
        except SystemExit as e:
            if time.monotonic() - t0 > 40:
                log(f"SSH not up after {time.monotonic() - t0:.0f} s (cap 40 s): {e}")
                return 1
            time.sleep(2)  # retry interval: one SSH ConnectTimeout is 5 s
    # setup's own ping fails until a mode gives natwan a way back; status after mode is the check.
    # each = a few ssh + host netns cmds, < 15 s; 60 s names a hang
    for args, must in ((["setup"], False), (["mode", "nat-ft"], True), (["status"], True)):
        if subprocess.run([sys.executable, str(ROOT / "scripts/nat_bench.py"), *args], timeout=60).returncode and must:
            return 1
    from st1008_ramload import relay_check
    if relay_check() == 3:  # relay rebooted during boot (#84): board lost power
        log("boot: relay rebooted -> board was unpowered; rerun boot")
        return 1
    log("boot: ready (nat-ft)")
    return 0


def qdisc_drops() -> int:
    import nat_bench
    out = nat_bench.sw("tc -s qdisc show dev eth0")
    return sum(int(m) for m in re.findall(r"dropped (\d+)", out))


def run(tag: str, runs: int, only: list[str] | None) -> int:
    env = dict(os.environ, NAT_BENCH_TAG=tag)
    for i in range(1, runs + 1):
        for label, args in SUITE:
            if only and label not in only:
                continue
            q0 = qdisc_drops()
            # one iperf3 run: 10 s + 2 s omit + setup; nat_bench enforces its own iperf3 cap; 90 s names a hang
            r = subprocess.run([sys.executable, str(ROOT / "scripts/nat_bench.py"), "run", "--label",
                                f"nic-{label}", *args], capture_output=True, text=True, env=env, timeout=90)
            q1 = qdisc_drops()
            res = [ln.split("RESULT", 1)[1].strip() for ln in r.stdout.splitlines() if "RESULT" in ln]
            log(f"[{tag} run {i}/{runs}] {label}: {res[0] if res else r.stdout[-300:] + r.stderr[-300:]} | "
                f"qdisc drops {q1 - q0}")
            with (ROOT / "tmp/logs/nic_path_bench.jsonl").open("a") as fh:
                fh.write(json.dumps({"tag": tag, "run": i, "label": label, "qdisc_drops": q1 - q0,
                                     "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}) + "\n")
    return 0


def table(tags: list[str]) -> int:
    rows = [json.loads(ln) for ln in JSONL.read_text().splitlines() if ln.strip()]
    rows = [r for r in rows if r.get("label", "").startswith("nic-") and (not tags or r.get("tag") in tags)]
    tags = tags or sorted({r["tag"] for r in rows})
    log(f"{'tag':28} {'test':14} {'n':>2} {'Mbit/s':>13} {'fwd kpps':>13} {'loss %':>11} {'VPE-ns/pkt':>13}")
    for t in tags:
        for label, _ in SUITE:
            rs = [r for r in rows if r["tag"] == t and r["label"] == f"nic-{label}"]
            if not rs:
                continue

            def rng(vals, fmt):
                vals = [v for v in vals if v is not None]
                return "-" if not vals else (f"{fmt(min(vals))}" if min(vals) == max(vals)
                                             else f"{fmt(min(vals))}-{fmt(max(vals))}")
            log(f"{t:28} {label:14} {len(rs):>2} {rng([r['mbps'] for r in rs], lambda v: f'{v:.0f}'):>13} "
                f"{rng([r['eth0_tx_pps'] / 1000 for r in rs], lambda v: f'{v:.1f}'):>13} "
                f"{rng([r.get('loss_pct') for r in rs], lambda v: f'{v:.1f}'):>11} "
                f"{rng([r['ns_vpe_per_rx_pkt'] for r in rs], lambda v: f'{v:.0f}'):>13}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("boot")
    b.add_argument("--no-ramload", action="store_true", help="kernel already up with port-up done")
    r = sub.add_parser("run")
    r.add_argument("--tag", required=True)
    r.add_argument("--runs", type=int, default=3)
    r.add_argument("--only", nargs="*", help="subset of " + ",".join(s[0] for s in SUITE))
    t = sub.add_parser("table")
    t.add_argument("tags", nargs="*")
    a = ap.parse_args()
    if a.cmd == "boot":
        return boot(not a.no_ramload)
    if a.cmd == "run":
        return run(a.tag, a.runs, a.only)
    return table(a.tags)


if __name__ == "__main__":
    sys.exit(main())
