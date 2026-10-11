# NAT on the TL-ST1008F (RTL9303)

Target: NAT near 2.5 Gbit/s (owner ISP: NBN HFC ~2 Gbit/s down). Issue: "Fast NAT (target 2.5 Gbit/s)". How to run the measurements: [NAT-OPS.md](NAT-OPS.md).

## Verdict

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
- Kernel NAT path (conntrack, nf_nat, flowtable, GRO) review, trace and tunables: not done yet (#71).

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
