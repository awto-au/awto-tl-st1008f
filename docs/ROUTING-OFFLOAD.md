# HW L3 routing offload (RTL9303, OpenWrt snapshot)

OpenWrt SNAPSHOT (kernel 6.18), `rtl83xx-switch` DSA driver, `l3.c` offload.

## Offload model (from `l3.c` design comment)

- RTL930x HW-forwards **only routes reached through a gateway** whose MAC is learnt on a switch port. Route gets a nexthop entry → ASIC action `fwd`.
- **On-link / directly-connected destinations TRAP to CPU** — by design, not a bug. So plain inter-VLAN routing between two directly-attached subnets is **software** on the single MIPS core.
- Default routes have no ASIC entry (reach CPU via catch-all). Multicast not offloaded. All egress ifaces share one 1536 B MTU.
- Capacity: 512 prefix rows (shared v4/v6; v6 = 3 rows), up to 1536 host routes.
- RTL838x/839x limited; RTL931x unsupported (FIB/neigh events ignored).

## Hardware NAT / IP rewrite: none (#58)

- Not hidden or fused off either: [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (#68).
- Routing rewrites SMAC, DMAC, VID, TTL, IPv4 header checksum only (datasheet §7.14). No IP address or L4 port rewrite.
- `L3_NEXTHOP` = DMAC idx + egress intf idx; `L3_EGR_INTF` = VID, SMAC idx, MTU idx, TTL/ICMP-redirect controls (GPL SDK `rtk_longan_table_struct.h`). ACL/PIE edits: VLAN, 1p, DSCP/TOS, IP reserved flag (datasheet §7.13.1, SDK `include/rtk/acl.h`). No NAT symbol in the SDK.
- OpenWrt `tc.c` rejects `FLOW_ACTION_MANGLE`; no HW flowtable binding.
- NAT stays on the CPU path (`rtl838x_eth`, 1G CPU port, #60). Fast path = route without NAT (static route on the upstream router; IPv6).

## Offload gaps (#59)

- On-link destinations: neighbours are not installed as host routes, so directly-connected inter-VLAN routing traps (6K-entry host table unused for this).
- Default route: rejected by `otto_l3_fib_check_v4()` (`!info->dst`, which also rejects `0.0.0.0/1`). Workaround to test: 8 routes `1/8 2/7 4/6 8/5 16/4 32/3 64/2 128/1` via the gateway.

## Verification surfaces

- ASIC route table: `cat /sys/kernel/debug/realtek_otto_l3/routes` — ACTION `trap` vs `fwd`, `chk,dec` = HW checksum + TTL-decrement, HIT counter. Reset: `echo 1 > …/clear_route_hits`.
- HW-offload proof = CPU port `eth0` stays flat (software routing would punt the whole flow) **and** route HIT climbs.
- Port errors: `ethtool -S lanN` (ifOutDiscards, dot1dTpPortInDiscards, DropEvents) + `/sys/class/net/lanN/statistics/*`.

## Measured — gateway-routed hairpin (single 10G host NIC)

Tool: `scripts/routing_wirespeed.py` (setup/run/probe/teardown). Topology: one host 10G port as a VLAN trunk, two netns in far subnets behind per-VLAN gateways so both directions are gateway-routed; switch routes VLAN10↔VLAN20, egress = ingress port (hairpin). Full-duplex 10G → TX and RX are independent channels, so goodput ≈ line rate (not halved).

- Goodput **9.19 Gbit/s** TCP (8 streams); wire **9.69 Gbit/s TX + 9.69 RX** = 10G line rate each way.
- UDP @9 Gbps: **9.53 Gbit/s, 0.029 % loss, 0.005 ms jitter** (loss is host UDP socket buffer; switch discards 0).
- CPU carried **0.000 %** of the routed volume (≈0.07 MB control vs 34 GB routed over 30 s).
- Errors **clean**: 0 host NIC errors (all counters), 0 switch tx/rx/crc errors, 0 discards; 2 rx_dropped / 29.76 M pkts (~7e-8).
- ASIC: `172.16.1.0/24 fwd NH13 chk,dec`, `172.16.2.0/24 fwd NH14 chk,dec`.

Contrast — on-link inter-VLAN (no gateway): **trap → CPU**, ~70 Mbit/s, 216 % of volume through CPU. Matches the design model.

## Pending

- True all-port routed test (ingress ≠ egress port) needs a **second 10G endpoint** — host has one 10G SFP+ (single-port ConnectX), twin is SFP+-only. Tracked for when equipment is available.
