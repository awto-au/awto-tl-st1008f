# RTL9303 clock tree and overclocking

Source tags: **[SRC]** GPL file:line (`dms1250/` = `sources/rtk-dms1250/`, `xgs1210/` = `sources/uboot-xgs1210/` in a clone of `github.com/reyalo/Realtek`; `owrt/` = OpenWrt `target/linux/realtek/`). **[BIN]** stock preloader (SPL) VA (`loader.bin` file `0x0000..0x507f`, XIP at `0x9fc00000`, SRAM copy at `0x9f000000`). **[LIVE]** register dump on this unit, 2026-10-10, mainline U-Boot after stock SPL init. **[DS]** `sources/rtl9303-cg-brief.pdf` (Rev 1.1-1). **SPEC** = inferred, not verified on hardware.

- Read it live: `clocks` (U-Boot, `board/tplink/tl-st1008f/clocks.c`). Host: `scripts/clock_calc.py decode <md.l dump>`.
- Writes: `clocks set cpu ... force` (procedure (a)) and `clocks set mem <MHz> force` (procedure (b)), both from SRAM; nothing else writes a clock register.
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

- MEM `+ 2`: RTL9300 SPL (two places) and the RTL9300 SDK `cg_mem.c:9` agree; OpenWrt's `+ 3` is the RTL960x formula (`owrt/files-6.18/drivers/clk/realtek/clk-rtl83xx.c:508-530`). DDR clock itself not measured (#39).
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
| `0234..024c` MEM PLL fields | — | [SRC] `xgs1210/arch/otto40/plr/src/platform/9300/cg/mem_pll.h:5-135`: MPCR0 `en_post_pi` 6:0, phase selects CK 16:12, CLKM 21:17, DQS0 26:22, DQS1 31:27; MPCR1 `cco_band` 31:30, DQ8-15 PI 4:0, DQ0-7 PI 9:5; MPCR2 `pdiv` 15:14, `icp` 11:8, `lpf_sr`, LDO; MPCR3 `n_code` 31:24; MPCR4 `clk_oe` 5:0, `dpi_mck_clk_en` 11:6; MPCR5 `f_code` 12:0 (0: integer N); MPCR6 SSC | — |
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
| `101c` DMCR write | — | any write latches DTR0-2 and issues the MRS in MR_MODE/MR_DATA; bit 31 busy until done; DIS_DRAM_REF 24 = refresh off. SDK rewrites it unchanged after DCR/DTR edits with DRAM live [SRC] `xgs1210/.../platform/9300/dram_gen4_9300/boot0412/memctl.c:2044`; MRS loop `.../fpga/memcntlr_setup.c:871-882` |
| `1038` MSRR | not dumped | FLUSH_OCP_CMD 31, DRAM_CMD_GOING 30 (reset 1). Not used |
| `1040` MPMR0 | `clocks` prints it | PM_MODE 29:28, T_CKE 27:24, TRSD 21:12, T_XSREF 9:0 (reset `0f3ff3ff`) [SRC] `.../dram_gen4_9300/memcntlr_reg.h:241-257`. PM_MODE 2 = self-refresh: SPEC (older Realtek controller, same field at 31:30: test code writes `0x8BFF1000` and treats read-back 2 as "in self-refresh", a bus access wakes it [SRC] `xgs1210/arch/otto/cpu/rlx5281/rtl8686/rtk_soc/test/crypto/crypto/rtl865xc_cryptoEngine.c:375-392`) |
| `1500` DACCR | `clocks` prints it | AC_MODE 31 (1 = digital delay), DQS0/1 group taps 20:16 / 12:8, AC_DYN_BPTR_CLR_EN 5, AC_BPTR_CLEAR 4 [SRC] `memcntlr_reg.h:766-790`. PHY FIFO reset = bit 4 0 -> 1, bit 5 = 1 [SRC] `xgs1210/arch/otto40/plr/src/soc/dram_gen4/memcntlr_setup.c:647-651` |
| `15b0..15c4` DCSDCR0-3, DWDMOR, DWDQSOR | `clocks` prints them | command/address/DQS delay taps [SRC] `memcntlr_reg.h:1010-1117`; the SPL writes speed-dependent values here (PHY pre-config) [BIN] |

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

