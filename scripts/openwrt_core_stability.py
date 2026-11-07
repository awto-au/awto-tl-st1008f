#!/usr/bin/env python3
"""openwrt_core_stability — OpenWrt-image stability per switch-core / CPU setting on sw2 (#160).

- `openwrt_core_stability.py CONFIG [--boots N] [--start K]`: N fresh ramloads of openwrt-ours, load each, stop at the first FAIL.
- Load: selftest, nat_bench setup + mode nat, iperf3 TCP -P 4 120 s (one interface), selftest again; PASS = >= 180 s of load, no oops, ssh up.
- Rows -> tmp/logs/openwrt_core_stability.jsonl, log tmp/logs/openwrt_core_stability.log. sw2 only (192.168.25.56).
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from boards import BENCH_IP as IP  # noqa: E402

LOG = ROOT / "tmp/logs/openwrt_core_stability.log"
JSONL = ROOT / "tmp/logs/openwrt_core_stability.jsonl"
CON = ROOT / "private/serial/st1008-console.log"
PY = sys.executable
SSH = ["ssh", "-q", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "BatchMode=yes", f"root@{IP}"]
BAD = re.compile(r"Oops|\bBUG\b|Kernel panic|gro_list_prepare|Unhandled kernel|Call Trace|Bad page|Fatal exception|Kernel bug")
TURBO = "turbo cpu={cpu},ddr={ddr},lx={lx},sram={sram}"


def raw(e220, e214):
    return (f"mw.l 0xbb00e220 {e220}; mw.l 0xbb00e214 {e214}; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff")


# name -> (turbo line, raw clock line or None); e220/e214 from docs/CLOCKS.md switch-core table
CONFIGS = {
    "c408": (TURBO.format(cpu=1350, ddr=662, lx=306, sram=500), None),
    "c608_cpu1000": (TURBO.format(cpu=1000, ddr=600, lx=306, sram=250), raw("0x36826", "0x478")),
    "c608_raw": (TURBO.format(cpu=1350, ddr=662, lx=306, sram=500), raw("0x36826", "0x478")),
    "c608_swc2": ("turbo cpu=1350,ddr=662,sram=500,swcore=608", None),
    "c508": (TURBO.format(cpu=1350, ddr=662, lx=306, sram=500), raw("0x30626", "0x3b8")),
    "c575": (TURBO.format(cpu=1350, ddr=662, lx=245, sram=500), raw("0x34a26", "0x438")),
}


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(cmd, tmo):
    """tmo is stated per call: measured stage time x 1.25-3; expiry returns 124 and is logged by the caller."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=tmo, cwd=ROOT, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"[timeout {tmo}s] {' '.join(cmd)[:100]}"


def ssh(cmd, tmo=20):
    try:
        return subprocess.run(SSH + [cmd], capture_output=True, text=True, errors="replace", timeout=tmo).stdout
    except subprocess.TimeoutExpired:
        return ""


def up_s():
    u = ssh("cut -d. -f1 /proc/uptime", 10).split()
    return int(u[-1]) if u and u[-1].isdigit() else None


def temp():
    t = ssh("cat /sys/class/thermal/thermal_zone0/temp", 10).split()
    return round(int(t[-1]) / 1000, 1) if t and t[-1].isdigit() else None


def console_new(off):
    with CON.open("rb") as f:
        f.seek(off)
        return f.read().decode("utf-8", "replace")


def first_bad(off):
    txt = console_new(off)
    for ln in txt.splitlines():
        if BAD.search(ln):
            return ln.strip()[:200]
    return None


