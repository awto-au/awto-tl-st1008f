# IPv4 NAT: where we are and how we got here (#65)

Target 2500 Mbit/s (NBN HFC). Facts and ceilings: [NAT.md](NAT.md). Run steps: [NAT-OPS.md](NAT-OPS.md). Raw rows: `tmp/logs/nat_bench.jsonl`.

Metric: TCP `-P 4`, NAT or route + nftables software flowtable, one-armed over lan1, CPU path only. UDP 64 B = forwarded kpps.

## Where we are (2026-11-06)

| Image / boot | Clocks | TCP Mbit/s | UDP 64 B kpps | Note |
|---|---|---|---|---|
| mainline initramfs, series to 300-35 (best) | picks | 514-544 | 110-113 | 2026-10-13..15 |
| mainline initramfs | base | 350 | 73 | 2026-10-13 |
| OpenWrt 7.3 (b455c5b), best knob combination | base | 369-377 | 59 | 2026-11-06, see "Combinations" |
| OpenWrt 7.3, image defaults | base | 283-294 | 53 | fraglist GRO now on at boot |
| OpenWrt 7.3, fraglist GRO off (old image) | base | 195-203 | - | |
| OpenWrt 7.3, masquerade, no flowtable | base | 78 | - | v6 NAT 73 |

- Clocks: base = CPU 1000 / DDR 650; picks = CPU 1375 / DDR 662 / LX 306 / SRAM 500.
- Best is 15 % of the target (picks-clock best 22 %). IPv6 needs no NAT: 9.1 Gbit/s in the ASIC.
- OpenWrt matches the initramfs at base clocks once tuned (375 vs 350); the old gap was fraglist GRO. The firewall ruleset costs nothing with the flowtable on (376 vs 377).
- OpenWrt has not been measured at picks clocks, nor with the best combination at picks.
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
| 2026-11-06 | OpenWrt 7.3 b455c5b, base clocks | 195-203; 283-294 with GRO list | - | NAT.md OpenWrt on 7.3 |
| 2026-11-06 | + pinned per-ring NAPI + TX ring per CPU + noqueue | 369-377 | 59 | Combinations |

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

## Combinations (2026-11-06, `./dev.py nat-knobs`)

Live switches, no rebuild: [NAT-OPS.md](NAT-OPS.md) "Knobs". OpenWrt 7.3 b455c5b, base clocks, sw2 RAM boot, NAT + flowtable, default route destination, TCP `-P 4` 10 s, one run per cell (spread about +-3 %). Rows: `tmp/logs/nat_knobs.jsonl`.

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
