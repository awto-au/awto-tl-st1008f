#!/usr/bin/env python3
"""stress_all — every load at once on one switch, rails + temps watched (#186, owner 2026-11-28).

Loads, all for --secs:
- host -> switch CPU: iperf3 --bidir -P 4 from the host's --bind address (e.g. selwyn 10G NIC .30 -> sw2 lan8).
- cage loop: lanA (main ns, 10.98.34.1) <-> lanB (netns lp4, 10.98.34.2) over the cable, iperf3 --bidir on the box
  (CPU-sourced: NIC TX + RX DMA both ways). Setup is idempotent; `--loop-teardown` puts lanB back.
- CPU + RAM: scripts/stress_trace.py --full (selftest repeated, 1 Hz telemetry, post-mortem on loss).
- Watchers: scripts/vcc_watch.py (10 ms Vcc), scripts/rail_watch.py (temps incl. module PHYs).
Logs: tmp/logs/stress_all-<ts>-<part>.log; summary in tmp/logs/stress_all.log.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=5"]
NS = "lp4"
LOOP_A, LOOP_B = "10.98.34.1", "10.98.34.2"
LOOP_MAC = "3a:de:0a:91:10:f4"  # locally administered: both ends would otherwise share the switch MAC


def log(msg: str) -> None:
    line = f"{datetime.now().astimezone().isoformat(timespec='seconds')} {msg}"
    print(line, flush=True)
    with (ROOT / "tmp/logs/stress_all.log").open("a") as f:
        f.write(line + "\n")


def box(ip: str, cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True)


def loop_setup(ip: str, a: str, b: str) -> None:
    box(ip, f"ip netns add {NS} 2>/dev/null; ip link set {b} netns {NS} 2>/dev/null; "
            f"ip -n {NS} link set {b} down; ip -n {NS} link set {b} address {LOOP_MAC}; ip -n {NS} link set {b} up; "
            f"ip -n {NS} link set lo up; ip -n {NS} addr replace {LOOP_B}/30 dev {b}; "
            f"ip addr replace {LOOP_A}/30 dev {a}; ip link set {a} up")


def loop_teardown(ip: str, b: str) -> None:
    box(ip, f"killall iperf3 2>/dev/null; ip -n {NS} link set {b} netns 1; ip netns del {NS}; ip link set {b} up")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ip")
    ap.add_argument("--secs", type=int, default=1800)
    ap.add_argument("--bind", default="192.168.25.30", help="host source address on the NIC cabled to the switch")
    ap.add_argument("--loop", default="lan3:lan4", help="cabled cage pair A:B, '' = none")
    ap.add_argument("--lab-ok", action="store_true", help="owner request: the lab unit (stress_trace --sw1-ok)")
    ap.add_argument("--loop-teardown", action="store_true")
    a = ap.parse_args()
    (ROOT / "tmp/logs").mkdir(parents=True, exist_ok=True)
    la, lb = a.loop.split(":") if a.loop else ("", "")
    if a.loop_teardown:
        loop_teardown(a.ip, lb)
        log(f"loop {a.loop} torn down on {a.ip}")
        return 0
    ts = time.strftime("%Y%m%d-%H%M%S")
    lp = lambda part: (ROOT / f"tmp/logs/stress_all-{ts}-{part}.log").open("w")  # noqa: E731
    box(a.ip, "killall iperf3 2>/dev/null; iperf3 -s -D -p 5201")
    if la:
        loop_setup(a.ip, la, lb)
        box(a.ip, f"ip netns exec {NS} iperf3 -s -D -p 5202 -B {LOOP_B}")
        r = box(a.ip, f"ping -c3 -W1 -I {la} {LOOP_B}")
        if " 0 packets received" in r.stdout or r.returncode:
            log(f"FAIL: loop {a.loop} does not pass ping: {r.stdout.strip()[-120:]}")
            return 2
    t = str(a.secs)
    procs = {
        "vcc": [PY, "scripts/vcc_watch.py", a.ip, "--secs", t],
        "rails": [PY, "scripts/rail_watch.py", a.ip, "--secs", t],
        "stress": [PY, "scripts/stress_trace.py", "--ip", a.ip, "--full", "--duration", t, *(["--sw1-ok"] if a.lab_ok else [])],
        "host_iperf": ["iperf3", "-c", a.ip, "-B", a.bind, "-p", "5201", "--bidir", "-P", "4", "-t", t, "-J"],
    }
    if la:
        procs["loop_iperf"] = [*SSH, f"root@{a.ip}", f"iperf3 -c {LOOP_B} -B {LOOP_A} -p 5202 --bidir -t {t} -J"]
    log(f"start {a.ip} for {a.secs} s: {', '.join(procs)} (logs tmp/logs/stress_all-{ts}-*.log)")
    run = {k: subprocess.Popen(v, cwd=ROOT, stdout=lp(k), stderr=subprocess.STDOUT) for k, v in procs.items()}
    rc = {k: p.wait() for k, p in run.items()}
    for k in ("host_iperf", "loop_iperf"):
        if k not in rc:
            continue
        try:
            j = json.loads((ROOT / f"tmp/logs/stress_all-{ts}-{k}.log").read_text())
            e = j["end"]
            log(f"{k}: tx {e['sum_sent']['bits_per_second'] / 1e6:.0f} Mbit/s, rx "
                f"{e['sum_received_bidir_reverse']['bits_per_second'] / 1e6:.0f} Mbit/s, retransmits "
                f"{e['sum_sent'].get('retransmits')}")
        except (ValueError, KeyError) as ex:
            log(f"{k}: no iperf3 result ({ex.__class__.__name__}), rc {rc[k]}")
    log(f"done: rc {rc}")
    return max(rc.values())


if __name__ == "__main__":
    sys.exit(main())
