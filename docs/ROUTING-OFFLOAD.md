# HW L3 routing offload (RTL9303, OpenWrt snapshot)

OpenWrt SNAPSHOT (kernel 6.18), `rtl83xx-switch` DSA driver, `l3.c` offload.

## Offload model (from `l3.c` design comment)

- RTL930x HW-forwards **only routes reached through a gateway** whose MAC is learnt on a switch port. Route gets a nexthop entry → ASIC action `fwd`.
- **On-link / directly-connected destinations TRAP to CPU** (upstream design). Plain inter-VLAN routing between two directly-attached subnets is **software** on the MIPS core. `300-17` `l3_onlink` changes this (below).
- Default routes have no ASIC entry (reach CPU via catch-all); `300-17` `l3_default_v4` / `l3_default_v6` change this. Multicast not offloaded. All egress ifaces share one 1536 B MTU.
- Capacity: 512 prefix rows (shared v4/v6; v6 = 3 rows), up to 1536 host routes.
- RTL838x/839x limited; RTL931x unsupported (FIB/neigh events ignored).

## Hardware NAT / IP rewrite: none (#58)

- Not hidden or fused off either: [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (#68).
- Routing rewrites SMAC, DMAC, VID, TTL, IPv4 header checksum only (datasheet §7.14). No IP address or L4 port rewrite.
- `L3_NEXTHOP` = DMAC idx + egress intf idx; `L3_EGR_INTF` = VID, SMAC idx, MTU idx, TTL/ICMP-redirect controls (GPL SDK `rtk_longan_table_struct.h`). ACL/PIE edits: VLAN, 1p, DSCP/TOS, IP reserved flag (datasheet §7.13.1, SDK `include/rtk/acl.h`). No NAT symbol in the SDK.
- SDK `include/rtk/acl.h` forward actions: permit, drop, copy/redirect to port(mask), unicast routing, default unicast routing, filtering, loopback, VLAN leaky. Remark actions: 1p, DSCP, TOS, IP precedence. No address/port rewrite.
- Tunnels, VXLAN, MPLS, OpenFlow set-field: RTL9310 (Mango) only; Longan has no tunnel DAL. Realtek hardware NAT exists in PON/router SoCs (RTL9607C, RTL8198 "fc"/hwnat), not the Otto switch family.
- OpenWrt `tc.c` rejects `FLOW_ACTION_MANGLE`; no `ndo_setup_tc` flow block, so nftables `flags offload` (HW flowtable) cannot bind.
- Not possible in hardware: SNAT, DNAT, masquerade, 1:1 NAT, port forwarding, NAT hairpin.
- Partial: ACL `UNICAST_ROUTING` (policy routing) steers selected flows to a next hop in hardware; still no rewrite.
- NAT stays on the CPU path (`rtl838x_eth`, 1G CPU port, #60; [NAT.md](NAT.md)). Fast path = route without NAT: the switch routes internal VLANs in hardware, the upstream router gets a static route to the switch's subnets; IPv6 needs no NAT.

## Offload gaps (#59) and `300-17`

Stock driver (OpenWrt `main` up to `e5ec5e199f`, 2026-10-11): both gaps are deliberate upstream design, nobody is working on them (upstream state below).

- On-link destinations: neighbours are not host routes, so directly-connected inter-VLAN routing traps (host table unused for this). Measured ~70 Mbit/s (v4) / 58.5 Mbit/s (v6) vs 9.69 Gbit/s gateway-routed.
- Default route: rejected by `otto_l3_fib_check_v4()` (`!info->dst`, also rejects `0.0.0.0/1`, so the `0/1 + 128/1` split fails) and `otto_l3_fib_check_v6()` (`ipv6_addr_any`). Effect: "route internally, uplink to the house router" sends every uplink packet to the CPU.
- Workarounds (no code): v4 8 routes `1/8 2/7 4/6 8/5 16/4 32/3 64/2 128/1` via the gateway (all but `0/8`; 8 of 512 prefix rows; on-link prefixes keep their longer trap rows; not measured). v6 `2000::/3` via the gateway: offloaded (`fwd`), 9.08 Gbit/s at 0 % CPU (NAT.md).

### Upstream state (surveyed 2026-10-12, #59)

- Design statements by the l3 author: on-link "forwarded by the CPU, which is what the box does with the offload off"; default route "gets no row, because such a row would match every destination" (openwrt/openwrt#25313). `otto_l3_fib_check_v6()`: left-out destinations go to the CPU because "sending those to the gateway is worse than trapping them".
- Consequence for `300-17`: default row above the catch-all; every left-out destination keeps a trap row above it (true since #25572/#25313); default row falls back to trap when any route of its family has no entry.
- Relevant merged PRs: #25313 (IPv6 offload + catch-all trap rows, 2026-10-03), #25583 (default with a source: no row), #25572 (v4 left-out routes and on-link prefixes get trap rows), #25602 (`RTF_ADDRCONF` RA routes left to the kernel), #25187 (connected subnets no longer written as /32), #25170 (host-route placement), #25636 (offload built unconditionally), #25740/#25753 (trap main routes inside a local prefix). Open #25822 is RTL839x only.
- Issues: #25129 (old rhltable keyed on `gw_ip`; CPU routing estimated "~20-50 MBit"), #25555 (RA default routes never offloaded), #25731 (closed: HW routing bypasses firewall and NAT "as already happens between VLAN interfaces"; any upstream PR must state that neighbour host routes extend this), #20139 (open, stale: inter-VLAN routing on physical ports broken on 24.10).
- Maintainer merges small bench-tested series quickly ("fully featured unicast routing for RTL930x within one month", #25731).
- Forum (OpenWrt realtek thread, 2026-09-22, SKS8300-8X / RTL9303, 6.18.52): inter-VLAN 7.71 Gbit/s with 4 streams and forwarding /32 host entries for on-link hosts. That is pre-rework code; current `main` traps on-link.
- `300-17` upstream PR: drafted, compiles `W=1` against `main` with the whole rtl83xx dir on 7.3, checkpatch --strict clean; not posted (owner approval required).

`openwrt/patches/300-17` (mainline 7.3 port; same change against `main` drafted for upstream) closes both. **Off by default**: what the ASIC routes bypasses nftables (firewall, NAT, conntrack).

| Module parameter (`/sys/module/rtl_otto_dsa/parameters/`, 0644) | Effect |
|---|---|
| `l3_onlink` | Resolved neighbour, reached on-link through a switch port, gets a host-table entry forwarding to its MAC. IPv4 and IPv6 |
| `l3_default_v4` | `0.0.0.0/0` via a gateway forwards from a row just above the catch-all |
| `l3_default_v6` | `::/0` via a gateway, same |

- Status (2026-10-12): built (`build-kernel --up` clean, `W=1` on `l3.o` clean), not run on hardware. Test plan: [ROUTING-OFFLOAD-OPS.md](ROUTING-OFFLOAD-OPS.md).
- A runtime change is applied at the next poll (`DELAY_PROBE_TIME`, 5 s default). Kernel cmdline: `rtl_otto_dsa.l3_onlink=1 rtl_otto_dsa.l3_default_v6=1`. The poll takes RTNL every 5 s and reads one entry per forwarding gateway route.
- NAT box (CPU masquerades to the internet, #58): `l3_default_v4` stays 0. A forwarding v4 default row sends internet traffic out un-NATed with the private source; the ASIC cannot rewrite IPs. `l3_default_v6=1` is fine where v6 is routed without NAT.
- The driver does not check for masquerade/SNAT: nftables rules are not visible to it without hooking the nf_tables core. Setting `l3_default_v4=1` on a NAT box is the operator's error.

### On-link neighbours (`l3_onlink`)

- Eligible = kernel FIB lookup of the address gives a unicast **main** route **without gateway** out of the neighbour's device, shorter than /32 (/128), no nexthop object, single path, no lwtunnel. v6 link-local / multicast / loopback never.
- Entry = an `otto_l3_route` host route with the neighbour as its own gateway (`neigh` flag): next hop, DMAC entry (shared per MAC), L2 next-hop bit, egress interface (VLAN of the device) are the gateway-route machinery.
- Lookup order (datasheet): host table first, LPM only on a host miss. So the neighbour entry wins over the connected prefix's trap row.
- Removed when: neighbour invalid/dead (`NUD_FAILED`, gc); moved to another device; a FIB route takes the address (replace of a /32 or /128); a FIB add/delete covering it makes it ineligible (re-checked per event); `l3_onlink` cleared.
- Added on: neighbour event, on-link main route add, any route delete, FIB replay, `l3_onlink` set (replay of `arp_tbl` / `nd_tbl`).
- Table full (1536 host route ids, or no slot in the 2x6 bucket): no entry; the on-link prefix trap row takes the traffic (CPU), as without `300-17`.
- IPv6 host entries: 3 slots at slot 0 or 3 of a 6-slot row; hash = SDK `_dal_longan_l3_hostHash0/1_ret()` = IPv4 hash of the low 32 bits XOR bit *i* at *i* % 9 for *i* >= 32 (`scripts/l3_hash6_check.py`: 200 133 addresses x 2 algorithms, 0 mismatches). Slot occupancy kept in a bitmap: the 2nd/3rd slot of a v6 entry does not read back as an entry.
- Capacity: 1536 host route ids shared with /32 FIB routes and the box's own v4 addresses; v6 entries use 3 of 6144 slots each.

### Default route (`l3_default_v4`, `l3_default_v6`)

- One parameter per family; each family's default row follows only its own parameter. Rules below apply per family.

- Row placed above the catch-all (`otto_l3_route_place()` keeps the catch-all last); `DFLT_ROUTE` bit = `prefix_len == 0`, as the SDK sets it.
- Upstream objection: a forwarding default row sends every destination the driver left without an entry to the gateway. Handling:
  - Every left-out destination already has a trap row above it (on-link prefixes, own addresses, routes through outside devices, blackhole/unreachable, multipath, nexthop objects, DSCP routes; v6 source-specific).
  - A route that got no entry: on the list with `hw_missing`, or `lost[family]` when it could not even be listed. Either holds the family's default row at **trap**. `lost` clears on a FIB replay, which the next route delete of that family requests while its `l3_default_v4`/`_v6` is set.
  - Policy rules other than local/main (`v4_fwd_off`/`v6_fwd_off`): traps, as every forwarding row.
  - v6 source-specific default (`::/0 from X`): the default row traps.
- Not offloaded (trap via the catch-all as before): RA-learnt `::/0` (`RTF_ADDRCONF`), multipath / nexthop-object defaults, default through a device outside the switch.
- Martian destinations (127/8, 0/8, ::1, multicast DIP in a unicast frame) have no rows; assumed dropped by `BAD_DIP_ACT` = drop in `L3_IPUC_ROUTE_CTRL` / `L3_IP6UC_ROUTE_CTRL` (SDK names the field, not its match set). Verified by the test plan, not yet on hardware.

### Neighbour refresh poll

- The ASIC forwards without the kernel seeing traffic, so neighbours go `STALE` and stay unconfirmed (a MAC change would go unseen; above `gc_thresh1` = 128 entries, unreferenced `STALE` entries are collected after `gc_stale_time` = 60 s).
- Every `DELAY_PROBE_TIME`: per forwarding route with a gateway (incl. neighbour entries), entry HIT set and neighbour `STALE` -> `neigh_event_send()` (kernel unicast-probes), HIT cleared. HIT is left alone otherwise, so the dump keeps showing it.
- Same poll retries next hops still waiting for an L2 entry (`no port ... routing in software`), and applies parameter changes.

## Firewall on the ASIC path (#66)

- Routes with action `fwd` are switched in the ASIC (DS §7.14.1 p.31); only `trap` routes reach the netfilter forward hook. nftables (forward chain, `ct state established`, WAN→LAN drop) does not see ASIC-routed traffic, including the IPv6 fast path (9.08 Gbit/s, eth0 7 pps).
- The ASIC has no connection tracking (none in the DS; no conntrack module in SDK `dal_longan_*`).
- PIE (DS §7.13 p.30-31) is the only enforcement point on this path:
  - 2K entries; actions drop / permit / redirect / trap / police / log.
  - The VLAN ACL phase runs before L2/L3 lookup, so it filters routed packets before routing.
  - The RTL930x template has `TCP_INFO` (TCP flags) at field 19 (`pie.c:1856`).
- OpenWrt `tc.c` does not accept `FLOW_DISSECTOR_KEY_TCP`: a flower rule on TCP flags cannot be offloaded today. Accepted keys: control, basic, eth addrs, vlan, ipv4/ipv6 addrs, ports.
- Consequence: IPv6 via the ASIC reaches every LAN host with a global address unless PIE rules drop it.
- Options (policy not decided):
  - Stateless PIE: drop WAN-ingress TCP SYN=1 ACK=0 towards LAN prefixes; allow ICMPv6 per RFC 4890; per-host permits; UDP has no SYN equivalent (trap inbound UDP to nftables, or permit selected ports).
  - Keep WAN→LAN v6 as `trap` (firewall applies) and offload LAN→WAN only: costs the downstream direction, the bulk of the traffic.
- Needed for stateless PIE: `FLOW_DISSECTOR_KEY_TCP` (flags) in `tc.c` → `pr->tcp_info` / `tcp_info_m`; test that a WAN-side SYN to a LAN host drops while LAN-initiated TCP runs at line rate.
- `300-17` parameters are off by default for this reason.

## Kernel visibility of offloaded traffic (switchdev model)

Upstream model (mlxsw, prestera, OpenWrt `l3.c`): the kernel's FIB, neighbour table and netfilter stay the source of truth; the driver mirrors them into the ASIC through FIB/netevent notifiers and must fall back to `trap` whenever the ASIC cannot honour kernel state.

Blind to ASIC-routed packets:
- `tcpdump` on lanN / eth0, nftables / iptables counters and logs, conntrack, `tc` software filters, flowtable stats, socket-level tools.

What still sees them, or how upstream restores visibility:
- Port counters: `ip -s link`, `ethtool -S lanN` (hardware MIB through DSA).
- Route state: `ip route` / `ip -6 route` flags `offload` / `trap` / `offload_failed` (`fib_alias_hw_flags_set`, `fib6_info_hw_flags_set`).
- Per-route hits: debugfs HIT bit (above).
- Packet copies: port mirroring (`tc ... matchall mirred`, `mirror.c`) to a capture port; sFlow sampling (ASIC sampler, `hsflowd`) for statistical visibility.
- Filtering: rules must be offloaded too (`tc flower` → PIE); otherwise the route stays `trap` (#66).

Gaps in ours (OpenWrt `l3.c` + `300-17`):
- IPv6 routes report offload flags; IPv4 routes do not (no `fib_alias_hw_flags_set` in `l3.c`), so `ip route` cannot show which v4 routes are in hardware.
- `300-17` takes RTNL in a 5 s poll (neighbour refresh, parameter apply); upstream expects notifier-driven updates.
- No check that nftables forward rules exist before offloading: `l3_default_v4`/`l3_onlink` on a box with a forward firewall or NAT silently bypasses it (params default off for this reason).
- No sampling to the CPU (`psample`) and no mirror-to-CPU wiring for `tcpdump` of offloaded flows.

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

## Measured — `300-17` on-link and default-route offload on 7.3 (2026-10-12)

Mainline 7.3-rc6 SMP (both VPEs, 300-18, eth0 IRQ on CPU0), CPU 1 GHz, `ramload uboot-mainline --then mainline-kernel`, one 10G SR in cage 1, nat-bench one-armed over lan1 VLANs 991/992, host netns, `mode route` (no NAT), TCP `-P 4`, 15 s, one run each.

| Path | Offload off Mbit/s | eth0 pps off | Offload on Mbit/s | eth0 pps on | CPU0 busy off / on |
|---|---|---|---|---|---|
| On-link v4 | 355 / 354 (fwd / rev) | 44.4k | 9247 / 9226 | 8-10 | 97 % / 0.5 % |
| On-link v6 | 332 | 43.2k | 9101 | 6 | 99.6 % / 0.2 % |
| Default v4 (`--dst 198.51.100.5`) | 563 | 46.9k | 9255 | 7 | 97 % / 0.3 % |
| Default v6 (`--dst 2001:db8:22::5`) | 534 | 46.6k | 9112-9125 | 5-7 | 99.7 % / 0.1-0.2 % |

- `l3_onlink=1`: host rows `10.99.1.2/32`, `10.99.2.2/32` `fwd chk,dec` NH 515/516; v6 `fd99:1::2/128`, `fd99:2::2/128` WIDTH 3 NH 518/517; HIT 1 after traffic. No `fe80::` rows.
- `l3_default_v6=1`, `l3_default_v4=0`: upper `::/0` `fwd` NH 21, upper `0.0.0.0/0` `trap` (v4 stays on the CPU path at 557 Mbit/s); catch-alls `trap` NH 0 last in both families.
- With the default offload off, the upper `/0` rows show `trap` with the gateway NH id (20 / 21), not NH 0.

### Correctness checks (same boot)

| # | Check | Result |
|---|---|---|
| a | `ip neigh del 10.99.2.2` | `/32` row gone at once; `0.0.0.0/0` (via 10.99.2.2) drops to `trap`; one ping -> both back `fwd` |
| c | `ip route add 10.99.2.0/25 via 10.99.1.2` | `10.99.2.2/32` row torn down; after `del` + ping it is back `fwd` NH 516 |
| e | `ip rule add from 10.99.1.2 table 100` | not testable on the mainline initramfs: `RTNETLINK answers: Not supported` (no `IP_MULTIPLE_TABLES`); needs OpenWrt-on-7.3 |
| i | all three parameters 0 | neighbour rows gone, upper `/0` rows `trap` within one poll |
| b, d, f, g, h | not run this pass | |

- `check-log` on the boot: CLEAN.

## Pending

- True all-port routed test (ingress ≠ egress port, #22) needs a clean **second 10G endpoint** — host has one 10G SFP+ (single-port ConnectX), twin is SFP+-only.
- Two-port L2 forwarding (2026-10-10, host on lan1, UNVR 10G SFP+ on lan8): lan1 rx +4.00 GB = lan8 tx +4.00 GB; lan1/lan8 rx_err 0, tx_err 0, 2 rx drops over 4 GB. Switch clean at line rate. Rates were endpoint-limited: UNVR→host 93 Mbit/s (UNVR `al_eth` TX bug), UNVR RX FCS errors (348 err / 13694 drop), bidir 2.5-3.6 Gbit/s. The UNVR is not a clean L3 endpoint.
- Candidate in-switch traffic sources for #22: Smart Packet Generator (#70), OAM loopback (DS §7.27).
