#!/usr/bin/env python3
"""Roll the vendor web-UI and CLI inventories up into feature areas (counts for docs/MANAGED-FEATURES.md).

- Inputs: `webui.json` (tplink_webui_inventory.py) and `cli-tree.json` (tplink_cli_tree.py) in `--inv`.
- Web page -> area by menu-path keyword; CLI command -> area by its feature keyword (first word after
  `configure` / `configure <iface>` / `show` / `clear`). First matching rule wins.
- Counts per area: backed web pages, form fields + columns on them, TDCP tables, CLI commands implemented
  on this device (`impl`), CLI commands with no registered backend.
- Log: tmp/logs/tplink_feature_areas.log
"""

import argparse
import collections
import json
import logging
import sys
from pathlib import Path

log = logging.getLogger("tplink_feature_areas")

# (area, web menu keywords, CLI keywords); first match wins, so the generic Ports rule is last
AREAS = [
    ("Stacking", ["Stack"], ["stack", "mad", "switch", "cluster"]),
    ("Optics / DDM", ["Optical Module"], ["ddm", "transceiver"]),
    ("Statistics / RMON", ["Traffic Statistics", "RMON"], ["rmon", "counters", "qos-queue-statistics"]),
    ("Mirroring", ["Port Monitoring"], ["monitor"]),
    ("Loop detection", ["Loopback Detection"], ["loopback-detection", "dldp"]),
    ("Port isolation / security", ["Port Isolation", "Port Security"], ["port-isolation", "port"]),
    ("LAG / LACP", ["Aggregation"], ["channel-group", "lacp", "port-channel", "etherchannel"]),
    ("MAC table", ["Address Table"], ["mac"]),
    ("VLAN (802.1Q, MAC/protocol/subnet, QinQ, GVRP, PVLAN)", ["VLAN > ", "Voice VLAN"],
     ["vlan", "switchport", "mac-vlan", "protocol-vlan", "ip-subnet-vlan", "dot1q-tunnel", "gvrp", "voice",
      "vlan-mac-security"]),
    ("STP / MSTP / ERPS", ["Spanning Tree", "ERPS"], ["spanning-tree", "erps"]),
    ("Multicast snooping", ["Multicast"], ["igmp", "mld"]),
    ("Dynamic routing absent here (BGP, OSPF, IS-IS, PIM, MPLS, BFD)", [],
     ["bgp", "ospf", "isis", "pim", "mpls", "bfd", "evpn", "vxlan", "nve", "static-lsp", "tunnel"]),
    ("QoS / storm / rate", ["Quality of Service"], ["qos", "storm-control", "bandwidth"]),
    ("ACL / time ranges", ["Access Control"], ["access-list", "time-range", "holiday", "ucl"]),
    ("L2 security (DHCP snoop, ARP, IPSG, DoS)", ["DHCP Snooping", "ARP Protection", "IP Source", "DoS",
                                                  "Flood-CPU", "Four-Tuple"],
     ["attacktrace", "ipsg", "arp-inspection", "dos", "dhcp-snooping"]),
    ("802.1X / AAA / RADIUS / TACACS+", ["802.1X", "AAA"], ["dot1x", "aaa", "radius", "radius-server",
                                                              "tacacs-server"]),
    ("DHCP server / relay", ["DHCP"], ["dhcp"]),
    ("L3: interfaces, static, RIP, VRRP, PBR, ARP/ND", ["Routing", "Interface Configuration", "ARP Function",
                                                         "Routing Table"],
     ["ip", "ipv6", "route-map", "router", "arp", "arp-cache", "vrf", "track"]),
    ("LLDP / LLDP-MED", ["LLDP"], ["lldp"]),
    ("SNMP", ["SNMP"], ["snmp-server"]),
    ("Syslog / monitoring / diagnostics", ["Log Management", "Running Status", "System Diagnosis",
                                           "Testing Tool", "Debug Mode"],
     ["logging", "log", "cpu-utilization", "memory-utilization", "ping", "tracert", "nqa", "temperature",
      "environment", "fan", "power", "debugging", "history"]),
    ("Management access (users, HTTP/S, SSH, Telnet, time)", ["User Management", "Security Management",
                                                               "System Time", "Management Port", "login"],
     ["user", "line", "telnet", "service", "http", "ssh", "system-time", "ntp-service", "hostname", "location",
      "contact-info", "enable", "enable-admin", "dns", "language", "screen-length", "screen-width", "who",
      "whoami", "system-info", "telnet-status"]),
    ("Config / firmware", ["System Tool"], ["copy", "firmware", "boot", "reboot", "reset", "remove",
                                            "running-config", "startup-config", "backup-config", "image-info",
                                            "files-in-system", "flash"]),
    ("Cloud management", ["Cloud Management"], ["cloud-server"]),
    ("sFlow", ["sFlow"], ["sflow"]),
    ("PTP", ["Time Synchronization"], ["ptp"]),
    ("PoE", ["PoE"], []),
    ("Industrial (Modbus, PROFINET, IEC 61850, serial)", ["Industrial Protocol"],
     ["modbus", "modbus-gateway", "profinet", "serial", "socket", "relay-warning"]),
    ("Terminal management", ["Terminal Management"], []),
    ("Ports (speed, FC, EEE, FEC, jumbo)", ["Port Configuration", "Rate Compatibility", "Port Interrupt",
                                           "Fault Monitoring"],
     ["speed", "duplex", "flow-control", "jumbo", "fec", "energy-efficient-ethernet", "shutdown", "description",
      "pattern", "port-auto-sleep", "interface", "cable-diagnostics", "led", "panel-id-led"]),
]


