# NAT: dated measurements, option tests and image runs 2026-11-07 to 2026-11-23 (history, not comparable)

Moved unchanged from [../NAT.md](../NAT.md) (live state stays there). Sections keep their original conditions; comparisons come only from [../NAT-STACK-RESULTS.md](../NAT-STACK-RESULTS.md). Conclusions: [../FINDINGS.md](../FINDINGS.md).

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

## Numbers at the final settings
Core 608, CPU 1350 / DDR 662 / LX 304 / SRAM 500, sw2, plain 7.4-rc1 bench kernel, cage 1, 2026-11-07. At CPU 1325 the zc+nat 1400 B rate is 166.8-170.4 kpps (plain 168.7-170.3, image 170.4; canary baseline 165.9 under perf, 2026-11-08). Detail: [CAMPAIGN-PLAIN-7.4.md](CAMPAIGN-PLAIN-7.4.md#old-options-re-tested-at-608-mhz-2026-11-07-owner-rule-re-test-after-a-core-clock-move), [FASTEST-SETTINGS.md](../FASTEST-SETTINGS.md).

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

- Different paths and clocks, not noise. Rows: `tmp/logs/nat_bench.jsonl`, `tmp/logs/nat161.jsonl`, [CANARY.md](../CANARY.md).

## OpenWrt r38178 + Linux 7.4-rc1 image vs Linux 7.4-rc1 plain (#161, core 508, CPU 1350, 2026-11-08)
- Image zc+nat is within 2 % of plain (1536 vs 1565 Mbit/s): the fast path works on the image.
- The 83-104 Mbit/s figure is the image on `nat` (conntrack + masquerade, no flowtable); the 413-422 plain figure is `nat-ft`. Different paths.
- Same-core stack rows (Mbit/s fwd / rev): plain `nat` 240 / 311, plain `nat-ft` 323 / 406, image `nat` 85 / 103, image `nat-ft` 268 / 344.
- The image sets `rps_cpus=1` on eth0 (netifd re-applies it), which defeats `--napi irq1`: `rps_cpus=0` gives +39 % fwd / +23 % rev on `nat`. Open: the remaining ~2.2x per packet on `nat` (fw4 hook chains, `fq_codel`, build config).

## What does not help (re-tested at core 608, 2026-11-07/08)
- Second CPU: ring split (par -24 %), NAPI split / threaded (-5 %), per-flow steering: none useful; forwarding stays 97-99 % on VPE1.
- Ties: `tx_by_cpu`, `noqueue`, CPU queue thresholds (78 / 512 / 4095), GRO fraglist off on the fast path.
- Cache variants (`zc_sync_bytes`, `zc_rx_part`, `300-42`): 1400 B within 0.4 %, 64 B -1.4 % / -5.8 %.
- Prefetch (`300-44` `zc_prefetch_desc` / `zc_prefetch_hdr`, CPU 1325): 1400 B within 0.5 %; 64 B descriptor +3.9 %, header -5.7 %; stays off.
- Rings in SRAM: no traffic (NIC DMA does not work from SRAM). SRAM packet buffers: no driver parameter exists.
- Clocks: CPU 1375+ (real limit at 608), DDR 675+ (no gain), LX arbitration patterns, SRAM bridge bits (tie or hang), UDP GRO forwarding (worse), RPS (worse).
- Stack path: GRO fraglist off -35 %; flowtable off -74 %; conntrack / flowtable sysctls within 2 % (#71).
- Testing of DDR and CPU limits is stopped (owner 2026-11-07).


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
