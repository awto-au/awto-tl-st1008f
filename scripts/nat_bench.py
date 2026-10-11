#!/usr/bin/env python3
"""nat_bench — CPU-path NAT / routing throughput through the ST1008F (docs/NAT.md, docs/NAT-OPS.md).

Topology (one-armed, all over the single 10G host link; lan1 reaches the host via the house switch):
  host netns natlan  enp7s0.991  10.99.1.2/24 gw 10.99.1.1  --VLAN 991-->  switch.991 10.99.1.1
  host netns natwan  enp7s0.992  10.99.2.2/24               <--VLAN 992--  switch.992 10.99.2.1
- Both test subnets are on-link at the switch -> the ASIC traps every packet to the CPU (l3.c design),
  so each forwarded packet crosses the CPU port twice (RX + TX).
- Test VLANs are tagged on lan1 only, never bridged to VLAN 1; no DHCP; NAT only out switch.992.
- Switch config is runtime only (bridge/ip/nft): nothing is written to flash; a reboot clears it.

Usage (via ./dev.py nat-bench ...):
  setup                              switch SVIs + host netns
  mode nat|nat-ft|route|route-ft     nft: masquerade and/or software flowtable (fw4 forward accept)
  run [--secs N] [-P N] [--reverse] [--udp MBPS --len B]   iperf3 natlan -> natwan + switch CPU stats
  local [--secs N] [-P N] [--reverse] host <-> switch iperf3 (CPU terminates; NIC/stack ceiling)
  pktgen [--count N --size B]       TX-only driver cost (in-kernel pktgen, kmod-pktgen)
  rxdrop [--secs N --size B]        RX-only driver cost (host UDP flood, dropped at lan1 ingress)
  v6-setup | v6-run [--onlink] [--dst A]   IPv6 routed through the ASIC (gateway-routed far /64s)
  status | teardown
Log: tmp/logs/nat_bench.log (one JSON line per run: tmp/logs/nat_bench.jsonl)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/nat_bench.log"
JSONL = ROOT / "tmp/logs/nat_bench.jsonl"

HOST_NIC = "enp7s0"            # host 10G (mlx4); also house mgmt, untouched
SW_IP = "192.168.25.48"        # st1008f-1 (ip-registry)
SW_PORT = "lan1"
LAN_VID, WAN_VID = 991, 992    # test-only VIDs, tagged on lan1 only
SW_LAN, SW_WAN = "10.99.1.1", "10.99.2.1"
H_LAN, H_WAN = "10.99.1.2", "10.99.2.2"
NS_LAN, NS_WAN = "natlan", "natwan"
CPU_HZ = 1_000_000_000
TAG = os.environ.get("NAT_BENCH_TAG", "")  # set by scripts/nat_clock_variants.py: variant name per row         # `clocks fast` (docs/CLOCKS-OPS.md); one 34Kc pipeline shared by 2 VPEs

SSH = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
       "-o", "ControlMaster=auto", "-o", f"ControlPath={ROOT}/tmp/nat_bench.ssh",
       "-o", "ControlPersist=120", f"root@{SW_IP}"]
# ssh command: LAN login + small /proc reads ~0.3 s; a CPU saturated by softirq stretches it to a few s.
# 20 s = ~1.25x the slowest seen under full load; expiry raises naming the command.
SSH_TMO_S = 20


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sw(cmd: str, check: bool = True, tmo: float = SSH_TMO_S) -> str:
    t0 = time.time()
    try:
        r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=tmo)
    except subprocess.TimeoutExpired:
        raise SystemExit(f"switch ssh timed out after {time.time()-t0:.1f}s (limit {tmo}s): {cmd}")
    if check and r.returncode != 0:
        raise SystemExit(f"switch cmd failed ({r.returncode}): {cmd}\n{r.stderr.strip()}")
    return r.stdout


def host(cmd: list[str], check: bool = True) -> str:
    # local ip/netns commands: instant; 10 s names a hang
    r = subprocess.run(["sudo", "-n", *cmd], capture_output=True, text=True, timeout=10)
    if check and r.returncode != 0:
        raise SystemExit(f"host cmd failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr.strip()}")
    return r.stdout


# ---- setup / teardown --------------------------------------------------------
def setup() -> int:
    log(f"setup: switch VLAN {LAN_VID}/{WAN_VID} tagged on {SW_PORT} + SVIs (runtime only)")
    cmds = []
    for vid, ip in ((LAN_VID, SW_LAN), (WAN_VID, SW_WAN)):
        cmds += [f"bridge vlan add dev {SW_PORT} vid {vid}",
                 f"bridge vlan add dev switch vid {vid} self",
                 f"ip link add link switch name switch.{vid} type vlan id {vid} 2>/dev/null; true",
                 f"ip addr replace {ip}/24 dev switch.{vid}",
                 f"ip link set switch.{vid} up"]
    sw(" && ".join(cmds))
    log(f"setup: host netns {NS_LAN}/{NS_WAN} on {HOST_NIC}.{LAN_VID}/.{WAN_VID}")
    host(["modprobe", "8021q"])
    for ns, vid, ip in ((NS_LAN, LAN_VID, H_LAN), (NS_WAN, WAN_VID, H_WAN)):
        sub = f"{HOST_NIC}.{vid}"
        host(["ip", "netns", "del", ns], check=False)
        host(["ip", "link", "del", sub], check=False)
        host(["ip", "netns", "add", ns])
        host(["ip", "link", "add", "link", HOST_NIC, "name", sub, "type", "vlan", "id", str(vid)])
        host(["ip", "link", "set", sub, "netns", ns])
        host(["ip", "-n", ns, "addr", "add", f"{ip}/24", "dev", sub])
        host(["ip", "-n", ns, "link", "set", "lo", "up"])
        # host enp7s0 runs MTU 9000; the switch ports are 1500 (jumbo -> lan1 ParserErrors, silent loss)
        # own MAC per test netns: both subifs otherwise share enp7s0's MAC + link-local (v6 ND to natwan failed)
        host(["ip", "-n", ns, "link", "set", sub, "address", f"02:99:00:00:{vid // 100:02d}:{vid % 100:02d}"])
        host(["ip", "-n", ns, "link", "set", sub, "mtu", "1500", "up"])
    host(["ip", "-n", NS_LAN, "route", "add", "default", "via", SW_LAN])
    return status()


def set_mode(mode: str) -> int:
    nat = mode.startswith("nat")
    ft = mode.endswith("-ft")
    log(f"mode {mode}: masquerade={'on' if nat else 'off'} flowtable={'on' if ft else 'off'}")
    sw("nft delete table inet nattest 2>/dev/null; "
       "nft list chain inet fw4 forward | grep -q nattest || "
       f"nft insert rule inet fw4 forward iifname '{{ switch.{LAN_VID}, switch.{WAN_VID} }}' accept "
       "comment nattest; "
       "nft list chain inet fw4 input | grep -q nattest-nd || "
       f"nft insert rule inet fw4 input iifname '{{ switch.{LAN_VID}, switch.{WAN_VID} }}' meta l4proto icmpv6 "
       "accept comment nattest-nd")  # IPv6 ND replies to the SVIs (fw4 input policy drop)
    rules = ["table inet nattest {"]
    if ft:
        rules += [f"  flowtable ft {{ hook ingress priority 0; devices = {{ {SW_PORT} }}; }}",
                  "  chain ftadd { type filter hook forward priority 0; policy accept;",
                  "    meta l4proto { tcp, udp } flow add @ft", "  }"]
    if nat:
        rules += ["  chain post { type nat hook postrouting priority srcnat; policy accept;",
                  f"    oifname switch.{WAN_VID} masquerade", "  }"]
    rules += ["}"]
    sw("nft -f - <<'EOF'\n" + "\n".join(rules) + "\nEOF")
    # route mode: natwan needs the way back to the LAN subnet (no NAT hides it)
    host(["ip", "-n", NS_WAN, "route", "del", "10.99.1.0/24"], check=False)
    if not nat:
        host(["ip", "-n", NS_WAN, "route", "add", "10.99.1.0/24", "via", SW_WAN])
    sw("conntrack -F 2>/dev/null; echo 1 >/proc/sys/net/netfilter/nf_conntrack_acct; true", check=False)
    return 0


def teardown() -> int:
    log("teardown: nattest table, fw4 reload, SVIs, bridge VLANs, host netns")
    sw("nft delete table inet nattest 2>/dev/null; nft delete table netdev rxdrop 2>/dev/null; "
       "killall iperf3 2>/dev/null; rmmod pktgen 2>/dev/null; ip -6 route del 2000::/3 2>/dev/null; "
       "/etc/init.d/firewall reload; "
       f"ip link del switch.{LAN_VID}; ip link del switch.{WAN_VID}; "
       f"bridge vlan del dev {SW_PORT} vid {LAN_VID}; bridge vlan del dev {SW_PORT} vid {WAN_VID}; "
       f"bridge vlan del dev switch vid {LAN_VID} self; bridge vlan del dev switch vid {WAN_VID} self; true",
       check=False)
    for ns, vid in ((NS_LAN, LAN_VID), (NS_WAN, WAN_VID)):
        host(["ip", "netns", "del", ns], check=False)
        host(["ip", "link", "del", f"{HOST_NIC}.{vid}"], check=False)
    return 0


def status() -> int:
    out = sw(f"bridge vlan show dev {SW_PORT}; ip -br addr | grep switch.99; "
             "nft list table inet nattest 2>/dev/null | head -20; "
             "grep -E 'nattest|99[12]' /sys/kernel/debug/realtek_otto_l3/routes; true", check=False)
    log(out.strip())
    r = subprocess.run(["sudo", "-n", "ip", "netns", "exec", NS_LAN, "ping", "-c", "2", "-W", "1", H_WAN],
                       capture_output=True, text=True, timeout=10)  # 2 pings x 1 s wait + margin
    log(f"ping {NS_LAN} -> {H_WAN}: {'OK' if r.returncode == 0 else 'FAIL'}")
    return 0 if r.returncode == 0 else 1


# ---- counters -----------------------------------------------------------------
SNAP_CMD = ("cat /proc/stat | grep '^cpu'; echo ==; cat /sys/class/net/eth0/statistics/rx_packets "
            "/sys/class/net/eth0/statistics/tx_packets /sys/class/net/eth0/statistics/rx_bytes "
            "/sys/class/net/eth0/statistics/tx_bytes /sys/class/net/eth0/statistics/rx_dropped "
            "/sys/class/net/eth0/statistics/tx_dropped; echo ==; grep eth0 /proc/interrupts; echo ==; "
            "cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null || echo 0")


def snap() -> dict:
    raw = sw(SNAP_CMD)
    cpu_part, eth_part, irq_part, ct_part = raw.split("==\n")
    cpus = {}
    for line in cpu_part.splitlines():
        f = line.split()
        cpus[f[0]] = [int(x) for x in f[1:]]
    eth = [int(x) for x in eth_part.split()]
    irq = sum(int(x) for x in irq_part.split()[1:3])
    return {"t": time.time(), "cpu": cpus, "eth0": dict(zip(
        ("rx_packets", "tx_packets", "rx_bytes", "tx_bytes", "rx_dropped", "tx_dropped"), eth)),
        "irq": irq, "ct": int(ct_part.split()[0])}


def cpu_report(a: dict, b: dict) -> dict:
    out = {}
    for name in a["cpu"]:
        d = [y - x for x, y in zip(a["cpu"][name], b["cpu"][name])]
        tot = sum(d[:8]) or 1
        # user nice system idle iowait irq softirq steal
        out[name] = {"busy": round(100 * (1 - (d[3] + d[4]) / tot), 1),
                     "softirq": round(100 * d[6] / tot, 1), "sys": round(100 * d[2] / tot, 1),
                     "irq": round(100 * d[5] / tot, 1)}
    return out


def iperf(ns_srv: str, srv_ip: str, ns_cli: str | None, secs: int, streams: int, reverse: bool,
          udp: int | None, length: int | None) -> dict:
    srv = (["sudo", "-n", "nice", "-n", "19", "ip", "netns", "exec", ns_srv] if ns_srv else []) + \
        ["iperf3", "-s", "-1", "-B", srv_ip]
    p = subprocess.Popen(srv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)  # iperf3 -s binds in <50 ms; 0.5 s keeps the client from racing it
    cli = (["sudo", "-n", "nice", "-n", "19", "ip", "netns", "exec", ns_cli] if ns_cli else []) + \
        ["iperf3", "-c", srv_ip, "-t", str(secs), "-P", str(streams), "-J", "-O", "2"]
    if reverse:
        cli.append("-R")
    if udp:
        cli += ["-u", "-b", f"{udp}M"]
    if length:
        cli += ["-l", str(length)]
    tmo = int((secs + 2) * 1.25) + 5  # run + 2 s omit, 1.25x, + connect
    try:
        r = subprocess.run(cli, capture_output=True, text=True, timeout=tmo)
    except subprocess.TimeoutExpired:
        p.kill()
        raise SystemExit(f"iperf3 timed out after {tmo}s (secs={secs})")
    p.kill()
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"iperf3 gave no JSON: {r.stdout[-400:]} {r.stderr[-400:]}")


def summarize(label: str, res: dict, a: dict, b: dict, udp: int | None) -> dict:
    end = res.get("end", {})
    if udp:
        s = end.get("sum", {})
        mbps = s.get("bits_per_second", 0) / 1e6
        extra = {"loss_pct": round(s.get("lost_percent", 0), 2), "pkts": s.get("packets")}
    else:
        mbps = end.get("sum_received", {}).get("bits_per_second", 0) / 1e6
        extra = {"retrans": end.get("sum_sent", {}).get("retransmits")}
    dt = b["t"] - a["t"]
    e = {k: (b["eth0"][k] - a["eth0"][k]) % 2**32 for k in a["eth0"]}  # 32-bit counters on MIPS32
    cpu = cpu_report(a, b)
    rx_pps = e["rx_packets"] / dt
    tx_pps = e["tx_packets"] / dt
    busy_vpe = sum(cpu[c]["busy"] for c in cpu if c != "cpu") / 100  # VPE-seconds per second
    row = {
        "label": label, "tag": TAG, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "mbps": round(mbps, 1), **extra,
        "eth0_rx_mbps": round(e["rx_bytes"] * 8 / dt / 1e6, 1), "eth0_tx_mbps": round(e["tx_bytes"] * 8 / dt / 1e6, 1),
        "eth0_rx_pps": int(rx_pps), "eth0_tx_pps": int(tx_pps),
        "eth0_rx_dropped": e["rx_dropped"], "eth0_tx_dropped": e["tx_dropped"],
        "irq_per_s": int((b["irq"] - a["irq"]) / dt), "conntrack": b["ct"], "cpu": cpu,
        # core cycles per CPU-RX packet if the busy VPE time were one 1 GHz pipeline
        "ns_vpe_per_rx_pkt": round(busy_vpe * 1e9 / rx_pps, 0) if rx_pps else None,
    }
    log(f"RESULT {label}: {row['mbps']} Mbit/s {extra} | eth0 rx {row['eth0_rx_mbps']} Mbit/s "
        f"{row['eth0_rx_pps']} pps, tx {row['eth0_tx_mbps']} Mbit/s {row['eth0_tx_pps']} pps, "
        f"drop rx/tx {e['rx_dropped']}/{e['tx_dropped']} | irq/s {row['irq_per_s']} | "
        f"cpu0 {cpu.get('cpu0')} cpu1 {cpu.get('cpu1')} | VPE-ns/pkt {row['ns_vpe_per_rx_pkt']}")
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def run(args, local: bool) -> int:
    label = args.label or ("local" if local else "fwd") + \
        f"{'-R' if args.reverse else ''}-P{args.P}{f'-udp{args.udp}-l{args.len}' if args.udp else ''}"
    if local:
        sw("nft list chain inet fw4 input | grep -q nattest || "
           f"nft insert rule inet fw4 input iifname switch.{LAN_VID} accept comment nattest; "
           f"pidof iperf3 >/dev/null || iperf3 -s -D -B {SW_LAN}")
    a = snap()
    if local:
        cli = ["sudo", "-n", "nice", "-n", "19", "ip", "netns", "exec", NS_LAN, "iperf3", "-c", SW_LAN, "-t", str(args.secs),
               "-P", str(args.P), "-J", "-O", "2"] + (["-R"] if args.reverse else []) + \
            (["-u", "-b", f"{args.udp}M", "-l", str(args.len)] if args.udp else [])
        tmo = int((args.secs + 2) * 1.25) + 5
        r = subprocess.run(cli, capture_output=True, text=True, timeout=tmo)
        res = json.loads(r.stdout)
    else:
        res = iperf(NS_WAN, H_WAN, NS_LAN, args.secs, args.P, args.reverse, args.udp, args.len)
    b = snap()
    if "error" in res:
        log(f"iperf3 error: {res['error']}")
        return 1
    summarize(label, res, a, b, args.udp)
    return 0


def pktgen(count: int, size: int) -> int:
    """TX-only cost: in-kernel pktgen on the switch, lan1 -> VLAN 992 -> natwan (host)."""
    mac = host(["ip", "netns", "exec", NS_WAN, "cat", f"/sys/class/net/{HOST_NIC}.{WAN_VID}/address"]).strip()
    pg = "/proc/net/pktgen"
    cfg = [f"modprobe pktgen", f"echo rem_device_all > {pg}/kpktgend_0", f"echo add_device {SW_PORT} > {pg}/kpktgend_0"]
    cfg += [f"echo '{c}' > {pg}/{SW_PORT}" for c in (
        f"count {count}", "clone_skb 0", f"pkt_size {size}", "delay 0", f"dst {H_WAN}", f"dst_mac {mac}",
        f"src_min {SW_WAN}", f"src_max {SW_WAN}", f"vlan_id {WAN_VID}", "udp_dst_min 9", "udp_dst_max 9")]
    sw(" && ".join(cfg))
    a = snap()
    # expected >= 5 kpps (CPU TX measured 7.7 kpps at 1400 B): count/5000 s, x1.25, + ssh
    tmo = count / 5000 * 1.25 + 10
    sw(f"echo start > {pg}/pgctrl", tmo=tmo)
    b = snap()
    res = sw(f"grep -A2 Result {pg}/{SW_PORT}")
    cpu = cpu_report(a, b)
    row = {"label": f"pktgen-tx-{size}B", "tag": TAG, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "result": " ".join(res.split()), "cpu": cpu}
    log(f"RESULT pktgen {size} B x {count}: {row['result']} | cpu0 {cpu['cpu0']} cpu1 {cpu['cpu1']}")
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    return 0


def flood(dst: str, secs: float, size: int) -> int:
    """Host-side UDP blaster (runs inside a netns via `_flood`); prints packets sent."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    payload = b"x" * size
    n, end = 0, time.time() + secs
    while time.time() < end:
        for _ in range(256):
            s.sendto(payload, (dst, 9))
        n += 256
    print(n)
    return 0


