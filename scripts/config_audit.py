#!/usr/bin/env python3
"""config_audit — kernel option table for the three NAT-test stacks (docs/NAT-STACK-TESTS.md).

- A upstream OpenWrt 6.18 snapshot: DERIVED = generic + rtl930x config-6.18 from tmp/openwrt-build + Config-kernel.in
  defaults for the buildbot (COLLECT_KERNEL_DEBUG -> DEBUG_INFO reduced). Not read from the snapshot binary.
- B ours-OpenWrt 7.4: final .config of tmp/openwrt-build (linux-7.4-rc1).
- C plain 7.4 bench kernel: tmp/build-mips-v7.4-rc1-bench/.config.
- Output: markdown table on stdout, copy in tmp/logs/config_audit.log. `--md-cell` unused; no args.
"""
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OW = ROOT / "tmp/openwrt-build"
B_CFG = next((OW / "build_dir").glob("target-*/linux-realtek_rtl930x/linux-7.4-rc1/.config"))
C_CFG = ROOT / "tmp/build-mips-v7.4-rc1-bench/.config"
A_FILES = [OW / "target/linux/generic/config-6.18", OW / "target/linux/realtek/rtl930x/config-6.18"]
# Config-kernel.in defaults for the buildbot (BUILDBOT -> COLLECT_KERNEL_DEBUG selects KERNEL_DEBUG_INFO; REDUCED default y)
A_DEFAULTS = """CONFIG_DEBUG_INFO=y
CONFIG_DEBUG_INFO_REDUCED=y
CONFIG_DEBUG_KERNEL=y
CONFIG_KALLSYMS=y
CONFIG_MAGIC_SYSRQ=y
CONFIG_PRINTK_TIME=y
CONFIG_DEBUG_FS=y
"""
ROWS = [  # (label, symbols)
    ("DEBUG_KERNEL", ["DEBUG_KERNEL"]),
    ("DEBUG_INFO / REDUCED", ["DEBUG_INFO", "DEBUG_INFO_REDUCED"]),
    ("DEBUG_FS", ["DEBUG_FS"]),
    ("FTRACE", ["FTRACE"]),
    ("FUNCTION_TRACER", ["FUNCTION_TRACER"]),
    ("FUNCTION_GRAPH_TRACER", ["FUNCTION_GRAPH_TRACER"]),
    ("DYNAMIC_FTRACE", ["DYNAMIC_FTRACE"]),
    ("IRQSOFF/TIMERLAT tracers", ["IRQSOFF_TRACER", "TIMERLAT_TRACER"]),
    ("KPROBES / UPROBES", ["KPROBES", "UPROBES"]),
    ("PERF_EVENTS / HW_PERF_EVENTS", ["PERF_EVENTS", "HW_PERF_EVENTS"]),
    ("PROFILING", ["PROFILING"]),
    ("KALLSYMS / KALLSYMS_ALL", ["KALLSYMS", "KALLSYMS_ALL"]),
    ("DYNAMIC_DEBUG", ["DYNAMIC_DEBUG"]),
    ("LOCKDEP / PROVE_LOCKING", ["LOCKDEP", "PROVE_LOCKING"]),
    ("DEBUG_SPINLOCK / DEBUG_ATOMIC_SLEEP", ["DEBUG_SPINLOCK", "DEBUG_ATOMIC_SLEEP"]),
    ("DEBUG_LIST", ["DEBUG_LIST"]),
    ("SLUB_DEBUG / PAGE_POISONING", ["SLUB_DEBUG", "PAGE_POISONING"]),
    ("DEBUG_VM / DEBUG_NET", ["DEBUG_VM", "DEBUG_NET"]),
    ("PAGE_POOL_STATS", ["PAGE_POOL_STATS"]),
    ("NET_DROP_MONITOR", ["NET_DROP_MONITOR"]),
    ("SCHEDSTATS / SCHED_DEBUG", ["SCHEDSTATS", "SCHED_DEBUG"]),
    ("MAGIC_SYSRQ", ["MAGIC_SYSRQ"]),
    ("PRINTK_TIME", ["PRINTK_TIME"]),
    ("CONSOLE_LOGLEVEL_DEFAULT", ["CONSOLE_LOGLEVEL_DEFAULT"]),
    ("Preempt model", ["PREEMPT_NONE", "PREEMPT_VOLUNTARY", "PREEMPT"]),
    ("HZ", ["HZ"]),
    ("NR_CPUS / SMP / MIPS_MT_SMP", ["NR_CPUS", "SMP", "MIPS_MT_SMP"]),
    ("HIGHMEM", ["HIGHMEM"]),
    ("CPU type / IRQ VI / FP_SUPPORT", ["CPU_MIPS32_R2", "CPU_MIPSR2_IRQ_VI", "MIPS_FP_SUPPORT"]),
    ("Optimisation", ["CC_OPTIMIZE_FOR_PERFORMANCE", "CC_OPTIMIZE_FOR_SIZE"]),
    ("STACKPROTECTOR / HARDENED_USERCOPY", ["STACKPROTECTOR", "HARDENED_USERCOPY"]),
    ("SLAB_FREELIST_HARDENED / RANDOM", ["SLAB_FREELIST_HARDENED", "SLAB_FREELIST_RANDOM"]),
    ("MODULES", ["MODULES"]),
    ("NF_CONNTRACK / TIMESTAMP / MARK", ["NF_CONNTRACK", "NF_CONNTRACK_TIMESTAMP", "NF_CONNTRACK_MARK"]),
    ("NF_FLOW_TABLE / NFT_FLOW_OFFLOAD", ["NF_FLOW_TABLE", "NFT_FLOW_OFFLOAD"]),
    ("RPS / RFS_ACCEL / XPS", ["RPS", "RFS_ACCEL", "XPS"]),
    ("NET_FLOW_LIMIT / BQL", ["NET_FLOW_LIMIT", "BQL"]),
    ("DEFAULT_NET_SCH / FQ_CODEL", ["DEFAULT_NET_SCH", "NET_SCH_FQ_CODEL"]),
    ("NET_RTL838X (rteth) / NET_DSA", ["NET_RTL838X", "NET_DSA"]),
    ("BPF_SYSCALL / BPF_JIT", ["BPF_SYSCALL", "BPF_JIT"]),
    ("IKCONFIG", ["IKCONFIG"]),
    ("Built-in cmdline", ["CMDLINE_BOOL", "MIPS_CMDLINE_DTB_EXTEND", "MIPS_CMDLINE_FROM_DTB"]),
]


