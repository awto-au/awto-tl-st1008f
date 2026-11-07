#!/usr/bin/env python3
"""dss_probe — run the Realtek SDK die-speed-sensor (DSS) sequence on sw2 and print ring-oscillator counts (#68, #38, #151).

- Source: SDK `uboot-*/arch/otto40/plr/src/platform/9300/misc/dss.c` `dss_test()`; regs (phys = 0x18000000 + off):
  DSS0_CTRL 0x250, DSS1_CTRL 0x25c: data_in[25:6] wire_sel[5] ro_sel[4:2] dss_en[1] dss_rst_n[0];
  DSS0_DATA 0x260, DSS1_DATA 0x268: ready[30] wsort_go[29] count_out[19:0].
- Per (wire_sel 0..1, ro_sel 1..5): zero DSS1_CTRL twice + DSS1_DATA, write both CTRL words (data_in 0xfff, en, rst_n),
  poll DSS1_DATA>>30 == 1 (SDK bound 0x1000 reads), read counts; always zero both CTRL words afterwards.
- Count -> speed formula (other Realtek SoC, unverified here): cycle time = count * dss_clk period / 16384.
- Also logs the SoC temperature when available. `dss_probe.py [--ip A.B.C.D] [--tag TEXT]`  Log tmp/logs/dss_probe.log
"""
import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/dss_probe.log"
SSH = ["-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]

SNIPPET = r"""
B=0x18000000
rd() { devmem $((B+$1)) 32; }
wr() { devmem $((B+$1)) 32 $2; }
echo "temp: $(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null) cpu: $(grep -m1 BogoMIPS /proc/cpuinfo)"
echo "before: c0=$(rd 0x250) c1=$(rd 0x25c) d0=$(rd 0x260) d1=$(rd 0x268)"
for ws in 0 1; do
 for rs in 1 2 3 4 5; do
  wr 0x25c 0; wr 0x25c 0; wr 0x268 0
  v=$(( (0xfff<<6) | (ws<<5) | (rs<<2) | 2 | 1 ))
  wr 0x250 $v; wr 0x25c $v
  n=0; d1=0
  while [ $n -lt 4096 ]; do
    d1=$(rd 0x268); n=$((n+1))
    [ $(( (d1>>30) & 3 )) -eq 1 ] && break
  done
  d0=$(rd 0x260)
  echo "ws=$ws rs=$rs ctrl=$(printf 0x%08x $v) polls=$n dss0=$d0 dss1=$d1 count0=$(( d0 & 0xfffff )) count1=$(( d1 & 0xfffff ))"
 done
done
wr 0x250 0; wr 0x25c 0
echo "after: c0=$(rd 0x250) c1=$(rd 0x25c) d0=$(rd 0x260) d1=$(rd 0x268)"
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    r = subprocess.run(["ssh", *SSH, f"root@{a.ip}", SNIPPET], capture_output=True, text=True,
                       timeout=120)  # 10 combinations x <=4096 polls of a mapped register, ms each
    out = r.stdout + (("\n[stderr] " + r.stderr) if r.stderr.strip() and "Warning" not in r.stderr else "")
    print(out)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a.ip} {a.tag}\n{out}\n")


if __name__ == "__main__":
    main()