def rxdrop(secs: int, size: int) -> int:
    """RX-only cost: UDP flood to the switch SVI, dropped at lan1 netdev ingress (driver + DSA rx only)."""
    mac = host(["ip", "netns", "exec", NS_LAN, "cat", f"/sys/class/net/{HOST_NIC}.{LAN_VID}/address"]).strip()
    sw("nft delete table netdev rxdrop 2>/dev/null; nft -f - <<'EOF'\n"
       f"table netdev rxdrop {{ chain in {{ type filter hook ingress device {SW_PORT} priority -500;\n"
       # match the source MAC: the frame may still carry its VLAN tag here, so `ip daddr` misses it
       f"  ether saddr {mac} counter drop\n  }}\n}}\nEOF")
    a = snap()
    r = subprocess.run(["sudo", "-n", "nice", "-n", "19", "ip", "netns", "exec", NS_LAN, sys.executable, "-I", __file__, "_flood",
                        SW_LAN, str(secs), str(size)], capture_output=True, text=True, timeout=secs * 1.25 + 5)
    b = snap()
    cnt = sw("nft list table netdev rxdrop | grep counter")
    sw("nft delete table netdev rxdrop")
    sent = int(r.stdout.strip() or 0)
    dt = b["t"] - a["t"]
    cpu = cpu_report(a, b)
    dropped = int(cnt.split("packets")[1].split()[0])
    pps = dropped / dt
    busy = sum(cpu[c]["busy"] for c in cpu if c != "cpu") / 100
    row = {"label": f"rxdrop-{size}B", "tag": TAG, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sent": sent,
           "received_pps": int(pps), "cpu": cpu, "ns_vpe_per_pkt": round(busy * 1e9 / pps) if pps else None}
    # RX rate = eth0 packets: with rx-gro-list on (default) the ingress counter sees GRO skbs, not packets
    eth_pps = int(((b["eth0"]["rx_packets"] - a["eth0"]["rx_packets"]) % 2**32) / dt)
    row["eth0_rx_pps"] = eth_pps
    row["ns_vpe_per_pkt"] = round(busy * 1e9 / eth_pps) if eth_pps else None
    log(f"RESULT rxdrop {size} B: host sent {sent} ({sent/secs:.0f} pps), eth0 rx {eth_pps} pps, ingress-dropped "
        f"{int(pps)} pps | cpu0 {cpu['cpu0']} cpu1 {cpu['cpu1']} | VPE-ns/pkt {row['ns_vpe_per_pkt']}")
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")
    return 0


