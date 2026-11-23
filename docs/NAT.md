# NAT on the TL-ST1008F (RTL9303): final state

Target: IPv4 NAT at 2.5 Gbit/s (owner ISP: NBN HFC ~2 Gbit/s down), issue #65 (closed). State as of 2026-11-08 (owner decision: go with what works, [DECISIONS.md](DECISIONS.md)).
Graphs and issue board: open rendered with `code-insiders --reuse-window docs/NAT-REPORT.html` (VS Code markdown preview does not open .html links); relative link [NAT-REPORT.html](NAT-REPORT.html); regenerate `python3 scripts/nat_report.py`. Key numbers also in "Graphs" below.
Progression across stacks (stock FW Linux 3.18.24; OpenWrt SNAPSHOT r36962 + Linux 6.18.55; OpenWrt main b455c5b + Linux 7.3-rc6-next-20261009; OpenWrt main r38178 + Linux 7.4-rc1; Linux 7.4-rc1 plain, no OpenWrt), audit, stack legend and gap list: [NAT-STACKS.md](NAT-STACKS.md); graphs [NAT-REPORT.html](NAT-REPORT.html#s10).
- NAT TCP P4, best per stack: OpenWrt r36962 / Linux 6.18.55 248; OpenWrt b455c5b / 7.3-next 507 (skb) / 1519 (zc); OpenWrt r38178 / Linux 7.4-rc1 268 / 1536 (core 508); Linux 7.4-rc1 plain (no OpenWrt) 422 / 1634 (core 608); clocks differ per row.
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
| Switch core | 608 MHz (SW VCO 3650, code 1; e214 `0x478`, e220 `0x36826`) | code 0 (/4 divider) wedges CPU-port DMA; code 1 passes up to 783 MHz live, see CLOCKS.md |
| CPU | **1325 MHz** on the OpenWrt image (5/5 stable); 1350 on the plain kernel | 1350 fails on the image at core 575 / 608 (xz decode errors, Oops, #160); 1375 fails at core 608 |
| DDR | 662 MHz | 675 / 700 pass only with `ddr-retrain --write`, no gain beyond noise |
| LX | ~304 MHz | follows the SW VCO |
| SRAM | 500 MHz | no effect on the NAT rate |

- Per domain: stock | final | why the gap: [FASTEST-SETTINGS.md](FASTEST-SETTINGS.md#final-settings).
- Not default on the flash chain: stock clocks unless the M3 turbo profile is set (#109, #152).
- Flash chain profile stays `cpu=1350,ddr=662,sram=500` without `swcore`: the flash OpenWrt console garbles at LX 304 (UART `base_baud` assumes LX 175, #159). `300-23` (clocks from PLL) is in the 6.18 flash build list, untested.
- Temperature is logged only; there is no 85 C abort (owner 2026-11-07). Idle readings 46-63 C.

## Graphs
Plain-md copy of the HTML report's headline numbers (sw2, cage 1). In this file `image` = OpenWrt main r38178 (`7e8bfcfe76`) + Linux 7.4-rc1, RAM boot; `plain` = Linux 7.4-rc1 + our series, bench initramfs (BusyBox, no OpenWrt). Other stacks: [NAT-STACKS.md](NAT-STACKS.md#stack-legend).

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
| 85 | `nat` | image (OpenWrt r38178 + 7.4-rc1) | 508 |

- Different paths and clocks, not noise. Rows: `tmp/logs/nat_bench.jsonl`, `tmp/logs/nat161.jsonl`, [CANARY.md](CANARY.md).

## OpenWrt r38178 + Linux 7.4-rc1 image vs Linux 7.4-rc1 plain (#161, core 508, CPU 1350, 2026-11-08)
- Image zc+nat is within 2 % of plain (1536 vs 1565 Mbit/s): the fast path works on the image.
- The 83-104 Mbit/s figure is the image on `nat` (conntrack + masquerade, no flowtable); the 413-422 plain figure is `nat-ft`. Different paths.
- Same-core stack rows (Mbit/s fwd / rev): plain `nat` 240 / 311, plain `nat-ft` 323 / 406, image `nat` 85 / 103, image `nat-ft` 268 / 344.
- The image sets `rps_cpus=1` on eth0 (netifd re-applies it), which defeats `--napi irq1`: `rps_cpus=0` gives +39 % fwd / +23 % rev on `nat`. Open: the remaining ~2.2x per packet on `nat` (fw4 hook chains, `fq_codel`, build config).

## What the remaining limit is
- The fast path is CPU-bound: the NIC IRQ + softirq VPE (VPE1) is 97-99 % busy at every size, ~170-180 kpps at 1400 B.
- Cost per packet: ~2 us fixed + a part that follows the switch-core clock (1400 B rate scales with it up to ~500, then the CPU binds; code-0 divider wedges, not the frequency). Not cache maintenance.
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
| eth0 `rps_cpus` | 0 (image: uci `network.globals.packet_steering=0`, `91_st1008f_steering`) | netifd default 1 cost 12-16 % on `nat-ft` (#161) |
| eth0 IRQ affinity | default (both CPUs; no pin) | no effect: zc 1673-1679 Mbit/s and stack 530-590 Mbit/s with the IRQ on CPU0 or CPU1 (matrix below, 2026-11-23); the pin default was removed |
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

- A/B on the flash image (sw2, OpenWrt 7.4-rc3, stock clocks, `nat-ft`, TCP P4, 10 s, 2026-11-21T18:36+11:00, 2 runs per setting): `rps_cpus` 1: 416-432 Mbit/s fwd, 416-430 rev, 120-280 rx drops; `rps_cpus` 0: 477-500 fwd, 477-483 rev, 0 drops; VPE ns/pkt 18.5-18.9 k -> 16.4-16.7 k (#161).
- A/B eth0 root qdisc on the flash image (sw2, 7.4-rc3, stock clocks, `rps_cpus` 0, `nat-ft`, TCP P4, 10 s, 2 runs, 2026-11-21T18:39+11:00): `mq` + `fq_codel` 471-480 Mbit/s fwd and rev, 0 tx drops; `noqueue` 535-554 (+12-15 %), VPE 14.6-14.8 k ns/pkt vs 16.5-16.8 k, tx drops 198-349 per run (~0.5 %, ring full instead of queue). Not made the default: needs a boot hook for a multi-queue device and the tx drops hit local traffic too (#161).
- Core 608 on the flash image (#159, sw2, 7.4-rc3 r38460, `st1008f_turbo=cpu=1325,ddr=662,sram=500,swcore=608` set over ssh, software reboot, 2026-11-21T18:48+11:00): kernel reports `LX frequency from PLL: 304166 kHz`, UART `base_baud = 19010375` (LX/16, matches), console readable, `st1008f-selftest` PASS (clocks cpu=1325 ddr=663 lx=304 sram=500, 22 s). 300-23 plus the U-Boot DTB fixup fix the garbled console. Override cleared afterwards (`turbo off`).

## Flash image 7.4-rc3 (OpenWrt r38178 base), 2026-11-21T21:10-21:15+11:00 (sw2, `nat-bench`/`zc_bench.py`, eth0 IRQ pinned to CPU1 for zc)
| Metric | Core 408, CPU 1350 | Core 608, CPU 1325 |
|---|---|---|
| NAT TCP P4 stack (`nat-ft`) fwd / rev | 446 / 443 Mbit/s | 456-462 / 458 Mbit/s |
| zc+nat 1400 B | 143.9 kpps | 165.6 kpps |
| zc+nat 64 B | not run | 449.9 kpps |
| zc / stack UDP 1400 B | 6.1x | 6.9x |

- `nat-ft` on the image (445-462) matches the plain-kernel rows above (413-422); the image row of 85 Mbit/s (core 508, 7.4-rc1) is gone with the `packet_steering=0` default.
- Eth0 IRQ placement does not matter for zc (retracted 2026-11-23: the earlier +4 % was run-to-run spread); see 'IRQ placement x stream count'.
- A first run right after boot read 124 Mbit/s with CPU1 99 % sys; the repeats are stable.
- `nat-bench setup` prints ping FAIL on the OpenWrt image until `mode` inserts the fw4 accept rules; `mode` then works.

## Flash image on OpenWrt dee2ff6a77 base (#185), 2026-11-22T07:31-07:36+11:00 (sw2, same benches, eth0 IRQ pinned to CPU1 for zc)
| Metric | Core 408, CPU 1350 | Core 608, CPU 1325 |
|---|---|---|
| NAT TCP P4 stack (`nat-ft`) fwd / rev | 488-496 / 489 Mbit/s | 527-528 / 533 Mbit/s |
| zc+nat 1400 B | 144.0 kpps | 164.5 kpps |
| zc+nat 64 B | not run | 448.4 kpps |

- Versus the 2026-11-21 image (27663a017a base, previous table): zc rates unchanged within noise. The stack-path difference (+10 % / +15 %) is not a base effect: see 'Stack path depends on uptime' below.
- Boot-log check clean after allowlist updates (otto_dsa setup print, `left` allmulticast/promiscuous, first-boot jffs2 0xdead marker, watchdog timeout any value).

## zc TCP on the OpenWrt image (#185), 2026-11-22T15:58+11:00 (sw2, core 408, CPU 1350, OpenWrt dee2ff6a77 base, 7.4-rc3, zc=1, eth0 IRQ on CPU1)
- NAT TCP P4 zc+nat fwd / rev: 1509 / 1505 Mbit/s (1509.2, 1509.7, 1505.2; one run each). Plain kernel at core 408 (2026-11-07, 7.4-rc1): 1458 Mbit/s (table above). The ~1.5 Gbit/s zero-copy rate holds on the image.
- Plain-kernel A/B on the new base not run: netboot needs the stock U-Boot to send over cage 1, which is a DAC to sw1 (no TX, #184 relay offline); the attempt rebooted sw2 and left sw1 lan4 stuck in RX calibration (#171, cleared by a sw1 reboot, owner OK).
- Retransmits 1350-1470 per 10 s are the known ASIC CPU-queue drops of the fast path.

## Plain 7.4-rc3 vs OpenWrt image, same patch set, core 608 / CPU 1325 / DDR 662 / LX 304 (#185), 2026-11-23T01:30-01:35+11:00
- Plain kernel booted by `./dev.py netboot mainline-7.4-rc3-clean-std.bin --reboot ssh --port-up 1 --turbo cpu=1325,ddr=662,sram=500,swcore=608` (our U-Boot window over the sw2-lan1 <-> sw1-lan4 DAC, 19 s from the reboot command to ping); OpenWrt image r38513 on the same boot profile. Single runs, eth0 IRQ on CPU1, zc parameters as `stack_compare.py zc_params(tcp)`.

| Metric | Plain 7.4-rc3 | OpenWrt image |
|---|---|---|
| zc+nat UDP 1400 B | 164.0 kpps | 164.5 kpps |
| zc+nat UDP 64 B | 428.6 kpps | 448.4 kpps |
| zc+nat TCP P4 fwd / rev | 1671 / 1671 Mbit/s (3 runs) | 1669 / 1672 Mbit/s (second run of two forward; first 1615 right after boot) |
| stack `nat-ft` TCP P4 fwd / rev | 521-522 / 524 Mbit/s | 527-528 / 533 Mbit/s |

- The ~1.5-1.7 Gbit/s zero-copy rate holds on both; plain and image are within noise at equal clocks.

## Single TCP stream vs 4 streams (2026-11-23T15:20+11:00, sw2 OpenWrt image, core 608 / CPU 1325, eth0 IRQ on CPU1, one 10 s run each)
| Path | P1 | P4 |
|---|---|---|
| stack `nat-ft` fwd | 622.8 Mbit/s (18 retransmits) | 590.3 Mbit/s (125) |
| zc+nat fwd | 1677.5 Mbit/s (117) | 1673.1 Mbit/s (1272) |

- One stream reaches the same rate as four: the limit is the CPU per packet, not the stream count. The stack `nat-ft` rows read 527-533 Mbit/s at P4 on 2026-11-22 and 590 here (same image and clocks); the spread between runs is not explained.

- Correction 2026-11-23: the 2026-11-22 image stack rows (488-496 at core 408, 527-533 at core 608) were measured with the eth0 IRQ on CPU0 and the plain-kernel row with it on CPU1; the pin does not move the stack path, so the 590-623 rows of 2026-11-23 are a boot-to-boot spread, not the pin.

## Stack path depends on uptime, not on the OpenWrt base (2026-11-23)
- Stack `nat-ft` TCP P4 fwd, core 608 / CPU 1325, 10 s runs: first runs after a boot ramp 189 -> 439 -> 528 Mbit/s, then a plateau of 527-536 (six runs, 3 min uptime, previous kernel build 2026-11-21). The new-base image at 2 min uptime (2026-11-22) gave 527-533; the same image at ~16 h uptime gave 577-629 (eth0 IRQ on CPU0 or CPU1: no difference). So the 2026-11-22 "+10-15 % from the new base" came from comparing runs taken at different uptimes. Cause of the uptime effect not found: idle system at both ends (90 % idle, 9 % sys, 59 C).
- Compare stack-path numbers only from the same uptime, after 3 warm-up runs.

## IRQ placement x stream count (2026-11-23T21:04-21:09+11:00, `scripts/irq_stream_matrix.py`, sw2 OpenWrt image, core 608 / CPU 1325, 10 s forward runs, alternating order, warm-up discarded)
| Path | IRQ | 1 stream | 4 streams | 10 streams |
|---|---|---|---|---|
| stack `nat-ft` | CPU0 | 590, 592 | 585, 565 | 531, 537 |
| stack `nat-ft` | CPU1 | 583, 590 | 555, 551 | 542, 547 |
| zc+nat | CPU0 | 633 (first cell, zc not yet engaged), 1678 | 1673, 1678 | 1665, 1662 |
| zc+nat | CPU1 | 1676, 1679 | 1676, 1674 | 1662, 1524 |

- IRQ on CPU0 and CPU1 are indistinguishable (one outlier cell each way); one stream is as fast as four; ten streams cost 5-10 % on the stack path.
- The first zc cell after the zc parameters are set can run on the stack path (633 Mbit/s): discard a warm-up run before a zc cell.
