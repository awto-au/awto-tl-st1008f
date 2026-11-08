#!/usr/bin/env python3
"""ow_reset_probe — boot an openwrt-ours* image on sw2, watch for a SoC reset by ping, keep kernel messages (#163).

- `ow_reset_probe.py IMAGE PROFILE [--boots N] [--secs S]`: IMAGE = ramload name (openwrt-ours, openwrt-ours-l3fix), PROFILE = default | c608_cpu1325.
- Per boot: ramload, ssh `dmesg -n 8`, `ssh logread -f` + `ping -D -i 1` for S s, then uptime + dmesg tail.
- Rows -> tmp/logs/ow_reset_probe.jsonl, per-boot kernel log tmp/logs/ow_reset_<image>_<profile>_<n>.klog. sw2 only.
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
from openwrt_core_stability import CON, PY, SSH, cfg, log, run, ssh, up_s  # noqa: E402

JSONL = ROOT / "tmp/logs/ow_reset_probe.jsonl"


def one_boot(image, profile, idx, secs, bootargs=""):
    off = CON.stat().st_size
    pre = []
    if profile != "default":
        turbo, rawl = cfg(profile)
        pre = ["--pre", turbo] + (["--pre", rawl] if rawl else [])
    cmd = ["./dev.py", "ramload", "uboot-mainline", "--stock-clocks", "--no-linkcheck", "--then", image, "--cage", "1"] + pre
    if bootargs:
        cmd += ["--bootargs", bootargs]
    t0 = time.time()
    rc, _ = run(cmd, 150)  # 35-40 s boot + stp ~15 s, x3 (as openwrt_core_stability)
    log(f"[{image} {profile} #{idx}] ramload rc {rc} in {time.time() - t0:.0f} s")
    row = {"image": image, "profile": profile, "boot": idx, "ramload_rc": rc, "date": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    up = False
    for _ in range(12):  # lan1 up ~4 s after port-up; 12 x <=10 s bounds the wait
        if run(["ping", "-c", "1", "-W", "2", IP], 6)[0] == 0 and up_s() is not None:
            up = True
            break
    row["up0"] = up_s() if up else None
    klog = ROOT / f"tmp/logs/ow_reset_{image}_{profile}_{idx}.klog"
    if up:
        ssh("dmesg -n 8", 10)
        ssh("echo w > /proc/sysrq-trigger", 10)
        lf = klog.open("w")
        lr = subprocess.Popen(SSH + ["logread -f"], stdout=lf, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        # ping -i 1 is the clock: per-reply timestamps give the loss time
        _, pout = run(["ping", "-D", "-c", str(secs), "-i", "1", "-W", "1", IP], secs + 20)
        lr.terminate()
        lf.close()
        recv = [ln for ln in pout.splitlines() if "bytes from" in ln]
        row["replies"] = len(recv)
        row["last_reply_ts"] = re.search(r"\[(\d+\.\d+)\]", recv[-1])[1] if recv else None
        row["first_reply_ts"] = re.search(r"\[(\d+\.\d+)\]", recv[0])[1] if recv else None
    row["uptime_end"] = up_s()
    txt = CON.open("rb")
    txt.seek(off)
    ctext = txt.read().decode("utf-8", "replace")
    row["reset_seen"] = bool(re.search(r"U-Boot|DRAM:|Realtek.*Boot|reset", ctext[ctext.find("bootm"):][3000:], re.I))
    row["console_tail"] = ctext.strip().splitlines()[-6:]
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    log(f"RESULT {image} {profile} #{idx}: up0 {row['up0']} replies {row.get('replies')}/{secs} uptime_end {row['uptime_end']}")
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("profile")
    ap.add_argument("--boots", type=int, default=3)
    ap.add_argument("--secs", type=int, default=150)
    ap.add_argument("--bootargs", default="", help="e.g. ignore_loglevel: kernel messages on the console")
    a = ap.parse_args()
    for i in range(1, a.boots + 1):
        one_boot(a.image, a.profile, i, a.secs, a.bootargs)


if __name__ == "__main__":
    main()