def cli_key(cmd: str) -> str:
    """Feature keyword; `ip`/`ipv6` commands keep their second word (`ip igmp`, `ipv6 mld`, ...)."""
    p = cmd.split()
    if p[0] == "configure" and len(p) > 1:
        q = p[2:] if p[1] in ("routeInterface", "virtualInterface", "interface") and len(p) > 2 else p[1:]
    elif p[0] in ("show", "clear", "debug") and len(p) > 1:
        q = p[1:]
    else:
        q = p
    if q[0] in ("ip", "ipv6") and len(q) > 1:
        sub = {"igmp": "igmp", "mld": "mld", "source": "ipsg", "verify": "ipsg", "savi": "ipsg", "bind": "ipsg",
               "arp": "arp-inspection", "dos-prevent": "dos", "cpu-defend": "dos", "http": "http", "ssh": "ssh",
               "bgp": "bgp", "ospf": "ospf", "pim": "pim", "mroute": "pim", "multicast-routing": "pim",
               "community-list": "bgp", "as-path-access-list": "bgp"}.get(q[1])
        if q[1] == "dhcp":
            sub = "dhcp-snooping" if len(q) > 2 and q[2] in ("snooping", "filter") else "dhcp"
        return sub or q[0]
    return q[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--inv", type=Path, required=True)
    a = ap.parse_args()
    Path("tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.FileHandler("tmp/logs/tplink_feature_areas.log", "w"),
                                  logging.StreamHandler()])
    web = json.loads((a.inv / "webui.json").read_text())
    cli = json.loads((a.inv / "cli-tree.json").read_text())
    st = collections.defaultdict(lambda: collections.Counter())
    tables = collections.defaultdict(set)
    other = collections.Counter()
    for p in web["pages"]:
        path = " > ".join(p["menu"])
        area = next((n for n, kws, _ in AREAS if any(k in path for k in kws)), None)
        if not area or not p["backed"]:
            continue
        st[area]["pages"] += 1
        st[area]["fields"] += len(p["fields"]) + len(p["columns"])
        tables[area] |= {f"{m}.{t}" for _, m, t in p["requests"]}
    for c in cli:
        if c["cmd"].split()[0] == "debug":
            continue
        k = cli_key(c["cmd"])
        area = next((n for n, _, kws in AREAS if k in kws), None)
        if area is None:
            other[k] += 1
            continue
        st[area]["cli_impl" if c["impl"] else ("cli_nobackend" if c["imi"] else "cli_unresolved")] += 1
    rows = []
    for n, _, _ in AREAS:
        s = st[n]
        rows.append({"area": n, "pages": s["pages"], "fields": s["fields"], "tables": len(tables[n]),
                     "cli_impl": s["cli_impl"], "cli_nobackend": s["cli_nobackend"],
                     "cli_unresolved": s["cli_unresolved"]})
        log.info("%-58s pages %3d fields %4d tables %3d cli impl %4d nobackend %4d unresolved %4d", n,
                 s["pages"], s["fields"], len(tables[n]), s["cli_impl"], s["cli_nobackend"], s["cli_unresolved"])
    log.info("unmapped CLI keywords (top 40): %s", other.most_common(40))
    (a.inv / "areas.json").write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
