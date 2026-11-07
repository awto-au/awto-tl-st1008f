#!/usr/bin/env python3
"""plain_final_boots — N plain-kernel boots at the final profile, each with load (sw2 only).

- Boot: canary's plain profile (core 608 raw regs, CPU 1325, DDR 662, SRAM 500). Load: NAT-mode iperf3 TCP P4 120 s, then zc+nat 1400 B (kpps) and integrity.
- Pass = no oops in the console delta, integrity PASS, ssh alive at the end (temperature logged only).
- `plain_final_boots.py [--boots N]`; rows tmp/logs/plain_final_boots.jsonl, log tmp/logs/plain_final_boots.log. Board is left on the RAM kernel.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import canary  # noqa: E402
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/plain_final_boots.log"
JSONL = ROOT / "tmp/logs/plain_final_boots.jsonl"
CON = canary.CONSOLE
PY = sys.executable
SSH = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "-o", "LogLevel=ERROR", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", f"root@{BENCH_IP}"]


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(cmd, tmo):
    """tmo = measured stage time x 1.25-3, stated per call; expiry returns rc 124."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=tmo, cwd=ROOT, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"[timeout {tmo}s] {' '.join(cmd)[:100]}"


def ssh(cmd, tmo=20):
    return run(SSH + [cmd], tmo)[1]


def temp():
    t = ssh("cat /sys/class/thermal/thermal_zone0/temp", 12).split()
    return round(int(t[-1]) / 1000, 1) if t and t[-1].isdigit() else None


def one(idx):
    row = {"boot": idx, "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "result": "FAIL"}
    off = CON.stat().st_size
    cmd = [PY, "dev.py", "ramload", "uboot-mainline", "--stock-clocks", "--then", "mainline-kernel", "--cage", "1", "--mgmt",
           "--pre", canary.PLAIN_TURBO, "--pre", canary.PLAIN_RAW]
    rc, out = run(cmd, 240)  # canary plain_boot total cap
    row["ramload_rc"] = rc
    log(f"[#{idx}] ramload rc {rc}: {out.strip().splitlines()[-1][-150:] if out.strip() else ''}")
    steps = [("natsetup", [PY, "scripts/nat_bench.py", "setup"], 90), ("natmode", [PY, "scripts/nat_bench.py", "mode", "nat"], 60),
             ("iperf120", [PY, "scripts/nat_bench.py", "run", "--secs", "120", "-P", "4"], 180),  # 120 s + omit + dumps
             ("natroute", [PY, "scripts/nat_bench.py", "mode", "route"], 60),
             ("zc", [PY, "scripts/zc_bench.py", "--nat", "--secs", "10", "--len", "1400", "--zc-only"], 120),
             ("integrity", [PY, "scripts/zc_bench.py", "--nat", "--integrity"], 90)]
    if rc == 0 and not canary.ensure_ssh(BENCH_IP):
        rc, row["why"] = 1, "no ssh"
    if rc == 0:
        for name, c, tmo in steps:
            r, o = run(c, tmo)
            tail = " | ".join(ln[-170:] for ln in o.strip().splitlines()[-2:])
            log(f"[#{idx}] {name} rc {r}: {tail}")
            row[name] = r
            if name == "iperf120":
                m = re.search(r"RESULT \S+: ([\d.]+) Mbit/s", o)
                row["tcp_mbit"] = float(m[1]) if m else None
            if name == "zc":
                m = re.search(r"zc\+nat: natwan rx \d+ pkts = ([\d.]+) kpps", o)
                row["zc_kpps"] = float(m[1]) if m else None
            if name == "integrity":
                row["integrity"] = "INTEGRITY PASS" in o
            if r != 0:
                row["why"] = f"{name} rc {r}"
                break
    row["oops"] = next((ln.strip()[:200] for ln in CON.read_bytes()[off:].decode("utf-8", "replace").splitlines()
                        if canary.BAD_CONSOLE.search(ln.encode())), None)
    row["temp"] = temp()
    up = ssh("cut -d. -f1 /proc/uptime", 12).split()
    row["alive"] = bool(up and up[-1].isdigit())
    ok = rc == 0 and not row.get("why") and not row["oops"] and row.get("integrity") and row["alive"]
    row["result"] = "PASS" if ok else "FAIL"
    JSONL.parent.mkdir(parents=True, exist_ok=True)
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    log(f"RESULT #{idx}: {row['result']} {json.dumps(row)}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boots", type=int, default=5)
    a = ap.parse_args()
    canary.refuse(BENCH_IP)
    res = [one(i) for i in range(1, a.boots + 1)]
    log(f"SUMMARY {sum(res)}/{len(res)} passed")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
