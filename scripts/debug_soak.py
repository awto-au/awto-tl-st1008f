#!/usr/bin/env python3
"""Repeated RAM boots of an OpenWrt image on sw2: did each boot hold, or reset by itself (#166)?

Each run = `./dev.py ramload uboot-mainline --stock-clocks --then IMAGE` (all its guards), then watch
the console log for a stock U-Boot banner after Linux (= reset) and SSH uptime until --hold seconds.
Reset uptime: wall time from `bootm` to the banner (upper bound, ~5 s poll), and the black-box
"previous boot ... after N s" the next boot prints (exact to the heartbeat). Output: tmp/debug-soak/<tag>-<time>/.
"""

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SER = ROOT / "private/serial/st1008-console.log"
IP = "192.168.25.56"  # sw2 bench mgmt
SSH = ["ssh", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", f"root@{IP}"]
BANNER = re.compile(rb"U-Boot 2011\.12")
LINUX = re.compile(rb"Linux version ")
BOOTM_TX = re.compile(rb"\[TX (\d\d:\d\d:\d\d)\] 'bootm ")
BLACKBOX = re.compile(rb"st1008f-blackbox: (previous boot #\d+ ended [^\r\n]*|no valid previous record[^\r\n]*)")
KLINE = re.compile(rb"^\[ *\d+\.\d+\] [^\r\n]*", re.M)
POLL_S = 5


def log(msg: str) -> None:
    print(f"{dt.datetime.now():%H:%M:%S} {msg}", flush=True)


def serial_since(off: int) -> bytes:
    with SER.open("rb") as f:
        f.seek(off)
        return f.read()


def ssh_uptime() -> int | None:
    try:
        r = subprocess.run(SSH + ["cut -d. -f1 /proc/uptime"], capture_output=True, text=True,
                           timeout=8)  # ConnectTimeout 4 + a cat; a hung board must not stall the poll
    except subprocess.TimeoutExpired:
        return None
    return int(r.stdout) if r.returncode == 0 and r.stdout.strip().isdigit() else None


def reset_in(buf: bytes) -> re.Match | None:
    """Stock U-Boot banner after the debug kernel's 'Linux version' = the board reset."""
    lx = LINUX.search(buf)
    return BANNER.search(buf, lx.end()) if lx else None


def stp_guard_power_cut(output: str) -> bool:
    return "FAIL: bridge STP not enabled" in output


def one_run(a, n: int, out: Path) -> dict:
    d = out / f"run{n:02d}"
    d.mkdir()
    off = SER.stat().st_size
    res = {"run": n, "start": f"{dt.datetime.now():%H:%M:%S}"}
    cmd = [sys.executable, str(ROOT / "dev.py"), "ramload", "uboot-mainline", "--stock-clocks", "--then", a.image]
    if a.bootargs:
        cmd += ["--bootargs", a.bootargs]
    cmd += [*(["--verbose-console"] if a.verbose_console else []), *(["--procd-watch"] if a.procd_watch else [])]
    with (d / "ramload.txt").open("w") as f:
        # one ramload: power/restart + TFTP + boot + STP + mgmt, ~3 min on the debug image; x2
        res["ramload_rc"] = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=420).returncode
    rl = (d / "ramload.txt").read_text(errors="replace")
    fails = [ln for ln in rl.splitlines() if ln.startswith(("FAIL", "TIMEOUT"))]
    res["setup_error"] = fails[-1][:160] if fails else ""
    # restart_board can also power-cycle after a missed software-reboot banner.
    if stp_guard_power_cut(rl):
        res["result"] = "SETUP-FAIL (power cut by guard)"
    else:
        last, t0 = 0, time.monotonic()
        while True:
            buf = serial_since(off)
            if reset_in(buf):
                res["result"] = "RESET"
                break
            up = ssh_uptime()
            if up is not None:
                if up < last:
                    res["result"] = "RESET"
                    break
                last = up
                if up >= a.hold:
                    res["result"] = "HELD"
                    break
            if time.monotonic() - t0 > a.hold + 240:  # boot reaches SSH ~100 s after ramload returns at worst
                res["result"] = "NO-SSH"
                break
            time.sleep(POLL_S)
        res["last_ssh_uptime"] = last
        res["detected"] = f"{dt.datetime.now():%H:%M:%S}"
    buf = serial_since(off)
    m = BOOTM_TX.findall(buf)
    if res["result"] == "RESET" and m:
        t_bootm = dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(m[-1].decode()))
        t_det = dt.datetime.combine(dt.date.today(), dt.time.fromisoformat(res["detected"]))
        res["reset_by_s"] = int((t_det - t_bootm).total_seconds())
    if res["result"] == "RESET":
        r = reset_in(buf)
        klines = KLINE.findall(buf[:r.start()]) if r else []
        res["last_kernel_line"] = klines[-1].decode(errors="replace")[:200] if klines else ""
    if res["result"] == "HELD":  # #166: which watchdog is /dev/watchdog (procd feeds only that one)?
        try:
            r = subprocess.run(SSH + ["for w in /sys/class/watchdog/watchdog*; do echo ${w##*/}"
                                      " $(readlink $w/device | sed 's|.*/||') $(cat $w/state 2>/dev/null); done"],
                               capture_output=True, text=True, timeout=10)  # two sysfs reads
            res["watchdogs"] = r.stdout.strip().replace("\n", "; ")
        except subprocess.TimeoutExpired:
            res["watchdogs"] = "?"
    if res["result"] in ("HELD", "NO-SSH"):
        with (d / "switch-logs.txt").open("w") as f:
            subprocess.run([sys.executable, str(ROOT / "dev.py"), "switch-logs", "--ip", IP, "--ephemeral-host-key",
                            "--logs-only"], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                           timeout=120)  # dmesg + logread over ssh, <30 s
    bb = BLACKBOX.findall(buf)
    res["blackbox_at_boot"] = bb[-1].decode(errors="replace") if bb else ""
    (d / "serial.log").write_bytes(serial_since(off))
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--hold", type=int, default=120, help="Linux uptime (s) that counts as held (default 120)")
    ap.add_argument("--image", default="openwrt-ours-6.18-debug")
    ap.add_argument("--bootargs", default="page_poison=1", help="appended kernel args (default page_poison=1)")
    ap.add_argument("--verbose-console", action="store_true", help="pass to ramload: full kernel console")
    ap.add_argument("--procd-watch", action="store_true", help="pass to ramload: log procd stalls (#166)")
    ap.add_argument("--stop-on-reset", action="store_true", help="stop after the first reset")
    ap.add_argument("--tag", default="soak")
    a = ap.parse_args()
    if not a.image.startswith("openwrt"):
        ap.error("--image must be an OpenWrt RAM image")
    out = ROOT / "tmp/debug-soak" / f"{a.tag}-{dt.datetime.now():%Y%m%d-%H%M%S}"
    out.mkdir(parents=True)
    log(f"soak {a.runs} x {a.image} '{a.bootargs}', hold {a.hold} s -> {out.relative_to(ROOT)}")
    runs = []
    for n in range(1, a.runs + 1):
        r = one_run(a, n, out)
        runs.append(r)
        log(f"run {n}: {r['result']}" + (f" by {r['reset_by_s']} s after bootm" if "reset_by_s" in r else "")
            + (f", ssh uptime {r.get('last_ssh_uptime')}" if r.get("last_ssh_uptime") else "")
            + (f" [{r['setup_error']}]" if r["setup_error"] else ""))
        (out / "summary.json").write_text(json.dumps(runs, indent=1))
        if a.stop_on_reset and r["result"] == "RESET":
            break
    # the black box each boot prints describes the previous boot: attribute it back
    for prev, cur in zip(runs, runs[1:]):
        prev["blackbox"] = cur["blackbox_at_boot"]
    (out / "summary.json").write_text(json.dumps(runs, indent=1))
    rows = ["| Run | Result | Reset by (s after bootm) | Black box (next boot) | Setup error |", "|---|---|---|---|---|"]
    for r in runs:
        rows.append(f"| {r['run']} | {r['result']} | {r.get('reset_by_s', '')} | {r.get('blackbox', '')} "
                    f"| {r['setup_error'][:70]} |")
    held = sum(r["result"] == "HELD" for r in runs)
    reset = sum(r["result"] == "RESET" for r in runs)
    rows.append(f"\n{held} held, {reset} reset, {len(runs) - held - reset} other, of {len(runs)}")
    (out / "summary.md").write_text("\n".join(rows) + "\n")
    print("\n".join(rows))
    return 0 if reset == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
