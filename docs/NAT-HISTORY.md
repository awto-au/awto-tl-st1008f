# NAT history: experiments, results and dead ends (#65)

Everything dated or superseded that used to live in NAT.md and NAT-PROGRESS.md, with the original conditions and numbers. Where we are today: [NAT.md](NAT.md). Run steps: [NAT-OPS.md](NAT-OPS.md). Newest CPU-port facts and sweeps (frame size, clocks, queue-1 threshold): [CPU-PORT.md](CPU-PORT.md). Raw rows: `tmp/logs/nat_bench.jsonl`, `tmp/logs/nat_knobs.jsonl`.

- Moved on 2026-11-07 from NAT.md (385 lines) and NAT-PROGRESS.md (186 lines); content unchanged apart from headings, ordering and cross-links.
- Sections run chronologically; each keeps its own conditions (clocks, kernel, image, date). Numbers from different sections are comparable only when the conditions match.
- "picks" = CPU 1350-1375 / DDR 662 / LX 306 / SRAM 500; "base" = `clocks fast` (CPU 1000, DDR 650, LX 175, SRAM 250); "stock" = CPU 800 / DDR 600.
- Metric unless noted: TCP `-P 4` through NAT + nftables software flowtable, one-armed over lan1; UDP 64 B = forwarded kpps.

## Index