- Same table in the GPL SDK [SRC] `xgs1210/arch/otto40/plr/src/platform/9300/cg/cg_mem.c:29-49` (formula `25*(ncode+2)/(2*(1<<pdiv))`, line 9 — settles the `+ 2`).
- Apply [SRC] `cg_mem.c:60-83` `cg_mem_pll_init`: MPCR4 `clk_oe` = 0, 200 us, write MPCR0-3, MPCR5 = MPCR6 = 0, 5 us, `clk_oe` = `0x3f`, 200 us; then CMUCR_OC0[9] = (CPU <= MEM), CMUCR_LX0-2/LXP[9] = (LX <= MEM), 50 us. No MEM PLL ready bit: fixed waits.
- No row above 600. 650 = 600 row + MPCR3 NCODE `0x32` (SPEC: MPCR0-2 hold PI phases and loop settings, 600 values reused).

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
| DDR3 clock | [DS] 8.3 "up to 800MHz (DDR3-1600)"; [DS] Table 25 fCK typ 600 MHz; SPL PLL table max 600, DTR/PHY to 650 | DRAM K4B4G1646E-BYMA = DDR3L-1866 (933 MHz) per OpenWrt commit `39b9b491bb`, not read on this unit | 600 (DDR3-1200); 650 via `clocks set mem` (untested) | stock; 650 = highest bin without an MRS (CWL 7 legal to 666 MHz) |
| DDR3 timings | part unknown | — | CL10 CWL7 tRCD/tRP 15 ns, tREFI 3.84 us | stock bin; tREFI at 2x rate costs ~3 % bandwidth (SPEC) |
| SPI SCK | 133 MHz FAST_READ (W25Q256JV) | not measured | 25.5 MHz | #35 |
| UART | LX / 16 = 10.94 MBd | host adapter (#32) | 115200 or `--fast` | host side |

- DRAM part: not visible in the board photos (top and bottom) → it sits under the SoC heatsink. OpenWrt commit `39b9b491bb` ("realtek: add support for TP-Link TL-ST1008F v2.0") lists Samsung K4B4G1646E-BYMA (4 Gbit x16 E-die, `Y` = DDR3L 1.35 V / 1.5 V capable, `MA` = DDR3-1866 13-13-13). Matches DCR/DTR2 (4 Gbit x16); speed bin SPEC until read.
- To confirm (main session, heatsink off): marking line 2 `K4B4G1646E-BYMA` (or other suffix: `-BCK0`/`-BYK0` DDR3-1600, `-BCH9` DDR3-1333 → 666 MHz cap), date code, and whether it is the only DRAM package. Photo it into `artifacts/`.
- Rated min at DDR3-1866 (JEDEC 13-13-13): tRCD = tRP = 13.91 ns, tRAS 34 ns, tWR 15 ns, tRTP/tWTR 7.5 ns, tRFC 260 ns (4 Gbit). The stock 650 bin (tRP/tRCD 10 clk = 15.4 ns, tRAS 26 = 40 ns) is inside it.

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

### (b) DDR clock at runtime, DRAM kept — `clocks set mem <MHz> [nosr] force` (#39)

Implemented: `board/tplink/tl-st1008f/ddr_sram.S` (routine), `clocks.c` `mem_set()` (C side), `scripts/mem_clock_step.py` / `./dev.py mem-clock` (verify). Built, **not run on hardware yet**.

C side, before the routine:

1. Bin = stock DTR bin (650, 600, 550, 500, 450, 400, 350, 300). PLL row per bin [SRC] `cg_mem.c:32-43`; 650 = 600 row + NCODE `0x32` (SPEC). DTR2 = ((MHz x tRFC_ns / 1000 + 5) << 20) | base, tRFC by die size from DCR (4 Gbit: 260 ns) [BIN].
2. Refuse: CL or CWL differ from the live DTR0 (needs MRS, #48) → only 650/600/550 pass on this board; MEM crossing CPU or LX (CMUCR SE_DRAM bits would change, [SRC] `cg_mem.c:54-55`); DCR not one x16 die.
3. Prints every register it will write (old -> new).
4. Canary: 1024 words (offset ^ seed) written uncached into a fresh heap buffer after `flush_dcache_range` on it.
5. Map SRAM (stock window, as (a)), copy routine to `0x9f004000`, I-cache fetch-and-lock; parameter block at `0xbf004800` (uncached SRAM; layout `ddr_sram.h`). Wait UART TEMT.
6. D-cache index write-back-invalidate of every line (Config1 geometry), as the last step before the call: no dirty line can be evicted while DRAM is in self-refresh. The routine makes no cached access.

Routine (SRAM, no stack, KSEG1 I/O only; UART marks `M S P X D` then `C`/`F`):

1. Config7 |= `0xc` (prediction off), `sync`, SRAM read.
2. DMCR `0xb800101c` bit 31 = 0 (bounded poll) else status 1, nothing written.
3. Clock going up: DTR0/1/2 written first (every 650 field >= the 600 field: valid at 600 too), DMCR rewritten unchanged = DTR latch [SRC] `boot0412/memctl.c:2044`; poll bit 31 else status 2, PLL untouched.
4. Self-refresh: MPMR0 `0xb8001040` PM_MODE 29:28 = 2 (SPEC encoding, see register map), read back into the block; 1 us. `nosr`: DMCR DIS_DRAM_REF 24 = 1 instead (DRAM unclocked-but-not-in-SR: violates JEDEC, no DLL reset on exit; fallback only).
5. MEM PLL = SDK `cg_mem_pll_init` [SRC] `cg_mem.c:60-73`: MPCR4 `clk_oe` = 0, 200 us; MPCR0-3; MPCR5 = MPCR6 = 0; 5 us; `clk_oe` = `0x3f`; 200 us. CMUCR not touched (refused in C if it would change).
6. Exit: PM_MODE = 0 (read back), 10 us (tXSDLL 512 clk = 0.8 us at 650). DRAM DLL resets itself on SR exit (JESD79-3); CL 10 / CWL 7 / WR 10 stay legal to 666 MHz, so no MRS.
7. PHY FIFO pointer clear: DACCR `0xb8001500` bit 4 0 -> 1, bit 5 = 1 [SRC] `soc/dram_gen4/memcntlr_setup.c:647-651`.
8. Clock going down: DTRs + latch now (status 4 on timeout).
9. Canary read back uncached. Mismatch → status `0x10`, the same sequence back to the set read before the change, canary again (`0x20` good / `0x40` still bad).

Bounds and waits:

| Wait | Value | Why |
|---|---|---|
| DMCR busy | 64 polls | DTR latch + one MRS: tMOD 12-24 clk + bus ~1 us; poll >= 50 ns → >= 3.2 us. Poll count left is reported: tighten once measured |
| PLL settle | 200 + 5 + 200 us fixed | SDK values; the MEM PLL has no ready bit |
| delay loop | `loops/us` = CPU MHz / 2 | 2-instruction loop >= 2 cycles: never shorter than asked |
| UART mark | 110 x 1 us | one char at 115200 = 87 us x 1.25; expiry drops the mark |

SPEC / unverified:

- PM_MODE 2 = self-refresh on this controller; whether it precharges all banks and how long entry takes. MPMR0 read-backs are printed (`MPMR0 in SR` should show `2` in 29:28, `exit` `0`).
- 650 MPCR0-2 (600 row reused).
- PHY delay taps (DCSDCR0-3, DWDQSOR) stay at their 600 values; the SPL has a 650 branch with different values (#49). AC_MODE = digital delay: taps are absolute, an 8 % shorter period moves the eye.
- No ZQCL after the change (not required by JEDEC for a frequency change; periodic ZQCS per D3ZQCCR unchanged).
- Other DRAM masters: the switch NIC DMA must be idle (no `rtk network on`, no eth command in this boot before the change; SPEC whether stock U-Boot's TFTP leaves it running after `go`).
- OpenWrt (`clk-rtl838x-sram.S`, `clk-rtl83xx.c:630-640`) does not change MEM at runtime: its MEM `set_rate` is pinned to the startup rate, with a TODO naming DTRs and DLL reset.

Run (main session): `./dev.py ramload uboot-mainline`, then `./dev.py mem-clock 600 650`. 600 first = stock values through the new sequence (proves self-refresh entry/exit and the PLL rewrite without a rate change). Pass per bin = `mem set OK`, `clocks` decodes the bin, crc32 + `md` of 16 MiB copied before the first change unchanged, `highmem test` 0 errors, crc32 unchanged after it. Hang = power cycle. If 600 hangs: retry with `--nosr` once, record which mark was last printed.

- Above 650: CWL 8 → MRS with unknown stock MR0-MR2 (#48).
- Fallback if the runtime path fails: SRAM-resident program (64 KiB SRAM, stack in SRAM) re-running the full SPL DDR init at 650 (PHY pre-config 650 branch, DCR provisional `0x21320000`, DTRs, ZQ cal, MRS, DLL reset, tap training, DCR `0x21421003`), then memtest; DRAM contents abandoned, power cycle after.
- Final form: own SPL in flash (flash writes: out of scope).
- Size: `uboot-mainline.bin` 301,941 -> 307,485 bytes (+5,544; routine 1,124 bytes), 2026-10-11.

### (c) Recovery

- All of the above is RAM-loaded. Power cycle (`./dev.py power off`/`on`, or `./dev.py stock`) reruns the stock SPL: stock clocks and DDR init. Flash is never written.
- A hung CPU or DRAM after a change is recovered the same way; there is no state to clean up.
