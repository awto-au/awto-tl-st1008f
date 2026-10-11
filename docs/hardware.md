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
- SFP modules tested: two 10GBASE-SR (OpenWrt reads both as FS `SFP-10GSR-85`). No SFP vendor lock found in SDK source, the loader, or the sibling `cli_server`.
- Partition map: [stock-flash-layout.json](stock-flash-layout.json); `flshow` output: [../artifacts/uboot-flshow.txt](../artifacts/uboot-flshow.txt).
- Board photos: [photos/README.md](photos/README.md).

## UART

- Header silkscreen `DH GND RX TX`. `DH` function unknown; leave it and adapter VCC disconnected.
- 3.3 V TTL. Adapter TX → board RX, adapter RX → board TX, common GND. No RS-232 levels, no 5 V TX.
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
- Activity is combined RX+TX (no directional indicator in the HW engine). Richer scheme: issue "per-port LEDs".

## Other GPIO / I2C

- SFP data I2C = `i2c_mst1`, SDA0-7 = GPIO9-16. SDK formula per SoC port: `scl_pin = 8 + 9*(port/4)`, `sda_pin = port/2`, `interface = 1-(port/4)`, 8-bit reg, random read. EEPROM `0x50`, DOM `0x51`.
  - Verified from stock U-Boot (after `rtk network on`): cage N = `rtk i2c init hw <id> 0 <N-1> 8 <0x50|0x51> 0 0` (7-bit addr, intf 0, sda = N-1). `0xa0` or intf 1 → `FAIL (-1)`.
  - DDM readable from U-Boot: `scripts/st1008_sfp_ddm.py` (issue #11).
- Per-cage `maximum-power-milliwatt` in the OpenWrt DTS (logged `sfp sfp-pN: Host maximum power`): cages 1/8 = 2.9 W, 2/3/6/7 = 1.5 W, 4/5 = 2.0 W. **Not a measured property of this board.**
  - Origin: XikeStor told users of *their* SKS8300-8X "≤2.9 W per port, ≤15.8 W total" (OpenWrt commit 0dc0b98295). The per-cage split sums to 15.8 W but no source gives a reason for which cage gets what; it is copied unchanged across RTL9303 8×SFP+ DTS files (XikeStor SKS8300/8310, Vimin, NicGiga, SiriVision, TP-Link). Nothing from TP-Link.
  - Linux effect is small: `sfp.c` only knows SFF-8472 levels 1.0 / 1.5 / 2.0 W (`sfp_module_parse_power`); host max only decides whether a module declaring 1.5 or 2.0 W may leave power level 1. 2.9 W ≡ 2.0 W. Only the 1.5 W cages (2/3/6/7) differ: a level-3 (2.0 W) module stays in level 1 there.
  - Modules drawing >2 W (10GBASE-T copper) cannot declare it in SFF-8472; the DTS numbers do not protect anything for them.
  - Real limit unknown: 3.3 V SFP rail(s) and their regulator rating on this PCB, against the 12 V 2 A (24 W) input. Treat per-cage values as unverified until the rail is identified.
  - USB EHCI (`0xb8021000`, little-endian regs): readable at the U-Boot prompt without hanging; at reset: halted, CONFIGFLAG 0, PORTSC1 `0x2000` (port power off, no connect, companion-owned). Issue #5.
- TX-disable: expander @ `0x38` on an `i2c-gpio` bus, SCL GPIO22 / SDA GPIO23 (`delay-us = 2`). Pin N = cage N+1, **active-high**.
  - Part is a TI TCA9534A (svanheule.net); "PCA9534" in these docs = same register map. The `A` variant's base address `0x38` matches.
- 3-position mode switch M1/M2/M3 = `gpio-keys` on gpio0 pins 17/18/19 (`BTN_0/1/2`, EV_SW, active-low, 50 ms debounce) per the OpenWrt v2 DTS. Stock behaviour: see "Mode switch (stock firmware)" below.
  - Read with raw `md.l 0xb800330c 1` (DAT), bits 17-19 (bank C bits 1-3). Not `rtk pinGet` before `rtk network on` (hangs the console).
- GPIO21: DTS external-watchdog toggle pin (1.2 s, always-running). Found static output-high at the U-Boot prompt; board does not reset. Unexplained.
- USB: RTL9303 has a USB 2.0 host (EHCI `0x18021000`, irq 28, 1 port); **not wired on this board** (issue #5, closed).
  - Chip: datasheet Rev 1.1-1 sec 6.10 — DM = ball F4, DP = G4, RREF J4 (12 kΩ to GND), AVDDH_USB 3.3 V, AVDDL_USB 1.1 V. Copy: `sources/README.md`.
  - Board photos (top and bottom): no USB connector or footprint, no D+/D- pads, no VBUS switch, no ESD array. Only headers: J14 UART (`DH GND RX TX`) and 5-pad JTAG on the bottom.
  - Live: PORTSC1 `0x2000` (PP=0, CCS=0, companion-owned); stock boot logs a root hub with nothing attached.
  - Firmware: stock initramfs has `ehci-hcd`, `usb-storage`, `usbtmc`, `r8152` (generic SDK kernel config); managed ST5008 rootfs carries a `USB_DEPLOYMENT` feature stub (config include only). No USB use found for this board.
  - OpenWrt realtek: no `ehci`/`usb` node in `rtl930x.dtsi` or any RTL9303 DTS; the only "usb" strings are the GPIO18 `usb_led` pinmux (reused as I2C SDA/mode switch on other boards).
  - Not tested: any rework to the BGA balls (F4/G4) — no pads, impractical.

## Mode switch (stock firmware)

Source: static RE of stock `rtk.ko` (TP-Link additions, `TP_CHKPATTERN` thread). Addresses = Ghidra VA of `rtk.ko` (ELF symbol value = VA - 0x14290). Issue #8.

### Behaviour by position

| Pattern | Pins 17/18/19 (1 = high) | Intended position (one-hot) | Stock behaviour |
|---|---|---|---|
| 1 | 0 / 1 / 1 | M1 grounds pin 17 | "1G mode": 1G modules up at 1G; 2.5G modules forced down to 1G (`media 2 for auto speed down`); 10G modules unaffected |
| 2 | 1 / 0 / 1 | M2 grounds pin 18 | split: SoC ports 0-3 (cages 1-4) as pattern 1, ports 4-7 (cages 5-8) as pattern 3 |
| 3 | anything else | M3 grounds pin 19 | "2.5G mode": 2.5G modules up at 2.5G; 1G modules left down (`will not set because of unmatched pattern`); 10G unaffected |

- Pattern decode (`custom_judge_pattern_mode`, `0x0020c240`): `(p17,p18,p19) == (0,1,1)` -> 1; `== (1,0,1)` -> 2; anything else -> 3. The decode is one-hot: each position grounds one pin.
- Live reads (U-Boot `md.l`, OpenWrt debugfs) show pin 17 low in all three positions: M1 0/1/1, M2 0/0/1, M3 0/1/0. Taken at face value M2 would fall through to pattern 3; that conflicts with the one-hot design, so the pin-17 read is suspect, not the firmware.
- Open: pin 17's pinmux/pull state in U-Boot and OpenWrt vs what stock Linux sets before reading. Verify by reading pin 17 at M2/M3 after configuring it as a pulled-up GPIO input, or under stock firmware.
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
- On change: prints `pattern changed switch reset`, drives gpio0 pin 21 low (`drv_generalCtrlGPIO_dataBit_set(0,0,0x15,0)`) = `switch_reset`; presumably reboots and re-latches the new pattern.
  - Pin 21 is the DTS "external watchdog" pin; the stock code calls the pin-21-low write `switch_reset` (`0x0020c374`). Effect on the board not observed live.
- A GPIO read error leaves the stack value stale (error path prints `gpio read failed ret=%d` and continues).

### Notes

- The `10G/2.5G/1G fiber insert` lines are EEPROM classification, not the switch. A 1G module logged as `10G fiber insert` under M1 means its EEPROM claimed 10G compliance bits; it is not evidence of a global mode.
- `gpioInit` (`0x0020c6dc`) is dead code (no caller).
- Stock U-Boot never reads pins 17-19.
- Stock decode with pin 17 always low separates only M1 vs not-M1. Pins 18/19 alone separate all three positions (measured reads above).

### Boot policy (our U-Boot, #46)

- `board_late_init` reads DAT bits 17-19 twice, 30 ms apart (stock settle), decodes pins 18/19 only: 1/1 = M1, 0/1 = M2, 1/0 = M3. Both low or the two reads differ = invalid -> M1.
- Prints `Mode:  Mx <name>, pins 17/18/19 = a/b/c`; sets env `boot_mode=Mx`, `bootcmd_m1=clocks fast; bootm 0xb4300000`.
- Chainloaded from flash (marker `0xa5a51008` @ `0xa0f80000`, cleared on read):
  - M1 / invalid: `bootcmd` = `bootcmd_m1`, `bootdelay=1` (unchanged from before #46).
  - M2 / M3: no autoboot, stays at the prompt; prints `needs Ethernet (stage 4, #46)`. `run bootcmd_m1` boots flash OpenWrt. DHCP/netconsole (M2) and TFTP recovery (M3) wait for stage-4 Ethernet.
- RAM-loaded (no marker): prompt at every position, `boot_mode` still set.
- Live check: `rtk mode` (stock pattern + `boot policy:` line). Mapping/verify: `./dev.py mode-map live | boot --expect Mx`.
- The switch must sit at M1 for unattended power-up to reach OpenWrt.

## Thermal

- Stock U-Boot / stock Linux: no thermal handling at all; the meter is never enabled. Passive cooling, no fan; PT7A7514 is a voltage supervisor only. Details: issue #13.
- OpenWrt 25.12.4: `CONFIG_REALTEK_THERMAL=y` + `CONFIG_THERMAL_HWMON=y` → `/sys/class/thermal/thermal_zone*/temp`, hwmon (`sensors`). SoC `cpu-thermal` zone (`rtl930x.dtsi`): critical 105 °C, `THERMAL_EMERGENCY_POWEROFF_DELAY_MS=0` → emergency power-off (a halt on this board). Board DTS adds `sfp-thermal` (8 module sensors, critical 110 °C).
- On-die meter (switch-SDK `swcore_rtl9300.h` layout; the U-Boot-header addresses are 8 bytes off):
  - **Off at power-on**: `CTRL_2.TM_ENABLE` (`0xBB000068` bit 16) = 0; `RESULT_0` holds a reset value with `TEMP_VALID` clear. Do not read it as a temperature.
  - Enable (as OpenWrt's `rtl9300_thermal_init`): `CTRL_1` (`0xBB000064`) bits 31:16 `SAMPLE_DLY` = `0x0800`; `CTRL_2` bit 16 = 1. RMW; no flash involved.
  - Read `RESULT_0` (`0xBB00006C`): `TEMP_VALID` = bit 24, `TEMP_OUT` = bits 23:16 = °C (OpenWrt `coefficients = <1000 0>`). `RESULT_1` (`0x70`): `TEMP_MAX` 14:8, `TEMP_MIN` 6:0, latched since enable.
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

## Hazards

- **Cage loop.** Cages 1 and 2 both cabled to the same LAN switch + both lasers on + `rtk network on` → the U-Boot SDK forwards front↔front → broadcast storm (TX mcast 39M in ~1 min). Break with `rtk port disable 8`. Light one cage only. OpenWrt initramfs lights all lasers and bridges all ports with no STP → unplug the second fiber before `bootm`.
- **GPIO/I2C before SDK init hangs the console.** `rtk pinGet`, `rtk i2c init sw`, `rtk i2c read` wedge U-Boot (power cycle needed) only if run before `rtk network on`. After it they work.
- **`rtk network on` twice in one boot is unreliable.** One second run returned `0xf030` and then the console went dead (power cycle); another second run returned normally. Run it once per boot.
- `rtk 10g <port> <media>` before `rtk network on` → `0xf002` (unit not initialised).
- `rtk network on` always ends `Err:0xf030:FAIL (0xf030)`: `phy_enable_set` returns `RT_ERR_PORT_NOT_SUPPORTED` for every PHY-less port; the loop ignores it. Benign.
- `rtk boardid <id>`, `rtk boardmodel <str>`, `rtk comboport` are setters, not queries.
- Flash-writing commands: `saveenv`, `savesys`, `setsys`, `upgrade *`, `*force`, `flerase`, `sf write/erase/update`, `erase`. Never used here.
- Old `rtk i2c init sw 0 0 8 0 0 ...` "SFP EEPROM reads = 0x0" bit-banged GPIO8/GPIO0 (MOD-DEF0) — wrong pins. Use devices 0-7.

## Prior art

- NicGiga S100-0800S-M (same `RTL9303_8XGE`, DTS derived from the ST1008F v2): OpenWrt install RAM-boots via plain `tftpboot`/`bootm` from vendor U-Boot. This unit needs `rtk network on` first (bare `tftpboot` resets the board: `No ethernet found`) and the laser enable.
- olliver's `realtek_sdk` (GitLab) builds this U-Boot family in Docker and has a `tplink_maple` branch (TP-Link ST-series).