# ---- IPv6: routed (no NAT) through the ASIC -----------------------------------
V6 = {LAN_VID: ("fd99:1::1", "fd99:1::2", NS_LAN, "fd99:11::5", "fd99:11::/64"),
      WAN_VID: ("fd99:2::1", "fd99:2::2", NS_WAN, "fd99:22::5", "fd99:22::/64")}


def v6_setup() -> int:
    """Gateway-routed v6 (far /64 behind each host) -> eligible for ASIC forwarding (l3.c)."""
    cmds = []
    for vid, (svi, hip, ns, far, farnet) in V6.items():
        cmds += [f"ip -6 addr replace {svi}/64 dev switch.{vid} nodad",
                 f"ip -6 route replace {farnet} via {hip} dev switch.{vid}"]
    sw("; ".join(cmds))
    for vid, (svi, hip, ns, far, farnet) in V6.items():
        sub = f"{HOST_NIC}.{vid}"
        host(["ip", "-n", ns, "-6", "addr", "replace", f"{hip}/64", "dev", sub, "nodad"])
        host(["ip", "-n", ns, "-6", "addr", "replace", f"{far}/128", "dev", sub, "nodad"])
        host(["ip", "-n", ns, "-6", "route", "replace", "default", "via", svi])
    r = subprocess.run(["sudo", "-n", "ip", "netns", "exec", NS_LAN, "ping", "-6", "-c", "3", "-W", "1",
                        "-I", V6[LAN_VID][3], V6[WAN_VID][3]], capture_output=True, text=True, timeout=10)
    log(f"v6 ping far->far: {'OK' if r.returncode == 0 else 'FAIL'}")
    log(sw("grep fd99 /sys/kernel/debug/realtek_otto_l3/routes; true"))
    return 0 if r.returncode == 0 else 1


