#!/usr/bin/env python3
"""spd_sensor_probe — release the RTL9303 die speed sensors from reset and read the ring-oscillator counts (#68, #38).

- Regs (SDK rtk-dms1250 rtl9300_soc_reg.h:1136-1210), phys = 0x18000000 + offset. SPD_SENSOR0 0x618: reset bits 31..28 =
  genr0 genr1 mini0 mini1; per-sensor wire_sel / ro_sel[2:0] at bits 15/14:12, 11/10:8, 7/6:4, 3/2:0.
  SPD_SENSOR1..4 (0x61c..0x628) = genr0 genr1 mini0 mini1: bit 31 dss_ready, 30 data_read_ack, 29 wrost_go, 19:0 count.
- Runs on sw2 over ssh (one command, loop on the board). Writes only these 9 words; restores SPD_SENSOR0..8 afterwards.
- `spd_sensor_probe.py [--ip A.B.C.D]`  Log tmp/logs/spd_sensor_probe.log
"""
import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/spd_sensor_probe.log"
BASE = 0x18000618
SSH = ["-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]

# on-board: sel = ro_sel 0..7 x wire_sel 0..1 for the generator sensor; read ready/count up to 20 times
SNIPPET = r"""
R=0x18000618
rd() { devmem $1 32; }
echo "before: $(for i in 0 1 2 3 4 5 6 7 8; do rd $((R+4*i)); done | tr '\n' ' ')"
k=0
for name in genr0 genr1 mini0 mini1; do
 reg=$((R+4*(k+1))); rst=$((1<<(31-k))); ws=$((15-4*k)); rs=$((12-4*k))
 for w in 0 1; do
  for ro in 0 1 2 3 4 5 6 7; do
   devmem $reg 32 0
   devmem $R 32 $(( rst | (w<<ws) | (ro<<rs) ))
   devmem $reg 32 $((1<<29))
   n=0; s=0
   while [ $n -lt 20 ]; do
     s=$(rd $reg); n=$((n+1))
     [ $(( s & (1<<31) )) -ne 0 ] && break
   done
   echo "$name wire=$w ro=$ro s0=$(rd $R) reg=$(printf 0x%08x $s) polls=$n ready=$(( (s>>31)&1 )) count=$(( s & 0xfffff ))"
   devmem $reg 32 $((1<<30))
  done
 done
 devmem $reg 32 0; devmem $R 32 0
 k=$((k+1))
done
echo "after restore: $(for i in 0 1 2 3 4 5 6 7 8; do rd $((R+4*i)); done | tr '\n' ' ')"
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    a = ap.parse_args()
    r = subprocess.run(["ssh", *SSH, f"root@{a.ip}", SNIPPET], capture_output=True, text=True,
                       timeout=90)  # 64 x (4 writes + <=20 reads) of mapped registers, ms each
    out = r.stdout + (("\n[stderr] " + r.stderr) if r.stderr.strip() else "")
    print(out)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a.ip}\n{out}\n")


if __name__ == "__main__":
    main()
