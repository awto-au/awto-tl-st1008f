# RTL9303 clock tree and overclocking

Source tags: **[SRC]** GPL file:line (`dms1250/` = `sources/rtk-dms1250/`, `xgs1210/` = `sources/uboot-xgs1210/` in a clone of `github.com/reyalo/Realtek`; `owrt/` = OpenWrt `target/linux/realtek/`). **[BIN]** stock preloader (SPL) VA (`loader.bin` file `0x0000..0x507f`, XIP at `0x9fc00000`, SRAM copy at `0x9f000000`). **[LIVE]** register dump on this unit, 2026-10-10, mainline U-Boot after stock SPL init. **[DS]** `sources/rtl9303-cg-brief.pdf` (Rev 1.1-1). **SPEC** = inferred, not verified on hardware.

- Read it live: `clocks` (U-Boot, `board/tplink/tl-st1008f/clocks.c`). Host: `scripts/clock_calc.py decode <md.l dump>`.
- Nothing here writes a clock register. Changes are procedures (below) for the main session to run.
- Recovery for every experiment: everything is RAM-loaded; a power cycle reruns the stock SPL (CPU 800 / LX 175 / DDR 600). Flash is never written.

## Summary

| Clock | Live | Formula (inputs = registers) | Source |
|---|---|---|---|
| XTAL | 25 MHz | fixed | [DS] Table 18 |
| CPU CMU VCO | 3200 MHz | 25 x (NCODE + 2) x 2 / 2^PREDIV (x4 if SEL_DIV4), `0xbb00e208` | [BIN] `0x9fc04100` |
| CPU = OCP0 | **800 MHz** | VCO / (DIVN2_CPU + 2), `0xbb00e210[6:4]` = 2 | [BIN] `0x9fc04100`; [LIVE] `sleep` check (+0.3 %) |
| CP0 Count | 400 MHz | CPU / 2 | 34Kc; [LIVE] `uboot-test timer` |
| SW CMU VCO | 2450 MHz | same formula, `0xbb00e214` (NCODE 47) | [BIN] `0x9fc0422c` |
| LX | **175 MHz** | SW VCO / (2 x (DIVN2_LXB + 2)), `0xbb00e220[12:9]` = 5 | [BIN] `0x9fc0422c`; [LIVE] UART divisor 95 works |
| NOR (SPI ctrl in) | 153.125 MHz | SW VCO / (2 x (DIVN2_SPI_NOR + 2)), `0xbb00e220[16:13]` = 6 | [BIN] `0x9fc04324` |
| SPI SCK | 25.52 MHz | NOR / (2 x (SFCR[31:29] + 1)), SFCR `0x5fc00244` -> /6 | [BIN] table `0x48e0` |
| MEM (DDR clock) | **600 MHz** (DDR3-1200) | 25 x (MPCR3[31:24] + 2) / (2 << MPCR2[15:14]) | [BIN] `0x9f000610`, `0x9fc00e0c` |
| UART | 115131 baud | LX / 16 / divisor | ns16550 |

- SPEC: OpenWrt's RTL960x MEM formula uses `NCODE + 3` (`owrt/files-6.18/drivers/clk/realtek/clk-rtl83xx.c:508-530`). RTL9300 SPL uses `+ 2` in two places; the actual DDR clock is not measured (#39).
- OCP = CPU clock in Realtek naming (`cg_dev_freq_t.ocp_mhz`, [SRC] `xgs1210/arch/otto40/plr/src/soc/cg_gen4/cg.h:7`).

## Register map

### PLL block, switch core `0xbb00e200` — [SRC] `dms1250/system/include/private/drv/swcore/swcore_rtl9300.h:108-415`

