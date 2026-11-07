# NAT on the TL-ST1008F (RTL9303): final state

Target: IPv4 NAT at 2.5 Gbit/s (owner ISP: NBN HFC ~2 Gbit/s down), issue #65. State as of 2026-11-07 (owner decision: go with what works, [DECISIONS.md](DECISIONS.md)).
Run the measurements: [NAT-OPS.md](NAT-OPS.md). Experiments, dead ends, core-408 numbers: [NAT-HISTORY.md](NAT-HISTORY.md). CPU-port registers: [CPU-PORT.md](CPU-PORT.md). No NAT hardware in the die: [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (#68).

## Verdict
- IPv6 is routed by the ASIC: 9.08 Gbit/s at 0 % CPU (needs the `2000::/3 via <gw>` workaround or `300-17`, #59).
- IPv4 NAT on the in-place fast path (`300-39`, `zc=1`) at the final settings: **1400 B forwarding 169-171 kpps (~1.9 Gbit/s of payload each way), NAT TCP `-P 4` ~1630 Mbit/s each way**; 64 B forwarding 424.5 kpps. About 65 % of the 2.5 Gbit/s target.
- IPv4 NAT on the skb stack (nftables software flowtable): TCP `-P 4` 413-422 Mbit/s, 1400 B 60 kpps. Fast path is 2.8x the stack.
- The ASIC rewrites MACs and TTL only, no IP or L4 port (#58, #68). Every NAT packet crosses the CPU port twice.
- 2.5 Gbit/s is not reachable by clocks (below).

## Final settings (owner 2026-11-07)
| Domain | Setting | Notes |
|---|---|---|
| Switch core | 608 MHz (SW VCO 3650, code 1; e214 `0x478`, e220 `0x36826`) | 612 (code 0) wedges CPU-port DMA: forbidden |
| CPU | 1350 MHz | 1375 passes at core 408, fails at core 608 |
| DDR | 662 MHz | 675 / 700 pass only with `ddr-retrain --write`, no gain beyond noise |
| LX | ~304 MHz | follows the SW VCO |
| SRAM | 500 MHz | no effect on the NAT rate |

- Per domain: stock | final | why the gap: [FASTEST-SETTINGS.md](FASTEST-SETTINGS.md#final-settings).
- Not default on the flash chain: stock clocks unless the M3 turbo profile is set (#109, #152).

## Data path
- ASIC: L2 switching, L3 routing (MAC rewrite, TTL, checksum; v4 and v6). `0/0` and `::/0` defaults and on-link neighbours trap to the CPU; `300-17` (`l3_default_v4/v6`, `l3_onlink`, opt-in) adds them ([ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md), #59).
- CPU port: port 28, internal DMA NIC (`rtl838x_eth`), 2 RX + 2 TX rings, RX ring chosen by trap reason (`/sys/kernel/debug/rteth/rxq`, `300-38`). Forwarded traffic is one reason, so ring 1 is idle.
- Fast path (`300-39`, `zc=1`): the frame is rewritten in its RX buffer (MACs, VLAN id, TTL, NAT address and port, incremental IP/TCP/UDP checksums) and sent from the same buffer; no skb, GRO, netfilter or qdisc.
  - Flows come from the nftables flowtable (`flags offload`) through DSA `TC_SETUP_FT`: two entries per connection; stats go back so timeouts refresh. Conntrack, new flows, SYN/FIN, ICMP errors, fragments and expiry stay in the stack.
  - Prototype limits: IPv4 only, DDR buffers, <= 2048 flows, UDP and TCP, no soak.
- Stack path (zc off): NAPI on VPE0 -> fraglist GRO (on at boot) -> conntrack + nf_nat -> nftables software flowtable (fw4 `flow_offloading=1`) -> DSA xmit -> `300-27` queue select -> TX ring 128, doorbell per <= 16 frames, reclaim in xmit (`300-12`).
- Driver patches in the path: `300-11`, `300-12`, `300-13`, `300-27`, `300-28`, `300-40`, `300-39`. Parked: `300-14`, `300-42` (cache variants), `300-43` (ring split).
- One NAT interface only (WAN side + LAN side); no multi-WAN design or tests.

## Numbers at the final settings
Core 608, CPU 1350 / DDR 662 / LX 304 / SRAM 500, sw2, plain 7.4-rc1 bench kernel, cage 1, 2026-11-07. Detail and baselines: [CAMPAIGN-PLAIN-7.4.md](CAMPAIGN-PLAIN-7.4.md#old-options-re-tested-at-608-mhz-2026-11-07-owner-rule-re-test-after-a-core-clock-move), [FASTEST-SETTINGS.md](FASTEST-SETTINGS.md).

| Metric | Value |
|---|---|
| zc+nat forwarding 1400 B | 169.2-170.7 kpps (VPE1 98 %) |
| zc+nat forwarding 64 B | 424.5 kpps |
| NAT TCP P4 zc+nat fwd / rev | 1634 / 1631 Mbit/s (1620 / 1623 in the combined run) |
| NAT TCP P4 stack fwd / rev | 422 / 413 Mbit/s |
| Stack forwarding 1400 B | 60.2 kpps |
| rx-only 1400 B / 64 B | 172-181 / 220-226 kpps |
| IPv6 routed in the ASIC | 9079 Mbit/s at 0 % CPU (2026-10-11, base clocks) |

- Switch core 408 -> 608: zc+nat 1400 B 144.8 -> 169-171 kpps (+17 %), TCP P4 1458 -> 1634 (+12 %); 64 B unchanged (VPE-bound).
- Flash OpenWrt 6.18 and 7.3 stack numbers, core-408 rows: [NAT-HISTORY.md](NAT-HISTORY.md).
- Fast-path TCP rows lose frames at the ASIC CPU queue (retransmits), not in the fast path.

## What the remaining limit is
- The fast path is CPU-bound: the NIC IRQ + softirq VPE (VPE1) is 97-99 % busy at every size, ~170-180 kpps at 1400 B.
- Cost per packet: ~2 us fixed + a part that follows the switch-core clock (1400 B rate scales with it up to 608; 612 is forbidden).
- 2.5 Gbit/s of 1500 B frames is ~312 kpps through the CPU port (data + ACKs); the fast path does ~170-180 kpps. Clocks cannot close it: CPU 1375+ fails at 608, DDR 675+ gives no gain, LX / SRAM do not move the rate.
- `rxdrop` (receive and drop) stops at about the same rate at 1400 B: the limit is receive-side, not the NAT rewrite.

## What does not help (re-tested at core 608, 2026-11-07)
- Second CPU: ring split (par -24 %), NAPI split / threaded (-3 to -7 %), per-flow steering: none useful; forwarding stays 97-99 % on VPE1.
- Ties: `tx_by_cpu`, `noqueue`, CPU queue thresholds (78 / 512 / 4095), GRO fraglist off on the fast path, cache variants (`zc_sync_bytes`, `zc_rx_part`).
- Rings in SRAM: no traffic (NIC DMA does not work from SRAM). SRAM packet buffers: no driver parameter exists.
- Clocks: CPU 1375+ (real limit at 608), DDR 675+ (no gain), LX arbitration patterns, SRAM bridge bits (tie or hang), UDP GRO forwarding (worse), RPS (worse).
- Stack path: GRO fraglist off -35 %; flowtable off -74 %.
- Testing of DDR and CPU limits is stopped (owner 2026-11-07).

## What works
- Stack path: TCP, UDP, ICMP and fragments follow normal Linux forwarding; TCP and UDP benchmarked.
- Fast path: IPv4 TCP and UDP NAT with kernel-fed flows, both directions. IPv6 is not in the fast path.
- IPv6: ASIC-routed far /64 both ways 9070 Mbit/s, `2000::/3` workaround 9079. On-link host to host traps (58.5 Mbit/s) until `300-17` `l3_onlink` is measured.
- ASIC-routed traffic bypasses nftables (#66): `300-37` offloads tc flower `tcp_flags`, a stateless SYN drop on lan1 ingress works.
- Big-endian flowtable issue: `nf_flow_table_offload.c` builds the 16-bit Ethernet address pieces from host-order constants, byte-correct on little-endian only. The driver decodes the four Ethernet entries by numeric value for both byte orders. Candidate upstream report (#85).

## Runtime tunables
| Tunable | Default | Effect |
|---|---|---|
| `rx-gro-list` on eth0 + lan1 | on (image sets it at boot) | off: -29 to -41 % on the stack path |
| fw4 `flow_offloading` | 1 | off: -74 % |
| eth0 qdisc | `mq` / `pfifo_fast` | `noqueue`: +12-15 % on the stack at stock clocks, ties on zc |
| `tx_by_cpu` (rteth) | 0 | stack path with pinned NAPI only (#145) |
| `cpuq_drop_pages` (rteth, read at open) | 1024 | queue-1 ON pages, OFF = ON - 16; 0 keeps the chip value (78) |
| `zc`, `zc_*` (rteth, runtime) | 0 | in-place fast path and its match / rewrite fields; do not change `zc_ring` under load |
| `sram_rings` (rteth) | 0 | any non-zero value gives no traffic |
| `rx-udp-gro-forwarding` | off | on: worse |
| storm control unknown-unicast | off (#111) | on at 20000 pps capped NAT at ~19 kpps |
| clocks | stock on the flash chain | final settings via `ramload ... --pre "turbo cpu=1350,ddr=662,lx=304,sram=500"` after the core is set, or the M3 profile (#109) |

- `turbo` steps: LX 175 / 204 / 245 / 306; CPU 800 / 1000 / 1050 / 1100-1425 in steps of 25; an invalid value rejects the whole profile.

## Hazards
- #149: the 7.3 OpenWrt RX path panics in `gro_list_prepare` (NULL deref) at LX 204 and with `perf record -a`; not seen on plain 7.4. Do not run `perf -a` on sw2 at the final settings; use LX 245 or higher.
- LX 204 under Linux prints garbage on the console (UART rate mismatch).
- Writing `MAC_FORCE_MODE_CTRL(28)` speed bits drops the CPU port; restore `0x217` over the console.
- `300-12` doorbell writes 0 into the other ring's `TX_FETCH`; whether that cancels a pending fetch is undocumented (risk on SMP).
- Fast path: prototype, no soak; ASIC egress-queue drops show as TCP retransmits at saturation.
- Receive floods can go dead after 1-3 runs (#156). Cage loops and fast SPI: see CLAUDE.md hazards.

## Open issues
| Issue | State |
|---|---|
| #65 Fast NAT umbrella | final state above; closes with the worklist in `tmp/close-worklist.md` |
| #140 fast path prototype | works; open: IPv6, fragments, soak, upstream shape |
| #145 knob combination as image default | stack-path default; zc is off by default |
| #71 NAT path review | knobs, profile, call graph done; conntrack function costs and sysctl A/B open |
| #59 L3 offload | `300-17` measured at ~9.1 Gbit/s; v4 flags reported; notifier updates open |
| #66 ASIC-routed bypasses nftables | SYN drop works; UDP policy, ICMPv6, PIE capacity open |
| #22 all-port wire-speed routed test | open |
| #149, #156 | RX panic on OpenWrt 7.3; receive floods dead after 1-3 runs |

## Sources
- Ceiling and cost model: [CPU-PORT.md](CPU-PORT.md). Datasheet audit: [DATASHEET-AUDIT.md](DATASHEET-AUDIT.md). Routing offload: [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md). Mainline throughput: [MAINLINE-PORT.md](MAINLINE-PORT.md).
- Raw rows: `tmp/logs/nat_bench.jsonl`, `tmp/logs/nat_knobs.jsonl`, `tmp/logs/fastest_search_core608.csv`, `tmp/logs/retest_options.jsonl`.
