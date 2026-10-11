# RTL9303 hardware inventory (TL-ST1008F v2)

Every SoC block: on the chip, wired on this board, used by stock U-Boot / stock Linux / OpenWrt / ours, value if enabled. Issue #62. Presence probe: `./dev.py hw-probe` ([scripts/README.md](../scripts/README.md#hw_probepy)).

Source tags:
- **[DS §]** `sources/rtl9303-cg-brief.pdf` Rev 1.1-1 (block diagram = Fig. 1).
- **[SOC]** Realtek GPL SDK `rtl9300_soc_reg.h`; **[SW]** `swcore_rtl9300.h` (github.com/reyalo/Realtek `sources/rtk-xgs1210/system/include/...`). Otto superset: lists blocks the RTL9303 package has no balls for.
- **[OWRT]** OpenWrt `target/linux/realtek` (`rtl930x.dtsi`, `rtl9303_tplink_tl-st1008f-v2.dts`, `rtl930x/config-6.18`, 25.12.4 boot log `artifacts/`). **[ML]** `mainline/` DTS + config, Linux 7.3 `rtl930x.dtsi`.
- **[BIN]** stock loader / `rtcore.ko` / `rtk.ko` decompiles (local only). **[LOG]** stock boot log `artifacts/stock-boot-20261008.log`.
- **[LIVE]** read on this unit (console log, dated in the cited doc). **[DOC]** repo doc named in the cell.
- **SPEC** = inferred, not verified on hardware or in vendor code.

Abbreviations: Y = yes, N = no, `-` = not applicable. Addresses are KSEG1 (`0xb8..` SoC, `0xbb..` switch core).

## CPU