| Reg | Live | Fields (decoded live value) |
|---|---|---|
| `e200` PLL_GLB_CTRL0 | `0001c0ff` | CPU_CLK_SEL 19 = 0, NOR_CLK_SEL 18 = 0, LXB_CLK_SEL 17 = 0, SW_PLL_READY 16 = 1, CPU_PLL_READY 15 = 1, 125M_READY 14 = 1, BYPASS_* 13:8 = 0, EN_{DDR,NOR,NAND,USB,LXB,CPU,125M,SRAM}_PLL 7:0 = all 1. PLL_DBG_OUT 30:20 (bit 30 = SPL relock toggle, see CPU apply) |
| `e204` PLL_GLB_CTRL1 | `0000023f` | DLL_PRE_DIVN 10:9 = 1, CMU_DLY_EN_{CPU,SW,125M} = 1, FLD_DSEL_{CPU,SW,125M} = 1 |
| `e208` PLL_CPU_CTRL0 | `000003e8` | DIVN3_CPU 26:25 = 0, FCODE 24:12 = 0, NCODE 11:4 = 62, BYPASS_PI 3 = 1, SEL_DIV4 2 = 0, SEL_PREDIV 1:0 = 0 |
| `e20c` PLL_CPU_CTRL1 | `00000001` | EN_SSC 31 = 0 (no spread), TIME0_CK = 1 |
| `e210` PLL_CPU_MISC | `6b439e23` | CMU_EN 30 = 1, CLKRDY 29:28 = 2, BIG_KVCO 27 = 1, LPF_RS 26:24 = 3, EN_WD 22 = 1, SEL_CP_I 19:16 = 3, SEL_CCO 15 = 1, LDO_SEL 14:12 = 1, LPF_CP 11 = 1, CP_NEW_EN 10 = 1, LDO_EN 9 = 1, **DIVN2_CPU 6:4 = 2**, DIVN2_DLL 3:1 = 1, EN_DLL 0 = 1 |
| `e214` PLL_SW_CTRL0 | `000002f8` | NCODE 47, BYPASS_PI 1, SEL_DIV4 0, PREDIV 0 |
| `e218` PLL_SW_CTRL1 | `00000000` | SSC off |
| `e21c` PLL_SW_MISC | `00d6873c` | loop/LDO settings (not decoded) |
| `e220` PLL_SW_DIV_CTRL | `0002ca26` | SW_CMU_EN 17 = 1, **DIVN2_SPI_NOR 16:13 = 6**, **DIVN2_LXB 12:9 = 5**, DIVN2_SWCORE 8:5 = 1, DIVN2_GPHYDBG 4:1 = 3, EN_GPHY_DBG 0 = 0 |
| `e224` PLL_125M_CTRL0 | `00000308` | NCODE 48 (VCO 2500 MHz), BYPASS_PI 1 |
| `e228` PLL_125M_CTRL1 | `0c000000` | DIVN2_125M 29:26 = 3 |
| `e22c` PLL_125M_MISC | `e0d6873c` | DIV5_EN 1, DIV4_EN 1, CMU_EN 1 |
| `e230` PLL_CML_CTRL | `000d0003` | CKREFBUF_CML_I 20:18 = 3, _R 17:16 = 1 |

- SPEC: switch-core clock = SW VCO / (2 x (DIVN2_SWCORE + 2)) = 408 MHz by analogy with LX; not used by any code here.

### SoC `0xb8000000` — [SRC] `dms1250/system/include/soc/socdef/rtl9300_soc_reg.h`

