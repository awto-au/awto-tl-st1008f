# NAT on the TL-ST1008F (RTL9303): where we are

Target: IPv4 NAT near 2.5 Gbit/s (2500 Mbit/s; owner ISP: NBN HFC ~2 Gbit/s down), issue #65. State as of 2026-11-07.
Run the measurements: [NAT-OPS.md](NAT-OPS.md). Every experiment, dead end and "which combination won": [NAT-HISTORY.md](NAT-HISTORY.md). CPU-port registers and sweeps: [CPU-PORT.md](CPU-PORT.md). No NAT hardware in the die: [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (#68).

## Verdict
- IPv6 is routed by the ASIC: **9.08 Gbit/s at 0 % CPU** (needs the `2000::/3 via <gw>` workaround, #59).
- IPv4 NAT on the skb stack (nftables software flowtable): best **544 Mbit/s** TCP (initramfs, picks clocks), 507 on OpenWrt 7.3; 22 % of target.
- IPv4 NAT on the in-place fast path (`300-39`, prototype): **1.25 Gbit/s** TCP with kernel-fed flows, 1.66 Gbit/s UDP 1400 B; 50-66 % of target. The 1400 B ceiling is not yet explained.
- The ASIC rewrites MACs and TTL only, no IP or L4 port (#58, #68). Every NAT packet crosses the CPU port twice.

## Current data path
- ASIC: L2 switching, L3 routing (MAC rewrite, TTL, checksum; v4 and v6). `::/0` and `0/0` default routes and on-link neighbours trap to the CPU; `300-17` (`l3_default_v4/v6`, `l3_onlink`, opt-in, not measured) adds them ([ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md), #59).
- CPU port: port 28, internal DMA NIC (`rtl838x_eth`), 2 RX + 2 TX rings, RX ring chosen by trap reason (`/sys/kernel/debug/rteth/rxq`, `300-38`). Forwarded traffic is one reason, so ring 1 is idle unless NAPI is pinned per ring.
- Stack path (default): NAPI on VPE0 (64 frames per poll, ~6 IRQ/s at UDP 64 B) -> fraglist GRO (on at boot) -> conntrack + nf_nat -> nftables software flowtable (fw4 `flow_offloading=1`) -> DSA xmit -> `300-27` queue select (control priority ring 1, rest ring 0, no hash) -> TX ring 128, one doorbell per <= 16 frames, reclaim in xmit (`300-12`).
- Driver patches in the path: `300-11` BQL + xmit_more, `300-12` NIC path, `300-13` lowmem fast paths (HIGHMEM, 512 MiB), `300-27`, `300-28` (RX descriptor read through the cache), `300-40` queue-1 threshold. Parked: `300-14`.
- Fast path (`300-39`, `zc=1`, default off): the frame is rewritten in its RX buffer (MACs, VLAN id, TTL, NAT address and port, incremental IP/TCP/UDP checksums) and sent from the same buffer; no skb, GRO, netfilter or qdisc.
  - Flows come from the nftables flowtable (`flags offload`) through DSA `TC_SETUP_FT`: two entries per connection; stats go back so timeouts refresh. Conntrack, new flows, SYN/FIN and expiry stay in the stack.
  - Prototype limits: IPv4 only, DDR buffers, <= 2048 flows, UDP and TCP, no soak.
- Queue-1 threshold (`300-40`): the chip drops at CPU queue 1 (ON/OFF pages); default 1024/1008 (chip boot 78/68).
- IPv6: routed in the ASIC without NAT. IPv6 NAT on the CPU path costs the same as IPv4.

## Best numbers (sw2 unless noted)
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

## Ceilings and what limits them
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

## What works
- Stack path: TCP, UDP, ICMP and fragments follow normal Linux forwarding; TCP and UDP benchmarked, ICMP and fragments not benchmarked.
- Fast path: IPv4 TCP and UDP NAT with kernel-fed flows, both directions. ICMP errors and fragments stay in the stack. IPv6 is not in the fast path.
- IPv6: ASIC-routed far /64 both ways 9070 Mbit/s, `2000::/3` workaround 9079. On-link host to host traps (58.5 Mbit/s) until `300-17` `l3_onlink` is measured.
- ASIC-routed traffic bypasses nftables (#66): `300-37` offloads tc flower `tcp_flags`, a stateless SYN drop on lan1 ingress works.
- Big-endian flowtable issue: `nf_flow_table_offload.c` builds the 16-bit Ethernet address pieces from host-order constants, byte-correct on little-endian only. On this MIPS the 12 address bytes arrive rotated; the driver decodes the four Ethernet entries by numeric value for both byte orders. Candidate upstream report (#85).

## Runtime tunables
| Tunable | Default | Effect |
|---|---|---|
| `rx-gro-list` on eth0 + lan1 | on (image sets it at boot; kernel default off) | off: -29 to -41 % |
| fw4 `flow_offloading` | 1 | off: -74 % |
| eth0 qdisc | `mq` / `pfifo_fast` | `noqueue`: +12-15 % at stock, UDP overload loss 0.1 to 1.2 % |
| `tx_by_cpu` (rteth, runtime) | 0 | ring = CPU number; only with pinned NAPI; not image default until reclaim-at-xmit (#145) |
| threaded NAPI, RPS, IRQ affinity | off | each lost alone ([NAT-HISTORY.md](NAT-HISTORY.md)); `./dev.py nat-knobs list` |
| `cpuq_drop_pages` (rteth, read at open) | 1024 | queue-1 ON pages, OFF = ON - 16; 0 keeps the chip value (78) |
| `zc`, `zc_*` (rteth, runtime) | 0 | in-place fast path and its match / rewrite fields; do not change `zc_ring` under load |
| `sram_rings` (rteth) | 0 | descriptor rings in SRAM; any non-zero value gives no traffic |
| `rx-udp-gro-forwarding` | off | on: worse |
| storm control unknown-unicast | off (#111) | on at 20000 pps capped NAT at ~19 kpps |
| clocks | stock on the flash chain | picks via `ramload ... --pre "turbo cpu=1350,ddr=662,lx=306,sram=500"` or the M3 profile (#109) |

- `turbo` steps: LX 175 / 204 / 245 / 306; CPU 800 / 1000 / 1050 / 1100-1425 in steps of 25; an invalid value rejects the whole profile.
- CPU 1375 gave 1 wrong decode in 55 under load; the pick is 1350 (#109).

## Hazards
- #149: the 7.3 RX path panics in `gro_list_prepare` (NULL deref, ksoftirqd/1). Hit 4 times: at LX 204 right after a network reload, and at LX 306 with `perf record -a` sampling (cpu-clock 2 kHz). Do not run `perf -a` on sw2 at picks. Stock-clock control run not yet done.
- LX 204 under Linux prints garbage on the console (UART rate mismatch) and triggers #149; use 245 or 306.
- Writing `MAC_FORCE_MODE_CTRL(28)` speed bits drops the CPU port; restore `0x217` over the console.
- `300-12` doorbell writes 0 into the other ring's `TX_FETCH`; whether that cancels a pending fetch is undocumented (risk on SMP).
- `tx_by_cpu` reclaims a ring only from its own CPU's NAPI, so skbs of local sockets sent from an idle CPU can wait.
- Fast path: prototype, no soak; ASIC egress-queue drops show as TCP retransmits at saturation.
- Cage loops and fast SPI: see CLAUDE.md hazards.

## Open issues
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

## Sources
- Ceiling and cost model: [CPU-PORT.md](CPU-PORT.md). Datasheet register audit: [DATASHEET-AUDIT.md](DATASHEET-AUDIT.md). Routing offload: [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md). Mainline throughput: [MAINLINE-PORT.md](MAINLINE-PORT.md).
- Raw rows: `tmp/logs/nat_bench.jsonl`, `tmp/logs/nat_knobs.jsonl`.