| Block | RTL9303 | Board | Stock U-Boot | Stock Linux | OpenWrt | Ours (U-Boot / mainline) | Value if enabled |
|---|---|---|---|---|---|---|---|
| MIPS 34Kc core | Y, PRId `0x00019555` [LIVE], "up to 800 MHz" [DS §8.1] | - | Y, 800 MHz | Y | Y, 800 MHz | Y; U-Boot runs 1 GHz chained ([CLOCKS.md](CLOCKS.md)) / Y | - |
| MT ASE, VPEs | Y: Config3 `0x00002424` bit 2 MT [LIVE]; 2 VPEs (Linux "Brought up 2 CPUs" [OWRT log]). TC count: MVPConf0 not read, SPEC | - | VPE0 only | SPEC (boot log shows no SMP lines) | `MIPS_MT_SMP`, `NR_CPUS=2` | VPE0 only / `MIPS_MT_SMP`, `NR_CPUS` 16 (#27) | - (used) |
| FPU | **N**: Config1 `0xbea3519e` bit 0 FP = 0 [LIVE] | - | - | emulation | emulation | integer only / emulation | - |
| DSP ASE | Y **rev 1 only**: Config3 bit 10 DSPP = 1, bit 11 DSP2P = 0 [LIVE] (#27 said r2) | - | N | kernel saves DSP context | userspace `CPU_TYPE:=24kc`, no `-mdsp` (#27) | N | low: codec/DSP loops; none for forwarding |
| Other CPU options | MIPS16e (Config1 CA), perf counters (PC), watch regs (WR), EJTAG (EP), UserLocal (Config3 ULRI), vectored ints (VInt; no VEIC), no SmartMIPS; no ISPRAM/DSPRAM scratchpad (Config `0x80248483` ISP = DSP = 0) [LIVE] | - | - | - | perf counters (`MIPS_PERF_SHARED_TC_COUNTERS`) | - | low |
| MMU | 32-entry JTLB, 4 ITLB, 4 DTLB [DS §8.1]; Config1 MMU size 32 [LIVE] | - | Y | Y | Y | wired TLB pair for `highmem` / Y | - |
| L1 caches | 32 KiB I + 32 KiB D, 4-way, 32 B lines [DS §8.1, LIVE Config1]; D-cache PIPT, no aliases [OWRT log] | - | Y | Y | Y | Y | - |
| L2 cache | **N**: Config2 `0x80000000` [LIVE] | - | - | - | selects `MIPS_CPU_SCACHE`, finds none (no "secondary cache" line) | not selected (correct) | - |
| CP0 Count timer | Y, CPU / 2 [LIVE [CLOCKS.md](CLOCKS.md)] | - | SPEC | SPEC | Y (hpt; rate from DT, our patch 300-05 reads the PLL); clocksource = otto timer | U-Boot timer / Y, rate wrong without DT `frequency` (#55) | - |

## Memory and buses

| Block | RTL9303 | Board | Stock U-Boot | Stock Linux | OpenWrt | Ours (U-Boot / mainline) | Value if enabled |
|---|---|---|---|---|---|---|---|
| 64 KiB SRAM | Y [DS §1 "64Kbyte SP-SRAM"]; seg regs `0xb8004000` (SEG0 = SRAMSAR0) [SOC] | - | SPL runs from it at `0x9f000000`; window bus `0x1f000000` (`0x1f000001`) left mapped [LIVE [UBOOT-MAINLINE.md](UBOOT-MAINLINE.md)] | N SPEC | N (930x clk driver off) | clock/DDR routines run from it ([CLOCKS.md](CLOCKS.md)); `highmem map` unmaps it / N | medium: hot data with ~110 ns DDR miss latency; NIC DMA reach unknown |
| DSP SRAM seg regs | regs at `0xb8004040` [SOC]; no DSP core in Fig. 1: N SPEC | - | - | - | - | - | none |
| Mask ROM | `ROMSAR` `0xb8004080` [SOC]; strap `BOOT_SEL` 1 = ROM boot [DS §6.12]: Y SPEC | boots NOR | - | - | - | - | none |
| DDR3 controller | Y, 8/16-bit, 1 GiB max [DS §8.3]; `0xb8001000` [SOC] | one x16 4 Gbit die, 512 MiB, 600 MHz [DOC [DRAM.md](DRAM.md)] | Y (SPL init) | Y | Y | DDR clock/timing tools ([CLOCKS.md](CLOCKS.md)) / Y | DRAM prefetch (MCR `ip_ref`/`dp_ref`) off in stock: +26-61 % (#52, #53) |
| Bus zones / unmapped segments | `UMSAR0-3` `0xb8001300`, OCP DOR/DMAR [SOC] | 2nd 256 MiB needs zone 3 | N | SPEC | Y (`300-02` highmem remap) | `highmem map` / N (#27) | 2nd 256 MiB in mainline (#27) |
| OCP / LX bus timeout monitors | `TO_CTRL` `0xb8005100`, `LB*TCR` `0xb8005200..` ; GIMR `OCPTO`/`LXMTO`/`LXSTO` [SOC] | - | SPEC | SPEC | N | N | low-medium: a hung bus access becomes an IRQ with the address |
| Speed sensors (ring osc) | `SPD_SENSOR0-8` `0xb8000618` [SOC] | - | N | N | N | N | low: die speed for overclock limits (#38) |
| IP enable registers | `IP_EN_CTRL` `0xb8000600`, `NEW_IP_EN_CTRL` `0xb800063c` [SOC] | - | - | - | - | read by `hw-probe` | - |

## Flash and serial interfaces

| Block | RTL9303 | Board | Stock U-Boot | Stock Linux | OpenWrt | Ours (U-Boot / mainline) | Value if enabled |
|---|---|---|---|---|---|---|---|
| SPI-NOR controller | Y: 2 CS, 1/2/4-bit, PIO + mmio read window, cached reads [DS §8.2]; `0xb8001200`, window `0xb4000000` [SOC, LIVE] | one Winbond W25Q256JV (32 MiB) on CS0; IO2/IO3 routing unknown (#61) | Y: SFCR2 `0xbbc14a00` = Fast Read **Dual I/O** mmio [LIVE #61] | Y: `RTK_NORSFG3`, `MMIO32-2/ModeC` [LOG] | PIO, 1-bit, no dirmap (#61) | PIO 1-bit + mmio window (stock mode) / PIO 1-bit | **high**: dual/quad dirmap in Linux (#61) |
| SPI-NAND controller + ECC | Y [DS §2 "512MB SPI NAND"]; `0xb801a400`, ECC `0xb801a600` [SOC]; OpenWrt nodes `status = "disabled"` | no NAND | N | N | N (`rtl930x_nand` subtarget is for other boards) | N | none |
| SPI master (2 sets) | Y [DS §2 "2-set SPI master"]: flash controller (CS0/CS1 balls E2/E1) + switch-core SPI master `SPI_CTRL1` `0xbb0003a0` [SW] | CS1 and switch-core SPI: nothing attached SPEC | `spi_master_*`, `spi_dev3_init` present [BIN] | "SPI none dev init" [LOG] | `0x3a0` only as pinmux (GPIO 3-7) | N | none |
| SPI slave | Y [DS §6.9], balls A1-A3/B3; strap `REG_IF_SEL` [DS §6.12] (external-CPU register access) | no external CPU | N | N | pinmux frees its GPIOs | N | none |
| UART0 | Y [DS §6.2], `0xb8002000` [SOC] | header J14 `DH GND RX TX` | console | console | console | console, up to 10.94 MBd ([UBOOT-MAINLINE.md](UBOOT-MAINLINE.md)) / console | - |
| UART1 | Y [DS §6.2], `0xb8002100` [SOC]; balls shared with EJTAG (RXD A4 = TDI, RTS B4 = TMS, CTS C5 = TCK, TXD D5 = TDO) | only via the 5-pad JTAG footprint SPEC | N | N | node `disabled`, pinmux `0xbb000204` | N | low-medium: second console while UART0 is busy |
| EJTAG | Y [DS §6.3], Config1 EP [LIVE] | 5-pad footprint, board bottom [DOC [hardware.md](hardware.md)] | N | N | N | N | medium: recovery path if flash boot breaks (needs a probe adapter) |
| I2C master MST1 | Y, `0xbb00036c` [SW]; SCL0 GPIO8, SDA0-7 GPIO9-16 [DOC hardware.md] | 8 SFP cages (EEPROM `0x50`, DDM `0x51`) | `rtk i2c` dev 0-7 | Y | `i2c_mst1` | `i2c-rtl9300` / Y | - (used) |
| I2C master MST2 | Y, `0xbb000388` [SW] | SCL1 = GPIO17 per SDK pin formula = mode switch: unusable here SPEC | N | N | N | N | none |
| "8-set I2C master" | [DS §2]: 8 SDA channels per master SPEC | - | - | - | - | - | - |
| GPIO 0-23 | Y [DS §6.4], `0xb8003300` [SOC] | 0-7 MOD-DEF0, 8 SCL0, 9-16 SDA0-7, 17-19 mode switch, 20 unknown, 21 ext watchdog / board reset, 22/23 i2c-gpio to TCA9534A [DOC hardware.md] | Y | Y | Y | Y / Y | - |
| External GPIO (RTL8231) | SDK ext-dev support (`ext-devInit`) [DOC [RTK-COMMANDS.md](RTK-COMMANDS.md)] | N (74HC164 LEDs + TCA9534A instead) | init fails (`0xf012`) | N | `LEDS_RTL8231` off | N | none |
| USB 2.0 host (EHCI) | Y [DS §6.10]; `0xb8021000`, irq 28 [LOG] | **N**: no connector, pads or ESD (#5) | N | `rtk_gen1-ehci`, 1 port, nothing attached [LOG] | N | N | none |
| PCIe | **N**: no balls [DS pin table]; only `PCIE_CTRL` PHY bits `0xb8000504` and `IP_EN` 6/7 [SOC] | - | - | - | - | - | none |
| SATA | **N**: no balls [DS pin table]; `SATA_CTRL` `0xb8000510` [SOC] | - | - | - | - | - | none |
| VoIP / PCM / NFBI / GMAC | `IP_EN_CTRL` bits only [SOC]; no balls: N SPEC | - | - | - | - | - | none |

## System blocks

| Block | RTL9303 | Board | Stock U-Boot | Stock Linux | OpenWrt | Ours (U-Boot / mainline) | Value if enabled |
|---|---|---|---|---|---|---|---|
| Interrupt controller | Y [DS Fig. 1]; per-VPE `GIMR/GISR/IRR0-3` `0xb8003000`/`0xb8003018` [SOC] | - | N (polled) SPEC | Y | `rtl9300-intc` | polled / Y | - |
| Delayed-interrupt (timer-coalesced) | `TC2-4_DLY_INTR` `0xb8003088` [SOC] SPEC | - | N | SPEC | N | N | low: NIC IRQ coalescing (#60) SPEC |
| Timers TC0-TC4 (+TC5) | "Timer*5" [DS Fig. 1]; SDK lists TC0-TC5 `0xb8003200` [SOC]: TC5 SPEC | - | N SPEC | `rtcore` "TC probe/init" [LOG] | `realtek_otto_timer` TC0-4 (clocksource) | CP0 / otto timer | - |
| SoC watchdog | Y [DS Fig. 1]; `WDTCNTRR/WDTINTRR/WDT_CTRL` `0xb8003260`, phase 1 IRQ + phase 2 reset [SOC] | - | not referenced [BIN] | `rtcore` probe + init [LOG]; no enable caller in `rtk.ko` [BIN]; userspace SPEC | `realtek_otto_wdt`, 30 s, reset-mode soc | **N** / `REALTEK_OTTO_WDT` | **high**: hang recovery from power-on through `bootm` (chained boot, #47) |
| External watchdog / reset line (GPIO21) | GPIO | DTS `linux,wdt-gpio` toggle 1.2 s; low = board reset (#18) | N | `switch_reset()` drives it low on mode change [BIN] | `gpio-wdt` (always-running) | refused low / node disabled (#18) | - |
| Reset control | `RST_GLB_CTRL_0` `0xbb00000c`: SW_CHIP_RST bit 0, NIC/queue/SerDes/switch resets, CHIP_RST_EN, WD_RST_EN; status `RST_GLB_STS_0-3` (chip / watchdog reset status) [SW]; `RST_OUT` pin [DS §6.11] | - | SPEC | SPEC | switch reset at CPU-port init ("RESETTING 9300") [OWRT log] | `reset` not implemented / `syscon-reboot` `0x0c` value 1 [ML] | **high**: `reset` in our U-Boot; reset-cause readout |
| Thermal sensor | Y, `0xbb000060-0x70` [SW]; off at power-on [LIVE [hardware.md](hardware.md)] | - | N | N (#13) | `realtek-thermal`, trip 105 °C | `rtk temp` / N | - (used) |
| eFuse / OTP | `EFUSE_ACCESS_*` `0xbb00c698-0xc6a4`, 8-bit address, 16-bit data, indirect [SW] | content unknown | N SPEC | N SPEC | N | N | low: ID / calibration words SPEC |
| Crypto engine | Y [DS Fig. 1 "Crypto Engine"; strap `EN_DECRYPT` = flash decrypt, §6.12]; `IPSEC_*` `0xb800c000`, `IP_EN_CTRL` bit 10, GIMR `SECURITY_IE` bit 22 [SOC]. Algorithms SPEC (SDK test code is for RTL865x/8686: DES/3DES/AES, MD5/SHA1 HMAC) | flash is plaintext; strap default 0 [DS] | N | N | N | N | low: legacy ciphers only; no ChaCha/GCM SPEC |
| GDMA / bus traffic generator | `LX0/1/2_GDMA_CTRL` `0xb8144000`/`0xb800a000`/`0xb8018000` + BTG regs [SOC]; enables `IP_EN_CTRL` 8/9, `NEW_IP_EN_CTRL` 6-10 (GDMA0-6; regs for 3 only); GIMR `BTG_IE` bit 12. Not in DS: SPEC | - | N | N | N | N | low-medium: memcpy/memset/checksum offload in U-Boot; bus load generator for DDR tests SPEC |
| Pinmux | `0xbb000200/204/3a0`, `0xbb00c600`, `0xbb00cc00` [OWRT] | - | Y | Y | Y | read-only (`reg-diff`) | - |

## Switch core

| Block | RTL9303 | Board | Stock U-Boot | Stock Linux | OpenWrt | Ours (U-Boot / mainline) | Value if enabled |
|---|---|---|---|---|---|---|---|
| Chip ID | `MODEL_NAME_INFO` `0xbb000004` = `0x93030001` [LIVE [hardware.md](hardware.md)]; `CHIP_INFO` `0x08` needs an enable write [SW] | - | Y | Y | "RTL9303 rev B" | read / N | - |
| 10G MACs | 8 (MAC0-7) [DS Fig. 1] = SoC ports 0, 8, 16, 20, 24-27 [OWRT DTS] | 8 SFP+ cages | Y | Y | Y (DSA `lan1-8`) | `network on`, MAC force, isolation / N | - |
| SerDes | 12 indices [OWRT log]; balls: S0 (SGMII, external CPU) + S2-S9 (10GBASE-R) [DS §6.5-6.6]; S1/S10/S11 no balls SPEC | S2-S9 = cages 1-8; S0 unused (DS: pull low via 1 kΩ) | Y | Y | `realtek-otto-pcs` | `network on`, `sdsreg` / N | - |
| CPU port / NIC DMA | port 28, internal NIC [DS §7.24]; `DMA_IF_*` `0xbb00e000..` [SW]; 32 CPU-port queues [DS §2] | - | `swnic_send` [BIN] | `RTNIC` | `rtl838x_eth`: 2 of 32 RX rings, TX ring 16 (#60) | N (Ethernet stage) / N | high: #60 (used, under-used) |
| External-CPU mode | port 28 SGMII or port 27 10G-R/USXGMII/HISGMII on S0 [DS §2] | N | - | - | - | - | none |
| Packet buffer | 12 Mbit, jumbo 12 KB [DS §2] | - | Y | Y | Y | Y | - |
| L2 / VLAN | 16K MAC (2-left 4-way), 1K MC, 4K VLAN, 64 MSTI [DS §2] | - | SDK default forwarding | Y | DSA bridge offload | PORT_ISO table only / N | - |
| L3 routing | 6K host, 512 LPM, 2K next hop, 128 intf, 64 router MAC, uRPF, PBR, MC routing [DS §2, §7.14]; no NAT (#58) | - | N | API in `rtk.ko` [BIN]; unmanaged: no config SPEC | `l3.c`: gateway routes only (#59) | N | medium: #59 |
| ACL / PIE | 2K entries, 256 policers, 2K log counters [DS §7.13] | - | N SPEC | N SPEC | partial (tc) SPEC | N | low (unmanaged use) |
| QoS / meters / storm control / SWRED | [DS §7.15-7.22]; `METER_GLB_CTRL` `0xbb00a0a0` [SW] | - | defaults | defaults SPEC | partial SPEC | N | low |
| Mirroring / sFlow / RSPAN | 4 mirror sets [DS §7.11]; `MIR_CTRL` `0xbb00a2a0`, `SFLOW_CTRL` `0xbb00bea0` [SW] | - | N | N SPEC | port mirroring SPEC | N | low-medium: hardware sniff port for debugging |
| Link aggregation | 64 groups x 8 ports [DS §7.10] | - | N | N SPEC | LAG offload SPEC | N | low |
| MIB counters | [DS §7.23]; `0xbb000664 + 0x100*port` [SW] | - | Y | Y | `ethtool -S` | `md.l` reads (docs) / N | - |
| LED engine | serial LED (`LED_MDC/MDIO` C1/C2) or scan, 3 sets [DS §6.7, §9.4.13]; `0xbb00cc00` [SW] | 24 LEDs via 3x 74HC164 [DOC hardware.md] | Y (`mac_led_config`) | Y | `led_set0` | `network on` LED config, `ledtest` / N | medium: richer LED scheme (#9) |
| System LED | `SYS_LED` B5 = GPIO0 when strap `SYS_LED_EN` = 1 [DS §6.7, §6.12] | GPIO0 is cage-1 MOD-DEF0: sys LED off SPEC | - | - | pinmux can disable it | - | none |
| MDIO / SMI masters | 4 buses M0-M3 [DS §6.11]; `SMI_*` `0xbb00ca00..` [SW]; aux GPIO-MDIO [OWRT] | no PHYs (`HWP_NONE`) | SMI MAC-type / polling config | Y | `mdio-rtl-otto` probes 4 buses; aux disabled | SMI_MAC_TYPE + poll masks / `MDIO_REALTEK_RTL9300` | none (no PHY) |
| EEE | per port, per speed [DS §7.28]; `EEE_*` `0xbb00c720..`, `0xbb003274 + 0x40*port` [SW] | optical SFP+: no EEE SPEC | dal `eee` init [DOC UBOOT-REFERENCE.md] | SPEC | N | N (`rtk eee` usage only) | none |
| OAM / dying gasp | 802.3ah loopback + dying gasp, `PWRMON` ball AD12 [DS §7.27]; `OAM_CTRL` `0xbb00a120` [SW] | PWRMON wiring unknown SPEC | N | N SPEC | N | N | low |
| PTP / IEEE 1588 | "supported by PHY" only [DS §2]; switch core has only the PTP trap `RMA_PORT_PTP_CTRL` [SW] | no PHY: **N** | - | - | - | - | none |
| SyncE | no mention [DS]; no SyncE regs [SW]: **N** SPEC | - | - | - | - | - | none |
| Stacking | "Stacking" [DS Fig. 1]; SDK `stack` init [DOC UBOOT-REFERENCE.md] | single unit | init only | SPEC | N | N | none |
| Clock outputs | 25 MHz `CKO0/1/2/4`, SerDes `CLKP/N_S2/4/6/8` [DS §6.11] | wiring unknown SPEC | - | - | - | - | none |

## Probe coverage

- `scripts/hw_probe.py` reads one or more ID/ctrl words of every block with a known address above; gated blocks (GDMA, crypto, SPI-NAND/ECC) only when their enable bit is set, or with `--gated`.
- Not read (side effects or need a write first): UART RBR/IIR/LSR/MSR, SPI `SFDR`, `GISR`, switch `ISR_GLB`, NIC `DMA_IF_INTR_STS`, `EFUSE_RDATA`, MIB counters, MAC link status, SerDes indirect regs. PCIe/SATA controllers: no balls, address unknown.
- CP0 Config words: not readable with `md`; values above from the `bench` command output (console log).
