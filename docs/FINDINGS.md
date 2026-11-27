# Findings: NAT limits, final settings, decisions

One page of conclusions. Facts per topic: [NAT.md](NAT.md), [CPU-PORT.md](CPU-PORT.md), [FASTEST-SETTINGS.md](FASTEST-SETTINGS.md), [CLOCKS.md](CLOCKS.md). Old experiments (kept unchanged, not comparable): [history/README.md](history/README.md).

- Raw numbers here come only from the controlled set: [NAT-STACK-RESULTS.md](NAT-STACK-RESULTS.md) (TrueNAS generator, 2026-11-09; plan [NAT-STACK-TESTS.md](NAT-STACK-TESTS.md)).
- Anything else is history: generators, clocks, uptimes and kernels differ per row, so rows cannot be compared (owner 2026-11-08).

## Verdict

- IPv4 / IPv6 routing: done by the ASIC at ~0 % CPU (`300-17`, opt-in, #59). ASIC-routed traffic bypasses nftables (#66).
- IPv4 NAT: the ASIC rewrites MACs and TTL only, no IP or L4 port (#58, #68). Every NAT packet crosses the CPU port twice.
- Fast path (`300-39`, in-place rewrite, no skb): ~1.67 Gbit/s TCP. Prototype, IPv4 only (#158).
- Skb stack: far below the fast path; the software flowtable helps (table below).
- 2.5 Gbit/s NAT is not reachable by clocks or driver options.

Controlled table (TCP, 4 connections, LAN to WAN, mean of 3 x 15 s, Mbit/s; B and C CONTROLLED, A not fully controlled, see source):

| Test | A: OpenWrt r38178, Linux 6.18.60 | B: OpenWrt r38178 + ours, 7.4-rc1 | C: minimal Linux 7.4-rc1 + ours |
|---|---:|---:|---:|
| NAT (conntrack) | 113.2 | 164.6 | 373.8 |
| NAT + software flowtable | 325.8 | 523.7 | 606.1 |
| NAT + zero-copy path | unavailable | 1,674.4 | 1,674.1 |
| Routed, CPU | not measured | 184.5 | not measured |
| Routed, switch chip | unavailable | 5,210.7 | not measured |

- Source: [NAT-STACK-RESULTS.md](NAT-STACK-RESULTS.md) 'What we found'. Why C beats B on the stack path is not established (OS services and compiler differ).

## Limits found

- Switch-core clock sets the 1400 B rate: it scales with the core clock up to 608 (408 = stock). Code 0 (/4 divider) wedges CPU-port DMA; code 1 is the usable step (#148).
- CPU-bound at core 608: the NIC IRQ + softirq VPE (VPE1) is 97-99 % busy at every frame size, ~170-180 kpps at 1400 B. Receive-and-drop stops at about the same rate: the limit is receive-side, not the NAT rewrite.
- CPU port: 2 RX + 2 TX rings, ring chosen by trap reason; forwarded traffic is one reason. Both VPEs share one pipeline and memory path, so a second CPU adds no rate (#146, #147, [CPU-PORT.md](CPU-PORT.md)).
- Zero-copy path: ~1.67 Gbit/s on both OpenWrt and plain kernel (controlled table).
- Stack path: numbers only from the controlled table; stack rates drift with uptime and boot, so only same-uptime runs compare.
- 2.5 Gbit/s of 1500 B frames is ~312 kpps through the CPU port (data + ACKs); the fast path does ~170-180 kpps.
- CPU clock: 1350 fails on the OpenWrt image at core 575 / 608 (#160); 1375 fails at 608. DDR 675+ needs `ddr-retrain --write`, no gain.

## What does not help

- Ring split (two RX rings, per-flow steering): slower than one ring.
- NAPI split / threaded NAPI: slower.
- SRAM rings: NIC DMA does not work from SRAM; no traffic.
- CPU-queue drop thresholds, `tx_by_cpu`, `noqueue`: tie.
- Cache variants (`zc_sync_bytes`, `zc_rx_part`, `300-42`) and prefetch (`300-44`): within noise, stay off.
- GDMA copy offload: no copy in the NAT path to offload.
- GRO: fraglist GRO off costs the stack path; UDP GRO forwarding is worse.
- Clock side options: LX arbitration patterns, SRAM bridge bits (tie or hang), RPS (worse), IRQ pinning (no effect).
- Detail and original numbers: [history/NAT-measurements-2026-11.md](history/NAT-measurements-2026-11.md), [history/CAMPAIGN-PLAIN-7.4.md](history/CAMPAIGN-PLAIN-7.4.md).

## Final settings

| Domain | Setting | Why the gap to the maximum |
|---|---|---|
| Switch core | 608 MHz (stock 408) | code 0 wedges DMA; 608 is the persistent step ([FASTEST-SETTINGS.md](FASTEST-SETTINGS.md#final-settings)) |
| CPU | 1325 MHz on the OpenWrt image; 1350 only on the plain kernel | 1350 corrupts computation on the image at core 575 / 608 (#160) |
| DDR | 662 MHz | 675 / 700 give no gain beyond noise |
| SRAM | 500 MHz | already the maximum; no effect on the NAT rate |
| LX | ~304 MHz | follows the switch-core VCO |

- Not default on the flash chain: stock clocks unless the M3 turbo profile is set (#109, #152).
- Fast SPI never with Linux reading flash (#50).

## Owner decisions (full list: [DECISIONS.md](DECISIONS.md))

- 2026-11-07: go with what works; DDR and CPU limit testing stopped; switch core 608, CPU refined to 1325 on 2026-11-08 (#160).
- 2026-11-07: after every switch-core clock increase, re-test the earlier losing options (second CPU, NAPI, SRAM rings, cache variants, queue thresholds). Satisfied for 608.
- 2026-11-07: one NAT interface only; no multi-WAN design or tests.
- 2026-11-07: kernel base = latest Linus tag; tests on a plain kernel, not OpenWrt.
- 2026-11-07: temperature is logged only, no abort threshold.
- 2026-11-08: comparisons come only from controlled runs; old results are history, kept in `docs/history/`.
- 2026-10-12: no netfilter guard on L3 offload; `l3_default_v4/v6` and `l3_onlink` stay operator opt-in.
- 2026-11-17: NAT load generator is selwyn's 10G NIC (`NAT_GENERATOR=truenas` keeps the TrueNAS path).
- 2026-11-27: bench / lab roles by `boards.BENCH_UNIT`; hardware flows target the bench unit only.

## Open items (NAT / clock related, `gh issue list --state open`, 2026-11-27)

- #158 productise the zero-copy path (IPv6, new flows, ICMP, fragments, boot defaults).
- #159 608 MHz core garbles the flash console (UART `base_baud` assumes LX 175).
- #160 CPU 1350 at core 608 panics on the OpenWrt image.
- #161 OpenWrt image `nat` path vs plain kernel: regression or bench artefact.
- #162 tooling flakes at the final profile.
- #156 receive floods go dead after 1-3 runs.
- #152 OpenWrt path for the turbo clocks (clk provider, uci profile, fallback).
- #144 sw1 resets under sustained CPU load at CPU 1350.
- #186 sw1 kernel panics under the L3 offload hairpin test.
- #185 OpenWrt main bump to `dee2ff6a77`.
- #66 ASIC-routed traffic and nftables policy.
- #59 L3 offload: IPv4 offload remainder.
- #50 SPI above 25.5 MHz under Linux.
- #48 DDR above 650 MHz (MRS / CWL).
- #85 upstream strategy for switchdev L3.
- #27 build settings vs the MIPS 34Kc.