def v6_run(secs: int, streams: int, onlink: bool, dst: str | None = None) -> int:
    src = V6[LAN_VID][1] if onlink else V6[LAN_VID][3]
    dst = dst or (V6[WAN_VID][1] if onlink else V6[WAN_VID][3])
    sw("echo 1 > /sys/kernel/debug/realtek_otto_l3/clear_route_hits; true")
    srv = subprocess.Popen(["sudo", "-n", "nice", "-n", "19", "ip", "netns", "exec", NS_WAN, "iperf3", "-s", "-1",
                            "-B", dst], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.5)  # iperf3 -s binds in <50 ms
    a = snap()
    tmo = int((secs + 2) * 1.25) + 5
    r = subprocess.run(["sudo", "-n", "nice", "-n", "19", "ip", "netns", "exec", NS_LAN, "iperf3", "-6", "-c", dst,
                        "-B", src, "-t", str(secs), "-P", str(streams), "-J", "-O", "2"],
                       capture_output=True, text=True, timeout=tmo)
    b = snap()
    srv.kill()
    res = json.loads(r.stdout)
    summarize(f"v6-{'onlink' if onlink else 'gw'}-{dst}-tcp-P{streams}-{secs}s", res, a, b, None)
    log(sw("grep fd99 /sys/kernel/debug/realtek_otto_l3/routes; true"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    m = sub.add_parser("mode")
    m.add_argument("mode", choices=["nat", "nat-ft", "route", "route-ft"])
    for name in ("run", "local"):
        r = sub.add_parser(name)
        r.add_argument("--secs", type=int, default=15)
        r.add_argument("-P", type=int, default=4)
        r.add_argument("--reverse", action="store_true")
        r.add_argument("--udp", type=int, default=None, help="UDP target Mbit/s")
        r.add_argument("--len", type=int, default=1460, help="UDP payload bytes")
        r.add_argument("--label", default=None)
    g = sub.add_parser("pktgen")
    g.add_argument("--count", type=int, default=100000)
    g.add_argument("--size", type=int, default=1400)
    d = sub.add_parser("rxdrop")
    d.add_argument("--secs", type=int, default=10)
    d.add_argument("--size", type=int, default=1400)
    f = sub.add_parser("_flood")
    f.add_argument("dst")
    f.add_argument("secs", type=float)
    f.add_argument("size", type=int)
    sub.add_parser("v6-setup")
    v = sub.add_parser("v6-run")
    v.add_argument("--secs", type=int, default=10)
    v.add_argument("-P", type=int, default=4)
    v.add_argument("--onlink", action="store_true", help="host-to-host on-link (expect CPU trap)")
    v.add_argument("--dst", default=None, help="far v6 address on natwan (e.g. one behind 2000::/3)")
    sub.add_parser("status")
    sub.add_parser("teardown")
    a = ap.parse_args()
    if a.cmd == "_flood":
        return flood(a.dst, a.secs, a.size)
    log(f"=== nat_bench {' '.join(sys.argv[1:])} ===")
    if a.cmd == "setup":
        return setup()
    if a.cmd == "mode":
        return set_mode(a.mode)
    if a.cmd in ("run", "local"):
        return run(a, a.cmd == "local")
    if a.cmd == "pktgen":
        return pktgen(a.count, a.size)
    if a.cmd == "rxdrop":
        return rxdrop(a.secs, a.size)
    if a.cmd == "v6-setup":
        return v6_setup()
    if a.cmd == "v6-run":
        return v6_run(a.secs, a.P, a.onlink, a.dst)
    if a.cmd == "status":
        return status()
    return teardown()


if __name__ == "__main__":
    sys.exit(main())
