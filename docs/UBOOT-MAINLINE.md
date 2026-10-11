# Mainline U-Boot port (stage 0: RAM chainload)

Issue #23. Stock U-Boot 2011 (clocks + DDR already up) loads a mainline U-Boot and `go`es to it: on power-up from flash `jffs2-log` via the stock `bootcmd` ([DEFAULT-BOOT.md](DEFAULT-BOOT.md#power-up-chain), #47), or RAM-loaded over TFTP by `./dev.py ramload uboot-mainline`. No DDR init (stock SPL does it).
Runs on the board: first boot 2026-10-10 (18 s from power-off to prompt via `ramload`, log CLEAN); `uboot-test` 40/40 on 2026-10-11 (02d8c05).

## Layout

- Scaffold: `uboot-port/` (tracked) = `arch/mips/mach-otto/`, `arch/mips/dts/tplink_tl-st1008f.dts`, `board/tplink/tl-st1008f/`, `include/configs/tplink_tl-st1008f.h`, `configs/tplink_tl-st1008f_ram_defconfig`.
- Build: `scripts/build_uboot_mainline.py` stages the scaffold into a pinned tree, patches 11 hooks idempotently (`arch/mips/Kconfig` x2, `arch/mips/Makefile`, `arch/mips/dts/Makefile`, Kconfig + Makefile of `drivers/gpio`, `drivers/i2c`, `drivers/spi`, `include/image.h` Realtek magic), builds out-of-tree.
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

## On-board checks (`./dev.py uboot-test`)

