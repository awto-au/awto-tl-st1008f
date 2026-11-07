#!/usr/bin/env python3
"""nat161_compare — NAT TCP on the plain 7.4-rc1 kernel vs the OpenWrt image, one session, sw2 only (#161).

- Profile (both): core 508 raw regs, CPU 1350, DDR 662, LX 306, SRAM 500. Bench = nat_bench / zc_bench, 3 x 15 s TCP P4 fwd/rev.
- Per image: settings dump, then matrix irq {default, irq1} x mode {nat, nat-ft}, then zc+nat (zc_bench --tcp --napi irq1).
- `nat161_compare.py plain|openwrt [--align SETTING ...]`; rows tmp/logs/nat161.jsonl, log tmp/logs/nat161.log, dumps tmp/logs/nat161_<img>_settings.txt.
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
import nat_bench as nb  # noqa: E402
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/nat161.log"
JSONL = ROOT / "tmp/logs/nat161.jsonl"
NBJ = ROOT / "tmp/logs/nat_bench.jsonl"
PY = sys.executable
TAG = ""
TURBO = "turbo cpu=1350,ddr=662,lx=306,sram=500"
RAW = "mw.l 0xbb00e220 0x30626; mw.l 0xbb00e214 0x3b8; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff"
P = "/sys/module/rtl838x_eth/parameters"
ETH_IRQ = "$(awk '/eth0/{print +$1}' /proc/interrupts)"
DUMP = [
    "uname -a", "cat /proc/cmdline", "grep -r . " + P + " 2>/dev/null",
    "nft list flowtables", "nft list ruleset", "conntrack -L 2>&1 | tail -3", "conntrack -C 2>&1",
    "grep -r . /proc/sys/net/netfilter/ 2>/dev/null | grep -E 'acct|count|max|checksum|tcp_loose|liberal|flowtable|offload'",
    "ethtool -k eth0 2>&1", "ethtool -c eth0 2>&1", "cat /proc/interrupts", f"cat /proc/irq/{ETH_IRQ}/smp_affinity",
    "grep -r . /sys/class/net/eth0/queues/*/rps_cpus /sys/class/net/eth0/threaded /sys/class/net/eth0/gro_flush_timeout "
    "/sys/class/net/eth0/napi_defer_hard_irqs /sys/class/net/eth0/tx_queue_len /sys/class/net/eth0/mtu 2>&1",
    "tc qdisc show", "pidof irqbalance; echo irqbalance_rc=$?", "ps | grep -v ' \\[' | head -40",
    "grep -r . /proc/sys/net/core/ 2>/dev/null | grep -E 'rps|backlog|budget|busy|netdev'", "grep -E 'MemFree|MemTotal' /proc/meminfo",
    "ls /etc/rc.d 2>/dev/null | head -50", "grep -i -E 'bogomips|model name' /proc/cpuinfo",
]


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(cmd, tmo):
    """tmo = stated per call (measured stage x 1.25-3); expiry rc 124."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=tmo, cwd=ROOT, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"[timeout {tmo}s] {' '.join(cmd)[:100]}"


def sw(cmd, tmo=30):
    try:
        return nb.sw(cmd, check=False, tmo=tmo)
    except Exception as e:  # noqa: BLE001
        return f"[sw error {e}]"


def boot(img):
    if img == "plain":
        cmd = [PY, "dev.py", "ramload", "uboot-mainline", "--stock-clocks", "--then", "mainline-kernel", "--kernel", "mainline-7.4-rc1.bin",
               "--cage", "1", "--mgmt", "--pre", TURBO, "--pre", RAW]
    else:
        cmd = [PY, "dev.py", "ramload", "uboot-mainline", "--stock-clocks", "--no-linkcheck", "--then", "openwrt-ours", "--cage", "1",
               "--pre", TURBO, "--pre", RAW]
    for _try in range(2):  # earlier plain boots fail ~1 in 6 at ramload; one retry
        rc, out = run(cmd, 240)
        if rc == 0 or "base_baud" in out:  # core 508 shifts the UART base_baud: allowlist UNKNOWN line only, board is up
            rc = 0
            break
        log(f"[{img}] ramload failed, tail: {' | '.join(out.strip().splitlines()[-6:])[-600:]}")  # measured 35-40 s boot + stp ~15 s (openwrt), plain total cap 240 s in canary
    log(f"[{img}] ramload rc {rc}: {out.strip().splitlines()[-1][-150:] if out.strip() else ''}")
    if rc != 0:
        return False
    return canary.ensure_ssh(BENCH_IP)


def dump(img, tag):
    out = [f"##### {img} {tag} {time.strftime('%Y-%m-%dT%H:%M:%S%z')}"]
    for c in DUMP:
        out.append(f"\n$ {c}\n" + sw(c, 20))
    p = ROOT / f"tmp/logs/nat161_{img}_settings.txt"
    with p.open("a") as fh:
        fh.write("\n".join(out) + "\n")
    log(f"[{img}] settings dump {tag} -> {p.relative_to(ROOT)}")


