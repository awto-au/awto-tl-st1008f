#!/usr/bin/env python3
"""stack_normalize — make a booted bench stack (A upstream OpenWrt, B ours OpenWrt, C plain kernel) identical
in everything except the kernel / OpenWrt stack under test; run BEFORE every bench. NAT-STACK-TESTS.md.

Steps (ssh to the switch, nothing on the host except the push):
  1. push the pinned tools to /tmp/stack-tools: static iperf3 (build_iperf3_static.py), ip-full + tc-full + libs
     (--pack copies them from B's root-realtek); symlinks /usr/bin/iperf3, /sbin/ip, /sbin/tc point at them.
  2. stop non-essential services (OpenWrt only): collectd lldpd uhttpd sysntpd dnsmasq odhcpd snmpd metricsd rpcd cron irqbalance.
     Kept: dropbear, network, procd/ubusd/netifd, logd, urngd, fan/led/gpio/poe, st1008f-linkwatch (loop guard).
  3. firewall stop, `nft flush ruleset`, load mainline/fw4-b.nft; one `stack-mgmt` accept for the mgmt interface (C's is lan1, not switch.1).
  4. sysctls (SYSCTLS below), rp_filter 0 everywhere, kernel.printk 1 4 1 7.
  5. RPS/XPS 0 on every netdev, eth0 qdisc, offloads (OFFLOADS), IRQ affinity (--napi).
  6. snapshot -> tmp/logs/stack_snapshot-<stack>[-<tag>].json (diffed by stack_compare.py's gate).
`--dry-run` prints every ssh command and the remote scripts; nothing is sent. Log: tmp/logs/stack_normalize.log
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/stack_normalize.log"
TOOLS = ROOT / "tmp/stack-tools"
OWRT_ROOT = ROOT / "tmp/openwrt-build/staging_dir/target-mips_24kc_musl/root-realtek"
FW4 = ROOT / "mainline/fw4-b.nft"
BENCH_IP = "192.168.25.56"  # scripts/boards.py BENCH_IP (sw2); not imported: boards probes the host NIC at import
REMOTE = "/tmp/stack-tools"
FLAVOUR = {"A": "owrt", "B": "owrt", "C": "mainline"}

# ---- the common settings (value + why) -------------------------------------------------------------------------
# net.* values: B image's measured values where it had one (nat161_openwrt_settings.txt), else the kernel default.
SYSCTLS = [
    ("net.ipv4.ip_forward", "1"), ("net.ipv6.conf.all.forwarding", "1"),
    ("net.netfilter.nf_conntrack_max", "8192"),         # B and C measured 8192
    ("net.netfilter.nf_conntrack_acct", "1"),           # nat_bench.py sets 1 per run
    ("net.netfilter.nf_conntrack_checksum", "0"),       # B 0 (OpenWrt sysctl.conf), plain kernel default 1: differed in #161 dumps
    ("net.netfilter.nf_conntrack_tcp_loose", "1"), ("net.netfilter.nf_conntrack_tcp_be_liberal", "0"),
    ("net.netfilter.nf_flowtable_tcp_timeout", "30"), ("net.netfilter.nf_flowtable_udp_timeout", "30"),
    ("net.netfilter.nf_conntrack_tcp_timeout_established", "7440"), ("net.netfilter.nf_conntrack_udp_timeout", "60"),
    ("net.netfilter.nf_conntrack_udp_timeout_stream", "180"),
    ("net.core.netdev_budget", "300"), ("net.core.netdev_budget_usecs", "20000"),  # 2 s/HZ at HZ 100; plain HZ 250 gave 8000
    ("net.core.netdev_max_backlog", "1000"), ("net.core.rps_sock_flow_entries", "0"),
    ("net.core.rmem_default", "212992"), ("net.core.wmem_default", "212992"),
    ("net.core.rmem_max", "4194304"), ("net.core.wmem_max", "4194304"),
    ("net.ipv4.tcp_rmem", "4096 131072 4194304"), ("net.ipv4.tcp_wmem", "4096 16384 4194304"),
    ("net.ipv4.tcp_congestion_control", "cubic"), ("net.ipv4.tcp_sack", "1"), ("net.ipv4.tcp_timestamps", "1"),
    ("net.ipv4.tcp_window_scaling", "1"), ("net.ipv4.tcp_ecn", "0"), ("net.ipv4.tcp_syncookies", "1"),
    ("net.ipv4.tcp_fin_timeout", "30"),
    ("net.ipv4.conf.all.rp_filter", "0"), ("net.ipv4.conf.default.rp_filter", "0"),  # strict rpf = extra fib lookup per packet; OpenWrt sets 1
    ("net.core.bpf_jit_enable", "1"), ("net.ipv4.tcp_keepalive_time", "120"),  # OpenWrt defaults; plain kernel 0 / 7200
    ("kernel.printk", "1 4 1 7"),                       # no console spam during a run (115200 serial)
]
OFFLOADS = {  # ethtool -K on eth0 and lan1; every stack showed these defaults already: pinned so a driver change shows up
    "gro": "on", "gso": "on", "rx-gro-list": "on", "rx-udp-gro-forwarding": "off", "tx-nocache-copy": "off",
}
STOP_SERVICES = "collectd luci_statistics lldpd uhttpd sysntpd dnsmasq odhcpd snmpd st1008f-metricsd st1008f-selftest rpcd cron irqbalance"
KILL_PROCS = "collectd lldpd uhttpd ntpd dnsmasq odhcpd snmpd crond rpcd irqbalance"
PINNED = [  # (local relative to TOOLS, remote name, mode)
    ("iperf3", "iperf3", "755"), ("ip-full", "ip-full", "755"), ("tc-full", "tc-full", "755"),
    ("ip", "ip", "755"), ("tc", "tc", "755"), ("fw4-b.nft", "fw4-b.nft", "644"),
]
WRAP = '#!/bin/sh\nLD_LIBRARY_PATH=%s/lib exec %s/%s-full "$@"\n'


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh_cmd(ip):
    return ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
            "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "-o", "ControlMaster=auto",
            "-o", f"ControlPath={ROOT}/tmp/stack_normalize.ssh", "-o", "ControlPersist=60", f"root@{ip}"]


def sha256(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---- host side: pack ip-full / tc-full + libs ----------------------------------------------------------------------
def pack():
    """Copy ip-full, tc-full and their DT_NEEDED libs (not musl) from B's root-realtek into tmp/stack-tools; write wrappers + MANIFEST."""
    TOOLS.mkdir(parents=True, exist_ok=True)
    (TOOLS / "lib").mkdir(exist_ok=True)
    todo, seen = [OWRT_ROOT / "usr/libexec/ip-full", OWRT_ROOT / "usr/libexec/tc-full"], set()
    for exe in todo[:2]:
        (TOOLS / exe.name).write_bytes(exe.read_bytes())
        (TOOLS / exe.name).chmod(0o755)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        out = subprocess.run(["readelf", "-d", str(f)], capture_output=True, text=True).stdout
        for need in re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", out):
            if need.startswith("libc.so"):
                continue  # musl stays stack-native (same 1.2.6 on A, B, C: recorded in the snapshot)
            hit = next((OWRT_ROOT / d / need for d in ("lib", "usr/lib") if (OWRT_ROOT / d / need).exists()), None)
            if hit is None:
                sys.exit(f"pack: {f.name} needs {need}: not in {OWRT_ROOT}")
            (TOOLS / "lib" / need).write_bytes(hit.resolve().read_bytes())
            (TOOLS / "lib" / need).chmod(0o755)
            todo.append(hit.resolve())
    for n in ("ip", "tc"):
        (TOOLS / n).write_text(WRAP % (REMOTE, REMOTE, n))
        (TOOLS / n).chmod(0o755)
    (TOOLS / "fw4-b.nft").write_bytes(FW4.read_bytes())
    lines = [f"{sha256(p)}  {p.relative_to(TOOLS)}" for p in sorted(TOOLS.rglob("*")) if p.is_file() and p.name != "MANIFEST.txt"]
    (TOOLS / "MANIFEST.txt").write_text("\n".join(lines) + "\n")
    log(f"pack: {len(lines)} files in {TOOLS.relative_to(ROOT)} (MANIFEST.txt)")


