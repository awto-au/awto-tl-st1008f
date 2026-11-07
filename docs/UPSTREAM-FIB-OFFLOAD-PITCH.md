**[DRAFT - NOT SENT - needs owner approval]**

# Upstream pitch: reuse the kernel FIB-offload infrastructure for RTL930x L3 (#85)

- Drafted 2026-11-07 on owner decision "pitch fib_offload first" (#85). Nothing is posted; second explicit approval of the final text is required.
- Builds on [UPSTREAM-L3.md](UPSTREAM-L3.md) (surveyed 2026-10-12). Kernel line numbers below are `v7.4-rc1` (`git -C tmp/linux-store show v7.4-rc1:<path>`). OpenWrt line numbers are `main` `7e8bfcfe76`, `target/linux/realtek/files-6.18/drivers/net/dsa/rtl83xx/`.
- Facts, measurements and conditions: [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md). This file only cites them.

## 0. Terminology correction (read first)

- No "fib_offload" module exists in mainline. What exists is the FIB notifier plus hw-flag helpers; every router driver wraps them privately.
  - `register_fib_notifier()` `net/core/fib_notifier.c:98`; events `include/net/fib_notifier.h:15-25`.
  - `fib_alias_hw_flags_set()` `net/ipv4/fib_trie.c:1038`; `fib6_info_hw_flags_set()` `net/ipv6/route.c:6457`; `nexthop_set_hw_flags()` `include/net/nexthop.h:253`.
  - `NETEVENT_NEIGH_UPDATE` `include/net/netevent.h:27`; `RTNH_F_OFFLOAD` / `RTNH_F_TRAP` `include/uapi/linux/rtnetlink.h:456,459`.
  - Documented in `Documentation/networking/switchdev.rst:341` ("L3 Routing Offload"): "register a FIB notifier ... mirror entries", no object model.
- Two things the pitch can mean. Owner picks (section 6, question 1):
  - **A. Reuse only:** the Realtek driver is a plain FIB-notifier consumer like prestera and mlxsw. No new core code. Needs a Realtek switch driver in mainline first (none exists).
  - **B. Shared helper:** `net/core/fib_offload.c` ([UPSTREAM-L3.md](UPSTREAM-L3.md#proposal-fib_offload-helper)); cover text below asks maintainers whether they want it, before any code.

## 1. Goal and measurements

- Goal: RTL930x (RTL9303, TL-ST1008F) routes inter-VLAN, on-link and default-route traffic at 10G in the ASIC by mirroring the kernel FIB and neighbour table, using the standard FIB-notifier interfaces.
- Ask: do not add a Realtek-specific router stack; share the kernel-facing plumbing (notifier copy/defer, neighbour tracking and refresh, hw flags, trap fallback) that mlxsw, prestera, rocker, netdevsim, and now sparx5 and octeontx2 each re-implement.

Measured (all sw2, one 10G SR host, nat-bench `mode route`, TCP `-P 4`, 15 s, one run each; no NAT):

| Path | CPU path Mbit/s | ASIC Mbit/s | CPU0 off / on | Date, image |
|---|---|---|---|---|
| On-link v4 | 118 | 9198 / 9223 (fwd / rev) | 97 % / 1.2 % | 2026-11-06, OpenWrt main `b455c5b` on 7.3 |
| On-link v6 | 115 | 9032-9138 | 99.8 % / 1 % | same |
| Default v4 | 118 | 9196 / 9201 | 97 % / 0.7 % | same |
| Default v6 | 197 | 9055-9085 | 99.8 % / 0.9 % | same |
| Gateway-routed hairpin v4 (stock driver) | - | 9190 goodput, 8 streams | CPU 0.000 % | docs/ROUTING-OFFLOAD.md |

- "CPU path" = `l3_onlink` / `l3_default_*` = 0 (upstream behaviour: on-link and default traffic trap to CPU).
- Correctness checks passed on that image: neighbour delete/add, covering-route add, policy rule (`ip rule`) suspends v4 rows, parameters off (checks a, c, d, e, i). Not run: b, f, g, h.
- Not measured: the 2026-11-07 rebase of `300-17` onto the reworked `l3.c` (`7e8bfcfe76`) and kernel `v7.4-rc1`. Build only (unverified on hardware).
- Offload is opt-in (module parameters) because ASIC-routed traffic bypasses nftables (#66); no in-tree router driver checks this either ([DECISIONS.md](DECISIONS.md), 2026-10-12).

## 2. Technical case

### 2.1 Events the offload consumes

| Event / hook | Source (v7.4-rc1) | Used for |
|---|---|---|
| `FIB_EVENT_ENTRY_REPLACE/ADD/DEL/APPEND` v4+v6 | `fib_notifier.h:16-19`, `fib_trie.c:93` | prefix and host rows |
| `FIB_EVENT_RULE_ADD/DEL` | `fib_rules.c:379` | suspend forwarding under policy rules |
| `FIB_EVENT_NH_ADD/DEL` | `fib_semantics.c:1872` | next hop link state |
| `NETEVENT_NEIGH_UPDATE` | `neighbour.c:137,1198,1548` | DMAC / next-hop table, on-link host rows |
| `NETDEV_*` + inetaddr / inet6addr notifiers | `inetdevice.h:172-175`, `addrconf.h:331-336` | router interface (VLAN, router MAC, MTU) |
| Nexthop objects | `nexthop.h:170-174` | trapped today (chip has no ECMP) |

- Flag reporting back: `fib_alias_hw_flags_set()` (v4) and `fib6_info_hw_flags_set()` (v6), `offload` / `trap` / `offload_failed`.
- Current OpenWrt `l3.c` registers all three notifier families (`l3.c:5076,5149,5158`) on `init_net` only. It now reports v4 flags too (`otto_l3_fib4_flags_set`, `l3.c:1771`); the v4 gap in [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md) and [UPSTREAM-L3.md](UPSTREAM-L3.md) is stale.

### 2.2 Mapping to RTL930x tables

| Kernel object | RTL930x table | Notes |
|---|---|---|
| Route /0../32 (v4), /0../128 (v6) | prefix route table (LPM) | 512 rows shared by v4 and v6; v6 uses 3 rows |
| /32, /128, neighbour | host route table | DIP exact; host lookup precedes LPM; v6 uses 3 of 6 slots |
| Gateway / neighbour MAC | next hop (DMAC idx + egress interface idx) | DMAC entries 2048 (`MAX_DMACS`, `l3.h`) |
| Router interface (VLAN, SMAC, MTU) | egress interface table + router MAC table | 64 router MACs (`MAX_ROUTER_MACS`), MTU profiles (`MAX_INTF_MTUS` 8, `l3_limits.h:7`) |
| Unresolvable / unsupported route | trap row (CPU) + catch-all row last | ordering by row index |

- Chip capacity table (RTL9300): host 6144, prefix 512, nexthop 2048, egress interface 128, router MAC 64, no ECMP. Source: openwrt/openwrt#25129 comment 2026-09-12 citing the GPL SDK chipdefs; driver caps host route ids at 1536 (`MAX_HOST_ROUTES`). Not independently re-derived here (unverified).
- RTL930x HW rewrites SMAC, DMAC, VID, TTL, IPv4 checksum only; no NAT (#58).
- Stock path (OpenWrt `main`): only routes via a gateway are forwarded. On-link destinations and default routes trap (design statements in openwrt/openwrt#25313).
- `300-17` adds (all opt-in, `/sys/module/rtl_otto_dsa/parameters/`):
  - `l3_onlink`: resolved neighbour reached on-link through a switch port gets a host-table row to its MAC (v4 + v6). Removed on neighbour death/move, a route taking the address, a covering route making it ineligible.
  - `l3_default_v4` / `l3_default_v6`: `/0` via a gateway gets a row above the catch-all; held at trap while any route of that family has no entry.
  - A poll every `DELAY_PROBE_TIME`: entry HIT bit + neighbour `STALE` -> `neigh_event_send()`.
- OpenWrt state: L3 reworked in `main` (regmap, `resource_lock`, MTU profiles, `otto_l3_flow_nexthop_get/put` `l3.c:2519,2597`, `otto_l3_fasttrack` `l3.c:143`). `fasttrack` is never set; nothing consumes the flow next hops yet ([OPENWRT-BUMP.md](OPENWRT-BUMP.md)).
- OpenWrt issues: #25129 (closed 2026-09-28, "L3 route offload broken", plappermaul; refactor series by l0rdg3x) and #25555 (closed 2026-10-04, static-analysis list of 9 priority-1 issues, e.g. policy routing bypassed by main-table offloads, Local vs Main row ownership). Both are OpenWrt-internal; neither mentions netdev or a shared helper (read 2026-11-07).

### 2.3 What is missing or awkward in the kernel API for this chip

| # | Gap | Where | Impact |
|---|---|---|---|
| 1 | FIB events arrive in atomic context with refs only on `fib_info`; every driver copies and defers | `fib_trie.c:93` -> atomic chain; `ip_fib.h:628` `fib_info_hold` | ~230 lines in `l3.c`, duplicated per driver |
| 2 | No neighbour replay API: `register_fib_notifier()` replays routes and rules, neighbours must be walked in the driver | `fib_notifier.c:98`; `arp.h:10` `arp_table(net)`, `ndisc.h:70` `nd_table(net)` | `l3_onlink` replay walks both tables by hand |
| 3 | `NETEVENT_NEIGH_UPDATE` passes only the neighbour; netns must be derived from `neigh->dev` | `netevent.h:27` | per-netns filtering done ad hoc (sparx5 v2 added "netns filtering"); `l3.c` is `init_net` only |
| 4 | No router-interface event; RIF is inferred from netdev + inetaddr notifiers | `inetdevice.h:172-175` | RIF/router-MAC/MTU lifecycle per driver |
| 5 | No neighbour-activity feedback; HW-forwarded flows leave the neighbour `STALE`. Drivers poll HW and call `neigh_event_send()` | `neighbour.h:478`; `neighbour.h:332` `neigh_confirm`; mlxsw RAUHTD poll `spectrum_router.c:2415-2487` | RTL930x has one HIT bit per entry; same poll as mlxsw/prestera (`prestera_router.c:1063`) |
| 6 | `fib_alias_hw_flags_set()` exists only for FIB aliases. Neighbour-derived host rows have no flag path except `NTF_OFFLOADED` | `fib_trie.c:1038`; `uapi/linux/neighbour.h:51` | on-link host rows invisible to `ip route`; `NTF_OFFLOADED` use by routers: unverified |
| 7 | Whole-table correctness for a forwarding default row is left to each driver: every route the driver cannot honour must trap above it (Pirko 2016 rationale) | `Documentation/networking/switchdev.rst:341` (no text on it) | `300-17` keeps `hw_missing` / `lost[family]` bookkeeping |
| 8 | No netfilter awareness: no notifier or query for forward/NAT rules | `include/net/netns/netfilter.h:22-23` (`hooks_ipv4/6[]`, read-only poke) | ASIC routing bypasses nftables (#66); owner decision 2026-10-12: out of scope |
| 9 | `fib_info_nh()` with nexthop objects warns/crashes if the driver does not check first | `nexthop.h:491,500`; OpenWrt report: WARN at `nexthop.h:500` from `otto_l3_fib_add_v4` (openwrt#25129, 2026-09-27) | every driver needs the same guard |
| 10 | Flowtable offload is delivered to the DSA conduit, never `ds->ops`; the RTL930x host table is DIP-only, so it cannot hold 5-tuple flows | `net/dsa/user.c:1721-1742` | FIB mirror is the fit; flowtable via PIE stays research |
| 11 | `offload_l3_fwd_mark` is set only by mlxsw; needed if a HW-routed packet is also copied to the CPU (mirror/sample) | `skbuff.h:815,1023`, `ip_forward.c:70`, `ip6_output.c:493` | not needed for v1 |
| 12 | `nd_tbl` is a template; per-netns `nd_table(net)` required; `l3.c` needed a fix for it (`300-10`) | `ndisc.h:68,70` | kernel-side change already merged; docs only |

- Chip-specific, not a kernel gap: no ECMP, no VRF, one MTU profile set, 512 prefix rows. These map to "trap + `offload_failed`", which the existing flags already express.

### 2.4 Who else is writing a private router now (lore search 2026-11-07)

| Driver | Posting | State |
|---|---|---|
| Microchip sparx5 / lan969x | `[PATCH net-next v2 0/9] net: sparx5: add L3 unicast routing offload`, 2026-08-10 (v1 2026-06-12); `sparx5_router.c` +3021 lines | in review; reviewed by Jakub Kicinski 2026-08-17; absent from `v7.4-rc1` |
| Marvell octeontx2 (switch) | `octeontx2: switch: offload host FIB updates to switch via AF mailbox`, v9 2026-08-31 | in review; `rvu_switch.c` only in `v7.4-rc1` |
| Netfilter flowtable | `[PATCH nf] netfilter: flowtable: tear down HW offloaded flows on FIB route changes`, 2026-07-08 (Ahmed Zaki; Pablo Neira Ayuso replied) | in review |

- sparx5 v2 changelog describes the same plumbing work as `l3.c`: neighbours anchored to the router leg "matching mlxsw/prestera", netns filtering, offload-ownership checks, `NETDEV_UNREGISTER` backstop.
- No Realtek Otto L3, DSA or switch posting found in `netdev` for 2026 (search `realtek|rtl930x|rtl9300|otto` x `dsa|switch|route|offload`, d:2026-01-01..): only rtl8365mb (Luiz Daros de Luca bridge/VLAN series 2026-03-31) and small fixes. Search truncated at 43 of ~60 results; later months not read (unverified).
- Whether any reviewer asked for shared code on the sparx5 threads: not read (unverified).

## 3. Proposed shape

### 3.1 Where the code lives

| Piece | Proposed home | Reason |
|---|---|---|
| Shared plumbing (option B only) | `net/core/fib_offload.c`, `include/net/fib_offload.h` | next to `fib_notifier.c`; DSA and pure-switchdev drivers both usable |
| Realtek Otto switch driver (L2 first) | new directory, not `drivers/net/dsa/realtek/` | existing directory is the RTL8365/8366 SMI/MDIO small-switch family (`realtek.h`, `rtl8365mb.c`, `rtl8366rb.c`, `rtl83xx.c`); MAINTAINERS "REALTEK RTL83xx SMI DSA ROUTER CHIPS" = Linus Walleij, Luiz Daros de Luca; Otto is an in-SoC memory-mapped switch with a DMA CPU port |
| Name | OpenWrt's dir `drivers/net/dsa/rtl83xx/` clashes in name with `realtek/rtl83xx.c`; owner decides a distinct name (e.g. `rtl-otto`) | naming only |
| L3 | driver-local file on top of the helper or notifier code, after L2 merges | [UPSTREAM-L3.md](UPSTREAM-L3.md) step 4 |

- DSA vs pure switchdev for Otto is open (Chris Packham 2024: leans switchdev; Andrew Lunn: "do not impose DSA if it does not fit"). The L3 side is independent of that choice: FIB notifier needs no DSA hook (`include/net/dsa.h` has no route/neighbour op).
- Driver size after the split (option B): about 3000 lines of table code and debugfs ([UPSTREAM-L3.md](UPSTREAM-L3.md)); OpenWrt `l3.c` is now 5189 lines.

### 3.2 Relation to OpenWrt's out-of-tree driver and mainline status

| Block | Mainline v7.4-rc1 | OpenWrt-carried |
|---|---|---|
| MDIO controller | `drivers/net/mdio/mdio-realtek-rtl9300.c` | `mdio-realtek-otto.c` (superset); `031-25..34` land in 7.4 |
| I2C master | `drivers/i2c/busses/i2c-rtl9300.c` | patches only |
| SPI-NOR | `drivers/spi/spi-realtek-rtl.c` | patches only |
| GPIO, IRQ, timer, wdt, UART | `gpio-realtek-otto.c`, `irq-realtek-rtl.c`, timer, `REALTEK OTTO WATCHDOG`, 8250 | patches only |
| PCS / SerDes | none | `pcs-rtl-otto.c` (4844 lines); needs phylink fwnode PCS provider, not upstream |
| CPU-port Ethernet | none | `rtl838x_eth.c` |
| DSA switch + tagger | none | `rtl83xx/` (~20k lines), `tag_rtl_otto.c` |
| L3 | none | `l3.c` (5189 lines) |

- Source: [MAINLINE-PORT.md](MAINLINE-PORT.md) inventory (7.3-rc6) plus `ls` of the `v7.4-rc1` tree 2026-11-07 (MDIO, I2C, SPI, GPIO, IRQ files present; no `pcs-rtl*`, no Otto DSA).
- Consequence: option A cannot start before a switch driver exists. Option B can be posted as a helper plus netdevsim/prestera users with Realtek only named as a future user.
- Authorship caveat: `l3.h` header is Gennaro Cimmino (l0rdg3x) with `Assisted-by: Claude` tags; l3.c has several authors. Upstreaming needs their sign-off and the kernel's AI-assistance rules (`Documentation/process/coding-assistants.rst`, `generated-content.rst`).

## 4. Risks and questions for maintainers

Risks:
- No maintainer for a new core helper unless a vendor adopts it (UPSTREAM-L3.md risk). prestera's maintainer is Marvell (Elad Nachman); sparx5 and octeontx2 authors are active in 2026.
- An RFC with no Realtek driver in mainline has no real user; reviewers may say "post the driver first".
- Churn: converting prestera/netdevsim needs hardware or netdevsim selftests (`tools/testing/selftests/drivers/net/netdevsim/fib.sh`, `fib_notifications.sh`, `nexthop.sh`, `tools/testing/selftests/net/forwarding/fib_offload_lib.sh`; paths from [UPSTREAM-L3.md](UPSTREAM-L3.md), re-verify in the tree before sending). A conversion regression is on us.
- sparx5 v2 is mid-review; our RFC lands in the same weeks and can read as hijacking it. Coordinate with Jens Emil Schulz Østergaard first.
- Offload bypasses nftables on this chip; reviewers may ask for a guard (decision: none, [DECISIONS.md](DECISIONS.md)).

Questions for maintainers (these go in the cover text):
1. Is a shared helper wanted, or should each driver keep its own plumbing (mlxsw/prestera precedent)?
2. If wanted: `net/core` or `net/switchdev`?
3. Neighbour replay and netns in `NETEVENT_NEIGH_UPDATE`: core change acceptable?
4. Host rows for on-link neighbours (mlxsw does it per RIF; prestera nexthop-only): acceptable default, or opt-in as now?
5. Reporting for neighbour-derived rows: `NTF_OFFLOADED` or nothing?
6. Should the helper demote to trap when netfilter forward/NAT hooks exist? (Would need netfilter-devel: Pablo Neira Ayuso, Florian Westphal.)

## 5. Draft cover text (UNSENT, 25 lines)

```
To: netdev@vger.kernel.org
Subject: [RFC] net: shared FIB-offload plumbing for switch drivers (Realtek RTL930x as a future user)

Hi,
I work on the Realtek RTL930x (Otto) switch family; there is no mainline
switch driver yet. Before writing one, I would like to know if the router
plumbing should be shared instead of copied again.

mlxsw, prestera, rocker, netdevsim and the in-review sparx5 and octeontx2
series each carry their own FIB notifier copy/defer, neighbour tracking and
refresh, offload/trap/offload_failed reporting and trap fallback (about
1000-1300 lines per driver; sparx5_router.c alone is 3021).

On RTL930x with an out-of-tree driver, a 10G host measures 118 Mbit/s when
on-link and default-route traffic trap to the CPU, and 9.2 Gbit/s with
on-link neighbour host rows and a forwarding default row. The ASIC rewrites
MACs and TTL only, no NAT.

Questions: (1) is a net/core helper (router interface, next hop and route
ops plus capabilities) wanted, or should drivers keep their own? (2) can
NETEVENT_NEIGH_UPDATE carry the netns, and can neighbours get a replay path
like register_fib_notifier()? (3) are host rows for on-link neighbours
acceptable by default? Data and sketch: <link to UPSTREAM-L3.md>. No code.
Thanks, <name>
```

- Block above: 24 lines including blank lines (limit 25).
- Replace `<link>` with a public URL of [UPSTREAM-L3.md](UPSTREAM-L3.md) only after owner approval; sign-off name and affiliation are the owner's call.

### Recipients (From `v7.4-rc1` MAINTAINERS; re-run `scripts/get_maintainer.pl` on real patches)

| Role | Who | Basis |
|---|---|---|
| To | netdev@vger.kernel.org | list |
| Cc | Ido Schimmel, David Ahern | NETWORKING [IPv4/IPv6], mlxsw |
| Cc | Jiri Pirko, Ivan Vecera | SWITCHDEV; Pirko wrote the 2016 notifier move |
| Cc | Andrew Lunn, Vladimir Oltean | NETWORKING [DSA] |
| Cc | Jakub Kicinski, Paolo Abeni, Eric Dumazet, David S. Miller | NETWORKING [GENERAL] / net-next |
| Cc | Elad Nachman | MARVELL PRESTERA |
| Cc | Jens Emil Schulz Østergaard, Horatiu Vultur | sparx5 router series (from its To/Cc) |
| Cc | Ratheesh Kannoth | octeontx2 switch series |
| Cc | Chris Packham | RTL9300 MDIO and rtl9301-switch binding author (address seen on lore: chris.packham@alliedtelesis.co.nz) |
| Cc | Linus Walleij, Luiz Angelo Daros de Luca | REALTEK RTL83xx SMI DSA (naming collision) |
| Cc, optional | Markus Stockhausen | Otto MDIO and l3 author on OpenWrt; address unverified |
| Cc, only if question 6 is kept | Pablo Neira Ayuso, Florian Westphal (netfilter-devel@vger.kernel.org) | NETFILTER |

- Do not Cc OpenWrt lists or GitHub; posting upstream is "scrub + three checks" per the owner's rules.

## 6. Owner decisions needed

1. Pitch A (reuse only; blocked on a Realtek switch driver) or B (helper RFC, text above)? The mail above is B phrased as a question.
2. Author name, affiliation and whether to credit the OpenWrt `l3.c` authors (Cimmino, Stockhausen) and AI assistance.
3. Include netfilter question 6 (adds netfilter-devel) or leave out (decision 2026-10-12: no guard).
4. Contact sparx5 author (Jens Emil Schulz Østergaard) first, or post cold.
5. Wait for `300-17` hardware verification on the 2026-11-07 `l3.c` rebase before quoting numbers (the table in section 1 is from `b455c5b`).

## 7. Before sending (checklist)

- [ ] Owner approves final text (second approval, #85); scrub check: no secrets, no vendor binaries, no private paths.
- [ ] If any patch is attached (not in this cover text): based on current `net-next` (`git fetch`; net-next closed during the merge window, `v7.4-rc1` is out), `--subject-prefix='RFC net-next'`.
- [ ] `scripts/checkpatch.pl --strict` clean; `W=1` and `C=1` build; `scripts/get_maintainer.pl` run on the real series.
- [ ] Helper RFC only: netdevsim converted and `fib.sh`, `fib_notifications.sh`, `nexthop.sh`, `fib_offload_lib.sh` pass; prestera conversion at least compile-tested.
- [ ] Re-read lore for new Realtek, sparx5, octeontx2 or "common router" threads the week of sending.
- [ ] Re-verify every `file:line` above against the base tree (they are `v7.4-rc1`).
- [ ] Update stale lines in [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md) and [UPSTREAM-L3.md](UPSTREAM-L3.md) (v4 flags now reported; `l3.c` size 5189; sparx5/octeontx2 evidence).
- [ ] Hardware re-run of `300-17` on `7e8bfcfe76` / `v7.4-rc1` if numbers are quoted.
- [ ] `Signed-off-by` and AI-assistance tags per `Documentation/process/coding-assistants.rst`.

## Unverified in this draft

- Chip table sizes (section 2.2): second-hand from openwrt#25129, not checked against the SDK.
- Whether mlxsw programs a host row for every neighbour on a RIF (read `spectrum_router.c:2348` signature only).
- `NTF_OFFLOADED` use by any router driver.
- Reviewer reactions on the sparx5/octeontx2 threads; lore results past item 43 of the Realtek search.
- Markus Stockhausen's email address; whether netdev wants an RFC without code.
