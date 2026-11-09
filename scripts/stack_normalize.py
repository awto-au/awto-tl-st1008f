#!/usr/bin/env python3
"""stack_normalize — make a booted bench stack (A upstream OpenWrt, B ours OpenWrt, C plain kernel) identical
in everything except the kernel / OpenWrt stack under test; run BEFORE every bench. NAT-STACK-TESTS.md.

Steps (ssh to the switch, nothing on the host except the push):
  1. push the pinned tools to /tmp/stack-tools: static iperf3 (build_iperf3_static.py), ip-full, tc-full,
     bridge, ethtool-full + libs (--pack copies them from B's root-realtek); symlinks point at them.
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
    ("net.netfilter.nf_conntrack_max", "8192"), ("net.netfilter.nf_conntrack_buckets", "8192"),  # B and C measured 8192
    ("net.netfilter.nf_conntrack_acct", "1"),           # nat_bench.py sets 1 per run
    ("net.netfilter.nf_conntrack_checksum", "0"),       # B 0 (OpenWrt sysctl.conf), plain kernel default 1: differed in #161 dumps
    ("net.netfilter.nf_conntrack_tcp_loose", "1"), ("net.netfilter.nf_conntrack_tcp_be_liberal", "0"),
    ("net.netfilter.nf_flowtable_tcp_timeout", "30"), ("net.netfilter.nf_flowtable_udp_timeout", "30"),
    ("net.netfilter.nf_conntrack_tcp_timeout_established", "7440"), ("net.netfilter.nf_conntrack_udp_timeout", "60"),
    ("net.netfilter.nf_conntrack_udp_timeout_stream", "180"),
    ("net.core.netdev_budget", "300"), ("net.core.netdev_budget_usecs", "20000"),  # 2 s/HZ at HZ 100; plain HZ 250 gave 8000
    ("net.core.netdev_max_backlog", "1000"), ("net.core.rps_sock_flow_entries", "0"), ("net.core.skb_defer_max", "128"),
    ("net.core.rmem_default", "212992"), ("net.core.wmem_default", "212992"),
    ("net.core.rmem_max", "4194304"), ("net.core.wmem_max", "4194304"),
    ("net.ipv4.tcp_rmem", "4096 131072 4194304"), ("net.ipv4.tcp_wmem", "4096 16384 4194304"),
    ("net.ipv4.tcp_congestion_control", "cubic"), ("net.ipv4.tcp_sack", "1"), ("net.ipv4.tcp_timestamps", "1"),
    ("net.ipv4.tcp_window_scaling", "1"), ("net.ipv4.tcp_ecn", "0"), ("net.ipv4.tcp_syncookies", "1"),
    ("net.ipv4.tcp_fin_timeout", "30"), ("net.ipv4.tcp_comp_sack_slack_ns", "10000"),
    ("net.ipv4.conf.all.rp_filter", "0"), ("net.ipv4.conf.default.rp_filter", "0"),  # strict rpf = extra fib lookup per packet; OpenWrt sets 1
    ("net.core.bpf_jit_enable", "1"), ("net.ipv4.tcp_keepalive_time", "120"),  # OpenWrt defaults; plain kernel 0 / 7200
    ("kernel.printk", "1 4 1 7"),                       # no console spam during a run (115200 serial)
]
OFFLOADS = {  # ethtool -K on eth0 and lan1; every stack showed these defaults already: pinned so a driver change shows up
    "gro": "on", "gso": "on", "rx-gro-list": "on", "rx-udp-gro-forwarding": "off", "tx-nocache-copy": "off",
}
STOP_SERVICES = "collectd luci_statistics lldpd uhttpd sysntpd dnsmasq odhcpd snmpd st1008f-metricsd st1008f-selftest rpcd cron irqbalance"
PINNED = [  # (local relative to TOOLS, remote name, mode)
    ("iperf3", "iperf3", "755"), ("ip-full", "ip-full", "755"), ("tc-full", "tc-full", "755"),
    ("ethtool-full", "ethtool-full", "755"), ("bridge-full", "bridge-full", "755"),
    ("ip", "ip", "755"), ("tc", "tc", "755"), ("ethtool", "ethtool", "755"),
    ("bridge", "bridge", "755"), ("fw4-b.nft", "fw4-b.nft", "644"),
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


# ---- host side: pack full tools + libs -----------------------------------------------------------------------------
def pack():
    """Copy B's full tools and DT_NEEDED libs (not musl) into tmp/stack-tools; write wrappers + MANIFEST."""
    TOOLS.mkdir(parents=True, exist_ok=True)
    (TOOLS / "lib").mkdir(exist_ok=True)
    sources = [(OWRT_ROOT / "usr/libexec/ip-full", "ip-full"), (OWRT_ROOT / "usr/libexec/tc-full", "tc-full"),
               (OWRT_ROOT / "usr/sbin/ethtool", "ethtool-full"), (OWRT_ROOT / "usr/sbin/bridge", "bridge-full")]
    todo, seen = [exe for exe, _ in sources], set()
    for exe, name in sources:
        (TOOLS / name).write_bytes(exe.read_bytes())
        (TOOLS / name).chmod(0o755)
    while todo:
        f = todo.pop()
        if f in seen:
            continue
        seen.add(f)
        result = subprocess.run(["readelf", "-d", str(f)], capture_output=True, text=True)
        if result.returncode:
            sys.exit(f"pack: cannot inspect {f.name}: {result.stderr.strip()}")
        for need in re.findall(r"\(NEEDED\)\s+Shared library: \[(.+?)\]", result.stdout):
            if need.startswith("libc.so"):
                continue  # musl stays stack-native (same 1.2.6 on A, B, C: recorded in the snapshot)
            hit = next((OWRT_ROOT / d / need for d in ("lib", "usr/lib") if (OWRT_ROOT / d / need).exists()), None)
            if hit is None:
                sys.exit(f"pack: {f.name} needs {need}: not in {OWRT_ROOT}")
            (TOOLS / "lib" / need).write_bytes(hit.resolve().read_bytes())
            (TOOLS / "lib" / need).chmod(0o755)
            todo.append(hit.resolve())
    for n in ("ip", "tc", "ethtool", "bridge"):
        (TOOLS / n).write_text(WRAP % (REMOTE, REMOTE, n))
        (TOOLS / n).chmod(0o755)
    (TOOLS / "fw4-b.nft").write_bytes(FW4.read_bytes())
    lines = [f"{sha256(p)}  {p.relative_to(TOOLS)}" for p in sorted(TOOLS.rglob("*")) if p.is_file() and p.name != "MANIFEST.txt"]
    (TOOLS / "MANIFEST.txt").write_text("\n".join(lines) + "\n")
    log(f"pack: {len(lines)} files in {TOOLS.relative_to(ROOT)} (MANIFEST.txt)")


