# Fastest stable settings: search plan (owner priority 2026-11-07)

Goal: fastest stable setting in every limiting domain, then load-test the best combination.
Tools: `./dev.py fastest-search` (scripts/fastest_search.py), `./dev.py load-test` (scripts/load_test.py). sw2 only; sw1 never.

## Final settings
Owner decision 2026-11-07 (CPU 1325 by owner choice 2026-11-08): go with what works; DDR and CPU limit testing stopped. Evidence: sections "Results 2026-11-07 (core 608)" and "CPU 1375+ and DDR 675+: lock or limit" below. Format: rated max | board | we run | why the gap.

| Domain | Stock | Final | Why the gap |
|---|---|---|---|
| Switch core | 408 MHz | 608 | 612 (code 0) wedges CPU-port DMA; 608 is the best-forwarding step (575 / 658 re-code LX); 1400 B rate scales with the core up to 608 |
| CPU | 800 | 1325 | highest step stable 5/5 on the OpenWrt image at core 608 (#160); 1350 passes short plain-kernel runs but fails the image at core 575 / 608; 1375 panics at core 608 (passes at 408) |
| DDR | 600 | 662 | 675 / 700 pass only with `ddr-retrain --write` and give no gain beyond noise |
| LX | 175 | ~304 | follows the SW VCO; 204 panics on the 7.3 image (#149); codes above 306 need a clocks.c change |
| SRAM | 250 | 500 | already the maximum; no measurable effect on the NAT rate |
| SPI (Linux) | 25.5 MHz | 23.4 (follows core 608) | fast SPI corrupts reads under Linux (#50) |

- Result: 1400 B zc+nat 169-171 kpps, NAT TCP P4 ~1630 Mbit/s ([NAT.md](NAT.md)).

## Scope and rules
- ONE NAT interface only (the `nat-bench setup` pair: one WAN side, one LAN side). No multi-WAN, no multi-interface case, in any bench or load test.
- Range = stock (known good) .. fastest programmable. Binary search from the midpoint; pass -> higher, fail/hang -> lower. Fastest viable = passes ONE quick test. No repeats during the sweep.
- Overview table per domain first; discuss with the owner before repeats or making anything a default.
- Software reboot only (`reset` / `reboot`, via `st1008_ramload.restart_board`); relay only if no prompt answers. No soaks: short functional runs.
- Other domains stay at the picks (CPU 1350, DDR 662, LX 306, SRAM 500) while one domain is searched. Picks: `docs/CAMPAIGN-PLAIN-7.4.md` clock sets.
- Every point power-cycles: the quick test needs the kernel booted (the CPU-port rate is only measurable in Linux), so the U-Boot-only session mode of `clocks-cycle --session` does not apply.

## Quick test (ONE per point)
| step | what | why / cap |
|---|---|---|
| 1 | `ramload uboot-mainline --then mainline-kernel --cage 1 --mgmt --pre <settings>` | kernel unlzma + initramfs XZ catch CPU faults crc32 misses (#103); stall 60 s, total 240 s (canary plain_boot) |
| 2 | ssh + temperature + `bogomips` | proves the clocks took (531 = 800, 664 = 1000, ~897 = 1350) |
| 3 | `ceiling_rxtx --sizes 64,1400 --modes rx --secs 6 --n 1` | 1400 B = switch-core limit, 64 B = VPE limit; 6 s: spread 0.3-0.5 % at 6 s runs (#147); stall 60 s, total 120 s |
| 4 | `zc_bench --integrity` (udpcheck 1400/500/64) | silent corruption; stall 60 s, total 90 s |
| 5 | link alive (ping + ssh), temperature, console scan | `Oops|BUG|Kernel panic|gro_list_prepare` (#149) |

- Pass: boot reaches ssh; rx 1400 B >= 5 kpps (one retry only for a stalled flood, a harness artefact of #147, never for noise); integrity PASS; link alive after; console clean (temperature logged only).
- Fail: any of the above false and link alive. Hang: no ssh after ramload, or link dead after the test. Both -> next lower point.
- Scan domains (no monotone knob): pass AND 1400 B rx >= 1.03 x 143.3 kpps (picks, #147) = "gain"; the best gain wins. 1.03 = 6x the 0.5 % spread.
- Hang recovery: the next point's ramload restarts in software; relay fallback is logged by `restart_board`.
- No temperature abort (owner 2026-11-07); temperature is logged. Heat: CPU/DDR/switch-core PLL raises are the heat sources; idle readings were 31-48 C (OVERCLOCK.md, CAMPAIGN-PLAIN-7.4.md), quantised 1.3 C.
- Time per point ~150 s (estimate: boot ~45 s, setup 8 s, 2 x rx ~12 s, integrity ~25 s, reads ~15 s; replace with `tmp/logs/fastest_search.log` timings).

## Domains, in order of expected value
| # | domain | knob | stock | pick | range / steps |
|---|---|---|---|---|---|
| 1 | switch-core | SW VCO `e214` NCODE + `e220[8:5]` + relock `e200` b30 | 408 MHz | 408 | 408, 450, 500, 550, 600, 612 |
| 2 | lx-arb | `LX0..2_ARB_CFG0-3` `0xB8000010-3C` | `0x10101010` | stock | stock, swap, m1, m0 (scan) |
| 3 | cpu | `turbo cpu=` | 800 | 1350 | 800, 1000, 1050, 1100..1425 step 25 |
| 4 | ddr | `turbo ddr=` | 600 | 662 | 600, 625, 650, 662, 675 .. 800 |
| 5 | sram / bridge | `0x40f8`, CMUCR_OC0 `0xb8000388` b9 | 250 | 500 | stock, pulse_dn, pulse_up, oc0_dram_flip (scan) |

1. switch-core (largest measured lever: 1400 B rate scales 1:1 with the clock, CAMPAIGN-PLAIN-7.4.md; #148 findings in docs/CLOCKS.md).
   - Steps = stock 408 (VCO 2450, code 1) then VCO steps with code 1 (/6): 508 (VCO 3050), 575 (3450), 608 (3650), 658 (3950). Each passed 3/3 boots.
   - Raw words (e214 / e220), also U-Boot `swcore=`: 508 `0x3b8`/`0x30626`; 575 `0x438`/`0x34a26`; 608 `0x478`/`0x36826`; 658 `0x4d8`/`0x38c26` (`fastest_search.SWC`, `swcore_step.py`).
   - 612 via code 0 (VCO 2450) wedges CPU-port DMA under forwarding: forbidden, not a step. 608 = recommended max (best forwarding); 575/658 re-code LX to 246/247 MHz.
   - LX and SPI-NOR share the SW VCO: the e220 words re-code them. e214 garbles the UART until e220 re-codes LX: one line, e220 first, relock last.
2. lx-arb: register-only, cheap. Master IDs and the NIC's bus are unknown (DATASHEET-AUDIT.md:185); candidates are blunt patterns written to all 12 words: `swap` 0x01010101, `m1` 0x11111111, `m0` 0x00000000. Expected effect is small unless another LX master competes. `--discover` records the reset values first.
3. cpu: pick 1350; 1375 failed 1 of 55 XZ decodes, 1400 fails. Bisection 800..1425 starts at 1100 (known passes), ~6 tests. Expected gain beyond 1350 <= 2 %; 64 B rate is VPE-bound, so it follows the CPU.
4. ddr: pick 662. 700 passes only with the MRS bin + per-DQ read/write retrain (DRAM.md (d')); 725+ fail. `turbo ddr=700` may not apply the trained taps: confirm in clocks.c before reading 675+ results; otherwise run `./dev.py ddr-retrain --mhz V` first (U-Boot-only gate). Expected gain <= 4 % (600 -> 650 moved every test <= 4 %).
5. sram / bridge bits: SRAM 500 is already the max. Candidates need the live values (`--discover`): `pulse_dn` / `pulse_up` = `0x40f8` `oc0_sram_pulse` [1:0] -1 / +1; `oc0_dram_flip` = CMUCR_OC0 SE_DRAM bit 9 flipped (rule MEM >= CPU/2: 662 < 675 at CPU 1350, so the constant may be wrong, OVERCLOCK.md). Expected effect: small; risk of a hang.

Not searched: LX frequency (pick 306; 204 triggered #149 on OpenWrt; codes above 306 need a clocks.c change), SPI (stock under Linux, #50: fast SPI = U-Boot-only sessions), CPU/DDR combinations beyond the combine step.

## Combination step
1. `fastest-search --combine`: best viable of each domain together, one quick test.
2. Fail -> drop the least valuable domain first: sram, ddr, cpu, lx-arb, switch-core (reverse of the table); retest after each drop.
3. The passing string is printed as `--settings` for `load-test`.

## Load test (`load-test --settings S`)
| stage | run | stall / total | verdict rule |
|---|---|---|---|
| boot | ramload at S | 60 / 240 s | reaches ssh; bogomips logged |
| sanity | nat-bench setup, mgmt ping, ARP + ICMP natlan -> natwan | 40 / 90 s | all rc 0 |
| tcp_fwd / tcp_rev | `nat-bench run --secs 10 -P 4` (+ `--reverse`) | 60 / 120 s | < 0.9 x baseline FAIL, < 0.97 WARN |
| udp1400 / udp64 | `zc_bench --nat --zc-only --napi irq1 --secs 6 --len L` | 60 / 100 s | same rule vs baseline |
| integrity | `zc_bench --integrity` | 60 / 90 s | PASS only |
| canary | `canary --only pre,selftest,gdma,dss,bootlog --no-ramload` | 60 / 300 s | rc 0 |
| flaps / temperature / console | carrier_changes delta; thermal_zone0; log scan | - | flaps WARN; temperature logged only; any Oops/BUG/panic/gro_list_prepare FAIL |

- ASIC drop counters (`drop_counters`) logged per TCP and UDP stage; rows in `tmp/logs/load_test.csv`.
- Baselines (CAMPAIGN-PLAIN-7.4.md): picks zc 1400 B 143.0 kpps, rx-only 1400 B 143.3, rx-only 64 B 228.3, stack 62.1; stock zc 119.4, stack 44.4. TCP P4 has no number in the docs: the first run becomes the baseline.
- Estimated runtime ~8 min plus the canary subset ~2 min. Options stage below adds ~1.5 min per runtime variant and ~3 min per boot variant.

## Old options re-test (after any new best switch-core clock)
Earlier options lost while the 408 MHz switch-core "door" was the limit. With a faster door the CPU can become the limit, so the second CPU (VPE1) may win. Every option is re-run at each new best core setting, against a baseline of the same session (same boot, same clocks, default state).

- `load-test --settings S --core <MHz> --options all|retest|name,...`. `retest` = options whose last verdict at 408 was not "wins".
- Rule: an option that tied or lost at 408 is re-run at every new best core setting. Rows: `tmp/logs/load_test_options.csv`; table via `load-test --options-table`.
- Verdict: wins >= 1.03 x baseline kpps, loses <= 0.97, else ties. Recorded per row: VPE0/VPE1 busy and which VPE saturates (>= 95 %); "neither (door-limited)" = the chip-to-NIC path still limits. VPE1 busy % tells whether the second CPU is useful.
- Boot/image options reboot with the same settings plus kernel/boot arg, so each gets its own baseline after the boot.

| option | knob / bench | image needed | 408 result | best-core result | verdict | VPE0/VPE1 busy |
|---|---|---|---|---|---|---|
| two-ring split | 300-43 rt0/rt1/par/par_acl1, `ring_split_ab.py`, `cpuq0_drop_pages=1024` | `mainline-7.4-rc1-ring.bin` | - | - | - | - |
| NAPI placement | `zc_bench --napi irq1 / split` (ring per VPE) | plain | - | - | - | - |
| tx_by_cpu on/off | `/sys/module/rtl838x_eth/parameters/tx_by_cpu` (300-38) | plain | - | - | - | - |
| noqueue | `tc qdisc replace dev eth0 root noqueue` | plain | - | - | - | - |
| SRAM rings | boot arg `rtl838x_eth.sram_rings=3` (300-25) | plain | - | - | - | - |
| cache variants | parked 300-42 `zc_sync_bytes` txfull / `zc_rx_part`, `zc_sync_ab.py` | needs build: 300-42 (skipped with a log line if the params are missing) | - | - | - | - |
| CPU queue thresholds | `cpuq_drop_pages`, `cpuq0_drop_pages` (300-40; read at open) | plain | - | - | - | - |
| zc vs stack | `zc_bench` with the stack run | plain | - | - | - | - |
| GRO fraglist off | `ethtool -K eth0 lan1 rx-gro-list off`, TCP P4 | plain | - | - | - | - |
| GDMA copy offload | n/a unless a copy exists in the NAT path (`kmod/gdma_bench` is a copy test) | - | n/a | n/a | n/a | n/a |

## Results (filled by `fastest-search --write-doc`)
<!-- RESULTS-BEGIN -->
| domain | knob | stock | pick | max tried | fastest viable | date/conditions |
|---|---|---|---|---|---|---|
| switch-core | SW VCO e214 NCODE + DIVN2_SWCORE e220[8: | 408 | 408 | - | - | not run picks, 1 quick test/point |
| lx-arb | LX0..2_ARB_CFG0-3 0xB8000010-3C (reset 0 | stock | stock | - | - | not run picks, 1 quick test/point |
| cpu | turbo cpu= | 800 | 1350 | - | - | not run picks, 1 quick test/point |
| ddr | turbo ddr= | 600 | 662 | - | - | not run picks, 1 quick test/point |
| sram | CPU_SRAM_ASY_TIMING 0x40f8 | stock | stock | - | - | not run picks, 1 quick test/point |
<!-- RESULTS-END -->

## Not covered
- Multi-interface / multi-WAN NAT. Soaks. LX above 306, SPI under Linux, IPv6 offload matrix (`l3_offload_ab.py`).
- Intermediate SW VCO steps beyond the list above (other agent, #148); DDR retrain automation for 675+ (see domain 4).
- Parsing of `ring_split_ab` / `zc_sync_ab` output in `load_test.py` is best-effort (last kpps figure; read their logs for the per-variant verdict).
- No hardware run yet: both scripts tested with `--dry-run`, `--list`, `ast.parse` only.

## Bench commands (later)
- `./dev.py fastest-search --list`, `./dev.py fastest-search --discover`, `./dev.py fastest-search --domain switch-core`, then lx-arb, cpu, ddr, sram.
- `./dev.py fastest-search --write-doc`; discuss with the owner; `./dev.py fastest-search --combine`.
- `./dev.py load-test --settings "<printed string>" --core <MHz> --options retest`; `./dev.py load-test --options-table`.

## Results 2026-11-07 (core 608)
- Setup: sw2, plain 7.4-rc1 bench kernel, switch core fixed at 608 MHz (VCO 3650, e214 `0x478`, e220 `0x36826`, LX 304, NOR code 11), one NAT interface, cage 1. Other domains at the picks (1350 / 662 / 500) while one is searched. `./dev.py fastest-search --core 608 --domain D`; rows `tmp/logs/fastest_search_core608.csv`.
- Quick test per point (one run, no repeats): rx-only 64 B + 1400 B 6 s, integrity, link alive, console scan (temperature logged only). Rx-only 1400 B varies +-6 % on one boot at 608 (CAMPAIGN-PLAIN-7.4.md), so a 3 % gain is not resolvable in a scan.
- Nothing made a default.

### CPU (bisect 800..1425 step 25)
| MHz | rx 1400 B kpps | rx 64 B kpps | result |
|---|---|---|---|
| 1000 | 151.1 | 182.9 | pass |
| 1050 | 150.8 | 192.4 | pass |
| 1100 | 158.6 | 193.5 | pass |
| 1250 | 175.6 | 217.2 | pass |
| 1325 | 173.5 | 220.2 | pass |
| 1350 | 180.5 | 226.2 | pass |
| 1375 | 179.4 | 231.6 | HANG: integrity FAIL, Kernel panic, link dead |

| stock | max tried | fastest viable | gain vs stock | why the gap |
|---|---|---|---|---|
| 800 (not run, known good) | 1375 | 1350 | 64 B 226 vs 183 kpps at 1000 (+24 %), 1400 B 180 vs 151 | 1375 panics (CPU fault, as at core 408); 1400 / 1425 not run (bisect: below a fail) |

### DDR (bisect 600..800, valid bins 600 625 650 662 675 700 ...)
| MHz | rx 1400 B kpps | result |
|---|---|---|
| 700 | - | FAIL: U-Boot canary 1190 words bad, reverted to 600 (safe) |
| 650 | 177.3 | pass |
| 675 | - | FAIL: canary 723 words bad, reverted (safe) |
| 662 | 174.4 | pass |

| stock | max tried | fastest viable | gain | why the gap |
|---|---|---|---|---|
| 600 | 700 | 662 | within noise (177.3 at 650, 174.4 at 662) | DRAM data errors at 675+ without retrain (DRAM.md) |

### LX bus (not swept at 608)
| stock | max possible | fastest viable | gain | why the gap |
|---|---|---|---|---|
| 175 | 304 (306 on VCO 2450) | 304 | - | at VCO 3650 only code 4 (304) is inside the allowed 175/204/245/306 +-1 % set; 204 / 245 need another VCO (575 MHz core: LX 246, forwarding 153 kpps vs 170 at 608, 19ea243). 204 panics on the 7.3 image (#149). Codes above 306 need a clocks.c change. A raw LX re-code would also skip the UART divisor update (`swc_write` does it). |

### LX arbitration (scan, 12 words 0xB8000010..3C written with one pattern; reset values: words 0x10-0x2c = 0, 0x30..3c = 0x32103210 / 0x03210321 / 0x01320132 / 0x21032103)
| pattern | rx 1400 B kpps | rx 64 B kpps | verdict |
|---|---|---|---|
| stock | 180.1 | 219.7 | baseline |
| swap 0x01010101 | 174.1 | 224.1 | no gain |
| m1 0x11111111 | 176.4 | 225.4 | no gain |
| m0 0x00000000 | 182.8 | 226.7 | +1.5 %, inside the +-6 % spread: no gain |

| stock | max tried | fastest viable | gain | why the gap |
|---|---|---|---|---|
| reset values | 4 patterns | stock | none | no pattern passes the 1.03 gain bar; master IDs unknown (DATASHEET-AUDIT.md:185) |

### SRAM / bridge (scan; SRAM already 500)
| point | rx 1400 B kpps | rx 64 B kpps | verdict |
|---|---|---|---|
| sram=250 (stock clock) | 174.3 | 231.2 | pass, no difference |
| sram=500, bridge stock (`0x40f8` = 0x85) | 174.6 | 212.1 | baseline |
| pulse_dn (`0x84`) | 169.3 | 226.6 | no gain |
| pulse_up (`0x86`) | 174.6 | 228.2 | no gain |
| oc0_dram_flip (CMUCR_OC0 `0x388` bit 9) | - | - | HANG: no ssh after ramload; next software ramload recovered |

| stock | max tried | fastest viable | gain | why the gap |
|---|---|---|---|---|
| 250 | 500 | 500 | none measurable | SRAM clock does not move 1400 B / 64 B rx at 608; bridge bits tie or hang |

### Combined winners vs the 608 baseline (cpu 1350, ddr 662, lx 304, sram 500, arb stock, bridge stock)
| metric | 608 baseline (CAMPAIGN-PLAIN-7.4.md) | this run |
|---|---|---|
| quick test rx 1400 / 64 B kpps | 177-181 / 220 | 172.0 / 222.2, integrity PASS, 53.2 C |
| zc+nat fwd 1400 B kpps | 169.2-170.7 | 169.3 (VPE0/1 busy 3/98) |
| NAT TCP P4 zc+nat fwd / rev Mbit/s | 1634 / 1631 | 1620 / 1623 |
| NAT TCP P4 stack fwd / rev Mbit/s | 422 / 413 | 406 / 412 |

- Result: the picks are the fastest viable at core 608 in every domain; the combination equals the baseline (differences <= 1 %).
- CPU raise is blocked by the 1375 fault, DDR by data errors at 675, the other domains do not move the NAT rate.

## CPU 1375+ and DDR 675+: lock or limit (2026-11-07)

- Method: U-Boot only (`./dev.py lock-probe`, `ddr-retrain`, plain `turbo ddr=`), then `fastest-search --once` on fresh boots. Core 408 = stock, 608 = recommended max. Picks ddr 662 / lx 306 / sram 500 for the CPU rows.
- Lock = `clocks: locked after N us` (TC5 timer), `0xbb00e200` bit 15 re-read 20x after each set, e208/e210 read back = written.

| point | lock N us | memtest (32 MiB low, cached+uncached) | Linux integrity | verdict |
|---|---|---|---|---|
| CPU 1350, core 408 / 608 | 0 / 0 | 0 errs / 0 errs | pass (reference) | ok |
| CPU 1375, core 408 | 0 | 0 errs, stepped and direct from 800 | PASS 143.7 kpps 1400 B, 49.3 C | ok at 408 |
| CPU 1375, core 608 | 0 | 0 errs, stepped and direct | 2/2 no boot: `XZ-compressed data is corrupt` panic, then no ssh | real limit, depends on core clock |
| CPU 1400, core 608 | 0 | cached 310 / 236 / 482 errs in 3 boots, uncached 0 | no boot: `lzma: uncompress error 1` | real limit |
| CPU 1400, core 408 | 0 | 0 errs | not run | passes U-Boot only |
| CPU 1425, core 408 | 0 | exception (epc in memtest), prompt lost | not run | real limit |
| CPU 1425, core 608 | exception in the set routine | - | not run | real limit |
| DDR 675 plain | n/a (no ready bit) | canary 495-501 bad, bit 1 (DQ1) in the first bad words, write test 0 bad | - | untrained read taps |
| DDR 700 plain | n/a | canary 1024-1062 bad, DQ1 + DQ6, write test 0 bad | - | untrained read taps |
| DDR 675 `ddr-retrain --write` | n/a | write test + 16 MiB crc32 clean | - | passes after retrain |
| DDR 700 `ddr-retrain --write` x2 | n/a | write test + 16 MiB crc32 clean both | - | passes after retrain |

- CPU: PLL locks at once at every point (0 us, bit 15 = 1 in 20/20 re-reads, no step/direct difference). The failures are CPU logic errors: wrong data in cached code/data, decompress errors, exceptions. 1375 passes at core 408 and fails at core 608, so the limit moves with the core clock (shared supply / noise); not a lock problem.
- DDR: plain 675/700 fail on the same low data lanes in every run with writes clean; retrained read taps pass at 675 and 700 (700 twice, trained taps differ 1-2 steps per boot). The MEM PLL has no ready bit (fixed 405 us settle), so a longer-settle retry was not possible without a code change. `turbo ddr=` does not retrain: fastest-search needs `ddr-retrain` before it can call 675/700 a fail.
- Open: DDR 675/700 under Linux with retrained taps and the 608 core not tested (retrain taps are not carried into `turbo`).
