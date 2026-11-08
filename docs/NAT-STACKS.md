# NAT and routing across software stacks: audit and gaps

Every measurement that exists per stack, with clocks, date and source. Graphs: [NAT-REPORT.html](NAT-REPORT.html#s10) (section 10; `python3 scripts/nat_report.py`). Final numbers: [NAT.md](NAT.md); conditions per row: [NAT-HISTORY.md](NAT-HISTORY.md).

- Stacks: see the legend below. Table `Stack` column keeps the short names 6.18 / 7.3 / 7.3 I / 7.4 / plain 7.4.
- Clock notation: CPU MHz / switch core MHz. Stock = 800 / 408 (DDR 600, LX 175). Base = 1000 / 408 (DDR 650). Picks = 1350 / 408 (DDR 662, LX 306, SRAM 500). Final = 1325-1350 / 608 (LX 304).
- Metric unless noted: TCP `-P 4` forward through NAT, one-armed over lan1, sw2, cage 1. `nat` = conntrack + masquerade, no flowtable. `nat-ft` = nftables software flowtable (skb stack). `zc` = in-place fast path (`300-39`).
- n/m = not measured. n/a = not applicable.
- "Stock-clock U-Boot era" rows are OpenWrt / mainline booted at stock clocks; the stock firmware itself has no rows (below).

## Stack legend

| Label | Kernel | OpenWrt / userland | Fast path | Rows |
|---|---|---|---|---|
| Stock FW | Linux 3.18.24 | TP-Link stock, Realtek SDK 3.2.0 | none | not measured |
| 6.18: OpenWrt SNAPSHOT r36962 + Linux 6.18.55 (flash image) | 6.18.55 | OpenWrt SNAPSHOT r36962 | none (no `300-17`, no zc) | 2026-10-11 |
| 7.3: OpenWrt main b455c5b851 + Linux 7.3-rc6-next-20261009 (image) | 7.3-rc6 + next-20261009 | OpenWrt main `b455c5b851` (2026-11-04) | zc `300-39`, queue-1 `300-40` | 2026-11-06 |
| 7.3 I: Linux 7.3-rc6 / next-20261009 plain (no OpenWrt) | 7.3-rc6 (10-12), next-20261009 (10-13, 10-15) | bench initramfs, no OpenWrt | `300-11` to `300-35`, per row | 2026-10-12 to 10-15 |
| 7.4: OpenWrt main r38178 + Linux 7.4-rc1 (image) | 7.4-rc1 | OpenWrt main `7e8bfcfe76` = r38178 (2026-11-07) | `300-17` rebased, zc `300-39/40`; L3 fixes rows: image `l3fix2` | 2026-11-07, 11-08 |
| plain 7.4: Linux 7.4-rc1 plain (no OpenWrt) | 7.4-rc1 + series (`uname -r` 7.4.0-rc1-dirty) | bench initramfs: BusyBox 1.31 + OpenWrt 24.10.7 ipks | series incl. zc `300-39/40` | 2026-11-07, 11-08 |

- Evidence: r38178 = `r38178-7e8bfcfe76` in `tmp/logs/l3_offload_ab-20261107-*.txt`; r36962 = NAT-HISTORY.md "Measured (2026-10-11)" conditions; b455c5b, next-20261009: NAT-HISTORY.md "OpenWrt on 7.3"; plain userland: PLAIN-KERNEL-TESTS.md, CAMPAIGN-PLAIN-7.4.md.
- Unknown: OpenWrt revision number (r...) of `b455c5b851` (not recorded). Kernel/userland of the CPU-PORT.md frame-size sweep rows other than 64 B / 1400 B (490.7 and 143.3 kpps were first measured on the 7.3 image, 2026-11-06; the 2026-11-07 sweep does not name its stack). 6.18 2026-10-10 IPv4 hairpin row (ROUTING-OFFLOAD.md): "OpenWrt SNAPSHOT (kernel 6.18)", exact revision unrecorded.
- 6.18 row: docs also record the flash as installed from the 25.12.4 sysupgrade file (OPENWRT-BUILD.md, header `Linux-6.18.55`); the 2026-10-11 conditions in NAT-HISTORY.md name SNAPSHOT r36962, used here. Upstream 25.12.4 initramfs is kernel 6.12.87 and was not used for any NAT row.
- Chart labels (NAT-REPORT.html) use `OpenWrt <rev> / Linux <ver>` compact forms of these rows.

## Stock firmware (TL-ST1008F v2 runtime, Realtek SDK 3.2.0)
| Stack | Test | Result | Clocks / date | Source |
|---|---|---|---|---|
| Stock FW | kernel | Linux 3.18.24 (`RTK_SDK`, extracted from this unit's backup); the 4.4.153 kernel is the SX v2 firmware of other models | - | HISTORY.md 2026-10-08 15:01; FIRMWARE-ANALYSIS.md |
| Stock FW | NAT, IP routing | none: unmanaged firmware, `rc` ends in `diag`, no `/bin/cli`, no netfilter app | - | README.md; artifacts/stock-initramfs-excerpts.md |
| Stock FW | any throughput, CPU load | n/m (no iperf, no IP tools in the initramfs; L2 switching is ASIC) | - | - |

## OpenWrt SNAPSHOT r36962 + Linux 6.18.55 (flash image; 6.18.60 is the flash now, no NAT rows)
| Stack | Test | Result | Clocks / date | Source |
|---|---|---|---|---|
| 6.18 | NAT `nat`, GRO on / off | 80 / 58 Mbit/s | base 1000/408, 2026-10-11 | NAT-HISTORY.md Measured |
| 6.18 | NAT `nat-ft` TCP P4 | 243-248 (3 boots); 228 chain boot; 213-217 GRO off | base; chain boot = stock | same |
| 6.18 | `nat-ft` CPU 800 / DDR 600 / LX 204 / no prefetch | 212 / 239 / 239 / 234 | single variable from base | Clock sensitivity |
| 6.18 | `nat-ft` TCP P1 / P4 (GRO off, chain boot) | 217 / 213 | stock, 2026-10-11 | nat_bench.jsonl `natft-tcp-P1/P4` |
| 6.18 | `nat-ft` UDP 1400 B at 600 offered | 441-460 goodput, 38.1-39.7 kpps, 21-25 % loss | base | nat_bench.jsonl tag `base` |
| 6.18 | `nat-ft` UDP 64 B | 41.9-44.9 kpps | base | same |
| 6.18 | route, no flowtable / flowtable | 62 / 232 | stock, 2026-10-11 | nat_bench.jsonl `route-tcp-P4`, `routeft-tcp-P4` |
| 6.18 | IPv6 gateway-routed in ASIC | 9070-9079 Mbit/s, 0 % CPU (`2000::/3` workaround) | 2026-10-11 | NAT-HISTORY.md IPv6 |
| 6.18 | IPv6 on-link (CPU, trap) | 58.5 | same | same |
| 6.18 | IPv4 gateway-routed hairpin in ASIC | 9190 (8 streams), UDP 9.53 Gbit/s, 0 % CPU | 2026-10-10 | ROUTING-OFFLOAD.md |
| 6.18 | zc fast path, `300-17` offload, final clocks | n/a (not in the 6.18 build) / n/m at final clocks | - | OPENWRT-BUILD.md |

## OpenWrt main b455c5b + Linux 7.3-rc6-next-20261009 (RAM boot `openwrt-ours`; rows marked `7.3 I` = Linux 7.3 plain initramfs, no OpenWrt)
| Stack | Test | Result | Clocks / date | Source |
|---|---|---|---|---|
| 7.3 | `nat` / `nat-ft` v4 (old image, GRO list off) | 77.7 / 203.2 Mbit/s; v6 72.7 / 205.3 | stock, 2026-11-06 | NAT-HISTORY.md OpenWrt on 7.3 |
| 7.3 | `nat-ft` image defaults | 283-294 (stock), 388 (picks); UDP 64 B 53 / 76 kpps | stock, picks 1350, 2026-11-06 | Where we are |
| 7.3 | `nat-ft` best knob combination (+31 %) | 369-377 (stock), 507 (picks); UDP 64 B 59 / 88 kpps | same | Combinations |
| 7.3 | zc, kernel-fed flows TCP P4 fwd / rev | 1250 / 1187; with `300-40`: 1517 / 1519 | picks 1350/408, 2026-11-06 | In-place forward prototype; CPU-PORT.md |
| 7.3 | zc stateless 1:1 NAT TCP P4 | 1340 / 1310 (stack route-only 115 / 129) | picks, 2026-11-06 | same |
| 7.3 | zc UDP 1400 B / 64 B vs stack | 143.3-143.7 / 490.7 kpps vs 21.8 / 22.7 (route, no flowtable) | picks, 2026-11-06 | same |
| 7.3 | L3 offload off / on, on-link v4 / v6, default v4 / v6 | 118 / 9198, 115 / 9032-9138, 118 / 9196, 197 / 9055-9085 | clocks not recorded, 2026-11-06 | ROUTING-OFFLOAD.md |
| 7.3 I | `nat-ft` + `300-11` (gro-list on) | 256-328 TCP; UDP 1400 B 600 offered 0 % loss, 700 / 900 offered 550 / 372 goodput; UDP 64 B 56 kpps | 1000/408, DDR 600, 2026-10-12 | NAT-HISTORY.md Mainline 7.3 |
| 7.3 I | `nat-ft` + `300-12` / `300-13` | 348-358 / 365-370; UDP 1400 B 900 offered 765 goodput | same, 2026-10-12 | NIC path; HIGHMEM |
| 7.3 I | `nat-ft` + series to `300-35`, picks | 528 (544 noqueue); UDP 1400 B 900 offered 899.5; UDP 64 B 110.8 kpps; CPU0 95 %, CPU1 0.6 % | 1350/408, 2026-10-15 | Mainline with today's series |
| 7.3 I | L3 offload off / on, on-link v4 / v6, default v4 / v6 | 355 / 9247, 332 / 9101, 563 / 9255, 534 / 9112-9125 | 1000/408, 2026-10-12 | ROUTING-OFFLOAD.md |
| 7.3 I | TCP P1 vs P4 (`nat-ft`, gro-list) | 289 vs 287 | 1000/408, 2026-10-12 | nat_bench.jsonl |

## OpenWrt main r38178 (7e8bfcfe76) + Linux 7.4-rc1 (RAM boot `openwrt-ours`, built 2026-11-07)
| Stack | Test | Result | Clocks / date | Source |
|---|---|---|---|---|
| 7.4 | `nat` / `nat-ft` / zc TCP P4 fwd (rev) | 85.5 (103) / 267.7 (344) / 1536 (1555) | 1350/508, 2026-11-08 | NAT-HISTORY.md #161; nat161.jsonl |
| 7.4 | `nat` with `rps_cpus=0` | 106.6 / 108.1 | same | #161 partial A/B |
| 7.4 | zc UDP 1400 B vs CPU, core 608 | 161.7 (1000), 160.4 (1200), 160.2 (1275), 170.4 (1325, 5/5); 1350 fails | 608, 2026-11-07 | CAMPAIGN-PLAIN-7.4.md #160 |
| 7.4 | `nat` TCP P4 at 608 / 1325 | 88.9 (one run) | 1325/608 | openwrt_core_stability.jsonl |
| 7.4 | L3 off / on, v4 on-link / default, v6 on-link / default (fwd) | 90 / 9197, 94 / 9201, 86 / 9058, 171 / 9066 | 1325/608, LX 306, 2026-11-08 | NAT-HISTORY.md L3 fixes |
| 7.4 | L3 off / on before the fixes | 86 / 9206 (v4 on-link) | 1350/408, 2026-11-07 | NAT-HISTORY.md L3 offload on the 7.4 base |
| 7.4 | UDP 64 B, stack UDP 1400 B, size sweep, streams, offered load | n/m | - | - |

## Linux 7.4-rc1 plain, no OpenWrt (bench kernel, bench initramfs)
| Stack | Test | Result | Clocks / date | Source |
|---|---|---|---|---|
| plain 7.4 | zc / stack UDP 1400 B | 119.4 / 44.4 kpps | stock 800/408, 2026-11-07 | CAMPAIGN-PLAIN-7.4.md #149 |
| plain 7.4 | zc / stack UDP 1400 B | 142.5-143.8 / 51-63 kpps | picks 1350/408 | same |
| plain 7.4 | size sweep zc 64 / 200 / 500 / 800 / 1100 / 1400 B | 490.7 / 409.6 / 313.6 / 225.6 / 173.0 / 142.5 kpps; rx-only 228.3 ... 143.3 | picks, 2026-11-07 | CPU-PORT.md; CAMPAIGN-PLAIN-7.4.md |
| plain 7.4 | `nat-ft` / zc TCP P4 | 408-413 / 1458-1463 | 1350/408, 2026-11-07 15:57 | nat_bench.jsonl |
| plain 7.4 | `nat` / `nat-ft` / zc TCP P4 fwd (rev) | 240 (311) / 323 (406) / 1565 (1571) | 1350/508, 2026-11-08 | #161 |
| plain 7.4 | `nat-ft` / zc TCP P4 | 422 (414) / 1634 (1631); `nat` 242 | 1350/608, 2026-11-07 | NAT.md; retest_options.jsonl |
| plain 7.4 | zc UDP 1400 B / 64 B; stack 1400 B | 169-171 / 424.5 / 60.2 kpps | 1350/608; CPU 1325: 166.8-170.4 | NAT.md; CAMPAIGN-PLAIN-7.4.md |
| plain 7.4 | L3 off / on, IPv6 routed, offered-load sweep, streams | n/m | - | - |

## Observations
- Stack path on 7.4 is slower than 7.3 at core 408 and picks: plain 7.4 `nat-ft` 408-413 (2026-11-07) vs 7.3 initramfs 528 (544 with noqueue, 2026-10-15). Conditions differ (series to `300-35` vs 7.4 + zc patches, noqueue, offload flag on the flowtable); not an A/B. Gap G4.
- Stock firmware cannot be a NAT or routing data point: the unit's stock image is an unmanaged-switch build. The progression starts at 6.18.
- Over load, `300-11` collapses (UDP 1400 B 900 offered: 372 goodput); `300-12` and later hold the offered rate to 900. CPU0 is 94-96 % busy at every recorded load.

## Gap list: what is missing to complete the comparison
Feasibility is for sw2 with existing tooling. Nothing here has been run. Boots = ramload boots; minutes include setup.

| # | Missing measurement | sw2 with existing tooling? | Run estimate |
|---|---|---|---|
| G1 | Stock FW NAT / routing TCP, CPU load | No value to measure: no NAT or IP routing in the image. A RAM boot of the stock kernel is possible without touching `0x0-0xDFFFF` (`tmp/tftp/stock-kernel.uImage` + `shell-ramdisk.uImage` from `scripts/build_stock_ramboot.py`; `./dev.py stock` gives the stock prompt; then `tftpboot` + `bootm` by hand, no dev.py flow). It has no iperf and no IP tools; a static MIPS BE iperf3 / `udpblast` would have to be built into the ramdisk (new tooling), and stock-kernel netfilter presence is unchecked | not runnable as is; if built: 1 boot, ~10 min after ~1 day of tooling |
| G2 | OpenWrt 6.18 at stock clocks, flash image (`nat`, `nat-ft`, UDP 1400 / 64 B, IPv6) | Yes: `./dev.py` reboot into the flash slot (no relay), then `nat-bench setup` + `run` (as on 2026-10-11) | 0 power-cycles, 1 reboot, ~10 min |
| G3 | OpenWrt 6.18 at final clocks | Yes: `ramload uboot-mainline --stock-clocks --then openwrt-ours-6.18 --pre "turbo cpu=1325,ddr=662,lx=306,sram=500"` + raw core 608 line (the `c608_cpu1325` recipe of `openwrt_core_stability.py`), then `nat-bench`. 6.18 build unproven at core 608; flash profile has no swcore (#159) | 1 boot (2 if it fails), ~12 min |
| G4 | 7.3 vs 7.4 at identical clocks (stack + zc, TCP P4 and UDP) | Yes: `openwrt-ours-7.3` vs `openwrt-ours` at the same `--pre`; `nat161_compare.py` accepts only `plain` / `openwrt` and ramload `--then` lacks `openwrt-ours-7.3` (image key exists): ~10 lines | 2 boots, ~15 min each (3 reps x 4 cells); L3 A/B +21 min per image |
| G5 | Plain 7.4 `nat-ft` with the 7.3 conditions (noqueue, picks, core 408) to explain 408-413 vs 528 | Yes: `nat_knobs.py` / `retest_options.py` on the plain kernel | 1 boot, ~10 min |
| G6 | UDP offered-load sweep (600 / 700 / 900) on 6.18, 7.4 images, plain 7.4 | Stack path: yes (`nat-bench run --udp N --len 1400`). zc path: no, `udpblast` has no rate argument (floods); needs a rate option | stack: 1 boot per stack, ~5 min; zc: tooling first |
| G7 | TCP `-P 1 / 2 / 8` on every stack and on zc | Stack: yes (`nat-bench run -P N`). zc TCP: `zc_bench --tcp` has no `-P` | 1 boot per stack, ~6 min |
| G8 | Frame-size sweep at final clocks and on the images (64 / 200 / 500 / 800 / 1100) | Yes: `zc_bench.py --nat --len N --napi irq1` | 1 boot, ~5 min per stack |
| G9 | Plain 7.4 L3 off / on (v4, v6) | Yes: `nat-bench offload` + `l3_offload_ab.py` on the plain bench kernel | 1 boot, ~10 min |
| G10 | 7.4 image zc TCP and `nat-ft` at final clocks (608 / 1325) | Yes: `nat161_compare.py openwrt` with the 608 raw line | 1 boot, ~15 min |
| G11 | CPU busy per VPE vs offered load on 7.4 and plain | Yes, same run as G6 (rows already carry `cpu`) | included in G6 |

- Minimum set for a same-clock progression (final clocks, one profile): G3 + G4 + G10 + G9: 5 boots, ~1.2 h. G1 needs the owner to decide whether "stock: n/a, no NAT" is accepted.
- No clock on a stack may be compared to another without the clocks in the row: the stack-level bars in the report carry CPU / core under each group.