# ---- remote scripts ---------------------------------------------------------------------------------------------------
def normalize_script(a):
    sysctl = "\n".join(f"{k} {v}" for k, v in SYSCTLS)
    offl = " ".join(f"{k} {v}" for k, v in {**OFFLOADS, **dict(o.split("=", 1) for o in a.offload)}.items())
    aff = {"irq1": "2", "irq0": "1"}.get(a.napi, "3")
    rps = ":" if a.rps == "keep" else """echo 0 > $q 2>/dev/null; v=$(cat $q 2>/dev/null) && ! echo "$v" | grep -qE '^[0,]*$' && echo "FAIL $q" """
    return f"""#!/bin/sh
# stack_normalize remote part: stack {a.stack} napi {a.napi} qdisc {a.qdisc}
T={REMOTE}
ln -sf $T/iperf3 /usr/bin/iperf3; ln -sf $T/ip /sbin/ip; ln -sf $T/tc /sbin/tc; ln -sf $T/ethtool /usr/sbin/ethtool; ln -sf $T/bridge /usr/sbin/bridge
for s in {STOP_SERVICES}; do
  if [ -x /etc/init.d/$s ]; then /etc/init.d/$s stop >/dev/null 2>&1 || echo "FAIL stopping service $s"; fi
done
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
  [ -e $q ] && {{ {rps}; }}
done
for n in threaded gro_flush_timeout napi_defer_hard_irqs; do echo 0 > /sys/class/net/eth0/$n 2>/dev/null; done
tc qdisc replace dev eth0 root {a.qdisc} || echo "FAIL qdisc {a.qdisc}"
for d in eth0 lan1; do
  out=$(ethtool -K $d {offl} 2>&1) || printf 'FAIL ethtool -K %s: %s\\n' "$d" "$(printf '%s' "$out" | tr '\\n' ' ')"
done
IRQ=$(awk '/eth0/{{print +$1}}' /proc/interrupts)
echo {aff} > /proc/irq/$IRQ/smp_affinity || echo "FAIL irq affinity"
echo done
"""


