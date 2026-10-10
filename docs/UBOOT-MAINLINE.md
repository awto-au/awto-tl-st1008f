# Mainline U-Boot port (stage 0: RAM chainload)

Issue #23. Stock U-Boot 2011 (clocks + DDR already up) `tftpboot`s a mainline U-Boot and `go`es to it. No flash, no DDR init, no reset.
Not hardware-verified yet (built and inspected only).

## Layout

- Scaffold: `uboot-port/` (tracked) = `arch/mips/mach-otto/`, `arch/mips/dts/tplink_tl-st1008f.dts`, `board/tplink/tl-st1008f/`, `include/configs/tplink_tl-st1008f.h`, `configs/tplink_tl-st1008f_ram_defconfig`.
- Build: `scripts/build_uboot_mainline.py` stages the scaffold into a pinned tree, patches 4 hooks idempotently (`arch/mips/Kconfig` x2, `arch/mips/Makefile`, `arch/mips/dts/Makefile`), builds out-of-tree.
- Pinned tree: mainline tag `v2026.07` at `tmp/u-boot-v2026.07` (plain clone of the upstream mirror; `git clone -s -n <upstream clone> tmp/u-boot-v2026.07 && git -C tmp/u-boot-v2026.07 checkout --detach v2026.07`).
- Build dir `tmp/uboot-mainline-build`; outputs `tmp/tftp/uboot-mainline.{bin,elf}`; log `tmp/logs/build_uboot_mainline.log`.
- Toolchain: `mips64-linux-gnu-` GCC 16.2.1, `-march=mips32r2 -mabi=32`, big-endian ELF32 (clang fallback not needed).
- Build quirk: host OpenSSL has no `engine.h`; defconfig sets `# CONFIG_TOOLS_LIBCRYPTO` and `# CONFIG_TOOLS_KWBIMAGE` (host tools only; target unaffected).

## Choices

| Item | Value | Why |
|---|---|---|
| Machine model | new `ARCH_OTTO`, shaped like `mach-jz47xx` / `mach-ath79` | smallest MIPS machines (DM + OF_CONTROL, fixed timer freq, no SoC clock/reset framework); bmips/mtmips pull clk/reset/pinctrl stacks |
| CPU | MIPS32r2 BE, `-mtune=34kc` | RTL9303 34Kc |
| Link / load / entry | `0x81000000` (KSEG0, `CONFIG_TEXT_BASE`) | same spot the clean-room loader (`uboot/`) and stock `boota` run from; clear of stock U-Boot (relocated at `0x83f00000`), kernel load `0x80100000`, TFTP area `0x84f00000` |
| Init stack | `0x80f00000` top (`CFG_SYS_INIT_SP_OFFSET`) | below TEXT_BASE, above kernel load address |
| Relocation | U-Boot relocates itself to top of RAM (`0x8ff.....`) | stock is dead after `go`, its `0x83f00000` region is free |
| Low-level init | `CONFIG_SKIP_LOWLEVEL_INIT`: no cache reset/disable, no DDR, no PLL | stock already did it; resetting caches could discard dirty TFTP data |
| RAM | 256 MiB fixed (`dram_init`), no probing | second 256 MiB is not linearly mapped (needs OpenWrt highmem remap) |
| Console | ns16550 DM, `0xb8002000`, `reg-io-width=1`, `reg-shift=2`, `clocks = <&ccu 2>` (LX from the PLL registers), 115200 | matches Linux `ns16550a` node; rate never hard-coded ([CLOCKS.md](CLOCKS.md)) |
| UART byte lane | `reg-offset = <0xfffffffd>` | data is in bits 31:24 = byte 0; U-Boot's BE ns16550 accesses byte `(1<<shift)-1` = 3; -3 cancels it. `CONFIG_NS16550_DYNAMIC` would be cleaner but does not compile on mips (`inb(u8 *)`) |
| Timer | CP0 Count, board `get_tbclk()` = CPU PLL / 2, read each call | follows a runtime CPU change; `uboot-test timer` checks it against the host clock |
| Env | `CONFIG_ENV_IS_NOWHERE`, `BOOTDELAY=-1` (stay at prompt) | no flash |
| Commands | md mw cp cmp go bootm printenv setenv version echo itest sleep fdt dm help run | `saveenv`, `ELF`, flash and net commands disabled |
| `reset` | prints `reset: not implemented (stage 0)`, returns | GPIO21 low = board reset (stock `rtk.ko`), deliberately not driven; SoC chip-reset register not yet RE'd |
| Kernel decompress | `CONFIG_LZMA`, `SYS_BOOTM_LEN=0x1000000` | OpenWrt uImages are LZMA |
| DTB | `OF_SEPARATE`, appended to `u-boot.bin` | one flat file for `go` |

