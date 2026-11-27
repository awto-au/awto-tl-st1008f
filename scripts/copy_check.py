#!/usr/bin/env python3
"""copy_check — network-free copy/compare on a switch (#186): splits CPU+RAM faults from the NIC path.
- On the box: urandom -> /tmp/cc.src, md5 once; per round `cp` src -> dst, md5 both. Only per-round status lines cross ssh.
- Mismatch: `cmp -l` lists offset + octal bytes (first 8). Corrupted src = fault at rest; stops the run.
- Stall guard: no line within the limit = hung box, run fails. Log: tmp/logs/copy_check_<ip>.log
Usage: python3 scripts/copy_check.py IP [--rounds 40] [--size-mb 16]
"""
import argparse
import select
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
SETUP_S = 30  # ssh + urandom fill + first md5, unmeasured; replaced by 1.25 x slowest round once rounds run
FLOOR_S = 3  # round limit floor: ssh line latency + scheduler jitter on a 2-VPE box

REMOTE = r"""
S=/tmp/cc.src; D=/tmp/cc.dst
dd if=/dev/urandom of=$S bs=1M count={mb} 2>/dev/null || {{ echo ERR dd; exit 3; }}
W=$(md5sum $S | cut -d' ' -f1); echo REF $W
i=1
while [ $i -le {rounds} ]; do
  cp $S $D
  g=$(md5sum $D | cut -d' ' -f1); s=$(md5sum $S | cut -d' ' -f1)
  if [ "$g" = "$W" ] && [ "$s" = "$W" ]; then echo "ROUND $i ok"
  else echo "ROUND $i BAD dst=$g src=$s"; cmp -l $S $D | head -8 | sed 's/^/CMP /'
    [ "$s" = "$W" ] || {{ echo "SRC corrupted at rest"; break; }}
  fi
  i=$((i+1))
done
rm -f $S $D; echo DONE
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ip")
    ap.add_argument("--rounds", type=int, default=40)
    ap.add_argument("--size-mb", type=int, default=16)
    ap.add_argument("--stall-s", type=float, default=0,
                    help="fixed round limit when other load runs alongside (round time follows its phases; "
                         "liveness then comes from stress_trace / rail_watch); 0 = 1.25 x slowest round")
    a = ap.parse_args()
    (ROOT / "tmp/logs").mkdir(parents=True, exist_ok=True)
    log = (ROOT / f"tmp/logs/copy_check_{a.ip}.log").open("a")

    def say(m):
        line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a.ip} {m}"
        print(line, flush=True)
        log.write(line + "\n")
        log.flush()

    say(f"start: {a.rounds} rounds x {a.size_mb} MiB, on-box cp + md5")
    p = subprocess.Popen([*SSH, f"root@{a.ip}", REMOTE.format(mb=a.size_mb, rounds=a.rounds)],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    limit, last, slowest, bad, done = SETUP_S, time.monotonic(), 0.0, 0, False
    while True:
        r, _, _ = select.select([p.stdout], [], [], limit)
        now = time.monotonic()
        if not r:
            say(f"STALL: no line for {limit:.1f} s (limit), box hung or unreachable")
            p.kill()
            return 2
        line = p.stdout.readline()
        if not line:
            break
        line = line.rstrip()
        if line.startswith("ROUND"):
            dt = now - last
            slowest = max(slowest, dt)
            limit = a.stall_s or max(FLOOR_S, 1.25 * slowest)
            line += f" ({dt:.2f} s)"
            bad += " BAD " in line
        done |= line == "DONE"
        last = now
        say(line)
    p.wait()
    if not done:
        say(f"ssh ended without DONE (rc {p.returncode}): box crashed or dropped the session")
        return 2
    say(f"done: {bad} of {a.rounds} rounds corrupted")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
