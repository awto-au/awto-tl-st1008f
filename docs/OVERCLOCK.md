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
| sw1 | 1000 | 650 | `clocks fast` (2026-10-11); fixed U-Boot in jffs2-log 2026-10-13, active at next power-up |
| sw2 | 1000 | 650 | `clocks fast`; DDR-only 600-662.5 pass, 675 fails + reverts (2026-10-12) |

- Ladder above 1000 MHz on sw2: results below once run.