SNAP_SYSCTL = (
    "for f in /proc/sys/net/core/* /proc/sys/net/ipv4/tcp_* /proc/sys/net/ipv4/ip_forward* "
    "/proc/sys/net/ipv4/conf/all/rp_filter /proc/sys/net/ipv4/conf/default/rp_filter "
    "/proc/sys/net/ipv4/conf/all/forwarding /proc/sys/net/ipv4/conf/default/forwarding "
    "/proc/sys/net/ipv4/conf/all/send_redirects /proc/sys/net/ipv4/conf/default/send_redirects "
    "/proc/sys/net/ipv6/conf/all/forwarding /proc/sys/net/netfilter/nf_conntrack_max "
    "/proc/sys/net/netfilter/nf_conntrack_acct /proc/sys/net/netfilter/nf_conntrack_checksum "
    "/proc/sys/net/netfilter/nf_conntrack_buckets /proc/sys/net/netfilter/nf_conntrack_tcp_* "
    "/proc/sys/net/netfilter/nf_conntrack_udp_* /proc/sys/net/netfilter/nf_flowtable* "
    "/proc/sys/kernel/printk*; do [ -f \"$f\" ] || continue; "
    "k=${f#/proc/sys/}; v=$(cat \"$f\" 2>&1) || { printf 'FAIL sysctl read %s: %s\\n' \"$k\" \"$v\"; continue; }; "
    "printf '%s = %s\\n' \"$(echo \"$k\" | tr / .)\" \"$v\"; done | sort"
)

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
    ("sysctl", SNAP_SYSCTL),
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
    ("v_musl", "/lib/ld-musl-mips-sf.so.1 2>&1 | head -2 | tr '\\n' ' '; echo"),
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
        subprocess.run(up, input=script, capture_output=True, text=True, timeout=15, check=True)  # tiny file
    except subprocess.TimeoutExpired:
        sys.exit(f"TIMEOUT upload {what} script: 15 s limit, {time.time() - t0:.1f} s elapsed")
    try:
        r = subprocess.run(go, capture_output=True, text=True, timeout=tmo)
    except subprocess.TimeoutExpired:
        sys.exit(f"TIMEOUT {what}: {tmo} s limit, {time.time() - t0:.1f} s elapsed")
    log(f"{what}: rc {r.returncode} in {time.time() - t0:.1f} s")
    if r.returncode:
        sys.exit(f"{what} failed rc {r.returncode}: {(r.stdout + r.stderr)[-400:]}")
    return r.stdout + r.stderr


def push(a):
    """Copy the pinned files over SSH, with a size-dependent timeout per file."""
    for local, remote, mode in PINNED:
        p = TOOLS / local
        if not p.exists():
            sys.exit(f"missing {p.relative_to(ROOT)}: python3 scripts/build_iperf3_static.py ; python3 scripts/stack_normalize.py --pack")
    files = [(TOOLS / n, n, m) for _, n, m in PINNED] + [(f, f"lib/{f.name}", "755") for f in sorted((TOOLS / "lib").glob("*"))]
    for p, rem, mode in files:
        tmo = max(30, int(10 + p.stat().st_size / (256 * 1024)))
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


def irq_readback_failure(snap, napi):
    value = snap.get("irq_affinity", "")
    match = re.fullmatch(r"irq\d+\s+([0-9a-fA-F,]+)", value)
    expected = {"irq0": 1, "irq1": 2, "default": 3}[napi]
    if not match or int(match.group(1).replace(",", ""), 16) != expected:
        return f"FAIL irq affinity readback: expected {expected:x}, got {value!r}"
    return None


def settings_readback_failures(snap, overrides):
    failures = []
    sysctls = dict(line.split(" = ", 1) for line in snap.get("sysctl", "").splitlines() if " = " in line)
    for key, expected in SYSCTLS:
        actual = sysctls.get(key, "")
        if actual.split() != expected.split():
            failures.append(f"FAIL sysctl readback {key}: expected {expected!r}, got {actual!r}")
    names = {"rx": "rx-checksumming", "tx": "tx-checksumming", "sg": "scatter-gather",
             "tso": "tcp-segmentation-offload", "ufo": "udp-fragmentation-offload",
             "gso": "generic-segmentation-offload", "gro": "generic-receive-offload",
             "lro": "large-receive-offload", "rxvlan": "rx-vlan-offload", "txvlan": "tx-vlan-offload",
             "ntuple": "ntuple-filters", "rxhash": "receive-hashing"}
    wanted = {**OFFLOADS, **dict(item.split("=", 1) for item in overrides)}
    for device in ("eth0", "lan1"):
        features = {}
        for line in snap.get(f"ethtool_k_{device}", "").splitlines():
            if match := re.match(r"\s*([^\s:]+):\s*(on|off)(.*)", line):
                features[match.group(1)] = (match.group(2), match.group(3))
        for key, expected in wanted.items():
            state = features.get(names.get(key, key))
            requested = re.search(r"\[requested (on|off)\]", state[1]) if state else None
            # B/C also report GSO off [requested on]; the gate compares effective states.
            valid = (state and (requested.group(1) if requested else state[0]) == expected
                     and (state[0] == expected or key == "gso" and expected == "on"))
            if not valid:
                failures.append(f"FAIL offload readback {device} {key}: expected {expected}, got {state}")
    return failures


