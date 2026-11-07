#!/usr/bin/env python3
"""nat_knobs — runtime switches for every NAT-speed idea, and a combination runner (#65, #60).

- Each knob is switched live over SSH on the running switch (no rebuild, no reboot); `states[0]` is the default.
- `list`: knobs and their live state. `set k=v ...`: switch. `reset`: all to default.
- `matrix`: baseline, each knob alone, then optional pairs / explicit combos; one `nat-bench run` per cell.
  Rows go to tmp/logs/nat_bench.jsonl (tag = cell name) and tmp/logs/nat_knobs.jsonl.
- Needs the nat-bench setup first (docs/NAT-OPS.md): `nat-bench setup`, `dflt-setup`, `offload 0 0 0`.
- Boot-time ideas (clocks, SRAM rings, HIGHMEM, kernel patches) are not here: `nat-clock-variants`, `nat-matrix`.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nat_bench as nb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/nat_knobs.log"
ROWS = ROOT / "tmp/logs/nat_knobs.jsonl"
BENCH_ROWS = ROOT / "tmp/logs/nat_bench.jsonl"
DST = os.environ.get("NAT_KNOBS_DST", "198.51.100.5")  # default route only: CPU path, NAT applies; plain kernel: 10.99.2.2 (masquerade on the SVI)
SSH_CAP_S = 20  # nat_bench.sw cap; every knob command is a sysctl / ethtool / tc write, < 1 s


def gro(v: str) -> str:
    return f"for d in eth0 lan1; do ethtool -K $d rx-gro-list {v}; done"


# name: (states, set-command per state, read command, what)
KNOBS: dict[str, dict] = {
    "gro_list": {"states": ["on", "off"], "what": "fraglist GRO on eth0 + lan1",
                 "set": {"on": gro("on"), "off": gro("off")},
                 "read": "ethtool -k eth0 | grep rx-gro-list | cut -d: -f2"},
    "udp_gro_fwd": {"states": ["off", "on"], "what": "UDP GRO for forwarding",
                    "set": {v: f"for d in eth0 lan1; do ethtool -K $d rx-udp-gro-forwarding {v}; done" for v in ("on", "off")},
                    "read": "ethtool -k eth0 | grep rx-udp-gro-forwarding | cut -d: -f2"},
    "irq_cpu": {"states": ["0", "1"], "what": "eth0 IRQ on VPE0 / VPE1",
                "set": {"0": "echo 1 > /proc/irq/$(awk '/eth0/{print +$1}' /proc/interrupts)/smp_affinity",
                        "1": "echo 2 > /proc/irq/$(awk '/eth0/{print +$1}' /proc/interrupts)/smp_affinity"},
                "read": "cat /proc/irq/$(awk '/eth0/{print +$1}' /proc/interrupts)/smp_affinity"},
    "rps": {"states": ["off", "vpe1"], "what": "RPS lan1 + eth0 RX queues to VPE1",
            "set": {"off": "for f in /sys/class/net/lan1/queues/rx-*/rps_cpus /sys/class/net/eth0/queues/rx-*/rps_cpus; do echo 0 > $f; done",
                    "vpe1": "for f in /sys/class/net/lan1/queues/rx-*/rps_cpus /sys/class/net/eth0/queues/rx-*/rps_cpus; do echo 2 > $f; done"},
            "read": "cat /sys/class/net/lan1/queues/rx-0/rps_cpus"},
    "napi_thread": {"states": ["off", "on"], "what": "threaded NAPI on eth0",
                    "set": {"off": "echo 0 > /sys/class/net/eth0/threaded", "on": "echo 1 > /sys/class/net/eth0/threaded"},
                    "read": "cat /sys/class/net/eth0/threaded"},
    "napi_pin": {"states": ["free", "split"], "what": "threaded NAPI kthreads pinned: ring0 VPE0, ring1 VPE1 (needs napi_thread=on)",
                 "set": {"free": "for t in $(ps | awk '/napi\\/eth0/{print $1}'); do taskset -p 3 $t >/dev/null; done",
                         "split": "i=0; for t in $(ps | awk '/napi\\/eth0/{print $1}'); do taskset -p $((1 << (i % 2) )) $t >/dev/null; i=$((i+1)); done"},
                 "read": "for t in $(ps | awk '/napi\\/eth0/{print $1}'); do taskset -p $t; done | tr '\\n' ' '"},
    "tx_by_cpu": {"states": ["0", "1"], "what": "TX ring + reclaim follow the forwarding CPU (300-38 module param)",
                  "set": {v: f"echo {v} > /sys/module/rtl838x_eth/parameters/tx_by_cpu" for v in ("0", "1")},
                  "read": "cat /sys/module/rtl838x_eth/parameters/tx_by_cpu"},
    "rxq": {"states": ["rr", "one", "swap"], "what": "RX ring per reason (300-38 debugfs): rr = alternating, one = all ring 0, swap = host-route 0 / net-route 1",
            "set": {"rr": "echo rr > /sys/kernel/debug/rteth/rxq", "one": "echo 'all 0' > /sys/kernel/debug/rteth/rxq",
                    "swap": "echo rr > /sys/kernel/debug/rteth/rxq; echo 'l3_host_route 0' > /sys/kernel/debug/rteth/rxq; "
                            "echo 'l3_net_route 1' > /sys/kernel/debug/rteth/rxq"},
            "read": "grep -E '^l3_(host|net)_route' /sys/kernel/debug/rteth/rxq | tr '\\n' ' '"},
    "qdisc": {"states": ["mq", "noqueue"], "what": "eth0 root qdisc",
              "set": {"mq": "tc qdisc replace dev eth0 root mq 2>/dev/null; true",
                      "noqueue": "tc qdisc replace dev eth0 root noqueue 2>/dev/null; true"},
              "read": "tc qdisc show dev eth0 | head -1 | cut -d' ' -f2"},
    "ct_acct": {"states": ["1", "0"], "what": "conntrack byte/packet accounting",
                "set": {v: f"echo {v} > /proc/sys/net/netfilter/nf_conntrack_acct" for v in ("0", "1")},
                "read": "cat /proc/sys/net/netfilter/nf_conntrack_acct"},
    # conntrack tunables (#71); "dflt" = leave the kernel default untouched
    "ct_liberal": {"states": ["0", "1"], "what": "nf_conntrack_tcp_be_liberal (accept out-of-window TCP)",
                   "set": {v: f"echo {v} > /proc/sys/net/netfilter/nf_conntrack_tcp_be_liberal" for v in ("0", "1")},
                   "read": "cat /proc/sys/net/netfilter/nf_conntrack_tcp_be_liberal"},
    "ct_loose": {"states": ["1", "0"], "what": "nf_conntrack_tcp_loose (pick up mid-stream flows)",
                 "set": {v: f"echo {v} > /proc/sys/net/netfilter/nf_conntrack_tcp_loose" for v in ("0", "1")},
                 "read": "cat /proc/sys/net/netfilter/nf_conntrack_tcp_loose"},
    "ct_checksum": {"states": ["1", "0"], "what": "nf_conntrack_checksum (verify L4 checksums in conntrack)",
                    "set": {v: f"echo {v} > /proc/sys/net/netfilter/nf_conntrack_checksum" for v in ("0", "1")},
                    "read": "cat /proc/sys/net/netfilter/nf_conntrack_checksum"},
    "ct_max": {"states": ["dflt", "4096", "65536"], "what": "nf_conntrack_max (table limit)",
               "set": {"dflt": "", "4096": "echo 4096 > /proc/sys/net/netfilter/nf_conntrack_max",
                       "65536": "echo 65536 > /proc/sys/net/netfilter/nf_conntrack_max"},
               "read": "cat /proc/sys/net/netfilter/nf_conntrack_max"},
    "ct_hash": {"states": ["dflt", "1024", "16384"], "what": "nf_conntrack hashsize (buckets)",
                "set": {"dflt": "", "1024": "echo 1024 > /sys/module/nf_conntrack/parameters/hashsize",
                        "16384": "echo 16384 > /sys/module/nf_conntrack/parameters/hashsize"},
                "read": "cat /sys/module/nf_conntrack/parameters/hashsize"},
    "ft_timeout": {"states": ["30", "120"], "what": "nf_flowtable_tcp_timeout (s)",
                   "set": {v: f"echo {v} > /proc/sys/net/netfilter/nf_flowtable_tcp_timeout" for v in ("30", "120")},
                   "read": "cat /proc/sys/net/netfilter/nf_flowtable_tcp_timeout"},
    "napi_defer": {"states": ["off", "on"], "what": "IRQ coalescing emulation: napi_defer_hard_irqs 2, gro_flush_timeout 100 us",
                   "set": {"off": "echo 0 > /sys/class/net/eth0/napi_defer_hard_irqs; echo 0 > /sys/class/net/eth0/gro_flush_timeout",
                           "on": "echo 2 > /sys/class/net/eth0/napi_defer_hard_irqs; echo 100000 > /sys/class/net/eth0/gro_flush_timeout"},
                   "read": "cat /sys/class/net/eth0/napi_defer_hard_irqs"},
    "budget": {"states": ["64", "128"], "what": "NAPI weight / softirq budget (dev_weight 64|128, netdev_budget 300|600)",
               "set": {"64": "sysctl -qw net.core.dev_weight=64 net.core.netdev_budget=300",
                       "128": "sysctl -qw net.core.dev_weight=128 net.core.netdev_budget=600"},
               "read": "sysctl -n net.core.dev_weight"},
    "fw4": {"states": ["loaded", "unloaded"], "what": "OpenWrt firewall ruleset present (OpenWrt vs initramfs gap)",
            "set": {"unloaded": "nft delete table inet fw4 2>/dev/null; true", "loaded": "/etc/init.d/firewall reload >/dev/null 2>&1; true"},
            "read": "nft list tables | grep -c fw4"},
    "flowtable": {"states": ["on", "off"], "what": "nftables software flowtable (nat-bench mode nat-ft / nat)",
                  "set": {}, "read": "nft list flowtables | grep -c 'flowtable ft'"},
}
DEFAULTS = {k: v["states"][0] for k, v in KNOBS.items()}
BASE: dict[str, str] = {}  # --base: applied under every cell
# new driver / kernel knobs append here when the code lands (rx_split, rx_cpu, ...)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def nat_bench(*args: str, tag: str = "") -> int:
    env = {**os.environ, "NAT_BENCH_TAG": tag}
    return subprocess.run(["./dev.py", "nat-bench", *args], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=300).returncode  # worst: 15 s run + setup dumps, x10 margin for a hung SSH


def apply(state: dict[str, str]) -> None:
    for k, v in state.items():
        if k == "flowtable":
            nat_bench("mode", "nat-ft" if v == "on" else "nat")
        elif KNOBS[k]["set"].get(v):
            nb.sw(KNOBS[k]["set"][v], tmo=SSH_CAP_S)
    if state.get("fw4") == "loaded" or "flowtable" in state:  # fw4 reload drops the nattest accept rules
        nat_bench("mode", "nat-ft" if state.get("flowtable", DEFAULTS["flowtable"]) == "on" else "nat")


def read_state() -> dict[str, str]:
    return {k: nb.sw(v["read"], check=False, tmo=SSH_CAP_S).strip() for k, v in KNOBS.items()}


def cell(name: str, state: dict[str, str], secs: int, udp: bool) -> dict:
    full = {**DEFAULTS, **BASE, **state}
    apply(full)
    out = {"cell": name, "state": {k: v for k, v in full.items() if v != DEFAULTS[k]}}
    for kind, args in (("tcp", ["--secs", str(secs), "-P", "4"]), ("udp64", ["--secs", str(secs), "--udp", "80", "--len", "64"])):
        if kind == "udp64" and not udp:
            continue
        n0 = sum(1 for _ in BENCH_ROWS.open())
        rc = nat_bench("run", "--dst", DST, *args, "--label", f"{kind}-{name}", tag=f"knobs:{name}")
        rows = BENCH_ROWS.read_text().splitlines()[n0:]
        if rc or not rows:
            out[kind] = None
            log(f"  {name} {kind}: FAILED rc={rc}")
            continue
        r = json.loads(rows[-1])
        out[kind] = {"mbps": r["mbps"], "tx_kpps": round(r["eth0_tx_pps"] / 1000, 1),
                     "cpu0": r["cpu"]["cpu0"]["busy"], "cpu1": r["cpu"]["cpu1"]["busy"], "ns_pkt": r["ns_vpe_per_rx_pkt"]}
        log(f"  {name} {kind}: {out[kind]}")
    with ROWS.open("a") as fh:
        fh.write(json.dumps({"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **out}) + "\n")
    return out


def parse_kv(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items:
        k, _, v = it.partition("=")
        if k not in KNOBS or v not in KNOBS[k]["states"]:
            sys.exit(f"bad knob {it}; see `list`")
        out[k] = v
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("reset")
    s = sub.add_parser("set")
    s.add_argument("kv", nargs="+")
    m = sub.add_parser("matrix")
    m.add_argument("--knobs", default=",".join(k for k in KNOBS if k not in ("napi_pin", "fw4")),
                   help="knobs to flip one at a time (each to its non-default state)")
    m.add_argument("--pairs", action="store_true", help="also every pair of --knobs")
    m.add_argument("--combo", action="append", default=[], help="name=k1=v1,k2=v2 explicit combination")
    m.add_argument("--base", default="", help="k=v,k=v applied under every cell (flip knobs on top of a combination)")
    m.add_argument("--secs", type=int, default=10, help="per run; iperf ramps 2 s (-O 2)")
    m.add_argument("--udp", action="store_true", help="also UDP 64 B per cell")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if a.cmd == "list":
        cur = read_state()
        for k, v in KNOBS.items():
            print(f"{k:12} default={v['states'][0]:8} states={'/'.join(v['states']):16} now={cur[k]!r:12} {v['what']}")
        return 0
    if a.cmd == "reset":
        apply(DEFAULTS)
        return 0
    if a.cmd == "set":
        apply(parse_kv(a.kv))
        return 0
    BASE.update(parse_kv([x for x in a.base.split(",") if x]))
    names = [k for k in a.knobs.split(",") if k]
    flip = {k: KNOBS[k]["states"][1] for k in names if k not in BASE}
    cells: list[tuple[str, dict]] = [("default", {})]
    cells += [(k, {k: v}) for k, v in flip.items()]
    if a.pairs:
        cells += [(f"{x}+{y}", {x: flip[x], y: flip[y]}) for x, y in itertools.combinations(names, 2)]
    for c in a.combo:
        cname, _, spec = c.partition("=")
        cells.append((cname, parse_kv(spec.split(","))))
    log(f"matrix: {len(cells)} cells x ({'tcp+udp64' if a.udp else 'tcp'}) x {a.secs} s")
    res = [cell(n, st, a.secs, a.udp) for n, st in cells]
    apply({**DEFAULTS})
    base = (res[0].get("tcp") or {}).get("mbps") or 0
    log("--- summary (TCP P4 Mbit/s, vs default)")
    for r in sorted(res, key=lambda r: -((r.get("tcp") or {}).get("mbps") or 0)):
        t = r.get("tcp") or {}
        d = f"{(t.get('mbps', 0) / base - 1) * 100:+.0f} %" if base and t else "-"
        u = r.get("udp64") or {}
        log(f"{r['cell']:34} {t.get('mbps', '-'):>7} {d:>7}  cpu1 {t.get('cpu1', '-'):>5}  udp64 {u.get('tx_kpps', '-')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