## Build, load, test

```
./dev.py build-uboot                 # -> tmp/tftp/uboot-mainline.bin
./dev.py ramload uboot-mainline      # power-cycle -> stock -> TFTP -> go 0x81000000 -> boot-log check
./dev.py uboot-test                  # on-board checks (scripts/uboot_mainline_test.py)
```

- `ramload` = stock `rtk network on`, one cage lit, `tftpboot 0x81000000 uboot-mainline.bin`, `go 0x81000000`. Entry = image start, no header.
- Status 2026-10-10 (stage 2): `uboot-test` 15/15 on the board; boot log CLEAN.

## On-board checks (`./dev.py uboot-test`)

| Check | Proves |
|---|---|
| timer | `sleep 5` = 5.013 s host (+0.3 %) → CP0 400 MHz (CPU/2) correct |
| bdinfo | 256 MiB at `0x80000000` |
| clocks | PLL decode shows `cpu 800 MHz`, `mem 600 MHz (DDR3-1200` (not yet run on the board) |
| gpio | all 24 lines from the driver == raw DATA `0xb800330c` |
| buttons | mode switch M1/M2/M3 via gpio-keys |
| sfp_a0 | first 96 A0 bytes via our I2C master == stock-loader dumps (cages 1, 2, 8) |
| ddm | live DDM: Vcc within 3.3 V ±5 %, temp 10-70 °C |
| laser | `rtk laser 2` → expander `0xfd` **and** cage 2 bias 1 mA → 6.3 mA; back to cage 1 |
| rtk_i2c / rtk_pin | stock output format (`data 0x..`) |
| refuse_* | module EEPROM write, GPIO21 low, all lasers on: refused |

Full stock `rtk` parity inventory, registers and parity harness: [RTK-COMMANDS.md](RTK-COMMANDS.md).

## Console speed