| Check | Proves |
|---|---|
| timer | `sleep 5` = 5.013 s host (+0.3 %) → CP0 400 MHz (CPU/2) correct |
| bdinfo | 256 MiB at `0x80000000` |
| clocks | PLL decode: `cpu ... src pll` (SSR.ckse_ocp0 = PLL), `mem 600/650 MHz` |
| fdt_clocks | `fdt boardsetup` on a control-DTB copy: `/cpus frequency`, `/cpu-clock`, `/lx_clk` = live rates (#41) |
| div64 | `bench div64`: u64 `/` `%` through our `__udivdi3`/`__umoddi3` (#33) |
| i2c_scan | `i2c probe` scan on cage 1 lists 50 51; 0x50 still answers after a NACK; CTRL1 logged (#33) |
| sfp_phy | copper modules: `rtk sfp N phy` reads 88E1111 ID `0x0141`/`0x0cc?` (#33); none fitted = SKIP |
| cr_idle | explicit only (~100 s): bare CR after 1-30 s idle gets a prompt (#31) |
| gpio | all 24 lines from the driver == raw DATA `0xb800330c` |
| buttons | mode switch M1/M2/M3 via gpio-keys |
| sfp_a0 | first 96 A0 bytes via our I2C master == stock-loader dumps (cages 1, 2, 8) |
| ddm | live DDM: Vcc within 3.3 V ±5 %, temp 10-70 °C |
| laser | `rtk laser 2` → expander `0xfd` **and** cage 2 bias 1 mA → 6.3 mA; back to cage 1 |
| rtk_i2c / rtk_pin | stock output format (`data 0x..`) |
| refuse_* | module EEPROM write, GPIO21 low, all lasers on: refused |
| network | our `rtk network on` with no stock network-on: cage 1 PCS + MAC up (#51) |

Results 2026-10-11 (board, CPU 1 GHz where `clocks fast` ran):

- `clocks` PASS (`cpu ... src pll`); `fdt_clocks` PASS: `fdt: clocks cpu 1000000 kHz, lx 175000 kHz`, `/cpus`, `/cpu-clock`, `/lx_clk` all match (21:49+11:00, 0cd6993, #41).
- `cr_idle` PASS: bare CR after 1, 2, 5, 10, 13, 15, 20, 30 s idle got a prompt every time (21:49+11:00, #31). The single 2026-10-10 no-echo event did not reproduce. Host PL2303 `power/control` = `on` (no USB autosuspend).
- `div64` PASS (5f29530, #33).
- `i2c_scan` and `sfp_phy` PASS after 032c7c8 (#33); values under [I2C](#i2c-i2c-rtl9300-and-sfp-phy-33).
- `network` PASS (ab649f1, `--from-flash`, `rtk_media=stock`): cage 1 `pcs up, mac up 10G`; cages 2-8 10GBASE-R, no link (lasers off). Power-up chain with the same build PASS (#51).
- `timer` +0.3 % at 800 MHz; also used for the 775-1050 MHz overclock steps ([CLOCKS.md](CLOCKS.md)).
- `ft_board_setup` is not exercised by OpenWrt boots: OpenWrt uImages carry an appended DTB, `bootm` passes none, so no `fdt: clocks` line and flash OpenWrt prints `CPU frequency from device tree: 800MHz` even at 1 GHz. Linux side fixed by `300-05` (CPU rate from the PLL, #55); `fdt_clocks` tests the fixup on a control-DTB copy instead.

Full stock `rtk` parity inventory, registers and parity harness: [RTK-COMMANDS.md](RTK-COMMANDS.md).

## Console speed

- UART = LX 175 MHz / 16 / divisor; every divisor 47..1 (232 k .. 10.94 MBd) passes byte-exact on ours and stock (`./dev.py serial-speed`, #32). Rate table, conditions, host-adapter limits: [CLOCKS.md § UART rates](CLOCKS.md#uart-rates-2026-10-10-32).
- Ours ~9 % slower than stock in chars/s at the top rate: per-character LSR polling in the DM ns16550 path (candidate: fill the 16-byte TX FIFO per THRE).
- `./dev.py ramload uboot-mainline --fast [DIV]`: after boot, `setenv baudrate` to 10.9375 MBd/DIV (default 1) and find the host request (`tmp/serial-cal.json` first, then sweep). `uboot-test` 29/29 at 10.94 MBd.
- After `--fast` the board stays fast until power-off; `console-restart`, the daemon's autoboot catch and `uboot-test reset` assume 115200.
- `CFG_SYS_BAUDRATE_TABLE` lists the exact divisor rates so `setenv baudrate` accepts them.
- Long input lines lose characters (#31, 2026-10-10 at 115200): lines of ~220-250 chars drop one char (`eho PAD_PAD` for `echo PAD_PAD`). UART FIFO on (IIR `0xc1`, LCR `0x03`, IER `0x00`). Adapter TX vs SoC RX not separated.
  - A lost final CR looks like a hang: U-Boot waits for Enter; one bare CR runs the pending line.
  - A lost char can change an address: a ~560-char `crc32` line became `crc32 0x82b0000 0x1000` (KUSEG, TLB-mapped) → `crc32_no_comp` fault, `Cause d0000028` (ExcCode 0x0a), U-Boot halted.
  - Workaround: `Console.send_checked` types 16-char chunks, compares the echo, sends Enter only on an exact match, else Ctrl-C and retry (fired 2x in ~30 lines during the serial ladder). `Console.run` uses it for every line over 60 chars.

## `rtk` command (stock-compatible subset, `board/tplink/tl-st1008f/cmd_rtk.c`)

- `rtk i2c read|write <dev> <reg> [data]`: dev 0-7 = cage EEPROM `0x50` (read-only), 8 = laser expander `0x38`. `rtk i2c init …` accepted as a no-op.
- `rtk pinGet <pin>` (non-claiming read), `rtk pinSet <pin> <0|1> [force]` (GPIO21 low needs `force`).
- `rtk laser [status|<cage>|none|all force]`, `rtk boardmodel`.
- `rtk sfp`: all cages, summary only (presence, checksums, compact DDM line). `rtk sfp <cage>`: summary + `--- ethtool decode ---`. `rtk sfp <cage> brief`: summary only. `rtk sfp <cage> raw`: hexdump A0/A2 (128 B each).
- `rtk sfp power`: counted power per cage + total vs budget (warn only, #30). Rules: [hardware.md](hardware.md#sfp-power).
- `rtk sfp <cage> phy [reg]`: copper module PHY at 0x56; each 16-bit reg = two 1-byte reads of the same reg (MSB, then LSB), as Linux `mdio-i2c` SMBus. A 2-byte block read returns LSB `0xff` (master has no clock stretching). ID1 first: read as `0x4101` = byte order off by one → one extra byte read re-aligns. Each byte: up to 5 tries 1 ms apart.
- Decoder: `board/tplink/tl-st1008f/sfp/` = ethtool 7.1 (`6b7b16e`) `sfpid.c`, `sfpdiag.c`, `sff-common.c`, `module-common.c` (GPL-2.0); printf output, no JSON, integer fixed point (no FPU). Rx external-cal polynomial per SFF-8472 (upstream omits r^2..r^4). Host check: `scripts/sfp_decode_host_test.py`.
- `rtk network on`: ours (`rtk_net.c`), stock sequence + cage isolation ([RTK-COMMANDS.md](RTK-COMMANDS.md#stage-4-network-on-10g-macsds-port-isolation)); results below ([Stage 4](#stage-4-network-on-without-stock-51)).

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

- Implemented: clock provider + `clocks` command (decode; `set cpu`/`set mem` from SRAM) + `ft_board_setup` rate patching ([CLOCKS.md](CLOCKS.md)), CP0 timer, ns16550 console, fixed 256 MiB RAM (U-Boot itself), `highmem` window for the second 256 MiB, env in RAM, `go`/`bootm`/memory commands, ERL cleared at entry; GPIO (`gpio-realtek-otto`), mode switch buttons; RTL9300 I2C master (8 SFP buses, `i2c-rtl9300`); i2c-gpio + TCA9534A lasers; `rtk` command.
- SPI-NOR read-only (stage 3, verified on the board 2026-10-10; see [SPI-NOR](#spi-nor-stage-3-read-only)).
- Chained-boot selection primary / recovery (`bootsel`, attempt record in RAM, SoC watchdog): [DEFAULT-BOOT.md](DEFAULT-BOOT.md) (#73); not run on the board.
- SerDes bring-up + `rtk network on` without stock (#51, [Stage 4](#stage-4-network-on-without-stock-51)).
- Not: Ethernet (CPU-port NIC, #80), flash env, reset (next: switch-core `+0x0c` write 1 = `syscon-reboot` per Linux DTS), interrupts (polled console only), second RAM bank for Linux handover ([highmem](#ram-above-256-mib-highmem-32)), second hardware thread.
- `bootm`: accepts the standard uImage magic `0x27051956` and the Realtek `0x93030000` (stock-style images, flash OpenWrt), so `bootm 0xb4300000` boots the flash OpenWrt (#47).

## 64-bit divide (`__udivdi3`, #33)

- Mainline v2026.07 `arch/mips/lib/udivdi3.c` is `__udivdi3(long long u, word_type b)` with a 32-bit `b`; GCC passes a 64-bit divisor in a register pair. On big-endian o32 `b` = the divisor's high word = 0 for any 32-bit divisor → `__div64_32` divides by 0 → `divu` + `teq` → ExcCode 13. Upstream bug (BE MIPS32; LE truncates divisors ≥ 2^32), not build flags.
- Fix: `uboot-port/arch/mips/lib/udivdi3.c` replaces mainline's: `__udivdi3` + `__umoddi3`, both `u64`, shift-subtract, no `divu`.
- Host proof: `scripts/udivdi3_host_test.py` under qemu-mips-static (MIPS32r2 BE): 211 cases match Python; mainline's signature called with the libgcc ABI sees divisor 0 for 1000. Board: `uboot-test div64` PASS.

## I2C (`i2c-rtl9300`) and SFP PHY (#33)

- `i2c probe` scan: skips reserved addresses 0x00-0x07 and 0x78-0x7f (i2cdetect range). The scan still failed until the driver kept ≥ 10 SCL periods of bus idle before each TRIG (100 µs at 100 kHz, 200 µs at 50 kHz), timed from the last transfer's end. Back-to-back transfers (µs gap) failed; single commands (ms gap) worked. Linux's busy poll sleeps 26-100 µs, so it never hits this.
- CTRL1 FAIL bit: stays set (`0000000a`) after a NACK even when 0 is written: write-1-to-clear or read-only, not a plain bit. Driver writes FAIL = 0 with TRIG and after a NACK. Result 2026-10-11 (032c7c8): bus 0 lists 50 51.
- Block reads from MCU-emulated EEPROMs (GLC-T, GLC-SX) fail at 100 kHz (module clock-stretches; the master has none). `rtk sfp` retries a failed block read at 50 kHz after 20 ms, then byte-wise; logs `[50 kHz: module clock-stretches]` (cages 3, 4, 7 on many boots).
- Copper PHY (88E1111 at 0x56): Linux binds it as `smbus:sfp-p3:16` via `mdio-i2c` `smbus_byte_mii_read_default_c22` = two 1-byte reads of the same register (MSB, then LSB). A 2-byte read returns LSB `0xff` (same at 50 kHz). One run read reg 0 as `0x4001` (BMCR `0x0140` byte-swapped: pointer one byte out), hence the ID1 realign in `rtk sfp N phy`.
- Result 2026-10-11 (032c7c8), GLC-T cages 3 and 7: BMCR `0x0140`, BMSR `0x0149`, ID `0x0141`/`0x0cc2`, reg 0x11 `0x8100`/`0x8140`; one byte retry each, no realign needed.
- SDK alternate layout (`RTL9300_INT_I2C_*`, for `HWP_CHIP_REV < 3` + `IF_CHIP_TYPE_1`: MST1 SDA_OUT_SEL bit 5, shifted MEM_ADDR, read = RWOP 1) does not apply: ours uses the normal layout and reads cages 1-7, which the INT layout would fail. GLB_CTRL `0x384` SDA_SEL bit per channel is set as the SDK does (#51).

## Stage 4: `network on` without stock (#51)

Implementation: [RTK-COMMANDS.md](RTK-COMMANDS.md#stage-4-network-on-10g-macsds-port-isolation). Our U-Boot no longer depends on stock `rtk network on` (ab649f1, 2026-10-11T22:08+11:00).

- Before: from flash with no stock network-on, every SerDes read `off (0x1f)`.
- `rtk network on` from flash, no stock: 7.1 s; all 8 SerDes 10GBASE-R (`0x1a`).
- MAC link needed `SMI_MAC_TYPE_CTRL 0xca04` cleared for the SerDes ports (stock `_rtl9300_smiMacType_init`), plus CPU port force `0xca8c = 0x217`. Before that fix: cage 1 PCS up, MAC down.
- Construct list: stock `rtk sdsreg get 0 2 46 20` = `0x1311` → list `a` (production chip `0x93030001`), not `bT` (`0x1179`).
- Default media from the Linux SFP logic: GLC-T → SGMII (`0x02`); GLC-SX-MM, PTB3370553 → 1000BASE-X (`0x04`); SFP-10GSR-85 → 10GBASE-R (`0x1a`).
- Not run at autoboot (opt-in `rtk_boot_net`); the power-up chain with this build PASS (stock → ours → flash OpenWrt, STP on).
- Register diff, stock after `rtk network on` vs ours from flash without it (`./dev.py reg-diff`, 2026-10-11T21:34+11:00):
  - pinmux `0xbb0003a0`: stock `0035e000`, ours `00340000` (stock also sets `0x1e000`; bit 13 muxes GPIO3-5 to SPI = false presence on cages 4-6, cleared by ours, [hardware.md](hardware.md)).
  - I2C GLB `0x384`: stock `00a3ffff`, ours 0 until first use; MST1 CTRL1 stock `0x78`.
  - GPIO DIR `0x3308`: stock also drives GPIO22 as output (`00600000` vs `00200000`); DATA pins 8-16 read 0 under stock (muxed to I2C), 1 under ours.
  - LED `0xcc00`/`0xcc0c` differed until the stock LED profile was ported (#9: 0 LED diffs since 24430e8).
- Cage 8 I2C works without stock (`i2c dev 7; i2c md 0x50` = `03 04 07 …`, `SFP-10GSR-85`); the one earlier `empty` read was a seating/transient fault.
- MAC/SerDes diff before the `0xca04` fix (54 words): `0xca8c` 217 vs 194; `0xcb14` `0f110101` vs `0f000000`; `0xcb18/cb1c` bit 2 stock only; SerDes page 4 regs 1/8, page 5 reg 1 bit 15, page 7 regs 0x15-0x19 on sds 3/5/7/9, page 0 reg 0x1d on sds 2/4.

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
- #81 stock-area gate (same refusal path, extra line): program/erase whose start address is in 0x0-0xFFFFF (LOADER + both env sectors; our U-Boot never writes the env), plus chip erase, WRSR1/2/3 and block lock/unlock (`0x98 0x7e 0x39 0x36`), print a `refused (#81): ...` line first (`0x.. is in stock LOADER+env 0x0-0xfffff (opcode 0x..)`). Address decoded from the spi-mem opcode+address buffer (3 or 4 bytes). Stays if the opcode allowlist ever admits writes. Test: `refuse_sf_stock` (`sf erase 0xff000 0x1000`, env2: outside the host gate, so it reaches the driver).
- mmio window: `claim_bus` sets SFCR RBO|WBO and deasserts CS; `release_bus` restores SFCR/SFCSR. `crc32 0xb4000000 ...` after `sf` matches.
- SPI clock: driver never writes the divider (`set_speed` is a no-op); `clocks set`/`clocks` own it. SFCR `0x5fc00244` = SPI_CLK_DIV 2 → SCK = NOR 153.125 / 6 = 25.52 MHz ([CLOCKS.md](CLOCKS.md)).

| Interface | Rated max | Board allows | We run | Why the gap |
|---|---|---|---|---|
| SPI clock, FAST_READ 0Bh | 133 MHz (W25Q256JV rev G, 3.0-3.6 V, `sources/README.md`) | U-Boot reads bit-exact to 122.5 MHz; Linux to 102.1 MHz ([CLOCKS.md](CLOCKS.md) ladder) | 25.52 MHz under Linux (stock); `ramload uboot-mainline` default 122.5 MHz (SFCR /2, NOR code 3) when Linux will not run | Linux JFFS2 CRC errors at 102.1 MHz (#50) |
| SPI clock, READ 03h | 50 MHz | not measured | not used (U-Boot picks 0Bh) | n/a |

- Read throughput (2026-10-10, commit after dda6fff, 1x I/O, stock divider): mmio `crc32` of 32 MiB 16.6 s (~2.0 MB/s); `sf read` 32 MiB 22.6 s (~1.5 MB/s).
- RDY wait limit per 32-bit word = 32 SCK x 1.25 + 1 us from the clock provider, per claim (3 us at 25.52 MHz); expiry prints limit and elapsed.
- Checks: `sf_probe`, `sf_read` (first and last 64 KiB: `sf read` crc32 == mmio crc32), `refuse_sf_write|erase|update` (all pass on the board), `refuse_sf_stock` (#81, not yet run on the board).
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
7. DDR SPL from the RE'd preloader sequence (#23). Replacing the stock SPL/payload in flash is out: `0x0`-`0xDFFFF` is never written (#47, #81).

## Feature scope (#80, owner 2026-10-12)

- Network: CPU-port Ethernet driver (DM_ETH, polled) over our `rtk network on`; management through the CPU port with ports isolated (loop-safe).
- Firmware update without TFTP: web failsafe (HTTP upload → verify uImage/FIT header, size, CRC → write `firmware`/`recovery` only), `wget` (HTTP; HTTPS needs lwIP), fastboot over UDP.
- No SSH: no SSH server exists for U-Boot; netconsole + web failsafe on the isolated management port instead.
- Unmanaged-switch mode: after `network on` the ASIC forwards with an idle CPU; needs ASIC storm control + loop detection (no STP in U-Boot). Fallback when Linux will not boot.
- Router in U-Boot: not planned (ARP/neighbour/trap handling = a network stack in a bootloader; Linux does it).
- Everything must work as if stock never ran: our `rtk network on` reproduces stock's full switch init ([UBOOT-REFERENCE.md](UBOOT-REFERENCE.md#datapath-registers-and-hand-derived-pokes)); proof = whole switch-core `reg-diff` on a cold boot, stock vs ours, every difference copied or listed with a reason. Primary test path = cold power-up → stock chain-load → ours.

## Driver reuse audit (#83)

Owner 2026-10-12: U-Boot drivers reuse Linux/OpenWrt code where possible (one OS-independent core + thin platform glue, awto-unvr pattern). Audit 2026-10-12 (on branch `worktree-agent-a224c1e0dfdf94299`; hashes change on merge). Mainline U-Boot v2026.07 has no Realtek Otto driver of any kind.

- **Shared core (branch `worktree-agent-a224c1e0dfdf94299`, with #80's U-Boot Ethernet; not yet merged to main):** NIC `rtl930x_eth.c` ↔ OpenWrt `rtl838x_eth.c` + `300-11/12`: `shared/rtl930x-nic/rtl930x_nic.h` (registers, descriptor/tag, reset, HOL, reason map, ring base, max length, enable/stop, doorbell); Linux via `300-19` (main's `300-18` = irqchip affinity). Linux glue (page_pool, NAPI, DSA) cannot run in U-Boot.
- **Share a core (to do), in suggested order:**
  - SFP power `rtk_sfppower.c` ↔ `300-06` `st_power_mw()`: pure function on A0 bytes, same rules written twice (drift risk). Trivial.
  - Mode-switch decode (`board.c`) ↔ `300-06`: one-hot pin table written twice. Trivial.
  - SerDes access `rtk_sds.c` ↔ OpenWrt `mdio-realtek-otto-serdes.c`: indirect cmd/data and page/SerDes remap (sds 3 → 10) must agree. Small, high value.
  - Port isolation (`rtk_iso_guard`, `iso_set`) ↔ OpenWrt `otto_table.c` + DSA: table-access engine also needed for VLAN/L2 init (#80).
  - Watchdog (`bootsel.c`) ↔ Linux `realtek_otto_wdt.c`: prescale/phase math duplicated; U-Boot `wdt` uclass driver on a shared core.
  - Port LEDs `rtk_led.c` ↔ OpenWrt DSA LED setup + `300-16`: same register map. Medium.
  - I2C `i2c-rtl9300.c` (233 lines) ↔ Linux (670): Linux uses regmap `reg_field` tables per SoC, so a core needs a field-accessor shim. Ours is hardware-verified: follow-up.
  - CP0 timer rate (`mach-otto`) ↔ `300-05`: same PLL formula. Small.
  - Thermal (`rtk temp`) ↔ OpenWrt `realtek-thermal.c`: enable + 2 field reads. Low value.
- **Reuse as-is:** SPI-NOR, i2c-gpio, TCA9534A, ns16550 (mainline U-Boot, unchanged); SFP decode `sfp/` (verbatim ethtool `sfpid.c`/`sfpdiag.c`); cage presence pinmux (`rtk_presence_pins_gpio`) → candidate: U-Boot `pinctrl-single` with the Linux DT node @ `0x1b0003a0` (needs a size and on-board check).
- **Keep ours:**
  - GPIO `gpio-realtek-otto.c` (97 lines) vs Linux (470): 3 data registers; Linux file is gpio-regmap + irqchip glue. Upstream ours to U-Boot later.
  - SPI controller `spi-realtek-rtl.c` (326) vs Linux (394): the read-only/#81 guard is U-Boot-only and must not move.
  - Clock decode `mach-otto/clock.c`, `clocks.c`: Linux has no Otto clk driver (U-Boot patches rates into the DTB, #41).
  - SerDes/MAC construct (`rtk_net.c`, `rtk_sds_tables.h`): replays the stock loader; OpenWrt PCS uses another mode-set; converging needs an on-board A/B.
  - SFP interface pick `rtk_sfpmode.c`: Linux code is bound to linkmode bitmaps/phylink. Re-sync the quirk list on Linux changes.
  - `highmem.c` (U-Boot needs a wired TLB entry; only register values common), `rtk_sdstest.c`, crypto, DDR/clock SRAM code (no Linux counterpart), `bootsel.c`, `board.c`, `cmd_rtk.c`, `rtk_stock.c`, `rtk_ours.c`, `bench.c`, `cmd_busscan.c` (U-Boot commands / boot policy).
- **Upstream:** `arch/mips/lib/udivdi3.c` fix ([64-bit divide](#64-bit-divide-__udivdi3-33)).
- Shared-source rule (with that merge): edit only `shared/`; build scripts copy it into U-Boot, the 7.3 tree and OpenWrt `files-7.3`; Linux `static_assert`s catch drift.