# ---- remote scripts ---------------------------------------------------------------------------------------------------
def normalize_script(a):
    sysctl = "\n".join(f"{k} {v}" for k, v in SYSCTLS)
    offl = " ".join(f"{k} {v}" for k, v in OFFLOADS.items())
    aff = "2" if a.napi == "irq1" else "3"
    return f"""#!/bin/sh
# stack_normalize remote part: stack {a.stack} napi {a.napi} qdisc {a.qdisc}
T={REMOTE}
ln -sf $T/iperf3 /usr/bin/iperf3; ln -sf $T/ip /sbin/ip; ln -sf $T/tc /sbin/tc
for s in {STOP_SERVICES}; do [ -x /etc/init.d/$s ] && /etc/init.d/$s stop >/dev/null 2>&1; done
killall {KILL_PROCS} 2>/dev/null
[ -x /etc/init.d/firewall ] && /etc/init.d/firewall stop >/dev/null 2>&1
nft flush ruleset
nft -f $T/fw4-b.nft || echo "FAIL nft load"
MG=$(ip -o -4 addr show | awk -v ip={a.ip} '$4 ~ "^"ip"/" {{print $2; exit}}')
[ -n "$MG" ] && nft "insert rule inet fw4 input iifname \\"$MG\\" accept comment stack-mgmt" || echo "FAIL stack-mgmt rule (mgmt dev '$MG')"
while read k v; do
  f=/proc/sys/$(echo $k | tr . /)
  [ -e "$f" ] || {{ echo "MISSING $k"; continue; }}
  echo "$v" > "$f" || echo "FAIL $k"
done <<'EOF'
{sysctl}
EOF
for f in /proc/sys/net/ipv4/conf/*/rp_filter; do echo 0 > $f; done
for q in /sys/class/net/*/queues/rx-*/rps_cpus /sys/class/net/*/queues/rx-*/rps_flow_cnt /sys/class/net/*/queues/tx-*/xps_cpus; do
  [ -e $q ] && {{ echo 0 > $q 2>/dev/null; v=$(cat $q 2>/dev/null) && ! echo "$v" | grep -qE '^[0,]*$' && echo "FAIL $q"; }}
done
for n in threaded gro_flush_timeout napi_defer_hard_irqs; do echo 0 > /sys/class/net/eth0/$n 2>/dev/null; done
tc qdisc replace dev eth0 root {a.qdisc} || echo "FAIL qdisc {a.qdisc}"
for d in eth0 lan1; do ethtool -K $d {offl} >/dev/null 2>&1 || echo "FAIL ethtool -K $d"; done
IRQ=$(awk '/eth0/{{print +$1}}' /proc/interrupts)
echo {aff} > /proc/irq/$IRQ/smp_affinity || echo "FAIL irq affinity"
echo done
"""


