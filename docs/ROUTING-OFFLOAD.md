# HW L3 routing offload (RTL9303, OpenWrt snapshot)

OpenWrt SNAPSHOT (kernel 6.18), `rtl83xx-switch` DSA driver, `l3.c` offload.

## Offload model (from `l3.c` design comment)

- RTL930x HW-forwards **only routes reached through a gateway** whose MAC is learnt on a switch port. Route gets a nexthop entry → ASIC action `fwd`.
- **On-link / directly-connected destinations TRAP to CPU** (upstream design). Plain inter-VLAN routing between two directly-attached subnets is **software** on the MIPS core. `300-17` `l3_onlink` changes this (below).
- Default routes have no ASIC entry (reach CPU via catch-all); `300-17` `l3_default` changes this. Multicast not offloaded. All egress ifaces share one 1536 B MTU.
- Capacity: 512 prefix rows (shared v4/v6; v6 = 3 rows), up to 1536 host routes.
- RTL838x/839x limited; RTL931x unsupported (FIB/neigh events ignored).

## Hardware NAT / IP rewrite: none (#58)

- Not hidden or fused off either: [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (#68).
- Routing rewrites SMAC, DMAC, VID, TTL, IPv4 header checksum only (datasheet §7.14). No IP address or L4 port rewrite.
- `L3_NEXTHOP` = DMAC idx + egress intf idx; `L3_EGR_INTF` = VID, SMAC idx, MTU idx, TTL/ICMP-redirect controls (GPL SDK `rtk_longan_table_struct.h`). ACL/PIE edits: VLAN, 1p, DSCP/TOS, IP reserved flag (datasheet §7.13.1, SDK `include/rtk/acl.h`). No NAT symbol in the SDK.
- OpenWrt `tc.c` rejects `FLOW_ACTION_MANGLE`; no HW flowtable binding.
- NAT stays on the CPU path (`rtl838x_eth`, 1G CPU port, #60). Fast path = route without NAT (static route on the upstream router; IPv6).

## Offload gaps (#59) and `300-17`

Stock driver (OpenWrt `main` up to `e5ec5e199f`, 2026-10-11): both gaps are deliberate upstream design, nobody is working on them (upstream survey: #59 comment 2026-10-12).

- On-link destinations: neighbours are not host routes, so directly-connected inter-VLAN routing traps (host table unused for this).
- Default route: rejected by `otto_l3_fib_check_v4()` (`!info->dst`, also rejects `0.0.0.0/1`) and `otto_l3_fib_check_v6()` (`ipv6_addr_any`). Workarounds: v4 8 routes `1/8 2/7 4/6 8/5 16/4 32/3 64/2 128/1`, v6 `2000::/3` via the gateway.

`openwrt/patches/300-17` (mainline 7.3 port; same change against `main` drafted for upstream) closes both. **Off by default**: what the ASIC routes bypasses nftables (firewall, NAT, conntrack).

| Module parameter (`/sys/module/rtl_otto_dsa/parameters/`, 0644) | Effect |
|---|---|
| `l3_onlink` | Resolved neighbour, reached on-link through a switch port, gets a host-table entry forwarding to its MAC. IPv4 and IPv6 |
| `l3_default` | `0.0.0.0/0` / `::/0` via a gateway forwards from a row just above the catch-all |

- A runtime change is applied at the next poll (`DELAY_PROBE_TIME`, 5 s default). Kernel cmdline: `rtl_otto_dsa.l3_onlink=1 rtl_otto_dsa.l3_default=1`.

### On-link neighbours (`l3_onlink`)

- Eligible = kernel FIB lookup of the address gives a unicast **main** route **without gateway** out of the neighbour's device, shorter than /32 (/128), no nexthop object, single path, no lwtunnel. v6 link-local / multicast / loopback never.
- Entry = an `otto_l3_route` host route with the neighbour as its own gateway (`neigh` flag): next hop, DMAC entry (shared per MAC), L2 next-hop bit, egress interface (VLAN of the device) are the gateway-route machinery.
- Lookup order (datasheet): host table first, LPM only on a host miss. So the neighbour entry wins over the connected prefix's trap row.
- Removed when: neighbour invalid/dead (`NUD_FAILED`, gc); moved to another device; a FIB route takes the address (replace of a /32 or /128); a FIB add/delete covering it makes it ineligible (re-checked per event); `l3_onlink` cleared.
- Added on: neighbour event, on-link main route add, any route delete, FIB replay, `l3_onlink` set (replay of `arp_tbl` / `nd_tbl`).
- Table full (1536 host route ids, or no slot in the 2x6 bucket): no entry; the on-link prefix trap row takes the traffic (CPU), as without `300-17`.
- IPv6 host entries: 3 slots at slot 0 or 3 of a 6-slot row; hash = SDK `_dal_longan_l3_hostHash0/1_ret()` = IPv4 hash of the low 32 bits XOR bit *i* at *i* % 9 for *i* >= 32 (`scripts/l3_hash6_check.py`: 200 133 addresses x 2 algorithms, 0 mismatches). Slot occupancy kept in a bitmap: the 2nd/3rd slot of a v6 entry does not read back as an entry.
- Capacity: 1536 host route ids shared with /32 FIB routes and the box's own v4 addresses; v6 entries use 3 of 6144 slots each.

### Default route (`l3_default`)

- Row placed above the catch-all (`otto_l3_route_place()` keeps the catch-all last); `DFLT_ROUTE` bit = `prefix_len == 0`, as the SDK sets it.
- Upstream objection: a forwarding default row sends every destination the driver left without an entry to the gateway. Handling:
  - Every left-out destination already has a trap row above it (on-link prefixes, own addresses, routes through outside devices, blackhole/unreachable, multipath, nexthop objects, DSCP routes; v6 source-specific).
  - A route that got no entry: on the list with `hw_missing`, or `lost[family]` when it could not even be listed. Either holds the family's default row at **trap**. `lost` clears on a FIB replay, which the next route delete requests while `l3_default` is set.
  - Policy rules other than local/main (`v4_fwd_off`/`v6_fwd_off`): traps, as every forwarding row.
  - v6 source-specific default (`::/0 from X`): the default row traps.
- Not offloaded (trap via the catch-all as before): RA-learnt `::/0` (`RTF_ADDRCONF`), multipath / nexthop-object defaults, default through a device outside the switch.
- Martian destinations (127/8, 0/8, ::1, multicast DIP in a unicast frame) have no rows; assumed dropped by `BAD_DIP_ACT` = drop in `L3_IPUC_ROUTE_CTRL` / `L3_IP6UC_ROUTE_CTRL` (SDK names the field, not its match set). Verified by the test plan, not yet on hardware.

### Neighbour refresh poll

- The ASIC forwards without the kernel seeing traffic, so neighbours go `STALE` and stay unconfirmed (a MAC change would go unseen; above `gc_thresh1` = 128 entries, unreferenced `STALE` entries are collected after `gc_stale_time` = 60 s).
- Every `DELAY_PROBE_TIME`: per forwarding route with a gateway (incl. neighbour entries), entry HIT set and neighbour `STALE` -> `neigh_event_send()` (kernel unicast-probes), HIT cleared. HIT is left alone otherwise, so the dump keeps showing it.
- Same poll retries next hops still waiting for an L2 entry (`no port ... routing in software`), and applies parameter changes.

## Verification surfaces

- ASIC route table: `cat /sys/kernel/debug/realtek_otto_l3/routes` — ACTION `trap` vs `fwd`, `chk,dec` = HW checksum + TTL-decrement, HIT bit. Reset: `echo 1 > …/clear_route_hits`.
  - Neighbour entries (`300-17`): `host` rows `<addr>/32` or `/128`, WIDTH 1 / 3, NH_ID >= 512. Default rows: `prefix ... 0.0.0.0/0` / `::/0`, the one with NH_ID 0 and `trap` last is the catch-all.
- Next hops: `…/nexthops` (DMAC idx, egress intf, VID, SMAC, L2 port and MAC).
- Test procedure: [ROUTING-OFFLOAD-OPS.md](ROUTING-OFFLOAD-OPS.md).
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
