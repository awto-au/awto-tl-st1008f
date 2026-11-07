#!/usr/bin/env python3
"""swcore_step — one switch-core clock step on sw2: ramload with the clock change, then rx / forwarding / integrity, hang detection (#148).

- Boot: `turbo cpu=1350,ddr=662,lx=306,sram=500`, optional SW VCO (e214), e220, relock (e200 bit 30), then the plain 7.4 kernel.
- Stages (each followed by a ping check): rx 1400 B n=3, stack+zc forwarding 12 s, integrity 1400/500/64.
- Hang = ping lost after a stage: console dump (IRQ count, DMA state, CPU queue 1), `ip link set eth0 down/up` as recovery, logged.
- Temperature (thermal_zone0) is logged after each stage; no temperature abort (owner 2026-11-07).
    swcore_step.py --tag 508 --e220 0x2c426 [--e214 0x...] [--no-boot] [--skip rx,fwd,int]
- Log: tmp/logs/swcore_step_TAG.log
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IP = "192.168.25.56"
SSH = ["ssh", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes", f"root@{IP}"]
LOG = None


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(cmd, tmo, **kw):
    """Stage limits are stated at each call: they are 1.5-3x the measured stage time, a stall names itself in the log."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=tmo, cwd=ROOT, **kw)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"[timeout {tmo}s] {' '.join(cmd)[:120]}"


def ssh(cmd, tmo=20):
    """stdout only (ssh host-key warnings go to stderr)."""
    try:
        return subprocess.run(SSH[:-1] + ["-q", SSH[-1], cmd], capture_output=True, text=True, timeout=tmo).stdout
    except subprocess.TimeoutExpired:
        return f"[ssh timeout {tmo}s]"


def alive():
    return run(["ping", "-c", "2", "-W", "2", IP], 8)[0] == 0 and "root" in run(SSH + ["echo root"], 10)[1] or False


def temp():
    t = ssh("cat /sys/class/thermal/thermal_zone0/temp").strip().splitlines()
    try:
        return int(t[-1])
    except (ValueError, IndexError):
        return -1


def console(cmd, secs=8):
    return run([sys.executable, "scripts/switch_console.py", "send", cmd, "--secs", str(secs)], secs + 20)[1]


def recover(stage):
    log(f"HANG after {stage}: console dump")
    log(console("grep eth0 /proc/interrupts; devmem 0x1b00e020 32; devmem 0x1b00e028 32; devmem 0x1b007c8c 32; devmem 0x1b007e44 32; devmem 0x1b007ec4 32; devmem 0x1b00df84 32", 8))
    console("ip link set eth0 down; ip link set eth0 up; ip link set lan1 up", 8)
    ok = alive()
    log(f"recovery by eth0 down/up: {'OK' if ok else 'FAILED'}")
    return ok


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--e220", default="0x2c426")
    ap.add_argument("--e214", default=None)
    ap.add_argument("--lx", default="306")
    ap.add_argument("--no-boot", action="store_true")
    ap.add_argument("--swc-first", action="store_true", help="clock change before `turbo` (CPU/DDR/LX)")
    ap.add_argument("--skip", default="")
    a = ap.parse_args()
    LOG = ROOT / f"tmp/logs/swcore_step_{a.tag}.log"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    skip = set(a.skip.split(","))
    if not a.no_boot:
        pre = ["--pre", f"turbo cpu=1350,ddr=662,lx={a.lx},sram=500"]
        # e214 (SW VCO) acts at once and garbles the UART until e220 re-codes LX: one line, e220 first, relock last
        line = f"mw.l 0xbb00e220 {a.e220}; "
        if a.e214:
            line += f"mw.l 0xbb00e214 {a.e214}; "
        line += "mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff"
        pre = (["--pre", line] + pre if a.swc_first else pre + ["--pre", line]) + ["--pre", "md.l 0xbb00e220 1", "--pre", "md.l 0xbb00e214 1"]
        t0 = time.time()
        # ramload takes ~40 s (two stages + tftp 5.7 MB); 120 s is 3x
        rc, out = run(["./dev.py", "ramload", "uboot-mainline", "--then", "mainline-kernel", "--kernel", "mainline-7.4-rc1.bin",
                       "--cage", "1", "--mgmt"] + pre, 120)
        log(f"ramload rc {rc} in {time.time() - t0:.0f} s; tail: {out.strip().splitlines()[-3:] if out.strip() else ''}")
        # lan1 10G link comes up ~4 s after port-up; 10 tries x (2 ping + ssh) bound the wait to < 60 s
        # lan1 10G link comes up ~4 s after port-up (dropbear is then missing): 15 pings x 2 s bound the wait to ~30 s
        up = any(run(["ping", "-c", "1", "-W", "2", IP], 6)[0] == 0 for _ in range(15))
        if up and "root" not in run(SSH + ["echo root"], 10)[1]:
            console("dropbear -R -B", 4)
        if not up or not any(alive() for _ in range(5)):
            log("BOOT FAIL: no ping/ssh after ramload")
            return 3
    # uptime >= 25 s before nat-bench setup (zc setup right after boot lost lan1 in the earlier campaign)
    t_end = time.time() + 90  # boot-to-25-s-uptime plus dropbear start: ~50 s expected, 90 s = 1.8x
    while time.time() < t_end:
        up = ssh("cut -d. -f1 /proc/uptime").strip().splitlines()
        if up and up[-1].isdigit() and int(up[-1]) >= 25:
            break
    else:
        log("no ssh uptime reading")
        return 3
    log(f"e200/e214/e220 = {ssh('devmem 0x1b00e200 32; devmem 0x1b00e214 32; devmem 0x1b00e220 32').split()}")
    t_before = temp()
    log(f"temp before {t_before / 1000:.1f} C")
    rc, out = run([sys.executable, "scripts/nat_bench.py", "setup"], 60)
    rc, out = run([sys.executable, "scripts/nat_bench.py", "mode", "route"], 30)
    stages = [
        ("rx", [sys.executable, "scripts/ceiling_rxtx.py", "--tag", "step" + a.tag, "--n", "3", "--sizes", "1400", "--modes", "rx", "--no-setup"], 90),
        ("fwd", [sys.executable, "scripts/zc_bench.py", "--nat", "--napi", "irq1", "--secs", "12", "--len", "1400"], 120),
        ("int", [sys.executable, "scripts/zc_bench.py", "--nat", "--napi", "irq1", "--secs", "12", "--len", "1400", "--integrity"], 60),
    ]
    status = "PASS"
    for name, cmd, tmo in stages:
        if name in skip:
            continue
        rc, out = run(cmd, tmo)
        keep = [ln for ln in out.splitlines() if any(k in ln for k in ("SUMMARY", "kpps", "integrity", "INTEGRITY", "zc /", "forwarded", "timed out"))]
        log(f"stage {name} rc {rc}: " + " | ".join(ln[-170:] for ln in keep[-8:]))
        t = temp()
        log(f"temp after {name}: {t / 1000:.1f} C")
        if not alive():
            status = f"HANG@{name}"
            if not recover(name):
                return 5
            run([sys.executable, "scripts/nat_bench.py", "setup"], 60)
    log(f"RESULT {a.tag}: {status}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
