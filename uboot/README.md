# awto u-boot — standalone RTL9303 bootloader

Clean-room bootloader for the TL-ST1008F (RTL9303, MIPS32r2 BE). **No stock code, no stock conventions as dependencies.** Goal: eventually replace stock SPL + U-Boot entirely (issue #23). Two products off one tree: a **dumb-switch** build (init ASIC, idle — no Linux) and a **managed** build (boot a kernel).

## Build

- `scripts/build_uboot.py` → `uboot/awto-uboot.{elf,bin}` (+ `tmp/tftp/`).
- Toolchain: clang (`--target=mips-linux-gnu -march=mips32r2 -EB`) + ld.lld + llvm-objcopy. No GCC cross-toolchain.

## Stages (roadmap)

1. **main (RAM harness)** — *done v0.0*: own CPU init (`start.S`), own UART init (`uart.c`), banner + echo CLI. Link `0x81000000`.
2. **clock/DDR SPL** — own reset vector `0xbfc00000`: PLLs (CPU `0xbb00e200`, mem `0xb8000234`), DDR3 (`0xb8001000`: PHY cfg, ZQ cal, MRS, per-DQ training), then jump to main. RE'd sequence in `tmp/re/board-bringup.md` / #23.
3. **SPI-NOR** — `0xb8001200` controller + `0xb4000000` read window; partition/env.
4. **SerDes/ASIC bring-up** — per-SDS `{page,reg,data}` (10GR), port enable, flood/forward defaults = dumb switch. Laser on: TCA9534A @0x38 via i2c-gpio (GPIO22/23).
5. **network + TFTP + boot** — for the managed build.

## Test harness (bring-up only — not a product dependency)

RAM-load + run during development:
```
tftpboot 0x81000000 awto-uboot.bin ; go 0x81000000
```
This runs the **main stage** assuming DRAM is up. The flash SPL (stage 2) removes that assumption — it does DDR itself from the reset vector. The RAM path is scaffolding, deleted once the SPL boots from flash.

## Hardware notes (from RE — our own register map, `soc.h`)

- UART0 `0xb8002000`: 32-bit regs, data in bits 31:24; THR `+0x00`, LSR `+0x14` (THRE `0x20000000`). Baud div = `lx_hz/(baud*16) - 1`, LCR `0x03`, FCR `0xc1`, MCR `0x43`. LX default 175 MHz (`SOC_LX_HZ` — confirm/own in the clock stage).
- GPIO `0xb8003300`: DIR `+0x08`, DAT `+0x0c`. GPIO21 = watchdog (keep high); 22/23 = i2c-gpio to the laser expander; 17/18/19 = 3-pos mode switch (boot selector, #23).
- 3-position switch + 8×3 LED matrix (HW LED engine `0xCC00`) → boot-mode selector + splash (#23).

## Hazards

- No flash writes until the SPL/flash path is proven on the bench with a recovery route (JTAG / full backup `private/`). RAM-only during bring-up.
