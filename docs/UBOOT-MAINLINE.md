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
| Console | ns16550 DM, `0xb8002000`, `reg-io-width=1`, `reg-shift=2`, `clock-frequency=175000000` (LX), 115200 | matches Linux `ns16550a` node that works |
| UART byte lane | `reg-offset = <0xfffffffd>` | data is in bits 31:24 = byte 0; U-Boot's BE ns16550 accesses byte `(1<<shift)-1` = 3; -3 cancels it. `CONFIG_NS16550_DYNAMIC` would be cleaner but does not compile on mips (`inb(u8 *)`) |
| Timer | CP0 Count, `CONFIG_SYS_MIPS_TIMER_FREQ=400000000` (CPU/2) | assumption; check with `sleep 10` against a wall clock |
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

- Implemented: CP0 timer, ns16550 console, fixed 256 MiB RAM, env in RAM, `go`/`bootm`/memory commands, ERL cleared at entry; GPIO (`gpio-realtek-otto`), mode switch buttons; RTL9300 I2C master (8 SFP buses, `i2c-rtl9300`); i2c-gpio + TCA9534A lasers; `rtk` command.
- SPI-NOR read-only (stage 3, built, not hardware-verified; see [SPI-NOR](#spi-nor-stage-3-read-only)).
- Not: DDR/PLL, Ethernet, SerDes, flash env, reset (next: switch-core `+0x0c` write 1 = `syscon-reboot` per Linux DTS), interrupts (polled console only), second RAM bank (#32), second hardware thread.
- `bootm`: mainline accepts only standard uImage magic `0x27051956`; `scripts/mainline_uimage.py` writes the Realtek `0x93030000` that stock accepts. Needs a `--magic` option before using `bootm` here.

## SPI-NOR (stage 3, read-only)

- Driver: `uboot-port/drivers/spi/spi-realtek-rtl.c` = DM_SPI port of Linux `spi-realtek-rtl.c` (GPL-2.0, Bert Vermeulen). Node `spi0: spi@1200` (`realtek,rtl8380-spi`, regs SFCR `+0x0`, SFCSR `+0x8`, SFDR `+0xc` = `0xb8001200/08/0c`) + `jedec,spi-nor` child + 7 stock partitions (`read-only`).
- Flash: Winbond EF4019 = `w25q256` entry, 32 MiB, 1x I/O. Config: `DM_SPI`, `SPI_FLASH`, `SPI_FLASH_WINBOND`, `CMD_SF`, `SPI_FLASH_BAR`, MTD; `SPI_FLASH_UNLOCK_ALL` off; `ENV_IS_NOWHERE` kept.
- >16 MiB: `SPI_FLASH_BAR` (extended address register C5h/C8h) so the flash stays in 3-byte mode; U-Boot resets the register to 0 after each read. Chosen over B7h (4-byte mode) because a flash left in 4-byte mode would break 3-byte reads through the mmio window.
- Read-only guard is in the driver (CMD_SF has no Kconfig to drop writes): opcode allowlist RDID, RDSR/2/3, READ, FAST_READ, RDSFDP, RDEAR, WRDI. WREN is held back and only sent when WREAR follows. Program/erase/WRSR opcodes print `refused: no flash writes (opcode 0x..)` and return -EPERM, so `sf write|erase|update` fail without the flash seeing a WREN.
- mmio window: `claim_bus` sets SFCR RBO|WBO and deasserts CS; `release_bus` writes back the saved SFCR and SFCSR, so `crc32 0xb4000000 ...` works after `sf`. Whether stock needs a different mode is unverified.
- SPI clock: divider inherited from stock, never written (`set_speed` is a no-op).

| Interface | Rated max | Board allows | We run | Why the gap |
|---|---|---|---|---|
| SPI clock, FAST_READ 0Bh | 133 MHz (W25Q256JV rev G, 3.0-3.6 V, `sources/README.md`) | not measured | stock divider, value not yet decoded | divider field in SFCR unknown; `sf_read` check logs SFCR; reading it out is an open item (#32) |
| SPI clock, READ 03h | 50 MHz | not measured | not used (U-Boot picks 0Bh) | n/a |

- RDY wait limit 40 us per 32-bit word: assumes SPI clock >= 1 MHz (32 clocks = 32 us) x 1.25; expiry prints limit and elapsed.
- Checks: `sf_probe`, `sf_read` (first and last 64 KiB: `sf read` crc32 == mmio crc32; last 64 KiB exercises the >16 MiB bank), `refuse_sf_write|erase|update`. Run `./dev.py uboot-test sf_probe sf_read refuse_sf_write refuse_sf_erase refuse_sf_update`.
- Full-chip mmio: `crc32 0xb4000000 0x2000000` (compare with `stockFullFlashCrc32BeforeAcquisition` `dd984f95` in `docs/stock-flash-layout.json` if it is the same CRC algorithm; unverified).
- Build: +24 KB over the pre-SPI image (266434 -> 290614 bytes).

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
