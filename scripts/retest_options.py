#!/usr/bin/env python3
"""retest_options — old NAT options re-tested at a switch-core clock on sw2 (owner rule 2026-11-07, docs/FASTEST-SETTINGS.md).

- `boot --core 408|608 [--kernel K] [--bootargs A]`: ramload (swcore_step recipe), wait uptime >= 25 s, SPI-clock readout, nat-bench setup + route.
- `meas --label L [--set CMD] [--reset CMD] [--napi irq1|split|irq] [--m rx1400,rx64,fwd1400,fwd64,stack1400,tcp]`: apply, measure once, reset.
- Rows -> tmp/logs/retest_options.jsonl, log tmp/logs/retest_options.log. sw2 only (192.168.25.56).
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IP = "192.168.25.56"
SSH = ["ssh", "-q", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes", f"root@{IP}"]
LOG = ROOT / "tmp/logs/retest_options.log"
JSONL = ROOT / "tmp/logs/retest_options.jsonl"
PY = sys.executable
# core -> (e220, e214, LX label): swcore_step recipe, docs/CLOCKS.md
CORES = {"408": (None, None, "306"), "608": ("0x36826", "0x478", "306")}
BAD = re.compile(rb"Oops|\bBUG\b|Kernel panic|gro_list_prepare")
CONSOLE = ROOT / "private/serial/st1008-console.log"


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(cmd, tmo):
    """tmo = stall/total cap stated per call by the caller (measured stage time x 1.5-3)."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=tmo, cwd=ROOT)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"[timeout {tmo}s] {' '.join(cmd)[:100]}"


def ssh(cmd, tmo=30):
    try:
        return subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=tmo).stdout
    except subprocess.TimeoutExpired:
        return f"[ssh timeout {tmo}s]"


def alive():
    return run(["ping", "-c", "2", "-W", "2", IP], 8)[0] == 0 and "root" in ssh("echo root", 10)


def temp():
    t = ssh("cat /sys/class/thermal/thermal_zone0/temp").split()
    return int(t[-1]) if t and t[-1].isdigit() else -1


def cmd_boot(a):
    e220, e214, lx = CORES[a.core]
    pre = ["--pre", f"turbo cpu={a.cpu},ddr=662,lx={lx},sram=500"]
    if e220:
        pre += ["--pre", f"mw.l 0xbb00e220 {e220}; mw.l 0xbb00e214 {e214}; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff"]
    pre += ["--pre", "md.l 0xbb00e220 1", "--pre", "md.l 0xbb00e214 1", "--pre", "md.l 0xb8001200 1"]
    cmd = ["./dev.py", "ramload", "uboot-mainline", "--then", "mainline-kernel", "--kernel", a.kernel, "--cage", "1", "--mgmt"]
    if a.bootargs:
        cmd += ["--bootargs", a.bootargs]
    t0 = time.time()
    rc, out = run(cmd + pre, 150)  # measured ~32-40 s (swcore_step logs); 150 s = stall cap x2.5, expiry = BOOT FAIL
    log(f"ramload core {a.core} {a.kernel} args '{a.bootargs}' rc {rc} in {time.time() - t0:.0f} s")
    up = any(run(["ping", "-c", "1", "-W", "2", IP], 6)[0] == 0 for _ in range(15))  # lan1 up ~4 s after port-up
    if up and "root" not in ssh("echo root", 10):
        run([PY, "scripts/switch_console.py", "send", "dropbear -R -B", "--secs", "4"], 30)
    if not up or not any(alive() for _ in range(5)):
        log("BOOT FAIL: no ping/ssh")
        return 3
    t_end = time.time() + 90  # boot to 25 s uptime ~50 s
    while time.time() < t_end:
        u = ssh("cut -d. -f1 /proc/uptime").split()
        if u and u[-1].isdigit() and int(u[-1]) >= 25:
            break
    regs = ssh("devmem 0x1b00e200 32; devmem 0x1b00e214 32; devmem 0x1b00e220 32; devmem 0x18001200 32").split()
    log(f"e200/e214/e220/SFCR = {regs} bogomips {ssh('grep -i bogomips /proc/cpuinfo | head -1').strip()} cmdline-args '{a.bootargs}'")
    if len(regs) >= 4:
        e220v, sfcr = int(regs[2], 16), int(regs[3], 16)
        nor_code = (e220v >> 13) & 0xF
        div = 2 * ((sfcr >> 29) + 1)
        log(f"SPI check: e220 NOR code {nor_code}, SFCR[31:29] {(sfcr >> 29)} -> divide {div}")
    log(f"temp {temp() / 1000:.1f} C")
    for sub in (["setup"], ["mode", "route"]):
        rc, out = run([PY, "scripts/nat_bench.py", *sub], 90)  # setup ~8-20 s measured
        log(f"nat-bench {sub} rc {rc}")
    return 0


