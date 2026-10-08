# TL-ST1008F v2 hardware

Narrative & dead ends: see [HISTORY.md](HISTORY.md). Evidence paths under `private/` are local-only (gitignored); public excerpts are in [../artifacts/](../artifacts/).

## Identity and storage

- Hardware revision v2 (label and PCB).
- SoC RTL9303, CPU 800 MHz, LX 175 MHz, DDR 600 MHz, 512 MiB RAM.
  - OpenWrt reports `SoC Type: Realtek RTL9303 rev B` → SerDes tables are the `bT` variant ([UBOOT-REFERENCE.md](UBOOT-REFERENCE.md) §4).
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

- All 8 SFP+ ports are switched by the RTL9303 L2/L3 ASIC (store-and-forward, line rate per port). Not a software bridge.
- The CPU (embedded MIPS, 800 MHz) only programs the ASIC (VLAN/STP/forwarding tables via SDK or DSA) and handles control-plane / CPU-port traffic.
- Managed vs unmanaged = which software programs the ASIC tables, not where switching happens.

### Port LEDs

- 3 LEDs per port, 24 total, via 3× 74HC164 shift registers (serial-LED output) — [svanheule.net](https://www.svanheule.net/switches/tl-st1008f).
- Driven by the RTL9303 hardware LED engine (`RTL930X_LED_GLB_CTRL` `0xCC00`; 3 LED sets), no CPU involvement.
- v2 DTS `led_set0`: set 0 = 1G/100M/10M, set 1 = 2.5G, set 2 = 10G, each LINK + ACT, active-high.
- Activity is combined RX+TX (no directional indicator in the HW engine). Richer scheme: issue "per-port LEDs".

## Other GPIO / I2C

- SFP data I2C = `i2c_mst1`, SDA0-7 = GPIO9-16. SDK formula per SoC port: `scl_pin = 8 + 9*(port/4)`, `sda_pin = port/2`, `interface = 1-(port/4)`, 8-bit reg, random read. EEPROM `0x50`, DOM `0x51`.
- TX-disable: expander @ `0x38` on an `i2c-gpio` bus, SCL GPIO22 / SDA GPIO23 (`delay-us = 2`). Pin N = cage N+1, **active-high**.
  - Part is a TI TCA9534A (svanheule.net); "PCA9534" in these docs = same register map. The `A` variant's base address `0x38` matches.
- 3-position mode switch M1/M2/M3 = `gpio-keys` on gpio0 pins 17/18/19 (`BTN_0/1/2`, EV_SW, active-low, 50 ms debounce) per the OpenWrt v2 DTS.
  - GPIO input only. Stock Linux (`rtcore.ko` SFP-insert handler) reads it and sets the SerDes media mode for the cages (`10G fiber insert` / `2.5G fiber insert`, then `rtk.ko` `media`/`sdsMode`). svanheule.net: one position = 2.5 Gbps. Stock U-Boot ignores it.
  - Appears global: with M1 asserted a 1G module was also set up as 10G fiber. Position → mode not mapped (issue: mode switch).
  - Read with raw `md.l 0xb800330c 1` (DAT), bits 17-19 (bank C bits 1-3). Not `rtk pinGet` before `rtk network on` (hangs the console).
  - One read at the prompt: bit 17 low (M1 asserted). Position → behaviour not mapped yet (issue: mode switch).
- GPIO21: DTS external-watchdog toggle pin (1.2 s, always-running). Found static output-high at the U-Boot prompt; board does not reset. Unexplained.
- USB: on-chip EHCI host, 1 root-hub port (`io mem 0x18021000`, irq 28). No external connector; likely pads/header. U-Boot has no USB commands.

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
