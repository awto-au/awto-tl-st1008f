#!/usr/bin/env python3
"""routing_wirespeed — measure HW-L3 routed throughput through the ST1008F and
prove the ASIC (not the CPU) does the forwarding, with error counters watched
on BOTH the switch and the host.

Topology (router-on-a-stick / hairpin over the single 10G host link):
  host enp7s0 (mgmt, untagged, 192.168.25.30)  ── lan1 ──  switch
    enp7s0.10 (VLAN10) in netns ns10  10.0.1.2/24  -> SVI switch.10 10.0.1.1
    enp7s0.20 (VLAN20) in netns ns20  10.0.2.2/24  -> SVI switch.20 10.0.2.1
  iperf3 ns10 -> ns20 forces every packet onto the wire, through the switch's
  inter-VLAN HW-L3 route, and back out lan1 (hairpin). The 10G cable carries
  BOTH directions, so routed throughput caps ~5 Gbit/s -- the cap is the host
  cable, not the ASIC.

Why netns: both test IPs are local to one host; without separate netns the
kernel routes ns10<->ns20 over loopback and never touches the wire.

HW-offload proof (two independent): (1) switch eth0 (CPU port) rx/tx stay ~flat
-- if traffic were punted/software-routed the CPU port would carry the whole
iperf volume; (2) the ASIC route table (debugfs routes) shows the inter-VLAN
routes with ACTION=fwd and their HIT counters climb (cleared before the run).

Config lands on OpenWrt's overlay only (uci) -- NOT U-Boot/vendor flash -- and
`teardown` reverts it. Management VLAN1 is never touched, so SSH survives setup.

Usage:
  routing_wirespeed.py setup          # configure switch + host, verify route
  routing_wirespeed.py run [--secs N] [--streams P] [--udp MBPS]
  routing_wirespeed.py status
  routing_wirespeed.py teardown
Log: tmp/logs/routing_wirespeed.log
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/routing_wirespeed.log"

# --- fixed test topology ---------------------------------------------------
HOST_NIC = "enp7s0"                 # the single 10G host NIC (mlx4), mgmt + trunk
from boards import BENCH_IP  # noqa: E402
SW_IP = BENCH_IP                    # sw2 bench unit (scripts/boards.py)
SW_PORT = "lan1"                    # hairpin front port (host is here)
CPU_PORT = "eth0"                   # switch CPU port -- must stay flat
VLANS = {                           # vlan -> (svi_ip, gw_host_ip, netns, far_ip)
    10: ("10.0.1.1", "10.0.1.2", "ns10", "172.16.1.5"),
    20: ("10.0.2.1", "10.0.2.2", "ns20", "172.16.2.5"),
}
FAR = {10: "172.16.1.0/24", 20: "172.16.2.0/24"}  # subnet behind each gw host
SRC_NS, DST_NS = "ns10", "ns20"
SRC_FAR, DST_FAR = VLANS[10][3], VLANS[20][3]
# The RTL930x L3 offload only HW-forwards routes reached THROUGH A GATEWAY whose
# MAC is learnt on a switch port; directly-connected (on-link) destinations are
# trapped to CPU by design (see l3.c). So each endpoint sits in a FAR subnet
# behind its VLAN host (the gateway), making both directions gateway-routed and
# thus eligible for hardware forwarding.

# ssh to the switch: dropbear needs the legacy algo opt-ins; blank root pw
SSH = [
    "ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
    "-o", "PreferredAuthentications=password", "-o", "PubkeyAuthentication=no",
    "-o", "HostKeyAlgorithms=+ssh-rsa",
    "-o", "KexAlgorithms=+diffie-hellman-group14-sha1",
    "-o", "ConnectTimeout=8", f"root@{SW_IP}",
]

# iperf3 subprocess timeout: expected worst case = run secs + TCP connect/setup
# (~3s) + JSON flush; cap at 1.25x+margin so a hung iperf names itself in the
# log instead of blocking forever. Computed per-run in run_iperf().
IPERF_SETUP_S = 5


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def sw(cmd: str, check: bool = True) -> str:
    """Run a shell command on the switch over ssh; return stdout."""
    r = subprocess.run(SSH + [cmd], capture_output=True, text=True, timeout=30)
    if check and r.returncode != 0:
        raise SystemExit(f"switch cmd failed ({r.returncode}): {cmd}\n{r.stderr}")
    return r.stdout


def host(cmd: list[str], check: bool = True, sudo: bool = True) -> str:
    """Run a command on the host (optionally via sudo -n); return stdout."""
    full = (["sudo", "-n"] if sudo else []) + cmd
    r = subprocess.run(full, capture_output=True, text=True, timeout=30)
    if check and r.returncode != 0:
        raise SystemExit(f"host cmd failed ({r.returncode}): {' '.join(cmd)}\n{r.stderr}")
    return r.stdout


# --- setup -----------------------------------------------------------------
def setup_switch() -> None:
    log("switch: adding VLAN10/20 bridge-vlans (lan1 tagged) + SVIs + firewall")
    uci = [
        "uci -q delete network.vlan10", "uci -q delete network.vlan20",
        "uci -q delete network.dev_sw10", "uci -q delete network.dev_sw20",
        "uci -q delete network.r10", "uci -q delete network.r20",
        "uci set network.vlan10=bridge-vlan",
        "uci set network.vlan10.device=switch",
        "uci set network.vlan10.vlan=10",
        f"uci add_list network.vlan10.ports='{SW_PORT}:t'",
        "uci set network.vlan20=bridge-vlan",
        "uci set network.vlan20.device=switch",
        "uci set network.vlan20.vlan=20",
        f"uci add_list network.vlan20.ports='{SW_PORT}:t'",
        "uci set network.dev_sw10=device",
        "uci set network.dev_sw10.name=switch.10",
        "uci set network.r10=interface",
        "uci set network.r10.device=switch.10",
        "uci set network.r10.proto=static",
        f"uci add_list network.r10.ipaddr='{VLANS[10][0]}/24'",
        "uci set network.dev_sw20=device",
        "uci set network.dev_sw20.name=switch.20",
        "uci set network.r20=interface",
        "uci set network.r20.device=switch.20",
        "uci set network.r20.proto=static",
        f"uci add_list network.r20.ipaddr='{VLANS[20][0]}/24'",
        # firewall: put both SVIs in 'lan' zone (forward=ACCEPT) so inter-VLAN
        # routing is permitted (the first packets + ARP go through netfilter
        # before the ASIC offload installs).
        "uci -q del_list firewall.@zone[0].network='r10'",
        "uci -q del_list firewall.@zone[0].network='r20'",
        "uci add_list firewall.@zone[0].network='r10'",
        "uci add_list firewall.@zone[0].network='r20'",
        "uci commit network", "uci commit firewall",
        "/etc/init.d/network reload", "/etc/init.d/firewall reload",
    ]
    sw(" ; ".join(uci))


def setup_host() -> None:
    log("host: creating netns + VLAN subifs on " + HOST_NIC)
    host(["modprobe", "8021q"])
    for vid, (svi, hip, ns, far) in VLANS.items():
        sub = f"{HOST_NIC}.{vid}"
        # clean any prior run, then build
        host(["ip", "netns", "del", ns], check=False)
        host(["ip", "link", "del", sub], check=False)
        host(["ip", "netns", "add", ns])
        host(["ip", "link", "add", "link", HOST_NIC, "name", sub,
              "type", "vlan", "id", str(vid)])
        host(["ip", "link", "set", sub, "netns", ns])
        host(["ip", "-n", ns, "addr", "add", f"{hip}/24", "dev", sub])
        # far address this host owns (the gateway-routed endpoint)
        host(["ip", "-n", ns, "addr", "add", f"{far}/32", "dev", sub])
        host(["ip", "-n", ns, "link", "set", "lo", "up"])
        host(["ip", "-n", ns, "link", "set", sub, "up"])
        host(["ip", "-n", ns, "route", "add", "default", "via", svi])
    # route each netns's traffic for the OTHER far subnet via the switch SVI
    host(["ip", "-n", SRC_NS, "route", "replace", FAR[20], "via", VLANS[10][0]])
    host(["ip", "-n", DST_NS, "route", "replace", FAR[10], "via", VLANS[20][0]])


def setup_switch_routes() -> None:
    """Static gateway routes in the switch FIB so the far subnets are reached
    THROUGH a gateway host (not on-link) -> eligible for HW forwarding. Added to
    the main table via `ip route` so the FIB notifier mirrors them to the ASIC;
    transient (gone on reboot/reload), which suits a bench test."""
    log("switch: adding gateway routes to far subnets (FIB -> ASIC mirror)")
    sw(f"ip route replace {FAR[10]} via {VLANS[10][1]} dev switch.10 ; "
       f"ip route replace {FAR[20]} via {VLANS[20][1]} dev switch.20",
       check=False)


def verify() -> bool:
    log(f"verify: ping gateway-routed ({SRC_FAR} -> {DST_FAR}) + check ASIC action")
    r = subprocess.run(
        ["sudo", "-n", "ip", "netns", "exec", SRC_NS,
         "ping", "-c", "3", "-W", "2", "-I", SRC_FAR, DST_FAR],
        capture_output=True, text=True, timeout=20)
    ok = r.returncode == 0
    log(f"  ping routed: {'OK' if ok else 'FAIL'}")
    if not ok:
        log("  " + r.stdout.strip().replace("\n", " | "))
    routes = sw("cat /sys/kernel/debug/realtek_otto_l3/routes", check=False)
    for line in routes.splitlines():
        if "172.16" in line:
            log("  ASIC route: " + " ".join(line.split()))
    return ok


# --- counters --------------------------------------------------------------
def snap() -> dict:
    s: dict = {}
    # switch CPU port + hairpin port (ethtool stats) + link /sys stats
    s["sw_eth0"] = _sys_stats_switch(CPU_PORT)
    s["sw_lan1"] = _sys_stats_switch(SW_PORT)
    s["sw_lan1_et"] = _ethtool_switch(SW_PORT)
    # host NIC error counters (the one physical NIC carries both VLANs)
    s["host_nic"] = _ethtool_host(HOST_NIC)
    # authoritative wire bytes from /sys (ethtool -S bytes are GSO/GRO-inflated)
    s["host_wire"] = _host_sys_bytes(HOST_NIC)
    return s


def _host_sys_bytes(dev: str) -> dict:
    d = {}
    for k in ("rx_bytes", "tx_bytes"):
        d[k] = int(Path(f"/sys/class/net/{dev}/statistics/{k}").read_text())
    return d


def _sys_stats_switch(dev: str) -> dict:
    out = sw(f"grep . /sys/class/net/{dev}/statistics/* ", check=False)
    d = {}
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.rpartition(":")
            d[k.split("/")[-1]] = int(v) if v.strip().isdigit() else v.strip()
    return d


def _ethtool_switch(dev: str) -> dict:
    out = sw(f"ethtool -S {dev}", check=False)
    return _parse_ethtool(out)


def _ethtool_host(dev: str) -> dict:
    out = host(["ethtool", "-S", dev], check=False)
    return _parse_ethtool(out)


def _parse_ethtool(out: str) -> dict:
    d = {}
    for line in out.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            v = v.strip()
            if v.isdigit():
                d[k.strip()] = int(v)
    return d


def _delta(before: dict, after: dict, keys: list[str]) -> dict:
    out = {}
    for k in keys:
        b, a = before.get(k), after.get(k)
        if isinstance(b, int) and isinstance(a, int):
            out[k] = a - b
    return out


# --- run -------------------------------------------------------------------
def run_iperf(secs: int, streams: int, udp_mbps: int | None) -> dict:
    # start server in dst netns, bound to the far address
    srv = subprocess.Popen(
        ["sudo", "-n", "ip", "netns", "exec", DST_NS, "iperf3", "-s", "-1",
         "-B", DST_FAR],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    client_up_deadline = time.time() + 3  # server listen is near-instant; poll
    while time.time() < client_up_deadline:
        if subprocess.run(["sudo", "-n", "ip", "netns", "exec", DST_NS,
                           "sh", "-c", "ss -ltn | grep -q 5201"],
                          capture_output=True).returncode == 0:
            break
    cmd = ["sudo", "-n", "ip", "netns", "exec", SRC_NS, "iperf3",
           "-c", DST_FAR, "-B", SRC_FAR, "-t", str(secs),
           "-P", str(streams), "-J"]
    if udp_mbps:
        cmd += ["-u", "-b", f"{udp_mbps}M"]
    # aggressive timeout: run secs + connect/setup, 1.25x + small margin
    tmo = int(secs * 1.25) + IPERF_SETUP_S + 5
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=tmo)
    except subprocess.TimeoutExpired:
        srv.kill()
        raise SystemExit(f"iperf3 timed out after {tmo}s (run secs={secs})")
    srv.kill()
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        raise SystemExit(f"iperf3 produced no JSON:\n{r.stdout}\n{r.stderr}")


def cmd_run(secs: int, streams: int, udp_mbps: int | None) -> int:
    setup_switch_routes()  # transient; re-assert in case a reload cleared them
    if not verify():
        raise SystemExit("route not up -- run `setup` first")
    sw("echo 1 > /sys/kernel/debug/realtek_otto_l3/clear_route_hits", check=False)
    before = snap()
    t0 = time.time()
    log(f"iperf3: {secs}s, {streams} stream(s), "
        f"{'UDP '+str(udp_mbps)+'Mbps' if udp_mbps else 'TCP'}")
    res = run_iperf(secs, streams, udp_mbps)
    dt = time.time() - t0
    after = snap()
    report(res, before, after, dt, udp_mbps)
    return 0


def report(res: dict, before: dict, after: dict, dt: float,
           udp_mbps: int | None) -> None:
    end = res.get("end", {})
    if udp_mbps:
        s = end.get("sum", {})
        gbps = s.get("bits_per_second", 0) / 1e9
        loss = s.get("lost_percent", 0)
        extra = f"loss={loss:.3f}%  jitter={s.get('jitter_ms',0):.3f}ms"
    else:
        s = end.get("sum_sent", {})
        rcv = end.get("sum_received", {})
        gbps = rcv.get("bits_per_second", 0) / 1e9
        extra = f"retransmits={s.get('retransmits','?')}"

    eth0_d = _delta(before["sw_eth0"], after["sw_eth0"],
                    ["rx_packets", "tx_packets", "rx_bytes", "tx_bytes"])
    lan1_sys = _delta(before["sw_lan1"], after["sw_lan1"],
                      ["rx_packets", "tx_packets", "rx_errors", "tx_errors",
                       "rx_dropped", "tx_dropped", "rx_crc_errors"])
    lan1_et = _delta(before["sw_lan1_et"], after["sw_lan1_et"],
                     ["ifOutDiscards", "dot1dTpPortInDiscards", "DropEvents"])
    nic_err = _delta(before["host_nic"], after["host_nic"],
                     [k for k in before["host_nic"]
                      if any(x in k for x in ("err", "drop", "discard",
                                              "crc", "missed", "fifo"))])

    routes = sw("cat /sys/kernel/debug/realtek_otto_l3/routes", check=False)
    hits = [" ".join(l.split()) for l in routes.splitlines()
            if "172.16" in l]

    # iperf volume for the offload comparison
    rx_bytes_total = (end.get("sum_received", {}).get("bytes")
                      or end.get("sum", {}).get("bytes", 0))
    cpu_share = (eth0_d.get("rx_bytes", 0) + eth0_d.get("tx_bytes", 0))

    # authoritative wire rate from /sys byte counters. Full-duplex 10G: the
    # routed flow leaves on VLAN10 (TX fiber) and returns on VLAN20 (RX fiber),
    # independent 10G channels, so goodput can approach line rate on each.
    wire = _delta(before["host_wire"], after["host_wire"], ["rx_bytes", "tx_bytes"])
    wtx = wire.get("tx_bytes", 0) * 8 / dt / 1e9
    wrx = wire.get("rx_bytes", 0) * 8 / dt / 1e9

    log("")
    log("================ ROUTED WIRE-SPEED TEST ================")
    log(f"goodput (iperf)   : {gbps:.2f} Gbit/s   {extra}")
    log(f"WIRE (host /sys)  : TX {wtx:.2f} Gbit/s  RX {wrx:.2f} Gbit/s "
        f"(full-duplex 10G; each near line rate)")
    log(f"iperf bytes moved : {rx_bytes_total/1e9:.2f} GB in {dt:.1f}s")
    log("--- HW-offload proof -----------------------------------")
    log(f"switch CPU port eth0 delta: {eth0_d}")
    log(f"  CPU carried {cpu_share/1e6:.2f} MB vs {rx_bytes_total/1e6:.1f} MB "
        f"routed  ({100*cpu_share/max(rx_bytes_total,1):.3f}% via CPU)")
    for h in hits:
        log(f"  ASIC route: {h}")
    log("--- error counters (want all zero) ---------------------")
    log(f"switch lan1 /sys : {lan1_sys}")
    log(f"switch lan1 drops: {lan1_et}")
    log(f"host {HOST_NIC} err : {nic_err}")
    log("========================================================")
    # verdict: offloaded if CPU port carried <2% of the routed volume; clean if
    # no error/drop/discard counter moved (packet-count keys excluded).
    offloaded = cpu_share < max(rx_bytes_total * 0.02, 5_000_000)
    errs = sum(v for k, v in {**lan1_sys, **lan1_et, **nic_err}.items()
               if "packet" not in k and isinstance(v, int))
    log(f"VERDICT: offload={'HW' if offloaded else 'CPU(!)'}  "
        f"errors={'clean' if errs == 0 else errs}")


# --- teardown / status -----------------------------------------------------
def teardown() -> int:
    log("teardown: reverting switch uci + routes + removing host netns/vlan")
    sw(f"ip route del {FAR[10]} 2>/dev/null ; ip route del {FAR[20]} 2>/dev/null",
       check=False)
    sw(" ; ".join([
        "uci -q delete network.vlan10", "uci -q delete network.vlan20",
        "uci -q delete network.dev_sw10", "uci -q delete network.dev_sw20",
        "uci -q delete network.r10", "uci -q delete network.r20",
        "uci -q del_list firewall.@zone[0].network='r10'",
        "uci -q del_list firewall.@zone[0].network='r20'",
        "uci commit network", "uci commit firewall",
        "/etc/init.d/network reload", "/etc/init.d/firewall reload",
    ]), check=False)
    for vid, (_, _, ns, _) in VLANS.items():
        host(["ip", "netns", "del", ns], check=False)
        host(["ip", "link", "del", f"{HOST_NIC}.{vid}"], check=False)
    log("teardown done")
    return 0


def probe(secs: int) -> int:
    """Run a sustained flow and poll the ASIC route table + CPU port WHILE it
    runs, to catch a /32 fwd entry installing mid-run (the before/after snapshot
    in `run` misses it if offload is transient). Polls until iperf exits."""
    setup_switch_routes()
    if not verify():
        raise SystemExit("route not up -- run `setup` first")
    srv = subprocess.Popen(
        ["sudo", "-n", "ip", "netns", "exec", DST_NS, "iperf3", "-s", "-1",
         "-B", DST_FAR],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cli = subprocess.Popen(
        ["sudo", "-n", "ip", "netns", "exec", SRC_NS, "iperf3",
         "-c", DST_FAR, "-B", SRC_FAR, "-t", str(secs), "-P", "4"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    saw_fwd = False
    samples = 0
    deadline = time.time() + secs + 10  # hard stop: run + margin (names itself)
    last_eth0 = None
    while cli.poll() is None and time.time() < deadline:
        routes = sw("cat /sys/kernel/debug/realtek_otto_l3/routes", check=False)
        e = _sys_stats_switch(CPU_PORT)
        samples += 1
        fwd_lines = [" ".join(l.split()) for l in routes.splitlines()
                     if "172.16" in l and " fwd " in l]
        if fwd_lines and not saw_fwd:
            saw_fwd = True
            for fl in fwd_lines:
                log(f"  [mid-run] FWD route appeared: {fl}")
        if last_eth0 is not None:
            drx = e["rx_packets"] - last_eth0["rx_packets"]
            log(f"  [mid-run {samples}] CPU-port rx +{drx} pkts/sample  "
                f"fwd_seen={saw_fwd}")
        last_eth0 = e
    cli.wait()
    srv.kill()
    log(f"probe done: {samples} samples, FWD route {'SEEN' if saw_fwd else 'NEVER'}"
        f" -> {'HW offload installs mid-run' if saw_fwd else 'always trap = CPU'}")
    return 0


def status() -> int:
    log("--- switch ASIC routes (10.0.x) ---")
    routes = sw("cat /sys/kernel/debug/realtek_otto_l3/routes", check=False)
    for l in routes.splitlines():
        if "172.16" in l or "DESTINATION" in l:
            log("  " + " ".join(l.split()))
    log("--- host netns ---")
    log(host(["ip", "netns", "list"], check=False, sudo=True).strip() or "(none)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("setup")
    r = sub.add_parser("run")
    r.add_argument("--secs", type=int, default=20)
    r.add_argument("--streams", type=int, default=4)
    r.add_argument("--udp", type=int, default=None, help="UDP target Mbps")
    p = sub.add_parser("probe")
    p.add_argument("--secs", type=int, default=20)
    sub.add_parser("teardown")
    sub.add_parser("status")
    a = ap.parse_args()

    log(f"=== routing_wirespeed {a.cmd} {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ===")
    if a.cmd == "setup":
        setup_switch()
        setup_host()
        setup_switch_routes()
        return 0 if verify() else 1
    if a.cmd == "run":
        return cmd_run(a.secs, a.streams, a.udp)
    if a.cmd == "probe":
        return probe(a.secs)
    if a.cmd == "teardown":
        return teardown()
    if a.cmd == "status":
        return status()
    return 2


if __name__ == "__main__":
    sys.exit(main())