| Date | What | Result |
|---|---|---|
| 2026-10-11 | [Measured (2026-10-11)](#measured-2026-10-11): OpenWrt 6.18, driver floor, flowtable | NAT+flowtable 243-248 Mbit/s; 80 without |
| 2026-10-11 | [Clock sensitivity](#clock-sensitivity-2026-10-11-devpy-nat-clock-variants): CPU/DDR/prefetch/LX one at a time | CPU clock moves pps 1:1; compute-bound |
| 2026-10-11 | [Ceiling arithmetic](#ceiling-arithmetic) and [What can and cannot leave the CPU](#what-can-and-cannot-leave-the-cpu) | 2.5G NAT through the CPU unreachable |
| 2026-10-12 | [Mainline 7.3](#mainline-73-2026-10-12): 7.3-rc6 with `300-11` vs OpenWrt 6.18 | 7.3 faster on every forwarding row |
| 2026-10-12 | [NIC path](#nic-path-300-12-2026-10-12): `300-12` doorbell, reclaim, TX ring 128 | TCP 302-307 to 348-358; overload collapse fixed |
| 2026-10-12 | [HIGHMEM and 512 MiB](#highmem-and-512-mib-300-13-2026-10-12-27): `300-13` lowmem fast paths | TCP 326-333 to 365-370 Mbit/s |
| 2026-10-12 | [Where the NIC time goes](#where-the-nic-time-goes-devpy-rteth-ftrace-1-ghz-nat--flowtable-tcp): ftrace split | No single driver cost over 2 us |
| 2026-10-12 | [Driver facts and open points](#driver-facts-and-open-points-rtl838x_eth-60): `300-14`, `tx_cpu` | SMP doorbell and TX NAPI on VPE1 lost |
| 2026-10-12 | [On-chip SRAM on the NIC path](#on-chip-sram-on-the-nic-path-103-code-reading): code reading | ~11 uncached reads, ~15 writes per frame |
| 2026-10-13 | [Clocks x on-chip SRAM matrix](#clocks-x-on-chip-sram-matrix-sw2-2026-10-13t1205-12151100-devpy-nat-matrix---perf) | Picks clocks +25 %; mapped SRAM no change |
| 2026-10-13 | [Runtime tunables at the picks](#runtime-tunables-at-the-picks-sw2-2026-10-13t1836-18501100): XPS, `300-27`, `300-28` | TCP 431 to 514-533 Mbit/s |
| 2026-10-15 | [Mainline with today's series](#mainline-with-todays-series-sw2-2026-10-15t0817-08451100): through `300-35` | 528 Mbit/s; noqueue 544 with overload loss |
| 2026-11-06 | [OpenWrt on 7.3 (main](#openwrt-on-73-main-b455c5b-next-20261009-ipv4-and-ipv6-nat-sw2-2026-11-06t0805-08081100): v4 and v6 NAT | v6 NAT equals v4 NAT; 205 vs 203 |
| 2026-11-06 | [Combinations](#combinations-2026-11-06-devpy-nat-knobs): `nat-knobs` | Best combination +31 % over defaults |
| 2026-11-06 | [In-place forward prototype](#in-place-forward-prototype-no-skb-2026-11-06-300-39-148-140): `300-39`, no skb | 143.7 kpps (1.66 Gbit/s) at 1400 B |
| 2026-11-06 | [Memory path and the second VPE](#memory-path-and-the-second-vpe-2026-11-06-scriptsmt_interferencepy) | Memory miss queue is the shared bottleneck |
| 2026-11-06 | [The second CPU](#the-second-cpu) | Per-flow ring split not yet tried |
| 2026-11-06 | [Where we are (2026-11-06)](#where-we-are-2026-11-06), [Ledger](#ledger-tcp-p4-nat--flowtable-unless-noted), [Tried, did not help](#tried-did-not-help) | 507 Mbit/s best, 20 % of target |
| undated | [Hybrid NAT](#hybrid-nat-cpu-rewrite--asic-forward-63), [Hybrid NAT (#63)](#hybrid-nat-63) | Not started; saves egress stack only |
| undated | [Strategy](#strategy-65-owner-2026-10-11), [IPv6 fast path](#ipv6-fast-path-how-most-traffic-avoids-nat), [Related](#related) | IPv6-first; NAT on CPU as fallback |
| 2026-11-06/07 | CPU-port register map, SPD_SEL writes, frame-size sweep, clock sweep at 1400 B, queue-1 threshold | In [CPU-PORT.md](CPU-PORT.md) |

## Combinations: what came back better

One table per question. Rows give the variant, the measured result, the conditions and date, the winner, and the section below that holds the evidence. Cells copy numbers from the sections; where two sections disagree, the section's own conditions apply.

### Q: Second VPE: where NAPI, IRQ, RX and TX work run

TCP P4, NAT + flowtable. VPE0 does all the work by default (one NIC IRQ, NAPI on VPE0).

| Variant | Result | Conditions, date | Verdict | Evidence |
|---|---|---|---|---|
| RPS to VPE1 | 128 vs 248 Mbit/s | OpenWrt 6.18, CPU 1000, 2026-10-11 | lost | [Forwarding through the CPU](#forwarding-through-the-cpu-tcp-4-streams-unless-noted) |
| RPS lan1 -> VPE1 on top of XPS-0 | 347 vs 502 | initramfs, picks, 2026-10-13 | lost | [Runtime tunables at the picks](#runtime-tunables-at-the-picks-sw2-2026-10-13t1836-18501100) |
| RPS to VPE1 | -31 % (default 283-294) | OpenWrt 7.3, stock 800, 2026-11-06 | lost | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| TX reclaim on the other VPE (`tx_cpu=0`, `300-14`) | ~44 % of baseline | mainline SMP, eth0 on CPU1, 2026-10-12 | lost | [Driver facts and open points](#driver-facts-and-open-points-rtl838x_eth-60) |
| `300-14` SMP-safe doorbell | 290 / 146 | 2026-10-12 | lost | [Tried, did not help](#tried-did-not-help) |
| Threaded NAPI | 440 vs 502 | initramfs, picks, 2026-10-13 | lost | [Runtime tunables at the picks](#runtime-tunables-at-the-picks-sw2-2026-10-13t1836-18501100) |
| Threaded NAPI | -9 % | OpenWrt 7.3, stock 800, 2026-11-06 | lost | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| IRQ on VPE1 alone | +1 % (work moves wholesale, VPE1 95 %) | same | neutral; -11 % on the best combination | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| Threaded NAPI, kthreads pinned one per ring, alone | +2 % | same | neutral | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| TX ring follows the CPU (`tx_by_cpu`) alone | 0 % | same | neutral | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| Pinned NAPI + `tx_by_cpu` | 320 (+13 %), CPU0/CPU1 92/95 % | same | better | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| Pinned NAPI + `tx_by_cpu` + eth0 `noqueue` | **370 (+31 %)**, 94/95 %; UDP 64 B 59 vs 53 kpps | same | **won** | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| `tx_by_cpu` + RPS | 193 (-32 %) | same | lost | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| Best combination, all frames on ring 0 (one VPE) | 344 (+21 %), CPU0/CPU1 2/96 % | same | second VPE adds 7 % | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| Fast path ring thread on VPE1 / on VPE0 / NIC IRQ on VPE1 (no thread) | 132.9 / 143.7 / 145 kpps | UDP 1400 B NAT, picks, 2026-11-06 | placement does not raise the rate | [In-place forward prototype](#in-place-forward-prototype-no-skb-2026-11-06-300-39-148-140) |

- Ideas that lost alone stack: pinned threads gain nothing until the two rings stop sharing a TX ring lock, and `noqueue` removes the qdisc lock.
- One more knob on top of the best combination (369): NAPI defer +3 %, UDP GRO forwarding +2 %, conntrack accounting off +2 %, NAPI budget +1 %, firewall off 0 %, IRQ on VPE1 -11 %, fraglist GRO off -41 %.
- Not tried in combination: SRAM packet buffers, `300-14` doorbell, picks clocks, `rx-gro-list` variants on `switch.*`, per-flow ring split ([The second CPU](#the-second-cpu)).

### Q: TX queue selection, qdisc and descriptor reads (picks, initramfs)

Mainline next-20261009, SMP, picks, NAT + flowtable, `nic-bench run`.

| Variant | TCP P4 Mbit/s | UDP 64 B kpps | Verdict | Evidence |
|---|---|---|---|---|
| baseline (`picks-uc0`), 2026-10-13 | 431 | 90.1 | - | [Runtime tunables at the picks](#runtime-tunables-at-the-picks-sw2-2026-10-13t1836-18501100) |
| XPS: both CPUs on eth0 tx-0 | 502-504 | 100.9-103.5 | better (no TX hash) | same |
| XPS-0 + threaded NAPI | 440 | 98.1 | lost | same |
| XPS-0 + RPS lan1 -> VPE1 | 347 | 93.0 | lost | same |
| XPS-0 + `rx-gro-list` off | 300 | 64.4 | lost | same |
| XPS-0 + GRO off | 485 | 65.4 | lost | same |
| `300-27` driver `ndo_select_queue`, no XPS map | 521-528 | 105.6-108.9 | **won** | same |
| + `300-28` (RX descriptor read through the cache) | 514-533 | 109.6-111.2 | **won** (UDP 64 B +3 %) | same |
| series through `300-35`, 2026-10-15 | 528 | 110.8 | no cost | [Mainline with today's series](#mainline-with-todays-series-sw2-2026-10-15t0817-08451100) |
| + 300-26 loop-probe handlers unregistered | 534 | 111.1 | within spread | same |
| + eth0 `noqueue` | 544 | 113.1 | -4 % CPU per TCP packet, but UDP overload loss 0.1 to 1.2 %: not default | same |
| + `rx-udp-gro-forwarding on` | 528 | 109.9 (1400 B @900: 71.4 vs 76.5 kpps, 4.4 % loss) | lost | same |
| eth0 `noqueue`, OpenWrt 7.3, stock 800, 2026-11-06 | +12 to +15 % | - | better (overload loss 1.2 %) | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| storm control unknown-unicast at the old default (20000 pps) | NAT capped at ~19 kpps | - | default now off (#111) | [Runtime tunables at the picks](#runtime-tunables-at-the-picks-sw2-2026-10-13t1836-18501100) |

### Q: NIC path: TX ring, reclaim and doorbell (`300-11` to `300-12`)

Mainline 7.3, CPU 1 GHz, DDR 600, HIGHMEM=y, 2026-10-12, 3 runs per step.

| Step | TCP P4 Mbit/s | UDP 64 B kpps | UDP 1400 B @900 loss | Verdict |
|---|---|---|---|---|
| base (`300-11`: TX ring 32, BQL, xmit_more) | 302-307 | 55.8-56.6 | 58-59 % | - |
| 1: RTL930x doorbell (cached `writel`) | 318-321 | 61.0-62.0 | 58 % | better |
| 2a: `napi_consume_skb`, reclaim in xmit when full | 347-359 | 68.7-69.1 | 41-45 % | better |
| 2b: TX ring 128, kick every 16 of a batch (= `300-12`) | 348-358 | 69.5-70.5 | 14-15 % | **won** |
| 3: TX from the RX page pool (no `dma_map`) | 351-360 | 70.0-70.5 | 14-17 % | no gain, reverted |
| experiment: final + HIGHMEM off | 369-380 | 74.5-75.9 | 7 % | not committed |

- Evidence: [NIC path](#nic-path-300-12-2026-10-12); per-function split: [Where the NIC time goes](#where-the-nic-time-goes-devpy-rteth-ftrace-1-ghz-nat--flowtable-tcp).

### Q: HIGHMEM and 512 MiB (`300-13`)

Same boot as above, 2026-10-12.

| Build | TCP P4 Mbit/s | UDP 64 B kpps | Verdict | Evidence |
|---|---|---|---|---|
| HIGHMEM=y, 256 MiB (`300-12` final) | 348-358 | 69.5-70.5 | - | [NIC path](#nic-path-300-12-2026-10-12) |
| `hm512-base`: HIGHMEM, 512 MiB DTS | 326-333 | 69.1-70.2 | - | [HIGHMEM and 512 MiB](#highmem-and-512-mib-300-13-2026-10-12-27) |
| `hm512-fix`: + `300-13` lowmem fast paths | 365-370 | 69.0-69.9 | **won** (TCP +11 %) | same |
| `nohm256`: HIGHMEM off, 256 MiB | 358-365 | 74.3-75.7 | reference; 7-12 % UDP gap left in `hm512-fix` | same |

### Q: GRO, flowtable, NAT versus route (CPU path)

| Variant | Result | Conditions, date | Verdict | Evidence |
|---|---|---|---|---|
| NAT, no flowtable | 80 (GRO on) / 58 (GRO off) Mbit/s | OpenWrt 6.18, base, 2026-10-11 | - | [Forwarding through the CPU](#forwarding-through-the-cpu-tcp-4-streams-unless-noted) |
| Route only, no flowtable | 62 Mbit/s | same | NAT costs nothing extra | same |
| NAT + flowtable | 243-248 (GRO on) / 213-217 (GRO off) | same | **won** (3-4x) | same |
| Route + flowtable | 232 | same | same as NAT | same |
| GRO on vs off, UDP 1400 B through the flowtable | 38-40 vs 20.8 kpps | same | GRO on doubles it | same |
| 7.3 `rx-gro-list` on vs off, NAT + flowtable | 256-328 vs 220-227 | initramfs, CPU 1000, DDR 600, 2026-10-12 | on | [Mainline 7.3](#mainline-73-2026-10-12) |
| 7.3 no flowtable (NAT 258, route 331) vs flowtable | initramfs has no fw4 ruleset | same | not comparable to OpenWrt rows | same |
| Flowtable off | -74 % (default 283-294) | OpenWrt 7.3, stock 800, 2026-11-06 | lost | [Combinations](#combinations-2026-11-06-devpy-nat-knobs) |
| Fraglist GRO off | -29 % (-41 % on the best combination) | same | on is the default | same |
| Masquerade vs masquerade + flowtable, v4 | 77.7 vs 203.2 Mbit/s | OpenWrt 7.3, old image (GRO list off), stock 800, 2026-11-06 | flowtable | [OpenWrt on 7.3 (main](#openwrt-on-73-main-b455c5b-next-20261009-ipv4-and-ipv6-nat-sw2-2026-11-06t0805-08081100) |
| Firewall ruleset with the flowtable on | 376 vs 377 | OpenWrt 7.3, stock 800 | costs nothing | [Where we are (2026-11-06)](#where-we-are-2026-11-06) |
| UDP GRO forwarding | 76.5 to 71.4 kpps, 4.4 % loss | picks, 2026-10-15 | lost | [Mainline with today's series](#mainline-with-todays-series-sw2-2026-10-15t0817-08451100) |

### Q: Clocks: CPU, DDR, prefetch, LX, SRAM

| Variant | Result | Conditions, date | Verdict | Evidence |
|---|---|---|---|---|
| CPU 1000 to 800 (-20 %) | TCP 248.3 to 212.4; UDP 64 B 44.9 to 36.2 (-19 %) | OpenWrt 6.18, `clocks fast`, 2026-10-11 | clock moves pps 1:1 | [Clock sensitivity](#clock-sensitivity-2026-10-11-devpy-nat-clock-variants) |
| DDR 650 to 600 | TCP 239.0; UDP 64 B 41.0 (-9 %) | same | small | same |
| MCR prefetch off | TCP 233.9; UDP 64 B 41.7 (-7 %) | same | keep prefetch on | same |
| LX 175 to 204 | TCP 238.7; UDP 64 B 41.4 | same | no gain | same |
| Stock 800 vs 1000, 7.3 | TCP 199.5 vs 256-328; UDP 1400 B 25.6 kpps | initramfs, gro-list off, 2026-10-12 | - | [Mainline 7.3](#mainline-73-2026-10-12) |
| base to picks, SRAM unmapped | TCP 350 to 435; UDP 64 B 73.4 to 94.2 kpps; 900 offered loss 13.6 to 0.2 % | initramfs, 2026-10-13 | **picks +25 %** | [Clocks x on-chip SRAM matrix](#clocks-x-on-chip-sram-matrix-sw2-2026-10-13t1205-12151100-devpy-nat-matrix---perf) |
| base to picks, SRAM mapped | TCP 348 to 444; UDP 64 B 72.8 to 94.5 | same | same | same |
| OpenWrt 7.3 stock vs picks 1350 | defaults 283-294 vs 388; best combination 369-377 vs 507 | 2026-11-06 | picks | [Where we are (2026-11-06)](#where-we-are-2026-11-06) |
| CPU 1375 vs 1350 | 1 wrong decode in 55 under load at 1375 | #109 | 1350 | [Where we are (2026-11-06)](#where-we-are-2026-11-06) |
| 1400 B fast path: LX 245 / DDR 500 / CPU 1000 (one at a time, -20 to -26 %) | 138.4 / 136.2 / 132.3 vs ~143 kpps | UDP+NAT, picks, 2026-11-06 | 3-8 % only: ceiling not clock bound | [CPU-PORT.md](CPU-PORT.md) |

### Q: On-chip SRAM and memory placement

| Variant | Result | Conditions, date | Verdict | Evidence |
|---|---|---|---|---|
| SRAM mapped, pool unused | no change (348 vs 350 base; 444 vs 435 picks) | initramfs, 2026-10-13 | neutral | [Clocks x on-chip SRAM matrix](#clocks-x-on-chip-sram-matrix-sw2-2026-10-13t1205-12151100-devpy-nat-matrix---perf) |
| Descriptor rings in SRAM (`300-25`, RX-only and TX-only) | link up, no traffic | same | NIC DMA does not work from SRAM | same |
| Packet buffers in SRAM | work (U-Boot `uboot-test net --ethsram`, TFTP/wget CRC match); 64 KiB = ~30 buffers | 2026-10-13 | possible, not tried in Linux | same |
| RX descriptor read through the cache (`300-28`) | UDP 64 B +3 %, TCP within spread | picks, 2026-10-13 | kept | [Runtime tunables at the picks](#runtime-tunables-at-the-picks-sw2-2026-10-13t1836-18501100) |
| Sibling VPE probe: none / sram / chase / stream | 344-347 / 293 / 226 / 86 Mbit/s | OpenWrt 7.3, stock 800, 2026-11-06 | DRAM misses shared; SRAM neighbour costs least | [Memory path and the second VPE](#memory-path-and-the-second-vpe-2026-11-06-scriptsmt_interferencepy) |
| Sibling L1 working set 8 / 16 / 28 KB | 242 / 217 / 200 Mbit/s | same | L1 capacity is not the limit | same |

### Q: In-place (zero-copy) forward versus the skb stack

Picks (CPU 1350 / DDR 662 / LX 306 / SRAM 500), OpenWrt 7.3, sw2 RAM boot, 2026-11-06, `300-39`.

| Variant | Stack path | In place | Verdict | Evidence |
|---|---|---|---|---|
| UDP 1400 B payload, route only | 21.8 kpps (252 Mbit/s) | 143.3 kpps (1658 Mbit/s) | 6.6x | [In-place forward prototype](#in-place-forward-prototype-no-skb-2026-11-06-300-39-148-140) |
| UDP 64 B payload, route only | 22.7 kpps | 490.7 kpps | 21.6x | same |
| UDP 1400 B, source NAT, 4 flows | 9.2 kpps | 143.6 kpps (1661 Mbit/s) | 15.6x | same |
| TCP P4, stateless static 1:1 NAT, client -> server | 114.7 Mbit/s | 1339.6 | 11.7x | same |
| TCP P4, same, server -> client | 129.1 | 1309.8 | 10.1x | same |
| TCP P4, real NAT: flowtable `flags offload` feeds the fast path, client -> server | 420 (software flowtable) | 1250 | 3.0x; best software-NAT result is 507 | same |
| TCP P4, same, server -> client | - | 1187 | - | same |

- Evidence for the 1400 B limit not being CPU: [CPU-PORT.md](CPU-PORT.md) (frame-size sweep, clock sweep); the stack-path equivalents are in the tables above.

### Q: Queue-1 drop threshold (`300-40`)

Picks, iperf3 TCP P4 through NAT, fast path, `--napi irq1`, 2026-11-06; forward / reverse. Full table and the evidence: [CPU-PORT.md](CPU-PORT.md) (queue 1 drop threshold).

| ON/OFF pages | Goodput Mbit/s | Retransmits | Verdict |
|---|---|---|---|
| 52/36 | 1117 / 1178 | 21.7k / 22.6k | lost |
| 78/68 (boot) | 1257 / 1295 | 15.1k / 15.3k | - |
| 1024/1008 (`300-40` default) | 1517 / 1519 | 1.9k / 2.0k | **won** |
| 4095/4080 | 1507 / 1504 | 1.3k / 1.3k | no gain; 4095 buffers up to 3634 pages |

### Q: ASIC forwarding, IPv6 and hybrid NAT

| Variant | Result | Conditions, date | Verdict | Evidence |
|---|---|---|---|---|
| IPv6 gateway-routed far /64 (ASIC L3) | 9070 Mbit/s at 0 % CPU | OpenWrt 6.18, 10 s, 2026-10-11 | won | [IPv6 through the ASIC](#ipv6-through-the-asic) |
| IPv6 `2000::/3 via <gw>` workaround, 60 s | 9079 Mbit/s at 0 % CPU | same | won (`::/0` is not offloaded) | same |
| IPv6 on-link host to host | 58.5 Mbit/s, VPE0 99.7 % | same | trapped to the CPU | same |
| IPv4/IPv6 NAT on the CPU, masquerade + flowtable | 203.2 v4 / 205.3 v6 Mbit/s | OpenWrt 7.3, old image, stock 800, 2026-11-06 | v6 NAT costs the same as v4 | [OpenWrt on 7.3 (main](#openwrt-on-73-main-b455c5b-next-20261009-ipv4-and-ipv6-nat-sw2-2026-11-06t0805-08081100) |
| Hybrid: CPU rewrite + ASIC re-injection (#63) | not started | - | saves only the egress stack; cannot reach 2.5G | [Hybrid NAT](#hybrid-nat-cpu-rewrite--asic-forward-63) |
| NAT rewrite in the ASIC | not supported (#58, #68) | - | none | [What can and cannot leave the CPU](#what-can-and-cannot-leave-the-cpu) |

### Q: Kernel and image

| Variant | Result | Conditions, date | Verdict | Evidence |
|---|---|---|---|---|
| 7.3 + `300-11` (gro-list on) vs OpenWrt 6.18 | TCP NAT +7-37 %, UDP +36-38 %, RX-only +41-44 %, TX-only level | 2026-10-12 | 7.3 | [Mainline 7.3](#mainline-73-2026-10-12) |
| linux-next vs 7.3 | tcp-P4 358-360 vs 325 Mbit/s | sw2, 2026-10-12 | next | [MAINLINE-PORT.md](MAINLINE-PORT.md#throughput-one-run-each) |
| SMP vs UP | 322-334 vs 346 | 2026-10-12 | UP a few % faster on throughput | [Ledger](#ledger-tcp-p4-nat--flowtable-unless-noted) |
| OpenWrt 7.3 vs initramfs | 283-294 at 800 MHz vs 350 at 1000 MHz = the clock ratio | 2026-11-06 | no image gap; the old low OpenWrt numbers were fraglist GRO off | [Where we are (2026-11-06)](#where-we-are-2026-11-06) |

## Verdict (as written 2026-10-12)

- IPv4 NAT runs only on the CPU path: the ASIC has no IP/port rewrite (#58).
  - Best measured, with the nftables software flowtable: OpenWrt 6.18 **248 Mbit/s** TCP NAT, UDP 1400 B 39.7 kpps (about 445 Mbit/s); our mainline 7.3 (DDR 600) with `300-12` **348-358 Mbit/s** TCP NAT, UDP 1400 B **65 kpps** (about 750 Mbit/s at 900 offered, no collapse), UDP 64 B 70 kpps. See "Mainline 7.3" and "NIC path (`300-12`)".
  - 2.5 Gbit/s needs about 10x less CPU per packet than today. Not reachable on this CPU.
  - The per-packet cost scales with the CPU clock and barely with DDR or LX (see "Clock sensitivity"): the CPU path is compute-bound.
- IPv6 needs no NAT and is routed by the ASIC at **9.08 Gbit/s with 0 % CPU**. This is the fast path; clients prefer IPv6 when it is offered (see "IPv6 fast path").
- CPU port speed (1G) is not the throughput limit: 65 kpps x 1400 B is about 750 Mbit/s each way. Its drain time per RX poll is why the TX ring needs 128 slots (#60, "NIC path").

## Measured (2026-10-11)

Conditions:
- Flash OpenWrt SNAPSHOT r36962, kernel 6.18.55.
- CPU 1000 MHz (BogoMIPS 663.55 vs 531.45 at 800 MHz), DDR3 650, DRAM prefetch on.
- One-armed over lan1 (10G) with VLANs 991/992; host 10G mlx4.
- `scripts/nat_bench.py`; raw rows in `tmp/logs/nat_bench.jsonl`.
- "µs/pkt" = busy VPE time / CPU-port RX packets.

### Driver-only floor

| Probe | 1400 B | 64 B | VPE0 | µs/pkt |
|---|---|---|---|---|
| RX only, eth0 GRO + rx-gro-list on (default): UDP flood dropped at lan1 netdev ingress, rate = eth0 rx_packets | 96.6-101.3 kpps | 110-115 kpps | 98 % softirq | 8.6-10 |
| RX only, GRO and rx-gro-list off | 43.6 kpps | 48.4 kpps | 98 % softirq | 20-23 |
| TX only: in-kernel pktgen on lan1 (clone_skb 0) | 42-53 kpps (476-591 Mbit/s) | 33-56 kpps | 82-93 % sys | 17-25 |

- RX: fraglist GRO batches the stack per GRO skb. The ingress counter then sees about 1 skb per 40 packets. Driver RX alone costs about 9 µs per packet.
- TX: pktgen spread is ±20 % between runs, larger than the clock effects below. Treat it as a range.
- Cost is per packet, not per byte: 64 B and 1400 B give about the same pps.

### Forwarding through the CPU (TCP, 4 streams unless noted)

| Path | Mbit/s | CPU-port pps (each way) | µs/pkt |
|---|---|---|---|
| NAT (masquerade), no flowtable | 80 (GRO on) / 58 (GRO off) | 10.2 k / 7.5 k | 94-128 |
| Route only, no NAT, no flowtable | 62 | 7.8 k | 124 |
| NAT + flowtable | **243-248** (GRO on, via `clocks fast`); 228 (GRO on, chain boot) / 213-217 (GRO off, P1/P4/reverse) | 30.6 k / 28.1 k / 26.6 k | 31-36 |
| Route + flowtable | 232 | 28.8 k | 33 |
| NAT + flowtable, UDP 1400 B at 600 Mbit/s offered, GRO on | **441-460 goodput** | 38.1-39.7 k, 0 driver drops | 24-25 |
| NAT + flowtable, UDP 64 B, GRO on | 41.9-44.9 kpps | - | 22 |
| NAT + flowtable, UDP 1400 B at 600 Mbit/s offered, GRO off | 240 goodput, 59.6 % loss | 20.8 k, heavy `rx_dropped` | - |
| NAT + flowtable, UDP 64 B, GRO off | 21.6 kpps | - | - |
| NAT + flowtable + RPS to VPE1 | **128** (worse) | 16.1 k | both VPEs ~95 % |

- The flowtable cuts the stack cost from about 85 µs to about 0. What is left is the driver plus per-skb cost.
- GRO on (the default, with rx-gro-list) doubles UDP forwarding through the flowtable (20.8 to 39.7 kpps). Keep it on.
- The GRO-on TCP and UDP rows (243-248 Mbit/s, 38-40 kpps) come from boots via our U-Boot `clocks fast` (`./dev.py nat-clock-variants base`, 3 runs).
- NAT itself costs nothing extra: NAT and plain routing give the same numbers with and without the flowtable.
- One VPE does all the work: one NIC IRQ, NAPI on VPE0, VPE1 idle.
  - RPS onto VPE1 halves throughput. The two VPEs share one 34Kc pipeline, and IPIs plus cache sharing cost more than they save.
- CPU-terminated (iperf3 on the switch), for comparison:
  - RX: UDP 230 Mbit/s, TCP 102 Mbit/s.
  - TX: UDP 87 Mbit/s, TCP 128 Mbit/s.
- Userspace daemons use about 0 % (procd, netifd, rpcd, ubusd, logd, urngd, dropbear, ntpd). Nothing to trim there.

### IPv6 through the ASIC

| Case | Mbit/s | CPU |
|---|---|---|
| Gateway-routed far /64 both ways, 10 s | 9070 | 0 % (eth0 12 pps) |
| `2000::/3 via <gw>` (default-route workaround), 60 s | **9079** | 0 % (eth0 7 pps) |
| On-link host to host (no gateway) | 58.5 | trapped: VPE0 99.7 % |

- `::/0` is not offloaded: it shows as `trap` in `realtek_otto_l3/routes`, same as IPv4 (#59). `300-17` `l3_default_v4` / `l3_default_v6` offload them, one parameter per family (mainline port, not yet measured).
- `2000::/3` covers all global unicast and is offloaded (`fwd`, `chk,dec`).
- Offloaded routes depend on the gateway's neighbour entry. With a STALE neighbour the route reads `trap`; once the neighbour is REACHABLE again it reads `fwd`. No flapping was seen over 60 s at 9 Gbit/s.

### ASIC limiters (read from regmap debugfs, all off)

- `MAC_FORCE_MODE_CTRL(28)` `0xCA8C` = `0x217`: force link, full duplex, SPD_SEL 2 = 1G, FC_EN.
  - SPD_SEL encodings: 4 = 10G, 5 = 2.5G, 6 = 5G (SDK `dal_longan_port.c`).
- `EGBW_PORT_CTRL(28)` `0x7820`: EN = 0. `IGBW_PORT_CTRL(28)` `0x80D8`: BW_EN = 0.
- CPU-queue force drop `0xC4DC` = 0. Peak CPU-queue depth under flood: `0x340` pages (clear-on-read `0x7E40`).
- `QM_RSN2CPUQID`: every reason goes to queue 0 or 1 (2 of 32 rings).

## Clock sensitivity (2026-10-11, `./dev.py nat-clock-variants`)

- Flash OpenWrt booted from our U-Boot after `clocks fast` plus one change. SPI stays stock throughout.
- NAT + flowtable, GRO on. Base = CPU 1000, DDR 650, tREFI 7.1 µs, MCR prefetch on, LX 175.
- Base spread over 3 boots: TCP 243-248 Mbit/s, UDP 1400 B 38.1-39.7 kpps, UDP 64 B 41.9-44.9 kpps, RX-drop 64 B 110-115 kpps. That is about ±4 %.

| Variant | Change | NAT TCP Mbit/s | µs/pkt | UDP 1400 B fwd kpps | UDP 64 B fwd kpps | RX-drop 1400/64 B kpps | vs base (UDP 64 B) |
|---|---|---|---|---|---|---|---|
| base | - | 248.3 | 31.2 | 39.7 | 44.9 | 101.3/114.6 | - |
| cpu800 | CPU 1000 to 800 (−20 %) | 212.4 | 36.4 | 34.4 | 36.2 | 86.4/96.8 | **−19 %** |
| ddr600 | DDR 650 to 600 (−8 %) | 239.0 | 32.6 | 37.5 | 41.0 | 94.5/112.6 | −9 % (TCP −4 %) |
| nopref | MCR ip_ref/dp_ref off | 233.9 | 33.1 | 37.6 | 41.7 | 97.8/109.4 | −7 % (TCP −6 %) |
| lx204 | LX 175 to 204 (+17 %) | 238.7 | 32.3 | 37.9 | 41.4 | 98.7/112.4 | −8 % (no gain) |

- **Compute-bound.** The CPU clock moves forwarding about 1:1: −20 % clock gives −13 to −19 % pps and −15 % RX.
- DDR clock and controller prefetch matter a little (≤ 9 %, near the run-to-run spread).
- LX (the switch-register / MMIO bus) gives no gain at +17 %. Per-packet uncached register access over LX is not the bottleneck.
- So the time is mostly instructions executed on the core, not DRAM latency or MMIO. Profiling (perf in the 7.3 port, #16) needs to find which code runs about 25-30k cycles per packet.
- LX 204 under Linux: the console prints garbage (DTB/UART rate mismatch). The board ran fine otherwise. STP was checked over SSH.
- `clocks set lx` takes codes 2..5 only (5 = stock 175), so a slower-LX step is not available.

## Ceiling arithmetic

- 2.5 Gbit/s of 1500 B frames = 208 kpps of data, plus about 104 kpps of TCP ACKs the other way. That is about 312 kpps through the CPU port.
- With one 34Kc pipeline at 1 GHz, that leaves about **3.2 µs (3200 cycles) per packet for RX + NAT + TX**. Measured today: 22-31 µs with the flowtable (GRO on); RX alone is about 9 µs and TX alone 17-25 µs.
- No L2 cache; a random cached miss costs 109 ns (CLOCKS.md). DMA is non-coherent, so every packet header is a cache miss after invalidate.
- 2 Gbit/s down-only (ACKs up) still needs about 250 kpps.
- Realistic ceiling for this CPU (estimates, 2026-10-11, not measured):
  - lean Linux forward + flowtable on MIPS ≈ 5-8k instructions ≈ 7-12 µs per packet at 1 GHz;
  - ~20-40 cache lines touched per packet × 110 ns miss ≈ 2-4 µs;
  - → ~80-140 kpps ≈ **1-1.7 Gbit/s** at 1500 B; sanity check: MT7621 (880 MHz, 2 cores) does ~0.9-1 Gbit/s software NAT + flowtable on all cores;
  - expected NIC driver cost ~3-5 µs per packet vs 17-25 µs measured (GRO off) → the 3-5x gap is per-packet overhead, not NAT (NAT costs nothing measurable over plain routing).
- 2.5G IPv4 NAT through the CPU is not reachable; 2.5G+ belongs to IPv6 routed in the ASIC.
- Driver-cost hypotheses listed 2026-10-11 and how they resolved: uncached descriptor rings (open, cached RX descriptors not tried); per-packet MMIO over LX (ruled out: LX +17 % = no gain); IRQ per packet (open); full-buffer cache maintenance (ruled out: sync/map cover the frame length only); TX ring 16 + doorbell per packet (fixed in `300-11`/`300-12`, the 29 µs doorbell poll was an RTL838x workaround).
- CPU port 28 is internal (`PHY_INTERFACE_MODE_INTERNAL`, DMA to RAM, no SerDes): the driver's `MAC_1000FD` cap and `0xCA8C` SPD_SEL = 1G are labels unless the ASIC paces port-28 egress to SPD_SEL. Untested: the 10G (`0x227`) / 2.5G (`0x22F`) A/B was skipped (owner, 2026-10-11) until the CPU path nears 1 Gbit/s; flash OpenWrt has no `/dev/mem`. The power-on SPD_SEL value is unread (only read after the stock loader, which writes other bits of `0xCA8C`).
- A driver rewrite gaining 3-4x (not measured) would give about 0.6-0.9 Gbit/s, and needs perf data first.

## What can and cannot leave the CPU

- ASIC can:
  - L3 routing with MAC rewrite, TTL and checksum (v4 and v6).
  - ACL drop, permit, redirect and copy.
  - PIE `UNICAST_ROUTING` to a nexthop index (policy routing, no rewrite).
  - Per-ACL CPU queue (`ACT_MSK_QID`).
- ASIC cannot:
  - Rewrite IP addresses or L4 ports, so no NAT (#58).
  - Trap only the first N packets of a flow: no such PIE action.
  - Insert TX checksums or do TSO.
  - Provide coherent DMA.
- Consequence: every NAT packet crosses the CPU twice (RX + TX). PIE can only keep non-NAT traffic away from the CPU: route it in hardware, drop junk in the ACL.
- FWD_ALE + `L3_ACT` re-injection (#63) skips only the egress stack. driver RX + TX (about 26-34 µs) remains, so the hybrid design cannot reach 2.5G either.

## Mainline 7.3 (2026-10-12)

Conditions:
- Our 7.3-rc6 kernel (#16): OpenWrt realtek drivers + `300-11` (TX ring 32, BQL, xmit_more doorbell), UP (one VPE), initramfs.
- Booted via `./dev.py ramload uboot-mainline --then mainline-kernel`: CPU 1000 MHz, **DDR 600** (compare with the OpenWrt `ddr600` row above), DRAM prefetch on, SPI stock.
- Same topology and script (`nat-bench`, SVIs `lan1.991`/`lan1.992`, no fw4). `rx-gro-list on` on eth0 + lan1 (set by `port-up`; the 7.3 default is off).
- Rows: `tmp/logs/nat_bench.jsonl`, tags `mainline73-1ghz`, `mainline73-1ghz-grolist`, `mainline73-cpu800`.

| Test | 7.3 rx-gro-list on | 7.3 rx-gro-list off | OpenWrt 6.18 (ddr600 / base) |
|---|---|---|---|
| NAT + flowtable, TCP P4 | **256-328** (2 boots: 323-328, 256-274) | 220-227 | 239 / 243-248 |
| NAT + flowtable, TCP P1 | 286-291 | 220 | 213-217 (GRO off) |
| NAT + flowtable, UDP 1400 B at 600 Mbit/s offered | **600 goodput, 0 % loss, 51 kpps** | 21.4 kpps fwd (qdisc drops) | 37.5 / 38-40 kpps |
| NAT + flowtable, UDP 1400 B at 700 / 900 offered | 46.9 / 31.7 kpps fwd | - | - |
| NAT + flowtable, UDP 64 B | **55.8-56.6 kpps** | 35.8 kpps | 41.0 / 42-45 kpps |
| Route + flowtable, TCP P4 | 356 | - | 232 |
| NAT, no flowtable, TCP P4 | 258 | - | 80 (fw4 ruleset) |
| Route, no flowtable, TCP P4 | 331 | - | 62 (fw4 ruleset) |
| RX only (rxdrop), 1400 / 64 B | 133 / 162 kpps | - | 94.5 / 112.6 kpps |
| TX only (pktgen), 1400 / 64 B | 37.7-40.0 / 60.8 kpps | - | 42-53 / 33-56 kpps |
| CPU-terminated TCP RX / TX (local, P1) | 295 / 238 | - | 102 / 128 |
| CPU-terminated UDP RX / TX | 53 kpps (613 Mbit/s) / 100 Mbit/s | - | 230 / 87 Mbit/s |

- 7.3 with fraglist GRO beats OpenWrt 6.18 on every forwarding row: TCP NAT +7-37 %, UDP +36-38 %, RX-only +41-44 %. TX-only is level.
- No-flowtable rows are not comparable: the initramfs has no fw4 ruleset, OpenWrt runs every packet through it.
- At 800 MHz (stock clocks, gro-list off): NAT + flowtable TCP 199.5, UDP 1400 B 25.6 kpps fwd; local TCP RX 277 / TX 212.
- The rows above are `300-11` only. Overload collapse (UDP 1400 B at 700/900 offered fell to 47/32 kpps) is fixed by `300-12`: see "NIC path".
- TCP P4 differs between two boots of the same image (323-328 vs 256-274, retransmits 1400 vs 3000); P1 matched (291 vs 286). Cause not isolated.

### NIC path (`300-12`, 2026-10-12)

linux-next vs 7.3 on sw2 (2026-10-12): [MAINLINE-PORT.md](MAINLINE-PORT.md#throughput-one-run-each) (next: tcp-P4 358-360 vs 325 Mbit/s).

Same boot and topology as above (DDR 600, CPU 1 GHz, HIGHMEM=y). `./dev.py nic-bench run`, 3 runs per step, one boot per step; rows tagged `nic-*` in `tmp/logs/nat_bench.jsonl`. Cells: min-max of 3. `fwd kpps` = eth0 TX. `ns/pkt` = busy VPE time per eth0 RX packet.

| Step | TCP P4 Mbit/s | UDP 1400 @600 kpps | @700 kpps (loss %) | @900 kpps (loss %) | UDP 64 B kpps | ns/pkt UDP 64 B |
|---|---|---|---|---|---|---|
| base (`300-11`) | 302-307 | 50.9-51.1 | 45.7-46.8 (21-23) | 31.3-32.1 (58-59) | 55.8-56.6 | 16690-16841 |
| 1: RTL930x doorbell (cached `writel`, no poll/lock/ktime) | 318-321 | 50.9-51.0 | 47.7-48.1 (19-20) | 32.0-32.3 (58) | 61.0-62.0 | 15366-15407 |
| 2a: `napi_consume_skb`, reclaim in xmit when full | 347-359 | 50.9-51.1 | 59.4-59.5 (0) | 40.4-44.4 (41-45) | 68.7-69.1 | 13579-13866 |
| 2b: TX ring 128, kick every 16 of a batch | 351-354 | 50.9-51.0 | 59.4-59.5 (0) | 64.9-65.2 (14-15) | 70.0-70.4 | 13559-13618 |
| 3: TX from the RX page pool (no `dma_map`) - reverted | 351-360 | 50.9-51.1 | 59.4 (0) | 63.8-65.3 (14-17) | 70.0-70.5 | 13523-13594 |
| final (`300-12` = 2b) | **348-358** | 50.9 | **59.4-59.6 (0)** | **64.5-65.3 (14-15)** | **69.5-70.5** | 13580-13705 |
| experiment: final + `HIGHMEM` off (not committed) | 369-380 | 50.9-51.1 | 59.4-59.5 (0) | 70.6-71.1 (7) | 74.5-75.9 | 12558-12700 |

- UDP 1400 B at 600 offered is offered-limited (51 kpps in = out); 900 offered is the saturated 1400 B number.
- Overload: eth0 qdisc drops at 900 offered 790-810 k per run (base) -> 0 (2b, final). Excess now drops in the NIC RX ring (no CPU spent), RX pps = TX pps.
- Cause of the collapse: reclaim ran only at the start of each RX poll; a poll's burst of 1400 B frames takes longer on the 1G CPU port than one ring holds, so TX got at most one 32-slot ring per 64-frame RX poll (RX 63 k : TX 32 k).
- Step 3 removed `dma_map`/`unmap` for forwarded frames (page pool mapped bidirectional, `dma_sync_single_for_device` only): no measurable gain, reverted. The cache writeback itself stays.
- `HIGHMEM=y` costs 5-9 %: every `dma_sync` goes through `kmap_atomic` and `page_address()` is out of line, while the HighMem zone is empty (256 MiB in the DTS). Trade-off with the second 256 MiB (#27).
- Final, other paths (1 run each): pktgen TX 1400 / 64 B 49.1 / 64.7 kpps (base 37.7-40.0 / 60.8); rxdrop 137 / 165 kpps (base 133 / 162); CPU-terminated TCP RX / TX 300 / 261 Mbit/s (base 295 / 238).
- Final: no driver warnings; BQL limits 133400 / 89798 B on tx-0 / tx-1 after the suite; qdisc requeues 30 over the whole suite.

### HIGHMEM and 512 MiB (`300-13`, 2026-10-12, #27)

Same boot and topology as "NIC path" (DDR 600, CPU 1 GHz, UP, `300-12`). `./dev.py nic-bench run`, 3 runs, one boot per row; tags in `tmp/logs/nat_bench.jsonl`.

| Build | TCP P4 Mbit/s | UDP 1400 @600 kpps | @700 kpps | @900 kpps (loss %) | UDP 64 B kpps | ns/pkt UDP 64 B |
|---|---|---|---|---|---|---|
| `hm512-base`: HIGHMEM, 512 MiB DTS | 326-333 | 51.1-51.2 | 59.6 | 60.3-60.9 (20-21) | 69.1-70.2 | 13636-13844 |
| `hm512-fix`: + `300-13` | **365-370** | 48.7-51.1 | 58.2-59.6 | 61.1-62.3 (19-20) | 69.0-69.9 | 13543-13699 |
| `nohm256`: HIGHMEM off, 256 MiB (reference) | 358-365 | 51.0-51.1 | 59.4-59.6 | 70.0-71.1 (7-8) | 74.3-75.7 | 12629-12656 |

- `300-13` (lowmem fast paths: `dma_sync_phys` without kmap, inline `page_address`): TCP +11 %, at or above the HIGHMEM-off reference.
- UDP saturated rows keep a 7-12 % gap: the remaining HIGHMEM cost is on the UDP path and not located yet (next: `./dev.py rteth-ftrace --count` on the highmem-only functions under UDP 64 B load).
- 512 MiB vs 256 MiB with HIGHMEM: same UDP 64 B as the 256 MiB "final" row above (69.5-70.5).

### Where the NIC time goes (`./dev.py rteth-ftrace`, 1 GHz, NAT + flowtable TCP)

- `function_graph` keeps the mcount hook on every function, so all times are inflated (load drops to 50-90 Mbit/s); use the split.
- `rteth_start_xmit` per call (depth 1): 18.9 µs (`300-11`) -> 14.0 µs (`300-12`).
- Doorbell: `regmap_read_poll_timeout` + `regmap_write` 29 µs per kick on 58 % of packets (`300-11`) -> `rteth_930x_tx_kick` 1.6 µs per kick (mostly tracer cost of one call).
- TX reclaim per packet: `dev_kfree_skb_any` 11.8 + `dma_unmap` 5.6 µs (`300-11`) -> `rteth_reclaim_tx_ring` 8.2 µs including `napi_consume_skb` and unmap.
- Remaining split per RX packet, `300-12`, depth 2 (µs, inflated): `dma_map_page_attrs` 4.3 (TX writeback; under it `kmap_local` + `r4k_dma_cache_wback_inv`), TX reclaim 4.2, `gro_receive_skb` 3.3, `page_pool_alloc_frag` 1.4, `napi_build_skb` 1.3, `__dma_sync_single_for_cpu` 1.1 (a no-op on the 34Kc: `cpu_needs_post_dma_flush` false), `is_vmalloc_addr` 1.0, `decode_tag` 0.9, `create_tx_header` 0.8, `tx_kick` 0.8, `eth_type_trans` 0.8, `page_address` 0.7 (HIGHMEM), `enable_rx_irq` 0.7.
- `rteth_poll_rx` self time: ring + uncached descriptor reads (about 8 single loads per frame). Cached descriptors would need per-line invalidation of a ring shared with the NIC (false sharing on the 4-byte ring entries): not done.
- `300-11` RX split per frame (before `300-12`, inflated): `dma_map_page_attrs` 10.6, `gro_receive_skb` 6.4, `page_pool_alloc_frag` 2.9, `napi_build_skb` 2.6, `__dma_sync_single_for_cpu` 2.2, `decode_tag` 1.8 µs. xmit_more batching rarely fires on forwarded traffic (58 % of packets kicked).
- None of the remaining `300-12` items is a driver-owned cost of 2 µs or more once tracer overhead is removed.

### Driver facts and open points (`rtl838x_eth`, #60)

- `NETIF_F_RXCSUM` rests on `RX_CHK_CRC_EN` = L2 CRC check only. The driver sets `CHECKSUM_UNNECESSARY` whenever `L2_ERR` = 0, so L4 checksums of locally terminated TCP/UDP are never verified.
- RX CPU tag: `L2_ERR_PKT`, `L3_ERR_PKT`, no L4-OK bit. TX CPU tag: no checksum or TSO bit. No interrupt-coalescing register (only per-ring RX_DONE / RX_RUNOUT masks); registers: [DATASHEET-AUDIT.md](DATASHEET-AUDIT.md) "CPU NIC / DMA interface".
- Threaded NAPI: not tested.
- `300-12` doorbell writes `cached | this ring's fetch bit`, i.e. 0 into the other ring's `TX_FETCH`. SDK `r9300_nicTxFetch_set` is an RMW (writes back a pending 1). Whether a written 0 cancels a pending fetch is undocumented: a risk on SMP and on UP with both rings active.
- `300-14` (parked in `openwrt/patches-parked/`, not applied; lowers throughput: [MAINLINE-PORT.md](MAINLINE-PORT.md) section 9). SMP-safe doorbell: every kick writes both fetch bits (an extra fetch of a ring with no OWN descriptor is a no-op); still one lockless `writel`.
- `300-14` module parameter `tx_cpu` (`/sys/module/rtl838x_eth/parameters/tx_cpu`, runtime): −1 (default) = `300-12` inline reclaim; N = per-ring TX NAPI on CPU N via `smp_call_function_single_async`, RX poll skips reclaim, a full ring stops the queue for the TX NAPI. Measured SMP 2026-10-12 (eth0 on CPU1): `tx_cpu=0` (TX NAPI on the other VPE) drops throughput to ~44 %; `tx_cpu=1` not measured. Idea: freeing is cache-miss heavy (~110 ns stalls), which 34Kc MT can overlap with VPE0's RX/NAT, unlike RPS; but VPE1 shares the pipeline and takes issue slots from VPE0.
- SMP race review of `300-11`/`300-12` (code reading): reclaim always under the txq lock (xmit holds it; RX poll takes `__netif_tx_lock`); BQL `completed_queue` and wake under the same lock; `napi_consume_skb(budget=1)` in xmit runs BH-disabled (OK); TX stats `unsigned long` (no tearing); RX stats under `rx_lock`. Only the doorbell needed a change.
- Generic `300-12` parts (reclaim, ring 128, kick batch) apply to RTL838x/839x/931x: build-tested only.
- SMP measurements (UP vs SMP, eth0 on CPU0 / CPU1): [MAINLINE-PORT.md](MAINLINE-PORT.md) section 9.

### On-chip SRAM on the NIC path (#103, code reading)

- Basis: `rtl838x_eth.c` + `300-11/12/20` on next-20261009. One forwarded frame = 1 RX slot + 1 TX slot + its reclaim. Counts = loads/stores the C code issues; not measured.
- SRAM: 64 KiB at bus `0x1f000000`, Linux gen_pool since `300-21` ([HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md#64-kib-sram)). Latency: `./dev.py sram-bench` (`300-22`; not run yet).
- Descriptors: `rx_data` + `tx_data` from `dmam_alloc_coherent` = uncached DDR (KSEG1). 2 RX + 2 TX rings x (128 ring words x 4 B + 128 frags x 32 B) = 18 KiB: fits.

Uncached DDR accesses per forwarded frame:

- RX `rteth_hw_receive`: ring word, `frag->len`, `frag->more`, `len` again in `rteth_create_skb`, `cpu_tag[0,1,2,7]` in `decode_tag`: 8 R. `frag->dma`, ring word: 2 W.
- TX `rteth_start_xmit`: ring word 1 R. `frag->len`, `frag->dma`, 10 halfword `cpu_tag` stores (`rtl930x_nic_tx_tag`), ring word: 13 W.
- TX reclaim: ring word, `frag.dma`: 2 R.
- Total: ~11 R (each a full DDR round trip, CPU stalled), ~15 W (write buffer).
- Barriers: `rmb` + `dma_wmb` per RX slot, `dma_wmb` + `wmb` per TX frame = 4 `sync` per frame; each drains the queued uncached writes.

Not movable to SRAM:

- MMIO (SoC registers): `rx_release` 1 W per NAPI poll; `enable_rx_irq` 2 RMW at poll end; `confirm_disable_irqs` 2 R + 2 RMW + 2 W per IRQ; doorbell 1 W per <= 16 TX frames. Estimate < 0.2 accesses per frame at budget 64.
- Cache maintenance on DDR packet buffers (RX pool 2 x 128 x 2 KiB = 512 KiB):
  - RX: `PP_FLAG_DMA_SYNC_DEV`, `max_len` 4 KiB: one 4 KiB invalidate per recycled page (2 frames) = ~64 line ops per frame. `sync_for_cpu` is a no-op on the 34Kc (`cpu_needs_post_dma_flush` false).
  - TX: `dma_map_single` writeback of the frame: len / 32 lines (64 B: 3, 1514 B: 48).

SRAM candidates:

- (a) NIC DMA reaches SRAM: rings + frags (18 KiB) from the gen_pool, ring base = pool phys. All ~11 R + ~15 W per frame move to SRAM; gain = 11 x (DDR - SRAM `uc_rd`) + faster write drain at the 4 `sync`s.
- (b) NIC DMA does not reach SRAM: CPU-only data through the cached alias (`CKSEG0ADDR`); only L1 misses get faster (gain per miss = DDR - SRAM `c_miss`). Descriptors stay in DDR.
  - Flowtable rhashtable buckets + `flow_offload` entries of the hot flows.
  - Conntrack hash bucket heads: default table > 64 KiB, needs a sized-down table.
  - FIB trie nodes + neighbour entries of the few routes.
  - Driver bookkeeping `rx_info.page[]/offset[]`, `tx_info.skb[]` (3 KiB): usually L1-resident, low value.
- NIC DMA reach (#103 plan step 4) decides (a); `sram-bench` `uc_rd` / `c_miss` sets the gain of each.

## Clocks x on-chip SRAM matrix (sw2, 2026-10-13T12:05-12:15+11:00, `./dev.py nat-matrix --perf`)

Conditions: mainline next-20261009 initramfs, SMP, NAT + flowtable, rx-gro-list on, one nic-bench run per cell. Base = `clocks fast` (CPU 1000, DDR 650, LX 175, SRAM 250); picks = + `turbo cpu=1375,ddr=662,lx=306,sram=500`. SRAM off = kernel built `--skip 300-21` (OpenWrt default); mapped = `300-21`, pool unused. Rows: `tmp/logs/nat_bench.jsonl`, tags `nat-<cell>`.

| Test | off / base | off / picks | mapped / base | mapped / picks |
|---|---|---|---|---|
| TCP P4 (Mbit/s) | 350 | 435 | 348 | 444 |
| UDP 1400 B, 900 offered: fwd kpps / loss | 65.9 / 13.6 % | 76.3 / 0.2 % | 64.6 / 15.3 % | 74.9 / 2.9 % |
| UDP 64 B fwd (kpps) | 73.4 | 94.2 | 72.8 | 94.5 |
| VPE-ns per packet, UDP 64 B | 13092 | 10170 | 13183 | 10120 |

- Picks vs base: TCP +25 %, UDP 64 B +28 %, overload loss at 900 Mbit/s gone. Mapped-but-unused SRAM: no change (within run-to-run spread).
- Rings in SRAM (`300-25`, `rtl838x_eth.sram_rings`): **NIC descriptor DMA does not work from SRAM**. RX-only (bit 0) and TX-only (bit 1) both: link up, no traffic (eth0 RX 2 frames, 1 error). Frame buffers in SRAM do work (U-Boot `uboot-test net --ethsram`: TX buffers + 16 RX buffers in SRAM, TFTP/wget CRC match). So candidate (a) above is out for descriptors; packet buffers in SRAM remain possible (64 KiB: ~30 buffers).
- Profile at mapped/picks, UDP 64 B, `perf record -e cpu-clock -a` 5 s (static perf, `./dev.py build-perf` / `nat-perf`; the 34K PMU overflow IRQ gives no samples, `perf stat` hardware counters read garbage). Shares of the busy VPE (VPE1 idle, 50 % of samples):
  - Driver (`rteth_poll_rx`, `rteth_start_xmit`, `rteth_930x_decode_tag`, `rteth_reclaim_tx_ring`): 14 %. The uncached descriptor accesses are inside these.
  - Cache maintenance (`r4k_dma_cache_inv`, `r4k_dma_cache_wback_inv`, `dma_unmap_phys`): 5 %.
  - GRO/GSO round trip (`dev_gro_receive`, `gro_receive_skb`, `udp_gro_receive`, `inet_gro_receive`, `__udpv4_gso_segment_csum`, `inet_gso_segment`, `__udp_gso_segment`): 16 %.
  - Hashing (`__siphash_aligned`, `__skb_flow_dissect`): 11 %. `__bzero` (skb init): 3 %.
  - One VPE does all NAPI work; the second VPE is idle.
- ASIC drop reasons during nic-bench (`drop-counters`, base clocks, 2026-10-13T12:23): only `EGR_QUEUE` (CPU-port egress queue): TCP P4 1640, UDP 64 B 32873 of ~1.2 M lost frames. Most UDP 64 B loss is past the ASIC (NIC RX ring / CPU), not in the switch.

## Runtime tunables at the picks (sw2, 2026-10-13T18:36-18:50+11:00)

Conditions: mainline next-20261009 initramfs, SMP, picks (`turbo cpu=1350,ddr=662,lx=306,sram=500`), NAT + flowtable, `nic-bench run --runs 1`, storm control with unknown-unicast off (#111). Rows: `tmp/logs/nat_bench.jsonl`, tags `picks-*`. Cells: eth0 RX.

| Change (one at a time) | TCP P4 Mbit/s | UDP 64 B kpps |
|---|---|---|
| baseline (`picks-uc0`) | 431 | 90.1 |
| **XPS: both CPUs on eth0 tx-0** (`picks-xps0`, recheck) | **502-504** | **100.9-103.5** |
| XPS-0 + RPS lan1 -> VPE1 | 347 | 93.0 |
| XPS-0 + threaded NAPI | 440 | 98.1 |
| XPS-0 + rx-gro-list off | 300 | 64.4 |
| XPS-0 + GRO off | 485 | 65.4 |
| **`300-27` (driver `ndo_select_queue`, no XPS map), 3 runs** (`picks-300-27`) | **521-528** | **105.6-108.9** |
| **+ `300-28` (RX descriptor read through the cache), 3 runs** (`picks-300-28`) | **514-533** | **109.6-111.2** |

- `300-27` makes XPS-0 permanent in the driver: control-priority frames on ring 1, the rest on ring 0, no hash. UDP 1400 B at 900 offered stays 76.5 kpps (line-limited, 0.1 % loss).
- `300-28`: each RX descriptor is one 32 B line written only by the NIC; one invalidate + cached read replaces ~8 uncached DDR loads per frame. UDP 64 B +3 %, TCP within spread; no RX errors.
- XPS-0: eth0 has 2 TX queues; without an XPS map every packet goes through `skb_tx_hash` (flow dissect + siphash) to pick one. The 11 % "hashing" in the profile above was this, not a qdisc (default qdisc is `pfifo_fast`; DSA ports and SVIs are `noqueue`).
- RPS and threaded NAPI stay worse: both VPEs share one 34Kc pipeline, so moving work to VPE1 adds IPI/cache cost without compute.
- GRO + fraglist GRO stay on: off costs 30-40 %.
- Storm control at the old default (unknown-unicast 20000 pps) capped NAT at ~19 kpps (`STORM_CONTROL` drops; routed traffic to the switch's own MAC counts as unknown unicast): default now off (#111).

## Mainline with today's series (sw2, 2026-10-15T08:17-08:45+11:00)

Conditions: mainline next-20261009 + series through 300-35 (`awto/st1008f/next-20261009`), initramfs, picks (`turbo cpu=1350,ddr=662,lx=306,sram=500`), NAT + flowtable, `./dev.py nic-bench run --runs 1`. Rows: `tmp/logs/nat_bench.jsonl`.

| Tag | TCP P4 Mbit/s | UDP 1400 B @900 kpps (loss) | UDP 64 B kpps |
|---|---|---|---|
| `picks-300-28` (2026-10-13, 3 runs) | 501-522 | 76.2-76.5 (0.0-0.1 %) | 109.6-111.2 |
| `mainline-20261015` | 528 | 76.5 (0.1 %) | 110.8 |
| `pt-loop-off` (300-26 handlers unregistered) | 534 | - | 111.1 |
| `qdisc-noqueue` (eth0 `noqueue` instead of `mq`/`pfifo_fast`) | 544 | 75.8 (1.2 %) | 113.1 |
| `udp-gro-fwd` (`rx-udp-gro-forwarding on` on eth0, lan1, lan1.99x) | 528 | 71.4 (4.4 %) | 109.9 |

- Today's patches (300-29 .. 300-35) cost nothing on the forwarding path.
- 300-26 loop-probe handler (`ETH_P_ALL` on every user port): +1 % TCP when removed, within spread; now registered only while loop detection is on.
- eth0 `noqueue`: -4 % CPU per packet on TCP (14,642 -> 14,055 ns), +1.5 % UDP 64 B, but UDP overload loss 0.1 -> 1.2 % (no queue behind a full TX ring). Not made the default.
- Batching ("many packets at once") already in place: NAPI polls up to 64 frames per IRQ (~6 IRQ/s under UDP 64 B: pure polling); TCP fraglist GRO merges ~40 packets so the stack + flowtable run once per merged skb; TX `xmit_more` + one doorbell per <= 16 frames (300-12, < 0.2 MMIO per frame).
- UDP GRO for forwarding (`rx-udp-gro-forwarding`) made UDP worse (1400 B @700 offered 0.0 -> 1.7 % loss, @900 76.5 -> 71.4 kpps, 4.4 % loss; 64 B unchanged): a merged UDP skb is split again before TX, the per-packet driver cost stays, and holding packets for merging makes TX burstier. Off (kernel default).
- What stays per packet: descriptor + DMA map/unmap + cache maintenance (~6 %), CPU tag, TX-ring reclaim. The NIC has no interrupt-coalescing register and no checksum/TSO bits in the TX CPU tag (see 'Driver facts'), so the hardware gives no batching beyond the rings.

Call graph, TCP NAT, VPE0 (`./dev.py nat-perf --test tcp-P4 --callgraph`, inclusive %):
- `rteth_poll_rx` (driver RX) 26.4; `gro_cell_poll` (second GRO pass, DSA user port) 68.6; `dev_gro_receive` 40.3.
- `nf_flow_offload_ip_hook` 47.8, of which the lookup 6.6 and `nf_flow_queue_xmit` 36.0 -> `__dev_queue_xmit` 33.1 -> `dsa_user_xmit` 21.5 -> `sch_direct_xmit` 14.7 -> `rteth_start_xmit` 11.0.
- `rteth_reclaim_tx_ring` 8.7 (TX completion freed inside each xmit); `validate_xmit_skb` 8.7 (incl. GSO of GRO'd packets).
- Flat self-time profile (top: `rteth_start_xmit` 4.9-5.8, `dev_gro_receive` 4.8-5.0, `rteth_poll_rx` 4.1-4.2): no single hotspot.

## OpenWrt on 7.3 (main b455c5b, next-20261009), IPv4 and IPv6 NAT (sw2, 2026-11-06T08:05-08:08+11:00)

`ramload openwrt-ours`, fw4 loaded, one 10G SR in cage 1, nat-bench one-armed, TCP `-P 4`, 15 s, one run each; ASIC offload parameters all 0; destination only the default route reaches (`--dst 198.51.100.5` / `2001:db8:22::5`), so every packet takes the CPU path.

| Mode | v4 fwd / rev Mbit/s | v6 Mbit/s | CPU0 |
|---|---|---|---|
| masquerade | 77.7 / 76.8 | 72.7 | 97-100 % |
| masquerade + software flowtable | 203.2 / 203.6 | 205.3 | 97-100 % |

- Translation checked in conntrack: v4 source `10.99.1.2` -> `10.99.2.1`; v6 source `fd99:11::5` -> reply to `fd99:2::1`. Flowtable runs show conntrack `OFFLOAD` entries.
- Gateway-routed far `/64` / far `/24` traffic never meets the masquerade rule: the ASIC forwards it (9.2 Gbit/s, #66). NAT is only exercised via the default route.
- Image: nf_tables kmods are in the image; the kernel release (`7.3-next-...`) differs from the kmod directory (`7.3`), fixed by a link in the image (`build_openwrt.py` `modules_link`).

## Combinations (2026-11-06, `./dev.py nat-knobs`)

Live switches, no rebuild: [NAT-OPS.md](NAT-OPS.md) "Knobs". OpenWrt 7.3 b455c5b, stock clocks (CPU 800, `ramload openwrt-ours` boots from stock U-Boot), sw2 RAM boot, NAT + flowtable, default route destination, TCP `-P 4` 10 s, one run per cell (spread about +-3 %). Rows: `tmp/logs/nat_knobs.jsonl`.

Each idea alone against the default (283-294):

| Knob (non-default state) | Mbit/s change | Note |
|---|---|---|
| eth0 qdisc `noqueue` | +12 to +15 % | overload loss was 1.2 % (2026-10-15) |
| fraglist GRO off | -29 % | now on by default |
| RPS to VPE1 | -31 % | |
| threaded NAPI | -9 % | |
| flowtable off | -74 % | |
| IRQ on VPE1 | +1 % | work moves wholesale, VPE1 95 % |
| conntrack accounting off, UDP GRO forwarding, NAPI budget x2 | +1 to +2 % | within spread |
| IRQ coalescing emulation (`napi_defer_hard_irqs`) | -2 % | |
| threaded NAPI, kthreads pinned one per ring | +2 % | |
| TX ring follows the CPU (`tx_by_cpu`) | 0 % | |

Combinations (default 283):

| Combination | Mbit/s | Change | CPU0 / CPU1 |
|---|---|---|---|
| pinned NAPI + `tx_by_cpu` | 320 | +13 % | 92 / 95 |
| pinned NAPI + `tx_by_cpu` + `noqueue` | **370** | **+31 %** | 94 / 95 |
| `tx_by_cpu` + RPS | 193 | -32 % | |
| same best, but all frames on ring 0 (one VPE) | 344 | +21 % | 2 / 96 |

On the best combination (369), one more knob at a time: NAPI defer +3 %, UDP GRO forwarding +2 %, conntrack accounting off +2 %, NAPI budget +1 %, firewall off 0 %, IRQ on VPE1 -11 %, fraglist GRO off -41 %. UDP 64 B: 59 kpps vs 53 (+11 %).

- Ideas that lost alone stack: pinned threads gain nothing until the two rings stop sharing a TX ring lock (a spinning VPE takes pipeline slots from its sibling), and `noqueue` removes the qdisc lock; together +31 %.
- The second VPE itself adds 7 % (344 to 369) here. Most of the gain is the lock and queue work, which also helps on one VPE.
- The split is by direction: the return stream (host-route reason) is ring 1, about one third of the frames; VPE1 does that. A split by flow would balance better (not tried).
- Not safe as an image default yet: with `tx_by_cpu` a ring is reclaimed only by its own CPU's NAPI, so skbs of local sockets sent from an idle CPU can wait. Fix first (reclaim at xmit).
- Not tried in combination: SRAM packet buffers, `300-14` doorbell, picks clocks, `rx-gro-list` variants on `switch.*`, per-flow ring split (PIE ACL hit -> ring via `QM_FLAG2CPUQID`).

## In-place forward prototype, no skb (2026-11-06, `300-39`, #148 #140)

OpenWrt 7.3, CPU 1350 / DDR 662 / LX 306 / SRAM 500, sw2 RAM boot. One UDP flow natlan -> natwan routed through the switch CPU path (no NAT, no flowtable); `scripts/zc_bench.py`. Receiver truth = `rx_packets` of the natwan interface (equal to the driver's forward count, no loss between). `zc=1`: the frame is rewritten in its RX buffer (DMAC, SMAC, VLAN id, TTL-1 + incremental IP checksum) and sent from the same buffer; no skb, GRO, netfilter or qdisc; the page returns to the pool when the TX completes. DDR buffers, one hard-coded flow, UDP only.

| Frame | Stack path | In place | Ratio | CPU0 |
|---|---|---|---|---|
| 1400 B payload (1446 B frame) | 21.8 kpps (252 Mbit/s) | 143.3 kpps (1658 Mbit/s on the wire) | 6.6x | 94 % both |
| 64 B payload | 22.7 kpps | 490.7 kpps | 21.6x | 94-96 % |

- Per packet: about 44 µs through the stack, 2 µs in place (64 B), 6.6 µs (1400 B).
- The 1400 B rate is not set by per-packet CPU cost: the NIC / CPU port moves 1.66 Gbit/s each way (RX + TX 3.3 Gbit/s total), so the CPU port is not a 1 Gbit/s cap.
- TX length: the NIC takes frame + 4 bytes of FCS room (`frag->len` = RX length); trimming the 4 bytes sent truncated frames that the receiver dropped (found by comparing the stack's TX frame with ours: `zc_dbg`).
- Source NAT of the flow (`zc_sip`, `zc_sport_add`; same run, plain UDP sender `scripts/tools/udpblast.c`, 4 flows, 1400 B): source 10.99.1.2:40000 -> 10.99.2.1:41000 on the wire, TTL 63, `[udp sum ok]` (tcpdump verifies the incrementally updated IP and UDP checksums), rate unchanged: 143.6 kpps (1661 Mbit/s). The stack path under the same flood: 9.2 kpps (15.6x). iperf3 cannot be the generator for NAT'd UDP (its server connects to the first source it sees).
- TCP, both directions, stateless static 1:1 NAT (client 10.99.1.2 <-> 10.99.2.1, port + 1000; forward rewrites the source, reverse rewrites the destination back, own MAC and VLAN; SYN, FIN, ACKs and iperf3's control connection all go through the in-place path; TCP and IP checksums incremental): iperf3 TCP P4, 10 s, one run each:

| Direction | Stack path (route only, no NAT, no flowtable) | In place with NAT | Ratio |
|---|---|---|---|
| client -> server | 114.7 Mbit/s | **1339.6 Mbit/s** | 11.7x |
| server -> client (`--reverse`) | 129.1 Mbit/s | **1309.8 Mbit/s** | 10.1x |

- The stack saw 10-15 pps in the in-place runs (misses only). For reference the best stack path at the same clocks (NAT + flowtable + best knob combination) is 507 Mbit/s: in place is 2.6x that, 54 % of the 2.5 Gbit/s target.
- **Real NAT, flow table fed by the kernel** (same boot and clocks): nftables masquerade + conntrack in the stack, flowtable with `flags offload` (`nat-bench mode nat-hw`). DSA hands the flowtable's `TC_SETUP_FT` to the NIC driver; each established connection becomes two entries (match = the packet's 5-tuple as it arrives, action = Ethernet addresses, NAT address and port, VLAN pop/push, egress port; incremental IP/TCP/UDP checksums); stats go back to the flowtable so timeouts refresh; new flows, SYN/FIN handling, conntrack and expiry stay in the stack. iperf3 TCP P4, 10 s, one run each:

| Direction | Stack + software flowtable (hw flag set, fast path off) | Fast path with the flowtable's flows |
|---|---|---|
| client -> server | 420 Mbit/s | **1250 Mbit/s** (16049 retransmits) |
| server -> client (`--reverse`) | - | **1187 Mbit/s** (10720 retransmits) |

- The stack saw 33-66 pps during the fast-path runs; `zc_flows` 10 per run (4 data + 1 control connection, 2 directions). 2.5x the best software-NAT result (507 Mbit/s with the best knob combination), 50 % of the 2.5 Gbit/s target.
- Retransmits (1.35 % of the segments in one 10 s run: 17.5k of 1.29 M, sender side) are ASIC egress-queue drops: `EGR_QUEUE` +20692 = `dot1dTpPortInDiscards` +20693 during the run, lan1 `ifOutDiscards` 0, `zc_busy` 0. The host sends at 10G line rate, the one-CPU fast path forwards about 100-140 kpps, so the queue toward the CPU overflows and TCP backs off: congestion at saturation (CPU0 92 %), not an error in the fast path.
- Second CPU (`zc_bench.py --nat --napi split`, picks clocks, 2026-11-06, UDP 1400 B NAT): fast-path ring thread on VPE1 -> 132.9 kpps (1537 Mbit/s), busy VPE0/VPE1 42/79 %, `zc_busy` 76k (TX ring of 32 full). Fast path on VPE0 (other thread on VPE1) -> 143.7 kpps, VPE0 99 %, `zc_busy` 24k. Moving the thread does not raise the rate and VPE1 is not saturated: the ceiling is the 32-entry TX ring / TX completion, not CPU. Next: bigger TX ring (#148).
- Re-test, no thread (`--napi irq1`: NIC IRQ + softirq poll on VPE1, 2026-11-06, picks clocks, UDP 1400 B NAT): 145 kpps, VPE1 99 %, VPE0 7 %, `zc_busy` 12k. The TX ring is already 128 entries (300-12); the rate is one CPU at ~6.9 us per packet. Thread scheduling costs a few percent (thread mode 133 kpps, thread 79 % busy), it is not the limit.
- CPU port speed field (`MAC_FORCE_MODE_CTRL(28)`, phys `0x1b00ca8c`, reads `0x217` = SPD_SEL 1G; `devmem` takes the physical address; SPD_SEL 4 = 10G, 5 = 2.5G, 6 = 5G): `scripts/cpuport_speed_ab.py` (2026-11-06) writing `0x227` (10G), `0x22F` (2.5G) or `0x237` (5G) alone leaves sw2 unreachable (ping dead, SSH rides the CPU port); restore `0x217` via the console brings it back (a reload only after a long hang). No rate was measured at any other setting. The DS has no CPU-port speed figure; the only measurement is 1.66 Gbit/s each way at the 1G label. Open: whether port 28 needs more than SPD_SEL (e.g. `MAC_L2_CPU_PORT_CTRL`, MAC mode) to run faster (#148).
  - Search 2026-11-06: no public document or driver sets a CPU-port speed above 1G on this family. OpenWrt and its forks carry the same driver (CPU port row `0xCA1C + 28*4`, only the max-length row is programmed). Reverse-engineered map (svanheule.net longan): `MAC_FORCE_MODE_CTRL` ports 0-28 incl. CPU, no CPU-specific speed field; `MAC_L2_CPU_PORT_CTRL` `0xC70C` picks internal port 28 or external port 27 (the 10G external-CPU option); `QM_CPUQID2XGQID_CTRL` `0xA334` (16 XG queues) next to `QM_CPUQID2QID_CTRL`; `SCHED_CPU_Q_CTRL[32]` `0x7F44` (STRICT_EN, WEIGHT). Realtek SDK (DMS-1250 drop) never writes the CPU port's force/speed (its port loops skip the CPU port); it only writes the CPU max-length row, 'ASIC auto uses the field for the port speed'. Not found: any measurement of the internal NIC rate. Web search through the awto-play CLI (`awto-play/playwrong --search`, 2026-11-06): OpenWrt forum threads for the RTL9303 boards (NicGiga S100-0800S-M, a close cousin with a DTS derived from ours; XikeStor SKS8300-8X) and the OpenWrt Realtek DeepWiki pages say nothing about the CPU port rate; only 'flow offloading reaches line rate' (ASIC offload, not the CPU path).
- `nf_flow_table_offload.c` builds the 16-bit Ethernet address pieces (`mask = ~0xffff0000`, `val = val16 [<< 16]`) from host-order constants: byte-correct on little-endian only. On this big-endian MIPS the 12 address bytes arrive rotated; the driver decodes the four Ethernet entries by numeric value for both byte orders. The IP and port entries use `htonl()` and are fine. Worth reporting upstream (#85 strategy).
- Not done: SRAM buffers (#148), the other VPE, IPv6, ICMP errors and fragments (stay in the stack), more than 2048 flows, a soak.

## Memory path and the second VPE (2026-11-06, `scripts/mt_interference.py`)

Question (owner): do the VPEs lose to each other through memory bandwidth, and can one VPE use a small private memory? Forwarding confined to VPE1 (344-347 Mbit/s: threaded NAPI pinned, one ring, `tx_by_cpu`, `noqueue`); a synthetic probe (`openwrt/selftest/st1008f-mtprobe.c`) on VPE0, 18 s, one run each, OpenWrt 7.3 b455c5b, stock clocks (CPU 800), sw2 RAM boot.

| Probe on VPE0 | Forwarding Mbit/s | Change | Probe rate vs alone |
|---|---|---|---|
| none | 344-347 | - | - |
| spin (ALU only, no memory) | 255 | -26 % | 71 % |
| small (8 KiB, L1 resident) | 240 | -30 % | 69 % |
| sram (64 KiB on-chip, uncached reads) | 293 | -16 % | 85 % (90 ns / load, alone) |
| chase (8 MiB, one DRAM miss at a time) | 226 | -34 % | 79-80 % (215 ns / load, alone) |
| stream (4 MiB copies, 130 MB/s alone) | **86** | **-75 %** | 90 % |

- Pipeline sharing works as designed: forwarding keeps 74 % while the sibling keeps 71 %, 1.45x the work of one thread.
- Memory is the shared bottleneck, not the pipeline: a DRAM-latency neighbour costs 19 points more than an on-chip-SRAM neighbour, and a streaming neighbour (130 MB/s, about 1 % of DDR3 peak) removes 75 %. Misses queue behind each other: with no L2, effectively one miss in flight.
- This matches the best combination (two VPEs forwarding: 369 vs 344 on one, +7 %): both VPEs wait on the same miss queue.
- L1 capacity (32 KB, 4-way, 32 B lines, shared by both VPEs): the sibling's L1-resident working set against forwarding on the other VPE, spin = 258 Mbit/s (no memory) as the reference:

| Sibling working set | Forwarding Mbit/s | Change vs alone (346) |
|---|---|---|
| 8 KB | 242 | -30 % |
| 16 KB | 217 | -37 % |
| 28 KB (most of the L1) | 200 | -42 % |

  - Taking most of the L1 costs 17 points beyond the pipeline share (spin -25 %): the forwarding working set is small (descriptors, headers, `skb` heads, flow entries: a few KB per packet batch). A smaller cache would lose, not gain; capacity is not the limit, the miss latency is.
  - Cache maintenance (`dma` invalidate / write-back) is 5 % of the profile: syncing only the bytes a frame used (page-pool recycle syncs 4 KiB per 2 frames today) is the available part of "cache sized to the packet".
- Cache size per VPE is not configurable: the 34Kc VPEs share one core and one pair of L1 caches. Cache locking (`CACHE` fetch-and-lock) could reserve lines for hot data; not tried.
- On-chip SRAM is the only memory off the DDR queue (90 ns uncached reads, no DDR traffic). Descriptors cannot live there (NIC DMA fails, #103). Packet buffers can, but are not `struct page` memory: 64 KiB is about 30 buffers.
- Probe caveats: `chase` over 8 MiB also takes TLB refills (4 KiB pages); `sram` is uncached (the cached alias is not reachable from user space); one run per cell.
- Next ideas, none tried: fewer DDR misses per packet (software prefetch of the next descriptor and headers in the RX loop, trimming per-packet touched lines); small-frame RX (ACKs) copied into an SRAM-backed buffer; cache-locked hot tables; keep memory-heavy daemons (collectd, logging) off the forwarding path.

## The second CPU

- Hardware: MIPS 34Kc with 2 VPEs = two hardware threads on one pipeline and one L1. It is not two cores. The gain is filling stall cycles (a miss costs about 109 ns), not 2x.
- Today VPE1 does no forwarding work:
  - eth0 has one IRQ; both RX rings' NAPI run on the CPU that takes it (VPE0).
  - RX ring = RX reason parity (`rteth_setup_cpu_rx_rings`). All forwarded traffic has one reason, so ring 1 is idle.
  - The XPS and `300-27` gain was removing the TX hash, not using VPE1 (forwarding transmits inside the RX softirq).
- Why the attempts lost: each handed single packets across VPEs (IPI per packet, a second GRO pass, ring locks). RPS 0.56x; `tx_cpu` 0.44x. Pinned per-ring NAPI with one TX ring per CPU works (see Combinations).
- Done 2026-11-06 with the existing ring map (`/sys/kernel/debug/rteth/rxq`, `300-38`). Not yet tried: a split by flow with no per-packet cross-VPE traffic.
  - The ASIC steers frames to a CPU ring by PIE action CPU QID (DS section 7.13.1; `ACT_MSK_QID`, not implemented in `tc.c`/`pie.c`).
  - Match L4 port parity (or ingress port) in the PIE: half the flows to ring 1.
  - NAPI of ring 1 on VPE1 (one IPI per poll, or a threaded NAPI pinned to VPE1); each VPE then does RX, GRO, flowtable and TX for its own flows.
  - Unknown until measured: whether QID applies to frames that reach the CPU by an L3 route trap, and the real MT gain (RPS suggests small).
- Open as a plan: #60.

## Hybrid NAT (#63)

- Not started. PIE matches the flow, the CPU rewrites, the ASIC routes the re-injected frame.
- Saves the egress stack only. The NIC RX + TX driver floor (about 10 µs per packet at picks, UDP 64 B) stays, so it cannot reach 2.5 Gbit/s alone.
- First experiment: does a CPU-transmitted frame with `FWD_ALE` + `L3_ACT` get an L3 route lookup ([NAT-HISTORY.md](NAT-HISTORY.md) hybrid section).

## Hybrid NAT: CPU rewrite + ASIC forward (#63)

Idea (owner research chat 2026-10-09..11): PIE matches the flow, the CPU rewrites IP/port (RFC 1624 incremental checksum), the ASIC routes the re-injected frame.

- Pieces: PIE 5-tuple match (have); header substitution (none in the ASIC, #58, #68); checksum fix after substitution (none); L3 next hop + MAC rewrite + TTL (have, DS §7.14). DNAT needs the route lookup on the translated address or a PIE next-hop override.
- Parser fields: `LONGAN_HSB_SIP/DIP/SPORT/DPORT`, `IP_PROTOCOL`, `TCP_FLAG`, `IPV4_CHKSUM_OK`. HSB/HSA = header state before/after the pipeline (diagnostic snapshots, not a rewrite engine).
- ACL `fwd_cpu_fmt` (`LONGAN_VACL_FWD_CPU_PKT_FMT`, IACL analogue): ORIGINAL 0 / MODIFIED 1 / NOP 2 = copy to CPU before or after the hardware modification. Same choice globally in `DMA_IF_PKT_CTRL` 0xCE00 `FWD/TRAP_PKT_FMT`.
- `ACL_ACTION_FWD_LOOPBACK` = IACL forwarding action 7 (internal loopback; which stages a looped frame re-enters: unknown).
- NIC DMA: ring entry (`OWN_HW` bit 0, `WRAP` bit 1) points to a packet descriptor (`struct rteth_frag`: buffer, size, `more`, offset, len, `cpu_tag[10]`).
- TX CPU-tag forwarding modes: FWD_ALE 0, PHYSICAL 1, LOGICAL 2, TRUNK 3, ONE_HOP 4, LOGICAL_ONE_HOP 5. The driver uses FWD_PHYSICAL with `L3_ACT` = 0.
- `L3_ACT` = 1 (SDK `nic_common.h:267`): "take effect of L3 routing and multicast replication" for CPU-TX frames. Whether FWD_ALE + `L3_ACT` runs a full L3 lookup: untested.
- Not present: TX IPv4/L4 checksum generation, TSO, L4 checksum validate (#68: HSA `CTX_*` fields mirror the TX CPU tag, no checksum field).
- Prior art elsewhere: NVIDIA Spectrum-2/3 (mlxsw ACL `pedit` IP/port rewrite in the ASIC), ConnectX-5 (tc flower + pedit + csum + ct), Realtek RTL8198 (gateway SoC hardware NAT; RTL8196C none). No RTL9303 implementation found.
- Gateway SoCs (RTL8198C/8197F) carry NAT in the next-hop table (`IPIndex` -> ext/int IP table); Longan `L3_NEXTHOP` has only `DMAC_IDX` + `L3_EGR_INTF_IDX`.
- Managed sisters (TL-ST5008F, SX3008F): no NAT advertised; VLAN translation is not IP rewrite.
- GRO/GSO help per-skb cost on bulk TCP; NAT never merges independent packets into bigger frames.
- Experiments still open (low value until the driver is faster): FWD_PHYSICAL vs FWD_ALE + `L3_ACT` (does an L3 route apply?); inject bad IPv4/TCP checksums (repaired?); ACL trap with `fwd_cpu_fmt` = MODIFIED; whether FWD_ALE lets the CPU skip bridge/DSA tagging.

## Strategy (#65, owner 2026-10-11)

- ISP: NBN HFC, ~2000/100 Mbit/s profile, 2.5GbE handoff.
- Ranked:
  1. IPv6-first: DHCPv6-PD on the WAN, RA per LAN VLAN, v6 routed in the ASIC (`2000::/3` workaround or `300-17` `l3_default_v6`; downstream needs `l3_onlink`, #59).
  2. IPv4 NAT on the CPU with the software flowtable (fw4 `flow_offloading=1`: 3-4x over no flowtable). IPoE preferred over PPPoE (PPPoE adds per-packet work; not measured).
  3. NIC driver work in the 7.3 port (#60: `300-11`, `300-12`; `300-14` parked), profiled first.
  4. Everything else off the CPU: inter-VLAN routing in the ASIC (#59), ACL drop of unwanted WAN ingress, PIE `UNICAST_ROUTING` for policy routing, NAT and control traffic (ARP/STP/ND) on different CPU queues (`QM_RSN2CPUQID` / PIE CPU-QID).
  5. CPU-port SPD_SEL 10G/2.5G A/B once the CPU path nears 1 Gbit/s.
- Not pursued: RPS onto VPE1 (measured worse on 6.18); hybrid re-injection as a route to 2.5G.
- 2 Gbit/s IPv4 today: NAT on another box (house router or an x86/ARM router with 2.5G/10G) with this switch routing in the ASIC and IPv6 native; or accept ~350 Mbit/s IPv4 NAT here.
- Open owner inputs: native IPv6 + DHCPv6-PD from the RSP; IPv4 by IPoE or PPPoE; where IPv4 NAT lives.
- Kernel NAT path review (#71): knob matrix, clocks x SRAM matrix, perf profile and rteth call graph done; open: per-function conntrack / nf_nat / flowtable cost (ftrace `function_graph`) and conntrack sysctl A/B.

## IPv6 fast path (how most traffic avoids NAT)

- Clients prefer IPv6 when they hold a global address: RFC 6724 source/destination selection plus Happy Eyeballs (RFC 8305).
- The box needs: a DHCPv6-PD prefix from the ISP on the WAN, RA (plus optional DHCPv6) per LAN VLAN, and the v6 routes offloaded.
- Offload requirements, both from #59:
  - Upstream: `::/0` is not offloaded, so install `2000::/3 via <ISP gw>` (verified here).
  - Downstream: LAN clients are on-link, so the trap path applies (58.5 Mbit/s here) without on-link neighbour host routes. This is the blocker for v6 at line rate in a real topology; `300-17` `l3_onlink` adds them (mainline 7.3 port, not yet measured: [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md), #59).
- Major content (video, CDNs, big clouds) is mostly v6-capable. What fraction of the household's traffic is v6: not measured.

## Related

- #58 no NAT in the ASIC.
- #59 offload gaps.
- #60 NIC driver.
- #63 hybrid NAT.
- #66 ASIC-routed traffic bypasses nftables ([ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md)).
- #71 kernel NAT path review.
- #68 no hidden/disabled rewrite hardware in the die ([HIDDEN-FEATURES.md](HIDDEN-FEATURES.md)).
- #22 all-port test.
- [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md).

## NAT-PROGRESS header and snapshot (2026-11-06)

Metric: TCP `-P 4`, NAT or route + nftables software flowtable, one-armed over lan1, CPU path only. UDP 64 B = forwarded kpps.

## Where we are (2026-11-06)

| Image / boot | Clocks | TCP Mbit/s | UDP 64 B kpps | Note |
|---|---|---|---|---|
| mainline initramfs, series to 300-35 (best) | picks | 514-544 | 110-113 | 2026-10-13..15 |
| mainline initramfs | base | 350 | 73 | 2026-10-13 |
| OpenWrt 7.3, best knob combination | **picks 1350** | **507** | 88 | 2026-11-06, see "Combinations" |
| OpenWrt 7.3, `noqueue` only | picks 1350 | 467 | 90 | |
| OpenWrt 7.3, image defaults | picks 1350 | 388 | 76 | |
| OpenWrt 7.3, best knob combination | stock 800 | 369-377 | 59 | |
| OpenWrt 7.3, image defaults | stock 800 | 283-294 | 53 | fraglist GRO now on at boot |
| OpenWrt 7.3, fraglist GRO off (old image) | stock 800 | 195-203 | - | |
| OpenWrt 7.3, masquerade, no flowtable | stock 800 | 78 | - | v6 NAT 73 |

- Clocks: stock = CPU 800 / DDR 600; base = CPU 1000 / DDR 650 (`clocks fast`); picks = CPU 1350-1375 / DDR 662 / LX 306 / SRAM 500 (1350 for OpenWrt runs; 1375 had 1 wrong decode in 55 under load, #109).
- Best is 20 % of the target (507 of 2500). IPv6 needs no NAT: 9.1 Gbit/s in the ASIC.
- No OpenWrt-vs-initramfs gap: 283-294 at 800 MHz vs 350 at 1000 MHz is the clock ratio (0.8); the old low OpenWrt numbers were fraglist GRO off. The firewall ruleset costs nothing with the flowtable on (376 vs 377).
- OpenWrt at picks: CPU 1350 / DDR 662 / LX 306 / SRAM 500 via `ramload uboot-mainline --then openwrt-ours --pre "turbo cpu=1350,ddr=662,lx=306,sram=500"`. Not the default: the flash chain runs stock clocks unless the M3 turbo profile is set (#109).
- Only with the best combination do both VPEs work: VPE0 94 %, VPE1 95 %. Every other run: VPE1 1-4 %.

## Ledger (TCP P4, NAT + flowtable unless noted)

| Date | Change | TCP Mbit/s | UDP 64 B kpps | Where |
|---|---|---|---|---|
| 2026-10-11 | OpenWrt 6.18.55, no flowtable | 80 (58 GRO off) | - | NAT-HISTORY.md Measured |
| 2026-10-11 | + flowtable | 228-248 | 42-45 | same |
| 2026-10-11 | CPU 1000 -> 800 | 212 | 36 | Clock sensitivity: compute-bound |
| 2026-10-12 | mainline 7.3, `300-11` (TX ring 32, BQL, xmit_more) | 302-328 | 56 | Mainline 7.3 |
| 2026-10-12 | `300-12` (doorbell, napi_consume_skb, TX ring 128) | 348-358 | 70 | NIC path |
| 2026-10-12 | `300-13` (lowmem fast paths, HIGHMEM) | 365-370 | 69-70 | HIGHMEM and 512 MiB |
| 2026-10-12 | SMP (both VPEs online) | 322-334 (UP 346) | - | MAINLINE-PORT.md section 9 |
| 2026-10-13 | picks clocks | 435-444 | 94 | Clocks x SRAM matrix |
| 2026-10-13 | XPS: no tx hash | 502-504 | 101-104 | Runtime tunables |
| 2026-10-13 | `300-27` (select_queue, no hash) | 521-528 | 106-109 | same |
| 2026-10-13 | `300-28` (RX descriptor read through cache) | 514-533 | 110-111 | same |
| 2026-10-15 | series to 300-35; eth0 `noqueue` | 528; 544 | 111; 113 | Mainline with today's series |
| 2026-11-06 | OpenWrt 7.3 b455c5b, stock 800 MHz | 195-203; 283-294 with GRO list | - | NAT-HISTORY.md OpenWrt on 7.3 |
| 2026-11-06 | + pinned per-ring NAPI + TX ring per CPU + noqueue | 369-377 | 59 | Combinations |

- Biggest steps: flowtable (3-4x over no flowtable), `300-12` (+15 %), picks clocks (+25 %), no tx hash (+16 %).
- Per-packet cost: about 30 µs OpenWrt TCP (stock 800 MHz, 2026-11-06); 13 µs mainline initramfs UDP 64 B (base), 10 µs (picks).

## Tried, did not help

| Idea | Result | Date |
|---|---|---|
| RPS to VPE1 | 128 vs 248 (6.18); 347 vs 502 (7.3) | 2026-10-11, 13 |
| Threaded NAPI | 440 vs 502 | 2026-10-13 |
| `300-14` SMP-safe doorbell | 290 / 146 | 2026-10-12 |
| TX reclaim on the other VPE (`tx_cpu=0`) | 44 % of baseline | 2026-10-12 |
| TX from the RX page pool (no dma_map) | no gain, reverted | 2026-10-12 |
| UDP GRO forwarding | worse (76.5 to 71.4 kpps, 4 % loss) | 2026-10-15 |
| LX bus +17 % | no gain | 2026-10-11 |
| Descriptor rings in SRAM | NIC DMA does not work from SRAM | 2026-10-13 |
| GRO or fraglist GRO off | -30 to -40 % | 2026-10-11, 13 |


## NAT.md before the 2026-11-07 finalisation (switch core 408 MHz era)

Verdict, best numbers, ceilings and open-issue table as NAT.md held them before the final settings (core 608 MHz) were adopted. Numbers here were taken at core 408; the final numbers are in NAT.md.

### Verdict
- IPv6 is routed by the ASIC: **9.08 Gbit/s at 0 % CPU** (needs the `2000::/3 via <gw>` workaround, #59).
- IPv4 NAT on the skb stack (nftables software flowtable): best **544 Mbit/s** TCP (initramfs, picks clocks), 507 on OpenWrt 7.3; 22 % of target.
- IPv4 NAT on the in-place fast path (`300-39`, prototype): **1.25 Gbit/s** TCP with kernel-fed flows, 1.66 Gbit/s UDP 1400 B; 50-66 % of target. The 1400 B ceiling is not yet explained.
- The ASIC rewrites MACs and TTL only, no IP or L4 port (#58, #68). Every NAT packet crosses the CPU port twice.


### Best numbers (sw2 unless noted)
Metric: iperf3 TCP `-P 4` through NAT + software flowtable, one-armed over lan1. Picks = CPU 1350 / DDR 662 / LX 306 / SRAM 500; base = CPU 1000 / DDR 650 / LX 175; stock = CPU 800 / DDR 600.

| Path, image, clocks, date | TCP Mbit/s | UDP 1400 B | UDP 64 B kpps |
|---|---|---|---|
| Flash OpenWrt 6.18.55, base, 2026-10-11 | 243-248 | 38.1-39.7 kpps | 41.9-44.9 |
| Initramfs 7.3 + series to `300-35`, picks, 2026-10-15 | 528 (544 with `noqueue`) | 76.5 kpps @900 offered, 0.1 % loss | 110.8 (113.1) |
| OpenWrt 7.3, picks, best knob combination, 2026-11-06 | 507 | - | 88 |
| OpenWrt 7.3, picks, image defaults | 388 | - | 76 |
| OpenWrt 7.3, stock, best knob combination | 369-377 | - | 59 |
| OpenWrt 7.3, stock, image defaults | 283-294 | - | 53 |
| Fast path, kernel-fed flows, picks, 2026-11-06 | 1250 / 1187 (fwd / rev) | - | - |
| Fast path, stateless 1:1 NAT, picks, 2026-11-06 | 1339.6 / 1309.8 | - | - |
| Fast path, UDP + NAT, picks, 2026-11-06/07 | - | 143.7 kpps (1.66 Gbit/s) | 490.7 |
| Fast path + queue-1 1024/1008 (`300-40`), picks, 2026-11-06 | 1517 / 1519 | - | - |
| IPv6 routed in the ASIC (`2000::/3` via gw), base, 2026-10-11 | 9079 (0 % CPU) | - | - |

- Flash image: 6.18 numbers only. 7.3 numbers are RAM boots (`ramload`); no 7.3-from-flash run is recorded.
- Fast-path TCP rows lose frames at the ASIC CPU queue (retransmits, ~1 % in one run, 1.9k per 10 s with `300-40`), not in the fast path itself.
- IPv4 / IPv6 NAT on the CPU, OpenWrt 7.3, old image (fraglist GRO off), stock, 2026-11-06, one run each: masquerade 77.7 / 76.8 (fwd / rev) v4, 72.7 v6; + flowtable 203.2 / 203.6 v4, 205.3 v6. Source rewrite verified in conntrack.
- Per packet: ~30 us OpenWrt TCP (stock); 13 us UDP 64 B (base) and 10 us (picks) on the stack; 2 us (64 B) and 6.6-7.0 us (1400 B) in place.
- No OpenWrt-vs-initramfs gap: 283-294 at 800 MHz vs 350 at 1000 MHz is the clock ratio. The firewall ruleset costs nothing with the flowtable on (376 vs 377).

### Ceilings and what limits them
Measured:
- Stack path: compute-bound on one VPE (VPE0 94-97 %). CPU clock moves pps 1:1; DDR, prefetch and LX move it <= 9 %. Call graph: no single hotspot (driver RX 26 %, GRO second pass 69 % inclusive).
- Second VPE: shares one 34Kc pipeline and one L1; the memory miss queue is the shared bottleneck (a streaming neighbour removes 75 %). Pinned per-ring NAPI + `tx_by_cpu` + `noqueue` is the only multi-VPE combination that won (+31 %, VPE0/VPE1 94/95 %).
- 2.5 Gbit/s of 1500 B frames is ~312 kpps through the CPU port (data + ACKs): 3.2 us per packet at 1 GHz. The stack path is 10-30 us.
- Fast path at 1400 B: 143 kpps = 1.66 Gbit/s each way (3.3 Gbit/s through the port); VPE busy 97-99 % at every size; cost ~1.5-2 us fixed + ~4 ns per byte (~2 Gbit/s asymptote). Cutting CPU, DDR or LX by ~25 % costs 3-8 %. `rxdrop` (receive and drop) also stops at 137 kpps at 1400 B.
- CPU-port speed field (`SPD_SEL`): writes of 10G / 2.5G / 5G alone leave sw2 unreachable; no rate measured at any other setting ([CPU-PORT.md](CPU-PORT.md)).

Not isolated:
- The cause of the 1400 B ceiling. It is byte-dependent and nearly clock-independent: candidates are NIC DMA, bus/DDR contention, or the chip feeding the CPU queue. #149 (RX panic that depends on LX clock) hints that the bus clock touches the DMA path; unconfirmed.
- Whether PIE CPU-QID steering applies to frames trapped by an L3 route, and the real gain of a per-flow ring split (#146).
- Stack-path ceiling on this CPU: estimate only (1-1.7 Gbit/s at 1500 B, not measured).
- GDMA engines work as memcpy/checksum (`kmod/gdma_test`) but the fast path copies nothing; speed sensors read 0 (#151, [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md)).

### Open issues
| Issue | State | Next step |
|---|---|---|
| #65 Fast NAT 2.5 Gbit/s | best 544 stack, 1.25-1.66 Gbit/s fast path | find the 1400 B ceiling cause (#148) |
| #148 CPU-port ceiling, SRAM/cache-locked data | parked P0 (#151); sweeps in [CPU-PORT.md](CPU-PORT.md) | stock-clock perf control, real-length RX/TX cache sync, GDMA probe |
| #149 RX panic in `gro_list_prepare` | open, 4 panics | same load + perf at stock clocks (0/3 vs 3/3) |
| #140 in-place / XDP NAT fast path | prototype works (`300-39`) | SRAM buffers, second VPE, IPv6, fragments, soak |
| #145 best knob combination as image default | +31 % measured | fix `tx_by_cpu` reclaim first |
| #146 balance VPEs by flow | not tried | PIE ACL hit -> RX ring 1, NAPI ring 1 on VPE1 |
| #147 fewer DDR misses per packet | not tried | prefetch next descriptor and headers; sync only used bytes |
| #103 other clock domains, SRAM for hot data | picks adopted; rings in SRAM fail | SRAM packet buffers |
| #60 NIC driver | `300-11/12/13/27/28/40` shipped | per-flow second CPU (#146) |
| #59 L3 offload gaps | `300-17` written, not measured | measure `l3_default_*`, `l3_onlink` |
| #66 ASIC-routed bypasses nftables | SYN drop via `300-37` works | UDP policy, ICMPv6 allow, PIE capacity |
| #71 NAT path review (conntrack, nf_nat, flowtable) | not done | trace and tunables |
| #22 all-port wire-speed routed test | open | run |
| #151 parked state of #148 | GDMA memcpy works; sensors read 0 | in #148 order |
| #63, #58, #68 | closed: no ASIC rewrite, hybrid not started | - |

## L3 offload on the 7.4 base (2026-11-07, #59)

- Image: `tmp/tftp/openwrt-ours-initramfs.bin` (OpenWrt main 7e8bfcfe76 on kernel 7.4-rc1, `300-17` rebased on the reworked `l3.c`), sw2, cage 1, `./scripts/l3_offload_ab.py -n 3` (TCP `-P 4`, 10 s, median [min..max] Mbit/s, one boot).
- Clocks: `ramload --stock-clocks` + `turbo cpu=1350,ddr=662,sram=500`, no switch-core change (LX stays 175). Core 608 + CPU 1350 + LX 306 panicked 2 of 2 boots on this image (below).
- Raw rows: `tmp/logs/l3_offload_ab-20261107-181238.csv` / `.txt`.

| Path | Dir | Offload off | Offload on | CPU0 busy off/on % | eth0 pps off/on |
|---|---|---|---|---|---|
| v4 on-link | fwd | 86 [84..92] | 9206 [9206..9212] | 98.5 / 36.2 | 21664 / 330 |
| v4 on-link | rev | 86 [85..86] | 9206 [9184..9216] | 98.7 / 63.6 | 21437 / 333 |
| v4 default | fwd | 86 [86..89] | 9227 [9212..9235] | 96.3 / 50.7 | 21737 / 340 |
| v4 default | rev | 88 [86..92] | 9231 [9199..9234] | 97.8 / 66.6 | 22004 / 335 |
| v6 on-link | fwd | 82 [82..83] | 9130 [9119..9139] | 99.7 / 56.5 | 21663 / 338 |
| v6 on-link | rev | 82 [81..90] | 9125 [9098..9137] | 99.9 / 55.0 | 21573 / 342 |
| v6 default | fwd | 165 [164..168] | 9129 [9114..9187] | 99.7 / 59.7 | 29223 / 339 |
| v6 default | rev | 2284 [2119..2766] | 9140 [9051..9148] | 99.3 / 45.9 | 17670 / 344 |

- Wire speed holds: 9.1-9.2 Gbit/s with the CPU port nearly idle (eth0 ~340 pps). CPU0 busy of 36-75 % with offload on is unexplained at that packet rate (not investigated).
- v6 default base: forward 165, reverse 2284 Mbit/s (not investigated).
- ASIC rows after each offload run: `fwd` with `chk,dec` flags on the host `/32` and `/128` rows and the default rows of the case under test.

| Check | Result |
|---|---|
| a `ip neigh del` | FAIL at the 6.25 s settle (default row still `trap`: the precondition `dflt4` row also needed > 6.25 s after `ALL_ON`); PASS in the 20 s re-run |
| b neighbour MAC change | PASS (new MAC in `nexthops`, ping ok) |
| c `ip route add 10.99.2.0/25` | PASS |
| d `ip addr add 10.99.2.2/32` | PASS (local `/32` `trap`) |
| e `ip rule add` | PASS (`suspended` log 2 -> 3) |
| f source-specific `::/0` | FAIL: `::/0` goes to `trap` as expected, but stays `trap` after the route is deleted and `l3_default_v6` toggled 0 -> 1 (neighbour REACHABLE, 20 s). A `ip -6 route del default` + `add` brings it back `fwd` NH 23 |
| i all parameters 0 | PASS |
| g, h | not run (g needs `--with-g`, 120 s; h needs raw frames) |

- IPv4 offload flags: `ip route` shows `rt_offload` on the default and `rt_trap` on the connected prefixes while offloaded. IPv6 routes show `rt_offload` / `rt_trap` too (`fd99:22::/64 via ...` `rt_offload`; the re-added `::/0` read `rt_trap` until offloaded).
- Finding: after `l3_default_v4` goes 1 -> 0 the IPv4 default keeps `rt_offload` although the ASIC row is `trap` (dmesg `default route 0.0.0.0/0 traps to the CPU`); it was `rt_offload` again after the re-enable. Flag is not cleared on the teardown path.
- Finding: after check f's source-specific `::/0` add/delete the plain `::/0` is not re-offloaded until the route is re-added (see f).
- Fixed in `300-17` (2026-11-08, host-built only, not yet run on sw2): demoted v4 default clears `rt_offload` (`otto_l3_default_check`); last source-specific v6 route requests a FIB replay (`otto_l3_fib_del_v6_src`) so the plain `::/0` is offered again.
- #149 (`gro_list_prepare`): not seen on this image at LX 175 over 48 iperf runs plus checks (one boot, ~12 min).

### Core 608 on the OpenWrt 7.4 image: unstable

- Boot 1: `turbo cpu=1350,ddr=662,lx=306,sram=500` + core 608 raw (e220 `0x36826`). `Unhandled kernel unaligned access` in `__d_lookup_rcu` (sh, uptime 31 s), reboot. Boot 2 same settings: selftest `cpu` FAIL, ssh `incorrect signature`, `Kernel panic - Fatal exception in interrupt` in `ipv6_getorigdst` (nf_conntrack, taint `B` BAD_PAGE, 179 s, in ksoftirqd under iperf).
- Both are corrupted pointers / code (no `gro_list_prepare`): memory or cache instability, not the #149 trace. The plain 7.4 bench kernel at the same core 608 / CPU 1350 / DDR 662 / LX 306 booted and ran the #71 runs below (~15 min) without a fault.
- The L3 runs used CPU 1350 / DDR 662 / SRAM 500 without the core change (selftest PASS all 11 items).

### `l3_offload_ab.py` bugs fixed

- `setup` pinged the switch SVI; fw4 input rejects it on OpenWrt (the SVI ping needs `mode`). Setup failure is no longer fatal and readiness is a natlan -> natwan ping through the switch, polled 8 x 1 s.
- Results cells printed `[---]` for an empty min/max; now `..`.
- `--settle SECS` override added; `wait ok` logged with the time.
- Not fixed in `nat_bench.setup`: `ip netns del` then immediate `ip link add ... vlan` fails ("VLAN device already exists") while the old namespace is still being torn down after a killed iperf3 (about 1 min). Kill stray `iperf3 -c` first.
- `l3_offload_ab.py` checks need an IPv6 ping before the v6 rows return: the gateway neighbour drops to STALE/DELAY within ~10 s without traffic.

## Linux NAT path cost: ftrace/conntrack A/B (2026-11-07, #71)

- Kernel: plain 7.4-rc1 bench kernel (`mainline-7.4-rc1.bin`), sw2 at core 608 / CPU 1350 / DDR 662 / LX 306 / SRAM 500 (`retest_options.py boot --core 608`), cage 1, `nat-bench mode nat-ft` (flowtable) or `nat` (conntrack on every packet). Stack path, `zc=0`, IRQ on VPE0.
- Tool limits: `perf record -a -e cpu-clock` gave ~20K samples via `nat_perf.py` but only 12-40 samples under `zc_bench.py --perf` once the NIC IRQ sat on VPE1; the zc profile below is from one earlier good run (31K samples, 2026-11-07 18:32, not saved).

### perf, stack path, TCP `-P 4` (`nat_perf.py --callgraph`, all CPUs, inclusive % of samples)

| Function | `nat-ft` (342 Mbit/s, 290 under perf) | `nat` (conntrack every packet) |
|---|---|---|
| `net_rx_action` (all softirq) | 49.1 | 49.2 |
| `gro_receive_skb` | 37.2 | 38.1 |
| `nf_hook_slow` | 28.1 | 9.7 |
| `nf_flow_offload_ip_hook` | 27.2 | - |
| `nf_flow_queue_xmit` | 20.5 | - |
| `nf_flow_offload_lookup` | 3.2 | - |
| `ip_output` | - | 19.9 |
| `nf_conntrack_in` | < 0.7 | 6.7 |
| `nf_conntrack_tcp_packet` | - | 2.8 |
| `hash_conntrack_raw` | - | 1.9 |
| `nf_nat_manip_pkt` | - | 1.4 |
| `nf_nat_ipv4_pre_routing` | - | 1.2 |
| `ip_forward` | - | 0.7 |

- With the flowtable, established flows skip conntrack and nf_nat: the hook is lookup 3.2 % + rewrite + queue xmit, no conntrack function above 0.7 %.
- Without it conntrack + nf_nat are ~9.7 % of all samples (~20 % of softirq time); GRO (37-38 %) and the DSA/TX path are larger.
- Files: `tmp/logs/nat_perf-n71-stack-cg.txt`, `nat_perf-n71-natct-cg.txt`, `nat_perf-n71-stack-flat.txt`.

### perf, zc+nat 1400 B (all CPUs, one run, 168 kpps)

- `default_idle_call` 50.8 %, `_raw_spin_unlock_irqrestore` 18.7 %, `rteth_poll_rx` 17.8 %, `r4k_dma_cache_inv` 3.1 %, `rteth_reclaim_tx_ring` 2.6 %, `__raw_copy_to_user` 1.2 % (perf's own file write). No netfilter symbol.
- Stack vs zc+nat, same boot, UDP 1400 B: 52.7-56.6 kpps vs 162.8-168.9 kpps (3.0-3.1x).

### ftrace `function_graph` (`rteth_ftrace.py --depth 3`, nat mode, TCP `-P 4`, tracer-inflated; load fell to 56 Mbit/s)

| Function | calls | avg us | us per rx packet |
|---|---|---|---|
| `ip_forward` (incl. output) | 14609 | 78.5 | 29.1 |
| `nf_conntrack_in` | 15138 | 48.0 | 18.4 |
| `nf_conntrack_tcp_packet` | 15080 | 22.2 | 8.5 |
| `hash_conntrack_raw` (siphash 1.3) | 15119 | 7.0 | 2.7 |
| `nf_nat_ipv4_pre_routing` | 14832 | 10.1 | 3.8 |
| `nf_nat_inet_fn` | 15112 | 6.5 | 2.5 |
| `__nf_conntrack_find_get` | 15121 | 2.4 | 0.9 |
| `nf_nat_manip_pkt` | 8478 | 6.9 | 1.5 |
| `__nf_ct_refresh_acct` | 15109 | 2.1 | 0.8 |
| `nf_checksum` | 14828 | 2.0 | 0.8 |

- Ring-buffer overrun (394K events lost): relative split only. Raw trace `tmp/rteth_ftrace/20261107-183755-d3.txt`. `nf_conntrack_in` is 63 % of `ip_forward`'s hook cost; TCP state tracking is the largest part (46 %).

### conntrack / flowtable sysctl A/B (`nat_knobs.py matrix`, TCP `-P 4`, 10 s, one run per point)

| Knob (default -> test) | `nat` Mbit/s | vs default | `nat-ft` Mbit/s | vs default |
|---|---|---|---|---|
| default | 248.0 | - | 341.1 | - |
| `nf_conntrack_acct` 1 -> 0 | 247.6 | -0.2 % | 342.9 | +0.5 % |
| `nf_conntrack_tcp_be_liberal` 0 -> 1 | 247.5 | -0.2 % | 343.1 | +0.6 % |
| `nf_conntrack_tcp_loose` 1 -> 0 | 247.3 | -0.3 % | 339.3 | -0.5 % |
| `nf_conntrack_checksum` 1 -> 0 | 251.8 | +1.5 % | 336.6 | -1.3 % |
| `nf_conntrack_max` -> 4096 / 65536 | 249.3 / 247.7 | +0.5 / -0.1 % | - | - |
| hashsize -> 1024 / 16384 | 251.1 / 249.5 | +1.3 / +0.6 % | - | - |
| `nf_flowtable_tcp_timeout` 30 -> 120 | 248.0 | 0 % | 336.3 | -1.4 % |

- All within 2 % (run-to-run spread is ~5 %): no tunable moves the NAT rate; no repeats run. 4 flows never stress the table size or hash.
- `nf_conntrack_max` and hashsize cannot be restored by `nat_knobs reset` (state `dflt` is a no-op); the later cells in the `nat` pass ran with max 4096 / hashsize 1024 in place. Boot afterwards.
- Absolute rates here (248 / 341) are below the 413-422 stack rows in [NAT.md](NAT.md); the setup differs (`nat_bench run` to 10.99.2.2, IRQ on VPE0, no `irq1`), not investigated.
- Open for #71: nothing in the stack path is conntrack-bound once the flowtable carries the flow; remaining acceptance is a decision (close with this table) or a UDP many-flow test of table size / hash (needs a flow generator).

## OpenWrt image vs plain kernel NAT TCP (#161)

- 2026-11-08, sw2, one session per image: core 508 raw regs (e220 0x30626, e214 0x3b8), CPU 1350, DDR 662, LX 306, SRAM 500, cage 1, one NAT interface (`nat-bench setup`), software reboot between images.
- Plain = `mainline-7.4-rc1.bin`; image = `openwrt-ours-initramfs.bin`. Driver `scripts/nat161_compare.py` (rows `tmp/logs/nat161.jsonl`, settings dumps `tmp/logs/nat161_<img>_settings.txt`).
- `nat_bench run --secs 15 -P 4` x3 per cell; values below are the mean of 3; cpu = busy % VPE0/VPE1 on fwd.

| Image | Path (irq) | fwd / rev Mbit/s | VPE0 / VPE1 busy | rx pps fwd |
|---|---|---|---|---|
| plain | `nat` (irq VPE0) | 240 / 311 | 99 / 85 | 30.5k |
| plain | `nat-ft` (irq VPE0) | 323 / 406 | 98 / 85 | 40.6k |
| plain | `nat-ft` (irq1) | 324 / 405 | 84 / 100 | 40.7k |
| OpenWrt | `nat` (irq VPE0) | 85.5 / 103.2 | 100 / 56 | 10.8k |
| OpenWrt | `nat` (irq1) | 76.6 / 88.0 | 98 / 78 | 9.6k |
| OpenWrt | `nat-ft` (irq VPE0) | 267.7 / 344.0 | 98 / 86 | 33.7k |
| OpenWrt | `nat-ft` (irq1) | 233.5 / 272.1 | 97 / 98 | 29.1k |
| plain | zc+nat (`zc_bench --tcp`, irq1) | 1565 / 1571 | - | - |
| OpenWrt | zc+nat (`zc_bench --tcp`, irq1) | 1536 / 1555 | - | - |

- `zc_bench --tcp` stack legs (nat-ft, irq1): plain 388-393 / 387-399, image 297-305 / 289-303 Mbit/s; zc legs 4.0x vs 5.0-5.3x.
- The 83-104 Mbit/s in #161 is the image in `nat` mode (conntrack + masquerade on every packet, no flowtable); the 413-422 plain rows are `nat-ft`. Not the same path.
- The image's fast path works: zc+nat 1536-1555 vs 1565-1571 plain (-2 %); zc counters equal (stack rx ~370 pps).

### Settings that differ (image vs plain)

- `rps_cpus` on `eth0` rx-0/rx-1: image `1` (VPE0), plain `0`. Reset by OpenWrt after `nat-bench setup` (netifd hotplug), so `--napi irq1` on the image still ends with the stack on VPE0 (VPE0 96 % softirq, VPE1 41 % at irq1).
- `eth0` qdisc: image `fq_codel`, plain `pfifo_fast`. Not varied.
- `nf_conntrack_checksum`: image 0, plain 1 (image setting is the cheaper one).
- fw4 loaded on the image: 12 base chains (mangle/raw/dstnat/srcnat/input/forward/output) = more netfilter hooks per packet; `ct state vmap` in input/forward/output; plain has only the bench's `nattest` table. Not removed in this session.
- Userland on the image: netifd, collectd, lldpd, snmpd, uhttpd, ntpd, procd; conntrack table 328 entries vs 5 on plain.
- Identical: `rtl838x_eth` parameters, `ethtool -k eth0`, GRO state, irq affinity default (VPE0), `threaded` 0, no irqbalance.

### Partial A/B on the image (nat, irq on VPE1, 1 x 15 s per point, same boot)

| Change (cumulative) | fwd / rev Mbit/s | VPE0 / VPE1 busy |
|---|---|---|
| image as booted (irq1) | 76.6 / 88.0 | 98 / 78 |
| `rps_cpus` = 0 | 106.6 / 108.1 | 45 / 98 |
| + `nf_conntrack_checksum` = 1 | 108.5 / 109.3 | 45 / 97 |
| plain, same path | 240.6 / 311 | 84 / 99 |

- RPS off: +39 % fwd, +23 % rev; VPE0 softirq share drops 95 % to 0, the single RX VPE then limits at 13.6k pps vs plain 30.3k pps at the same 98-99 % busy: image costs 2.2x more per packet on `nat`.
- A daemons-stopped run (collectd, lldpd, snmpd, uhttpd, ntpd) was taken with RPS back on (netifd re-applied it): 95 Mbit/s fwd vs 76.6, i.e. daemons are a minor share; not isolated with RPS off.

### Conclusion

- Not a regression of the zc path: image zc+nat is within 2 % of plain.
- Image `nat-ft` stack is 17-28 % below plain; image `nat` stack is 2.2-2.8x below plain (85-104 vs 240-311).
- Part of the gap is `rps_cpus` = 1 (OpenWrt packet steering), which defeats `--napi irq1` placement: the image never gets a stack path on VPE1. Removing it gives +23-39 % on `nat`.
- Remaining ~2.2x per packet on `nat` is not explained: candidates are the fw4 hook chains (not removed), `fq_codel` on `eth0`, and kernel config differences in conntrack/nf (image build vs plain build). Next probe: on the image `nft delete table inet fw4` then `tc qdisc replace dev eth0 root noqueue`, and `perf` (`perf_push.py`, `nat_perf.py`) on both images for `nf_hook_slow` / `nf_conntrack_in` shares, with RPS 0 and the same irq placement.
- Bench note: `nat_bench.py run` leaves a root `iperf3 -s -1` in the netns when the client cannot connect (failed run); the leftover blocks the next `setup` (`8021q: VLAN device already exists`) until it is killed.

## L3 offload fixes on the 7.4 base (#59), 2026-11-08

- Image `tmp/tftp/openwrt-ours-l3fix-initramfs.bin` (7.4 + 300-17 fixes), RAM-loaded on sw2 with `ramload uboot-mainline --then openwrt-ours-l3fix` (new image key).
- Clocks: core 608 raw (e220 0x36826 / e214 0x478), CPU 1325, DDR 662, SRAM 500, LX 306; also once at the ramload default clocks (CPU 1000, stock core).
- Superseded: missing `st1008f-stx` selftest helper (#163), not the 300-17 fixes.
- Result: image did not stay up. 5 boots of 5 (3 at the 608/1325 profile, 2 at default clocks) ended in a SoC reset 26-32 s after kernel start (blackbox "unclean ... msg boot"); the chain then booted the flash 6.18 slot a.
  - Boot to shell and STP worked in 4 of 5; in the boot with `ps w` captured, `nft -f /dev/stdin` (fw4 reload) sat in D state at ~17 s, then no console echo.
  - Console loglevel is 1 after `ramload`, so no kernel message was captured; sysrq-w capture not obtained (race with the ramload STP step).
  - One boot hit the ramload STP check (45 s) and cut relay power per #19; next ramload restarted the daemon first and powered on.
- `l3_offload_ab.py` checks a-i: NOT RUN (board never answered ssh long enough). Check f and the `offload --default-v4 0` rt_offload expectation are unverified on hardware.
- Control not run: the 7.3 `openwrt-ours` image holds 608/1325 5/5 (openwrt_core_stability.py), so the hang is image-side (7.4 + fixes), not clocks.
- Next: boot with `ignore_loglevel` bootargs and `echo w > /proc/sysrq-trigger` right after the shell; bisect fixes in `l3.c` (notifier path) vs the 7.4 userspace.

## #147 prefetch A/B, 2026-11-08

- Kernel `mainline-7.4-rc1-pf.bin` (plain, 300-44 parked patch), booted `retest_options.py boot --core 608 --cpu 1325`; BogoMIPS 872 (1325 MHz), SPI divide 6.
- `zc_prefetch_ab.py --tag pf1`: n=3 interleaved rounds, 12 s runs, NAT zc path (`zc_bench.py --nat --napi irq1 --zc-only`), VPE1 99 % busy in all cells; integrity PASS in every variant and round.
- Log: tmp/logs/zc_prefetch_ab.log.

| Variant (desc, hdr) | 1400 B kpps | vs base | 64 B kpps | vs base |
|---|---|---|---|---|
| base (0,0) | 166.8 | - | 424.8 | - |
| desc (1,0) | 166.5 | -0.1 % | 441.2 | +3.9 % |
| hdr (0,1) | 166.7 | 0.0 % | 400.6 | -5.7 % |
| both (1,1) | 165.9 | -0.5 % | 439.9 | +3.5 % |

- Spread inside a variant 0.1-0.4 % at 1400 B, 0.2-1.3 % at 64 B.
- Verdict 1400 B: no variant outside the +-3 % band; prefetch is not a gain at the bulk size.
- 64 B: `desc` +3.9 % and `both` +3.5 % (just past the band, small packets only); `hdr` -5.7 %. Parameters stay default off.

## L3 offload checks on the 7.4 base with the fixes (2026-11-08, #59)

- Image: `openwrt-ours-l3fix2` (7.4-rc1, `300-17` with the v4 `rt_offload` clear and the v6 FIB replay), sw2, cage 1, `ramload uboot-mainline --stock-clocks --then ... --pre turbo cpu=1325,ddr=662,lx=306,sram=500` + core 608 raw regs (`c608_cpu1325`). `/usr/libexec/st1008f-stx` present, BogoMIPS 875.72.
- Run: `l3_offload_ab.py -n 3 --with-g` (`tmp/logs/l3_offload_ab-20261108-124930.txt`), checks re-run after the script fix (`-130653.txt`). One boot, ~21 min, no panic/reset/`gro_list_prepare` (#149) in dmesg.

| Path | Dir | Offload off | Offload on | eth0 pps off/on |
|---|---|---|---|---|
| v4 on-link | fwd | 90 [86..91] | 9197 [9184..9200] | 22436 / 345 |
| v4 on-link | rev | 90 [88..94] | 9201 [9195..9202] | 22306 / 342 |
| v4 default | fwd | 94 [92..98] | 9201 [9191..9222] | 23215 / 345 |
| v4 default | rev | 90 [88..92] | 9189 [9188..9212] | 22354 / 344 |
| v6 on-link | fwd | 86 [83..86] | 9058 [9056..9068] | 22617 / 345 |
| v6 on-link | rev | 89 [89..94] | 9068 [9052..9147] | 23507 / 343 |
| v6 default | fwd | 171 [168..171] | 9066 [9064..9067] | 30140 / 341 |
| v6 default | rev | 1456 [1361..1731] | 9058 [9049..9059] | 17970 / 341 |

| Check | Result |
|---|---|
| a `ip neigh del` | PASS |
| b neighbour MAC change | PASS |
| c `ip route add` covering prefix | PASS |
| d local `/32` | PASS |
| e `ip rule add` | PASS |
| f source-specific `::/0` | PASS: plain `::/0` back to `fwd` ~4 s after the delete, `rt_offload` again, dmesg "no longer offloaded" + "replaying the FIB" |
| g 120 s run, neighbour states | PASS (DELAY/REACHABLE/STALE, never FAILED, 0 "no valid neighbour") |
| h martian DIPs (`scripts/l3_offload_h.py`) | FAIL: DIP `0.0.0.1` forwarded to natwan (2 of 2 runs); `127.0.0.2` and `::1` not seen; control `10.99.2.2` seen |
| i all params 0 | PASS |

- v4 flag: `l3_default_v4` 1 -> 0 turns the v4 default from `rt_offload` to `rt_trap` (fix confirmed).
- h: `BAD_DIP_ACT` drop covers loopback and `::1` but not `0.0.0.0/8` with the v4 default row forwarding; needs a trap row for `0.0.0.0/8` above the default (open).
- First check f run failed: the v6 gateway neighbour was STALE (no v6 traffic since check e), so the default row read `trap`. Script bug, not the driver.

### Script changes
- `l3_offload_ab.py`: v6 ping before the check preconditions and before f's wait; f no longer toggles `l3_default_v6` (the driver replays by itself).
- New `scripts/l3_offload_h.py`: raw AF_PACKET UDP frames (no scapy installed) from natlan to the SVI MAC, sniffer in natwan, control DIP.
