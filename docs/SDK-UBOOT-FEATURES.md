# Realtek SDK U-Boot / preloader feature inventory (RTL9300 / 9303)

Every feature in the SDK loader sources for the RTL930x, whether the stock TP-Link build has it, whether our U-Boot has it, and what is worth adding. Facts only; do not repeat: [SDK-LEFTOVERS.md](SDK-LEFTOVERS.md) (test commands, #74), [SDK-FEATURE-MAP.md](SDK-FEATURE-MAP.md) (API slots, #76), [HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md) (SoC blocks, #62), [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (registers, #68), [DRAM.md](DRAM.md), [CLOCKS.md](CLOCKS.md), [RTK-COMMANDS.md](RTK-COMMANDS.md) (`rtk` verb parity, 62/62), [UBOOT-REFERENCE.md](UBOOT-REFERENCE.md) (stock loader), [UBOOT-MAINLINE.md](UBOOT-MAINLINE.md), [SDK-SOURCES.md](SDK-SOURCES.md).

## Method and legend

- Path tags (all read-only, under `sources/` of a clone of `github.com/reyalo/Realtek` unless noted):
  - **DMS** `sources/uboot-dms1250` (U-Boot 2011.12, D-Link, SDK 3.6.9; has `.config`, `u-boot.map`).
  - **XGS** `sources/uboot-xgs1210` (Zyxel, SDK trunk 2020; adds `httpd/`, `sys` commands).
  - **RTK-D** `sources/rtk-dms1250`, **RTK-X** `sources/rtk-xgs1210` (SDK `system/uboot`, `config`).
  - **TPL** `private/tplink-gpl-sg3218xp-m2-v2/rtk-ms-sdk-4.0.2.55154/loader/u-boot-2011.12` (TP-Link GPL, SDK 4.0.2; has `.config`, `.o` files, `u-boot.map`).
  - **PLR** = `arch/otto40/plr` inside DMS/TPL (preloader). **OLV** = `git_mirror/olliver/realtek_sdk` (SDK 3.5.0).
- "Stock" evidence, strongest first: **HELP** `artifacts/uboot-help.txt` (49-entry live `help`); **STR** `strings` of the ST1008F stock `loader.bin` (`private/stock-loader-20261007/`); TPL `.config` + built `.o` list (SG3218XP-M2, not our board: same SDK family, 4.0.2 vs stock 3.6.6).
- Stock column: **Y** present; **N** absent (HELP/STR zero hits); **dead** source/object exists but no reachable command or Kconfig symbol; **?** unverified.
- Ours column: **Y**, **part**, **N** (`uboot-port/board/tplink/tl-st1008f/` = **UP**, defconfig `uboot-port/configs/tplink_tl-st1008f_ram_defconfig`, build `.config` `tmp/uboot-mainline-build/.config`).
- Value to us: high / medium / low / none (CPU-less 10G SFP+ bench switch; sw2 only; no PHYs; NOR 32 MiB).
- Findings are in this doc only; no issue filed (read-only task). Open questions numbered Q1.. at the end.

## 1. Summary

| Section | Rows | In stock | In ours (Y / part) | Value high or medium |
|---|---|---|---|---|
| 2 Commands (C) | 41 | 14 | 3 / 3 | 6 |
| 3 Config options (O) | 54 | 37 | 28 / 2 | 0 |
| 4 Preloader init functions (P) | 15 | 6 | 1 / 1 | 0 |
| 5 Drivers / hardware blocks (D) | 33 | 21 | 13 / 6 | 4 |
| Total | 143 | 78 | 45 / 12 | 10 |

- N = 143 features (each row once). M = 78 present in the stock build. K = 57 in ours (45 full, 12 partial).
- Counting rule: stock = Y, stubs, or a concrete stock value; ours = Y, part, or a concrete value of its own. Option rows are fuzzy (a stock default that merely differs counts as present). `?` and `n/a` count as neither.
- 65 rows are not in stock (N, dead, `?`, n/a). Of the 10 high or medium rows, 9 are not in stock (D06, DDR calibration, is) - section 8.

- Stock build = U-Boot 2011.12 + SDK `rtk` layer; the 9300 "Diagnosis Tools" menu (`board/Realtek/rtl9300/menuconfig.in:1-12`) is entirely off: STR has 0 hits for `mdram_test`, `mconcur_test`, `mflash_test`, `mgdma`, `next_freq`, `boot_bin`.
- 9300 test commands cannot build from the public trees: `board/Realtek/rtl9300/` holds only `board_cmd.c` + headers; `dram_test`/`flash_test`/`concur_test`/`gdma_driver.o` live only in rtl838x/839x dirs and an old Otto-gen tree (`arch/otto/cpu/rlx5281/rtl8686/rtk_soc/test/`).
- Preloader (PLR) in stock = 6 init functions (section 4). The preloader CLI, `dss_test`, BTG tests and `mt_ram_test` are in the tree but not built into the 9300 NOR project.
- Largest unexploited SDK items for us: DDR calibration routines (DRAM.md lead 1), BTG + GDMA concurrent stress, die-speed-sensor sequence, HTP loopback tests, TP-Link `dt_*` DRAM bus tests.

## 2. Commands

Registered with `U_BOOT_CMD` (or the `rtk`/`sys` dispatchers) in the SDK loader; generic commands enabled by the SDK defconfig. Menu symbols are `board/Realtek/rtl9300/menuconfig.in` lines (:4 DRAM Test, :5 DRAM Diagnosis `#`, :6 SPI FLASH Test, :7 GDMA `#`, :8 SRAM `#`, :9 Concurrent, :10 Forever `#`, :11 DRAM AC DC; `#` = commented out).

| Feature | SDK file:line | Stock | Ours | Value |
|---|---|---|---|---|
| C01 `mdram_test` | DMS board_cmd.c:438; menu :4 | N | part (`memtest`, UP memtest.c:201) | low |
| C02 `mflash_test` | DMS board_cmd.c:446; menu :6 | N | N | low |
| C03 `mconcur_test` | DMS board_cmd.c:487; menu :9; Makefile:12-13 | N | N | medium |
| C04 `mgdma_test` | DMS board_cmd.c:470; menu :7 `#` | N | N (kmod only) | low |
| C05 `midmem_test` | DMS board_cmd.c:479 | dead | N | none |
| C06 `forever_test` | DMS board_cmd.c:462; menu :10 `#` | dead | N | none |
| C07 `mdram_dig` | DMS board_cmd.c:430; menu :5 `#` | dead | N | none |
| C08 `mwrite_test` `mread_test` `mwrite_read_test` | DMS board_cmd.c:406-426; menu :11 | N | N | low |
| C09 `boot_bin` | DMS board_cmd.c:454 (no menu symbol) | dead | N | none |
| C10 `next_freq` | DMS board_cmd.c:495 (no menu symbol) | dead | N | none |
| C11 `reset_all` | DMS board_cmd.c:503 | Y | part (`reset`, cpu.c:36) | low |
| C12 `do_mem_mtest_dtr` (8 h retention) | DMS board_cmd.c:10 | dead | N | low |
| C13 `rtk eee on/off` | RTK-D uboot_cmd.c:369 (`CONFIG_EEE`) | N | N | none |
| C14 `rtk send` | RTK-D uboot_cmd.c:866 | Y (hidden) | N (stub) | low |
| C15 `rtk sfp-speed` `sys-esd` `parameter version` | RTK-D uboot_cmd.c:319-351 (8390 only) | N | N | none |
| C16 `rtk l2-testmode` | RTK-D uboot_cmd.c:784 (8380 only) | N | N | none |
| C17 `rtk mib` `looptest` `looptest_cfg` | RTK-D uboot_cmd.c:879-1450 (9310 only) | N | N | none |
| C18 `rtk testmode` | RTK-D uboot_cmd.c:1462 (help text) | Y (text only) | Y (Usage) | none |
| C19 `sys burn-in enable/time/summary` | RTK-X uboot_cmd.c:1564-1595; uboot_func.c:3484,3512,4100 | N | N | medium |
| C20 `sys errlog clear` | RTK-X uboot_cmd.c:1513; uboot_func.c:3493 | N | N | low |
| C21 `sys internal-loopback-set/unset/test` | RTK-X uboot_cmd.c:1532-1555; uboot_func.c:3805,3816 | N | N | medium |
| C22 `sys external-loopback-test` | RTK-X uboot_cmd.c:1556; uboot_func.c:3920 | N | N | medium |
| C23 `sys fan-test` | RTK-X uboot_cmd.c:1522 (`CONFIG_PRODUCT_XGS1250`) | N | N | none |
| C24 `boota [0\|1]` dual image | XGS common/cmd_bootm.c:1782 | Y | part (`bootsel`, UP bootsel.c:439) | covered |
| C25 `bootf` | DMS common/cmd_bootm.c:1943 | N | N | none |
| C26 `httpd` web failsafe | XGS common/cmd_net.c:35-43; net/net.c:2111-2457 | N | N | low |
| C27 `bootldr` `spibootldr` `ldrinfo` | XGS common/cmd_bootldr.c:165, cmd_spibootldr.c:33, cmd_ldrinfo.c:188 | N | N | none |
| C28 `upgrade loader\|runtime1\|runtime2\|rom` | RTK-D cmd_upgrade.c:740 | Y | N (by design) | none |
| C29 `flshow` | RTK-D cmd_partition.c:169 | Y | N | low |
| C30 `flerase` | RTK-D cmd_partition.c:137 | Y | N (banned) | none |
| C31 `printsys` `setsys` `savesys` | RTK-D cmd_sysinfo.c:422,430,439 | Y | N (bootsel record) | none |
| C32 `loadb` `loads` `loady` | XGS common/cmd_load.c:1029-1082 | Y | N | medium |
| C33 `mtest` | common/cmd_mem.c (`CONFIG_CMD_MEMORY`) | Y | N (no `CMD_MEMTEST`) | low |
| C34 `erase` `protect` `flinfo` | common/cmd_flash.c | Y (no-op stubs) | N | none |
| C35 `saveenv` / `env` in SPI flash | common/cmd_nvedit.c; env_sf.c | Y | N (`ENV_IS_NOWHERE`) | low |
| C36 `md5sum` `sha1sum` | DMS common/cmd_md5sum.c:49, cmd_sha1sum.c:49 | N | N | low |
| C37 `sntp` `dns` `nfs` `rarp` | XGS net/sntp.c, dns.c, nfs.c, rarp.c | N | N | none |
| C38 `usb` (EHCI RTL9300) | TPL drivers/usb/host/ehci-rtl9300.c; rtl9300.h:182-189 | N | N | none |
| C39 TP-Link `dt_*` DRAM tests | TPL common/dt_bus.c:595,852; dt_stable.c:114,288,396; dt_verify.c:245,498; dt_mtest.c:433; Makefile:187 | dead | N | medium |
| C40 `rtk` stock verbs (40 forms) | RTK-D uboot_cmd.c:151-866 | Y | Y (62/62) | covered |
| C41 generic shell: `base cmp cp crc32 go help iminfo loop md mm mw nm run sleep version printenv setenv bootm bootp ping tftpboot sf` | common/, net/ | Y | Y | covered |

Notes:
- C01-C03, C08: symbols exist in the menu but TPL `.config` has none set (`.config` tail: only `CONFIG_CMD_SF/RTK/RUN/NET/PING/IMI/LOADB/LOADS/SAVEENV/FLASH/MEMORY`).
- C01/C02/C03: 9300 board dir lacks `dram_test`, `flash_test`, `concur_test`, `gdma_driver.c`, `concur_pattern.c` (Makefile:12-13 names the objects; `find` over DMS/XGS/TPL: none). Reference implementations: rtl838x `memctl_dram.c:1401` (4-6 passes: uncached, cached, +data/ins prefetch), rtl838x `memctl_flash.c:832` (backs up the range, destructive patterns, restores), PLR `rtk_mem_test/memctl_dram.c:1265`, old-gen `rtk_soc/test/concur/concur_test.c` (CPU + GDMA + IDMEM concurrent).
- C08: infinite write/read hammer on one address for scope probing; `loop` + `mw` do the same.
- C12: write pattern, wait 2 880 000 x 10 ms, read back; symbol in `u-boot.map` (DMS line 340), no `U_BOOT_CMD`.
- C14: hidden in stock ([RTK-COMMANDS.md](RTK-COMMANDS.md#stock-verbs) `send`); transmits a fixed `pkt_content` via `NetSendPacket`, then polls RX 80 times. Ours prints `not yet` (UP cmd_rtk.c `rtk_not_yet("send")`) although `rtl930x_eth.c` now exists.
- C19-C23: Zyxel "HTP" (hardware test program). `burn-in time N` (N <= 10 h) loops DRAM, flash, port-loopback and PHY-register tests (`sys_htp_run_case`, uboot_func.c:4100); result log written to flash `0xb4ff0000` (uboot_func.c:62-64) - collides with our firmware slot B on ST1008F, never port the log as is. Error codes: DRAM_VAL, FLSH_DDR_VAL, FLSH_SPI_PRB, FLSH_FLS_VAL, PORT_LOP_SET, PORT_PKT_VAL, BREAK, FAN_FAIL, PHY_REG_FAIL (uboot_func.c:3539-3557).
- C26: `boota` failure on both slots calls `rtk_network_on()` + `NetLoopHttpd()` (cmd_bootm.c:1736-1745, 1796-1806); uIP server in `XGS httpd/`; upload then "Upgrading..." (net.c:2220-2228). Kconfig `CONFIG_CMD_HTTPD` XGS config.in:83.
- C32: ours defconfig `# CONFIG_CMD_LOADB is not set`, `# CONFIG_CMD_LOADS is not set`; stock HELP lists `loadb`, `loads`, `loady`.
- C36: neither command is in HELP; ours has the MD5/SHA1 libs (`CONFIG_MD5=y`, `CONFIG_SHA1=y`) but no command.
- C39: TP-Link addition (copyright header "TP-LINK Co., Ltd R&D SMB", dt_mtest.c:1-6), objects linked unconditionally but no `U_BOOT_CMD` in any `dt_*.c`; STR has no `xtalk`/bus-test strings. Functions: data-bus walk, address-bus walk, pattern, stable, fade (retention), read-write-mix, crosstalk helpers. License of the TP-Link-authored files: unverified (GPL tree, no SPDX).
- C40/C41: parity and command list in the linked docs; HELP shows `reset_all`, `printsys`, `savesys`, `setsys`, `upgrade`, `flerase`, `flshow`, `boota`, `rtk`.
- Ours-only commands (not SDK): `memtest bench busscan highmem clocks bootsel turbo ethstat`, `rtk laser sfp mode temp spg storm loopdetect sdsdump sds led crypto linkcheck`, plus mainline `dhcp wget tftpput fastboot netconsole i2c gpio button`.

## 3. Config options

Defaults: first value TPL/DMS `config.in`; "menu default" where the menuconfig prompt differs from the built `.config`.

| Option | Source:line | Default | Meaning | Stock / Ours |
|---|---|---|---|---|
| O01 `CONFIG_UART0` / `UART1` | TPL config.in:19-21 | UART0 | console UART | Y / Y (DT) |
| O02 `CONFIG_INTERRUPT_SUPPORT` | config.in:24 | n | CP0 IRQ handling | N / N (polled) |
| O03 `CONFIG_BOOT_SPI_NOR` / `SPI_NAND` | config.in:25-27 | NOR | boot media | NOR / NOR |
| O04 `CONFIG_CMDLINE_EDITING` | config.in:35 | y | history/edit | Y / Y |
| O05 `CONFIG_CMD_FLASH` | config.in:36; rtl9300.h:85 `#undef` | y | CFI flash cmds; undef'd, stubs remain | stubs / N |
| O06 `CONFIG_CMD_MEMORY` | config.in:37 | y | md/mm/mw/cp/cmp/loop/base/mtest | Y / Y (no mtest) |
| O07 `CONFIG_CMD_IMI` | config.in:38 | n (`.config` y) | `iminfo` | Y / Y |
| O08 `CONFIG_CMD_ENV` | config.in:39-43 | y if env in flash; `.config` unset | env save cmd | N / N |
| O09 `CONFIG_CMD_DUMPREGS` | config.in:44 | n | CP0 register dump | N / N |
| O10 `CONFIG_RTK_BOOT` + `TFTP_DOWNLOAD` / `SERIAL_DOWNLOAD` / `ICE_DOWNLOAD` / `STANDALONE_APP` | config.in:51-56 | y; y/n/n/n | "menu boot" download paths | TFTP / TFTP |
| O11 `CONFIG_CMD_NET` `PING` `NET_MULTI` | config.in:58-78 | y | TFTP, BOOTP, ping | Y / Y |
| O12 `CONFIG_ETHADDR` `IPADDR` `SERVERIP` | config.in:74-82 | 00:E0:4C:86:70:01 / 192.168.1.1 / 192.168.1.111 | build-in addresses | env / random MAC |
| O13 `CFG_PROMPT` | config.in:93 | `RTL9300 # ` | prompt (stock live `RTL9300#`) | Y / own |
| O14 `CONFIG_SYS_TEXT_BASE` | config.in:102 | 0x83F00000 | relocation | Y / 0x81000000 |
| O15 `CONFIG_BOOTDELAY` | config.in:104 | -1 (`.config` 3) | autoboot delay | 1 (env) / -1 + ESC |
| O16 `CONFIG_BOOTCOMMAND` | config.in:108 | `boota` (TPL) | boot cmd | boota / chain |
| O17 `CONFIG_BOARDVERSION` `BOARDMODEL` `BOOTARGS` `POSTWORD` | config.in:110-116 | empty | board strings; `POSTWORD` use unverified | boardmodel env / read-only verb |
| O18 `CONFIG_BAUDRATE` | config.in:118 | 115200 (TPL `.config` 38400) | console rate | 115200 / 115200..10.94 MBd |
| O19 `CONFIG_LZMA` | config.in:120 | n (`.config` y) | LZMA uImage | Y / Y |
| O20 `CONFIG_ENABLE_SPI_NAND_DRIVER` | config.in:125 | n | SPI-NAND stack (UBI, ECC, mtdparts) | N / N |
| O21 `CONFIG_RTK_USB_EHCI_HCD` | DMS config.in:127; rtl9300.h:182-189 | n | USB host + RTL8152 | N / N |
| O22 `CONFIG_SHELL_LOGIN_AUTH` | XGS config.in:122 | n | login prompt; no `.c` reference (grep) | N / N |
| O23 `CONFIG_SHA1` define | XGS config.in:128 | y | SHA1 lib | ? / Y |
| O24 `CONFIG_RTOS_TOOLCHAIN_USED` | config.in:137 | n | non-Linux toolchain | N / N |
| O25 `CONFIG_ENABLE_IH_MAGIC_NUMBER_CHK` + `IH_MAGIC_NUMBER` | config.in:138-139 | n; 0x93000000 | image magic (RTL9300 family ID) | N / N |
| O26 `CONFIG_ENV_CRC_ERROR_SAVE_DEFAULT_ENV` | config.in:140; DMS `.config`:198 | n (DMS y) | on bad env CRC write defaults to flash | N / N |
| O27 `CONFIG_CMD_SF` `NOR_SPIF_G3` `SPI_NOR_FLASH` `ECC_ENGINE_G2` | config.in:178-189 | y (NOR boot) | SDK NOR stack | Y / part |
| O28 `CONFIG_UBOOT_SDK_SUPPORT` | RTK-D config.in:144 | y | link SDK (`rtk network on`) | Y / own code |
| O29 `CONFIG_SDK_DRIVER_RTCORE` `NIC` `NIC_R9300` | RTK-D config.in:157-158,219 | y | rtcore + NIC | Y / own driver |
| O30 `CONFIG_SDK_DRIVER_GPIO` `SPI` `I2C` `I2C_R9300` | RTK-D config.in:175-177 | y (forced) | GPIO, SPI, I2C | Y / Y (DM) |
| O31 `CONFIG_SDK_DRIVER_WATCHDOG` `SDK_TC_DRV` | RTK-D config.in:169,180 | n in U-Boot | WDT / timer driver | N / N |
| O32 `CONFIG_SDK_UART1` | RTK-D config.in:192 | y | second UART in SDK | ? / N |
| O33 `CONFIG_SDK_BSP_FLASH` `FLASH_LAYOUT_TYPE5` `TURNKEY_SYSINFO` `DUAL_IMAGE` | RTK-D config.in:397-402 | y (forced) | partition table, SYSINFO, A/B | Y / part (bootsel) |
| O34 `CONFIG_SDK_SPI_DEV_*` | RTK-D config.in:460 | none | extra SPI device 1-5 | none / N |
| O35 `CONFIG_SDK_BSP_SPI_NOR_BOOT` / `NAND_BOOT` | RTK-D config.in:466 | NOR | boot medium | NOR / NOR |
| O36 `CONFIG_SDK_HW_PROFILE_PROBE_GPIO` / `UBOOT_ENV` | RTK-D config.in:504 | UBOOT-ENV | profile from `boardmodel` env | env / read verb |
| O37 `CONFIG_SDK_EXPERIMENTAL` `FPGA_PLATFORM` `EXPERIMENTAL_RTL8211FS` | RTK-D config.in:67-71,477-478 | n | experimental PHY, FPGA | N / N |
| O38 PHY selections `SDK_RTL8218D/E` `8224` (TPL), `8214C/QF` `8224` `8231` (DMS) | TPL `.config`:38,39,48; DMS `.config`:32-52 | per board | PHY drivers in loader | Y (code) / N |
| O39 `CONFIG_PRE_CONSOLE_BUFFER` (+`_ADDR` 0x80000000, `_SZ` 1 MiB) | TPL rtl9300.h:56-59 | on | buffer console before UART init | Y / N |
| O40 `CONFIG_SYS_BAUDRATE_TABLE` `UART_DIVISOR_MOD` | TPL rtl9300.h:53-54 | 9600..115200; -1 | baud table | Y / fixed |
| O41 `CONFIG_SYS_MEMTEST_START/END` | TPL rtl9300.h:64-65 | 0x80200000-0x80400000 | `mtest` range | Y / N |
| O42 `CONFIG_SYS_MAXARGS` `CBSIZE` `PBSIZE` | TPL rtl9300.h:103-105 | 16 / 512 | shell limits (UBOOT-REFERENCE) | Y / mainline |
| O43 `NORSF_MMIO_4B_EN` `XREAD_EN` `WBUF_LIM_B` `CFLASH_BASE` | TPL rtl9300.h:171-175 | 1 / 0 / 128 / 0x94000000 | NOR MMIO 4-byte, dual/quad read off, write buffer | Y / N (SPI ctrl) |
| O44 `SYSTEM_RESET()` | TPL rtl9300.h:164-168 | write 1 to 0xbb00000c | chip reset | Y / Y (cpu.c:36) |
| O45 `TIMER1_BASE` 0xb8003210, `TIMER_STEP_PER_US` 4 | TPL rtl9300.h:177-180 | LX-clock timer | udelay | Y / N (CP0 count) |
| O46 `CONFIG_SYS_MONITOR_LEN` `STACKSIZE` `MALLOC_LEN` `BOOTPARAMS_LEN` | TPL rtl9300.h:33-36 | 256K / 256K / 1M / 128K | memory map | Y / MALLOC 1M |
| O47 `STANDALONE_UBOOT` | PLR project/9300_nor_demo/info.in:6 | 1 | PLR copies U-Boot, no 2nd stage | Y / n/a |
| O48 `cg_info_proj` CPU/MEM/LX/SPIF MHz | PLR project/9300_nor_demo/parameters.c:50-57 | 800/600/175/25 | boot clocks | see CLOCKS.md / `clocks` |
| O49 `uart_baud_rate` | PLR project/9300_nor_demo/parameters.c:49 | 0 (PLR silent) | PLR UART; stock prints, so set elsewhere (unverified) | ? / n/a |
| O50 DRAM defines `_REDUCE_CALIBRATION_` `CONFIG_SOFTWARE_OVERWRITE_FREQ` `DRAM_AUTO_TIMING_SETTING` `DRAM_AUTO_SIZE_DETECTION` `USE_OTTO_CG_FUNCTION` `DRAM_AUTO_TYPES` `DDR3_USAGE` `DRAM_AUTO_PARAMETERS` | PLR template/9300_nor/ab_memcntlr_setup.c:11-26 | all on | auto DDR3 init | Y (STR `AK: Reduce DDR calibration`, `II: define USE_OTTO_CG_FUNCTION`) / N |
| O51 `DDR2_DRAM_ODT_VALUE` 75, `DDR3_DRAM_RTT_WR` 0, `RTT_NOM` 60, `PREFERED_DRAM_DRIV_STRENGTH` 0 (reduce), `SYS_PLL_CTRL` 0 | PLR template/9300_nor/ab_memcntlr_setup.c:23-30 | as listed | ODT / drive | values in stock unverified / N |
| O52 boot0412 ifdefs `TCAS_MAC_PHY` `ANALOG_DLL_DELAY_LINE` `DRAM_PUPD` `RAM_650` `DATA_BUF_MASK` `DRAM_BUS_WIDTH_8BIT` `DRAM_CHIP_NUM_TWO` `AUTOK_DEBUG` | PLR src/platform/9300/dram_gen4_9300/boot0412/memctl.c:788,815,981,1322,1561,1673,1883,1941 | which are defined: unverified | DRAM variants | ? / N |
| O53 PLL limits: CPU 400-800 step 25, LX/SPIF 133-204, SRAM 250-500, `MAX_SPIF_FREQ` 105 | PLR src/platform/9300/cg/cg.c:25-33,123-130 | fixed | clock ranges | Y / Y (`clocks`) |
| O54 PLR memory map: SRAM 64 KiB @0x9f000000, TLB 32 entries, LPLR 16 KiB @0x9fc00000, header +0x20 | PLR src/platform/9300/info.in:14-37 | fixed | preloader layout | Y / Y (SRAM, HARDWARE-INVENTORY:79) |

Notes:
- TPL `.config` is SG3218XP-M2 (`CONFIG_BOARDMODEL="RTL9302C_4xRTL8224_2XGE"`, baud 38400); ST1008F stock reads `RTL9303_8XGE` and 115200 ([UBOOT-REFERENCE.md](UBOOT-REFERENCE.md)). ST1008F stock option values are inferred from HELP/STR, not from a `.config`.
- O10: stock `bootm`/`boota` do not check an image magic; `upgrade loader` checks 0x93000000 ([UBOOT-REFERENCE.md](UBOOT-REFERENCE.md#image-checks-24)).
- O26: the SDK default is "do not repair"; stock behaviour on bad CRC is built-in default env without writing ([UBOOT-REFERENCE.md](UBOOT-REFERENCE.md#env-and-sysinfo-24)).
- O43: `XREAD_EN` 0 = single-line reads only; ours reads at 122.5 MHz FAST_READ 0Bh ([UBOOT-MAINLINE.md](UBOOT-MAINLINE.md#spi-nor-stage-3-read-only)).

## 4. Preloader init functions

`REG_INIT_FUNC(fn, lvl)` puts `{lvl, fn}` into `.init_func_level.<lvl>` (PLR `src/include/init_define.h:6`). `startup.S` runs CPU/cache/SRAM/BSS/stack setup (PLR `template/9300_nor/startup.S:76-95`), then `traversal_init_table()` calls the table in section order (`ab_lplr_c_entry.c`; `lib/misc/init_level.c` merges the 16 KiB LPLR table with the PLR table by level). Only `ab_*` files of the template plus the project dir are built (PLR `Makefile.in:64-71`).

Pre-table steps: `CPU_INIT`, `CACHE_INIT`, `SRAM_CTRL_INIT` (platform/9300/arch.h:16), `CSRAM_INIT` (copy SRAM code from flash), `BSS_INIT`, `STACK_GUARD_INIT` (0xcafecafe), `STACK_INIT` (startup.S).

| Lvl | Function (file:line) | Stock | What it does | Ours |
|---|---|---|---|---|
| P01 1 | `plr_init_utility` template/9300_nor/ab_util.c:79 | Y | UART init if `uart_baud_rate`, banner `PRELOADER.%u.%u.%u.%x.%x`, LX timer, bus-timeout monitors off (`OBTCR`, `LBPSTCR`, `LB0-2 M/S TCR`) | N (stays off, HARDWARE-INVENTORY:524) |
| P02 11 | `cg_copy_info_to_sram` platform/9300/cg/cg.c:334 | Y | copy `cg_info_proj` clock request into SRAM | n/a |
| P03 13 | `cg_init` platform/9300/cg/cg.c:335 (body :308) | Y | PLL setup CPU/SRAM/LX/SPIF/MEM; prints `II: CPU %dMHz, MEM %dMHz, LX %dMHz, SPIF %dMHz` | Y (`clocks`, CLOCKS.md) |
| P04 20 | `norsf_detect` soc/nor_spi_gen3/nor_spif_core.c:17 | Y | NOR SPI-F probe via vendor tables (winbond/mxic/gd/micron/spansion) | part (mainline spi-nor) |
| P05 30 | `dram_setup` template/9300_nor/ab_memcntlr_setup.c:53 | Y | `memctlc_init_dram` (boot0412/memctl.c:1847): PHY preset, DTR/MRS, ZQ, DLL reset, `DDR_Calibration` (memctl_cali_dram.c:851), size detect | N (retune only, DRAM.md) |
| P06 32 | `exit_preloader` template/9300_nor/ab_uboot.c:71 | Y | copy U-Boot to `uboot_vmabase`, `osc_init`, `chsp_jump` to `board_init_f` | n/a |
| P07 22 | `dss_test` platform/9300/misc/dss.c:87 | N (file not `ab_*`; STR no `ro_sel`) | die speed sensor, 2 wire x 5 ring-osc counts | N |
| P08 2 | `spi_nand_func_symbol_retrive` soc/nand_spi_gen1/nand_spi_symb_func.c:56 | N (NAND template) | NAND symbol table | n/a |
| P09 3 | `init_spi_nand` template/9300_nand/ab_init.c:50 | N | SPI-NAND init | n/a |
| P10 5 | `init_ecc_sw_patch` soc/ecc_gen1/ecc_sw_patch.c:88 | N | software BCH patch | n/a |
| P11 10 | `init_tlb` template/9300_nand/ab_init.c:90 | N | TLB + page table (NAND only) | n/a |
| P12 20 | `mc_info_probe` ... `mc_calibration` (22-28), `mc_result_decode` (29) soc/dram_gen4/memcntlr_setup.c:875-880 | N (9300 uses monolithic autok at 30) | generic table-driven DDR path | N |
| P13 33 | `ecc_controller_test` soc/rtk_mem_test/ecc_bch_test.c:298 | N | ECC engine self-test | n/a |
| P14 36 | `change_sp_to_dram` template/9300_nand/ab_stack_to_ddr.c:17 | N | stack to DDR (NAND) | n/a |
| P15 38 | `uboot_bring_up` lib/bringUboot/nor_spi_uboot_bringup.c:69 | N (non-standalone) | load U-Boot image from flash | n/a |

Notes:
- Order seen in STR: banner, `II: Disable Bus Timeout Monitor`, `II: CPU ... SPIF`, NOR detect, `AK: Start DDR_Calibration...`, `II: DRAM init start/done`, `DD: %08x <- %08x (%d B)...` = P01, P03, P04, P05, P06 (consistent with the table).
- LPLR table (16 KiB first stage at 0x9fc00000, `OTTO_LPLR_SIZE` info.in:32): contents not in the tree as source for 9300 NOR; unverified.
- P07: `dss_test` is the only PLR init function that is not built into the 9300 NOR template although its source sits in `platform/9300/misc/`.

## 5. Drivers and hardware blocks

| Block / feature | SDK source | Stock | Ours | Value |
|---|---|---|---|---|
| D01 NOR SPI-F + vendor probes (winbond :327, mxic :303, gd :359, micron :252, spansion :273) | PLR soc/nor_spi_gen3/; DMS arch/otto40/lib/nor_spi_gen3/ | Y | part (Winbond only) | none |
| D02 NOR MMIO 4B / dual-quad read (`xread`) | TPL rtl9300.h:171-175; STR `xread_en` | Y (off) | N | low |
| D03 SPIF clock divisor | PLR cg.c:88-109; ab_nor_spif_div_ctrl.c | Y | Y | covered |
| D04 SPI-NAND gen2/gen3 (24 vendors) + ECC engine | DMS arch/otto40/lib/spi_nand_gen3, ecc_gen2 | N | N | none |
| D05 PLL / clock generator (CPU, LX, SPIF, MEM, SRAM) | PLR cg.c:62-266, cg_mem.c:60-108 | Y | Y | covered |
| D06 DDR3 init + DQ/DQS auto-calibration | PLR boot0412/memctl.c:1847; memctl_cali_dram.c:566-851 | Y | N | high |
| D07 DRAM test library (word/half/byte, walking 0/1, addr-rot, memcpy, unaligned, cache-flush toggle, prefetch modes) | PLR soc/rtk_mem_test/memctl_dram.c:119-1265, mt_ram_test.c:28-648 | N | part | low |
| D08 Bus traffic generator (BTG) | PLR soc/rtk_mem_test/bus_traffic_generator.c:100-367 | N | N | medium |
| D09 GDMA (memcpy, checksum, memset, XOR, memcmp, byte swap, pattern) | old-gen `rtk_soc/test/gdma/`; no 9300 driver | N | N (kmod/gdma_test) | low |
| D10 Die speed sensor (DSS) | PLR platform/9300/misc/dss.c:41-87 | N | N | medium |
| D11 64 KiB SRAM mapping | PLR platform/9300/arch.h:16; startup.S | Y | Y | covered |
| D12 OCP/LX bus-timeout monitors (off at boot) | PLR ab_util.c (`RMOD_OBTCR` ...) | Y (off) | N | low |
| D13 UART (`otto_uart.c`), baud table | DMS arch/otto40/lib/otto_uart.c | Y | Y (ns16550) | covered |
| D14 Timers (LX timer, TC0-5) | DMS arch/otto40/lib/otto_time.c | Y | N (CP0 count) | none |
| D15 SoC watchdog | SDK driver off in U-Boot (RTK-D config.in:169,180); HW `WDT_CTRL` 0xb8003260 | N | N | medium |
| D16 Thermal meter | no U-Boot code (grep arch/otto40, rtl9300, system/uboot: 0) | N | Y (`rtk temp`) | covered |
| D17 eFuse / OTP | register header only (DMS board/Realtek/rtl9300/rtl9300.h) | N | part (probe script) | none |
| D18 Secure boot / image signature | none in SDK U-Boot; IH magic only (config.in:138); TP-Link DES decode TPL common/Makefile:178-179 | ? | N | none |
| D19 Image CRC (header + data, `verify` env) | common/image.c | Y | Y | covered |
| D20 Env in SPI flash (BDINFO, CRC32) | common/env_sf.c; rtl9300.h:126-135 | Y | N | low |
| D21 Dual image + SYSINFO | XGS cmd_bootm.c:1700-1782; RTK-D cmd_sysinfo.c | Y | part (bootsel) | covered |
| D22 Flash layout type 5 | DMS arch/otto40/lib/otto_flash_layout.c | Y | docs only | none |
| D23 NIC (`rtnic`) + TFTP/BOOTP/ping | RTK-D system/uboot/rtnic | Y | Y (own `rtl930x_eth.c`) | covered |
| D24 SDK init: rtcore, `rtk_init`, hw profile, SerDes construct, PHY poll off | RTK-D uboot_init.c:62-84; dal_longan_sds.c:4737-4788 | Y | Y (`rtk network on`) | covered |
| D25 SerDes eye / PRBS / loopback (`dal_longan_sds_*`) | RTK-D dal_longan_sds.c | code only (13 `dal_longan_*.o`) | Y (`rtk sds`) | covered |
| D26 PHY drivers 8218D/E, 8224, 8214, ext RTL8231 GPIO | RTK-D uboot_func.c; drv/rtl8231 | Y (code) | part (8231 verbs) | none |
| D27 LED test | RTK-D uboot_func.c:1824 | Y | Y | covered |
| D28 EEE enable/disable per PHY | RTK-D uboot_func.c:874-1204 | N | N | none |
| D29 Combo-port media | RTK-D uboot_func.c:566-740 | Y | Y | covered |
| D30 USB EHCI + RTL8152 | TPL drivers/usb/host/ehci-rtl9300.c | N | N | none |
| D31 Crypto engine (U-Boot use) | none in SDK U-Boot; old-gen `rtk_soc/test/crypto/cryptoTest.c` | N | Y (`rtk crypto`) | covered |
| D32 Hardware profiles (114) | RTK-D system/hwp | Y | Y (list) | covered |
| D33 `dal_longan_init` switch-core defaults (26 modules: FC thresholds, CPU max length, ...) | RTK-D dal_longan_mapper.c; SDK-FEATURE-MAP:148 | Y | part (NIC path only) | low |

Notes:
- D06: [DRAM.md](DRAM.md) leads 1-3 already plan the read/write DQ retrain from `DDR_Calibration_Full_Scan_Reduce` (memctl_cali_dram.c:566-847); this doc adds nothing there.
- D08: registers per [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md#gdma--bus-traffic-generator-62): BTG write block +0x100, read block +0x200 on LX1/LX2 read/write fine; `btg_para_v3_t` (bus_traffic_generator.h): LX id, read/write, burst 16-128 B, packet 32 B-8160 B, iterations, response/period time, address base/mask/gap, read-check mode (none / data gen / checksum). PLR only runs it from `btg_test()`/`btg_verification()` (not in the init table).
- D09: [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) has the measured 9300 behaviour (memcpy + checksum OK on LX1/LX2, LX0 unreliable).
- D10: dss.c registers `DSS0/1_CTRL` 0xB8000250/0xB800025C, `DSS0/1_DATA` 0xB8000260/0xB8000268, `DSS_DEBG` 0xB8000264/0xB800026C; sequence per (wire_sel 0-1) x (ro_sel 1-5): zero CTRL1 twice + DATA1, write CTRL (data_in 0xfff, en, rst_n), poll DATA1 bit 30 (bound 0x1000), read `count_out` [19:0]. These are not the `SPD_SENSOR0-8` words at 0xb8000618 that read 0 in [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md#speed-sensors-ring-osc-62); whether the two blocks are the same sensors: Q3. `scripts/dss_probe.py` (untracked) already runs the sequence from Linux.
- D15: HARDWARE-INVENTORY:284-289 (`WDT_CTRL` 0 = off in our U-Boot; OpenWrt `realtek_otto_wdt` 30 s).
- D16/D17: SDK has no U-Boot code for them; the register facts are in HARDWARE-INVENTORY.md (thermal :308, eFuse :316).
- D33: reset-time register defaults that Linux also depends on; unread values listed in [SDK-FEATURE-MAP.md](SDK-FEATURE-MAP.md#other-facts).

## 6. Not in stock but in SDK source

| Item | Why absent from the stock build | Rows | Port effort | Needs |
|---|---|---|---|---|
| Board test commands | menu symbols unset (menuconfig.in:4-11) | C01-C03, C08 | medium: 9300 bodies missing, rewrite from old-gen/838x | register-level GDMA/BTG (done in kmod) |
| Commented-out symbols | `#bool` lines (menuconfig.in:5,7,8,10) | C04, C06, C07 | n/a | n/a |
| Symbols never defined | no Kconfig entry (`CONFIG_CMD_BOOT_BIN`, `NEXT_FREQ`, `IDMEM_TEST`) | C05, C09, C10 | none | obsolete (838x era) |
| Unregistered functions | no `U_BOOT_CMD` | C12, C39 | low | wrapper only |
| Other-chip branches | `#if CONFIG_SDK_RTL8380/8390/9310` | C15-C17 | none | wrong chip |
| Product branch | `CONFIG_PRODUCT_XGS1250` | C23 | none | fan |
| XGS-only tree (Zyxel) | not in DMS/TPL | C19-C22, C26, O22 | low-medium | uses SDK APIs; re-implement on UP register code |
| PLR file outside template | not an `ab_*` file | P07, D07, D08 | low | SRAM or DRAM scratch |
| Generic commands not selected | defconfig | C32, C33, C36, C37 | trivial | Kconfig symbols |
| EEE, PHY, USB | no hardware on the board | C13, C38, D28, D30 | none | n/a |
| Watchdog in U-Boot | SDK disables | D15, O31 | low | mainline `REALTEK_OTTO_WDT` (HARDWARE-INVENTORY:289) |

## 7. Features other vendors enable

Searches 2026-11-07: `gh search code CONFIG_RTK_USB_EHCI_HCD` (only reyalo/Realtek and danieltwagner/teg-s750); `gh search code "CONFIG_CMD_HTTPD rtl9300"` and `gh search repos "realtek otto u-boot rtl838x"` returned nothing; web search + svanheule.net `sdk_uboot_init`; OpenWrt forum thread 134478. No OpenWrt-hosted Realtek U-Boot tree found.

| Tree | Source | Enables beyond the TP-Link build | Verified |
|---|---|---|---|
| Zyxel XGS1210 | XGS | `CONFIG_CMD_HTTPD` web recovery; `sys` HTP burn-in + loopback tests; `CONFIG_SHELL_LOGIN_AUTH` (dead); `CONFIG_SHA1` | config.in:83,122,128; uboot_cmd.c:1509-1595 |
| D-Link DMS-1250 | DMS | `CONFIG_ENV_CRC_ERROR_SAVE_DEFAULT_ENV=y`; PHYs 8214C/8214QF/8224/8231 + experimental 8211FS; `bootf` and Cameo/D-Link boot layer (`dlink_customer.h`, `mem=120M` bootargs); `CONFIG_BOOTDELAY` 3 | `.config`:32-62,178,198; cmd_bootm.c:1943 |
| TP-Link SG3218XP-M2 | TPL | DES image decode (`common/DesDecode.c`, `des*.c`), `md5_tp.c`, `flashApp*.c`, `dt_*` DRAM tests; `CONFIG_SDK_FEATURED_MINISDK`; 4.0.2 adds 9311B/9330 families | common/Makefile:178-187; `.config` |
| olliver `realtek_sdk` (Zyxel XGS1010/1210/1250, SDK 3.5.0) | OLV; forum post 2022-08-13 | removed dual-image/SYSINFO boot-check, 3 partitions (u-boot, env, firmware = 15 MiB); keeps the destructive self-test (command name unverified); same `menuconfig.in` as DMS | `diff` of config.in and menuconfig.in vs TPL: only the USB bool differs |
| TRENDnet TEG-S750 | `danieltwagner/teg-s750` `gpl_oss_of_realtek_sdk3/loader/u-boot-2011.12` | nothing extra seen: same `config.in` USB bool, `rtl9300.h` USB block (stripped tree) | gh code search hit list only |
| `jameywine/bismarck-preloader` | SDK-SOURCES.md | RTL9603C-vd DDR3 600-800 MHz rows, write leveling, DQS auto-K on the RTL9300 register map | [DRAM.md](DRAM.md) |
| Hasivo, XikeStor, Horaco, ONTi | - | no public loader source | SDK-SOURCES.md "Not found" |

- Features other vendors enable and TP-Link does not: HTTPD recovery (Zyxel), env auto-repair (D-Link), HTP self-test (Zyxel), USB host (compiled option in every tree, off in every `.config` seen).
- USB: `rtl9300.h` selects `USB_EHCI_RTL9300` + `USB_ETHER_RTL8152`; the ST1008F has no connector (HARDWARE-INVENTORY:239).

## 8. Top 10 candidates to add (ranked)

Test = smallest check on sw2 (never sw1). All run from our RAM U-Boot, no flash writes.

| # | Candidate (rows) | SDK source | Smallest test on sw2 | Value / effort |
|---|---|---|---|---|
| 1 | DDR read/write DQ retrain at the target MEM clock (D06) | PLR boot0412/memctl_cali_dram.c:566-847 | `clocks set mem 650`, retrain, `memtest low cached` vs the failing run | high / medium |
| 2 | Concurrent bus stress: GDMA memcpy/memcmp on LX1+LX2, BTG, CPU `memtest` (C03 D08 D09) | rtk_soc/test/concur/concur_test.c; bus_traffic_generator.c:100-367 | 5 s at stock clocks, 0 errors; repeat at the failing MEM clock | high / medium |
| 3 | `rtk dss`: die-speed-sensor sequence (D10 P07) | PLR platform/9300/misc/dss.c:41-87 | one pass (ws 0, ro_sel 1-5) at stock CPU, compare with `scripts/dss_probe.py` | medium / low |
| 4 | `loadb` / `loady` (serial binary load) (C32) | XGS common/cmd_load.c:1073-1082 | `loady` 1 MiB at current speed, `crc32` equals host | medium / trivial |
| 5 | TP-Link DRAM bus tests (data bus, address bus, fade, crosstalk, mtest) (C39 C33 C12) | TPL common/dt_bus.c:595,852; dt_verify.c:245,498; dt_mtest.c:433 | data+address bus walk on 1 MiB scratch at stock: pass; at failing clock: fail names the pin | medium / low-medium |
| 6 | SoC watchdog armed before `bootm` (D15) | HW `WDT_CTRL` 0xb8003260 (not SDK code) | arm 5 s, hang in a `loop`, board returns to U-Boot | medium / low |
| 7 | `rtk looptest`: internal/external loopback frame test (C21 C22) | RTK-X uboot_func.c:3805-3920 | cage 1 internal loopback, 10 frames TX = 10 RX, counters match | medium / medium |
| 8 | `hash` / `md5sum` / `sha1sum` (C36) | DMS common/cmd_sha1sum.c:49 | `hash sha1` of a TFTP'd file equals host `sha1sum` | low-medium / trivial |
| 9 | `httpd` failsafe upload (RAM only) (C26) | XGS net/net.c:2111-2457; httpd/ | `httpd` serves page; upload 1 MiB to RAM, `crc32` | low / medium |
| 10 | `rtk send` (C14) | RTK-D uboot_cmd.c:866 | `rtk send` with a host capture on cage 1 | low / low |

Details:
- 1: DRAM.md leads 1-3 (do not duplicate); measured read failure DQ4 late at 675 MHz is the target. Needs the SRAM routine + 8 KiB scratch (DRAM.md:154).
- 2: GDMA facts (burst field [7:6], checksum, LX0 unusable) are in HIDDEN-FEATURES.md; DMA only inside a reserved window; BTG read-check mode data-gen gives a hardware pattern check.
- 3: ring-osc counts relate to die speed for the overclock limit (#38); formula count-to-MHz unverified.
- 4: ours defconfig has `CMD_LOADXY_TIMEOUT=90` but no `CMD_LOADB` (build `.config`); in newer trees `loady` may be a separate symbol (unverified).
- 5: reachable only by writing a `U_BOOT_CMD` wrapper; no hardware dependency; license check first (Q5).
- 6: not an SDK feature (SDK keeps WDT off in U-Boot); listed because it closes the hang window between `bootm` and the Linux watchdog probe that the A/B trial counter (`bootsel`) cannot cover.
- 7: HTP uses `rtk_port_*` APIs; re-implement on our register code (`rtk_linkcheck.c`, `rtl930x_eth.c`).

## 9. Open questions

- Q1 Stock LPLR (first 16 KiB) init-table contents: not in any tree; `strings`/disassembly of the stock loader's first 16 KiB would answer. Affects whether a level-0 function (e.g. UART baud set, `uart_baud_rate` = 0 in parameters.c:49) exists before P01.
- Q2 TPL/DMS `parameters.c` sets MEM 600 / CPU 800 / LX 175; ST1008F stock boots with its own project values (UBOOT-REFERENCE: "preloader") - not compared against the SDK demo project; unverified.
- Q3 Are the DSS registers (0xB8000250-0xB800026C) the same sensors as `SPD_SENSOR0-8` (0xb8000618), which read 0 (held in reset)? `scripts/dss_probe.py` (untracked, not committed here) tests the 0x250 block.
- Q4 9300 `dram_test` / `flash_test` / `concur_test` / `gdma_driver` sources are missing from every public tree; behaviour on RTL9300 inferred from RTL838x/839x and old-gen code only.
- Q5 License of the TP-Link-authored `dt_*` files (copyright header, no GPL notice in the files read, `dt_mtest.c:1-6`): needs a decision before porting.
- Q6 HTP log region `0xb4ff0000` (uboot_func.c:62-64) vs ST1008F flash layout: confirm it lies inside firmware slot B before any HTP port.
- Q7 `docs/UBOOT-MAINLINE.md` lines 31 and 126 say `reset` is not implemented; `uboot-port/arch/mips/mach-otto/cpu.c:36-52` implements it (RST_GLB_CTRL write). Doc is stale.
- Q8 `CONFIG_POSTWORD` (config.in:116) and `CONFIG_SHELL_LOGIN_AUTH` (XGS config.in:122): no code reference found by grep; confirm they are inert.
- Q9 Which boot0412 ifdefs (O52) are defined in the ST1008F stock preloader: only `AK:`/`II:` strings (STR) are confirmed.
- Q10 Findings above are not yet filed as issues (task was read-only on repo state); the caller should file Q1-Q10 per the issue rule.