def parse_rx(out):
    m = re.findall(r"SUMMARY rx (\d+) B: ([\d.]+) kpps", out)
    v = re.findall(r'"vpe0": ([\d.]+), "vpe1": ([\d.]+)', out)
    return (float(m[-1][1]), float(v[-1][0]), float(v[-1][1])) if m and v else (None, None, None)


def parse_zc(out):
    m = re.findall(r"= ([\d.]+) kpps .*?busy VPE0/VPE1 (\d+)/(\d+)%", out)
    return (float(m[-1][0]), float(m[-1][1]), float(m[-1][2])) if m else (None, None, None)


def cmd_meas(a):
    mark = CONSOLE.stat().st_size
    row = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "core": a.core, "label": a.label, "set": a.set}
    if a.set:
        ssh(a.set)
    napi = ["--napi", a.napi]
    for m in a.m.split(","):
        if m.startswith("rx"):
            ln = m[2:]
            rc, out = run([PY, "scripts/ceiling_rxtx.py", "--tag", f"ro{a.label}", "--n", "1", "--sizes", ln, "--modes", "rx", "--secs", "6", "--no-setup",
                           *(["--napi", a.napi] if a.napi in ("irq", "irq1") else [])], 90)  # 6 s run + dumps ~20 s, x4
            k, v0, v1 = parse_rx(out)
        elif m.startswith("fwd") or m.startswith("stack"):
            ln = re.sub(r"\D", "", m)
            extra = ["--zc-only"] if m.startswith("fwd") else []
            rc, out = run([PY, "scripts/zc_bench.py", "--nat", *napi, "--secs", str(a.secs), "--len", ln, *extra], 120)  # 2 runs x (secs+~15 s)
            k, v0, v1 = parse_zc(out)
            if m.startswith("stack"):
                s = re.findall(r"stack: natwan rx \d+ pkts = ([\d.]+) kpps .*?busy VPE0/VPE1 (\d+)/(\d+)%", out)
                k, v0, v1 = (float(s[-1][0]), float(s[-1][1]), float(s[-1][2])) if s else (None, None, None)
        elif m == "tcp":
            rc, out = run([PY, "scripts/zc_bench.py", "--tcp", "--nat", "--secs", "10", *napi], 400)  # 4 runs x (10 s + ~40 s dumps) = 200 s measured-ish, x2
            t = re.findall(r"(stack|zc\+nat)( \(reverse\))?: iperf3 TCP P4 ([\d.?]+) Mbit/s", out)
            row["tcp"] = {f"{n}{'_rev' if r else '_fwd'}": x for n, r, x in t}
            log(f"{a.label} tcp: {row['tcp']}")
            continue
        else:
            continue
        row[m] = {"kpps": k, "vpe0": v0, "vpe1": v1}
        log(f"{a.label} {m}: {k} kpps VPE0/1 {v0}/{v1} (rc {rc}) temp {temp() / 1000:.1f} C alive {alive()}")
    if a.reset:
        ssh(a.reset)
    with CONSOLE.open("rb") as fh:
        fh.seek(mark)
        bad = BAD.findall(fh.read())
    row["bad_console"] = [b.decode() for b in bad[:3]]
    row["alive"] = alive()
    row["temp_mC"] = temp()
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    log(f"ROW {json.dumps(row)}")
    return 0 if row["alive"] else 5


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = ap.add_subparsers(dest="cmd", required=True)
    b = sp.add_parser("boot")
    b.add_argument("--core", choices=list(CORES), required=True)
    b.add_argument("--cpu", type=int, default=1350, help="CPU MHz in the turbo pre line")
    b.add_argument("--kernel", default="mainline-7.4-rc1.bin")
    b.add_argument("--bootargs", default="")
    m = sp.add_parser("meas")
    m.add_argument("--core", default="608")
    m.add_argument("--label", required=True)
    m.add_argument("--set", default="")
    m.add_argument("--reset", default="")
    m.add_argument("--napi", default="irq1", choices=["irq", "irq1", "split"])
    m.add_argument("--secs", type=int, default=6)
    m.add_argument("--m", default="rx1400,fwd1400")
    a = ap.parse_args()
    return cmd_boot(a) if a.cmd == "boot" else cmd_meas(a)


if __name__ == "__main__":
    sys.exit(main())
