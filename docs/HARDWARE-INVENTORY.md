# RTL9303 hardware inventory (TL-ST1008F v2)

Every SoC block: on the chip, wired on this board, used by stock U-Boot / stock Linux / OpenWrt / ours, value if enabled. Issue #62. Presence probe: `./dev.py hw-probe` ([scripts/README.md](../scripts/README.md#hw_probepy)).

Source tags:
- **[DS §]** `sources/rtl9303-cg-brief.pdf` Rev 1.1-1 (block diagram = Fig. 1).
- **[SOC]** Realtek GPL SDK `rtl9300_soc_reg.h`; **[SW]** `swcore_rtl9300.h` (github.com/reyalo/Realtek `sources/rtk-xgs1210/system/include/...`). Otto superset: lists blocks the RTL9303 package has no balls for.
- **[OWRT]** OpenWrt `target/linux/realtek` (`rtl930x.dtsi`, `rtl9303_tplink_tl-st1008f-v2.dts`, `rtl930x/config-6.18`, 25.12.4 boot log `artifacts/`). **[ML]** `mainline/` DTS + config, Linux 7.3 `rtl930x.dtsi`.
- **[BIN]** stock loader / `rtcore.ko` / `rtk.ko` decompiles (local only). **[LOG]** stock boot log `artifacts/stock-boot-20261008.log`.
- **[LIVE]** read on this unit (console log, dated in the cited doc). **[DOC]** repo doc named in the field.
- **SPEC** = inferred, not verified on hardware or in vendor code.

Per block: RTL9303, Board, Stock U-Boot, Stock Linux, OpenWrt, Ours (U-Boot / mainline), Value if enabled; a field that is not applicable is omitted. Abbreviations: Y = yes, N = no, `-` = not applicable. Addresses are KSEG1 (`0xb8..` SoC, `0xbb..` switch core).

## CPU

### MIPS 34Kc core
- RTL9303: Y, PRId `0x00019555` [LIVE], "up to 800 MHz" [DS §8.1]
- Stock U-Boot: Y, 800 MHz
- Stock Linux: Y
- OpenWrt: Y, 800 MHz
- Ours (U-Boot / mainline): Y; U-Boot runs 1 GHz chained ([CLOCKS.md](CLOCKS.md)) / Y

