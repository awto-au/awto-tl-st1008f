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

## Load (from stock U-Boot at `RTL9300#`)

```
rtk network on
rtk i2c write 8 1 0xfe          # cage 1 laser only (cage loop hazard)
rtk i2c write 8 3 0
setenv ipaddr <switch-ip>; setenv serverip <tftp-server-ip>
tftpboot 0x81000000 uboot-mainline.bin
go 0x81000000
```

- TFTP root: `tmp/tftp/` (`scripts/tftpd.py`). Same recipe as README; only the file name and address differ.
- Image size varies per build (about 190 KB, checked at each load by the `tftpboot` "Bytes transferred" line).
- Entry = start of image (`_start: b reset`), no header, no uImage wrapper. `go` passes no meaningful arguments.

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

- Implemented: CP0 timer, ns16550 console, fixed 256 MiB RAM, env in RAM, `go`/`bootm`/memory commands, ERL cleared at entry.
- Not: DDR/PLL, SPI-NOR, GPIO, I2C, Ethernet, SerDes, flash env, reset, interrupts (polled console only), second RAM bank, second hardware thread.
- `bootm`: mainline accepts only standard uImage magic `0x27051956`; `scripts/mainline_uimage.py` writes the Realtek `0x93030000` that stock accepts. Needs a `--magic` option before using `bootm` here.

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

1. GPIO: `gpio0` `0xb8003300`; mode switch M1/M2/M3 = 17/18/19 (active-low); GPIO21 held high, never toggled.
2. SPI-NOR: SFCR `0xb8001200`, read window `0xb4000000`; read-only first; `saveenv` stays out.
3. I2C (8 channels, SCL GPIO8, SDA GPIO9-16) + TCA9534A `0x38` lasers + SFP DDM (`i2c`/`sfp` commands).
4. RTL930x CPU-port Ethernet + SerDes 10GBASE-R; DM_ETH.
5. lwIP + iperf (lwiperf) for wire-speed tests.
6. `hwtest` commands in the style of awto-unvr `docs/uboot-hw-test-suite.md`.
7. DDR SPL from the RE'd preloader sequence (#23); then flash boot replacing stock SPL + payload.
