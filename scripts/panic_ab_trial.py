#!/usr/bin/env python3
"""panic_ab_trial — one #149 A/B trial on the OpenWrt 7.3 image: ramload, nat setup, perf push, zc+perf (sw2 only).

- `panic_ab_trial.py picks|stock` -> one fresh ramload + trigger, then a one-line verdict.
- Panic evidence = new console-log bytes since the trial start (Oops / gro_list_prepare / Call Trace).
- Log tmp/logs/panic_ab_trial.log. Stall guards: each step has a cap (basis in CAPS).
"""
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/panic_ab_trial.log"
CON = ROOT / "private/serial/st1008-console.log"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "root@192.168.25.56"]
# step -> cap s: ramload 35-40 s boot + stp ~15 s (x3); nat setup ~10 s; zc 12 s x2 + perf 15 s (x3)
CAPS = {"ramload": 150, "dropbear": 10, "nat": 40, "perf": 60, "zc": 150}
PICKS = ["uboot-mainline", "--then", "openwrt-ours", "--cage", "1", "--pre", "turbo cpu=1350,ddr=662,lx=306,sram=500"]
STOCK = ["openwrt-ours", "--cage", "1"]


def log(m):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {m}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def run(name, cmd, out):
    try:
        r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=CAPS[name], stdin=subprocess.DEVNULL)
        out.write_text(r.stdout + r.stderr)
        log(f"{name} rc={r.returncode}")
        return r.returncode
    except subprocess.TimeoutExpired as e:
        out.write_text(str(e.stdout) + str(e.stderr))
        log(f"{name} TIMEOUT {CAPS[name]}s")
        return 124


def main():
    mode = sys.argv[1]
    tag = f"{mode}-{time.strftime('%H%M%S')}"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    start = CON.stat().st_size
    d = ROOT / "tmp/logs"
    if "--no-boot" not in sys.argv:  # continue on the board already booted
        run("ramload", ["./dev.py", "ramload", *(PICKS if mode == "picks" else STOCK)], d / f"pab_{tag}_ramload.log")
    run("dropbear", ["./dev.py", "send", "killall dropbear; dropbear -R -B", "--secs", "2"], d / f"pab_{tag}_db.log")
    for i in range(2):  # ping check fails right after boot: retry once
        if run("nat", ["./dev.py", "nat-bench", "setup"], d / f"pab_{tag}_nat{i}.log") == 0:
            break
    run("perf", ["python3", "scripts/perf_push.py"], d / f"pab_{tag}_perf.log")
    rc = run("zc", ["python3", "scripts/zc_bench.py", "--nat", "--napi", "irq1", "--secs", "12", "--len", "1400", "--perf"], d / f"pab_{tag}_zc.log")
    with CON.open("rb") as f:
        f.seek(start)
        txt = f.read().decode("utf-8", "replace")
    (d / f"pab_{tag}_console.log").write_text(txt)
    panic = bool(re.search(r"Oops|gro_list_prepare|Kernel panic|Call Trace", txt))
    fns = sorted(set(re.findall(r"(?:ra|epc|PC is at|Call Trace.*?)\s*[:=]?\s*\S*\b([a-z_0-9]+\+0x[0-9a-f]+/0x[0-9a-f]+)", txt)))[:8]
    zc = re.findall(r"zc\+nat: .*?= ([\d.]+) kpps", (d / f"pab_{tag}_zc.log").read_text())
    r = subprocess.run([*SSH, "cat /proc/uptime; cat /sys/class/thermal/thermal_zone0/temp; grep -m1 BogoMIPS /proc/cpuinfo; tr ' ' '\\n' </proc/cmdline | grep lastreset; true"], capture_output=True, text=True, timeout=15)
    log(f"RESULT {tag} panic={panic} zc_rc={rc} zc_kpps={zc} fns={fns} alive={r.stdout.split() if r.returncode == 0 else 'NO SSH'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
