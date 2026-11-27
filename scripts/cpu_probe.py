#!/usr/bin/env python3
"""cpu_probe — does CPU MHz N hold at core 608 on the OpenWrt image, with a live bridge/SRAM knob? (#160)

- Sets the chain profile `cpu=N,ddr=662,sram=500,swcore=608`, reboots sw2 in software, applies the knob over ssh as soon as it answers,
  then runs the selftest xz decode (cpu.xz vs cpu.md5) in a loop pinned to each CPU for SECS; every wrong decode is counted.
- Knobs (live, devmem): none | dram_flip (CMUCR_OC0 0xb8000388 bit 9 cleared: MEM < CPU/2) | pulse_up / pulse_dn (CPU_SRAM_ASY_TIMING 0xb80040f8 [1:0] +-1).
- FAIL = a wrong decode, ssh lost for > 30 s, or an Oops in dmesg. Always puts the profile back to cpu=1325 (retries over ssh while a failing boot loops).
- Time limits: ssh wait after reboot 120 s (boot ~25 s, x4.8, a reboot loop shows as no stable ssh); poll every 10 s; SECS 180 (failures seen at 32-53 s, #160).
- `cpu_probe.py --cpu 1350 --knob dram_flip [--secs 180]`; log tmp/logs/cpu_probe.log
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IP = BENCH_IP
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes", "-q", f"root@{IP}"]
LOG = ROOT / "tmp/logs/cpu_probe.log"
BASE_PROFILE = "cpu=1325,ddr=662,sram=500,swcore=608"
KNOB = {"none": "true",
        "dram_flip": "devmem 0x18000388 32 0x0",
        "pulse_up": "devmem 0x180040f8 32 0x86",
        "pulse_dn": "devmem 0x180040f8 32 0x84"}
LOAD = ("rm -f /tmp/ld.*; for c in 0 1; do nice -n 19 taskset -c $c sh -c 'while :; do "
        "m=$(xz -dc /usr/share/st1008f-selftest/cpu.xz | md5sum | cut -d\" \" -f1); "
        "[ \"$m\" = 3902a5968ffd7ef5b46207dd60a7c934 ] && echo ok >> /tmp/ld.'$c' || echo bad >> /tmp/ld.'$c'; done' >/dev/null 2>&1 & done; echo started")


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(cmd, tmo=10):
    try:
        r = subprocess.run(SSH + [cmd], capture_output=True, text=True, errors="replace", timeout=tmo)
        return r.stdout.strip() if r.returncode == 0 else None
    except subprocess.TimeoutExpired:
        return None


def set_profile(profile):
    r = subprocess.run([sys.executable, "scripts/uboot_chain_env.py", "turbo", "set", profile, "--ssh", "--ip", IP],
                       capture_output=True, text=True, cwd=ROOT, timeout=60)
    return r.returncode == 0


def wait_ssh(limit, settle=False):
    """settle: also wait for uptime >= 40 s (boot-time flash writes, config-slot save, would collide with `turbo set`; seen failing at ~5 s)."""
    t0 = time.time()
    while time.time() - t0 < limit:
        up = ssh("cut -d. -f1 /proc/uptime", 5)
        if up and up.isdigit() and (not settle or int(up) >= 40):
            return True
    return False


def reboot_and_wait():
    """Software reboot; wait for ssh to drop (<= 30 s: reboot -f is immediate, a still-answering ssh means it has not gone down), then for it to return (<= 120 s)."""
    ssh("sync; reboot -f", 5)
    t0 = time.time()
    while time.time() - t0 < 30 and ssh("echo up", 3) == "up":
        pass
    return wait_ssh(120)


def restore():
    t0 = time.time()
    while time.time() - t0 < 180:  # a failing boot loops every ~30-60 s; each boot answers ssh for >= 25 s
        if wait_ssh(10, True) and set_profile(BASE_PROFILE):
            log(f"profile restored to {BASE_PROFILE}")
            return reboot_and_wait()
    log("RESTORE FAILED: profile may still be the trial one")
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cpu", type=int, required=True)
    ap.add_argument("--knob", choices=list(KNOB), default="none")
    ap.add_argument("--secs", type=int, default=180)
    ap.add_argument("--extra", default="", help="more profile keys, e.g. sedram=0 (our U-Boot, #160)")
    a = ap.parse_args()
    profile = f"cpu={a.cpu},ddr=662,sram=500,swcore=608" + (f",{a.extra}" if a.extra else "")
    log(f"=== cpu {a.cpu} knob {a.knob} secs {a.secs}")
    status = "PASS"
    try:
        if not wait_ssh(60, True) or not set_profile(profile):
            log("could not set the trial profile")
            return 2
        if not reboot_and_wait():
            status = "FAIL: no ssh after reboot"
        else:
            clk = ssh("dmesg | grep 'LX frequency'")
            log(f"booted: {clk}")
            log(f"knob {a.knob}: {ssh(KNOB[a.knob] + '; devmem 0x18000388 32; devmem 0x180040f8 32')}")
            log(f"load: {ssh(LOAD)}")
            t0 = last_ok = time.time()
            while time.time() - t0 < a.secs:
                r = ssh("cat /tmp/ld.0 /tmp/ld.1 2>/dev/null | sort | uniq -c | tr '\\n' ' '; dmesg | grep -c -E 'Oops|BUG|Unable to handle'; true", 8)
                if r is None:
                    if time.time() - last_ok > 25:  # starved sshd answers within seconds; 25 s of silence = crash or hang
                        status = f"FAIL: ssh lost at {time.time() - t0:.0f} s"
                        break
                    continue
                last_ok = time.time()
                if " bad" in r or not r.endswith("0"):
                    status = f"FAIL at {time.time() - t0:.0f} s: {r}"
                    break
            else:
                log(f"final: {ssh('cat /tmp/ld.0 /tmp/ld.1 | sort | uniq -c | tr \"\\n\" \" \"')}; temp {ssh('cat /sys/class/thermal/thermal_zone0/temp')}")
    finally:
        ok = restore()
    log(f"RESULT cpu {a.cpu} knob {a.knob}: {status}; restore {'OK' if ok else 'FAILED'}")
    return 0 if status == "PASS" and ok else 1


if __name__ == "__main__":
    sys.exit(main())
