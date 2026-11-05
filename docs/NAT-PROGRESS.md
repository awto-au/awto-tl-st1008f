# IPv4 NAT: where we are and how we got here (#65)

Target 2500 Mbit/s (NBN HFC). Facts and ceilings: [NAT.md](NAT.md). Run steps: [NAT-OPS.md](NAT-OPS.md). Raw rows: `tmp/logs/nat_bench.jsonl`.

Metric: TCP `-P 4`, NAT or route + nftables software flowtable, one-armed over lan1, CPU path only. UDP 64 B = forwarded kpps.

## Where we are (2026-11-06)

| Image / boot | Clocks | TCP Mbit/s | UDP 64 B kpps | Note |
|---|---|---|---|---|
| mainline initramfs, series to 300-35 (best) | picks | 514-544 | 110-113 | 2026-10-13..15 |
| mainline initramfs | base | 350 | 73 | same boot family, 2026-10-13 |
| OpenWrt 7.3 (b455c5b), `rx-gro-list on` | base | 264 | not run | 2026-11-06 |
| OpenWrt 7.3 (b455c5b), image defaults | base | 195-203 | not run | `rx-gro-list` off |
| OpenWrt 7.3, masquerade, no flowtable | base | 78 | not run | v6 NAT 73 |

- Clocks: base = CPU 1000 / DDR 650; picks = CPU 1375 / DDR 662 / LX 306 / SRAM 500.
- Best is 21 % of the target. IPv6 needs no NAT: 9.1 Gbit/s in the ASIC.
- OpenWrt vs initramfs at base clocks: 264 vs 350 (-25 %), cause not isolated (suspects: fw4 and conntrack accounting, image kernel config, packages).
- OpenWrt has not been measured at picks clocks.
- The OpenWrt image does not enable fraglist GRO: +35 % when enabled by hand. Needs a boot-time default.
- CPU use in every run: VPE0 96-97 % (softirq), VPE1 1-4 %.

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
| 2026-11-06 | OpenWrt 7.3 b455c5b, base clocks | 195-203; 264 with GRO list | - | NAT.md OpenWrt on 7.3 |

- Biggest steps: flowtable (3-4x over no flowtable), `300-12` (+15 %), picks clocks (+25 %), no tx hash (+16 %).
- Per-packet cost: about 30 µs OpenWrt TCP (base, 2026-11-06); 13 µs mainline initramfs UDP 64 B (base), 10 µs (picks).

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

## The second CPU

- Hardware: MIPS 34Kc with 2 VPEs = two hardware threads on one pipeline and one L1. It is not two cores. The gain is filling stall cycles (a miss costs about 109 ns), not 2x.
- Today VPE1 does no forwarding work:
  - eth0 has one IRQ; both RX rings' NAPI run on the CPU that takes it (VPE0).
  - RX ring = RX reason parity (`rteth_setup_cpu_rx_rings`). All forwarded traffic has one reason, so ring 1 is idle.
  - The XPS and `300-27` gain was removing the TX hash, not using VPE1 (forwarding transmits inside the RX softirq).
- Why the attempts lost: each handed single packets across VPEs (IPI per packet, a second GRO pass, ring locks). RPS 0.56x; `tx_cpu` 0.44x.
- What has not been tried: a split with no per-packet cross-VPE traffic.
  - The ASIC steers frames to a CPU ring by PIE action CPU QID (DS section 7.13.1; `ACT_MSK_QID`, not implemented in `tc.c`/`pie.c`).
  - Match L4 port parity (or ingress port) in the PIE: half the flows to ring 1.
  - NAPI of ring 1 on VPE1 (one IPI per poll, or a threaded NAPI pinned to VPE1); each VPE then does RX, GRO, flowtable and TX for its own flows.
  - Unknown until measured: whether QID applies to frames that reach the CPU by an L3 route trap, and the real MT gain (RPS suggests small).
- Open as a plan: #60.

## Hybrid NAT (#63)

- Not started. PIE matches the flow, the CPU rewrites, the ASIC routes the re-injected frame.
- Saves the egress stack only. The NIC RX + TX driver floor (about 10 µs per packet at picks, UDP 64 B) stays, so it cannot reach 2.5 Gbit/s alone.
- First experiment: does a CPU-transmitted frame with `FWD_ALE` + `L3_ACT` get an L3 route lookup ([NAT.md](NAT.md) hybrid section).
