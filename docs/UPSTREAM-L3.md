# Upstream path for L3 routing offload (#85)

Surveyed 2026-10-12. Question: instead of a new Realtek-only L3 stack, can the switchdev router code already in mainline be factored into helpers a Realtek driver plugs into? Kernel tree read: Linux 7.3-rc6 (with our Otto port); OpenWrt `realtek/files-6.18`. Line counts are `wc -l` on those trees.

## Answer

- No shared router helper exists in mainline, and nobody has proposed one on netdev (lore searches below). Every FIB-offloading driver writes its own notifier, neighbour, nexthop, flag and trap code.
- OpenWrt has not tried it. Realtek Otto upstreaming so far covers peripherals and MDIO only. No DSA, CPU-NIC or L3 code has been posted to netdev.
- Roughly 1000-1300 lines of each router driver are hardware-neutral (breakdown below). A helper library is feasible. Precedent: DSA's maintainer supports extracting shared switch code from DSA but has no time for it.
- Recommendation: a FIB-mirror helper (`fib_offload`, sketch below), designed **together with** the Realtek switch driver and pitched as "the second and third users" (Realtek, prestera). Flowtable offload does not fit the RTL930x host/prefix tables (below) and stays a later, separate option.

## Upstream history

**2015: switchdev core FIB ops.**
- Scott Feldman, "switchdev: add IPv4 routing offload" (v1-v4, 2015-03).
- The core called the driver per route and aborted *all* offload on the first failure. Roopa Prabhu's 2015-05 patch "switchdev: don't abort hardware ipv4 fib offload on failure…" disputed that design.
- Thread list: [lore search](https://lore.kernel.org/netdev/?q=s%3A%28fib+OR+route+OR+router+OR+routing%29+AND+s%3A%28dsa+OR+switchdev%29&o=-1).

**2016-09: DSA FIB hook attempt.**
- John Crispin (OpenWrt), [`[PATCH] net: dsa: add FIB support`](https://lore.kernel.org/netdev/1473675233-36952-1-git-send-email-john@phrozen.org/).
- It added `ipv4_fib_prepare/add/del` to `dsa_switch_ops` on top of `SWITCHDEV_OBJ_ID_IPV4_FIB`.
- Review covered only style: [Andrew Lunn](https://lore.kernel.org/netdev/20160912140002.GH11400@lunn.ch/) and [Vivien Didelot](https://lore.kernel.org/netdev/87intz22jy.fsf@ketchup.mtl.sfl/), who asked for `port_` naming and void `_add`.
- Overtaken two weeks later (below) and never merged. DSA has had no FIB hook since.

**2016-09: switchdev FIB infrastructure removed.**
- Jiri Pirko, [`fib offload: switch to notifier`](https://lore.kernel.org/netdev/1474887154-6286-1-git-send-email-jiri@resnulli.us/). It added `register_fib_notifier`, converted mlxsw and rocker, and deleted the switchdev FIB ops.
- Reason 1: a driver must see *all* prefixes, not only those on its ports. Otherwise "HW might forward prefixes known to kernel incorrectly", e.g. a HW default route while a management port has an address.
- Reason 2: "abort" moved into each driver ("the driver knows what to in order to properly abort").
- This is the design that left every driver with private router plumbing.

**2021-2022: prestera router.**
- [Basic router v1](https://lore.kernel.org/netdev/20211217195440.29838-1-yevhen.orlov@plvision.eu/) (2021-12). [Andrew Lunn](https://lore.kernel.org/netdev/Yb4R55w1mq+NXOwO@lunn.ch/) asked why IP addresses are needed: trapping the router MAC is enough for software routing.
- [Nexthop routes v7](https://lore.kernel.org/netdev/20221001093417.22388-1-yevhen.orlov@plvision.eu/) merged 2022-10-04, entirely driver-local. Nobody asked to share code with mlxsw.

**2024-06/07: "net: dsa: Realtek switch drivers" thread.**
- Started by Chris Packham (Allied Telesis), who wants RTL930x L2 and inter-VLAN routing offload. [Thread](https://lore.kernel.org/netdev/20240708142337.y5rwdxijvfnqftnh@skbuf/T/).
- Luiz Angelo Daros de Luca: improve the OpenWrt drivers first (regmap, a per-SoC abstraction instead of `if (family)` branches, no magic numbers, a real tagger).
- Chris Packham: the "NIC" is the switch's own DMA; its registers sit inside the switch block. He leans towards pure switchdev rather than DSA.
- Andrew Lunn: "you should not try to impose DSA if it does not fit". Look at the Microchip drivers; ocelot is both switchdev and DSA.
- Vladimir Oltean ([mirror](https://lkml.iu.edu/hypermail/linux/kernel/2407.1/00619.html)) is "in principle in favor of extracting core stuff out of DSA into a more generic 'eth switch' library", but has no time or incentive. "The most advanced switchdev drivers like mlxsw will probably not benefit from it". The other drivers carry boilerplate "which nobody really likes to re-re-re-write or re-re-re-review".
- Vladimir Oltean also [asked](https://lkml.rescloud.iu.edu/2407.1/00630.html) "inter-VLAN routing? Or routing offload in general?". Chris Packham [answered](https://lkml.org/lkml/2024/7/9/2) inter-VLAN routing.

**Realtek Otto pieces on netdev since then.**
- Chris Packham: [RTL9300 MDIO](https://lore.kernel.org/netdev/?q=s%3A%28rtl9300+OR+rtl930x+OR+otto+OR+rtl838x%29+AND+s%3A%28switch+OR+ethernet+OR+dsa+OR+tag%29&o=-1) (v1-v11, 2024-12 to 2025-04).
- Chris Packham: [rtl9301-switch binding moved to net](https://lore.kernel.org/netdev/20250218195216.1034220-1-chris.packham@alliedtelesis.co.nz/), applied 2025-02-21. Since then he has posted no Realtek switch code to netdev ([search](https://lore.kernel.org/netdev/?q=f%3Achris.packham+AND+d%3A20250301..+AND+NOT+s%3ARe&o=-1)).
- Markus Stockhausen (OpenWrt), 2026-05 to 2026-10, all MDIO: multi-SoC groundwork, RTL931x, [RTL83xx](https://lwn.net/Articles/1081360/), bus frequency v5 (2026-10-05).
- Other mainline Otto drivers (irq, timer, gpio, wdt, i2c, spi): [MAINLINE-PORT.md](MAINLINE-PORT.md).
- No DSA switch, tagger, `rtl838x_eth`, PCS or L3 posting was found ([author search](https://lore.kernel.org/netdev/?q=%28f%3Amarkus.stockhausen+OR+f%3Ajonas.gorski+OR+f%3Asander%40svanheule+OR+f%3Abjorn%40mork.no+OR+f%3Ajan%403e8.eu%29+AND+s%3APATCH+AND+NOT+s%3ARe+AND+s%3A%220%2F%22&o=-1)).
- OpenWrt `l3.c` work is OpenWrt PRs only (`gh search prs --repo openwrt/openwrt "realtek: l3"`: #25640, #25643, #25682, #25737, #25738, #25805, #25822). None of it has been factored out or upstreamed.

**Not found.**
- No netdev proposal for a common FIB/router helper. Subject and body searches for fib/router/routing combined with library/helpers/generic/common, 2017 onwards, return only driver-internal refactors (mlxsw) and tunnel-route helpers.
- No Ido Schimmel statement on a shared library was found.

## Kernel facilities today

- `Documentation/networking/switchdev.rst` § "L3 Routing Offload": the driver registers a FIB notifier and mirrors entries. No core object model.
- `include/net/switchdev.h`: no L3 objects; only the multicast-router port attributes.
- `net/dsa/`, `include/net/dsa.h`: no FIB, route or neighbour hook.
  - `dsa.rst` TODO: "Making SWITCHDEV and DSA converge towards an unified codebase".
  - `dsa_user_setup_tc()` forwards `TC_SETUP_FT` to the **conduit's** `ndo_setup_tc` (`dsa_user_setup_ft_block`), never to `ds->ops`. DSA flowtable offload therefore assumes a PPE on the conduit (MediaTek, Airoha).
  - `dsa_user_fill_forward_path` returns `DEV_PATH_DSA` as a terminal hop.
- Core helpers drivers already share:
  - `register_fib_notifier` (with replay and dump-flush)
  - `fib_alias_hw_flags_set`, `fib6_info_hw_flags_set`
  - `register_nexthop_notifier`, `nexthop_set_hw_flags`, `nexthop_bucket_set_hw_flags`, `nexthop_res_grp_activity_update`
  - `register_netevent_notifier` (`NETEVENT_NEIGH_UPDATE`), `neigh_event_send`
- nftables chain offload (`nf_tables_offload.c`, 699 lines): netdev-family **ingress** base chains only (`ops->hooknum != NF_NETDEV_INGRESS` → no offload). Forward-chain rules cannot be offloaded, and no API tells a driver they exist.

## Who offloads L3 today

| Driver | Router LOC | Model | Notes |
|---|---|---|---|
| mlxsw `spectrum_router.c` | 11785 | FIB mirror | v4/v6, nexthop objects, ECMP, VRF, tunnels |
| prestera `prestera_router*.c` | 1643 + 688 | FIB mirror | v4 only, `init_net` only; `_hw.c` = HW object layer |
| rocker `rocker_ofdpa.c` | ~400 of 6001 | FIB mirror | v4, no ECMP; first failure aborts all (legacy) |
| netdevsim `fib.c` | 1671 | FIB mirror | Test model: flags, nexthop objects, fault injection |
| OpenWrt `l3.c` | 4404 (ours 4843) | FIB mirror | Otto 838x/839x/930x; per-SoC ops table in `l3.h` |
| mtk `mtk_ppe*.c` | 686 + 1140 | flowtable | 5-tuple FOE entries on the conduit PPE |
| airoha `airoha_ppe.c` | 1686 | flowtable | Same design as mtk |
| mlx5 `tc_ct.c`, `rep/tc.c` | 2541 | flowtable / tc ct | Reuses the eswitch flower path |

- mlx5 `en_tc.c`, `lag/mp.c` and `tc_tun_encap.c` register FIB notifiers only to track encap and multipath; they do not offload routes.
- sparx5, lan966x and ocelot have no L3 offload: no FIB notifier, no `TC_SETUP_FT`, no `FLOW_ACTION_MANGLE`.
- SAI (switch abstraction used by SONiC, [`inc/`](https://github.com/opencomputeproject/SAI/tree/master/inc)) splits L3 into the same objects as below: virtual router, router interface, neighbor, next hop, next-hop group, route, hostif (trap). That split is a tested vendor-neutral boundary. FreeBSD and DPDK were not surveyed.

## Hardware-neutral pieces

Line counts are approximate; function names are the anchors.

**1. FIB notifier plumbing.** Atomic-context copy, workqueue, `fib_info` hold, replay and dump-flush.
- mlxsw ~350: `mlxsw_sp_router_fib_event`, `_fib4/6_event_work`.
- prestera ~85, plus ~200 of parsing: `__prestera_router_fib_event*`, `prestera_kern_fib_info_nhs`.
- l3.c ~230: `otto_l3_fib_notifier`, `otto_l3_fib*_event_work_do`, `otto_l3_fib_dump_flush`.

**2. Neighbour tracking.** `NETEVENT_NEIGH_UPDATE` → work → find routes and nexthops using that neighbour.
- mlxsw ~450: `mlxsw_sp_router_netevent_event`, neigh_entry hashtable.
- prestera ~150: `prestera_kern_neigh_cache_*`.
- l3.c ~230: `otto_l3_netevent_notifier`, `otto_l3_nexthop_update`; walks the route list, no hash.

**3. Nexthop tracking.**
- mlxsw ~2300, mixed with adjacency-table code; the only one with nexthop objects.
- prestera ~120.
- l3.c: single gateway only; ECMP and nexthop objects are trapped.

**4. Neighbour refresh.** HW-forwarded traffic never confirms the neighbour, so read HW activity and call `neigh_event_send()`.
- mlxsw ~330: `mlxsw_sp_router_neighs_update_work` (RAUHTD dump).
- prestera ~90: `prestera_router_update_neighs_work`.
- OpenWrt l3.c: none. Ours (`300-17`): `otto_l3_poll` / `otto_l3_gw_refresh` (HIT bit).

**5. HW flag reporting.**
- mlxsw ~200, prestera ~120: `fib_alias_hw_flags_set` / `fib6_info_hw_flags_set` with offload, trap and offload_failed.
- l3.c ~60: v6 only. v4 pokes `RTNH_F_OFFLOAD` directly, like rocker's legacy code.

**6. Trap fallback.** Route cannot be honoured → trap row plus `offload_failed`.
- mlxsw ~80: `mlxsw_sp_fib_entry_op_trap`.
- prestera ~100: arbiter decision.
- l3.c ~250: `otto_l3_route_trap_hw`, catch-all rows, `otto_l3_resync_*`.

**7. Policy checks.** Non-default FIB rules, VRF/table, DSCP rules, local-prefix shadowing.
- l3.c ~225: `otto_l3_rules_*`, `otto_l3_local_prefix_check`.
- mlxsw: VRs plus a rule-abort path. prestera: none.

**8. Router interfaces.** Netdev/VLAN → RIF (MAC, VID, MTU). The policy is neutral; the allocation is HW.
- mlxsw ~2000, prestera ~190, l3.c ~400.

**9. Netfilter awareness: none anywhere.**
- No driver checks for forward-chain rules or NAT before offloading.
- mlxsw expects the operator to mirror policy into `tc` ACLs.

**Totals.**
- Items 1, 2, 4, 5, 6 and 7 are about 1000-1300 lines per driver.
- In l3.c (ours) that is about 1300 of 4843; the rest is per-SoC table access (~1900), row placement (~400) and debugfs (~550).

## Two offload models

**A. FIB mirror** (mlxsw, prestera, rocker, l3.c).
- Kernel FIB plus neighbours drive HW prefix, host and nexthop tables. Per destination, independent of flows.
- Fits RTL930x exactly: LPM prefix table, host table (DIP exact), nexthop = DMAC index + egress interface, TTL/checksum rewrite in HW ([ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md)).
- Gap: bypasses netfilter. Firewall, conntrack and NAT never see forwarded packets (#66, #58).

**B. Flowtable offload** (`nf_flow_table_offload.c`, 1326 lines; mtk, airoha, mlx5).
- conntrack offloads a flow after nftables accepts it (`flow add @ft`). The driver gets `FLOW_CLS_REPLACE/DESTROY/STATS` per direction.
- Match: ingress ifindex, VLAN, exact src+dst /32 or /128, proto, exact TCP/UDP ports, TCP FIN/RST = 0.
- Actions: eth MANGLE, VLAN push/pop, REDIRECT. IP/port MANGLE only for NAT. TTL decrement is implied.
- Aging: `lastused` from `FLOW_CLS_STATS`.
- Firewall-correct by construction: only accepted, established flows go to HW, and teardown (FIN/RST) is punted.
- RTL930x fit:
  - The host table matches DIP only. One host entry would forward *every* flow to that host, including unaccepted ones, so it cannot represent a 5-tuple flow. Same over-approximation as `l3_onlink`.
  - No IP or port rewrite (#58), so no NAT flows. Routed non-NAT flows only.
  - No in-tree driver maps flowtable entries to 3-tuple route entries. mtk and airoha have `IPV4_ROUTE` / `IPV6_ROUTE_3T` encoders but always program HNAPT / `ROUTE_5T`, and they require ports.
  - DSA routes `TC_SETUP_FT` to the conduit (`rtl838x_eth`, which has no PPE), so a DSA core change would be needed to reach the switch.
  - Unverified alternative: PIE (2K entries, 5-tuple match plus `TCP_INFO` flags, `UNICAST_ROUTING` action to a nexthop) could hold exact 5-tuple flows. Costs: PIE capacity shared with ACLs; per-entry hit counters for aging not checked. Needs a datasheet/SDK pass before anyone relies on it.

**Recommendation: combine, FIB mirror first.**
- FIB mirror is the upstream-accepted model for switch ASICs (mlxsw, prestera). The RTL930x tables are FIB-shaped.
- Make netfilter awareness part of the helper (below) so a FIB-mirror driver can refuse to forward when forward hooks or NAT exist, instead of the operator-set module parameters in `300-17`.
- Flowtable via PIE: research item; it is also the only path that keeps nftables in charge on this chip.

## Proposal: `fib_offload` helper

- Location: `net/core/fib_offload.c` plus `include/net/fib_offload.h`. Usable by switchdev and DSA drivers alike, so no DSA core hook is needed.
- Scope: everything in items 1-7. The driver keeps table access, placement and RIF allocation.

```c
enum fib_offload_action { FO_FWD, FO_TRAP, FO_DROP };

struct fib_offload_rif {            /* router interface: netdev/VLAN egress */
	struct net_device *dev;
	u8 mac[ETH_ALEN];
	u16 vid;
	u32 mtu;
	u32 hw_id;                      /* driver-owned */
};

struct fib_offload_nh {             /* resolved next hop, refcounted by core */
	struct fib_offload_rif *rif;
	u8 dmac[ETH_ALEN];
	struct neighbour *neigh;        /* held by core */
	u32 hw_id;
};

struct fib_offload_route {
	int family;                     /* AF_INET / AF_INET6 */
	union { __be32 v4; struct in6_addr v6; } dst;
	u8 plen;
	u32 tb_id;
	enum fib_offload_action action;
	struct fib_offload_nh *nh;      /* FO_FWD only */
	bool host;                      /* plen == max: driver may use host table */
	bool neigh_route;               /* on-link neighbour host entry (l3_onlink) */
	unsigned long hw_priv;
};

struct fib_offload_ops {
	int  (*rif_add)(struct fib_offload *fo, struct fib_offload_rif *rif);
	void (*rif_del)(struct fib_offload *fo, struct fib_offload_rif *rif);
	int  (*nh_add)(struct fib_offload *fo, struct fib_offload_nh *nh);
	int  (*nh_update)(struct fib_offload *fo, struct fib_offload_nh *nh);
	void (*nh_del)(struct fib_offload *fo, struct fib_offload_nh *nh);
	int  (*route_add)(struct fib_offload *fo, struct fib_offload_route *rt);
	int  (*route_replace)(struct fib_offload *fo, struct fib_offload_route *rt);
	void (*route_del)(struct fib_offload *fo, struct fib_offload_route *rt);
	bool (*route_active)(struct fib_offload *fo, struct fib_offload_route *rt,
			     bool clear);       /* HIT readback for neigh refresh */
};

struct fib_offload_caps {
	u32 families;                   /* BIT(AF_INET) | BIT(AF_INET6) */
	bool default_route;             /* HW row for /0 */
	bool host_table;
	bool ecmp;
	bool nexthop_objects;
	bool onlink_neigh;              /* neighbour host entries */
};

struct fib_offload *fib_offload_register(struct net *net,
		const struct fib_offload_ops *ops,
		const struct fib_offload_caps *caps,
		bool (*dev_ours)(const struct net_device *dev),
		void *priv, struct netlink_ext_ack *extack);
void fib_offload_unregister(struct fib_offload *fo);
```

What the core does:
- Notifiers: registers the FIB, netevent and (if `caps.nexthop_objects`) nexthop notifiers; owns the workqueue, replay and dump-flush.
- Eligibility: decides FWD vs TRAP per route from caps and from `dev_ours`, so routes out of non-switch ports trap.
  - Traps: multipath without `ecmp`, nexthop objects without support, lwtunnel, source-specific v6, non-default FIB rules.
  - Matches today's `otto_l3_fib_check_v4/v6` and `otto_l3_rules_*`.
- Neighbours: resolves gateways and holds them; calls `nh_update` on `NETEVENT_NEIGH_UPDATE`; traps routes whose next hop is unresolved.
- Refresh: polls `route_active()` at `DELAY_PROBE_TIME`; HIT plus `NUD_STALE` → `neigh_event_send()`. Replaces mlxsw RAUHTD, prestera `k_arb_hw_evt` and our `otto_l3_poll`.
- Failure: `route_add` error → re-add as `FO_TRAP` and set `offload_failed`. Reports `offload` / `trap` via `fib_alias_hw_flags_set` / `fib6_info_hw_flags_set` for **both** families (fixes the l3.c v4 gap).
- Netfilter awareness (new; needs netfilter maintainers):
  - If `net->nf.hooks_ipv4/6[NF_INET_FORWARD]` is non-empty, or a NAT hook is registered at POST_ROUTING, demote every FWD route to TRAP and report `trap`.
  - A hook-change notifier from netfilter would make this event-driven.
  - Over-cautious (conntrack-only setups also trap) but never wrong. Replaces the `l3_default_v4`/`l3_onlink` operator guard.

### RTL930x mapping (`l3.c` → ops)

| op | `l3.c` today (keeps) | moves to core |
|---|---|---|
| `rif_add/del` | `otto_l3_alloc_egress_intf`, `otto_l3_router_mac_*`, `set_egress_intf` | `otto_l3_egress_sync`, `otto_l3_netdev_notifier` policy |
| `nh_add/update/del` | `set_nexthop`, `otto_l3_dmac_get/put` | `otto_l3_nexthop_update`, `otto_l3_port_gw_resolve` |
| `route_add/replace` | `otto_l3_route_place`, `route_write`, `host_route_write`, `find_slot` | `otto_l3_fib_add_v4/v6`, `otto_l3_fib_check_v4/v6` |
| `route_del` | `otto_l3_route_compact`, row writes | `otto_l3_fib_del_v4/v6`, `otto_l3_route_remove` |
| `route_active` | HIT bit read/clear (debugfs `clear_route_hits` code) | `otto_l3_poll`, `otto_l3_gw_refresh` |

- Also moving to core: `otto_l3_fib_notifier`, `otto_l3_netevent_notifier`, `otto_l3_resync_*`, `otto_l3_rules_*`, `otto_l3_neigh_*` (on-link entries become the `onlink_neigh` cap), catch-all and trap-row policy.
- Staying in the driver: the per-SoC ops table in `l3.h` (`route_read/write`, `host_route_*`, `get/set_nexthop`, `*_egress_*`, `route_rows_move`). It already is the hardware boundary. Placement and debugfs stay too.
- Expected driver size after the split: about 3000 lines of l3.c (table code and debugfs).

## Upstream path

1. **Switch driver first, no L3.**
   - Realtek RTL930x switchdev/DSA driver: L2, VLAN, FDB, STP, LAG. L3 offload is not upstreamable before a switch driver exists.
   - Settle DSA vs pure switchdev first: the NIC is switch DMA. Owners: Andrew Lunn, Vladimir Oltean; coordinate with Chris Packham (Allied Telesis) and the OpenWrt realtek developers (Markus Stockhausen, l3 author).
   - Clean up per Luiz's list in OpenWrt first (regmap, per-SoC ops, tagger).
2. **RFC: `fib_offload` helper with two users** (netdev, `[RFC net-next]`).
   - Users: netdevsim `fib.c` conversion (testable everywhere; selftests `drivers/net/netdevsim/fib.sh`, `fib_notifications.sh`, `nexthop.sh`, `net/forwarding/fib_offload_lib.sh`) plus prestera (smallest real router, already split kernel-side vs `_hw.c`).
   - Draft cover letter: `tmp/issue-drafts/85-rfc-fib-offload.md` (local, not posted).
   - Reviewers: Ido Schimmel and David Ahern (IPv4/IPv6 and FIB notifier owners; Ido maintains mlxsw), Jiri Pirko (switchdev, wrote the 2016 notifier move), Elad Nachman (prestera), Vladimir Oltean and Andrew Lunn (DSA consumers), Jakub Kicinski / Paolo Abeni (net-next).
   - Expect mlxsw to stay out (Oltean: "mlxsw will probably not benefit").
3. **Netfilter guard as a separate small series.**
   - Forward/NAT hook presence query or notifier. Owners: Pablo Neira Ayuso, Florian Westphal (netfilter-devel).
4. **Realtek L3 on top of the helper,** after the switch driver merges: per-SoC table ops only. Start with RTL930x; 838x/839x later.
5. **Research, parallel:** PIE-backed flowtable for routed non-NAT flows. Needs a DSA change to deliver `TC_SETUP_FT` to the switch, not only the conduit. Prototype in OpenWrt before proposing.

- Do not post anything without owner approval (public lists).
- Risk: no one maintains the helper unless a vendor (Marvell/PLVision, Allied Telesis) adopts it. Pitch it to prestera and Chris Packham before step 2.

## Search method and gaps

- lore.kernel.org via the browser (`goto`); plain fetch hits the Anubis proof-of-work page. Mirrors: lkml.iu.edu, lkml.org.
- Not searched: netfilter-devel for forward-hook query APIs; the OpenWrt forum in depth (one search, nothing relevant); FreeBSD, DPDK.
