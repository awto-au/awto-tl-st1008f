# NAT on the TL-ST1008F (RTL9303)

Target: NAT near 2.5 Gbit/s (owner ISP: NBN HFC ~2 Gbit/s down). Issue: "Fast NAT (target 2.5 Gbit/s)". How to run the measurements: [NAT-OPS.md](NAT-OPS.md).

## Verdict

- IPv4 NAT runs only on the CPU path: the ASIC has no IP/port rewrite (#58).
  - Best measured, with the nftables software flowtable: **248 Mbit/s** TCP NAT; UDP 1400 B forwards 39.7 kpps (about 445 Mbit/s).
  - 2.5 Gbit/s needs about 10x less CPU per packet than today. Not reachable on this CPU.
  - The per-packet cost scales with the CPU clock and barely with DDR or LX (see "Clock sensitivity"): the CPU path is compute-bound.
- IPv6 needs no NAT and is routed by the ASIC at **9.08 Gbit/s with 0 % CPU**. This is the fast path; clients prefer IPv6 when it is offered (see "IPv6 fast path").
- CPU port speed setting (1G) is not the limit. Every CPU path measured tops out below 500 Mbit/s.

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

- `::/0` is not offloaded: it shows as `trap` in `realtek_otto_l3/routes`, same as IPv4 (#59).
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

## IPv6 fast path (how most traffic avoids NAT)

- Clients prefer IPv6 when they hold a global address: RFC 6724 source/destination selection plus Happy Eyeballs (RFC 8305).
- The box needs: a DHCPv6-PD prefix from the ISP on the WAN, RA (plus optional DHCPv6) per LAN VLAN, and the v6 routes offloaded.
- Offload requirements, both from #59:
  - Upstream: `::/0` is not offloaded, so install `2000::/3 via <ISP gw>` (verified here).
  - Downstream: LAN clients are on-link, so the trap path applies (58.5 Mbit/s here) until on-link neighbours get host routes (#59, fix 1). This is the blocker for v6 at line rate in a real topology.
- Major content (video, CDNs, big clouds) is mostly v6-capable. What fraction of the household's traffic is v6: not measured.

## Related

- #58 no NAT in the ASIC.
- #59 offload gaps.
- #60 NIC driver.
- #63 hybrid NAT.
- #68 no hidden/disabled rewrite hardware in the die ([HIDDEN-FEATURES.md](HIDDEN-FEATURES.md)).
- #22 all-port test.
- [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md).
