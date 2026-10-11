# TL-ST1008F v2 hardware

Narrative & dead ends: see [HISTORY.md](HISTORY.md). Evidence paths under `private/` are local-only (gitignored); public excerpts are in [../artifacts/](../artifacts/).

## Identity and storage

- Hardware revision v2 (label and PCB).
- SoC RTL9303, CPU 800 MHz, LX 175 MHz, DDR 600 MHz, 512 MiB RAM (one 4 Gbit x16 DDR3 die, under the heatsink). Clock tree: [CLOCKS.md](CLOCKS.md).
  - OpenWrt reports `SoC Type: Realtek RTL9303 rev B`; `0xBB000004 = 0x93030001` = production part → SerDes construct list `a`, not `bT` ([UBOOT-REFERENCE.md](UBOOT-REFERENCE.md#chip-revision)).
- Flash: Winbond `EF4019`, 32 MiB SPI NOR, single chip. Mapped at `0xb4000000`-`0xb5ffffff`.
- U-Boot `2011.12.(3.6.6.55087)`, built 2022-01-19; toolchain Realtek MSDK-4.8.5p1 Build 2536.
- Saved env: `boardmodel=RTL9303_8XGE`, `bootcmd=boota`, `bootdelay=1`, `baudrate=115200`, `ipaddr=192.168.0.100`, `serverip=192.168.0.145`.
  - `ethaddr` is the Realtek OUI with placeholder NIC bytes (not a unique factory MAC). `printsys` → `Invalid system information`; no unique MAC location found.
- UART: 115200 8N1, U-Boot and stock Linux alike.
- SFP modules: no vendor lock found in SDK source, the loader, or the sibling `cli_server`. Fitted set below.
- Partition map: [stock-flash-layout.json](stock-flash-layout.json); `flshow` output: [../artifacts/uboot-flshow.txt](../artifacts/uboot-flshow.txt).
- Board photos: [photos/README.md](photos/README.md).

- **Current (owner, 2026-10-12): only one 10G SR left fitted, for management; the other modules are removed.** The table below is the 2026-10-10 full set (module inventory).

### Fitted SFP modules (2026-10-10, all 8 cages; our U-Boot `rtk sfp`)

| Cage | Module | Serial | Media |
|---|---|---|---|
| 1 | FS SFP-10GSR-85 | F2140097682 | 10GBASE-SR, DDM |
| 2 | FS SFP-10GSR-85 | F2140098879 | 10GBASE-SR, DDM |
| 3 | Cisco-Finisar GLC-T 8.0 | MTC106630 | 1000BASE-T |
| 4 | Cisco-Finisar GLC-SX-MM 6.0 | H33A663 | 1000BASE-SX |
| 5 | Cisco-NEO PTB3370553CN0CS1 | NDG20040529 | 1G 1310 nm SMF, DDM |
| 6 | FS SFP-10GSR-85 | F2031577643 | 10GBASE-SR, DDM |
| 7 | Cisco-Finisar GLC-T 8.0 | MTC106627 | 1000BASE-T |
| 8 | FS SFP-10GSR-85 | F2140097683 | 10GBASE-SR, DDM |

- All 8 pass both EEPROM checksums and declare power level 1 (≤ 1 W).
- GLC-T: no DDM, no TX-disable (laser bit has no effect), connector byte `0x07` (LC) is wrong for RJ45, made 2007-08-17, Marvell 88E1111 PHY at 0x56; EEPROM emulated by an MCU that stretches the clock → reads need 50 kHz and a few seconds after power-on.
- GLC-SX-MM: binary fields space-padded (bytes 3-19, 36-39, 64-65); `rtk sfp` zeroes them. Connector byte says "Fibre Channel Style 2 copper" (vendor error, reported as-is).
- PTB3370553: no compliance code (described from rate/wavelength/reach); vendor `rtk.ko` classes it "unknown media"; on 2026-10-12 it had RX signal, no link, symbol-error counter saturated ([SDS-TOOLS.md](SDS-TOOLS.md)).
- Cage 1 fibre = house LAN uplink. Cages 3 ↔ 7 copper cable removed 2026-10-11.
- DDM at the stock U-Boot prompt, lasers off (2026-10-10, `scripts/st1008_sfp_ddm.py`, #11):

| Cage | Temp °C | Vcc V | Bias mA | RX dBm |
|---|---|---|---|---|
| 1 | 33.4 | 3.335 | 0.002 | -2.36 |
| 2 | 33.0 | 3.322 | 0.002 | -2.46 |
| 8 | 28.7 | 3.317 | 0.002 | -2.15 |

  - TX power -40 dBm (off); status byte 110 = `0x80` (TX_DISABLE asserted); alarm byte 112 = `0x05` (bias low + TX power low).
  - SR modules: FS `SFP-10GSR-85`, 850 nm, 10.3 GBd, date code 211223, internal calibration.

## Network identity

- **No factory MAC.** Stock `printsys` → `Invalid system information`; stock env `ethaddr` was a Realtek-OUI placeholder (#36).
- **Base MAC `16:b0:46:e9:0d:c0`:** saved in `u-boot-env` `ethaddr` by the 2026-10-08 `sysupgrade`; locally administered (bit 1 of the first byte set) = randomly generated, not TP-Link assigned. Used by flash OpenWrt and our 7.3 kernel (nvmem layout on `u-boot-env`). Stock leaves the switch MAC registers at `00:e0:4c:00:00:00`.
- **Management address** (owner, 2026-10-12): DHCP client + static fallback `192.168.0.1/24`; house LAN reserves `192.168.25.48` (registry block `st1008f-1` = `.48`-`.55`). Today's flash OpenWrt: static `.48/24` on bridge `switch.1`, gateway/DNS `.254`. [DECISIONS.md](DECISIONS.md).
- **Lab hosts** (registry): host `enp7s0` TFTP server `192.168.25.30` (static NM entry + DHCP reservation); power relay `192.168.25.49` (DHCP-reserved; [Bench power relay](#bench-power-relay-84)).

## Bench power relay (#84)

- ESPHome node `office-bench-lights` (ESP8266, HA entity `Office Bench Lights relay`), `192.168.25.49`; switches the board's 12 V supply. No power metering.
- **A relay reboot leaves the board unpowered:** `restore_mode: RESTORE_DEFAULT_OFF` without `esp8266: restore_from_flash: true`.
- Seen 2026-10-12: relay OFF unprompted at 10:24:30+11:00 and between 10:26:58 and 10:27:42, each 25-60 s after a `dev.py` power-on (10:24:06, 10:26:40). ESPHome `sensor/uptime` read 64 s at ~10:29 = the relay itself had rebooted.
  - Not Home Assistant: no automation references the entity; `light.office_lights` does not include it.
  - Suspect: ESP8266 reset (brownout or EMI) when the relay switches the board load on. HA `sensor.office_bench_lights_reset_reason` would confirm; not yet read.
- Detection (`scripts/switch_power.py`): every on/off logs relay uptime before/after (`tmp/relay_uptime.json`); `check` flags a reboot (uptime < recorded + elapsed − 30 s), exit 3; `check --fix` powers on once if a reboot left it OFF. `ramload` (end) and `nic-bench boot` run it.
- Not done (config in the private awto-terminal repo, `hass/esphome/office-bench-lights.yaml`): `restore_from_flash: true` + `RESTORE_DEFAULT_ON`; snubber or separate ESP supply; entity rename.
- **Managed-switch convention** (applies when routing goes live):
  - one base MAC per box; management interface, ports and VLAN interfaces share it (base+1… only for extra MACs such as VRRP);
  - the ASIC holds an L2 entry for its own MAC pointing at the CPU port (frames to the switch trap to the CPU; broadcast/ARP copied);
  - one management IP on the management VLAN (VLAN 1 untagged); IPv6 by SLAAC;
  - routing mode: one SVI (L3 interface) per VLAN, all sharing one router MAC held in the RTL9303 router-MAC table; VRRP virtual MACs go in the same table (SDK hardware VRRP, [SDK-FEATURE-MAP.md](SDK-FEATURE-MAP.md));
  - firewall for ASIC-routed traffic = ACLs (#66).

## UART

- Header silkscreen `DH GND RX TX`. `DH` function unknown; leave it and adapter VCC disconnected.
- 3.3 V TTL. Adapter TX → board RX, adapter RX → board TX, common GND. No RS-232 levels, no 5 V TX.
- Max rate = LX / 16 = 10.9375 MBd (divisor 1). Every integer divisor passes byte-exact on stock U-Boot and ours (2026-10-10, #32); ours ~9 % slower in chars/s at the top rate. The datasheet and TP-Link manual give no UART clock or limit.
  - Host adapter PL2303 (`067b:2303`, clone) runs faster than its requested rate (request 5.13 M → 10.94 M actual); scripts sweep the host request per rate (`tmp/serial-cal.json`).
  - Above ~3.6 MBd chars/s fall below line rate (one-char-at-a-time output + USB adapter).
  - Long command lines drop characters (no flow control): scripts send in chunks, check the echo, then send CR (#31).
- Autoboot: `Hit Esc key to stop autoboot`, `bootdelay=1` → one ESC byte gives `RTL9300#`. Window is ~1 s; use the console daemon's auto-catch (`scripts/switch_console_daemon.py`).
- PL2303 adapter: `tio` drops it when stdin is not a terminal; pyserial (the daemon) holds it.

## Front-panel cage → SoC port → SerDes

From the OpenWrt v2 DTS (`SWITCH_PORT_SFP(p,l,s,c,g)` = SoC port, label, SerDes, LED set, cage); corroborated by the stock loader's packed hardware profile.

| Front cage | SoC/SDK port | SerDes | SFP I2C channel | MOD-DEF0 GPIO (active-low) | PCA9534 tx-disable pin |
| --- | --- | --- | --- | --- | --- |
| 1 | 0 | sds2 | i2c0 | gpio0 pin 0 | 0 |
| 2 | 8 | sds3 | i2c1 | gpio0 pin 1 | 1 |
| 3 | 16 | sds4 | i2c2 | gpio0 pin 2 | 2 |
| 4 | 20 | sds5 | i2c3 | gpio0 pin 3 | 3 |
| 5 | 24 | sds6 | i2c4 | gpio0 pin 4 | 4 |
| 6 | 25 | sds7 | i2c5 | gpio0 pin 5 | 5 |
| 7 | 26 | sds8 | i2c6 | gpio0 pin 6 | 6 |
| 8 | 27 | sds9 | i2c7 | gpio0 pin 7 | 7 |

- SoC port 28 (`port@1c`, phy-mode internal, fixed 1G) = internal CPU port, not a cage.
- All 8 cages are integrated RTL9303 10G SerDes (10GBASE-R); no external PHY (`phy_idx = HWP_NONE`).
- Cages 1/2 = SDK ports **0 and 8**, not 0 and 1. Stock Linux `port 0 media 5` / `port 1 media 5` messages use logical module indices, not SDK ports (one fewer line after removing the cage-2 module).
- Verified live: cage 1 and cage 2 each TFTP an image with only that laser lit.

### Cage presence pinmux (#29)

- MOD-DEF0 cages 4-8 = GPIO3-7 share pins with the switch-core SPI master. `SPI_CTRL1` `0xbb0003a0` muxes them:
  - bit 13 `GPIO_SPI_SEL` = GPIO3-5 (cages 4-6) as SCK/MISO/MOSI.
  - bit 11 `GPIO6_CSB1_SEL` = GPIO6 (cage 7) as CS1; bit 10 `GPIO7_CSB0_SEL` = GPIO7 (cage 8) as CS0.
- Stock `rtk network on` ("SPI Master init") writes `0x0000e000` (bit 13 + `CLK_DIV`): reads `0035e000` after it, `00340000` without it (reg-diff).
- Bit 13 set: GPIO3-5 read 0 = "present" on empty cages; Linux sfp then fails the EEPROM read (`-EIO`). Seen in RAM boots after stock network on (`ramload` flows).
- Nothing uses the switch-core SPI master on this board (#77). The pins are always GPIO in our code:
  - Our U-Boot clears bits 13/11/10 in `board_init` and in `rtk network on` (`rtk_presence_pins_gpio()`, `rtk.h`).
  - Linux DTS: `pinmux@1b0003a0` (`pinctrl-single`, nodes as OpenWrt `rtl930x.dtsi`), applied by `&gpio0` `pinctrl-0` (mainline DTS, OpenWrt 6.18 tree patch).
- OpenWrt's TL-ST1008F v2 DTS does not apply `pinmux_disable_spi0` (upstream fix: draft, not posted).

### Switch fabric

- One chip: the RTL9303 package holds the CPU (1× MIPS 34Kc, 800 MHz, 2 hardware threads → Linux shows 2 CPUs), the switch core, 8 SerDes, GPIO/I2C/SPI/LED/thermal blocks. No separate processor on the board. External: DDR3, SPI NOR, TCA9534A, 74HC164s.
- CPU ↔ switch core = internal CPU port (SDK port 28, `eth0` 1G-class under OpenWrt). Software routing tops out there (issue #15).
- All 8 SFP+ ports are switched by the RTL9303 L2/L3 ASIC (store-and-forward, line rate per port). Not a software bridge.
- The CPU only programs the ASIC (VLAN/STP/forwarding tables via SDK or DSA) and handles control-plane / CPU-port traffic.
- Managed vs unmanaged = which software programs the ASIC tables, not where switching happens.

### Port LEDs

- 3 LEDs per port, 24 total, via 3× 74HC164 shift registers (serial-LED output) — [svanheule.net](https://www.svanheule.net/switches/tl-st1008f).
- Driven by the RTL9303 hardware LED engine (`RTL930X_LED_GLB_CTRL` `0xCC00`; 3 LED sets), no CPU involvement.
- v2 DTS `led_set0`: set 0 = 1G/100M/10M, set 1 = 2.5G, set 2 = 10G, each LINK + ACT, active-high.
- Stock loader profile `RTL9303_8XGE` set 0 (what stock `rtk network on` programs): LED0 `0x0A01` = 10G link/act, LED1 `0x0A08` = 2.5G, LED2 `0x0BA0` = 1G/100M/10M. Selector bits: 0 = 10G, 1 = 5G, 3 = 2.5G, 5 = 1G, 7 = 100M, 8 = 10M, 9 = link, 11 = activity (#9).
- After stock `rtk network on`: `0xcc00` = `01452651`, cage LEDs in software mode (`SW_EN` `0xf`). Our `rtk network on` matches every register `0xcc00-0xccc8` (reg-diff, 0 diffs, 2026-10-11, #9). Register detail: [RTK-COMMANDS.md](RTK-COMMANDS.md#port-leds).
- ST5008F (managed sibling) uses other set-0 values and `0xCC00`; SDK env `ledModeInitSkip=1` keeps the bootloader's LED setup in Linux: [MANAGED-FEATURES.md](MANAGED-FEATURES.md).
- Activity is combined RX+TX (no directional indicator in the HW engine).

## SFP power

- **No per-cage limits.** Our DTS sets `maximum-power-milliwatt = <2000>` on all 8 cages (SFF-8472's top level; Linux treats anything ≥ 2.0 W as 2.0 W). #30.
  - Replaced OpenWrt's borrowed split (cages 1/8 = 2.9 W, 2/3/6/7 = 1.5 W, 4/5 = 2.0 W): a level-3 (2.0 W) module stayed in level 1 in cages 2/3/6/7, so behaviour depended on the cage.
  - Split origin: XikeStor's "≤ 2.9 W per port, ≤ 15.8 W total" for *their* SKS8300-8X (OpenWrt commit 0dc0b98295), copied unchanged across RTL9303 8×SFP+ DTS files. Nothing from TP-Link.
- **Board budget check instead (warn only, never blocks or disables a module).**
  - Budget default **15.0 W** (declared module power) = (24 W input (PSU 12 V 2 A) − 6 W board draw) × ~0.85 3.3 V regulator.
  - Measured by owner 2026-10-12 at the 12 V input: no SFPs fitted ≈ 0.5 A (≈ 6 W); each SFP with laser disabled adds ≈ 0.1 A (≈ 1.2 W input ≈ 1.0 W at the module).
  - Unknown: 3.3 V SFP rail(s) and regulator rating on this PCB; per-module draw with laser on / link up. #30.
  - Check 2026-10-12 (one 10G SR in cage 1): U-Boot `rtk sfp power` 1.0 W by 1 module, budget 15.0 W; Linux `power_total_mw` 1000, `power_cage_mw` `1000 0 0 0 0 0 0 0`.
  - No vendor precedent: the managed ST5008F firmware has no power-level (A0 byte 64) handling or budget (#30).
  - GLC-T (copper): declares level 1, no DDM (no A2 page), so nothing measurable; real 10GBASE-T modules draw 2.5-3 W and commonly still declare level 1.
- **Counted power per module** (same rules in U-Boot and Linux):
  - A0 byte 64: bit 5 → level 3 = 2.0 W; else bit 1 → level 2 = 1.5 W; else level 1 = 1.0 W. Linux `sfp.c` also gates these on byte 94 (SFF-8472 rev ≥ 10.2 / 11.4) and needs DDM (byte 92 bit 6) to switch levels; the count ignores those gates (a module may draw its declared level regardless).
  - Copper modules cannot declare > 2.0 W, so they are raised to a datasheet table (max of declared and table):

| Module (how detected) | Counted | Source |
|---|---|---|
| 1000BASE-T (byte 6 bit 3, or RJ45 `0x22` + rate < 2.5G) | 1.2 W | FS SFP-GE-T: 350 mA × 3.47 V |
| 2.5GBASE-T (byte 36 `0x1e`, or RJ45 + rate 2.5-9.9G) | 2.0 W | FS SFP-2.5G-T: "< 2 W" |
| 5G/10GBASE-T (byte 36 `0x16`/`0x1c`/`0x1d`, or RJ45 + rate ≥ 10G) | 3.0 W | FS SFP-10G-T-30: 3.0 W max |

  - Datasheets: [sources/README.md](../sources/README.md).
  - EEPROM unreadable = not inserted: 0 W, cage reported empty, in U-Boot and Linux (#29).
  - GLC-T declares level 1 and has connector byte `0x07` (not RJ45), so it is counted 1.2 W via byte 6.
- **U-Boot** (`rtk_sfppower.c`):
  - `rtk sfp power`: per cage counted W + source, then total vs budget.
  - `rtk network on` and `rtk port` print `rtk: SFP power X.X W declared by N modules, budget 15.0 W (env sfp_budget_mw)`.
  - Over budget: `rtk: WARNING: SFP declared total X.X W > budget 15.0 W (board input 24 W) (#30)` (fails `check-log` until reviewed).
  - Budget: env `sfp_budget_mw` (mW, default 15000).
- **Linux** (mode-switch driver, `openwrt/patches/300-06`; in our 7.3 kernel and the OpenWrt build):
  - Recomputed on every insert/remove (500 ms poll). Info line on every change of the total; `dev_warn` once on going over (`SFP declared total X.X W > budget 15.0 W (board input 24 W)`), info when back under.
  - sysfs on the `mode-switch` platform device: `power_total_mw`, `power_cage_mw` (8 values, cage 1 first, 0 = empty), `power_budget_mw` (rw, re-checks at once).
  - Module param `power_budget_mw` (built-in: `tplink_st1008f_mode.power_budget_mw=` on the kernel command line).
  - debugfs `st1008f-mode-switch/state`: total + per-port `power_mw` and source.

## Other GPIO / I2C

- SFP data I2C = `i2c_mst1`, SDA0-7 = GPIO9-16. SDK formula per SoC port: `scl_pin = 8 + 9*(port/4)`, `sda_pin = port/2`, `interface = 1-(port/4)`, 8-bit reg, random read. EEPROM `0x50`, DOM `0x51`.
  - Verified from stock U-Boot (after `rtk network on`): cage N = `rtk i2c init hw <id> 0 <N-1> 8 <0x50|0x51> 0 0` (7-bit addr, intf 0, sda = N-1). `0xa0` or intf 1 → `FAIL (-1)`.
  - DDM readable from U-Boot: `scripts/st1008_sfp_ddm.py` (issue #11).
- SFP power: [SFP power](#sfp-power).
- USB EHCI (`0xb8021000`, little-endian regs): readable at the U-Boot prompt without hanging; at reset: halted, CONFIGFLAG 0, PORTSC1 `0x2000` (port power off, no connect, companion-owned). Issue #5.
- TX-disable: expander @ `0x38` on an `i2c-gpio` bus, SCL GPIO22 / SDA GPIO23 (`delay-us = 2`). Pin N = cage N+1, **active-high**.
  - Part is a TI TCA9534A (svanheule.net); "PCA9534" in these docs = same register map. The `A` variant's base address `0x38` matches.
- 3-position mode switch M1/M2/M3 on gpio0 pins 17/18/19. OpenWrt v2 DTS: `gpio-keys` (`BTN_0/1/2`, EV_SW, active-low, 50 ms debounce); our mainline DTS: the mode-switch driver ("Linux driver (#64)" below). Stock behaviour: see "Mode switch (stock firmware)" below.
  - Read with raw `md.l 0xb800330c 1` (DAT), bits 17-19 (bank C bits 1-3). Not `rtk pinGet` before `rtk network on` (hangs the console).
- GPIO21: DTS external-watchdog toggle pin (1.2 s, always-running). Found static output-high at the U-Boot prompt; board does not reset. Low = board reset (stock `switch_reset()`). Unexplained as a watchdog: the managed ST5008F has no `<wtd>` board section and never uses GPIO21; TP-Link's watchdog support is generic (`insmod <wtd> enGpio= feedGpio=`, 500 ms feed) (#18).
- USB: RTL9303 has a USB 2.0 host (EHCI `0x18021000`, irq 28, 1 port); **not wired on this board** (issue #5, closed).
  - Chip: datasheet Rev 1.1-1 sec 6.10 — DM = ball F4, DP = G4, RREF J4 (12 kΩ to GND), AVDDH_USB 3.3 V, AVDDL_USB 1.1 V. Copy: `sources/README.md`.
  - Board photos (top and bottom): no USB connector or footprint, no D+/D- pads, no VBUS switch, no ESD array. Only headers: J14 UART (`DH GND RX TX`) and 5-pad JTAG on the bottom.
  - Live: PORTSC1 `0x2000` (PP=0, CCS=0, companion-owned); stock boot logs a root hub with nothing attached.
  - Firmware: stock initramfs has `ehci-hcd`, `usb-storage`, `usbtmc`, `r8152` (generic SDK kernel config); managed ST5008 rootfs carries a `USB_DEPLOYMENT` feature stub (config include only). No USB use found for this board.
  - OpenWrt realtek: no `ehci`/`usb` node in `rtl930x.dtsi` or any RTL9303 DTS; the only "usb" strings are the GPIO18 `usb_led` pinmux (reused as I2C SDA/mode switch on other boards).
  - Not tested: any rework to the BGA balls (F4/G4) — no pads, impractical.

## Bus devices (full scan, #77)

Read-only scan 2026-10-12 (`./dev.py bus-scan`, details: [BUS-SCAN.md](BUS-SCAN.md)). No device beyond those listed exists on any scanned bus.

- I2C MST1 SDA0-7 (cage N = SDA N-1), 0x08-0x77 at 100 + 50 kHz: only the fitted module.
  - 0x50 ID EEPROM (all cages); 0x51 DDM (SR/SX/PTB modules); 0x56 88E1111 PHY (GLC-T copper).
- Expander bus (bit-bang SCL GPIO22 / SDA GPIO23): only 0x38 TCA9534A. No temp sensor, RTC, EEPROM or PMIC.
- I2C MST2: not scanned (SCL1 = GPIO17 = mode switch); idle (CTRL2 `0x5003`).
- SPI-NOR controller: CS0 = W25Q256 (JEDEC `ef 40 19`); CS1 reads `ff`, nothing attached.
- Switch-core SPI master (`SPI_CTRL1` `0xbb0003a0` = `0035e000` after stock network on): GPIO3-5 muxed as SPI, no CS routed, idle; nothing attached. Our code muxes the pins back to GPIO ("Cage presence pinmux" above).
- MAC EEPROM autoload (`0xbb00c6e4..`): runs at every reset; STS NOEEPROM 0 / COMPL 1 / VALID_FAIL 1 → something answers (likely cage-1 SFP EEPROM on the shared SDA), content rejected, nothing loaded.
- I2C/SPI slave register interface (`0xbb000360-0368`): 0, unused.

## Mode switch (stock firmware)

Source: static RE of stock `rtk.ko` (TP-Link additions, `TP_CHKPATTERN` thread). Addresses = Ghidra VA of `rtk.ko` (ELF symbol value = VA - 0x14290). Issue #8.

### Behaviour by position

| Pattern | Pins 17/18/19 (1 = high) | Intended position (one-hot) | Stock behaviour |
|---|---|---|---|
| 1 | 0 / 1 / 1 | M1 grounds pin 17 | "1G mode": 1G modules up at 1G; 2.5G modules forced down to 1G (`media 2 for auto speed down`); 10G modules unaffected |
| 2 | 1 / 0 / 1 | M2 grounds pin 18 | split: SoC ports 0-3 (cages 1-4) as pattern 1, ports 4-7 (cages 5-8) as pattern 3 |
| 3 | anything else | M3 grounds pin 19 | "2.5G mode": 2.5G modules up at 2.5G; 1G modules left down (`will not set because of unmatched pattern`); 10G unaffected |

- Pattern decode (`custom_judge_pattern_mode`, `0x0020c240`): `(p17,p18,p19) == (0,1,1)` -> 1; `== (1,0,1)` -> 2; anything else -> 3. The decode is one-hot: each position grounds one pin.
- Measured live 2026-10-11 under flash OpenWrt (debugfs gpio, `./dev.py mode-watch`), full M1→M2→M3→M1 cycle: **M1 0/1/1 → pattern 1, M2 1/0/1 → pattern 2, M3 1/1/0 → pattern 3**. One-hot as designed; pin 17 works. The earlier "pin 17 low everywhere" record (M2 0/0/1, M3 0/1/0) was wrong.
- Not yet read at M2/M3 under our U-Boot (`rtk mode`).
- Global: `check_pattern_thread_func` stores one pattern, `sfpPatternSet` fans it out to the 8 per-port bytes at `0x00396838..3f`. Per-port values differ only in pattern 2.
- 10G modules (type 5) never consult the pattern. The switch only chooses 1G vs 2.5G for modules that SFP EEPROM-classify as 1G/2.5G.

### Decision chain

- `init_module` (`0x0020e8b0`) starts 3 kthreads: `TP_CHKMEDIA` (`check_media_thread_func` `0x0020b834`), `TP_CHKPATTERN` (`check_pattern_thread_func` `0x0020c490`), `TP_CHKELECP`.
- `check_pattern_thread_func` loop: `custom_get_pattern_mode` -> if first iteration (`DAT_003576f0` = 1 in .data) print `cur pattern = %d`, latch `DAT_00396840`, call `sfpPatternSet`.
- `custom_get_pattern_mode` (`0x0020c29c`): for each of `gpio_pin[] = {17,18,19}` (rodata `0x0022078c`): `osal_time_usleep(30000)` then `drv_generalCtrlGPIO_dataBit_get(0,0,pin,&v)` -> `rtl9300_gpio_dataBit_get` (`rtcore.ko` `0x00014550`) = raw read of `0xb800330c` bit n, no inversion.
- `sfpPatternSet` (`0x0020c394`): 1 -> all 8 bytes = 1; 3 -> all = 2; 2 -> bytes 0-3 = 1, 4-7 = 2; then sets `DAT_0039680c` = 1.
- `tpSfpSetType` (`0x0020b07c`, run by `TP_CHKMEDIA`) first spins `while (DAT_0039680c == 0) osal_time_sleep(1)`: no port is configured before the first pattern read.
- Per port, module class from SFP EEPROM (`tpSfpGetType` / `tpSfpGetTypeOnce`, `rtcore.ko` `0x000151bc` / `0x000157a4`): 2 = `1G fiber insert`, 3 = `2.5G fiber insert` (EEPROM byte 12 nominal bit rate 0x19..0x20 = 2.5-3.2 GBd), 5 = `10G fiber insert` (10G compliance bits in byte 3). Presence = MOD-DEF0 pins 0-7 (not 17-19).
- Pattern value p (per port) x class:
  - class 3, p = 1: `rtk_port_10gMedia_set(2)`, `phy_speed_set(2)`, nway force-link on, autoneg on (runs as 1G).
  - class 3, p != 1: `rtk_port_10gMedia_set(3)`, `rtk_port_phyForceModeAbility_set(5,1)`, nway off, autoneg off (2.5G forced).
  - class 2, p != 2: media 2, `phy_speed_set(2)`, autoneg on.
  - class 2, p = 2: port not configured (`unmatched pattern`).
  - class 5 and other: media = class, `phy_speed_set(7)`.
- Copper SFP-T modules (`tpSfpIsElec`) read the same per-port byte: p = 1 -> speed mask `0x04` / media 5, p = 2 -> mask `0x08` / media 2. Lower confidence (decompile only).

### Timing

- Read when: once at module init (first iteration latches), then polled every loop of `TP_CHKPATTERN`.
- Poll period ~1 s + 3 x 30 ms settle: `osal_time_sleep(1)` = `schedule_timeout(100)` (HZ = 100, 1 s).
- Debounce: none beyond the 30 ms settle before each pin read; a single changed sample counts.
- Between detents no pin is grounded: pins read 1/1/1 = pattern 3 (seen M1 → M2 under our 300-06 driver, 2026-10-11, #64). Stock would reset the switch on that transient.
- On change: prints `pattern changed switch reset`, drives gpio0 pin 21 low (`drv_generalCtrlGPIO_dataBit_set(0,0,0x15,0)`) = `switch_reset`; presumably reboots and re-latches the new pattern.
  - Pin 21 is the DTS "external watchdog" pin; the stock code calls the pin-21-low write `switch_reset` (`0x0020c374`). Effect on the board not observed live.
- A GPIO read error leaves the stack value stale (error path prints `gpio read failed ret=%d` and continues).

### Notes

- The `10G/2.5G/1G fiber insert` lines are EEPROM classification, not the switch. A 1G module logged as `10G fiber insert` under M1 means its EEPROM claimed 10G compliance bits; it is not evidence of a global mode.
- `gpioInit` (`0x0020c6dc`) is dead code (no caller).
- Stock U-Boot never reads pins 17-19.
- Stock decode separates all three positions (measured above). Pins 18/19 alone do too.

### Boot policy (our U-Boot, #46)

- Owner decision 2026-10-12 changes the meanings (implementation in progress, #73): M1 = switch mode (bridge + STP), M2 = isolated management, M3 = recovery image with isolated management. The text below is the current build. [DECISIONS.md](DECISIONS.md).

- `board_late_init` reads DAT bits 17-19 twice, 30 ms apart (stock settle), decodes pins 18/19 only: 1/1 = M1, 0/1 = M2, 1/0 = M3. Both low or the two reads differ = invalid -> M1.
- Prints `Mode:  Mx <name>, pins 17/18/19 = a/b/c` (names: M1 `switch`, M2 `isolated`, M3 `recovery`); sets env `boot_mode=Mx`, `bootcmd_m1=clocks fast; bootm 0xb4300000`.
- Chainloaded from flash (marker `0xa5a51008` @ `0xa0f80000`, cleared on read): `bootsel` picks the image and passes `st1008f.mode=mN` in `bootargs` (#73, [DEFAULT-BOOT.md](DEFAULT-BOOT.md) "Boot selection", "Modes").
  - M1 / M2 / invalid: primary (with fallback), `bootdelay=1`. Linux: M1 = switch, M2 = isolated management.
  - M3: recovery image (isolated management); no recovery image yet → prompt.
- RAM-loaded (no marker): prompt at every position, `boot_mode` still set.
- Live check: `rtk mode` (stock pattern + `boot policy:` line). Mapping/verify: `./dev.py mode-map live | boot --expect Mx`.
- Unattended power-up reaches OpenWrt at every position once `recovery` holds an image; until then M3 stops at the prompt.

### Linux driver (#64)

- `openwrt/patches/300-06-realtek-rtl930x-tplink-mode-switch.patch`: platform driver `tplink,st1008f-mode-switch` (`CONFIG_TPLINK_ST1008F_MODE_SWITCH`), port of the stock flow above; vendor decode incl. pin 17, not the 18/19 boot-policy decode.
- DT node `mode-switch` (mainline DTS): `gpios` = pins 17/18/19 `GPIO_ACTIVE_HIGH` (raw, like stock), `port@N { sfp = <&sfpN>; }`. Replaces the gpio-keys M1/M2/M3 node (same pins, one owner).
- Per-port action via `set_link_ksettings` on the netdev whose `sfp_bus` is the cage's: media 2 = 1000BASE-X AN on, media 3 = 2500BASE-X AN off, unmatched = admin down; 10G/DAC/unknown untouched; modules with a PHY untouched.
- Pattern change: logs `pattern changed`, re-reads every module under the new pattern. No GPIO21 write.
- Presence = I2C probe of EEPROM 0x50 (not MOD-DEF0); removal after 2 failed probes. 0x50 answers but the ID read fails = empty (0 W, no media decision), retried each pass, logged once (#29).
- State: `/sys/kernel/debug/st1008f-mode-switch/state`. Mainline (no DSA ports): decisions only, `no netdev on this cage`.

## Thermal

- Stock U-Boot / stock Linux: no thermal handling at all; the meter is never enabled. Passive cooling, no fan; PT7A7514 is a voltage supervisor only. Details: issue #13.
- OpenWrt 25.12.4: `CONFIG_REALTEK_THERMAL=y` + `CONFIG_THERMAL_HWMON=y` → `/sys/class/thermal/thermal_zone*/temp`, hwmon (`sensors`). SoC `cpu-thermal` zone (`rtl930x.dtsi`): critical 105 °C, `THERMAL_EMERGENCY_POWEROFF_DELAY_MS=0` → emergency power-off (a halt on this board). Board DTS adds `sfp-thermal` (8 module sensors, critical 110 °C).
- On-die meter (switch-SDK `swcore_rtl9300.h` layout; the U-Boot-header addresses are 8 bytes off):
  - **Off at power-on**: `CTRL_2.TM_ENABLE` (`0xBB000068` bit 16) = 0; `RESULT_0` holds a reset value with `TEMP_VALID` clear. Do not read it as a temperature.
  - Enable (as OpenWrt's `rtl9300_thermal_init`): `CTRL_1` (`0xBB000064`) bits 31:16 `SAMPLE_DLY` = `0x0800`; `CTRL_2` bit 16 = 1. RMW; no flash involved.
  - Read `RESULT_0` (`0xBB00006C`): `TEMP_VALID` = bit 24, `TEMP_OUT` = bits 23:16. `RESULT_1` (`0x70`): `TEMP_MAX` 14:8, `TEMP_MIN` 6:0, latched since enable.
  - **Conversion unsettled (#13):** OpenWrt (`coefficients = <1000 0>`), `rtk temp` and the readings below take `TEMP_OUT` as °C. Realtek SDK 3.6.9 `dal_longan_switch_thermalTemp_get` (ST5008F `core`): `TM_ENABLE` = 1, 10 ms, `TEMP_OUT × 129 − 1000` (/100) → **°C = 1.29 × TEMP_OUT − 10**. By that formula raw 73 = 84.2 °C, and OpenWrt's 105 °C trip fires at ~125 °C real. Needs an external probe at two temperatures.
  - No vendor over-temperature handling in either firmware (diag CLI only).
  - U-Boot one-liner (RMW values from a stock boot): `mw.l 0xBB000064 0x08000007; mw.l 0xBB000068 0x00034cd7; md.l 0xBB00006C 2`.
- 2026-10-08, heatsink off, idle at U-Boot after `rtk network on`, one laser on, ~7 min after power-on: **73 °C** steady (3 reads); min/max since enable 55/73. Not yet checked against an external probe.

## SFP lasers are OFF in stock U-Boot (root cause of "no 10G in U-Boot")

- PCA9534 power-on: all pins input (reg3 = `0xff`) → tx-disable pulled high → all 8 lasers off.
- U-Boot never drives it. Its `SFP insert init` stage (`FUN_83f212b8`) only configures GPIO0-7 (MOD-DEF0) as inputs. The EEPROM/media/`tx dis set` strings in the loader are unreferenced (Linux-only code).
- No TP-Link laser command exists in the loader; none is needed.
- Lasers off looks like: switch RX sees far-end light (sds2 page5 reg0 = `0x100D`), far end sees nothing; MIB TX = 0; `tftpboot` → `Loading: *T T` timeouts.

### Method A (use this): native `rtk i2c` device 8

```
rtk network on                 # first: registers I2C devices 0-8 (dev 0-7 = SFP EEPROMs, dev 8 = PCA9534)
rtk i2c write 8 1 0xfe         # output reg; bit N=1 keeps cage N+1 laser off; 0xfe = cage 1 only
rtk i2c write 8 3 0            # config reg: all pins output
rtk i2c read 8 1               # readback
```

- PCA9534 regs: 0 input, 1 output, 2 polarity, 3 config (1 = input). Power-on `0xff/0xff/0x00/0xff`.
- `rtk i2c read 0 0` / `read 1 0` = `0x3` (real SFP EEPROM byte 0). `rtk i2c read 9 1` → `FAIL (61455)` (`0xf00f`, no device 9).
- `rtk i2c init sw 5 0 22 0 23 8 0x38 1 0 0` + device 5 also works; device 8 makes it unnecessary.
- PCA9534 state survives warm `reset`, not a power cycle.
- Env macro (`setenv` has a 16-arg limit, so split): `setenv laser1 rtk i2c write 8 1 0xfe`; `setenv laser2 rtk i2c write 8 3 0`; `setenv laser run laser1 laser2`; `run laser`. Not saved (`saveenv` = flash write).

### Method B: GPIO bit-bang with `md.l`/`mw.l`

- Pure MMIO, works with no SDK init. Script: [../scripts/st1008_pca9534.py](../scripts/st1008_pca9534.py) (`probe|read|enable-tx --out 0xNN`, ~40 s per enable, ACK-checked).
- RTL9300 GPIO block `0xb8003300` (OpenWrt `gpio0`, `ranges 0x18000000`): `+0x00` pin enable (`0x00ffffff`), `+0x08` DIR (1 = out), `+0x0C` DAT, `+0x10` ISR, `+0x14/+0x18` IMR A/B, C/D, `+0x38` IER. Bit n = GPIO n.
- Live at prompt: DIR `0x00e00000` (GPIO21/22/23 out), DAT `0x00ec00c4` (21/22/23 high; bits 0/1 low = cages 1/2 present; bit 17 low = mode switch M1). Keep GPIO21 out+high in every write.
- Open-drain emulation (board pull-ups): line low = DIR bit set with DAT bit 0; line high = DIR bit clear. Clear DAT bits 22/23 once; then each edge is one DIR write: both released `0x00200000`, SDA low `0x00a00000`, SCL low `0x00600000`, both low `0x00e00000`. Sample SDA = `md.l 0xb800330c 1` bit 23.
- I2C framing: START = SDA low, SCL low; bit = set SDA, SCL high, SCL low; ACK = release SDA, SCL high, sample, SCL low; STOP = SDA low, SCL high, SDA high. Write `0x70`, reg, data. Up to 6 `mw.l` per U-Boot line (joined by `;`) worked.
- Writing reg1 = `0x00`, reg3 = `0x00` lights all 8 lasers (cage-loop hazard below).

## Link and traffic checks

- **Use MIB counters.** `md.l 0xBB000700 8` (port 0), `md.l 0xBB000F00 8` (port 8). General formula (OpenWrt `stats.c`): `addr = 0x0664 + (port+1)*256 - 4 - offset`, base `0xBB000000`. Port 0: TX ucast `0xBB000708`, RX ucast `0xBB00070C`, TX mcast `0xBB000710`, TX bcast `0xBB000718`.
- `rtk sdsreg get 0 <sds> 1 30` (block-lock, low 9 bits `0x1ff`) is **not** a usable link indicator here: it read `0x0000`/`0x0100` while millions of frames flowed.
- `MAC_LINK_STS` `0xBB00CB10` reflects force-mode bits, not real link.
- RX light: `rtk sdsreg get 0 <sds> 5 0`, bit `0x1000` set = signal detect (lit `0x100D`, dark `0x000C`).
- Our U-Boot `rtk port` / `rtk sds status`: PCS link (10GR block lock, 1G BMSR), MAC link + speed (`0xcb18`). Cage 1 on the house fibre reads `pcs up, mac up 10G` after our `rtk network on` (2026-10-11, #51).
- SerDes mode for SGMII / 100BX / 1000BX / 2500BX / 10GBASE-R is forced inside the SerDes: page `0x1f` (WDIG) reg 9, `FRC_SDS_MD_ON` bit 6, mode bits 11:7. The MAC-side `SDS_MODE_SEL` (`0x194/0x2a0/0x2a4/0x198`) then stays `0x1f` ("off"); only XSGMII/USXGMII/QSGMII are MAC-driven. All 8 cages read `0x1a` (10GBASE-R) after stock `rtk network on` (2026-10-11, #42).
- Open (#44): with the stock network on and cage 1 lit, `MAC_LINK_STS 0xcb10` showed cage 2 "mac up" (laser off) and cage 1 "mac down" (2026-10-10/11).

## Hazards

- **Cage loop.** Cages 1 and 2 both cabled to the same LAN switch + both lasers on + `rtk network on` → the U-Boot SDK forwards front↔front → broadcast storm (TX mcast 39M in ~1 min). Break with `rtk port disable 8`. Light one cage only. OpenWrt initramfs lights all lasers and bridges all ports with no STP → unplug the second fiber before `bootm`.
  - OpenWrt 25.12.4 default config (bridge `switch`, lan1-8, no STP), cages 1/2/8 to one LAN switch, 2026-10-10: host bcast+mcast 5 → 13,354 pps ~80 s after forwarding (slow ramp); at 253 s `rtl838x-eth eth0: Ring contention` ×3, then the switch hangs (#19).
  - Bridge STP from first boot (set before netifd) blocks it: lan2 → blocking 1.5 s after up (own BPDU looped via lan1); bridge is root, the house switch sends no BPDUs; 10 min at 2-8 pps, 0 `Ring contention` (#19).
  - Flash OpenWrt (STP saved) at power-up, 2026-10-11: lan2 listening 28.7 s → blocking 30.1 s, lan1 forwarding 44.0 s; no port forwarded before STP decided; steady state lan2 blocking (#43).
  - Managed ST5008F firmware turns a port's laser off on admin-down and all lasers off before reboot; OpenWrt and ours do neither ([MANAGED-FEATURES.md](MANAGED-FEATURES.md), #19).
- **GPIO/I2C before SDK init hangs the console.** `rtk pinGet`, `rtk i2c init sw`, `rtk i2c read` wedge U-Boot (power cycle needed) only if run before `rtk network on`. After it they work. Same for `rtk comboport copper|fiber` (#34).
- **`rtk network on` twice in one boot is unreliable.** One second run returned `0xf030` and then the console went dead (power cycle); another second run returned normally. Run it once per boot.
- `rtk 10g <port> <media>` before `rtk network on` → `0xf002` (unit not initialised).
- `rtk network on` always ends `Err:0xf030:FAIL (0xf030)`: `phy_enable_set` returns `RT_ERR_PORT_NOT_SUPPORTED` for every PHY-less port; the loop ignores it. Benign.
- `rtk boardid <id>`, `rtk boardmodel <str>`, `rtk comboport` are setters, not queries.
- Flash-writing commands: `saveenv`, `savesys`, `setsys`, `upgrade *`, `*force`, `flerase`, `sf write/erase/update`, `erase`. Never used here.
- Old `rtk i2c init sw 0 0 8 0 0 ...` "SFP EEPROM reads = 0x0" bit-banged GPIO8/GPIO0 (MOD-DEF0) — wrong pins. Use devices 0-7.

## Prior art

- NicGiga S100-0800S-M (same `RTL9303_8XGE`, DTS derived from the ST1008F v2): OpenWrt install RAM-boots via plain `tftpboot`/`bootm` from vendor U-Boot. This unit needs `rtk network on` first (bare `tftpboot` resets the board: `No ethernet found`) and the laser enable.
- olliver's `realtek_sdk` (GitLab) builds this U-Boot family in Docker and has a `tplink_maple` branch (TP-Link ST-series).
