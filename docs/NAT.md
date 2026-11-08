# NAT on the TL-ST1008F (RTL9303): final state

Target: IPv4 NAT at 2.5 Gbit/s (owner ISP: NBN HFC ~2 Gbit/s down), issue #65 (closed). State as of 2026-11-08 (owner decision: go with what works, [DECISIONS.md](DECISIONS.md)).
Graphs and issue board: open rendered with `code-insiders --reuse-window docs/NAT-REPORT.html` (VS Code markdown preview does not open .html links); relative link [NAT-REPORT.html](NAT-REPORT.html); regenerate `python3 scripts/nat_report.py`. Key numbers also in "Graphs" below.
Progression across stacks (stock FW, OpenWrt 6.18 / 7.3 / 7.4, plain 7.4-rc1), audit and gap list: [NAT-STACKS.md](NAT-STACKS.md); graphs [NAT-REPORT.html](NAT-REPORT.html#s10).
- NAT TCP P4, best per stack: 6.18 248, 7.3 507 (skb) / 1519 (zc), 7.4 image 268 / 1536 (core 508), plain 7.4 422 / 1634 (core 608); clocks differ per row.
- Stock FW has no NAT or routing (unmanaged); no stack has data for every test: 12 test rows, matrix in the report.
- Missing for a same-clock comparison: 6.18 and 7.3 vs 7.4 at final clocks, UDP offered-load and `-P 1/2/8` on 7.4, plain 7.4 L3 (gaps G1-G11).
Run the measurements: [NAT-OPS.md](NAT-OPS.md). Experiments, dead ends, core-408 numbers: [NAT-HISTORY.md](NAT-HISTORY.md). CPU-port registers: [CPU-PORT.md](CPU-PORT.md). No NAT hardware in the die: [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (#68).

## Verdict
- IPv6 and IPv4 routing are done by the ASIC: 9.06-9.20 Gbit/s at ~0 % CPU with `300-17` (on-link rows, default routes), measured on the 7.4 base (#59).
- IPv4 NAT on the in-place fast path (`300-39`, `zc=1`) at the final settings: **1400 B forwarding 169-171 kpps (~1.9 Gbit/s of payload each way), NAT TCP `-P 4` ~1630 Mbit/s each way**; 64 B forwarding 424.5 kpps. About 65 % of the 2.5 Gbit/s target.
- IPv4 NAT on the skb stack (nftables software flowtable, `nat-ft`): TCP `-P 4` 413-422 Mbit/s, 1400 B 60 kpps. Fast path is 2.8x the stack.
- The ASIC rewrites MACs and TTL only, no IP or L4 port (#58, #68). Every NAT packet crosses the CPU port twice.
- 2.5 Gbit/s is not reachable by clocks or driver options (below).

## Final settings (owner 2026-11-07, CPU refined 2026-11-07 by #160)
| Domain | Setting | Notes |
|---|---|---|
| Switch core | 608 MHz (SW VCO 3650, code 1; e214 `0x478`, e220 `0x36826`) | 612 (code 0) wedges CPU-port DMA: forbidden |
| CPU | **1325 MHz** on the OpenWrt image (5/5 stable); 1350 on the plain kernel | 1350 fails on the image at core 575 / 608 (xz decode errors, Oops, #160); 1375 fails at core 608 |
| DDR | 662 MHz | 675 / 700 pass only with `ddr-retrain --write`, no gain beyond noise |
| LX | ~304 MHz | follows the SW VCO |
| SRAM | 500 MHz | no effect on the NAT rate |

- Per domain: stock | final | why the gap: [FASTEST-SETTINGS.md](FASTEST-SETTINGS.md#final-settings).
- Not default on the flash chain: stock clocks unless the M3 turbo profile is set (#109, #152).
- Flash chain profile stays `cpu=1350,ddr=662,sram=500` without `swcore`: the flash OpenWrt console garbles at LX 304 (UART `base_baud` assumes LX 175, #159). `300-23` (clocks from PLL) is in the 6.18 flash build list, untested.
- Temperature is logged only; there is no 85 C abort (owner 2026-11-07). Idle readings 46-63 C.

## Graphs
Plain-md copy of the HTML report's headline numbers (plain 7.4 kernel, sw2, cage 1).

Switch core vs 1400 B rate (zc+nat, 2026-11-07):

| Core MHz | kpps |
|---|---|
| 245 | 87 |
| 306 | 108-110 |
| 408 (stock) | 143.5-144.8 |
| 608 | 169-171 |

Option deltas at core 608 (re-tested, no gain):

| Option | Effect |
|---|---|
| ring split | 123.8 vs 163.6 kpps |
| NAPI split / threaded | -3 to -11 % |
| tx_by_cpu / noqueue / queue thresholds | tie at ~169 kpps |

Paths:

| Path | 1400 B kpps | TCP P4 Mbit/s |
|---|---|---|
| ASIC routing | ~0 % CPU | 9060-9200 |
| zc fast path (`zc=1`) | 169-171 | ~1630 |
| stack, flowtable (`nat-ft`) | 60 | 413-422 |

## Data path
- ASIC: L2 switching, L3 routing (MAC rewrite, TTL, checksum; v4 and v6). `0/0` and `::/0` defaults and on-link neighbours trap to the CPU; `300-17` (`l3_default_v4/v6`, `l3_onlink`, opt-in) adds them ([ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md), #59).
- CPU port: port 28, internal DMA NIC (`rtl838x_eth`), 2 RX + 2 TX rings, RX ring chosen by trap reason (`/sys/kernel/debug/rteth/rxq`, `300-38`). Forwarded traffic is one reason, so ring 1 is idle.
- Fast path (`300-39`, `zc=1`): the frame is rewritten in its RX buffer (MACs, VLAN id, TTL, NAT address and port, incremental IP/TCP/UDP checksums) and sent from the same buffer; no skb, GRO, netfilter or qdisc.
  - Flows come from the nftables flowtable (`flags offload`) through DSA `TC_SETUP_FT`: two entries per connection; stats go back so timeouts refresh. Conntrack, new flows, SYN/FIN, ICMP errors, fragments and expiry stay in the stack.
  - Prototype limits: IPv4 only, DDR buffers, <= 2048 flows, UDP and TCP, no soak. Productising: #158.
- Stack path (zc off): NAPI on VPE0 -> fraglist GRO (on at boot) -> conntrack + nf_nat -> nftables software flowtable (fw4 `flow_offloading=1`) -> DSA xmit -> `300-27` queue select -> TX ring 128, doorbell per <= 16 frames, reclaim in xmit (`300-12`).
- Driver patches in the path: `300-11`, `300-12`, `300-13`, `300-27`, `300-28`, `300-40`, `300-39`. Parked: `300-14`, `300-42` (cache variants), `300-43` (ring split), `300-44` (prefetch).
- One NAT interface only (WAN side + LAN side); no multi-WAN design or tests.

## Numbers at the final settings
Core 608, CPU 1350 / DDR 662 / LX 304 / SRAM 500, sw2, plain 7.4-rc1 bench kernel, cage 1, 2026-11-07. At CPU 1325 the zc+nat 1400 B rate is 166.8-170.4 kpps (plain 168.7-170.3, image 170.4; canary baseline 165.9 under perf, 2026-11-08). Detail: [CAMPAIGN-PLAIN-7.4.md](CAMPAIGN-PLAIN-7.4.md#old-options-re-tested-at-608-mhz-2026-11-07-owner-rule-re-test-after-a-core-clock-move), [FASTEST-SETTINGS.md](FASTEST-SETTINGS.md).

| Metric | Value |
|---|---|
| zc+nat forwarding 1400 B | 169.2-170.7 kpps (VPE1 98 %) |
| zc+nat forwarding 64 B | 424.5 kpps |
| NAT TCP P4 zc+nat fwd / rev | 1634 / 1631 Mbit/s (1620 / 1623 in the combined run) |
| NAT TCP P4 stack (`nat-ft`) fwd / rev | 422 / 413 Mbit/s |
| Stack forwarding 1400 B | 60.2 kpps |
| rx-only 1400 B / 64 B | 172-181 / 220-226 kpps |
| IPv4 / IPv6 routed in the ASIC | 9.06-9.20 Gbit/s at ~345 pps on eth0 (7.4 base, 2026-11-08) |

- Switch core 408 -> 608: zc+nat 1400 B 144.8 -> 169-171 kpps (+17 %), TCP P4 1458 -> 1634 (+12 %); 64 B unchanged (VPE-bound).
- Flash OpenWrt 6.18 and 7.3 stack numbers, core-408 rows: [NAT-HISTORY.md](NAT-HISTORY.md).
- Fast-path TCP rows lose frames at the ASIC CPU queue (retransmits), not in the fast path.

## Stack TCP numbers: which path and clock
| Mbit/s (fwd) | Path | Image | Switch core |
|---|---|---|---|
| 413-422 | `nat-ft` (flowtable) | plain | 608 |
| 323 | `nat-ft` | plain | 508 |
| 242 | `nat` (conntrack, no flowtable) | plain | 608 (canary boots) |
| 240 | `nat` | plain | 508 |
| 85 | `nat` | OpenWrt image | 508 |

- Different paths and clocks, not noise. Rows: `tmp/logs/nat_bench.jsonl`, `tmp/logs/nat161.jsonl`, [CANARY.md](CANARY.md).

## OpenWrt image vs plain kernel (#161, core 508, CPU 1350, 2026-11-08)
- Image zc+nat is within 2 % of plain (1536 vs 1565 Mbit/s): the fast path works on the image.
- The 83-104 Mbit/s figure is the image on `nat` (conntrack + masquerade, no flowtable); the 413-422 plain figure is `nat-ft`. Different paths.
- Same-core stack rows (Mbit/s fwd / rev): plain `nat` 240 / 311, plain `nat-ft` 323 / 406, image `nat` 85 / 103, image `nat-ft` 268 / 344.
- The image sets `rps_cpus=1` on eth0 (netifd re-applies it), which defeats `--napi irq1`: `rps_cpus=0` gives +39 % fwd / +23 % rev on `nat`. Open: the remaining ~2.2x per packet on `nat` (fw4 hook chains, `fq_codel`, build config).

## What the remaining limit is
- The fast path is CPU-bound: the NIC IRQ + softirq VPE (VPE1) is 97-99 % busy at every size, ~170-180 kpps at 1400 B.
- Cost per packet: ~2 us fixed + a part that follows the switch-core clock (1400 B rate scales with it up to 608; 612 is forbidden). Not cache maintenance.
- 2.5 Gbit/s of 1500 B frames is ~312 kpps through the CPU port (data + ACKs); the fast path does ~170-180 kpps. Clocks cannot close it: CPU above 1350 fails at 608, DDR 675+ gives no gain, LX / SRAM do not move the rate.
- `rxdrop` (receive and drop) stops at about the same rate at 1400 B: the limit is receive-side, not the NAT rewrite.

## What does not help (re-tested at core 608, 2026-11-07/08)
- Second CPU: ring split (par -24 %), NAPI split / threaded (-5 %), per-flow steering: none useful; forwarding stays 97-99 % on VPE1.
- Ties: `tx_by_cpu`, `noqueue`, CPU queue thresholds (78 / 512 / 4095), GRO fraglist off on the fast path.
- Cache variants (`zc_sync_bytes`, `zc_rx_part`, `300-42`): 1400 B within 0.4 %, 64 B -1.4 % / -5.8 %.
- Prefetch (`300-44` `zc_prefetch_desc` / `zc_prefetch_hdr`, CPU 1325): 1400 B within 0.5 %; 64 B descriptor +3.9 %, header -5.7 %; stays off.
- Rings in SRAM: no traffic (NIC DMA does not work from SRAM). SRAM packet buffers: no driver parameter exists.
- Clocks: CPU 1375+ (real limit at 608), DDR 675+ (no gain), LX arbitration patterns, SRAM bridge bits (tie or hang), UDP GRO forwarding (worse), RPS (worse).
- Stack path: GRO fraglist off -35 %; flowtable off -74 %; conntrack / flowtable sysctls within 2 % (#71).
- Testing of DDR and CPU limits is stopped (owner 2026-11-07).

## What works
- Stack path: TCP, UDP, ICMP and fragments follow normal Linux forwarding; TCP and UDP benchmarked.
- Fast path: IPv4 TCP and UDP NAT with kernel-fed flows, both directions. IPv6 is not in the fast path.
- Routing offload (`300-17`, 7.4 base, #59): checks a-g and i pass (neighbour delete / MAC change, covering prefix, local `/32`, `ip rule`, source-specific `::/0`, 120 s run, all params 0); v4 `rt_offload` clears when `l3_default_v4` goes 1 -> 0. Check h fails: DIP `0.0.0.1` is forwarded (needs a trap row for `0.0.0.0/8`).
- ASIC-routed traffic bypasses nftables (#66): `300-37` offloads tc flower `tcp_flags`, a stateless SYN drop on lan1 ingress works.
- Big-endian flowtable issue: `nf_flow_table_offload.c` builds the 16-bit Ethernet address pieces from host-order constants, byte-correct on little-endian only. The driver decodes the four Ethernet entries by numeric value for both byte orders. Candidate upstream report (#85).

## Runtime tunables
| Tunable | Default | Effect |
|---|---|---|
| `rx-gro-list` on eth0 + lan1 | on (image sets it at boot) | off: -29 to -41 % on the stack path |
| fw4 `flow_offloading` | 1 | off: -74 % |
| eth0 `rps_cpus` | image 1, plain 0 | image: defeats `--napi irq1`; 0 gives +23-39 % on `nat` (#161) |
| eth0 qdisc | `mq` / `pfifo_fast` (image `fq_codel`) | `noqueue`: +12-15 % on the stack at stock clocks, ties on zc |
| `tx_by_cpu` (rteth) | 0 | stack path with pinned NAPI only (#145) |
| `cpuq_drop_pages` (rteth, read at open) | 1024 | queue-1 ON pages, OFF = ON - 16; 0 keeps the chip value (78) |
| `zc`, `zc_*` (rteth, runtime) | 0 | in-place fast path and its match / rewrite fields; do not change `zc_ring` under load |
| `sram_rings` (rteth) | 0 | any non-zero value gives no traffic |
| `rx-udp-gro-forwarding` | off | on: worse |
| storm control unknown-unicast | off (#111) | on at 20000 pps capped NAT at ~19 kpps |
| clocks | stock on the flash chain | final settings via `ramload ... --pre "turbo cpu=1325,ddr=662,lx=304,sram=500"` after the core is set, or the M3 profile (#109) |

- `turbo` steps: LX 175 / 204 / 245 / 306; CPU 800 / 1000 / 1050 / 1100-1425 in steps of 25; an invalid value rejects the whole profile.

## Hazards
- #149: the 7.3 OpenWrt RX path panicked in `gro_list_prepare` (NULL deref) at LX 204 / 245 and with `perf record -a` (2/5 boots at CPU 1350); not seen on plain 7.4 (0/9). Use LX 245 or higher; no `perf -a` on sw2 at the final settings.
- #160: CPU 1350 at core 575 / 608 on the OpenWrt image corrupts computation (xz decode errors, Oops at 32-53 s). Use CPU 1325 there.
- #163: the OpenWrt boot selftest resets the SoC when `st1008f-stx` is missing; `build_openwrt` now fails without the helper.
- LX 204 and LX 304 under Linux print garbage on the flash console (UART rate mismatch, #159).
- Writing `MAC_FORCE_MODE_CTRL(28)` speed bits drops the CPU port; restore `0x217` over the console.
- `300-12` doorbell writes 0 into the other ring's `TX_FETCH`; whether that cancels a pending fetch is undocumented (risk on SMP).
- Fast path: prototype, no soak; ASIC egress-queue drops show as TCP retransmits at saturation.
- Receive floods can go dead after 1-3 runs (#156). Tooling flakes at the final profile (#162). Cage loops and fast SPI: see CLAUDE.md hazards.

## Open issues
- Full board with status and next step: [NAT-REPORT.html](NAT-REPORT.html#s8).
- NAT / clock: #158 productise zc, #159 flash console at LX 304, #160 CPU 1350 on the image, #161 image `nat` ~2.2x, #162 tooling flakes, #163 selftest helper, #156, #149, #147, #66, #59 (check h, notifier updates), #48 (DDR above 650), #22.
- Closed in this campaign: #65, #71, #103, #140, #145, #146, #148, #151, #28.

## Sources
- Ceiling and cost model: [CPU-PORT.md](CPU-PORT.md). Datasheet audit: [DATASHEET-AUDIT.md](DATASHEET-AUDIT.md). Routing offload: [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md). Mainline throughput: [MAINLINE-PORT.md](MAINLINE-PORT.md). Canary baseline: [CANARY.md](CANARY.md).
- Raw rows: `tmp/logs/nat_bench.jsonl`, `tmp/logs/nat_knobs.jsonl`, `tmp/logs/fastest_search_core608.csv`, `tmp/logs/retest_options.jsonl`, `tmp/logs/nat161.jsonl`, `tmp/logs/zc_prefetch_ab.jsonl`, `tmp/logs/openwrt_core_stability.jsonl`.