# ---- diff (also used by stack_compare.py's gate) ----------------------------------------------------------------------
IGNORE = re.compile(r"^(stack|when|flavour_expected|normalise_failures|qdisc_requested|uname_v|uname_a|loadavg|meminfo|cpuinfo|bootloader_clock|rt_perf_processes)$")
# the stack under test, by construction: key regex -> reason. Anything else that differs = NOT CONTROLLED.
KNOWN = [
    (r"uname_r", "kernel under test (A 6.18.60 vs B/C 7.4-rc1)"),
    (r"rteth_params|l3_params", "A lacks configuration options for this project's switch-driver and on-link/default-route offload changes"),
    (r"config_gz_sha256|kconfig_debug", "only C ships /proc/config.gz (IKCONFIG); A and B: build-time config in NAT-STACK-TESTS.md"),
    (r"processes", "OpenWrt base system on A/B, not C; local linkwatch is B-only"),
    (r"sha_native", "native tool binaries are separate builds (versions recorded where available)"),
    (r"ethtool_i_eth0", "driver version string follows the kernel"),
]


def _norm(key, val):
    if key == "processes":  # argv0 basenames, minus our own ssh/ps/sh helpers and kernel noise
        names = sorted({os.path.basename(ln.split()[0]) for ln in val.splitlines() if ln.split()} - {"sh", "ash", "tr", "cat", "sleep", "dropbear"})
        return "\n".join(names)
    if key == "sysctl":  # volatile counters
        return "\n".join(ln for ln in val.splitlines() if not re.search(r"nf_conntrack_count|netdev_rss_key|tcp_fastopen_key|tcp_mem|tcp_available_ulp|tcp_l3mdev_accept|bpf_jit_kallsyms", ln))  # random / RAM-size / config-dependent, not on the path
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
    ap.add_argument("--napi", choices=["irq1", "irq0", "default"], default="irq1", help="NIC irq on VPE1 (smp_affinity 2, as the --napi irq1 cells), VPE0 (1) or both (3)")
    ap.add_argument("--rps", choices=["zero", "keep"], default="zero", help="zero = pin RPS/XPS to 0 (default); keep = leave the stack's own value (#149 V3)")
    ap.add_argument("--offload", action="append", default=[], metavar="K=V", help="override one OFFLOADS entry, e.g. gro=off (#149)")
    ap.add_argument("--qdisc", default="noqueue", help="eth0 root qdisc on every stack (default noqueue: no queueing, one less variable; plain kernel gave 544 vs 528 with it)")
    ap.add_argument("--snap-dir", default=str(ROOT / "tmp/logs"), help="where the snapshot json is written")
    ap.add_argument("--tag", default="", help="snapshot file suffix (e.g. post)")
    ap.add_argument("--snapshot-only", action="store_true", help="skip push and normalisation; snapshot only (drift check after a bench)")
    ap.add_argument("--pack", action="store_true", help="host only: pack ip/tc/bridge/ethtool, libs, wrappers and fw4 + MANIFEST")
    ap.add_argument("--dry-run", action="store_true", help="print every ssh command and remote script; send nothing")
    a = ap.parse_args()
    if a.pack:
        pack()
        return 0
    if not a.stack:
        ap.error("--stack required")
    if a.stack == "A" and a.napi == "irq1" and not a.snapshot_only:
        ap.error("A lacks the 300-18 IRQ fix: irq1 can disable networking; use --napi irq0 instead")
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
    if "sysctl" not in snap:
        bad.append("FAIL snapshot: missing sysctl section")
    else:
        bad.extend(line for line in snap["sysctl"].splitlines() if line.startswith("FAIL sysctl read "))
    for failure in bad:
        if failure.startswith(("FAIL snapshot:", "FAIL sysctl read ")):
            log(f"  {failure}")
    if not a.snapshot_only and (failure := irq_readback_failure(snap, a.napi)):
        bad.append(failure)
        log(f"  {failure}")
    if not a.snapshot_only:
        for failure in settings_readback_failures(snap, a.offload):
            bad.append(failure)
            log(f"  {failure}")
    snap.update({"stack": a.stack, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "napi": a.napi, "qdisc_requested": a.qdisc,
                 "normalise_failures": "\n".join(bad), "flavour_expected": FLAVOUR[a.stack]})
    p = Path(a.snap_dir) / f"stack_snapshot-{a.stack}{'-' + a.tag if a.tag else ''}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(snap, indent=1, sort_keys=True) + "\n")
    log(f"snapshot -> {p} ({len(snap)} keys); normalise failures: {len(bad)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
