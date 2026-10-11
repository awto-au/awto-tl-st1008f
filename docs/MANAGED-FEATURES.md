# Managed-firmware feature inventory (TL-ST5008F v2 1.2.0, RTL9303) vs ours (#79)

What TP-Link's managed firmware for the same chip offers, how it is wired, and what our 7.3 + OpenWrt has. Feeds #79 step 2-3.

## Sources and tools

- Firmware: `TL-ST5008F V2.0_1.2.0_Build_20260506_Rel.71783(s)` (China build, `8SFP+ L3 Managed Switch`), extracted in `private/china/st5008f-v2-extracted/` (FIRMWARE-ANALYSIS.md). Static analysis only; nothing executed.
- Web UI: `rootfs/usrImage/data/webImage.z` → `scripts/tplink_ow_unpack.py` → 269 files (Vue 2 `dmui` app, built 2026-03-31).
- Web inventory: `scripts/tplink_webui_inventory.py` → `inventory/webui.{json,md}` (menu → page → fields → API → backend).
- CLI inventory: `scripts/tplink_cli_tree.py` → `inventory/cli-tree.{json,txt}` (every command, params, enum choices, handler, backend daemon).
- Roll-up: `scripts/tplink_feature_areas.py` → `inventory/areas.json` (counts below).
- Outputs live in `private/china/st5008f-v2-extracted/inventory/` (vendor-derived, not tracked).

### `OW` asset bundle format

- Optional LZMA-alone wrapper (`5d 00 00 80 00`), as shipped in `webImage.z`; decompresses to `webImage.decoded` (4.8 MB).
- Header: `OW` x16 (32 bytes), BE u32 version (1), BE u32 file count (269 here).
- Entry, 140 bytes: name[128] NUL-padded absolute path (`/rc_filesys/doc/...`), BE u32 size, BE u32 absolute offset, BE u32 flags (0 for all).
- Data uncompressed, 4-byte aligned, right after the table (first at `0x9344` = 40 + 269 x 140).

### Management plumbing (how every surface reaches the switch)

- **TDCP JSON** is the one config API. Web, cloud and app all send `{"method":"get|set|add|del|do", "<module>":{"name"|"table":"<x>", ...}}` to `POST /stok=<token>/ds`; uploads/downloads use `/stok=<token>/<path>`.
- Backends register handlers by name: `REGISTER_CB_FOR_TDCP_JSON("<module>","<table>",TDCP_MTH_*,imi_slp_*)` (536 registrations) or `slp_json_file_register` + `imi_slp_*` (697 handler names). Owners: `core` (388), `sysmanage` (87), `mcast` (58), `snmpd` (32), `mstp` (19), `frrService` (18), `httpd` (13), `nms_report`, `cloud_sdk`, `nqa`, `ssh`, `app_vlanVoice`.
- **CLI**: `cli_server` holds a static node tree (12-word nodes, see the script docstring). Leaf → `wmcli_*` → `cli_*` → IMI call by name `imi_cli_*`; daemons register names with `TPIMI_REGISTER_COMMAND(imi_cli_*)` (1656 registrations across 14 binaries).
- **Runtime menu trim**: the UI asks `{function:{name:"new_module_spec"}}` and `{<module>:{name:"capability"}}`, then hides pages via a path → capability map. Statically reproduced as "backed" = request table has a backend handler.
- Process model (from `/etc/daemons`, `frr/`): `core` (switch SDK + most features), `sysmanage`, `httpd`, `cli_server`, `ssh`, `snmpd`, `mcast` (IGMP/MLD), `mstp`, `dhcpd` (ISC), FRR (`zebra`, `staticd`, `ripd`, `vrrpd`, `mgmtd`), `nms_report`, `nqa`, cloud (`cloud_sdk`, `cloud-brd`, `cloud_relayClient`), `ubusd`.
- Base: Buildroot 2015.11.1, Linux 3.18.24, uClibc, Realtek SDK 3.2.0 label (`/etc/version`; SDK tree 3.6.9 per SDK-SOURCES.md).

### Counts

| Surface | Total in image | On this device |
|---|---|---|
| Web pages (menu leaves) | 200 | 174 with a backend |
| Web fields + columns | 1366 | see per-area table |
| CLI commands | 5308 (54 modes, 423 hidden) | 2312 IMI-registered |
| TDCP handlers | 536 + 697 names | all |
| SNMP MIB groups/tables | 268 | 142 TP-Link private |

- The web app and `cli_server` are shared across TP-Link product lines: PoE, Modbus, PROFINET, IEC 61850, serial server, PTP, sFlow, BGP/OSPF/IS-IS/MPLS/BFD/DCB nodes exist but have no backend here.
- CLI "IMI-registered" is an upper bound: `frrService` registers BGP/OSPF commands although only `ripd`, `staticd`, `vrrpd` ship.
- 1990 CLI commands reach no `imi_cli_` name within two call levels (local or table-driven); not counted either way.

## Summary

