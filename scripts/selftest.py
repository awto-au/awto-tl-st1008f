#!/usr/bin/env python3
"""selftest — run st1008f-selftest on a running switch and fetch the result (#108, docs/SELFTEST.md).

- Default: SSH to --ip (bench sw2), run `st1008f-selftest --quiet [ARGS]`, print the summary line,
  save the JSON to tmp/logs/selftest-<ip>-<YYYYMMDD-HHMMSS>.json.
- `--console`: same at the mainline initramfs prompt (`st1008f-linux # `) through the console daemon.
- `--last`: no run; print the last boot/manual result (/tmp summary + JSON). The only mode allowed on
  sw1 (house switch: network checks only; the test loads CPU and most free RAM for ~20 s).
- Exit 0 PASS, 1 FAIL, 2 no result. Log: tmp/logs/selftest.log
"""

import argparse
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP, SW1_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/selftest.log"
SUMMARY = r"st1008f-selftest: (PASS|FAIL) \[[^\r\n]*"
PROMPT = r"st1008f-linux # "
SSH_S = 5        # dropbear handshake ~1 s on the 1 GHz MIPS (switch_check.py)
JSON_S = 2       # ~10 KB JSON: SSH < 0.1 s; console at 115200 ~0.9 s, x1.25 rounded up
FAST_STEPS, FAST_L = 9, 2   # target steps with the 2 s bound (st1008f-selftest L_FAST etc.)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def target_worst_s(mem: int, cpu: int) -> int:
    """Sum of the target's own step bounds: the host cap never fires before the target names the step."""
    return FAST_STEPS * FAST_L + math.ceil(cpu * 1.25) + 1 + math.ceil(mem * 1.25) + 1


def ssh(ip: str, cmd: str, cap: float) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes",
                           "-o", "StrictHostKeyChecking=accept-new", f"root@{ip}", cmd],
                          capture_output=True, text=True, timeout=cap)


def save(ip: str, text: str) -> dict | None:
    try:
        data = json.loads(text)
    except ValueError:
        log(f"JSON unreadable ({len(text)} B)")
        return None
    out = ROOT / f"tmp/logs/selftest-{ip}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(data, indent=1) + "\n")
    for name, it in data.get("items", {}).items():
        log(f"  {name:8} {it.get('status'):4} {it.get('detail')}")
    log(f"JSON: {out.relative_to(ROOT)}")
    return data


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP)
    ap.add_argument("--console", action="store_true", help="mainline initramfs prompt via the console daemon")
    ap.add_argument("--last", action="store_true", help="read the last result only")
    ap.add_argument("--mem-secs", type=int, default=12)
    ap.add_argument("--cpu-secs", type=int, default=5)
    ap.add_argument("--full", action="store_true", help="all 6 memory patterns (mem 60 s, cpu 10 s)")
    a = ap.parse_args()
    if a.ip == SW1_IP and not a.last and not a.console:
        log(f"refused: {a.ip} is sw1 (house switch, network checks only); use --last")
        return 2
    if a.full:
        a.mem_secs, a.cpu_secs = 60, 10
    args = f"--quiet --mem-secs {a.mem_secs} --cpu-secs {a.cpu_secs}"
    cap = target_worst_s(a.mem_secs, a.cpu_secs)
    where = "console" if a.console else a.ip

    if a.console:
        from st1008_ramload import Console
        con = Console()
        con.note("interactive-begin")
        try:
            con.run("", PROMPT, 2, "initramfs prompt")
            if not a.last:
                log(f"run on {where}: st1008f-selftest {args} (target bound {cap} s)")
                m, _ = con.run(f"st1008f-selftest {args}", SUMMARY, cap, "selftest summary")
                log(m.group(0).strip())
            m, out = con.run("cat /tmp/st1008f-selftest.json", r"\}\}\s*\r?\n" + PROMPT, JSON_S, "selftest JSON")
        finally:
            con.note("interactive-end")
        text = out[out.find("{"):out.rfind("}}") + 2]
    else:
        cmd = "cat /tmp/st1008f-selftest.summary 2>/dev/null || echo 'st1008f-selftest: none'" if a.last else \
            f"st1008f-selftest {args}"
        log(f"{'last result' if a.last else 'run'} on {where}" + ("" if a.last else f" (target bound {cap} s)"))
        r = ssh(a.ip, f"{cmd}; echo @@JSON@@; cat /tmp/st1008f-selftest.json 2>/dev/null || "
                      f"cat /etc/st1008f-selftest.last.json 2>/dev/null", SSH_S + cap + JSON_S)
        if r.returncode == 255:
            log(f"FAIL ssh root@{a.ip}: {r.stderr.strip()}")
            return 2
        head, _, text = r.stdout.partition("@@JSON@@")
        for ln in head.strip().splitlines():
            log(ln)
    data = save(a.ip if not a.console else "console", text.strip()) if text.strip() else None
    if not data:
        log("no result JSON on the target")
        return 2
    return 0 if data.get("result") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
