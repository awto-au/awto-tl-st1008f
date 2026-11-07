#!/usr/bin/env python3
"""dss_soak — long background soak of sw2: temperature + die-speed-sensor counts + uptime, with optional CPU load (#151, #149).

- Every INTERVAL s one ssh reads: uptime, load, thermal_zone0, and DSS1 counts for the 10 (wire_sel, ro_sel) combos of
  scripts/dss_probe.py. CSV: tmp/logs/dss_soak.csv. Purpose: does die speed / temperature drift or the board die under
  load at the current clocks (heat-vs-speed theory), and when exactly did it die.
- `--load N` starts N busy loops on the board (pids in /tmp/dss_soak.pids), always killed at the end.
- Stops after --minutes, or after 3 consecutive ssh failures (board dead: the last good row + the failure time are the data).
- `dss_soak.py [--minutes 60] [--interval 10] [--load 2] [--ip A.B.C.D] [--tag TEXT]`
"""
import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSV = ROOT / "tmp/logs/dss_soak.csv"
SSH = ["-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
COMBOS = [(ws, rs) for ws in (0, 1) for rs in (1, 2, 3, 4, 5)]

SAMPLE = r"""
B=0x18000000
rd() { devmem $((B+$1)) 32; }
wr() { devmem $((B+$1)) 32 $2; }
printf "%s %s %s " "$(cut -d' ' -f1 /proc/uptime)" "$(cut -d' ' -f1 /proc/loadavg)" "$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null)"
for ws in 0 1; do for rs in 1 2 3 4 5; do
  wr 0x25c 0; wr 0x25c 0; wr 0x268 0
  wr 0x25c $(( (0xfff<<6) | (ws<<5) | (rs<<2) | 3 ))
  n=0; d=0
  while [ $n -lt 64 ]; do d=$(rd 0x268); n=$((n+1)); [ $(( (d>>30) & 3 )) -eq 1 ] && break; done
  printf "%s " $(( d & 0xfffff ))
done; done
wr 0x25c 0
echo
"""


def ssh(ip, cmd, tmo):
    try:
        r = subprocess.run(["ssh", *SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=tmo)
        return r.returncode, r.stdout.strip()
    except subprocess.TimeoutExpired:
        return 255, ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--interval", type=float, default=10)  # 10 s: temperature moves over minutes; DSS read ~0.5 s
    ap.add_argument("--load", type=int, default=0)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    CSV.parent.mkdir(parents=True, exist_ok=True)
    new = not CSV.exists()
    fh = CSV.open("a")
    if new:
        fh.write("iso,tag,uptime_s,load1,temp_mC," + ",".join(f"ws{w}rs{r}" for w, r in COMBOS) + "\n")
    if a.load:
        ssh(a.ip, "for i in $(seq %d); do (while :; do :; done) & echo $! >> /tmp/dss_soak.pids; done" % a.load, 10)
    end = time.time() + a.minutes * 60
    fails = 0
    try:
        while time.time() < end:
            t = time.time()
            rc, out = ssh(a.ip, SAMPLE, 20)  # sample ~0.5 s; 20 s names a hung board under load
            iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            if rc == 0 and out:
                fails = 0
                fh.write(f"{iso},{a.tag},{','.join(out.split())}\n")
            else:
                fails += 1
                fh.write(f"{iso},{a.tag},FAIL{fails}\n")
            fh.flush()
            if fails >= 3:
                fh.write(f"{iso},{a.tag},STOP board unreachable 3x\n")
                break
            time.sleep(max(0, a.interval - (time.time() - t)))  # fixed sampling period, see docstring
    finally:
        if a.load:
            ssh(a.ip, "kill $(cat /tmp/dss_soak.pids) 2>/dev/null; rm -f /tmp/dss_soak.pids", 10)
        fh.close()


if __name__ == "__main__":
    main()