- UART = LX 175 MHz / 16 / divisor; every divisor 47..1 (232 k .. 10.94 MBd) passes byte-exact (`./dev.py serial-speed`). Results + host request table: #32.
- `./dev.py ramload uboot-mainline --fast [DIV]`: after boot, `setenv baudrate` to 10.9375 MBd/DIV (default 1) and find the host request (`tmp/serial-cal.json` first, then sweep). `uboot-test` 29/29 at 10.94 MBd.
- After `--fast` the board stays fast until power-off; `console-restart`, the daemon's autoboot catch and `uboot-test reset` assume 115200.
- `CFG_SYS_BAUDRATE_TABLE` lists the exact divisor rates so `setenv baudrate` accepts them.
- Long input lines lose characters (#31): scripts type through `Console.send_checked` (echo-verified, Enter last).

## `rtk` command (stock-compatible subset, `board/tplink/tl-st1008f/cmd_rtk.c`)

- `rtk i2c read|write <dev> <reg> [data]`: dev 0-7 = cage EEPROM `0x50` (read-only), 8 = laser expander `0x38`. `rtk i2c init …` accepted as a no-op.
- `rtk pinGet <pin>` (non-claiming read), `rtk pinSet <pin> <0|1> [force]` (GPIO21 low needs `force`).
- - `rtk laser [status|<cage>|none|all force]`, `rtk boardmodel`.
- `rtk sfp`: all cages, summary only (presence, checksums, compact DDM line). `rtk sfp <cage>`: summary + `--- ethtool decode ---`. `rtk sfp <cage> brief`: summary only. `rtk sfp <cage> raw`: hexdump A0/A2 (128 B each).
- Decoder: `board/tplink/tl-st1008f/sfp/` = ethtool 7.1 (`6b7b16e`) `sfpid.c`, `sfpdiag.c`, `sff-common.c`, `module-common.c` (GPL-2.0); printf output, no JSON, integer fixed point (no FPU). Rx external-cal polynomial per SFF-8472 (upstream omits r^2..r^4). Host check: `scripts/sfp_decode_host_test.py`.
- `rtk network on`: not yet (no Ethernet driver; stage 4).

## Expected console

```
U-Boot 2026.07-dirty (<build date>)

Model: TP-Link TL-ST1008F v2.0
DRAM:  256 MiB
Core:  <n> devices, <n> uclasses, devicetree: separate
In:    serial
Out:   serial
Err:   serial
st1008f-mainline # 
```

- Silence after `go`: suspect cache coherency (stale I-cache vs dirty D-cache), then the UART byte lane. Use `md.l 0xb8002014 1` (LSR, byte 0 = top byte of the word) from stock to compare.
- Garbled text: divisor. U-Boot computes 175e6/(16*115200) = 95 (Linux gets the same).
- Banner timing is the first thing to compare after load: `sleep 10` then wall clock checks the CP0 rate assumption.

## Implemented / not

- Implemented: clock provider + read-only `clocks` command + `ft_board_setup` rate patching ([CLOCKS.md](CLOCKS.md)), CP0 timer, ns16550 console, fixed 256 MiB RAM (U-Boot itself), `highmem` window for the second 256 MiB, env in RAM, `go`/`bootm`/memory commands, ERL cleared at entry; GPIO (`gpio-realtek-otto`), mode switch buttons; RTL9300 I2C master (8 SFP buses, `i2c-rtl9300`); i2c-gpio + TCA9534A lasers; `rtk` command.
- SPI-NOR read-only (stage 3, verified on the board 2026-10-10; see [SPI-NOR](#spi-nor-stage-3-read-only)).
- Not: DDR/PLL writes (procedures in [CLOCKS.md](CLOCKS.md)), Ethernet, SerDes, flash env, reset (next: switch-core `+0x0c` write 1 = `syscon-reboot` per Linux DTS), interrupts (polled console only), second RAM bank (#32), second hardware thread.
- `bootm`: mainline accepts only standard uImage magic `0x27051956`; `scripts/mainline_uimage.py` writes the Realtek `0x93030000` that stock accepts. Needs a `--magic` option before using `bootm` here.

## RAM above 256 MiB (`highmem`, #32)

- DRAM 512 MiB: DCR `0xb8001004` = `0x21421003` → bank+row+col bits = 29 (OpenWrt 300-02 `realtek_get_system_memory`).
- Bus zones (OpenWrt 300-02, GPL-2.0): zone 1 = bus 0x0-0x0fffffff → DRAM 0x0 (KSEG0/1, U-Boot's 256 MiB); zone 3 = bus 0x20000000-0x9fffffff, off at reset (`O0DOR2 0`, `O0DMAR2 0x1ffff`).
- `highmem map`: clear UMSAR0-3/SRAMSAR0-3 (stock: SRAM at bus 0x1f000000, `0x1f000001`), `O0DOR2 = 0x70000000`, `O0DMAR2 = 0x7fffffff` → bus 0x20000000 = DRAM 0x10000000. Then one wired TLB pair (256 MiB pages): VA `0xc0000000` → bus 0x20000000, uncached. Other 31 entries parked on unique KSEG0 VPNs first.
- `highmem test [bytes]`: alias check (16 MiB stride markers must not appear in the low bank) + address^pattern, 2 passes. Full bank 2026-10-10: 0 errors, 14.3 s (uncached, ~70 MB/s of traffic).
- Not yet: Linux handover. MIPS bootm passes one memory bank (`ram_base`/`ram_size`); the second bank needs `ft_board_setup` + `NR_DRAM_BANKS=2`, and a kernel with the zone-3 remap (OpenWrt has it; mainline 7.3 needs 300-02).

## SPI-NOR (stage 3, read-only)

- Driver: `uboot-port/drivers/spi/spi-realtek-rtl.c` = DM_SPI port of Linux `spi-realtek-rtl.c` (GPL-2.0, Bert Vermeulen). Node `spi0: spi@1200` (`realtek,rtl8380-spi`, regs SFCR `+0x0`, SFCSR `+0x8`, SFDR `+0xc` = `0xb8001200/08/0c`) + `jedec,spi-nor` child + 7 stock partitions (`read-only`).
- Flash: Winbond EF4019 = `w25q256` entry, 32 MiB, 1x I/O. Config: `DM_SPI`, `SPI_FLASH`, `SPI_FLASH_WINBOND`, `CMD_SF`, MTD; no `SPI_FLASH_BAR`; `SPI_FLASH_UNLOCK_ALL` off; `ENV_IS_NOWHERE` kept.
- Address mode: stock leaves the flash in **4-byte mode** (the mmio window spans 32 MiB on it). A 3-byte READ reads `(addr<<8)|0xff`: `sf read` at 0x100 returned flash 0x100ff. U-Boot therefore runs 4-byte (sends EN4B `0xB7`, harmless: already set).
- Read-only guard is in the driver (CMD_SF has no Kconfig to drop writes): opcode allowlist RDID, RDSR/2/3, READ/FAST_READ (3B and 4B `0x13`/`0x0c`), RDSFDP, RDEAR, WRDI, EN4B. EX4B `0xE9` refused (mmio needs 4-byte mode). WREN held back, only sent before WREAR. Program/erase/WRSR print `refused: no flash writes (opcode 0x..)`, return -EPERM; the flash never sees a WREN for them.
- mmio window: `claim_bus` sets SFCR RBO|WBO and deasserts CS; `release_bus` restores SFCR/SFCSR. `crc32 0xb4000000 ...` after `sf` matches.
- SPI clock: divider inherited from stock, never written (`set_speed` is a no-op). SFCR read `0x5fc00244` (field decode: #35).

| Interface | Rated max | Board allows | We run | Why the gap |
|---|---|---|---|---|
| SPI clock, FAST_READ 0Bh | 133 MHz (W25Q256JV rev G, 3.0-3.6 V, `sources/README.md`) | not measured | stock divider (SFCR `0x5fc00244`, not decoded) | divider field unknown (#35) |
| SPI clock, READ 03h | 50 MHz | not measured | not used (U-Boot picks 0Bh) | n/a |

- Read throughput (2026-10-10, commit after dda6fff, 1x I/O, stock divider): mmio `crc32` of 32 MiB 16.6 s (~2.0 MB/s); `sf read` 32 MiB 22.6 s (~1.5 MB/s).
- RDY wait limit 40 us per 32-bit word: assumes SPI clock >= 1 MHz (32 clocks = 32 us) x 1.25; expiry prints limit and elapsed.
- Checks: `sf_probe`, `sf_read` (first and last 64 KiB: `sf read` crc32 == mmio crc32), `refuse_sf_write|erase|update`. All pass on the board.
- Full chip 2026-10-10: `sf read` and mmio both CRC32 `671232ac`. Differs from the 2026-10-08 backup (`dd984f95`): `firmware` now holds OpenWrt 25.12.4 (sysupgrade 2026-10-08) and env `ethaddr` changed (#36).

## Sources for later stages (GPL-2.0, attribute on port)

| Stage | Driver | Take from |
|---|---|---|
| GPIO | gpio-realtek-otto | OpenWrt `target/linux/realtek` (clone `tmp/openwrt`), Linux mainline |
| SPI-NOR | rtl838x SPI controller | OpenWrt `realtek` patches / `drivers/spi/spi-realtek-rtl.c` |
| I2C + SFP DDM | `i2c-rtl9300` (SCL/SDA mux, 8 channels) | OpenWrt `realtek` files, Linux mainline |
| Ethernet / L2 / SerDes | RTL930x switch core, CPU port DMA, SerDes tables | olliver's `realtek_sdk` (GitLab, branch `tplink_maple`), D-Link DMS-1250 GPL tree, OpenWrt `rtl838x` ethernet + `rtl930x` PCS |
| DDR / PLL | RE'd preloader sequence | issue #23 (regs `0xb8001000..`, `0xb8000234..`, `0xbb00e200..`) |

Stage 0 uses none of them.

## Next stages

1. ~~GPIO~~ done. ~~I2C + lasers + SFP DDM~~ done.
2. `reset` via switch-core `0xbb00000c` = 1 (Linux `syscon-reboot`); 512 MiB (#32).
3. ~~SPI-NOR read-only~~ built (below); `saveenv` stays out.
4. RTL930x CPU-port Ethernet + SerDes 10GBASE-R; DM_ETH; `rtk network on`.
5. lwIP + iperf (lwiperf) for wire-speed tests.
6. `hwtest` commands in the style of awto-unvr `docs/uboot-hw-test-suite.md`.
7. DDR SPL from the RE'd preloader sequence (#23); then flash boot replacing stock SPL + payload.
