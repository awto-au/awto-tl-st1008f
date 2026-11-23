#!/usr/bin/env python3
"""err_inventory — every error-like counter of a running switch, side by side for sw1 and sw2 (#186). Read-only.

- Sources: /proc/interrupts (ERR, MIS), /proc/net/{dev,snmp,netstat,softnet_stat}, /proc/vmstat (alloc stalls, OOM), /proc/meminfo
  (HardwareCorrupted), /sys/class/net/*/statistics, `ethtool -S` of every lanN (ASIC MIB), rteth debugfs rxq, MIPS unaligned counters,
  tainted flag, bus-timeout monitor and DMA mask registers (devmem).
- A counter is listed when its name looks like an error (err|drop|fifo|crc|fail|timeout|over|invalid|bad|miss|corrupt|collis|abort|discard|
  loss|alloc|stall|oom|unalign|trunc|short|long|jabber|frag|retrans) and the value is nonzero on at least one unit.
- Usage: python3 scripts/err_inventory.py [--ips 192.168.25.48,192.168.25.56]. Raw dump per unit: tmp/logs/err_inventory_<ip>.txt
"""
import argparse
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
NAME = re.compile(r"err|drop|fifo|crc|fail|timeout|over|invalid|bad|miss|corrupt|collis|abort|discard|loss|alloc|stall|oom|unalign|trunc|short|long|jabber|frag|retrans|ERR|MIS", re.I)

REMOTE = r'''
echo "## uptime $(cut -d. -f1 /proc/uptime)"
echo "## tainted $(cat /proc/sys/kernel/tainted)"
awk '/^ *(ERR|MIS):/{print "intr_"$1, $2}' /proc/interrupts
grep -E 'HardwareCorrupted|Slab|SUnreclaim|MemFree' /proc/meminfo | tr -d ':' | awk '{print "meminfo_"$1, $2}'
grep -E '^(oom_kill|allocstall|pgalloc_dma|pgscan|pgsteal|compact_fail|compact_stall|thp_|drop_|kswapd_low|pageoutrun|unevictable)' /proc/vmstat | awk '$2>0{print "vmstat_"$1, $2}'
for f in /proc/net/snmp /proc/net/netstat; do
  awk 'NR%2==1{n=split($0,h," "); p=h[1]} NR%2==0{for(i=2;i<=n;i++) print "net_"p"_"h[i], $i}' $f
done
awk '{printf "softnet_cpu%d_processed %d\nsoftnet_cpu%d_dropped %d\nsoftnet_cpu%d_time_squeeze %d\n", NR-1, strtonum("0x"$1), NR-1, strtonum("0x"$2), NR-1, strtonum("0x"$3)}' /proc/net/softnet_stat 2>/dev/null
for d in /sys/class/net/*; do n=$(basename $d); case $n in lo|br*|switch*|*.*) continue;; esac
  for s in $d/statistics/*; do v=$(cat $s 2>/dev/null); echo "netdev_${n}_$(basename $s) $v"; done
done
for p in 1 2 3 4 5 6 7 8; do ethtool -S lan$p 2>/dev/null | awk -v p=$p 'NR>1{gsub(":","",$1); print "asic_lan"p"_"$1, $2}'; done
for f in /sys/kernel/debug/rteth/rxq; do cat $f 2>/dev/null | awk '{print "rteth_"$1, $2}'; done
for f in /sys/kernel/debug/mips/unaligned_instructions /sys/kernel/debug/mips/unaligned_action; do [ -r $f ] && echo "mips_$(basename $f) $(cat $f)"; done
for r in 0x18005100 0x18005104 0x18005108 0x18005200 0x18005204 0x18005208 0x1800520c 0x18005210 0x18001004 0x1800e02c 0x1800e028 0x18000010 0x18000014; do echo "reg_$r $(devmem $r 32 2>/dev/null)"; done
dmesg | grep -c -i -E 'unaligned|bad page|BUG:|WARNING|rcu.*stall|hung task|ecc|uncorrect|slub|poison|corrupt|spurious|unexpected' | awk '{print "dmesg_suspect_lines", $1}'
'''


def collect(ip):
    r = subprocess.run([*SSH, f"root@{ip}", REMOTE], capture_output=True, text=True, timeout=90)
    raw = r.stdout
    (ROOT / f"tmp/logs/err_inventory_{ip}.txt").write_text(raw)
    d = {}
    for ln in raw.splitlines():
        p = ln.split()
        if len(p) >= 2 and not ln.startswith("##"):
            d[p[0]] = p[1]
        elif ln.startswith("## "):
            d[p[1]] = p[2] if len(p) > 2 else ""
    return d


def num(x):
    try:
        return int(x, 0)
    except (ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ips", default="192.168.25.48,192.168.25.56")
    a = ap.parse_args()
    ips = a.ips.split(",")
    data = {ip: collect(ip) for ip in ips}
    keys = sorted(set().union(*[set(d) for d in data.values()]))
    print(f"{'counter':58} " + " ".join(f"{ip:>16}" for ip in ips))
    for k in keys:
        vals = [data[ip].get(k) for ip in ips]
        nums = [num(v) for v in vals]
        reg = k.startswith("reg_")
        if reg or k in ("uptime", "tainted") or (NAME.search(k) and any(n for n in nums if n)):
            print(f"{k:58} " + " ".join(f"{str(v):>16}" for v in vals))


if __name__ == "__main__":
    main()