| Reg | Live | Fields | Line |
|---|---|---|---|
| `0044` SSR | not dumped | **ckse_ocp0 2** (CPU clock: 1 = PLL, 0 = alternate; SPL clears it around a CPU PLL change), cksel_ocp1 3, gnt_dly 10:8, soc_init_rdy 0 | 124 |
| `0200` SPCR | `000e000e` | OCP0PLL_DIV 21:16 = 14, RD_SDCLK_SEL 5:0 = 14. SPEC: legacy (RTL838x-era) field, not read by the SPL | 466 |
| `0204` PCCR | `40000002` | SSC_RST_N 30 = 1, PLLDDR_PSEN 1 = 1, SSC_EN 6 = 0 | 472 |
| `0218` ANACR | `000000c4` | PLLANA 15:0 | 512 |
| `021c` DCKOCR | `00000000` | DDR CK output phase taps | 518 |
| `0220` MPSR | `00000002` | MCKG_PHS 2:0 = 2 | 528 |
| `0228` LPSR | `00000303` | SPICLK_SEL 11:8 = 3, LXCLK_SEL 3:0 = 3. SPEC: legacy; SPL helper `0x9fc00e40` computes 1000/(sel+2) = 200 MHz from it, which the working UART rules out | 536 |
| `022c` DCER | `00000001` | START_DRAM_CLKO 0 = 1 | 544 |
| `0234..024c` MPCR0-6 | `7f 400001ef 26a33860 2e0f0000 fff 0 0` | MEM PLL: MPCR2 `23c` PDIV 15:14; MPCR3 `240` NCODE 31:24 = 0x2e; MPCR4 `244` [5:0] = PLL enable/reset (SPL: 0 = hold, 0x3f = run) | 548-575 |
| `0388` CMUCR_OC0 | not dumped | SE_DRAM 9 = (MEM >= CPU/2), SE_SPIF 17 [BIN `0x9f00063c`, `0x9f0008f8`] | 591 |
| `03a8/3b8/3c8/3d8` CMUCR_LX0-2/LXP | not dumped | SE_DRAM 9 = (MEM >= LX) | 629-695 |
| `0700` | not dumped | bit 1 = (SRAM-domain limit `[0x9f000b96]` == 500); written by the CPU apply. No SDK name | — |
| `40f8` | not dumped | [1:0] = CPU/2 vs 250 MHz class (0: < 250, 1: < 500, 2: >= 500), bit 6 = CPU/2 <= 250, bit 8 = 250 >= 3 x LX. No SDK name [BIN `0x9fc04100`, `0x9fc0422c`] | — |
| `1200` SFCR | `5fc00244` (#35) | SPI_CLK_DIV 31:29 = 2 (divide 2 x (n+1) = 6) | 2169 |

### DDR3 controller `0xb8001000` — [SRC] `rtl9300_soc_reg.h:1253-1445`; encoding [SRC] `xgs1210/arch/otto40/plr/src/soc/dram_gen2/memcntlr_setup.c:120-298`

- Encoding: every DTR field = clocks - 1. tREFI = (T_REFI + 1) x 2^(T_REFI_UNIT + 5) clocks. Gen2 source; RTL9300 field positions from its own header. Check: CWL field 6 -> 7 clocks, the only JEDEC-legal CWL at tCK 1.667 ns.

| Reg | Live | Decode @ 600 MHz (tCK 1.667 ns) |
|---|---|---|
| `1000` MCR | `20241e60` | DRAM_TYPE 31:28 = 2 -> DDR3; EEPROM_TYPE 21, FLASH_MAP1_DIS 18; LX1-3_FRQ_SLOWER 12:10 = 1, LX0 13 = 0, OCP0_FRQ_SLOWER 9 = 1; OCP0/1_RBF_F_DIS 5/6 = 1 |
| `1004` DCR | `21421003` | BANKCNT 29:28 = 2 (8 banks), DBUSWID 25:24 = 1 (x16), ROWCNT 23:20 = 4 (15 bits), COLCNT 19:16 = 2 (10 bits) -> 2^29 = 512 MiB = **one 4 Gbit x16 die**; PRL_BANK_ACT_EN 12 = 1 |
| `1008` DTR0 | `99644838` | CL 10 (16.7 ns), tWR 10 (16.7), CWL 7, tRTP 5 (8.3), tWTR 5 (8.3), tREFI 2304 clk = 3.84 us, CAS_PHY 3:0 = 8 (PHY read latency, raw) |
| `100c` DTR1 | `0808061f` | tRP 9 (15.0 ns), tRCD 9 (15.0), tRRD 7 (11.7), tFAW 32 (53.3) |
| `1010` DTR2 | `0a116000` | tRFC 162 clk (270 ns), tRAS 23 (38.3 ns) |
| `101c` DMCR | `00130000` | DTR_UP_BUSY/MRS_BUSY 31 = 0; MR_MODE_EN 20 = 1, MR_MODE 17:16 = 3, MR_DATA 0: last MRS = MR3 0 |
| `1040` MPMR0 | not dumped | PM_MODE 29:28 (SPEC: self-refresh entry), T_CKE, TRSD, T_XSREF |

- DTR2 confirms the die size: SPL rule tRFC = MEM x tRFC_ns / 1000 + 5 with 260 ns (4 Gbit) gives 161 = `0xa1` [BIN `0x9fc022e4`, table `0x338c` = {90,110,160,260,350} ns]. The earlier hand-trace `0xa1016000` (#23) had the field 4 bits too high.
- tREFI 3.84 us = the >85 °C (2x refresh) rate; tRP/tRCD 15 ns = DDR3-1333 timings.

## Stock SPL tables [BIN]

### CPU (`0x9fc04100`; NCODE @ file `0x4a34`, DIVN2 @ `0x4a20`; index (MHz - 400) / 25; request outside 400-800 -> error)

| Req | NCODE | DIVN2 | VCO | CPU |
|---|---|---|---|---|
| 400 / 425 / 450 / 475 / 500 | 46 / 49 / 52 / 55 / 58 | 4 (/6) | 2400-3000 | 400-500 |
| 525 / 550 / 575 | 50 / 53 / 55 | 3 (/5) | 2600 / 2750 / 2850 | **520** / 550 / **570** |
| 600 ... 800 step 25 | 46, 48, 50, 52, 54, 56, 58, 60, 62 | 2 (/4) | 2400 ... 3200 | 600 ... 800 |

- VCO range used by stock: 2400-3200 MHz. DIVN2 codes used: 2, 3, 4. Code 1 (/3) and 0 (/2) never used.
- Also written per CPU change: `0xb8000700` bit 1, `0xb80040f8` [1:0]/bit 6 (table above). Unchanged for any CPU 500-999 MHz.

### LX / SPI-NOR (`0x9fc0422c`, `0x9fc04324`)

- LX: DIVN2_LXB = SW VCO / (2 x LX) - 2; request window 133-204 MHz (`(lx - 133) < 72`). With SW VCO 2450: code 4 = 204.17, 5 = 175.0, 6 = 153.1, 7 = 136.1 MHz.
- NOR: DIVN2_SPI_NOR scanned 4..7 (SW VCO/408 - 2 .. SW VCO/266 - 2), SFCR code from `{div,code}` table `0x48e0` = (2,0) (4,1) ... (16,7); picks the fastest SCK <= request (default 25 MHz, `0x0bc6`). Default request table `0x0bc0` = {CPU 800, MEM 600, LX 175, SPIF 25, -, 250}.

### MEM PLL (`0x9fc03ff0`, apply `0x9f00063c`; tables @ `0x49e4`/`0x49a8`/`0x496c`/`0x4930`; index (MHz - 250) / 25; out of range -> **index 0 = 250 MHz**)

| Req MHz | MPCR0 `234` | MPCR1 `238` | MPCR2 `23c` | MPCR3 `240` |
|---|---|---|---|---|
| 250 / 275 | `0008407f` | `4000018f` | `26222400` | `120f0000` / `140f0000` |
| 300 / 325 / 350 | `0008407f` | `4000018f` | `26222520` | `160f0000` / `180f0000` / `1a0f0000` |
| 375 | `0008407f` | `4000018f` | `26622520` | `1c0f0000` |
| 400 | `0000007f` | `400001ef` | `26622520` | `1e0f0000` |
| 425 / 450 | `0008407f` | `4000018f` | `26a23720` | `200f0000` / `220f0000` |
| 475 / 500 | `000c607f` | `4000018f` | `26a23740` | `240f0000` / `260f0000` |
| 525 / 550 | `000c607f` | `4000018f` | `26a33840` | `280f0000` / `2a0f0000` |
| 575 | `000c807f` | `4000018f` | `26a33860` | `2c0f0000` |
| 600 | `0000007f` | `400001ef` | `26a33860` | `2e0f0000` |

- Apply: MPCR4[5:0] = 0, 200 us, write MPCR0-3, MPCR5 = MPCR6 = 0, 5 us, MPCR4[5:0] = `0x3f`, 200 us; then CMUCR_OC0[9] and CMUCR_LX*[9] (SE_DRAM). Runs before DDR init.
- No row above 600. MPCR3 NCODE for 625 / 650 = `0x30` / `0x32` by the formula; MPCR0-2 for them unknown (#39).

### DDR timing bins (DTR table @ file `0x3320`; DDR3 select 650->0, 600->1, ... 200->8, other -> 300 bin)

| MEM | DTR0 | DTR1 | DTR2 base | CL/CWL/tWR | tRTP/tWTR | tRP/tRCD | tRAS |
|---|---|---|---|---|---|---|---|
| 650 | `99655838` | `0909061f` | `00019000` | 10/7/10 | 6/6 | 10/10 | 26 |
| **600** | `99644838` | `0808061f` | `00016000` | 10/7/10 | 5/5 | 9/9 | 23 |
| 550 | `98644738` | `0808051e` | `00014000` | 10/7/9 | 5/5 | 9/9 | 21 |
| 500 | `77533d26` | `0707031b` | `00013000` | 8/6/8 | 4/4 | 8/8 | 20 |
| 450 | `67533d26` | `07070418` | `00011000` | 7/6/8 | 4/4 | 8/8 | 18 |
| 400 | `56433b25` | `05050315` | `0000f000` | 6/5/7 | 4/4 | 6/6 | 16 |
| 350 / 300 / 200 | see `scripts/clock_calc.py` | | | | | | |

- DTR2 = ((MEM x tRFC_ns / 1000 + 5) << 20) | base. 650 MHz, 4 Gbit: `0x0ae19000` (tRFC 175 clk = 269 ns).
- The SPL PHY pre-config (`0x9fc02664`) also has a 650 MHz branch: Realtek planned DDR3-1300; only the MEM PLL table stops at 600.

## Ratings

| Clock | Rated max | Board allows | We run | Why the gap |
|---|---|---|---|---|
| CPU | 800 MHz ([DS] p.1 "up to 800MHz") | no core-voltage control known (DVDDL 1.1 V +-5 %, [DS] Table 16); passive heatsink, 73 °C idle (hardware.md) | 800 | stock; above = overclock, procedure (a) |
| LX | not stated; SPL accepts 133-204 MHz | UART divisor scales | 175 | stock default; 204 is inside the SPL window |
| DDR3 clock | [DS] 8.3 "up to 800MHz (DDR3-1600)"; [DS] Table 25 fCK typ 600 MHz; SPL PLL table max 600, DTR/PHY to 650 | DRAM part rating unknown | 600 (DDR3-1200) | stock |
| DDR3 timings | part unknown | — | CL10 CWL7 tRCD/tRP 15 ns, tREFI 3.84 us | stock bin; tREFI at 2x rate costs ~3 % bandwidth (SPEC) |
| SPI SCK | 133 MHz FAST_READ (W25Q256JV) | not measured | 25.5 MHz | #35 |
| UART | LX / 16 = 10.94 MBd | host adapter (#32) | 115200 or `--fast` | host side |

- DRAM part: not visible in the board photos (top and bottom) → it sits under the SoC heatsink. Identify: remove the heatsink, read the marking (Samsung K4B4G1646x-xxyy: last letters = speed bin, e.g. `-BCK0` DDR3-1600, `-BCH9` DDR3-1333; Nanya/Winbond/Micron equivalents). No SPD on a soldered part; the die size (4 Gbit x16) is known from DCR/DTR2.

## Clock provider (U-Boot, implemented; hardware checks #41)

- `arch/mips/mach-otto/clock.c`: `otto_clocks_read()` decodes every rate from the registers on each call (no cache, no constants). Driver `realtek,rtl9300-clock` (UCLASS_CLK, pre-reloc), cells: 0 CPU, 1 MEM, 2 LXB (OpenWrt `rtl83xx-clk.h` numbering), 3 SPI SCK.
- Consumers:
  - ns16550: `clocks = <&ccu 2>` (was `clock-frequency = <175000000>`). Rate read once at `of_to_plat`.
  - CP0 timer: board `get_tbclk()` = CPU / 2, re-read every call; `CONFIG_SYS_MIPS_TIMER_FREQ` and `HAS_FIXED_TIMER_FREQUENCY` removed.
  - I2C (`i2c-rtl9300`): `clocks = <&ccu 2>`; busy-wait scales the SCL table by LX / 175 MHz (table characterised at stock LX). SPEC: SCL derives from LX (#40).
  - SPI (`spi-realtek-rtl`): `clocks = <&ccu 3>`; RDY limit = 32 SCK x 1.25 + 1 us, recomputed per claim (3 us at 25.5 MHz; was a fixed 40 us).
- `ft_board_setup()`: patches the kernel DTB with the live rates: `/cpus` `frequency` (OpenWrt 300-02 derives the CP0 rate = this / 2), `/cpu-clock` and `/lx_clk` `clock-frequency` (rtl930x.dtsi fixed clocks), every `ns16550a` that carries `clock-frequency`. Only existing properties are changed.
- Cost: `u-boot.bin` 293,374 -> 300,901 bytes (+7,527, CONFIG_CLK + command + fdt hook), 2026-10-10.

## Linux: what an RTL930x clk-rtl83xx extension needs (documentation only)

- Compatible `realtek,rtl9300-clock`; `#clock-cells = <1>`; parent 25 MHz osc.
- recalc_rate:
  - CPU: `0xbb00e208` (VCO as above) / (`0xbb00e210[6:4]` + 2). The 838x/839x DIVN2 at CTRL0[19:12] + 4 does not apply.
  - LXB: VCO(`0xbb00e214`) / (2 x (`0xbb00e220[12:9]` + 2)).
  - MEM: 25 MHz x (`0xb8000240[31:24]` + 2) / (2 << `0xb800023c[15:14]`).
- set_rate (optional): SRAM routine as the CPU apply below (SSR.ckse_ocp0 mux, relock trigger, READY poll); MEM set_rate only with the DDR procedure (b).
- DT consumers to switch from fixed clocks: `cpu@0/1 clocks`, `uart0/1`, `timer@3200` (otto timer), watchdog, `i2c@36c/@388`, `/cpus frequency` (or make 300-02 read the clock).
- Until then: U-Boot `ft_board_setup` patches the fixed-clock values.

## CPU overclock: measured (2026-10-10, mainline U-Boot RAM-loaded, heatsink off, stock core voltage)

- `clocks set cpu <e208> <e210> [relock] force`: stock sequence from SRAM with the lines I-cache locked (`clocks_sram.S`). Relock = `e200` bit 30 (chip `0x93030001`, bit 4 = 0). SRAM/UMSAR window remapped for the call, restored after.
- `./dev.py cpu-clock <e210> <e208> ...`: ladder; real rate measured from `sleep 5` vs host (CP0 Count = CPU/2).
- DIVN2 code 1 = /3 confirmed (rates match the formula within the timer's usual -0.3 %).

| CPU MHz | e208 | e210 | result |
|---|---|---|---|
| 775 | `0x3c8` | `0x6b439e23` | real 772.9 |
| 800 (stock) | `0x3e8` | `0x6b439e23` | real 797.6 |
| 816.7-983.3 | `0x2f8`-`0x398` | `0x6b439e13` | all PASS |
| 900 | `0x348` | `0x6b439e13` | uboot-test 39/40 (only the old cpu-800 pin failed), 78 C |
| 1000 | `0x3a8` | `0x6b439e13` | uboot-test **40/40**, highmem 12.4 s (14.3 s at 800), 79 C |
| 1016.7 / 1033.3 / 1050 | `0x3b8` / `0x3c8` / `0x3d8` | `0x6b439e13` | PASS (timer only) |
| 1066.7 | `0x3e8` | `0x6b439e13` | **hang** after the PLL write (VCO 3200 = stock's own max at /4, so the CPU, not the PLL) |

- Ceiling ~1050 MHz. Running choice not made yet: needs a long stress (Linux load, hours, temperature) before picking a default; 1000 MHz = 25 % over stock passed the suite.

## Change procedures

### (a) CPU PLL at runtime — stock sequence [BIN] `0x9f000850` -> `0x9f0002a0` (#38)

Stock runs it from SRAM with the routine's I-cache lines locked (`0x9f000240`, range `0x9f0002a0` + 8 KiB), then invalidates the I-cache. No DDR self-refresh: DRAM keeps its own PLL.

1. Read once (decides step 6): `md.l 0xbb000004 1` (model; bit 4 variant, [3:0] rev), `md.l 0xb8000044 1` (SSR), `md.l 0xb8000700 1`, `md.l 0xb80040f8 1`, `md.l 0xb8000388 1`.
2. Copy the routine to SRAM (KSEG0 `0x9f00xxxx`, clear of `0x9f000b70..0x9f000bbc` SPL globals) or lock it in I-cache. Not after `highmem map` (it unmaps SRAM: SRAMSAR cleared) unless re-mapped.
3. Wait UART TEMT (LSR bit 6) so no byte is in flight.
4. CP0 Config7 (`$16, 7`) |= `0xc` (34K branch/return prediction off; OpenWrt 839x does the same).
5. SSR `0xb8000044` bit 2 = 0 (CPU to the alternate clock). Write `0xbb00e208` (NCODE) **then** `0xbb00e210` (DIVN2): DIVN2 first with the old NCODE can briefly select a higher rate.
6. Relock trigger: if `0xbb000004` bit 4 = 1 and [3:0] < 3: `0xbb00e220` bit 17 (SW_CMU_EN) 0 -> 1; else `0xbb00e200` bit 30 0 -> 1. Live `e200` bit 30 = 0 and `e220` bit 17 = 1 point at the first branch (SPEC). Hazard: SW_CMU_EN also gates the SW PLL = LX, NOR, switch core: a toggle may glitch the console and the running switch.
7. Poll `0xbb00e200` bit 15 (CPU_PLL_READY) = 1. Stock has no limit. Ours: iteration bound, logged on expiry; lock time not known (SPEC: PLLs lock in tens of us).
8. SSR bit 2 = 1. Rewrite `0xb8000700`/`0xb80040f8` only if the CPU class changes (not for 500-999 MHz). Spin 10000 iterations (stock). Restore Config7. I-cache invalidate.
9. Nothing else scales with CPU: UART, I2C, SPI hang off the SW PLL. CP0 timer follows automatically (`get_tbclk`). Linux gets the new rate via `ft_board_setup`.
10. Verify: `clocks`; `./dev.py uboot-test timer` (sleep 5 vs host clock: measures the real CPU/2 against the decoded value); `highmem test`.

First experiments (exact values; `scripts/clock_calc.py cpu <MHz>`):

| Step | CPU | `0xbb00e208` | `0xbb00e210` | Point |
|---|---|---|---|---|
| 0 | 800 | `0x000003e8` | `0x6b439e23` | stock values: proves the sequence |
| 1 | 775 | `0x000003c8` | `0x6b439e23` | stock table row 15, below stock |
| 2 | **816.667** | `0x000002f8` | `0x6b439e13` | first overclock: NCODE 47, DIVN2 1 (/3), VCO 2450 = the SW CMU's own live VCO |
| 3 | 833.333 / 850 / 866.667 / 883.333 / 900 | `0x308` / `0x318` / `0x328` / `0x338` / `0x348` | `0x6b439e13` | +16.7 MHz steps, VCO 2500-2700 |

- DIVN2 code 1 = /3 is the SPL's own arithmetic (`D + 2`), never exercised by stock: SPEC. If `sleep` shows a different rate, the code is not /3.
- Alternative 825 MHz with DIVN2 2 needs VCO 3300 (above the stock 2400-3200 range).

### LX at runtime [BIN] `0x9f0008a4`

1. Wait UART TEMT. `0xbb00e200` bit 17 (LXB_CLK_SEL) = 1 (SPEC: glitch-free switch to the alternate clock).
2. `0xbb00e220[12:9]` = new code (4 = 204.17 MHz, inside the SPL window). `0xbb00e200` bit 17 = 0.
3. `0xb80040f8` bit 8 = (250 >= 3 x LX): 0 for 175 and 204.
4. Same step, before any output: UART divisor = round(LX / 16 / baud): 115200 -> 111 (114,958 baud, -0.2 %); write LCR DLAB, DLL/DLM, LCR. Update the ns16550 `plat->clock` (read once at probe) or U-Boot's next `setenv baudrate` uses the old LX.
5. Scales with LX: UART, otto timer + watchdog (Linux), I2C SCL (SPEC), LX bus masters. Not: CPU, DDR, SPI (NOR has its own divider).

### (b) DDR clock and timings (#39)

Runtime change from DRAM-resident U-Boot: high risk, several unknowns. Order of preference:

1. **SRAM test program** (recommended first): RAM-loaded from stock U-Boot, copies itself to SRAM (64 KiB), runs with stack in SRAM, never touches DRAM until re-init. DRAM contents are abandoned (payload already done); result printed on UART; power cycle after.
   1. MPCR4[5:0] = 0; 200 us; MPCR0-2 = 600 row (`0x7f`, `0x400001ef`, `0x26a33860`, SPEC for 650), MPCR3 = `0x320f0000` (650); MPCR5 = MPCR6 = 0; 5 us; MPCR4[5:0] = `0x3f`; 200 us. CMUCR_OC0/LX*[9] unchanged (MEM >= CPU/2, MEM >= LX).
   2. Full DDR3 init exactly as the SPL at f = 650 (#23 sequence): PHY pre-config 650 branch, DCR provisional `0x21320000`, DTR0/1/2 = `0x99655838` / `0x0909061f` / `0x0ae19000`, ZQ cal, MRS (MR0 from CL10/tWR10, MR2 CWL7: same codes as 600), DLL reset, per-DQ tap training, DCR final `0x21421003`.
   3. Memory test (address^pattern, both banks via highmem remap). Report taps and errors.
2. **Runtime, keep DRAM** (only after 1 passes): flush D-cache; run from SRAM; write the 650 DTRs first (each field >= the 600 value: safe at 600), trigger by rewriting DCR and poll DMCR bit 31 = 0 (SPL order, SPEC that the DCR write latches DTRs); enter self-refresh (MPMR0 PM_MODE, encoding unknown: SPEC); MEM PLL as step 1.1; exit self-refresh; MR0 DLL reset + 512 clk; ZQCL (`0xb8001094`); retrain taps (destroys a 64 KiB buffer). JEDEC allows a DDR3 clock change only in self-refresh or precharge power-down.
3. **Own SPL in flash**: final form; needs flash writes, out of scope.

- Next bins: DDR3-1300 (650) uses the stock 650 DTR bin; above 650 needs new DTRs from the DRAM datasheet (part unknown) and PHY settings the SPL does not have.

### (c) Recovery

- All of the above is RAM-loaded. Power cycle (`./dev.py power off`/`on`, or `./dev.py stock`) reruns the stock SPL: stock clocks and DDR init. Flash is never written.
- A hung CPU or DRAM after a change is recovered the same way; there is no state to clean up.