Effort: S = config/package or register writes; M = new driver/daemon code (100-300 lines or a feed package + glue); L = new subsystem. "Ours" = OpenWrt (rtl83xx DSA) on our board today; the 7.3 port carries the same driver set (#73).

| Area | Vendor | Ours | Gap | Effort |
|---|---|---|---|---|
| [Ports](#ports-speed-fc-eee-fec-jumbo) | full | most | rate groups, FEC | S |
| [Optics / DDM](#optics--ddm) | full | read-only | alarms, auto-disable | S |
| [Statistics / RMON](#statistics--rmon) | full | counters | RMON groups | M |
| [Mirroring](#mirroring) | 4 sessions | tc mirred | UI | S |
| [Loop detection](#loop-detection) | yes | none | all | M |
| [Isolation / port security](#port-isolation--port-security) | yes | isolation | MAC limits | S |
| [LAG / LACP](#lag--lacp) | yes | yes | UI | S |
| [MAC table](#mac-table) | full | basic | flap detect, filter | S |
| [VLAN](#vlan) | 802.1Q+7 types | 802.1Q | MAC/proto/QinQ/GVRP | M |
| [STP / MSTP / ERPS](#stp--mstp--erps) | full | kernel STP | MSTP, guards, ERPS | M |
| [Multicast snooping](#multicast-snooping) | IGMP/MLD full | bridge snoop | profiles, MVR | M |
| [QoS / storm / rate](#qos--storm--rate) | full | police only | storm, sched, DSCP | M |
| [ACL / time ranges](#acl--time-ranges) | full | tc flower | ranges, time, UI | M |
| [L2 security](#l2-security) | full | none | all | M-L |
| [802.1X / AAA](#8021x--aaa--radius--tacacs) | full | none | all | M |
| [DHCP server / relay](#dhcp-server--relay) | yes | dnsmasq | relay opt82 | S |
| [L3 routing](#l3-routing) | static/RIP/VRRP/PBR | static + offload | HW VRRP, PBR | M |
| [LLDP / LLDP-MED](#lldp--lldp-med) | full | none in image | package | S |
| [SNMP](#snmp) | v1/v2c/v3 + traps | none in image | package + MIBs | M |
| [Syslog / monitoring](#syslog--monitoring--diagnostics) | full | logd | remote, alarms | S |
| [Management access](#management-access) | RBAC, HTTP/S, SSH | root, LuCI, SSH | users, policy | S |
| [Config / firmware](#config--firmware) | dual image | sysupgrade | dual image | M |
| [Cloud / Omada](#cloud-management-and-omada) | China cloud | none | Omada agent | L |
| [Stacking](#stacking) | 8 units | none | n/a | - |
| [Absent on 5008F](#present-in-the-ui-absent-on-this-device) | - | - | none | - |

### Ranked gaps

Ranked by value to this board (router/switch at home, loop incident #43, CPU protection), then effort.

1. **SNMP agent with standard MIBs** (IF-MIB, BRIDGE/Q-BRIDGE, LLDP-MIB, ENTITY-SENSOR for DDM/temp): owner ask, monitoring. M.
2. **Storm control + per-protocol storm meters**: would have contained #43; registers known (DATASHEET-AUDIT rows 32-33). S-M.
3. **Loop detection** (vendor `lbd`, RLDP trap; SDK-FEATURE-MAP #15): second line behind STP. M.
4. **LLDP / LLDP-MED** (`lldpd` package): topology for the controller and SNMP. S.
5. **MSTP + BPDU guard / root guard / TC protection** (`mstpd` or ustpd): edge-port safety. M.
6. **Attack prevention / DoS** (`ATK_PRVNT_*`, row 31): wire-speed, no CPU cost. S.
7. **Omada adoption agent** (#21): owner ask; no vendor code to reuse (China build has no Omada). L.
8. **Config backup/restore + dual-image firmware**: vendor keeps startup/backup images. M.
9. **QoS: scheduler, 802.1p/DSCP maps, egress shaping** (rows 49-51). M.
10. **L2 learn limits / port security** (row 20). S.
11. **Syslog remote + alarm/trap log + DDM/temperature alarms**. S.
12. **IGMP/MLD snooping profiles, querier, multicast VLAN**. M.
13. **802.1X + RADIUS/TACACS+ for management login** (hostapd wired, pam/tacacs). M.
14. **DHCP snooping / ARP inspection / IP source guard** (PIE + trap rules). L.
15. **Hardware VRRP router MAC + PBR in PIE** (SDK-FEATURE-MAP #9, row 38). M.

## Per area

Format per block: vendor settings (UI page → fields; CLI; backend), ASIC, ours, gap. Field lists are the UI labels; API names are `module.table`.

### Ports (speed, FC, EEE, FEC, jumbo)

- Vendor UI: Port Configuration (status, speed, duplex, autoneg, flow control, description, jumbo), Rate Compatibility Mode, Fault Monitoring → Port Interrupt Alarm; Management Port Configuration (out-of-band port, absent on this board).
- Rate Compatibility Mode: per **rate group** `10G_1G` (default, `switch.xml default_sfp_pattern`) or `10G_2.5G`; applies at next boot (`port.port_sfpp_pattern`, `swPortSetSfpPPatternNextBoot`). Groups = cage pairs 1-2, 3-4, 5-6, 7-8 (`boardInfo.xml sfpp_pattern_group`). A pair cannot mix 1G and 2.5G.
- CLI (core): `speed`, `duplex`, `flow-control`, `jumbo`, `energy-efficient-ethernet`, `port-auto-sleep`, `fec`, `pattern next-boot`, `shutdown`, `description`, `show interface`, `show cable-diagnostics`.
- ASIC: DATASHEET-AUDIT rows 1, 23, 56, 62, 63.
- Ours: ethtool speed/autoneg on phylink (1000BASE-X / 2500BASE-X / 10GBASE-R per lane), MTU up to 12 KB, pause via phylink, EEE op present. No FEC control, no pair-rule check.
- Gap: enforce the pair rule when a 1G and a 2.5G module share a pair (driver warning); FEC knob. S.

### Optics / DDM

- Vendor UI: DDM Status (temp, voltage, bias, TX/RX power), DDM Configuration (enable, Port Auto Disable on alarm), DDM Threshold (alarm/warning high/low per value), Optical Module Information (vendor, PN, type, wavelength, distance, date). API `sfp.ddm_status|ddm_config|ddm_threshold|sfp_message`.
- CLI: `ddm` (config-if, 16), `show ddm` (49), `show transceiver`; SNMP `tplinkDdmInfoEntry`; traps `ddm biascurExceed|rxPowExceed|tempExceed|txPowExceed|volExceed`.
- Vendor module database `data/sfpInfo.xml` (352 lines): TP-Link part numbers → type/rate.
- ASIC: SFP I2C masters (row 11).
- Ours: `ethtool -m` (EEPROM + DDM), U-Boot `rtk sfp`/`st1008_sfp_ddm.py`; hwmon via the SFP driver.
- Gap: threshold alarms → syslog/trap; optional port auto-disable. S.

### Statistics / RMON

- Vendor UI: Traffic Statistics (`mib_counter.mib_counter`, rate view), RMON Statistics / History (interval, buckets, owner) / Event (log/trap, owner) / Alarm (variable, rising/falling threshold + event).
- CLI: `rmon` (18), `show rmon`, `clear counters`; SNMP RMON (`snmp-1.0/rmon/*`), IF-MIB.
- ASIC: 4 MIB counter sets, RFC 1213/2863/2819 (row 58).
- Ours: `ethtool -S`, `ip -s link`, DSA rmon stats.
- Gap: RMON history/alarm/event (via SNMP agent). M.

### Mirroring

- Vendor UI: Port Monitoring (session, destination port, source ports, ingress/egress); API `port.mirror`, `port.mirror_unusable_port`. CLI `monitor session` (32 nodes incl. RSPAN/ERSPAN variants; only local registered).
- ASIC: 4 sets, ingress/egress (rows 28-29).
- Ours: tc `mirred` offload (`mirror.c`).
- Gap: UI/uci only. S.

### Loop detection

- Vendor UI: Loopback Detection: global enable, interval, auto-recovery time; per port: enable, processing mode (alert / port-based block / VLAN-based block), recovery mode, status. API `port.lbd_global_cfg`, `port.lbd_port_cfg`. CLI `loopback-detection` (+`packet-vlan`), SNMP `tplinkLoopbackDetectionMIBObjects`, trap `loopback-detection`.
- ASIC: RLDP/RLPP trap (SDK-FEATURE-MAP #15).
- Ours: bridge STP only (#43 history).
- Gap: loop-detect frame sender + trap handler + port block. M.

### Port isolation / port security

- Vendor UI: Port Isolation (per-port forward list, mode), Port Security (max learned MACs per port, `port.port_safe`). CLI `port isolation`, `mac address-table max-mac-count`.
- ASIC: per-port + VLAN-based isolation (row 25); learn limits system/port/VLAN (row 20).
- Ours: `BR_ISOLATED` per port. No learn limit.
- Gap: learn-limit registers + bridge `max_learned` hook. S.

### LAG / LACP

- Vendor UI: Aggregation List (group, member ports, static/LACP), LACP Configuration (system priority, port priority, mode, management key). API `lag.lag_entry|lacp_entry|lag_global|lag_ability`. CLI `channel-group`, `lacp`, `port-channel load-balance`; SNMP `tplinkLagMIBGlobalConfig`, `tplinkLagLacpManage`.
- ASIC: 64 groups x 8, 4 hash algorithms (row 27).
- Ours: DSA LAG offload (`lag.c`) + bonding/teamd.
- Gap: hash-algorithm selection exposure; UI. S.

### MAC table

- Vendor UI: Address Table Display, Static, Dynamic (aging enable, aging time), Filter (blackhole), MAC Address Flapping Detection (enable, alarm threshold, excluded VLANs). API `fdb_manage.*`.
- CLI: `mac address-table` (28), traps `mac new|full|learn-mode-change|max-learned`.
- ASIC: 16K L2, aging, notification (rows 17-19).
- Ours: bridge fdb, static entries, aging.
- Gap: filter (drop) entries, flap detection (SA move counter or software). S.

### VLAN

- Vendor UI: 802.1Q VLAN (VLAN list, names, per-port tagged/untagged/PVID, port type), VLAN MAC Security (per-VLAN MAC limit + action), MAC VLAN, Protocol VLAN (templates), VLAN VPN (QinQ: global, uplink/downlink ports, mapping list), GVRP, Private VLAN (primary/secondary, port mode), VLAN-MSTP Instance mapping, Voice VLAN (VLAN, priority, OUI table, port mode).
- CLI: `vlan` (222), `switchport` (38), `mac-vlan`, `protocol-vlan`, `ip-subnet-vlan`, `dot1q-tunnel`, `gvrp`, `voice`; SNMP Q-BRIDGE subset (`dot1qBase`, `dot1qFdbEntry`, `dot1qTpFdbEntry`) + `tpVlan*`, `macVlanEntry`, `protocolVlanEntry`, `privateVlanEntry`, `tplinkQinqVlanMIBObjects`.
- ASIC: 4K VLAN, ingress/egress filter, QinQ, protocol/MAC/subnet VLAN, translation (rows 12-16). PVLAN registers absent (SDK-FEATURE-MAP #8); vendor builds PVLAN from isolation.
- Ours: 802.1Q via DSA bridge VLANs only.
- Gap: MAC/protocol VLAN and QinQ need PIE/VLAN-profile code; GVRP needs a daemon; voice VLAN = LLDP-MED + OUI ACL. M each.

### STP / MSTP / ERPS

- Vendor UI: Basic (enable, mode STP/RSTP/MSTP, CIST priority, hello, forward delay, max age, max hops, BPDU rate limit), Information, Port (priority, internal/external path cost, edge, P2P, protocol migration), MSTP Region (name, revision), Instance (VLANs, priority), Instance Port, Port Protection (BPDU guard, BPDU filter, root guard, loop guard), TC Protection (threshold, cycle). Daemon `mstp`; API `spanning_tree.*`.
- ERPS (G.8032): ring ID, control VLAN, ring type, protected instance, WTR/guard/hold-off timers, revertive, notification ring. `core` handlers `erps.*`.
- CLI: `spanning-tree` (37) + `show spanning-tree` (167), `erps` (32); SNMP BRIDGE-MIB STP + `tpStp*`, `tpMstp*`; trap `spanning-tree topologychange`.
- ASIC: 64 MST instances (row 26).
- Ours: kernel STP (bridge), MST state offload in driver; flash OpenWrt has STP saved (#43).
- Gap: `mstpd` (RSTP/MSTP), guards, TC protection; ERPS (no OpenWrt daemon). M / L.

### Multicast snooping

- Vendor UI per IGMP and MLD: Basic (enable, unknown-multicast drop/forward, report suppression, fast-leave), Port (fast leave, max groups, overflow action, router port), VLAN (member/router port timers, last-member query count/interval), Multicast VLAN (MVR), Query (querier, interval, max response, source IP), Profile (address ranges permit/deny), Profile Binding, Packet Statistics; address tables (IPv4/IPv6 dynamic + static). Daemon `mcast` (58 TDCP handlers).
- CLI: `ip igmp snooping` / `ipv6 mld snooping` (218 registered).
- ASIC: 1K MC table, IGMPv1-3/MLDv1-2 trap (rows 21, 42).
- Ours: bridge multicast snooping + mdb offload; querier available in bridge.
- Gap: profiles (filter), per-port max groups, MVR. M.

### QoS / storm / rate

- Vendor UI: Port priority + trust mode, Scheduling Mode (SP, WRR, WFQ, SP+WRR, SP+WFQ; per-queue weight and bandwidth limit; CLI `qos queue mode|weight|bandwidth-limit|cos-map|dscp-map`), 802.1p → queue map, DSCP → priority map, Bandwidth Suppression (ingress/egress per port), Storm Suppression (broadcast/multicast/unknown-unicast, kbps/ratio/pps). API `qos.*`. CLI `qos` (21), `storm-control` (16), `bandwidth`; SNMP `tplinkQosScheduler`, `tplinkQosDSCP`, `tpStormControlEntry`, `tpRateLimitEntry`.
- ASIC: rows 32-33 (storm), 47-54 (meters, queues, scheduling, shaping, SWRED).
- Ours: tc police (ingress/egress port rate) only; storm control N on 930x.
- Gap: storm control (registers known), scheduler and maps via DSA/tc mqprio or sysfs. S-M.

### ACL / time ranges

- Vendor UI: Time Period (segments, holidays), MAC ACL, Standard IP ACL, Extended IP ACL, IPv6 ACL (rules: match fields, fragment, user priority, ranges, rule order/step), Policy (actions: redirect, mirror, rate, remark), binding to port/VLAN. API `acl.*` (53 TDCP registrations). CLI `access-list` (36), `time-range`; SNMP `tpMacRuleEntry`, `tpStdipRuleEntry`, `tpExtipRuleEntry`, `tpIPv6RuleEntry`, `tpPolicy*`, `tpAclBind*`.
- ASIC: PIE 2K entries, ranges, actions, counters (rows 43-45).
- Ours: tc flower offload (no ranges, no TCP flags; #66).
- Gap: range checkers, time-based rules (cron + tc), UI. M.

### L2 security

- Vendor UI: DHCP Snooping (global, VLAN, port trust, Option 82 circuit/remote ID), ARP Protection (anti-spoof per VLAN/port, anti-attack rate limit, statistics), IP Source Guard (per-port IP/MAC verification), Four-Tuple Binding (IP-MAC-VLAN-port; manual, scan, list), DoS Protection (attack types list), Flood-CPU Protection (per-protocol rate). API `dhcp_snooping.*`, `arp_defend.*`, `ip_source_guard.*`, `qtable.*`, `dos_defense.*`, `flood_cpu_defend.*`.
- CLI: `ip dhcp snooping`, `ip arp inspection`, `ip source binding|verify`, `ip dos-prevent`, `ip cpu-defend`, `ipv6 savi`.
- ASIC: attack prevention (row 31), PIE trap/drop for snooping-derived bindings (rows 43-44); no IP-MAC bind table (SDK-FEATURE-MAP #8).
- Ours: none.
- Gap: DoS = register writes (S); snooping/IPSG = trap DHCP + build PIE entries from leases (L).

### 802.1X / AAA / RADIUS / TACACS+

- Vendor UI: 802.1X Global (enable, auth mode PAP/EAP, quiet period, supplicant timeout, retries) and Port (control mode, control type port/MAC, guest VLAN); AAA Global, Method Lists (login/enable/dot1x auth + accounting, 4 methods), Server Groups, RADIUS servers (IP, auth/acct port, key, retries, timeout), TACACS+ servers. API `aaa.*` (26). CLI `dot1x`, `aaa`, `radius-server`, `tacacs-server`.
- ASIC: EAPOL trap (row 24), port authorisation state via VLAN/ACL.
- Ours: none.
- Gap: `hostapd` wired 802.1X authenticator (feeds) + port-state hook; RADIUS/TACACS for SSH/LuCI login (PAM / tacacs). M.

### DHCP server / relay

- Vendor UI: DHCP Server (enable, pools: subnet, range, lease, gateway, DNS, domain, next-server, boot file, NetBIOS), Static Binding (import), Allocated list, Relay (global, Option 82 support/strategy/circuit ID/remote ID, relay servers per interface). Daemon ISC `dhcpd`; API `dhcpd.*`.
- Ours: `dnsmasq`/`odhcpd` (default packages); relay via `dnsmasq --dhcp-relay` or `odhcpd`.
- Gap: Option 82 on relay. S.

### L3 routing

- Vendor UI: Interface Configuration (VLAN interfaces, routed ports, loopback; IPv4/IPv6, DHCP/static, L3 forwarding enable), Static Routing v4/v6, Routing Table, Route Map, Policy Routing, RIP (v1/v2, networks, interfaces: auth, passive, split horizon, poison reverse), VRF (UI only; no HW VRF), Proxy ARP, Local Proxy ARP, ARP list, Static ARP, ARP-IP conflict detection (no backend), IPv6 neighbours.
- Daemons: FRR `zebra` (with `zebra_fpm`/`zebra_stk` modules) + `staticd`, `ripd`, `vrrpd`; `librib`/`libroute`. `/etc/daemons` enables bgpd/ospfd/isisd/pimd/ldpd but those binaries are not in the image.
- ASIC: L3 unicast, uRPF, PBR, VRRP router MAC (rows 36-40; SDK-FEATURE-MAP #8-9).
- Ours: kernel routing + DSA L3 offload (ROUTING-OFFLOAD.md, #59), static routes via netifd; FRR/bird/keepalived in feeds.
- Gap: VRRP MAC into the router-MAC table; PBR via PIE; uRPF. M.

### LLDP / LLDP-MED

- Vendor UI: Global (enable, TX interval, TTL multiplier, TX delay, init delay, fast count, trap interval), Port (admin TX/RX, TLV select, trap), Neighbour info, Statistics; LLDP-MED (fast start count, device class, port: TLVs, location: civic address/ELIN, network policy). API `lldp.*` (19 in core). SNMP `lldp*` (TP-Link tables, not LLDP-MIB OIDs).
- Ours: none in the image; `lldpd` (feeds) does LLDP + LLDP-MED + SNMP subagent.
- Gap: package + uci defaults. S.

### SNMP

- Agent: TP-Link `snmpd` (`snmp-1.0` sources: own engine + RMON) linked with net-snmp 5.9.1 libraries (`libnetsnmp*.so.40`, initramfs). `net-snmp-create-v3-user` present.
- Versions v1, v2c, v3 (USM auth MD5/SHA, priv DES per `cli_server` enum strings; VACM views, groups, communities with view + right). Engine ID local/remote. UDP 161; notify hosts with port, retries, timeout, type trap/inform, v4/v6 hosts.
- UI: Global, View, Group, User, Community, Notification, RMON (4 groups). API `snmp.*` (32).
- Standard MIBs served (handler names): MIB-II `system`, `interfaces`/`ifEntry`, `ifXEntry`, `ip`/`ipAddrEntry`/`ipNetToMediaEntry`, `icmp`, `tcp`/`tcpConnEntry`, `udp`/`udpEntry`; BRIDGE-MIB `dot1dBase|Stp|Tp|Static`; P-BRIDGE `dot1dExtBase`, `dot1dTrafficClassEntry`, `dot1dPortGarpEntry`; Q-BRIDGE `dot1qBase`, `dot1qFdbEntry`, `dot1qTpFdbEntry`; RMON; SNMP-TARGET/NOTIFICATION (`1.3.6.1.6.3.15/16/18`: USM, VACM, community); DISMAN-PING/TRACEROUTE (`pingCtlEntry`, `traceRouteCtlEntry`); RADIUS-AUTH/ACC-CLIENT.
- Private (142 tables under TP-Link's enterprise tree): `tplink{SysInfo,SysTime,SysTool,Ssh,Ssl,Http,Ddm,DhcpServer,LagLacp,LoopbackDetection,QinqVlan,QosDSCP,QosScheduler,PortRate,SDM}*`, `tp{Port,Vlan,Stp,Mstp,Igmp,Mld,Acl,Policy,Arp,Dhcp,Syslog,SysMonitor,Stack,Rip,Vrrp,Sflow,Poe,...}*`. No MIB text files in the image.
- Traps (CLI `snmp-server traps`): snmp coldstart/warmstart/linkup/linkdown/auth-failure, link-status per port, spanning-tree topologychange, loopback-detection, storm-control, bandwidth-control, mac new/full/max-learned/learn-mode-change, ddm (5), cpu, memory, temperature, fan, power, flash, ipaddr-change, lldp, ntp, syslog, vlan create/delete, ospf/bgp/isis (no backend).
- Ours: none in the image. OpenWrt `snmpd` (net-snmp) gives MIB-II, IF-MIB, HOST-RESOURCES; BRIDGE/Q-BRIDGE not served; `lldpd` adds LLDP-MIB.
- Gap: net-snmp + bridge MIB module (or `snmpd` pass_persist reading bridge/DSA) + DDM/thermal via ENTITY-SENSOR; trap generation from netifd/hotplug. TP-Link private OIDs not needed (Omada does not poll them). M.

### Syslog / monitoring / diagnostics

- Vendor UI: System Log (view, filter), Alarm (trap) Log, Local Log (buffer/flash, severity, sync frequency), Remote Log (servers, severity), CPU/Memory monitoring, Cable Detection (VCT; n/a for SFP), Ping, Tracert, Debug Mode (diagnosis, debug log levels and output). CLI `logging`, `show cpu-utilization`, `show temperature`, `nqa` (probes).
- Ours: `logd`/`logread`, remote syslog via uci `system.log_ip`, ping/traceroute (busybox).
- Gap: severity filtering per target, alarm log fed by DDM/thermal/storm events. S.

### Management access

- Vendor UI: User Management (users, levels admin/operator/power_user/user, password change), Password Security (expiry, complexity, character classes), Security Configuration, HTTP (enable, port, timeout, max sessions), HTTPS (cert/key upload, session timeout, per-level session limits), SSH (version, key upload), Telnet (enable), System Time (manual, NTP preferred/alternate, interval, time zone, DST), Management Port (out-of-band; none on this board).
- CLI `user`, `line`, `ip http`, `ip ssh`, `telnet`, `system-time`, `ntp-service`, `hostname`, `location`, `contact-info`.
- Ours: root + LuCI (release images), dropbear SSH, uhttpd, sysntpd.
- Gap: multi-user RBAC (LuCI ACLs exist), password policy. S.

### Config / firmware

- Vendor UI: Startup Configuration (image select: Startup Image / Backup Image), Import/Export Configuration (text config), Software Upgrade (HTTP upload, reboot), Reboot, Factory Reset; cloud firmware check (`cloud_config.new_firmware`, `upgrade_info`). CLI `copy` (16: tftp/ftp/sftp ↔ running/startup/backup, firmware), `boot application`, `firmware upgrade`, `show image-info`.
- Dual image: two application images, one active, boot selector (`system.image_config`). Upgrade instructions MHT: Web → System Tools → Software Upgrade.
- Ours: sysupgrade (+ `-b` config backup), LuCI flash page; single OpenWrt image on flash; our U-Boot chain (DEFAULT-BOOT.md).
- Gap: A/B images selected by our U-Boot (fits the existing fallback flag). M.

### Cloud management and Omada

- This China build has **no Omada code** (no `omada`, no ports 29810-29814, no `adopt` strings). It speaks TP-Link's China cloud ("商云", `n-deventry-smb.tplinkcloud.com.cn`).
- Shape: device-initiated TLS (wolfSSL/CyaSSL) to an entry server (`sefPort` 60443), redirected to a device server (`defaultPort` 50443); heartbeat 105 s; JSON TDCP methods passed through (`passthroughHandleMethod`) to the same handlers the web UI uses; optional private cloud server (`cloud-server` CLI, `ipc_cloudServerPrivatePortSet`). Relay client for remote web/CLI (`cloud_relayClient`, `remote_relay`); `nms_report` pushes events and stats. Config `data/cloud_brd_conf`; CA `tp-link-root-CA.pem`, `tums_ca.cer`.
- Omada (international SG/SX series) is a different protocol: see #21 (adoption = device self-describes; feasible as an open agent).
- Ours: none.
- Gap: Omada device agent per #21. L. TDCP JSON names here can seed the capability model only loosely; Omada uses its own message classes.

### Stacking

- Vendor UI/backend: Stack Member (priority), Stack Port (port group), virtual chassis; `switch.xml` stack code 109, unit IDs 1-8. `stack_manage.*` in core.
- ASIC: stacking over ports 24-27 (row 69).
- Ours/gap: not useful for one unit. -

### Present in the UI, absent on this device

- No backend in this image: sFlow (UI 3 pages; `core` has SDK sFlow strings only), PTP (no 1588 PHY; SDK-FEATURE-MAP #8), PoE, Modbus / Modbus gateway, PROFINET, IEC 61850, serial server, terminal management, ARP-IP conflict detection, relay warning (alarm contacts).
- CLI-only families with no backend or daemon here: BGP, OSPF/OSPFv3, IS-IS, PIM, MPLS/LDP, BFD, EVPN/VXLAN, DCB/PFC, NETCONF, gRPC telemetry.
- sFlow is still worth having on our side: ASIC sampler (row 30) + `hsflowd`. M.

## Board secrets / how the vendor does it

Static RE of TL-ST5008F v2 1.2.0 (SDK 3.6.9.55156) against stock TL-ST1008F v2 (SDK 3.6.6.55087) and the GPL SDKs (#79). No vendor code executed.

- Sources: `private/china/st5008f-v2-extracted/rootfs/usrImage/data/{boardInfo,switch,sfpInfo}.xml`; `core` decompiles `private/ghidra/vendor-nic/st5008f-{board,core-str,core-ref,core-name,core-addr}.c`; `st5008f-rtcore.c`; stock `private/ghidra/stock-rtcore-full.c`.
- Regenerate: `scripts/vendor_nic_decompile.py st5008f-board` (name regex) and `addr|str|ref|name` modes (persistent project); values `python3 -I scripts/st5008f_board_values.py` → `tmp/st5008f/board_values.json`.
- `core` call targets: Ghidra `FUN_x` = dynsym `x + 8` throughout (e.g. `FUN_0109fcd8` = `rtk_sds_eyeParam_set` 0x0109fce0).
- Board files: TP-Link drives everything board-specific from `boardInfo.xml` through a generic XML engine (`adBoard*`). SDK-level tuning hooks are empty: `conf_rtl9300_cust_board_list` is `.bss` (zero) in both `core` and stock `rtk.ko`, so `dal_longan_sds_rxCaliConf_cust` / `dal_longan_sds_txParam_cust` (`core` 0x0107f048 / 0x0107f1b8) do nothing.

### Board identity: ST5008F v2 is a different PCB from ST1008F v2 (#79)

- Same: profile `RTL9303_8XGE`; front port → SDK port 0, 8, 16, 20, 24-27 (CPU 28); SerDes 2-9, 10GBASE-R, normal polarity; SFP I2C `sck=8`, `sda=0..7`, `intf=0`, EEPROM 0x50 (boardInfo `i2cList`, `portInfo_list`; hw profile in both `rtcore.ko`).
- Different GPIO use (boardInfo `gpio_list`, `sysLed_good`, `usb_micro`):

| GPIO | ST5008F v2 | ST1008F v2 |
|---|---|---|
| 0-7 | SFP ABS, high = absent | MOD-DEF0, same polarity |
| 17 | system LED (out, init low; green = high) | mode switch M1 |
| 18 | micro-USB console insert detect (in) | mode switch M2 |
| 19 | micro-USB console enable (out, high) | mode switch M3 |
| 21 | not used | external-watchdog pin (DTS) |
| 22 | out, high | i2c-gpio SCL (TCA9534A) |
| 23 | not used | i2c-gpio SDA |

- ST5008F has no TCA9534A: TX-disable is on the LED shift chain (below). No mode switch, no reset button, no watchdog, no fan, no temperature sensor, no SerDes polarity / LEQ list (all those boardInfo sections absent).
- Consequence: ST5008F per-board values (SerDes TX eye, LED map) are TP-Link's tuning for *its* layout; use them as a starting point for ours, not as ours.

### SerDes TX eye (#25)

- SDK default tables (`dal_longan_sds_txParam_config_init`, `sds_cfg_rtl9303_80G`, applied per SerDes when 10G media is set): identical bytes in SDK 3.7.0 source, stock ST1008F `rtk.ko` and ST5008F `core`:

| SerDes (cage) | 10G fibre: imp / pre / main / post (pre_en, post_en) | DAC (all lengths) |
|---|---|---|
| 2 (1) | 8 / 2 / 9 / 2 (1,1) | 8 / 0 / 16 / 0 (0,0) |
| 3 (2) | 8 / 1 / 9 / 1 (1,1) | same |
| 4 (3), 5 (4) | 8 / 0 / 9 / 0 (0,0) | same |
| 6 (5) | 8 / 1 / 9 / 0 (1,0) | same |
| 7 (6) | 8 / 2 / 9 / 0 (1,0) | same |
| 8 (7) | 8 / 1 / 9 / 1 (1,1) | same |
| 9 (8) | 8 / 2 / 9 / 2 (1,1) | same |

- ST5008F override (boardInfo `sfp_param_list`, order impedance, pre, main, post, post2, pre_en, post_en, post2_en, main_en; "SDK 3.6.9 ignores post2/main_en"):

| Cage | fibre (pre / main / post, pre_en, post_en) | copper/DAC |
|---|---|---|
| 1, 5 | 0 / 25 / 0, 0, 1 | 20 / 18 / 24, 1, 1 (all cages) |
| 2, 3, 6, 7 | 0 / 29 / 8, 0, 1 | |
| 4, 8 | 0 / 27 / 0, 0, 1 | |

- Applied by `FUN_00bf1b60` (from SerDes init `FUN_00bf27f8`, registered by `adTscDyCfgMapperInit` 0x00bf2db8): `rtk_sds_eyeParam_get` → keep the **current impedance** (XML `impedance=5` is never written) → `rtk_sds_eyeParam_set` with XML pre/main/post/enables.
- Re-applied on module change by `adTscCfgEyeCallBack` (0x00b4c0c8): copper set when the module type is 1, 0x13 (1X_COPPER_ACTIVE), 0x14 (1X_COPPER_PASSIVE), 0x28, 0x29, 0x2d, 0x3c; fibre set otherwise.
- vs ours: after our `rtk network on` the 10GR cages read pre 0 / main 12 / post 0 ([SDS-TOOLS.md](SDS-TOOLS.md)): neither the SDK table (main 9) nor ST5008F (main 25-29). Field scale is the raw register field in both (page 0x2f, main = 7[8:4]).

### SerDes RX calibration (#25)

- `rtl9300_rxCaliConf_serdes_myParam` in **both** vendor binaries: `dacLongCableOffset 0, tap0_init_val 0x1f, vth_min 1, eqHoldEnable 1, dfeTap1_4Enable 1` (phy variant: eqHold 0). Same as SDK 3.8.0; SDK 3.7.0 has offset 3 / vth_min 0 (the values quoted in [UBOOT-REFERENCE.md](UBOOT-REFERENCE.md) §2).
- ST5008F boardInfo `phy_rxcali_en = 0` → `gPhyRxCaliEnable = 0` (`FUN_00b591f0`): the extra `dal_longan_sds_rxCali` pass in `FUN_00bf27f8` (via `FUN_0106f608`) is skipped.
- `FUN_00bf27f8` then runs `subDrvTscInit` per SerDes with `pal_usleep(100000)` after each.

### SFP+ speed "pattern" per SerDes pair (#25, #8)

- `boardInfo` `sfpp_pattern_group`: cages (1,2), (3,4), (5,6), (7,8) = SerDes (2,3), (4,5), (6,7), (8,9).
- `switch.xml` `default_sfp_pattern = 10G_1G`; other value `10G_2.5G` (`imi_slp_sfpp_patternSet` 0x00e00b68: "10G_1G" → 1, else 2).
- `swPortSetSfpPPatternNextBoot` (0x00db8cec) writes the pattern to **both** ports of the group (refused if either port's LAG speed conflicts); CLI text "The pattern will be actived after next boot". No live change.
- Same constraint as ST1008F's hardware mode switch (1G vs 2.5G modules; stock resets the board on change, [hardware.md](hardware.md) "Mode switch"), but per SerDes pair instead of global/half. Reason for pairing not stated in code; the pair shares the even SerDes' debug/CMU block ([SDS-TOOLS.md](SDS-TOOLS.md)). Our Linux mode-switch driver changes speed live, per cage.

### SFP presence, EEPROM, TX-disable (#29)

- ABS: SoC GPIO 0-7, `level=high` = absent (= MOD-DEF0 active-low, as ours).
- EEPROM: I2C 0x50, read on insert 128 B, or 256 B with a page-select write (byte 0x7f = 0, then 5 ms) for some types (`FUN_00b3c34c` 0x00b3c34c). DDM via 0x51 (`adSfpEpmGet/Set`).
- Classification: `sfpInfo.xml`, 46 SFP rules on A0 bytes 3/4/5/6/8/12/36/120-125; TP-Link's own copper modules matched by A0 120-124 = `SFP-T` (10G/2.5G, bit 125.6 selects) or `SFPGE` (1G). Type → speed/autoneg in `adSfpSetType` (0x00b4039c). No vendor lock (classification only).
- TX-disable = LED engine (boardInfo `sfp_txDis_list`: `type=led intf=1 class=2 bit=<SDK port> level=low`):
  - `FUN_00a57e54` → `adChipSdkLedStreamBitSet` → `FUN_00b5c9e8`: `rtk_led_portLedEntitySwCtrlMode_set(unit, port, entity 2, media 1, mode)`, `..SwCtrlEnable_set(.., 1)`, `rtk_led_swCtrl_start`.
  - Mode 0 (off) when the requested state ≠ `level`, 7 (on) when equal: assert TX-disable → LED2 off; release → LED2 on.
  - LED index 2 of each port (`LED_PORT_SW_EN_CTRL` bit 2, boardInfo `0xBB00CC4C` = 4) is the TX_DISABLE line, i.e. the third 74HC164 output per port.
- Laser policy (#19): `adPortStateSetTxDis` (0x00b123e8): admin-down port → TX-disable on. `adBoardMiscReBoot` (0x00aa7740): all lasers off (`adBoardPortSfpTxDisEnableAll`) before reboot. Neither exists in OpenWrt/ours (#19 cage loop).
- Pinmux: boardInfo writes only `GPIO_SEL_CTRL` 0xBB000200 [11:10] = 0 (GPIO18/19 as GPIO, not USB-LED / LED-sync), via `adBoardInfoGpioMutiplexModeInit` before and after SDK init. Nothing touches `GPIO_SEL_CTRL[9:0]` (slave-SPI CS/SDO) or `SPI_CTRL1` 0x3A0 (GPIO3-5 SPI mux).
- ST5008F `rtcore.ko` `rtcore_customer_init` (0x00011540): for `RTL9303_8XGE` sets `GPIO_SEL_CTRL` bit 11 (`GPIO19_LEDSYNC_SEL`) = 1 (`FUN_000114d0`); user space clears it again. Stock ST1008F `_rtcore_ledSync_init` (0x000115d0) is a stub: never set.

### LEDs (#9)

- hw profile `RTL9303_8XGE` LED set 0 (`.data` in each `rtcore.ko`, offsets from `_hwp_led_parse`):

| | LED0 | LED1 | LED2 |
|---|---|---|---|
| stock ST1008F | `0x0A01` 10G link/act | `0x0A08` 2.5G link/act | `0x0BA0` 1G/100M/10M link/act |
| ST5008F | `0x0A28` 1G+2.5G link/act | `0x0A01` 10G link/act | `0x0A01` (then SW = TX-disable) |
| SDK 4.0.2 GPL | `0x0BA0` | `0x0A01` | end |

- Selector bits (from SDK 4.0.2 profile comments): 0 = 10G, 1 = 5G, 3 = 2.5G, 5 = 1G, 7 = 100M, 8 = 10M, 9 = link, 11 = activity.
- ST5008F register writes after SDK init (`FUN_00b589f0`, list parsed by `FUN_00b5bf5c`):
  - `0xCC00` mask `0x5C6FFF` = `0x000C4001`: LED_MOD 1 (serial), PWR_ON_BLINK 0, STP1/STP2_PWR_ON 0, SYS_LED_MODE 2, BLINK_TIME_SEL 3, LED_ACTIVE 0. Stock ST1008F reads `0x01452651`: LED_ACTIVE 1, BLINK_TIME_SEL 1, SYS_LED_MODE 1, STP1 5 / STP2 6.
  - `0xCC04` port 0 LED_NUM_SEL 2; `0xCC28` = `0x0A010A28`; `0xCC34` port 0 fibre set 0; `0xCC4C` port 0 SW_EN = 4 (LED2); `0xCC5C` port 0 SW_FIB_LED2_MODE 0.
  - `portLed_select`: green = LED1 (10G), yellow = LED0 (1G/2.5G).
- SDK (both firmwares, `rt_util_ledInitFlag_get`, GPL `drv_rtl9300.c:676`): U-Boot env `ledModeInitSkip=1` skips `rtl9300_led_config` in Linux (keeps the bootloader LED state).

### Thermal (#13)

- Realtek SDK 3.6.9 `dal_longan_switch_thermalTemp_get` (`core` 0x01150e48; not in the GPL SDKs, not in stock `rtk.ko`):
  - write `THERMAL_METER_CTRL_2.TM_ENABLE` = 1, `osal_time_mdelay(10)`, read `THERMAL_METER_RESULT_0.TEMP_OUT` [22:16];
  - result `TEMP_OUT * 129 - 1000`, printed `/ 100.0` as "meter temperature" (diag `switch get thermal`): **°C = 1.29 × TEMP_OUT − 10**.
  - OpenWrt (`coefficients = <1000 0>`) and our docs read TEMP_OUT as °C directly. The 73 raw reading in [hardware.md](hardware.md) "Thermal" = 84.2 °C by Realtek's formula. Needs an external-probe check.
  - `thermalTemp_get` does not write `CTRL_1.SAMPLE_DLY`; OpenWrt writes `0x0800`.
- TP-Link use: only the diag CLI calls it. ST5008F board temperature callback (`adChipSdkMapperInit` slot 2, `FUN_00b57a70`; slot inferred from the GPIO slots) returns not-supported; no temperature/fan XML → no monitoring, alarm, fan or throttling. `/sys/.../thermal_zone0/temp` is read only on chassis MPUs (`FUN_00a9f570`).

### Watchdog / GPIO21 (#18)

- TP-Link watchdog = boardInfo `<wtd>` (`adBoardInfoXmlWtdInit` 0x00a8cca0): `insmod <wtd_path> enGpio=<wtd_en> feedGpio=<wtd_feed>`, GPIOs saved to `/tplink/exe/data/wtdGpio`; chassis feed task toggles every 500 ms (`adBoardChassisWorkGoodFeedWtdTask`).
- ST5008F boardInfo has no `<wtd>`: no external watchdog. GPIO21 is not referenced.
- Chip watchdog (`drv_watchdog_*`, `rtk_switch_watchdog*`): no TP-Link caller; diag CLI only.

### Power (#30)

- No SFP power-level (A0 byte 64) or budget logic in `core`; boardInfo has no power section. Only QSFP LP-mode (`adBoardPortSfpLPModeEnable`, unused here).

### Reset button (#79)

- `/button/factory_reset` (`adBoardDevButtonXmlInit` 0x00a6b668): held ≥ 10 polls × 500 ms (5 s) → restore defaults + reboot (`FUN_00a9f690`). Not configured on ST5008F.

### Flow control, CPU port (#82, #60)

- `drvPortInitRealtek` (0x00ba7eac) → `subDrvPortFlowctrlInit` (0x00c03f90), per front port: `rtk_flowctrl_portPauseOnAllowedPageNum_set(port, 100)` (`FC_PORT_ACT_CTRL` 0xD804 + 4p, `ALLOW_PAGE_CNT`); then `MAC_L2_GLOBAL_CTRL0` 0xC700 `LIMIT_PAUSE_EN` [26:25] = 0.
- `rtk_switch_cpuMaxPktLen_set(0, RX, 12000)` and `(0, TX, 12000)` = `switch.xml` `jumbo_length`.
- `switch.xml`: `flowctrl_default` off; CPU queues 8, weight 127; `tpcl_cpucode_distribute` (ARP/ND/DHCP/OSPF/VRRPv6/ICMP 2000 pps, others 0) present but `include=false`.
- OpenWrt/ours: neither write; reset values unread.

### MAC address, flash, upgrade (#29)

- SDK system MAC (both firmwares): `ioal_param_sysMac_get` → `rt_util_sysMac_get` → U-Boot env `ethaddr` read from flash (`rt_util_flashEnv_get`, `rtcore.ko`).
- ST5008F flash: dual image `usrimg1@main` / `usrimg2@main` (`start_system.sh` mounts usrimg2 if present, else usrimg1), squashfs copied to RAM and loop-mounted; config on jffs2 `usrappfs` → `/tplink/usrapp` (`initramfs/etc/start_system.sh`).
