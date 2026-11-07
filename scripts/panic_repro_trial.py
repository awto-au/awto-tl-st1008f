#!/usr/bin/env python3
"""panic_repro_trial — original #149 reproducer: idle boot to 90 s uptime, then zc no-perf, then zc+perf (sw2 only).

- `panic_repro_trial.py owrt|plain "<turbo profile>"` -> fresh ramload, read-only ssh polls until uptime >= 90 s, zc, zc --perf.
- Panic evidence = new console-log bytes since trial start. Result line + files tmp/logs/prt_<tag>_*.log, log tmp/logs/panic_repro_trial.log.
- Poll period 5 s: the 7.3 panics came at 37-39 s uptime, so 5 s resolves them. Stall guard: every step has a cap (CAPS).
"""
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/panic_repro_trial.log"
CON = ROOT / "private/serial/st1008-console.log"
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", "root@192.168.25.56"]
# ramload 35-40 s boot (+stp ~15 s on OpenWrt) x3; idle wait: 90 s uptime + boot margin; nat ~10 s x4; perf push x3; zc 12 s x2 + perf ~15 s x3
CAPS = {"ramload": 150, "idle": 150, "nat": 40, "perf": 60, "zc": 100}
PANIC = re.compile(r"Oops|gro_list_prepare|Kernel panic|Call Trace|Unable to handle")
WAIT = threading.Event()


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


def ssh(cmd, t=8):
    try:
        r = subprocess.run([*SSH, cmd], capture_output=True, text=True, timeout=t, stdin=subprocess.DEVNULL)
        return r.stdout if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        return None


def con_since(start):
    with CON.open("rb") as f:
        f.seek(start)
        return f.read().decode("utf-8", "replace")


def main():
    kind, prof = sys.argv[1], sys.argv[2]
    tag = f"{kind}-{time.strftime('%H%M%S')}"
    d = ROOT / "tmp/logs"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    start = CON.stat().st_size
    nxt = "openwrt-ours" if kind == "owrt" else "mainline-kernel"
    cmd = ["./dev.py", "ramload", "uboot-mainline", "--then", nxt, "--cage", "1", "--pre", prof] + ([] if kind == "owrt" else ["--mgmt"])
    log(f"TRIAL {tag} profile={prof}")
    if "--no-boot" not in sys.argv:
        run("ramload", cmd, d / f"prt_{tag}_ramload.log")
    if kind == "plain" and ssh("true") is None:  # port-up's dropbear sometimes absent (keygen race) / carrier late
        run("nat", ["./dev.py", "send", "pgrep dropbear || dropbear -R -B", "--secs", "2"], d / f"prt_{tag}_db0.log")
    t0 = time.time()
    seen, panic, last = [], False, None
    while time.time() - t0 < CAPS["idle"]:
        up = ssh("cat /proc/uptime")
        if up:
            last = float(up.split()[0])
            seen.append(last)
        if PANIC.search(con_since(start)):
            panic = True
            break
        if last is not None and last >= 90:
            break
        WAIT.wait(5)
    log(f"idle phase panic={panic} last_uptime={last} polls={len(seen)}")
    info = ssh("cat /proc/uptime; cat /sys/class/thermal/thermal_zone0/temp; grep -m1 BogoMIPS /proc/cpuinfo; tr ' ' '\\n' </proc/cmdline | grep lastreset; dmesg | grep -m2 -E 'LX frequency|clocks'; true") if not panic else None
    log(f"info {info.split(chr(10)) if info else None}")
    zc = {}
    if not panic:
        run("nat", ["./dev.py", "send", "killall dropbear; dropbear -R -B", "--secs", "2"], d / f"prt_{tag}_db.log") if kind == "owrt" else None
        for i in range(2):
            if run("nat", ["./dev.py", "nat-bench", "setup"], d / f"prt_{tag}_nat{i}.log") == 0:
                break
        run("perf", ["python3", "scripts/perf_push.py"], d / f"prt_{tag}_perf.log")
        for name, extra in (("noperf", []), ("perf", ["--perf"])):
            rc = run("zc", ["python3", "scripts/zc_bench.py", "--nat", "--napi", "irq1", "--secs", "12", "--len", "1400", *extra], d / f"prt_{tag}_zc_{name}.log")
            zc[name] = (rc, re.findall(r"zc\+nat: .*?= ([\d.]+) kpps", (d / f"prt_{tag}_zc_{name}.log").read_text()))
            if PANIC.search(con_since(start)):
                panic = True
                log(f"panic during zc {name}")
                break
    txt = con_since(start)
    (d / f"prt_{tag}_console.log").write_text(txt)
    panic = panic or bool(PANIC.search(txt))
    fns = sorted(set(re.findall(r"\b([a-z_0-9]+\+0x[0-9a-f]+/0x[0-9a-f]+)", txt)))[:12]
    up_at = re.findall(r"\[\s*(\d+\.\d+)\][^\n]*(?:Oops|Unable to handle)", txt)
    end = ssh("cat /proc/uptime; cat /sys/class/thermal/thermal_zone0/temp; tr ' ' '\\n' </proc/cmdline | grep lastreset; true")
    log(f"RESULT {tag} panic={panic} oops_uptime={up_at[:1]} zc={zc} fns={fns} end={end.split() if end else 'NO SSH'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