SNAP = [  # (key, remote command); every command stderr merged; output compared as text
    ("uname_r", "uname -r"), ("uname_v", "uname -v"), ("uname_a", "uname -a"), ("cmdline", "cat /proc/cmdline"),
    ("config_gz_sha256", "[ -e /proc/config.gz ] && zcat /proc/config.gz | sha256sum || echo absent"),
    ("kconfig_debug", "[ -e /proc/config.gz ] && zcat /proc/config.gz | grep -E '^(# )?CONFIG_(DEBUG_KERNEL|DEBUG_FS|DEBUG_INFO|FTRACE|FUNCTION_TRACER|FUNCTION_GRAPH_TRACER|DYNAMIC_FTRACE|PERF_EVENTS|PROFILING|DYNAMIC_DEBUG|KPROBES|UPROBES|LOCKDEP|PROVE_LOCKING|KALLSYMS|KALLSYMS_ALL|SCHEDSTATS|SLUB_DEBUG|DEBUG_LIST|DEBUG_VM|NET_DROP_MONITOR|HZ|STACKPROTECTOR|HARDENED_USERCOPY|MEMCG|IP_MULTIPLE_TABLES|DEFAULT_NET_SCH|NETFILTER_EGRESS|PREEMPT[A-Z_]*|CC_OPTIMIZE[A-Z_]*)[= ]' || echo absent"),
    ("rt_perf", "[ -e /proc/sys/kernel/perf_event_paranoid ] && echo y || echo n"),
    ("rt_ftrace", "[ -d /sys/kernel/tracing/events ] || [ -d /sys/kernel/debug/tracing/events ] && echo y || echo n"),
    ("rt_current_tracer", "cat /sys/kernel/tracing/current_tracer /sys/kernel/debug/tracing/current_tracer 2>/dev/null | head -1; true"),
    ("rt_dyndbg", "[ -e /sys/kernel/debug/dynamic_debug/control ] && echo y || echo n"),
    ("rt_kprobes", "[ -e /sys/kernel/debug/kprobes ] && echo y || echo n"),
    ("rt_lockdep", "[ -e /proc/lockdep ] && echo y || echo n"), ("rt_schedstat", "[ -e /proc/schedstat ] && echo y || echo n"),
    ("rt_kallsyms", "[ -r /proc/kallsyms ] && echo y || echo n"),
    ("rt_debugfs_mounted", "grep -q ' debugfs ' /proc/mounts && echo y || echo n"),
    ("rt_perf_processes", "pidof perf trace-cmd 2>/dev/null || echo none"),
    ("sysctl", "sysctl -a 2>/dev/null | grep -E '^(net\\.core\\.|net\\.ipv4\\.(tcp_|ip_forward|conf\\.(all|default)\\.(rp_filter|forwarding|send_redirects))|net\\.ipv6\\.conf\\.all\\.forwarding|net\\.netfilter\\.nf_(conntrack_(max|acct|checksum|tcp_|udp_|buckets)|flowtable)|kernel\\.printk)' | sort"),
    ("ethtool_k_eth0", "ethtool -k eth0 2>&1"), ("ethtool_k_lan1", "ethtool -k lan1 2>&1"), ("ethtool_g_eth0", "ethtool -g eth0 2>&1"),
    ("ethtool_c_eth0", "ethtool -c eth0 2>&1"), ("ethtool_i_eth0", "ethtool -i eth0 2>&1 | grep -v -E '^(bus-info|firmware-version|expansion)'"),
    ("tc_qdisc_eth0", "tc qdisc show dev eth0 2>&1"), ("tc_qdisc_lan1", "tc qdisc show dev lan1 2>&1"),
    ("netdev_sysfs", "grep -r . /sys/class/net/eth0/threaded /sys/class/net/eth0/gro_flush_timeout /sys/class/net/eth0/napi_defer_hard_irqs /sys/class/net/eth0/tx_queue_len /sys/class/net/eth0/mtu /sys/class/net/lan1/mtu 2>&1"),
    ("rps_xps", "grep -r . /sys/class/net/eth0/queues/rx-*/rps_cpus /sys/class/net/eth0/queues/tx-*/xps_cpus /sys/class/net/lan1/queues/*/rps_cpus /sys/class/net/lan1/queues/*/xps_cpus 2>&1; true"),
    ("irq_affinity", "I=$(awk '/eth0/{print +$1}' /proc/interrupts); echo irq$I $(cat /proc/irq/$I/smp_affinity)"),
    ("irqbalance", "pidof irqbalance || echo none"),
    ("nft_file_sha256", f"sha256sum {REMOTE}/fw4-b.nft | cut -d' ' -f1"),
    ("nft_ruleset_lines", "nft list ruleset 2>&1 | grep -v stack-mgmt | wc -l"),
    ("nft_ruleset_sha256", "nft list ruleset 2>&1 | grep -v stack-mgmt | sed 's/packets [0-9]* bytes [0-9]*//' | sha256sum | cut -d' ' -f1"),
    ("rteth_params", "grep -r . /sys/module/rtl838x_eth/parameters 2>/dev/null | sort; true"),
    ("l3_params", "grep -r . /sys/module/rtl_otto_dsa/parameters 2>/dev/null | sort; true"),
    ("processes", "for d in /proc/[0-9]*; do c=$(tr '\\0' ' ' < $d/cmdline 2>/dev/null); [ -n \"$c\" ] && echo \"$c\"; done"),
    ("loadavg", "cat /proc/loadavg"), ("meminfo", "grep -E 'MemTotal|MemFree' /proc/meminfo"),
    ("cpuinfo", "grep -i -E 'bogomips|model name' /proc/cpuinfo"), ("nproc_online", "cat /sys/devices/system/cpu/online"),
    ("v_busybox", "busybox 2>&1 | head -1"), ("v_nft", "nft -v 2>&1 | head -1"),
    ("v_ethtool", "ethtool --version 2>&1 | head -1"), ("v_ip", "ip -V 2>&1 | head -1"), ("v_tc", "tc -V 2>&1 | head -1"),
    ("v_iperf3", "iperf3 --version 2>&1 | head -1"), ("v_dropbear", "dropbear -V 2>&1 | head -1"),
    ("v_musl", "/lib/ld-musl-mips-sf.so.1 2>&1 | head -2 | tr '\\n' ' '"),
    ("sha_pinned", f"cd {REMOTE} && sha256sum iperf3 ip-full tc-full fw4-b.nft 2>&1"),
    ("sha_native", "sha256sum /bin/busybox /usr/sbin/nft /usr/sbin/ethtool /usr/sbin/dropbear 2>&1 | sed 's/  / /'"),
    ("bootloader_clock", "grep -r . /sys/kernel/debug/realtek_otto_clk 2>/dev/null | head -5; true"),
]


