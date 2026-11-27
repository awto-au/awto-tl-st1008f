# Fastest settings: results 2026-11-07 (history)

Moved unchanged from [../FASTEST-SETTINGS.md](../FASTEST-SETTINGS.md) (plan, rules, final settings stay there). Conclusions: [../FINDINGS.md](../FINDINGS.md).

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