def one_boot(name, idx):
    turbo, rawl = CONFIGS[name]
    row = {"config": name, "boot": idx, "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "result": "FAIL"}
    off = CON.stat().st_size
    pre = ["--pre", turbo]
    if rawl:
        pre += ["--pre", rawl]
    pre += ["--pre", "md.l 0xbb00e220 1", "--pre", "md.l 0xbb00e214 1"]
    cmd = ["./dev.py", "ramload", "uboot-mainline", "--stock-clocks", "--no-linkcheck", "--then", "openwrt-ours", "--cage", "1"] + pre
    t0 = time.time()
    rc, out = run(cmd, 150)  # measured 35-40 s boot + stp ~15 s; 150 s = ~3x, expiry = BOOT FAIL
    log(f"[{name} #{idx}] ramload rc {rc} in {time.time() - t0:.0f} s")
    up = False
    for _ in range(12):  # ~lan1 up 4 s after port-up; 12 tries x <=10 s bound the wait
        if run(["ping", "-c", "1", "-W", "2", IP], 6)[0] == 0 and up_s() is not None:
            up = True
            break
        run([PY, "scripts/switch_console.py", "send", "killall dropbear; dropbear -R -B", "--secs", "2"], 20)
    row["first_oops"] = first_bad(off)
    if not up:
        row["why"] = "BRINGUP: no ssh after ramload (kernel alive, no oops)"
        row["eth0"] = run([PY, "scripts/switch_console.py", "send", "ip -s link show eth0", "--secs", "3"], 20)[1][-400:]
        row["bringup"] = True
        return finish(row, off)
    u0, t_up = up_s(), time.time()
    regs = ssh("devmem 0x1b00e200 32; devmem 0x1b00e214 32; devmem 0x1b00e220 32; devmem 0x18001200 32", 15).split()
    dm = ssh("dmesg | grep -i -E 'base_baud|watchdog|wdt|bogomips'; grep -i bogomips /proc/cpuinfo | head -1", 15)
    cl = [ln.strip() for ln in console_new(off).splitlines() if "clocks:" in ln or "turbo OK" in ln or "base_baud" in ln]
    bb = re.search(r"base_baud = (\d+)", dm + console_new(off))
    row.update(regs=regs, lx_mhz=round(int(bb.group(1)) * 16 / 1e6, 1) if bb else None, clocks=cl[-4:],
               wdt=[ln for ln in dm.splitlines() if re.search(r"watchdog|wdt", ln, re.I)][:3], temp0=temp(), up0=u0)
    log(f"[{name} #{idx}] up {u0} s regs {regs} LX {row['lx_mhz']} wdt {row['wdt']} temp {row['temp0']}")
    steps = [
        ("selftest1", [PY, "scripts/selftest.py", "--last"], 30),  # boot-time run (~26 s), waited for below
        ("natsetup", [PY, "scripts/nat_bench.py", "setup"], 60),
        ("natmode", [PY, "scripts/nat_bench.py", "mode", "nat"], 40),
        ("iperf120", [PY, "scripts/nat_bench.py", "run", "--secs", "120", "-P", "4"], 160),  # 120 s + 2 s omit + snaps
        ("selftest2", [PY, "scripts/selftest.py"], 90),
        ("iperf30r", [PY, "scripts/nat_bench.py", "run", "--secs", "30", "-P", "4", "--reverse"], 60),  # pads the load past 180 s
    ]
    ssh("while pidof st1008f-selftest >/dev/null; do usleep 500000; done", 60)  # boot selftest ~26 s, x2
    t_load = time.time()
    for sname, c, tmo in steps:
        rc, o = run(c, tmo)
        for _ in range(3):  # boot-time run may start after the pidof wait: wait again, re-read
            if not (sname == "selftest1" and rc == 2):
                break
            ssh("while pidof st1008f-selftest >/dev/null; do usleep 500000; done", 60)  # x2 of ~26 s
            rc, o = run(c, tmo)
        tail = " | ".join(ln[-150:] for ln in o.strip().splitlines()[-2:])
        log(f"[{name} #{idx}] {sname} rc {rc}: {tail}")
        row[sname] = rc
        bad = first_bad(off)
        if bad or not (up_s() is not None):
            row["first_oops"] = bad
            row["fail_step"] = sname
            row["fail_uptime_est"] = u0 + int(time.time() - t_up)
            row["why"] = "oops" if bad else "ssh down"
            return finish(row, off)
        if sname.startswith("selftest") and rc == 1:  # 2 s item timeouts (sfp/asic) are noise at any clock: only cpu/mem count
            row[sname + "_fail"] = re.findall(r"^\S+\s+(\w+)\s+FAIL", o, re.M)
            rc = 1 if any(x in ("cpu", "mem") for x in row[sname + "_fail"]) else 0
        if sname.startswith("selftest") and rc != 0:
            row["why"] = f"{sname} FAIL rc {rc}"
            row["fail_step"] = sname
            row["fail_uptime_est"] = u0 + int(time.time() - t_up)
            return finish(row, off)
        if sname.startswith("iperf") and rc != 0:
            row["why"] = f"iperf rc {rc}"
            row["fail_step"] = sname
            row["fail_uptime_est"] = u0 + int(time.time() - t_up)
            return finish(row, off)
    row["load_s"] = int(time.time() - t_load)
    row["temp1"] = temp()
    if row["load_s"] < 180:
        row["why"] = f"load only {row['load_s']} s"
        return finish(row, off)
    row["result"] = "PASS"
    return finish(row, off)


def finish(row, off):
    row["uptime_end"] = up_s()
    row["first_oops"] = row.get("first_oops") or first_bad(off)
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    log(f"RESULT {row['config']} #{row['boot']}: {row['result']} {row.get('why', '')} oops={row['first_oops']} fail_uptime~{row.get('fail_uptime_est')} s temp {row.get('temp0')}->{row.get('temp1')}")
    return "BRINGUP" if row.get("bringup") else row["result"] == "PASS"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("config", choices=sorted(CONFIGS))
    ap.add_argument("--boots", type=int, default=3)
    ap.add_argument("--start", type=int, default=1)
    a = ap.parse_args()
    done = bring = 0
    i = a.start
    while done < a.boots:
        r = one_boot(a.config, i)
        i += 1
        if r == "BRINGUP":
            bring += 1
            if bring > 3:
                log(f"{a.config}: 4 bring-up failures, stop")
                return 2
        elif r is False:
            log(f"{a.config}: stop after failure at boot {i - 1}")
            return 1
        else:
            done += 1
    log(f"{a.config}: {a.boots}/{a.boots} PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
