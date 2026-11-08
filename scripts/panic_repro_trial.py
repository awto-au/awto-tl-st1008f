#!/usr/bin/env python3
"""panic_repro_trial — #149 reproducer: idle boot to 90 s, then existing UDP/TCP zc trigger with optional perf (sw2 only).

- `panic_repro_trial.py owrt|plain "<turbo profile>"` -> fresh ramload, read-only ssh polls until uptime >= 90 s, zc, zc --perf.
- Panic evidence = new console-log bytes since trial start. Result line + files tmp/logs/prt_<tag>_*.log, log tmp/logs/panic_repro_trial.log.
- Current 7.4 arms: --clock-set common --image openwrt-ours-clean --normalize --no-perf --tcp.
- Exit 0 = NO_PANIC with successful steps and SSH health, 1 = PANIC, 2 = INVALID (never a clean result).
- --dry-run prints commands without board or console access.
- Poll period 5 s: the 7.3 panics came at 37-39 s uptime, so 5 s resolves them. Stall guard: every step has a cap (CAPS).
"""
import argparse
import json
import re
import shlex
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
CAPS = {"ramload": 150, "idle": 150, "nat": 40, "perf": 60, "zc": 150, "normalise": 180}
PANIC = re.compile(r"Oops|gro_list_prepare|rteth-gro-diag|Kernel panic|Call Trace|Unable to handle")
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


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("kind", choices=["owrt", "plain"])
    ap.add_argument("profile", nargs="?", default="", help="legacy turbo command; use --clock-set for the controlled clocks")
    ap.add_argument("--clock-set", choices=["common", "final"], help="reuse stack_compare.py clock recipes, including core PLL")
    ap.add_argument("--image", help="ramload --then key (default openwrt-ours or mainline-kernel)")
    ap.add_argument("--kernel", help="plain ramload image filename, e.g. mainline-7.4-rc1-clean3.bin")
    ap.add_argument("--bootargs", help="e.g. rtl838x_eth.gro_diag=1 (DEBUG_NET image only)")
    ap.add_argument("--normalize", action="store_true", help="reuse stack_normalize.py after NAT setup; nonzero = invalid trial")
    ap.add_argument("--napi", choices=["irq0", "irq1"], default="irq1")
    ap.add_argument("--rps-mask", choices=["0", "1", "2", "3"], default="0")
    ap.add_argument("--qdisc", choices=["noqueue", "fq_codel"], default="noqueue")
    ap.add_argument("--gro-mode", choices=["on", "list-off", "off"], default="on")
    ap.add_argument("--secs", type=int, choices=range(1, 31), default=12, metavar="1..30", help="duration of each existing bench cell")
    ap.add_argument("--tcp", action="store_true", help="existing zc_bench TCP P4 stack + zc, both directions")
    ap.add_argument("--no-perf", action="store_true", help="only no-perf trigger; do not push perf onto clean images")
    ap.add_argument("--no-boot", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print commands; no board, console, or file access")
    a = ap.parse_args(argv)
    if not a.profile and not a.clock_set and not a.no_boot:
        ap.error("provide a turbo profile or --clock-set")
    if a.profile and a.clock_set:
        ap.error("profile and --clock-set are mutually exclusive")
    if a.tcp and not a.no_perf:
        ap.error("--tcp currently requires --no-perf; the historical perf trigger is UDP")
    if a.kernel and a.kind != "plain":
        ap.error("--kernel is for plain only; select an OpenWrt --image instead")
    if not a.normalize and (a.rps_mask != "0" or a.qdisc != "noqueue" or a.gro_mode != "on"):
        ap.error("RPS, qdisc and GRO arms require --normalize")
    return a


def command_plan(a, tag):
    nxt = a.image or ("openwrt-ours" if a.kind == "owrt" else "mainline-kernel")
    boot = ["./dev.py", "ramload", "uboot-mainline", "--then", nxt, "--cage", "1"]
    if a.kind == "plain":
        boot += ["--mgmt"]
    if a.kernel:
        boot += ["--kernel", a.kernel]
    if a.clock_set:
        from stack_compare import TURBO, RAW
        boot += ["--stock-clocks", "--pre", TURBO[a.clock_set], "--pre", RAW[a.clock_set]]
    elif a.profile:
        boot += ["--pre", a.profile]
    if a.bootargs:
        boot += ["--bootargs", a.bootargs]
    norm = ["python3", "scripts/stack_normalize.py", "--stack", "B" if a.kind == "owrt" else "C",
            "--napi", a.napi, "--rps-mask", a.rps_mask, "--qdisc", a.qdisc, "--gro-mode", a.gro_mode, "--tag", tag]
    trigger = ["python3", "scripts/zc_bench.py", "--nat", "--napi", a.napi, "--secs", str(a.secs), "--len", "1400"]
    if a.tcp:
        trigger += ["--tcp"]
    steps = [] if a.no_boot else [("ramload", boot)]
    steps += [("nat", ["./dev.py", "nat-bench", "setup"])]
    if a.normalize:
        steps += [("normalise", norm)]
    steps += [("mode", ["./dev.py", "nat-bench", "mode", "nat"]),
              ("status", ["./dev.py", "nat-bench", "status"])]
    if not a.no_perf:
        steps += [("perf", ["python3", "scripts/perf_push.py"])]
    steps += [("zc-noperf", trigger)]
    if not a.no_perf:
        steps += [("zc-perf", trigger + ["--perf"])]
    if a.normalize:
        steps += [("snapshot", norm[:-1] + [tag + "-post", "--snapshot-only"])]
    return steps


def main(argv=None):
    a = parse_args(argv)
    kind = a.kind
    tag = f"{kind}-{time.strftime('%Y%m%d-%H%M%S')}"
    steps = command_plan(a, tag)
    if a.dry_run:
        for name, cmd in steps:
            print(f"{name}: {shlex.join(cmd)}")
        return 0
    d = ROOT / "tmp/logs"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    start = CON.stat().st_size
    log(f"TRIAL {tag} args={json.dumps(vars(a), sort_keys=True)}")
    invalid = []
    if not a.no_boot:
        if run("ramload", steps[0][1], d / f"prt_{tag}_ramload.log"):
            invalid.append("ramload failed")
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
    detail = ssh("cat /proc/version; cat /proc/cmdline; cat /sys/module/rtl838x_eth/parameters/gro_diag 2>/dev/null; cat /sys/kernel/debug/rteth/rxq; grep eth0 /proc/interrupts; for a in 0x1b00e200 0x1b00e214 0x1b00e220; do devmem $a 32; done; true") if not panic and not invalid else None
    (d / f"prt_{tag}_identity.log").write_text(detail or "unavailable\n")
    boot_id = ssh("cat /proc/sys/kernel/random/boot_id") if not panic and not invalid else None
    if not boot_id and not panic:
        invalid.append("no boot identity before trigger")
    zc = {}
    if last is None or last < 90:
        invalid.append("idle/SSH readiness not established")
    if not panic and not invalid:
        run("nat", ["./dev.py", "send", "killall dropbear; dropbear -R -B", "--secs", "2"], d / f"prt_{tag}_db.log") if kind == "owrt" else None
        for name, cmd in steps:
            if name == "ramload":
                continue
            cap = "zc" if name.startswith("zc-") else "normalise" if name == "snapshot" else "nat" if name in ("mode", "status") else name
            out = d / f"prt_{tag}_{name}.log"
            rc = run(cap, cmd, out)
            if name.startswith("zc-"):
                zc[name] = (rc, re.findall(r"zc\+nat: .*?= ([\d.]+) kpps", out.read_text()))
            if PANIC.search(con_since(start)):
                panic = True
                log(f"panic during {name}")
                break
            # setup can return 1 until mode installs the return route / fw4 rules.
            # The subsequent status ping is the required connectivity check.
            if name == "nat" and rc == 1:
                log("setup rc=1: defer verdict until mode + status")
                continue
            if rc:
                invalid.append(f"{name} rc={rc}")
                break
    txt = con_since(start)
    (d / f"prt_{tag}_console.log").write_text(txt)
    panic = panic or bool(PANIC.search(txt))
    fns = sorted(set(re.findall(r"\b([a-z_0-9]+\+0x[0-9a-f]+/0x[0-9a-f]+)", txt)))[:12]
    up_at = re.findall(r"\[\s*(\d+\.\d+)\][^\n]*(?:Oops|Unable to handle)", txt)
    end = ssh("cat /proc/uptime; cat /sys/class/thermal/thermal_zone0/temp; tr ' ' '\\n' </proc/cmdline | grep lastreset; true")
    end_id = ssh("cat /proc/sys/kernel/random/boot_id")
    if end is None or end_id is None:
        invalid.append("no final SSH health check")
    if boot_id and end_id and boot_id.strip() != end_id.strip():
        invalid.append("boot identity changed (uncaptured reboot)")
    # A late panic during the final SSH check still belongs to this trial.
    txt = con_since(start)
    (d / f"prt_{tag}_console.log").write_text(txt)
    panic = panic or bool(PANIC.search(txt))
    verdict = "PANIC" if panic else "INVALID" if invalid else "NO_PANIC"
    log(f"RESULT {tag} verdict={verdict} invalid={invalid} panic={panic} boot_id={boot_id!r} end_id={end_id!r} oops_uptime={up_at[:1]} zc={zc} fns={fns} end={end.split() if end else 'NO SSH'}")
    return 1 if panic else 2 if invalid else 0


if __name__ == "__main__":
    sys.exit(main())
