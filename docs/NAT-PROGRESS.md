# IPv4 NAT: where we are and how we got here (#65)

Target 2500 Mbit/s (NBN HFC). Facts and ceilings: [NAT.md](NAT.md). Run steps: [NAT-OPS.md](NAT-OPS.md). Raw rows: `tmp/logs/nat_bench.jsonl`.

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
| 2026-10-11 | OpenWrt 6.18.55, no flowtable | 80 (58 GRO off) | - | NAT.md Measured |
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
| 2026-11-06 | OpenWrt 7.3 b455c5b, stock 800 MHz | 195-203; 283-294 with GRO list | - | NAT.md OpenWrt on 7.3 |
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
- First experiment: does a CPU-transmitted frame with `FWD_ALE` + `L3_ACT` get an L3 route lookup ([NAT.md](NAT.md) hybrid section).