def load(files, extra=""):
    d = {}
    for text in [f.read_text() for f in files] + [extra]:
        for ln in text.splitlines():
            if m := re.match(r"CONFIG_(\w+)=(.*)", ln):
                d[m[1]] = m[2].strip('"')
            elif m := re.match(r"# CONFIG_(\w+) is not set", ln):
                d[m[1]] = "n"
    return d


def cell(d, syms, a_derived=False):
    out = []
    for s in syms:
        v = d.get(s)
        if v is None:
            v = "-" if not a_derived else "-"
        out.append(f"{s}={v}")
    return " ".join(out) if len(syms) > 1 or True else ""


def main():
    A, B, C = load(A_FILES, A_DEFAULTS), load([B_CFG]), load([C_CFG])
    lines = ["| option | A upstream 6.18 (derived) | B ours-OpenWrt 7.4 | C plain 7.4 bench |", "|---|---|---|---|"]
    for label, syms in ROWS:
        lines.append(f"| {label} | " + " | ".join(cell(d, syms) for d in (A, B, C)) + " |")
    diff = [s for s in sorted(set(A) | set(B) | set(C)) if s in B and s in C and B[s] != C[s] and re.search("DEBUG|TRACE|PERF|PROF|PROBE|KALLSYMS|SCHED|LOCK|PREEMPT|HZ", s)]
    out = "\n".join(lines) + "\n\nB vs C differing debug/trace/preempt symbols: " + ", ".join(f"{s} B={B[s]} C={C[s]}" for s in diff) + "\n"
    print(out)
    log = ROOT / "tmp/logs/config_audit.log"
    with log.open("a") as f:
        f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] B={B_CFG} C={C_CFG}\n{out}")


if __name__ == "__main__":
    sys.exit(main())