def last_rows(n0):
    rows = [json.loads(ln) for ln in NBJ.read_text().splitlines()[n0:]]
    return rows


def nrows():
    return len(NBJ.read_text().splitlines()) if NBJ.exists() else 0


def bench(img, irq, mode, rev, secs=15):
    n0 = nrows()
    cmd = [PY, "scripts/nat_bench.py", "run", "--secs", str(secs), "-P", "4", "--label", f"n161-{img}-{irq}-{mode}"] + (["--reverse"] if rev else [])
    rc, out = run(cmd, 50)  # 15 s + 2 s omit + snaps ~ 25 s, x2
    rows = last_rows(n0)
    r = rows[-1] if rows else {}
    cpu = r.get("cpu", {})
    row = {"tag": TAG, "img": img, "irq": irq, "path": mode, "dir": "rev" if rev else "fwd", "mbit": r.get("mbps"), "rc": rc,
           "cpu0": cpu.get("cpu0"), "cpu1": cpu.get("cpu1"), "irq_s": r.get("irq_per_s"), "rx_pps": r.get("eth0_rx_pps"),
           "retrans": r.get("retrans"), "ct": r.get("conntrack")}
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    log(f"[{img}] {irq} {mode} {row['dir']}: {row['mbit']} Mbit/s cpu0 {row['cpu0']} cpu1 {row['cpu1']} irq/s {row['irq_s']} rx_pps {row['rx_pps']} rc {rc}")
    return row


def set_irq(img, irq):
    if irq == "irq1":
        sw(f"echo 0 > /sys/class/net/eth0/threaded; echo 2 > /proc/irq/{ETH_IRQ}/smp_affinity")
    log(f"[{img}] irq {irq}: affinity {sw(f'cat /proc/irq/{ETH_IRQ}/smp_affinity').strip()} threaded {sw('cat /sys/class/net/eth0/threaded').strip()}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("img", choices=["plain", "openwrt"])
    ap.add_argument("--no-boot", action="store_true")
    ap.add_argument("--reps", type=int, default=3)
    ap.add_argument("--only", help="comma list of irq:path cells, e.g. irq1:nat-ft (skips zc unless 'zc' listed)")
    ap.add_argument("--tag", default="", help="label for the rows (aligned-setting runs)")
    ap.add_argument("--pre-cmd", action="append", default=[], help="switch shell command run after setup (align a setting)")
    a = ap.parse_args()
    img = a.img
    global TAG
    TAG = a.tag
    if not a.no_boot and not boot(img):
        log(f"[{img}] BOOT FAIL")
        return 1
    if a.no_boot and not canary.ensure_ssh(BENCH_IP):
        log(f"[{img}] no ssh")
        return 1
    rc, o = run([PY, "scripts/nat_bench.py", "setup"], 90)  # OpenWrt: ping fails before `mode` opens fw4 input, rc ignored there
    log(f"[{img}] setup rc {rc}: {o.strip()[-300:] if rc else ''}")
    if rc and img == "plain":
        return 1
    rc, o = run([PY, "scripts/nat_bench.py", "mode", "nat-ft"], 60)
    for c in a.pre_cmd:
        log(f"[{img}] pre-cmd {c}: {sw(c).strip()[:200]}")
    dump(img, "after nat-ft mode")
    cells = a.only.split(",") if a.only else [f"{i}:{m}" for i in ("default", "irq1") for m in ("nat", "nat-ft")] + ["zc"]
    cur_irq = None
    for cell in cells:
        if cell == "zc":
            continue
        irq, mode = cell.split(":")
        if irq != cur_irq:
            set_irq(img, irq)
            cur_irq = irq
        run([PY, "scripts/nat_bench.py", "mode", mode], 60)
        for rev in (False, True):
            for _ in range(a.reps):
                bench(img, irq, mode, rev)
    if "zc" in cells:
        run([PY, "scripts/nat_bench.py", "mode", "nat-ft"], 60)
        for k in range(a.reps):
            rc, o = run([PY, "scripts/zc_bench.py", "--tcp", "--nat", "--napi", "irq1", "--secs", "15"], 220)  # 4 x ~35 s runs + setup
            for ln in o.splitlines():
                if "iperf3 TCP" in ln or "zc / stack" in ln:
                    log(f"[{img}] zc_bench#{k}: {ln[24:230]}")
            with JSONL.open("a") as fh:
                fh.write(json.dumps({"img": img, "path": "zc_bench", "rep": k, "rc": rc, "lines": [ln[24:230] for ln in o.splitlines() if "iperf3 TCP" in ln]}) + "\n")
    log(f"[{img}] DONE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
