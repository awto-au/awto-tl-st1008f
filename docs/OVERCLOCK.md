# Overclock: method, register rules, per-unit settings

Run/recover steps: [OVERCLOCK-OPS.md](OVERCLOCK-OPS.md). Clock tree and registers: [CLOCKS.md](CLOCKS.md). Issues #101, #103.

## Method

- Every PLL change runs from SRAM with its lines locked in the I-cache: CPU (`clocks_sram.S`), DDR (`ddr_sram.S`). No stack, no DRAM access, I/O via KSEG1, marks straight to the UART.
- The DDR routine verifies a 1024-word canary at the new clock (uncached, then cache-line refills) and reverts to the old set on a mismatch, inside SRAM.
- Every ratio-dependent register is written for the new rate (table below). A missed one hangs intermittently, it does not fail cleanly (#101).
- Power-up: `bootsel fast` arms the SoC watchdog (13 s) before `clocks fast`. A change that never finishes → SoC reset → that boot skips the overclock (record word in reserved RAM); the boot after retries.
- Sweeps: coarse points first (one short pass, n = 5 power cycles each), then bisect between the last pass and the first fail, n = 20 only on the chosen setting. No soaks.
- Pass = the change reports OK, the prompt answers, a 16 MiB `crc32` completes, temperature read. A clean `FAIL … reverted` is a fail, not a hang.

## Ratio-dependent registers (SDK names)

| Register | Rule (SDK) | CPU 800 / 1000 | CPU 1100-1300 | Ours |
|---|---|---|---|---|
| CPU_SRAM_ASY_TIMING `0xb80040f8` `oc0_sram_pulse` [1:0] | OCP0 = CPU/2 vs SRAM: < SRAM → 0, < 2 SRAM → 1, else 2 | SRAM 250: 1 / 2 | 2 (SRAM 500: 1) | written per CPU change (f13672d) |
| … `sram_oc0_pulse` bit 6 | SRAM ≥ OCP0 | 0 / 0 | 0 (SRAM 500: 1 to 1000 MHz) | written per CPU change |
| … `sram_lx_pulse` bit 8 | 3 x LX ≤ SRAM | 0 (LX 175) | 0 | written by `clocks set lx` (250 rule) |
| PLL_SRAM_CTRL `0xb8000700` `sram_pll_sel` bit 1 | SRAM 250 (0) / 500 (1) | 0 | 0 | not changed (SRAM 500 untested, #103) |
| CMUCR_OC0 `0xb8000388` SE_DRAM bit 9 | MEM ≥ OCP0 | 1 at DDR 600/650 | 1 up to CPU 1300 at DDR 650 | not written (constant); our `mem_set` guard compares CPU, not CPU/2 |
| CMUCR_OC0 SE_SPIF bit 17 | SPI-NOR ≥ OCP0 | 0 | 0 | not written (constant) |
| CMUCR_LX0-2/LXP SE_DRAM bit 9 | MEM ≥ LX | 1 | 1 | not written (constant) |
| PLL_CPU_CTRL0 `0xbb00e208` / PLL_CPU_MISC_CTRL `0xbb00e210` | VCO = 50 x (NCODE + 2); CPU = VCO / (DIVN2 + 2); stock VCO 2400-3200 | /4 VCO 3200 / /3 VCO 3000 | 1100: /2 VCO 2200 (below range); 1200: /2 2400; 1300: /2 2600 | `clocks set cpu`; values `scripts/clock_calc.py cpu` |
| MEM PLL MPCR0-6 `0xb8000234..24c` | per bin (CLOCKS.md); MPCR6 SSC 0 | — | — | per bin in `mem_bins[]` |

- LX-scaled: UART divisor (`clocks set lx` updates it), I2C SCL, otto timer + watchdog tick (Linux). Not touched by CPU/DDR changes.

## Per-unit settings

| Unit | CPU | DDR | Source |
|---|---|---|---|
| sw1 | 1000 | 650 | `clocks fast`; U-Boot md5 `f4065adc…` in jffs2-log 2026-10-13T09:34 (SSH), active at next power-up |
| sw2 | 1000 | 650 | same build, chain on; power-up PASS 2026-10-13T09:35; DDR-only 600-662.5 pass, 675 fails + reverts |

- Build f4065adc = #101 fix (CPU_SRAM_ASY_TIMING) + SDK order from the #102 audit: DACCR `ac_bptr_clear` after the tREFI DTR latch, 1 µs before DMCR busy polls, SRAM drain + PLL_SRAM_CTRL rewrite in the CPU change. `clocks-cycle fast` 20/20 on it (2026-10-13T09:33).

## Overview survey (sw2, 2026-10-13T09:10-10:01+11:00, one run per point, our U-Boot RAM-loaded)

One quick test per point: the change reports OK, prompt, 16 MiB `crc32`, temperature (31-34 °C raw at every point). No repeats; the owner picks settings before n=20.

| Domain | Point | Result | Measured | Note |
|---|---|---|---|---|
| CPU | 1050-1400 | pass | real 1097.6 / 1185.6 / 1297.2 / 1395.9 at 1100 / 1200 / 1300 / 1400 | /2 VCO 2200-2800 above 1050; 1100-1400 also n=5 |
| CPU | 1425 | pass | decoded only | `0x378` /2 VCO 2850 |
| CPU | 1450, 1500 | hang | — | inside `clocks set cpu` (no prompt) |
| SRAM | 250 → 500 | pass | uc read 80.4 → 60.0 ns, uc write 22.0 → 15.0 ns, cached fill 26.9 → 23.8 ns/word | DRAM: 80.3 / 14.5 / 26.6 ns; `clocks membench`, CPU 800 |
| LX | 306, 245 | pass | — | UART follows (`clocks set lx 2/3`); Linux side untested |
| DDR | 800, 750, 700 | fail | canary bad, reverted | 700 + dqshift −6 also fails |
| DDR | 675 + dqshift −8 | pass | — | 662.5 and 650 pass plain |
| SPI-NOR (U-Boot, Quad I/O 0xEB, D = 0) | 306 | hang | `crc32` timeout | NOR code 0 |
| SPI-NOR | 204, 153 | fail | CRC wrong | codes 1, 2 |
| SPI-NOR | 122.5 | pass | flash_c 37.0 MB/s, chip CRC 3.5 s | code 3 (as Dual I/O) |

## Linux at the picks (sw2, 2026-10-13T10:36-11:26+11:00, mainline next + SRAM patches)

- Base = `nic-bench boot` clocks: our U-Boot `clocks fast` (CPU 1000, DDR 600, SRAM 250); points add `turbo` before `bootm` (`ST1008F_RAMLOAD_EXTRA="--pre|turbo …"`).
- Quick test per point now includes a kernel boot to the initramfs shell (`clocks-cycle --session`, default): U-Boot unlzma + kernel initramfs XZ unpack catch CPU faults the 16 MiB `crc32` misses.

### Kernel boot per clock (one boot each)

| turbo | Result |
|---|---|
| cpu=1400,ddr=662,sram=500 | panic `XZ-compressed data is corrupt` (initramfs unpack, 0.59 s) |
| cpu=1400,sram=500 | same panic |
| cpu=1400 | same panic |
| ddr=662 / sram=500 / ddr=662,sram=500 | shell |
| cpu=1300 / 1350 / 1375 | shell |
| cpu=1375,ddr=662,sram=500 | shell (3 boots) |
| cpu=1400,ddr=662,sram=500 + `memtest=4`, from stock clocks | U-Boot `lzma compressed: uncompress error 1`, reset |
| `clocks-cycle --session cpu --lo 1350` from stock clocks | 1375, 1400, 1425: shell (one boot each) |

- CPU 1400: 4 fails, 1 pass; 1425: 1 pass. DRAM is clean at the same clocks (DRAM.md "Memtest"): the fault is CPU-side (decompressor = core + L1 load). 1400/1425 are marginal; 1375 passed all 5 boots.
- LX 306: kernel console garbled. `ft_board_setup` patches the fixed-clocks to the live LX/CPU, but the kernel uses its appended DTB (`Working FDT set to 0`), so the patch never reaches it. Needs a separate DTB passed to `bootm` or kernel-side LX detection.

### At cpu=1375,ddr=662,sram=500 vs base (one run each)

| Test | Base | Picks (1375) |
|---|---|---|
| nic-bench tcp-P4 | 291 Mbit/s | 418 Mbit/s |
| nic-bench udp1400 900 Mbit/s offered: loss | 26.5 % | 0.2 % |
| nic-bench udp64 forward | 61.5 kpps | 92.2 kpps |
| sram-bench SRAM uc read / cached miss | 5571 / 6676 ns | 3764 / 4445 ns |
| sram-bench DDR uc read / cached miss / uc write | 7504 / 7805 / 4270 ns | 7228 / 7433 / 4827 ns |

- sram-bench ns = raw loop time from `sram_bench`; cached hit 274 → 195 ns tracks the CPU ratio (1000 → 1375). DDR uncached writes got slower (+13 %).
- `mem-stress` hung the kernel at every clock incl. stock: the 300-21 SRAM window shadows Linux phys `0x2f000000` (HARDWARE-INVENTORY.md 64 KiB SRAM, #107, fixed by a DTS reservation).
- Not done: NIC DMA into SRAM, Linux load test at the picks.

## CPU above 1000 MHz (sw2, 2026-10-13, CPU_SRAM_ASY_TIMING written)

| CPU | e208 / DIVN2 (VCO) | `clocks-cycle cpu` n=5 | Real rate (`cpu-clock`, host-timed `sleep 5`) |
|---|---|---|---|
| 1050 | `0x3d8` /3 (3150) | 5/5 | — |
| 1100 | `0x2a8` /2 (2200) | 5/5 | 1097.6 |
| 1150 | `0x2c8` /2 (2300) | — | 1147.2 |
| 1200 | `0x2e8` /2 (2400) | 4/5 + 1 ramload miss | 1185.6 (−1.2 %) |
| 1300 | `0x328` /2 (2600) | — | 1297.2 |

- Pass = PLL locked, prompt, 16 MiB `crc32`, temperature. U-Boot idle temperature 31-32 °C (raw `TEMP_OUT`, meter just enabled) at every point.
- Before the CPU_SRAM_ASY_TIMING fix, 1066.7 MHz (/3, VCO 3200) hung after the PLL write (2026-10-10). /2 with VCO 2200-2600 locks at once.
- Not yet: n=5 at 1300, points above 1300, a Linux load at these rates, n=20 on the pick.
