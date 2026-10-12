# SPI-NOR: controller, flash limits, Linux read path

Facts only, code reading 2026-10-13 (#50, #61). Measured ladders: [CLOCKS.md](CLOCKS.md#spi-nor-read-path). Sources: `SDK` = GPL SDK 4.0.2 `loader/u-boot-2011.12/arch/otto40/` ([SDK-SOURCES.md](SDK-SOURCES.md)); `DS` = `sources/winbond-W25Q256JV-RevL.pdf` (printed page numbers).

## Controller (RTL9300 = SDK `nor_spi_gen3`, `plr/src/soc/nor_spi_gen3/nor_spif_register.h`)

| Reg | Fields | Stock / SDK use |
|---|---|---|
| SFCR `b8001200` | clk_div 31:29, RBO 28, WBO 27, SPI_TCS 26:22, TCHSH 7:4, TSLCH 3:0 | `5fc00244`; SDK writes only clk_div (`nor_spif_div_ctrl.c:60`) |
| SFCR2 `b8001204` | cmd 31:24, size 23:21, rd_opt 20, cmd_io 19:18, addr_io 17:16, dummy 15:13 (clocks / 2), data_io 12:11, 4B 9 | `bbc14a00` (BBh dual I/O); written only in `nor_spif_core.c:384-425` |
| SFCSR `b8001208` | CSB0 31, LEN 29:28, RDY 27, IO_WIDTH 26:25, CMD 23:16, CSB_STS 11:10, IDLE 4 | PIO; SDK sets IO_WIDTH per phase and waits RDY+IDLE and CSB_STS (`nor_spif_core.c:217-375`) |
| SFRDR `b8001218` | per-IO read sample delay io3 28:24, io2 20:16, io1 12:8, io0 4:0 | 0; **nothing in the SDK or reyalo trees writes it**; units undocumented |

- No pipeline-latency field on the NOR controller. `snaf_pl` (2 above 50 MHz, `platform/9300/cg/cg.c:213-214`) is SPI-NAND only (SNAFCFR `b801a400`).
- SDK clock limits (`platform/9300/cg/cg.c:29-33, 196`): NOR source 133-204 MHz, SCK ≤ 105 MHz. NOR code 4 (204.2 MHz source, SCK 102.1) = the SDK ceiling; code 3 (245 MHz, SCK 122.5) is outside it.
- SDK changes the NOR source with PLL_GLB_CTRL0 `nor_clk_sel` = 1 around the divider write (`cg.c:94-104`); our ladder writes e220[16:13] directly (`scripts/flash_speed_step.py`).

## Flash: W25Q256JVFIQ (DS)

- FR 133 MHz (3.0-3.6 V) for every read except 03h/13h; **fR = 50 MHz for 03h and 13h** (p.38 13h: "D.C. to a maximum of fR"; p.82).
- Dummy clocks fixed, not frequency-dependent: 0Bh/0Ch 8, 3Bh/3Ch 8, 6Bh/6Ch 8, BBh/BCh 4 (mode byte M7-0), EBh/ECh 2 mode + 4 dummy (p.25-29, p.39). No Set Read Parameters (C0h).
- No DTR, no QPI on IQ parts (p.24).
- tCLQV ≤ 6 ns, tCLQX ≥ 1.5 ns at 30 pF (p.82).
- Output drive SR3 DRV1:0 (§7.1.8 p.19): 00 100 %, 01 75 %, 10 50 %, 11 25 %. **IQ factory default = 25 %.** Volatile write: 50h then 11h.

| SCK MHz | Period ns | Period - tCLQV ns |
|---|---|---|
| 102.1 | 9.79 | 3.79 |
| 122.5 | 8.16 | 2.16 |
| 133 | 7.52 | 1.52 |
| 153.1 | 6.53 | 0.53 |

- The window reads pass at 122.5 MHz, so the controller samples about one period after the launch edge: margin = period - tCLQV - round trip - setup. Fits 122.5 passing and 153.1 failing (U-Boot whole-chip CRC). Only SFRDR or a stronger driver (DRV) moves that limit.

## Linux read path

- Upstream `spi-realtek-rtl.c` sets no `mode_bits` → 1-1-1 only.
- spi-nor uses Fast Read only with `m25p,fast-read` in the DT when a node exists (`drivers/mtd/spi-nor/core.c:3122-3124`; U-Boot `spi-nor-core.c:3089-3093`). None of our three DTs has it (OpenWrt `rtl9303_tplink_tl-st1008f-v2.dts`, `mainline/tplink-tl-st1008f-v2.dts`, `uboot-port/.../tplink_tl-st1008f.dts`).
- W25Q256JV gets 4-byte opcodes → **reads use 13h, 0 dummy, rated 50 MHz**. Matches the dirmap log `op 0x13` (CLOCKS.md).
- Flash OpenWrt during the #50 failures = release 25.12.4 / 6.18.55 (OPENWRT-BUILD.md): upstream PIO driver, no dirmap.
- U-Boot's window uses BBh/EBh (rated 133 MHz). Our U-Boot `sf read` = PIO driver (`uboot-port/drivers/spi/spi-realtek-rtl.c`, accepts 13h and 0Ch), same DT rule → 13h.

### #50 explained

- 102.1 MHz = 2.0x and 122.5 MHz = 2.45x the 13h rating. 13h has no dummy clocks: the first data bit follows the last address bit by half a clock, without the access time the dummy clocks give.
- Bulk md5 (mtdblock, large reads): few commands per byte → rare errors (122.5 fails, 102.1 passes).
- JFFS2 reads thousands of 12-68 byte nodes, each a new 13h command, each CRC-checked → 102.1 fails.
- 122.5 MHz also runs the NOR source above the SDK's 204 MHz with 2.2 ns margin.
- Smaller PIO differences from the SDK: Linux polls RDY only (no IDLE), rewrites SFCSR per word, raises CS without waiting CSB_STS.

## Settings to try, highest first

Bench order: [CLOCKS-OPS.md](CLOCKS-OPS.md#spi-nor-leads-50).

1. `m25p,fast-read;` in the flash node (OpenWrt, mainline, U-Boot DTs): 0Ch, 8 dummy, rated 133 MHz.
2. All Linux reads through dirmap with SFCR2 = 4-byte quad I/O (ECh class, `ebc27200` CRC-proven at 122.5 MHz in U-Boot); 300-07 + `dirmap` reg in the flash image.
3. SR3 DRV = 100 % (volatile first); recheck the window at 153.1 MHz.
4. SFRDR sweep (io0-3 together) at the first failing step.
5. Driver: wait RDY|IDLE and CSB_STS; `mode_bits` RX_DUAL/QUAD + SFCSR IO_WIDTH per `rx_nbits` → `spi-rx-bus-width = <4>` usable.
6. Stay at NOR code ≥ 4 (≤ 102.1 MHz) until 1-4 pass at 122.5.
- CS timing (TCS 31, TCHSH/TSLCH 4) is far above the 3 ns / 10 ns minimums: not a cause.