def snap_script():
    return "#!/bin/sh\n" + "\n".join(f"echo '@@{k}'; ( {c} ) 2>&1" for k, c in SNAP) + "\n"


# ---- ssh transport ----------------------------------------------------------------------------------------------------
def run_remote(a, script, tmo, what):
    """Script goes to /tmp/stack-script-<what>.sh first, then runs with stdin from /dev/null (a command must not eat the script)."""
    path = f"/tmp/stack-script-{what}.sh"
    up, go = ssh_cmd(a.ip) + [f"cat > {path}"], ssh_cmd(a.ip) + [f"sh {path} </dev/null"]
    if a.dry_run:
        log(f"[dry-run] {what}: {' '.join(up[-1:])}   then   {' '.join(go[-1:])}   (timeout {tmo} s); script:")
        print(script)
        return ""
    t0 = time.time()
    try:
        subprocess.run(up, input=script, capture_output=True, text=True, timeout=15, check=True)  # tiny file, LAN login ~0.3 s
        r = subprocess.run(go, capture_output=True, text=True, timeout=tmo)
    except subprocess.TimeoutExpired:
        sys.exit(f"TIMEOUT {what}: {tmo} s limit, {time.time() - t0:.1f} s elapsed")
    log(f"{what}: rc {r.returncode} in {time.time() - t0:.1f} s")
    return r.stdout + r.stderr


