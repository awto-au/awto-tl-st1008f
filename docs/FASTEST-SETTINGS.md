# Fastest stable settings: search plan (owner priority 2026-11-07)

Goal: fastest stable setting in every limiting domain, then load-test the best combination.
Tools: `./dev.py fastest-search` (scripts/fastest_search.py), `./dev.py load-test` (scripts/load_test.py). sw2 only; sw1 never.

## Final settings
Owner decision 2026-11-07 (CPU 1325 by owner choice 2026-11-08): go with what works; DDR and CPU limit testing stopped. Evidence (history): [history/FASTEST-SETTINGS-results-2026-11.md](history/FASTEST-SETTINGS-results-2026-11.md). Format: rated max | board | we run | why the gap.

| Domain | Stock | Final | Why the gap |
|---|---|---|---|
| Switch core | 408 MHz | 608 | code 0 (/4) wedges CPU-port DMA, code 1 passes to 783 live (CLOCKS.md); 608 is the persistent step (575 / 658 re-code LX); 1400 B rate scales with the core up to 608 |
| CPU | 800 | 1325 | highest step stable 5/5 on the OpenWrt image at core 608 (#160); 1350 passes short plain-kernel runs but fails the image at core 575 / 608; 1375 panics at core 608 (passes at 408) |
| DDR | 600 | 662 | 675 / 700 pass only with `ddr-retrain --write` and give no gain beyond noise |
| LX | 175 | ~304 | follows the SW VCO; 204 panics on the 7.3 image (#149); codes above 306 need a clocks.c change |
| SRAM | 250 | 500 | already the maximum; no measurable effect on the NAT rate |
| SPI (Linux) | 25.5 MHz | 23.4 (follows core 608) | fast SPI corrupts reads under Linux (#50) |

- Result: [FINDINGS.md](FINDINGS.md).

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
- **1**: domain switch-core; knob SW VCO `e214` NCODE + `e220[8:5]` + relock `e200` b30; stock 408 MHz; pick 408; range / steps 408, 450, 500, 550, 600, 612
- **2**: domain lx-arb; knob `LX0..2_ARB_CFG0-3` `0xB8000010-3C`; stock `0x10101010`; pick stock; range / steps stock, swap, m1, m0 (scan)
- **3**: domain cpu; knob `turbo cpu=`; stock 800; pick 1350; range / steps 800, 1000, 1050, 1100..1425 step 25
- **4**: domain ddr; knob `turbo ddr=`; stock 600; pick 662; range / steps 600, 625, 650, 662, 675 .. 800
- **5**: domain sram / bridge; knob `0x40f8`, CMUCR_OC0 `0xb8000388` b9; stock 250; pick 500; range / steps stock, pulse_dn, pulse_up, oc0_dram_flip (scan)

1. switch-core (largest measured lever: 1400 B rate scales 1:1 with the clock, CAMPAIGN-PLAIN-7.4.md; #148 findings in docs/CLOCKS.md).
   - Steps = stock 408 (VCO 2450, code 1) then VCO steps with code 1 (/6): 508 (VCO 3050), 575 (3450), 608 (3650), 658 (3950). Each passed 3/3 boots.
   - Raw words (e214 / e220), also U-Boot `swcore=`: 508 `0x3b8`/`0x30626`; 575 `0x438`/`0x34a26`; 608 `0x478`/`0x36826`; 658 `0x4d8`/`0x38c26` (`fastest_search.SWC`, `swcore_step.py`).
   - 612 via code 0 (VCO 2450) wedges CPU-port DMA under forwarding: the /4 divider, not the frequency. 608 = highest persistent step (U-Boot points); 575/658 re-code LX to 246/247 MHz.
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

- **two-ring split**: knob / bench 300-43 rt0/rt1/par/par_acl1, `ring_split_ab.py`, `cpuq0_drop_pages=1024`; image needed `mainline-7.4-rc1-ring.bin`
- **NAPI placement**: knob / bench `zc_bench --napi irq1 / split` (ring per VPE); image needed plain
- **tx_by_cpu on/off**: knob / bench `/sys/module/rtl838x_eth/parameters/tx_by_cpu` (300-38); image needed plain
- **noqueue**: knob / bench `tc qdisc replace dev eth0 root noqueue`; image needed plain
- **SRAM rings**: knob / bench boot arg `rtl838x_eth.sram_rings=3` (300-25); image needed plain
- **cache variants**: knob / bench parked 300-42 `zc_sync_bytes` txfull / `zc_rx_part`, `zc_sync_ab.py`; image needed needs build: 300-42 (skipped with a log line if the params are missing)
- **CPU queue thresholds**: knob / bench `cpuq_drop_pages`, `cpuq0_drop_pages` (300-40; read at open); image needed plain
- **zc vs stack**: knob / bench `zc_bench` with the stack run; image needed plain
- **GRO fraglist off**: knob / bench `ethtool -K eth0 lan1 rx-gro-list off`, TCP P4; image needed plain
- **GDMA copy offload**: knob / bench n/a unless a copy exists in the NAT path (`kmod/gdma_bench` is a copy test); 408 result n/a; best-core result n/a; verdict n/a; VPE0/VPE1 busy n/a

## Results (filled by `fastest-search --write-doc`)
<!-- RESULTS-BEGIN -->
- **switch-core**: knob SW VCO e214 NCODE + DIVN2_SWCORE e220[8:; stock 408; pick 408; date/conditions not run picks, 1 quick test/point
- **lx-arb**: knob LX0..2_ARB_CFG0-3 0xB8000010-3C (reset 0; stock stock; pick stock; date/conditions not run picks, 1 quick test/point
- **cpu**: knob turbo cpu=; stock 800; pick 1350; date/conditions not run picks, 1 quick test/point
- **ddr**: knob turbo ddr=; stock 600; pick 662; date/conditions not run picks, 1 quick test/point
- **sram**: knob CPU_SRAM_ASY_TIMING 0x40f8; stock stock; pick stock; date/conditions not run picks, 1 quick test/point
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