### MT ASE, VPEs
- RTL9303: Y: Config3 `0x00002424` bit 2 MT [LIVE]; 2 VPEs (Linux "Brought up 2 CPUs" [OWRT log]). TC count: MVPConf0 not read, SPEC
- Stock U-Boot: VPE0 only
- Stock Linux: SPEC (boot log shows no SMP lines)
- OpenWrt: `MIPS_MT_SMP`, `NR_CPUS=2`
- Ours (U-Boot / mainline): VPE0 only / `MIPS_MT_SMP`, `NR_CPUS=2` (`mainline/st1008f-v2.config`; `--up` build: one VPE) (#27)
- Value if enabled: used

### FPU
- RTL9303: **N**: Config1 `0xbea3519e` bit 0 FP = 0 [LIVE]
- Stock Linux: emulation
- OpenWrt: emulation
- Ours (U-Boot / mainline): integer only / emulation

### DSP ASE
- RTL9303: Y **rev 1 only**: Config3 bit 10 DSPP = 1, bit 11 DSP2P = 0 [LIVE] (#27 said r2)
- Stock U-Boot: N
- Stock Linux: kernel saves DSP context
- OpenWrt: userspace `CPU_TYPE:=24kc`, no `-mdsp` (#27)
- Ours (U-Boot / mainline): N
- Value if enabled: low: codec/DSP loops; none for forwarding

### Other CPU options
- RTL9303: MIPS16e (Config1 CA), perf counters (PC), watch regs (WR), EJTAG (EP), UserLocal (Config3 ULRI), vectored ints (VInt; no VEIC), no SmartMIPS; no ISPRAM/DSPRAM scratchpad (Config `0x80248483` ISP = DSP = 0) [LIVE]
- OpenWrt: perf counters (`MIPS_PERF_SHARED_TC_COUNTERS`)
- Value if enabled: low

### MMU
- RTL9303: 32-entry JTLB, 4 ITLB, 4 DTLB [DS §8.1]; Config1 MMU size 32 [LIVE]
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: Y
- Ours (U-Boot / mainline): wired TLB pair for `highmem` / Y

### L1 caches
- RTL9303: 32 KiB I + 32 KiB D, 4-way, 32 B lines [DS §8.1, LIVE Config1]; D-cache PIPT, no aliases [OWRT log]
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: Y
- Ours (U-Boot / mainline): Y

### L2 cache
- RTL9303: **N**: Config2 `0x80000000` [LIVE]
- OpenWrt: selects `MIPS_CPU_SCACHE`, finds none (no "secondary cache" line)
- Ours (U-Boot / mainline): not selected (correct)

### CP0 Count timer
- RTL9303: Y, CPU / 2 [LIVE [CLOCKS.md](CLOCKS.md)]
- Stock U-Boot: SPEC
- Stock Linux: SPEC
- OpenWrt: Y (hpt; rate from DT, our patch 300-05 reads the PLL); clocksource = otto timer
- Ours (U-Boot / mainline): U-Boot timer / Y, rate wrong without DT `frequency` (#55)

## Memory and buses

### 64 KiB SRAM
- RTL9303: Y [DS §1 "64Kbyte SP-SRAM"]; seg regs `CPU_SRAM_SEG0-3_ADDR` `0xb8004000` [SOC]
- Stock U-Boot: SPL runs from it at `0x9f000000`; window bus `0x1f000000` (`0x1f000001`) left mapped [LIVE [UBOOT-MAINLINE.md](UBOOT-MAINLINE.md)]
- Stock Linux: N SPEC
- OpenWrt: N (930x clk driver off)
- Ours (U-Boot / mainline): clock/DDR routines run from it ([CLOCKS.md](CLOCKS.md)); `highmem map` unmaps it / Y: `300-21` re-maps it, DT `sram@1f000000` mmio-sram pool, bench `300-22` (#103)
- Mapping (SDK PLR `SRAM_CTRL_INIT`, `platform/9300/arch.h`): `UMSAR0` = `0x1f000001` + `UMSSR0` = 9 (DRAM decode off there), `CPU_SRAM_SEG0_ADDR` = `0x1f000001`, `_SIZE` = 9 (64 KiB), `_BASE` = `0x00030000` (bits 17:16; SDK field map says 15:8). CPU view: KSEG0 `0x9f000000`, KSEG1 `0xbf000000`.
- Survives both U-Boots (ours writes seg 0 only inside `clocks set`, restored after; `highmem map` is not in the boot chain). OpenWrt `300-02` `rtl930x_prepare_highmem` zeroes `UMSAR0-3` + `SRAMSAR0-3` on every HIGHMEM kernel with > 256 MiB, so Linux had no SRAM before `300-21`.
- The window shadows **DRAM** `0x1f000000`-`0x1f00ffff` too: after the zone-3 remap that DRAM is Linux phys `0x2f000000`-`0x2f00ffff`, and a CPU access there hangs (U-Boot `./dev.py sram-alias-probe`, 2026-10-13; the neighbouring words are plain DRAM). The unmap segment matches the DRAM-side address, not the bus address. DTS reserves the 64 KiB `no-map` (`sram-shadow@2f000000`); without it a tmpfs fill hung the kernel (#107).
- Value if enabled: medium: hot data with ~110 ns DDR miss latency; NIC DMA reach unknown (field name `lx_sa` hints an LX-side decode; no SDK code puts a NIC ring there)

### DSP SRAM seg regs
- RTL9303: regs `DSP_SRAM_SEG0-3_ADDR` at `0xb8004040` [SOC]; no DSP core in Fig. 1: N SPEC
- Value if enabled: none

### Mask ROM
- RTL9303: `ROMSAR` `0xb8004080` [SOC]; strap `BOOT_SEL` 1 = ROM boot [DS §6.12]: Y SPEC
- Board: boots NOR
- Value if enabled: none

### DDR3 controller
- RTL9303: Y, 8/16-bit, 1 GiB max [DS §8.3]; `MCR` `0xb8001000` [SOC]
- Board: one x16 4 Gbit die, 512 MiB, 600 MHz [DOC [DRAM.md](DRAM.md)]
- Stock U-Boot: Y (SPL init)
- Stock Linux: Y
- OpenWrt: Y
- Ours (U-Boot / mainline): DDR clock/timing tools ([CLOCKS.md](CLOCKS.md)) / Y
- Value if enabled: DRAM prefetch (MCR `ip_ref`/`dp_ref`) off in stock: +26-61 % (#52, #53)

### Bus zones / unmapped segments
- RTL9303: `UMSAR0-3` `0xb8001300`, OCP `DOR0-2`/`DMAR0-2` `0xb8004200` [SOC]
- Board: 2nd 256 MiB needs zone 3
- Stock U-Boot: N
- Stock Linux: SPEC
- OpenWrt: Y (`300-02` highmem remap)
- Ours (U-Boot / mainline): `highmem map` / N (#27)
- Value if enabled: 2nd 256 MiB in mainline (#27)

### OCP / LX bus timeout monitors
- RTL9303: `TO_CTRL` `0xb8005100`, `LB*TCR` `0xb8005200..` ; GIMR `OCPTO`/`LXMTO`/`LXSTO` [SOC]; present, enable bit 31 off [LIVE, [Measured](#measured-2026-10-11-hw-probe)]
- Stock U-Boot: SPEC
- Stock Linux: SPEC
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: low-medium: a hung bus access becomes an IRQ with the address

### Speed sensors (ring osc)
- RTL9303: `SPD_SENSOR0-8` `0xb8000618` [SOC]
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: low: die speed for overclock limits (#38)

### IP enable registers
- RTL9303: `IP_EN_CTRL` `0xb8000600`, `NEW_IP_EN_CTRL` `0xb800063c` [SOC]
- Ours (U-Boot / mainline): read by `hw-probe`

## Flash and serial interfaces

### SPI-NOR controller
- RTL9303: Y: 2 CS, 1/2/4-bit, PIO + mmio read window, cached reads [DS §8.2]; `SFCR` `0xb8001200`, window `0xb4000000` [SOC, LIVE]
- Board: one Winbond W25Q256JV (32 MiB) on CS0; IO2/IO3 routing unknown (#61)
- Stock U-Boot: Y: SFCR2 `0xbbc14a00` = Fast Read **Dual I/O** mmio [LIVE #61]
- Stock Linux: Y: `RTK_NORSFG3`, `MMIO32-2/ModeC` [LOG]
- OpenWrt: PIO, 1-bit, no dirmap (#61)
- Ours (U-Boot / mainline): PIO 1-bit + mmio window (stock mode) / PIO 1-bit
- Value if enabled: **high**: dual/quad dirmap in Linux (#61)

### SPI-NAND controller + ECC
- RTL9303: Y [DS §2 "512MB SPI NAND"]; `SNFCFR` `0xb801a400`, ECC `ECCFR` `0xb801a600` [SOC]; OpenWrt nodes `status = "disabled"`
- Board: no NAND
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: N (`rtl930x_nand` subtarget is for other boards)
- Ours (U-Boot / mainline): N
- Value if enabled: none

### SPI master (2 sets)
- RTL9303: Y [DS §2 "2-set SPI master"]: flash controller (CS0/CS1 balls E2/E1) + switch-core SPI master `SPI_CTRL1` `0xbb0003a0` [SW]
- Board: CS1 and switch-core SPI: nothing attached SPEC
- Stock U-Boot: `spi_master_*`, `spi_dev3_init` present [BIN]
- Stock Linux: "SPI none dev init" [LOG]
- OpenWrt: `0x3a0` only as pinmux (GPIO 3-7)
- Ours (U-Boot / mainline): N
- Value if enabled: none

### SPI slave
- RTL9303: Y [DS §6.9], balls A1-A3/B3; strap `REG_IF_SEL` [DS §6.12] (external-CPU register access)
- Board: no external CPU
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: pinmux frees its GPIOs
- Ours (U-Boot / mainline): N
- Value if enabled: none

### UART0
- RTL9303: Y [DS §6.2], `UART0_PBR_THR_DLL` `0xb8002000` [SOC]
- Board: header J14 `DH GND RX TX`
- Stock U-Boot: console
- Stock Linux: console
- OpenWrt: console
- Ours (U-Boot / mainline): console, up to 10.94 MBd ([UBOOT-MAINLINE.md](UBOOT-MAINLINE.md)) / console

### UART1
- RTL9303: Y [DS §6.2], `UART1_PBR_THR_DLL` `0xb8002100` [SOC]; balls shared with EJTAG (RXD A4 = TDI, RTS B4 = TMS, CTS C5 = TCK, TXD D5 = TDO)
- Board: only via the 5-pad JTAG footprint SPEC
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: node `disabled`, pinmux `JTAG_SEL_CTRL` `0xbb000204`
- Ours (U-Boot / mainline): N
- Value if enabled: low-medium: second console while UART0 is busy

### EJTAG
- RTL9303: Y [DS §6.3], Config1 EP [LIVE]
- Board: 5-pad footprint, board bottom [DOC [hardware.md](hardware.md)]
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: medium: recovery path if flash boot breaks (needs a probe adapter)

### I2C master MST1
- RTL9303: Y, `I2C_MST1_CTRL1` `0xbb00036c` [SW]; SCL0 GPIO8, SDA0-7 GPIO9-16 [DOC hardware.md]
- Board: 8 SFP cages (EEPROM `0x50`, DDM `0x51`)
- Stock U-Boot: `rtk i2c` dev 0-7
- Stock Linux: Y
- OpenWrt: `i2c_mst1`
- Ours (U-Boot / mainline): `i2c-rtl9300` / Y
- Value if enabled: used

### I2C master MST2
- RTL9303: Y, `I2C_MST2_CTRL1` `0xbb000388` [SW]
- Board: SCL1 = GPIO17 per SDK pin formula = mode switch: unusable here SPEC
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: none

### "8-set I2C master"
- RTL9303: [DS §2]: 8 SDA channels per master SPEC

### GPIO 0-23
- RTL9303: Y [DS §6.4], `PABCD_DIR` `0xb8003308`, `PABCD_DAT` `0xb800330c` [SOC]
- Board: 0-7 MOD-DEF0, 8 SCL0, 9-16 SDA0-7, 17-19 mode switch, 20 unknown, 21 ext watchdog / board reset, 22/23 i2c-gpio to TCA9534A [DOC hardware.md]
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: Y
- Ours (U-Boot / mainline): Y / Y

### External GPIO (RTL8231)
- RTL9303: SDK ext-dev support (`ext-devInit`) [DOC [RTK-COMMANDS.md](RTK-COMMANDS.md)]
- Board: N (74HC164 LEDs + TCA9534A instead)
- Stock U-Boot: init fails (`0xf012`)
- Stock Linux: N
- OpenWrt: `LEDS_RTL8231` off
- Ours (U-Boot / mainline): N
- Value if enabled: none

### USB 2.0 host (EHCI)
- RTL9303: Y [DS §6.10]; `0xb8021000`, irq 28 [LOG]
- Board: **N**: no connector, pads or ESD (#5)
- Stock U-Boot: N
- Stock Linux: `rtk_gen1-ehci`, 1 port, nothing attached [LOG]
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: none

### PCIe
- RTL9303: **N**: no balls [DS pin table]; only `PCIE_CTRL` PHY bits `0xb8000504` and `IP_EN` 6/7 [SOC]
- Value if enabled: none

### SATA
- RTL9303: **N**: no balls [DS pin table]; `SATA_CTRL` `0xb8000510` [SOC]
- Value if enabled: none

### VoIP / PCM / NFBI / GMAC
- RTL9303: `IP_EN_CTRL` bits only [SOC]; no balls: N SPEC
- Value if enabled: none

## System blocks

### Interrupt controller
- RTL9303: Y [DS Fig. 1]; per-VPE `GIMR/GISR/IRR0-3` `0xb8003000`/`0xb8003018` [SOC]
- Stock U-Boot: N (polled) SPEC
- Stock Linux: Y
- OpenWrt: `rtl9300-intc`
- Ours (U-Boot / mainline): polled / Y

### Delayed-interrupt (timer-coalesced)
- RTL9303: `TC2-4_DLY_INTR` `0xb8003088` [SOC] SPEC
- Stock U-Boot: N
- Stock Linux: SPEC
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: low: NIC IRQ coalescing (#60) SPEC

### Timers TC0-TC4 (+TC5)
- RTL9303: "Timer*5" [DS Fig. 1]; SDK lists TC0-TC5 `0xb8003200` [SOC]; 6 timer sets read back (TC5 present) [LIVE]
- Stock U-Boot: N SPEC
- Stock Linux: `rtcore` "TC probe/init" [LOG]
- OpenWrt: `realtek_otto_timer` TC0-4 (clocksource)
- Ours (U-Boot / mainline): CP0 / otto timer

### SoC watchdog
- RTL9303: Y [DS Fig. 1]; `WDTCNTRR/WDTINTRR/WDT_CTRL` `0xb8003260`, phase 1 IRQ + phase 2 reset [SOC]
- Stock U-Boot: not referenced [BIN]
- Stock Linux: `rtcore` probe + init [LOG]; no enable caller in `rtk.ko` [BIN]; userspace SPEC
- OpenWrt: `realtek_otto_wdt`, 30 s, reset-mode soc
- Ours (U-Boot / mainline): **N** / `REALTEK_OTTO_WDT`
- Value if enabled: **high**: hang recovery from power-on through `bootm` (chained boot, #47)

### External watchdog / reset line (GPIO21)
- RTL9303: GPIO
- Board: DTS `linux,wdt-gpio` toggle 1.2 s; low = board reset (#18)
- Stock U-Boot: N
- Stock Linux: `switch_reset()` drives it low on mode change [BIN]
- OpenWrt: `gpio-wdt` (always-running)
- Ours (U-Boot / mainline): refused low / node disabled (#18)

### Reset control
- RTL9303: `RST_GLB_CTRL_0` `0xbb00000c`: SW_CHIP_RST bit 0, NIC/queue/SerDes/switch resets, CHIP_RST_EN, WD_RST_EN; status `RST_GLB_STS_0-3` (chip / watchdog reset status) [SW]; `RST_OUT` pin [DS §6.11]
- Stock U-Boot: SPEC
- Stock Linux: SPEC
- OpenWrt: switch reset at CPU-port init ("RESETTING 9300") [OWRT log]
- Ours (U-Boot / mainline): `reset` not implemented / `syscon-reboot` `0x0c` value 1 [ML]
- Value if enabled: **high**: `reset` in our U-Boot; reset-cause readout

### Thermal sensor
- RTL9303: Y, `THERMAL_METER_CTRL_0-2`, `THERMAL_METER_RESULT_0-1` `0xbb000060-0x70` [SW]; off at power-on [LIVE [hardware.md](hardware.md)]
- Stock U-Boot: N
- Stock Linux: N (#13)
- OpenWrt: `realtek-thermal`, trip 105 °C
- Ours (U-Boot / mainline): `rtk temp` / N
- Value if enabled: used

### eFuse / OTP
- RTL9303: `EFUSE_ACCESS_*` `0xbb00c698-0xc6a4`, 8-bit address, 16-bit data, indirect [SW]. Autoloaded at reset (`CTRL_DONE` = 1 at power-up); loaded copies: `MAC_EFUSE_CTRL` `0xc6fc` = `0x0003fffe` (CHIP_MODE 14, read-only), `CALIB_CTRL_2-4` `0xc6ac` = `033c03f1 81308128 00000188`, `CODE_PROTECT_STATE` `0xc7c8` = 0 (no EJTAG-disable / key fuses) [LIVE 2026-10-12, #68]
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: N
- Ours (U-Boot / mainline): `./dev.py hidden-write-probe efuse` (read sequence only)
- Value if enabled: low: SW read path returns 0 for all 256 words with `EFUSE_ACCESS_EN` = 0; enable value unknown (#68); left unread by owner decision (#75)

### Crypto engine
- RTL9303: Y [DS Fig. 1 "Crypto Engine"; strap `EN_DECRYPT` = flash decrypt, §6.12]; `IPSEC_*` `0xb800c000`, `IP_EN_CTRL` bit 10, GIMR `SECURITY_IE` bit 22 [SOC]. RTL865xC-class engine: AES-128/192/256 ECB/CBC/CTR, DES, 3DES, MD5, SHA1, HMAC; 25/25 KATs pass, AES-128 29 MB/s, clock = LX [LIVE 2026-10-12, [CRYPTO.md](CRYPTO.md)]
- Board: flash is plaintext; strap default 0 [DS]
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: N
- Ours (U-Boot / mainline): `rtk crypto probe/test/bench` / N
- Value if enabled: low: AES ~235 Mbit/s offload; hashing slower than the CPU; no GCM/ChaCha/SHA-2

### GDMA / bus traffic generator
- RTL9303: `LX0/1/2_GDMA_CTRL` `0xb8144000`/`0xb800a000`/`0xb8018000` + BTG regs [SOC]; enables `IP_EN_CTRL` 8/9, `NEW_IP_EN_CTRL` 6-10 (GDMA0-6; regs for 3 only); GIMR `BTG_IE` bit 12. Not in DS: SPEC
- Stock U-Boot: N
- Stock Linux: N
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: low-medium: memcpy/memset/checksum offload in U-Boot; bus load generator for DDR tests SPEC

### Pinmux
- RTL9303: `GPIO_SEL_CTRL` / `JTAG_SEL_CTRL` / `SPI_CTRL1` `0xbb000200/204/3a0`, `EXT_GPIO_GLB_CTRL` `0xbb00c600`, `LED_GLB_CTRL` `0xbb00cc00` [OWRT]
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: Y
- Ours (U-Boot / mainline): read-only (`reg-diff`)

## Switch core

### Chip ID
- RTL9303: `MODEL_NAME_INFO` `0xbb000004` = `0x93030001` [LIVE [hardware.md](hardware.md)]; `CHIP_INFO` `0x08` with `CHIP_INFO_EN` = 0xA: `0x100a6487` = RL_VID 1, MCID 0, RL_ID `0x6487` [LIVE 2026-10-12, #68]
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: "RTL9303 rev B"
- Ours (U-Boot / mainline): read / N

### 10G MACs
- RTL9303: 8 (MAC0-7) [DS Fig. 1] = SoC ports 0, 8, 16, 20, 24-27 [OWRT DTS]
- Board: 8 SFP+ cages
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: Y (DSA `lan1-8`)
- Ours (U-Boot / mainline): `network on`, MAC force, isolation / N

### SerDes
- RTL9303: 12 indices [OWRT log]; balls: S0 (SGMII, external CPU) + S2-S9 (10GBASE-R) [DS §6.5-6.6]; S1/S10/S11 no balls SPEC
- Board: S2-S9 = cages 1-8; S0 unused (DS: pull low via 1 kΩ)
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: `realtek-otto-pcs`
- Ours (U-Boot / mainline): `network on`, `sdsreg` / N

### CPU port / NIC DMA
- RTL9303: port 28, internal NIC [DS §7.24]; `DMA_IF_*` `0xbb00e000..` [SW]; 32 CPU-port queues [DS §2]
- Stock U-Boot: `swnic_send` [BIN]
- Stock Linux: `RTNIC`
- OpenWrt: `rtl838x_eth`: 2 of 32 RX rings, TX ring 16 (#60)
- Ours (U-Boot / mainline): N (Ethernet stage) / N
- Value if enabled: high: #60 (used, under-used)

### External-CPU mode
- RTL9303: port 28 SGMII or port 27 10G-R/USXGMII/HISGMII on S0 [DS §2]
- Board: N
- Value if enabled: none

### Packet buffer
- RTL9303: 12 Mbit, jumbo 12 KB [DS §2]
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: Y
- Ours (U-Boot / mainline): Y

### L2 / VLAN
- RTL9303: 16K MAC (2-left 4-way), 1K MC, 4K VLAN, 64 MSTI [DS §2]
- Stock U-Boot: SDK default forwarding
- Stock Linux: Y
- OpenWrt: DSA bridge offload
- Ours (U-Boot / mainline): PORT_ISO table only / N

### L3 routing
- RTL9303: 6K host, 512 LPM, 2K next hop, 128 intf, 64 router MAC, uRPF, PBR, MC routing [DS §2, §7.14]; no NAT (#58)
- Stock U-Boot: N
- Stock Linux: API in `rtk.ko` [BIN]; unmanaged: no config SPEC
- OpenWrt: `l3.c`: gateway routes only (#59)
- Ours (U-Boot / mainline): N
- Value if enabled: medium: #59

### ACL / PIE
- RTL9303: 2K entries, 256 policers, 2K log counters [DS §7.13]
- Stock U-Boot: N SPEC
- Stock Linux: N SPEC
- OpenWrt: partial (tc) SPEC
- Ours (U-Boot / mainline): N
- Value if enabled: low (unmanaged use)

### QoS / meters / storm control / SWRED
- RTL9303: [DS §7.15-7.22]; `METER_GLB_CTRL` `0xbb00a0a0` [SW]
- Stock U-Boot: defaults
- Stock Linux: defaults SPEC
- OpenWrt: partial SPEC
- Ours (U-Boot / mainline): N
- Value if enabled: low

### Mirroring / sFlow / RSPAN
- RTL9303: 4 mirror sets [DS §7.11]; `MIR_CTRL` `0xbb00a2a0`, `SFLOW_CTRL` `0xbb00bea0` [SW]
- Stock U-Boot: N
- Stock Linux: N SPEC
- OpenWrt: port mirroring SPEC
- Ours (U-Boot / mainline): N
- Value if enabled: low-medium: hardware sniff port for debugging

### Link aggregation
- RTL9303: 64 groups x 8 ports [DS §7.10]
- Stock U-Boot: N
- Stock Linux: N SPEC
- OpenWrt: LAG offload SPEC
- Ours (U-Boot / mainline): N
- Value if enabled: low

### MIB counters
- RTL9303: [DS §7.23]; `STAT_PORT_MIB_CNTR(port)` `0xbb000664 + 0x100*port` [SW]
- Stock U-Boot: Y
- Stock Linux: Y
- OpenWrt: `ethtool -S`
- Ours (U-Boot / mainline): `md.l` reads (docs) / N

### LED engine
- RTL9303: serial LED (`LED_MDC/MDIO` C1/C2) or scan, 3 sets [DS §6.7, §9.4.13]; `LED_GLB_CTRL` `0xbb00cc00` [SW]
- Board: 24 LEDs via 3x 74HC164 [DOC hardware.md]
- Stock U-Boot: Y (`mac_led_config`)
- Stock Linux: Y
- OpenWrt: `led_set0`
- Ours (U-Boot / mainline): `network on` LED config, `ledtest` / N
- Value if enabled: medium: richer LED scheme (#9)

### System LED
- RTL9303: `SYS_LED` B5 = GPIO0 when strap `SYS_LED_EN` = 1 [DS §6.7, §6.12]
- Board: GPIO0 is cage-1 MOD-DEF0: sys LED off SPEC
- OpenWrt: pinmux can disable it
- Value if enabled: none

### MDIO / SMI masters
- RTL9303: 4 buses M0-M3 [DS §6.11]; `SMI_*` `0xbb00ca00..` [SW]; aux GPIO-MDIO [OWRT]
- Board: no PHYs (`HWP_NONE`)
- Stock U-Boot: SMI MAC-type / polling config
- Stock Linux: Y
- OpenWrt: `mdio-rtl-otto` probes 4 buses; aux disabled
- Ours (U-Boot / mainline): SMI_MAC_TYPE + poll masks / `MDIO_REALTEK_RTL9300`
- Value if enabled: none (no PHY)

### EEE
- RTL9303: per port, per speed [DS §7.28]; `EEE_*` `0xbb00c720..`, `0xbb003274 + 0x40*port` [SW]
- Board: optical SFP+: no EEE SPEC
- Stock U-Boot: dal `eee` init [DOC UBOOT-REFERENCE.md]
- Stock Linux: SPEC
- OpenWrt: N
- Ours (U-Boot / mainline): N (`rtk eee` usage only)
- Value if enabled: none

### OAM / dying gasp
- RTL9303: 802.3ah loopback + dying gasp, `PWRMON` ball AD12 [DS §7.27]; `OAM_CTRL` `0xbb00a120` [SW]
- Board: PWRMON wiring unknown SPEC
- Stock U-Boot: N
- Stock Linux: N SPEC
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: low

### PTP / IEEE 1588
- RTL9303: "supported by PHY" only [DS §2]; switch core has only the PTP trap `RMA_PORT_PTP_CTRL` [SW]
- Board: no PHY: **N**
- Value if enabled: none

### SyncE
- RTL9303: no mention [DS]; no SyncE regs [SW]: **N** SPEC
- Value if enabled: none

### Stacking
- RTL9303: "Stacking" [DS Fig. 1]; SDK `stack` init [DOC UBOOT-REFERENCE.md]
- Board: single unit
- Stock U-Boot: init only
- Stock Linux: SPEC
- OpenWrt: N
- Ours (U-Boot / mainline): N
- Value if enabled: none

### Clock outputs
- RTL9303: 25 MHz `CKO0/1/2/4`, SerDes `CLKP/N_S2/4/6/8` [DS §6.11]
- Board: wiring unknown SPEC
- Value if enabled: none

## Probe coverage

- `scripts/hw_probe.py` reads one or more ID/ctrl words of every block with a known address above; gated blocks (GDMA, crypto, SPI-NAND/ECC) only when their enable bit is set, or with `--gated`.
- Not read (side effects or need a write first): UART RBR/IIR/LSR/MSR, SPI `SFDR`, `GISR`, switch `ISR_GLB`, NIC `DMA_IF_INTR_STS`, MIB counters, MAC link status, SerDes indirect regs. PCIe/SATA controllers: no balls, address unknown.
- CP0 Config words: not readable with `md`; values above from the `bench` command output (console log).

## Measured 2026-10-11 (hw-probe)

`./dev.py hw-probe --label first` at our U-Boot (from flash), 2026-10-11T23:24+11:00: all 62 safe probes completed, no hang (#62).

- `IP_EN_CTRL` `0xb8000600` = `0x40000f88`: USBPHY0, VOIPACC, IPSEC, **GDMA1, GDMA0**, PCIE0, P1USBHOST enabled at reset. PCIe/VoIP/USB bits = Otto-superset defaults (no balls / not wired). `NEW_IP_EN_CTRL` `0xb800063c` = 0 (GDMA2-6 off).
- GDMA0/1 enabled at reset; gated GDMA reads (`--gated`) not yet run.
- Present: OCP and LX bus-timeout monitors (`0x1c000000` / `0x70000000`, enable bit 31 off), 6 timer sets (TC5; the datasheet says 5), UART1 (LCR `03`, unused), EHCI (PORTSC1 `0x2000`, nothing attached), thermal meter, OAM dying-gasp ctrl, EEE.
- SoC watchdog `WDT_CTRL` = 0 (off) in our U-Boot.
- Reset-cause words at `0xbb00000c` (`RST_GLB_CTRL_0`, `RST_GLB_STS_0-2`): `00005000 0 0 0000000c`.
- Crypto engine: present and working, `EN_IPSEC` 1; power-up IPSSDAR `9fc0ffb0`, IPSDDAR `9fc0ffe0`, IPSCSR 0, IPSCTR `000010d2` ([CRYPTO.md](CRYPTO.md)).
- eFuse: not read further; owner decision 2026-10-12 leaves it unread (#75, [DECISIONS.md](DECISIONS.md)); the autoloaded copies above carry the useful content.

## GDMA function codes

- `CTRL[27:24]` (SDK `rtk_soc/test/gdma/asicregs.h`): 0 memcpy, 1 checksum, 2 sequential TCAM, 3 memset, 9 XOR, 10 memcmp, 11 byte swap, 12 pattern match; 8 source / 8 destination block pointers (scatter/gather).
- SDK uses it only in test commands (`mgdma_test`, `mconcur_test`); stock and OpenWrt never touch it. Linux gain small: the network stack does not use async memcpy.