def push(a):
    """cat over ssh stdin, skipped when the remote sha256 already matches. Limit per file: 10 s + size / 256 KiB/s
    (assumed floor for dropbear on the 34Kc, NOT measured; a hit names file and size)."""
    for local, remote, mode in PINNED:
        p = TOOLS / local
        if not p.exists():
            sys.exit(f"missing {p.relative_to(ROOT)}: python3 scripts/build_iperf3_static.py ; python3 scripts/stack_normalize.py --pack")
    files = [(TOOLS / n, n, m) for _, n, m in PINNED] + [(f, f"lib/{f.name}", "755") for f in sorted((TOOLS / "lib").glob("*"))]
    for p, rem, mode in files:
        tmo = int(10 + p.stat().st_size / (256 * 1024))
        cmd = ssh_cmd(a.ip) + [f"mkdir -p {REMOTE}/lib && cat > {REMOTE}/{rem}.part && chmod {mode} {REMOTE}/{rem}.part && mv {REMOTE}/{rem}.part {REMOTE}/{rem}"]
        if a.dry_run:
            log(f"[dry-run] push {p.relative_to(ROOT)} ({p.stat().st_size} B, sha256 {sha256(p)[:16]}): {' '.join(cmd[-1:])}  (timeout {tmo} s)")
            continue
        t0 = time.time()
        try:
            r = subprocess.run(cmd, input=p.read_bytes(), capture_output=True, timeout=tmo)
        except subprocess.TimeoutExpired:
            sys.exit(f"TIMEOUT push {rem} ({p.stat().st_size} B): {tmo} s limit")
        if r.returncode:
            sys.exit(f"push {rem} failed rc {r.returncode}: {r.stderr.decode(errors='replace')[:200]}")
        log(f"push {rem}: {p.stat().st_size} B in {time.time() - t0:.1f} s")


def parse_snapshot(text):
    out, key = {}, None
    for ln in text.splitlines():
        if ln.startswith("@@"):
            key = ln[2:]
            out[key] = []
        elif key:
            out[key].append(ln)
    return {k: "\n".join(v).strip() for k, v in out.items()}


# ---- diff (also used by stack_compare.py's gate) ----------------------------------------------------------------------
IGNORE = re.compile(r"^(stack|when|flavour_expected|normalise_failures|qdisc_requested|uname_v|uname_a|loadavg|meminfo|cpuinfo|bootloader_clock|rt_perf_processes)$")
# the stack under test, by construction: key regex -> reason. Anything else that differs = NOT CONTROLLED.
KNOWN = [
    (r"uname_r", "kernel under test (A 6.18.60 vs B/C 7.4-rc1)"),
    (r"rteth_params|l3_params", "A has no 300-xx rteth/l3 module parameters (patch set under test)"),
    (r"config_gz_sha256|kconfig_debug", "only C ships /proc/config.gz (IKCONFIG); A and B: build-time config in NAT-STACK-TESTS.md"),
    (r"processes", "OpenWrt base system (procd, ubusd, netifd, logd, urngd, hotplug, linkwatch) runs on A/B, not C"),
    (r"sha_native", "native tool binaries are separate builds (same versions, see v_*)"),
    (r"ethtool_i_eth0", "driver version string follows the kernel"),
]


