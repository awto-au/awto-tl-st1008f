#!/usr/bin/env python3
"""cpuport_speed_ab — CPU port 28 SPD_SEL A/B on sw2 (#148, docs/NAT-PROGRESS.md).

- Writes MAC_FORCE_MODE_CTRL(28) (phys 0x1b00ca8c) over the CONSOLE (the SSH path rides the CPU port).
- Per value: set, wait for ping (<= 10 x 2 s), run `zc_bench.py --nat --napi irq1`, log the zc+nat line.
- Always restores 0x217 (1G) over the console, also on error.
- Needs: sw2 on the 7.3 image at picks clocks, `nat-bench setup` done. Log tmp/logs/cpuport_speed_ab.log
- `cpuport_speed_ab.py [--values 0x217,0x22F,0x237]`  (SPD_SEL = bits 6:3: 2=1G 4=10G 5=2.5G 6=5G)
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/cpuport_speed_ab.log"
REG = "0x1b00ca8c"
SW2 = "192.168.25.56"


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def console(cmd):
    r = subprocess.run([sys.executable, str(ROOT / "scripts/switch_console.py"), "send", cmd],
                       capture_output=True, text=True, timeout=30)  # one console line, answer is immediate
    return r.stdout


def ping_ok():
    for _ in range(10):  # ping -W2 paces itself: 10 x 2 s = 20 s for ARP/link to settle after the write
        if subprocess.run(["ping", "-c1", "-W2", SW2], capture_output=True).returncode == 0:
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--values", default="0x217,0x22F,0x237")
    a = ap.parse_args()
    try:
        for v in a.values.split(","):
            console(f"devmem {REG} 32 {v}")
            up = ping_ok()
            if not up:
                log(f"{v}: sw2 unreachable after the write (link/traffic dead)")
                console(f"devmem {REG} 32 0x217")
                if not ping_ok():
                    log("restore to 0x217 did not bring sw2 back: needs ramload")
                    return 1
                continue
            r = subprocess.run([sys.executable, str(ROOT / "scripts/zc_bench.py"), "--nat", "--napi", "irq1", "--secs", "10"],
                               capture_output=True, text=True, timeout=240)  # 2 x 10 s runs + setup, x ~8 margin
            line = next((x for x in r.stdout.splitlines() if "zc+nat:" in x), "no zc+nat line: " + r.stdout[-200:])
            log(f"{v}: {line.split(' ', 1)[-1][:230]}")
    finally:
        console(f"devmem {REG} 32 0x217")
        log(f"restored {REG} = 0x217; reads: " + console(f"devmem {REG} 32").strip().splitlines()[-2:][0])
    return 0


if __name__ == "__main__":
    sys.exit(main())