def _norm(key, val):
    if key == "processes":  # argv0 basenames, minus our own ssh/ps/sh helpers and kernel noise
        names = sorted({os.path.basename(ln.split()[0]) for ln in val.splitlines() if ln.split()} - {"sh", "ash", "tr", "cat", "sleep", "dropbear"})
        return "\n".join(names)
    if key == "sysctl":  # volatile counters
        return "\n".join(ln for ln in val.splitlines() if not re.search(r"nf_conntrack_count|netdev_rss_key|nf_conntrack_buckets|tcp_fastopen_key|tcp_mem|tcp_available_ulp|tcp_l3mdev_accept|bpf_jit_kallsyms", ln))  # random / RAM-size / config-dependent, not on the path
    if key == "ethtool_i_eth0":
        return val
    return val


def diff_snapshots(snaps):
    """snaps {label: {key: value}} -> [(key, {label: value}, known_reason | None)] for every key whose normalised values differ."""
    keys = sorted(set().union(*[set(s) for s in snaps.values()]))
    out = []
    for k in keys:
        if IGNORE.match(k):
            continue
        vals = {lab: _norm(k, s.get(k, "<missing>")) for lab, s in snaps.items()}
        if len(set(vals.values())) > 1:
            reason = next((why for rx, why in KNOWN if re.fullmatch(rx, k)), None)
            out.append((k, vals, reason))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stack", choices=["A", "B", "C"], help="which stack is booted (selects services/firewall steps)")
    ap.add_argument("--ip", default=BENCH_IP)
    ap.add_argument("--napi", choices=["irq1", "default"], default="irq1", help="NIC irq on VPE1 (smp_affinity 2, as the --napi irq1 cells) or both (3)")
    ap.add_argument("--qdisc", default="noqueue", help="eth0 root qdisc on every stack (default noqueue: no queueing, one less variable; plain kernel gave 544 vs 528 with it)")
    ap.add_argument("--snap-dir", default=str(ROOT / "tmp/logs"), help="where the snapshot json is written")
    ap.add_argument("--tag", default="", help="snapshot file suffix (e.g. post)")
    ap.add_argument("--snapshot-only", action="store_true", help="skip push and normalisation; snapshot only (drift check after a bench)")
    ap.add_argument("--pack", action="store_true", help="host only: build tmp/stack-tools ip/tc/libs/wrappers/fw4 + MANIFEST")
    ap.add_argument("--dry-run", action="store_true", help="print every ssh command and remote script; send nothing")
    a = ap.parse_args()
    if a.pack:
        pack()
        return 0
    if not a.stack:
        ap.error("--stack required")
    log(f"=== stack_normalize stack {a.stack} ip {a.ip} napi {a.napi} qdisc {a.qdisc} tag '{a.tag}' dry-run {a.dry_run}")
    if not a.snapshot_only:
        push(a)
        out = run_remote(a, normalize_script(a), 90, "normalise")  # stop ~12 services x <3 s + nft + sysctls
        bad = [ln for ln in out.splitlines() if ln.startswith(("FAIL", "MISSING"))]
        for ln in bad:
            log(f"  {ln}")
        if not a.dry_run and "done" not in out:
            sys.exit(f"normalise did not finish: {out[-300:]}")
    else:
        bad = []
    out = run_remote(a, snap_script(), 30, "snapshot")  # ~60 small reads; 20 s was the loaded-ssh worst case in nat_bench.py
    if a.dry_run:
        return 0
    snap = parse_snapshot(out)
    snap.update({"stack": a.stack, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "napi": a.napi, "qdisc_requested": a.qdisc,
                 "normalise_failures": "\n".join(bad), "flavour_expected": FLAVOUR[a.stack]})
    p = Path(a.snap_dir) / f"stack_snapshot-{a.stack}{'-' + a.tag if a.tag else ''}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
    log(f"snapshot -> {p} ({len(snap)} keys); normalise failures: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
