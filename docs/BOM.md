# TL-ST1008F v2 component list (from photos)

Every part identifiable on the board photos: refdes, marking, part, function, evidence. Issue #87. Board facts: [hardware.md](hardware.md); SoC blocks: [HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md); bus scan: [BUS-SCAN.md](BUS-SCAN.md).

Evidence tags:
- **[TOP] / [BOT]**: [photos/tl-st1008f-v2-board-top.jpg](photos/tl-st1008f-v2-board-top.jpg), `-bottom.jpg` (svanheule.net unit, heatsink on).
- **[SVH-nnn]**: svanheule.net close-up `2016_0101_*_nnn.jpg` (`sources/photos-svanheule/`, local); downscaled copies in [photos/](photos/README.md).
- **[OWN name]**: owner photos of this unit, 2026-10-08 / 2026-10-11, heatsink off (`docs/photos/Photos-1-001.zip`, local, not committed).
- **[V1]**: svanheule.net de-heatsinked V1 board (`sources/photos-svanheule/svanheule-v1-deheatsinked.png`, local).
- **[REF]**: Realtek RTL9302D reference sheet `sources/rtl9302d-reference-schematic-anoatech.pdf`.

Confidence: **H** = marking read and matches the vendor marking code; **M** = marking partly read or part named by svanheule.net; **L** = inferred from layout / silkscreen only.

Two units seen (owner, svanheule.net): same PCB, different second-source parts (U7, DRAM date codes, capacitor brands).

## Summary

| Refdes | Part | Function | Conf. |
|---|---|---|---|
| (under HS1) | Realtek RTL9303 | SoC + 8x 10G switch | H |
| (under HS1) | Zentel A3T4GF40BBF-HP | DDR3 4 Gbit x16 | H |
| U11 | Winbond W25Q256JVFIQ | 32 MiB SPI NOR | H |
| U108 | TI TPS568230 | buck, 1.1 V core | H |
| U107 | TI TPS568230 (SPEC) | buck, 3.3 V | M |
| U2 | 1117-class adj. LDO | 1.5 V DDR3 | M |
| U7 | SGM706-S / PT7A7514 | supervisor | H |
| Y1 | 25.000 MHz HC-49/US | SoC crystal | H |
| U109 | TI TCA9534APWR | I2C GPIO, TX-disable | H |
| U21-U23 | 74HC164 TSSOP-14 | LED shift registers | H |
| SW1 | 3-pos slide switch | mode M1/M2/M3 | H |
| D (per cage) | onsemi MMBD7000 (M5C) | SFP signal clamp (SPEC) | M |
| L (per cage) | power inductor pair | SFP VccT/VccR filter | L |
| J1 | DC barrel jack | 12 V in | H |
| J3-J10 | SFP+ cage | ports CON1-CON8 | H |
| J14 | 4-pin 2.54 mm | UART0 | H |
| TP_JTAG_* | 5 pads | EJTAG | H |
| SW2 | not fitted | reset button | H |

## SoC and memory

### SoC (under heatsink HS1)
- Marking: `RTL9303` / `P5HH4P2` / `GP23 TAIWAN` [OWN 20261008_161840].
- 8 SFP+ SerDes, MIPS 34Kc, 25 MHz XTAL. Datasheet: `sources/rtl9303-cg-brief.pdf`.
- Refdes not visible (heatsink outline HS1).

### DRAM (under heatsink HS1, right of SoC)
- Marking: `Zentel` / `A3T4GF40BBF` / `-HP` / `2528ZEE0` / `570333C` [OWN 20261011_202641..202719, 20261008_161732].
- Zentel A3T4GF40BBF-HP: DDR3/DDR3L 4 Gbit 256M x16, 96-ball FBGA, DDR3-1866 13-13-13. Datasheet: `sources/README.md` (Zentel DSA3T4GF340BBFF rev 06). Timings use: [DRAM.md](DRAM.md), [CLOCKS.md](CLOCKS.md).
- svanheule.net: "unknown chip" (photos heatsink on). The V1 photo shows Samsung `SEC 910` `K4B4G16` `46E BYMA` = **K4B4G1646E-BYMA** [V1]: the OpenWrt commit's Samsung part is the V1 chip.
- Supply: U2 rail silkscreened `TP1V5_1` = 1.5 V (DDR3 mode, not DDR3L 1.35 V). Not measured.

### SPI NOR flash U11
- Marking: `winbond` / `25Q256JVFQ` / date `2531` [OWN 20261008_102126, _161840]; `2222` [SVH-007].
- **W25Q256JVFIQ**: SOIC-16 300 mil, QE = 1 factory fixed (datasheet Rev L §7.1.4, `sources/winbond-W25Q256JV-RevL.pdf`). JEDEC `ef 40 19` ([BUS-SCAN.md](BUS-SCAN.md)).
- Silkscreen `U10` + `U11` around the same pads: dual footprint (alternate package outline).
- Neighbours: C312 (pin 2 VCC decoupling), R4476 (pin 1), R114-R117, R25-R33 (SPI series resistors, SPEC).
- Pin wiring: [Flash IO2/IO3 wiring](#flash-io2io3-wiring-61).

## Power

### Input
- J1 DC barrel jack, silkscreen `12V`; test points `TP12V_1`-`TP12V_4`.
- Bulk: radial electrolytic by J1; 2x 470 µF 16 V polymer (marking `EPC29` [TOP], `EPF31` [OWN 161745]) at U107/U108; 2x 100 µF 16 V polymer (blue sleeve).
- Unfitted: radial cap footprint between J1 and the bulk cap; 0402 pads C3473-C3476.

### U108: 1.1 V core buck
- Marking `568230` / `TI` = **TI TPS568230RJE** (VQFN-HR 20, 3x3 mm; TI marking code `568230`) [SVH-005, OWN 20261008_102238].
- 4.5-18 V in, 8 A, D-CAP3. Inductor L69 `2R2` = 2.2 µH. Output test point `TP1V1_1` [OWN 20261008_161747].
- Datasheet: `sources/ti-tps568230.pdf`, https://www.ti.com/lit/ds/symlink/tps568230.pdf.

### U107: 3.3 V buck
- Marking not readable on either unit's photo [TOP, OWN 20261008_102302, _102405]. Same package outline as U108; svanheule.net lists "2x TPS568230" → U107 = TPS568230 (M).
- Inductor L68 (large shielded), output caps C3424-C3427, test point `TP3V3_1` / `TPGND1`.
- 3.3 V feeds the SoC I/O and the 8 SFP cages (rating of the SFP rail: #30).

### U2: 1.5 V DDR3 LDO
- SOT-223, marking `1117B` / `AD 9051` [OWN 20261008_161732]. 1117-class adjustable LDO; vendor not identified (`1117B` + `AD` = adjustable). Input rail not traced (3.3 V SPEC).
- Output caps C18-C20, test point `TP1V5_1` / `TPGND3`.
- V1: same position, SOT-223 [V1].

### U7: supervisor
- Owner unit: `SGM706-SYS8` `2520C` = **SG Micro SGM706-S**, SOIC-8: 2.93 V reset threshold, 200 ms reset, watchdog 1.6 s typ / 1.0 s min [OWN 20261008_102453]. Datasheet `sources/sgmicro-sgm706.pdf`.
- svanheule.net unit: `PT7A` `7514WE` = **Diodes (Pericom) PT7A7514WE**: same pinout and thresholds (2.93 V, 1.6 s WD, active-low RESET) [SVH-006]. Datasheet `sources/diodes-pt7a75xx.pdf` (not recommended for new design).
- MAX706 pinout: 1 MR, 2 VCC, 3 GND, 4 PFI, 5 PFO, 6 WDI, 7 RESET, 8 WDO.
- [REF] uses MAX706RESA: WDI from GPIO0/SYS_LED (R81 not fitted), WDO→MR via R79 (not fitted), RESET → SoC RESETB.
- GPIO21 (#18): static high at the U-Boot prompt does not reset; driven low resets at once. A WDI hookup with WDO→MR would reset after ~1.6 s of static level, so GPIO21 most likely drives **MR** (pin 1, internal pull-up) and is not a watchdog feed. SPEC: trace not visible.
- Next to it: SW2 (not fitted) and through-hole pad `TPJTAG_RESET1` (manual reset access); D2 (SOT-23-5, marking `VM`), D3 (SOT-23, marking `B6`): not identified.

## Clock

### Y1: 25 MHz crystal
- HC-49/US (SMD), marking `?25.000 20` (25.000 MHz; `20` = load pF or ppm, vendor code first char unread) [OWN 20261008_161840, V1]. Between SoC and cages, above HS1.
- SoC XI/XO; [REF] uses 22 pF load caps (C188/C195). [CLOCKS.md](CLOCKS.md).

## I2C, GPIO, LEDs

### U109: TCA9534A
- Marking TI logo / `PW534A` / `24K G4` / `AD4N` = **TI TCA9534APWR** (TSSOP-16, TI code `PW534A`) [SVH-001, OWN 20261008_102248].
- Address 0x38 on bit-bang I2C GPIO22/23; P0-P7 = cage 1-8 TX-disable, active-high ([hardware.md](hardware.md#other-gpio--i2c)). Pull-ups R4470/R4471.
- Datasheet `sources/ti-tca9534a.pdf`, https://www.ti.com/lit/ds/symlink/tca9534a.pdf.

### U21, U22, U23: LED shift registers
- Marking `HC164` / `9510045` / `YXD22` / `23C` (TSSOP-14) [SVH-002, SVH-011, OWN 20261008_102321]. Vendor not identified from the lot lines; function = 74HC164 8-bit SIPO.
- Serial-LED output of the RTL9303 LED engine; 3 x 8 = 24 LED lines. Functional datasheet: `sources/nexperia-74hc164.pdf` (Nexperia 74HC164PW, same pinout).
- D51-D57: small SMD parts beside the LED groups, not identified [SVH-002, SVH-011].

### LEDs
- 24 green-lens through-hole LEDs in 8 black right-angle 3-high holders, top-right edge [OWN 20261008_161815, TOP].

### SW1: mode switch
- 3-position side-actuated slide switch, refdes SW1, with C134-C136 / FB8-FB10 / R87-R90 / R345 [OWN 20261008_161815]. GPIO17/18/19 (M1/M2/M3).

## SFP+ cages

### J3-J10 (CON1-CON8)
- 20-pin SFP+ cage + connector; silkscreen `J3 CON1` (right, by the LEDs) ... `J10 CON8` (left, by J1) [TOP, OWN 20261008_161732, _161747]. CONn = cage n.
- Per-cage series/pull resistors on the top side (e.g. R141-R153), TPGND test points around each connector [BOT].

### Per-cage bottom-side parts
- Each cage: 2 shielded inductors (e.g. L18/L19), 2 SOT-23 diodes (e.g. D18/D19), caps (e.g. C341-C348), resistors (e.g. R178/R193) [SVH-008, BOT, OWN 20261008_161900].
- Inductors: VccT/VccR filter (SFF-8431 host filter pattern). Value not marked. L.
- Diodes `M5C` = **onsemi MMBD7000** dual series switching diode (SOT-23, code `M5C`); clamps on cage signal lines SPEC. Datasheet `sources/onsemi-mmbd7000.pdf`.
- No per-cage load switch, fuse or current limiter: cage power is not switchable; one 3.3 V rail for all 8 (#30).

## Connectors and debug

### J14: UART0
- 4 x 2.54 mm through-hole, silkscreen `DH GND RX TX` [TOP]. 115200 8N1. `DH` unconnected in use ([photos/README.md](photos/README.md)).

### EJTAG
- 5 x through-hole pads `TP_JTAG_TRST`, `_TCK`, `_TDO`, `_TDI`, `_TMS` beside U11, with R340/R341/R342/R344 [OWN 20261008_161840]. Owner unit has pin headers fitted.
- SoC balls shared with UART1 ([HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md#ejtag)).

## Mechanical, markings, unfitted

- HS1: finned aluminium heatsink over SoC + DRAM (outline HS1). Mounting holes M1-M5.
- PCB bottom: `KB-6160` `10955` `223Y` `009` (fab/UL code, date) [BOT]. Top silkscreen board numbers: `2030501176` (svanheule unit), `2088500731` (owner unit), both `N31220`.
- Label `TL-ST1008F 2.0 R` (hardware 2.0).
- Unfitted: SW2 reset button; radial cap at J1; C3473-C3476; alternate flash outline U10; LED-area pads C3460-C3471 / R4201-R4215 (fitted state not resolvable).
- Not on the board: USB connector/pads (#5), external PHY, second SPI/I2C devices ([BUS-SCAN.md](BUS-SCAN.md)).

### V1 differences [V1]
- DRAM Samsung K4B4G1646E-BYMA.
- Top-right: unfitted RJ45 footprint `RJ1`, magnetics `T1`, QFN footprints (U15, U20) and a second crystal footprint `Y2`: a copper/management-port option not built. V2 has none of these.
- Bucks: same two-buck + SOT-223 LDO arrangement; polymer caps `EPA02`.

## Flash IO2/IO3 wiring (#61)

- W25Q256JV SOIC-16 pinout (datasheet Rev L §3.4): 1 IO3/HOLD#, 2 VCC, 3 RESET#, 4-6 NC, 7 CS#, 8 DO/IO1, 9 IO2/WP#, 10 GND, 11-14 NC, 15 DI/IO0, 16 CLK.
- [OWN 20261008_102126/_102129] (chip upside down, pin 1 top-right by the dot):
  - Pin 1 (IO3): copper runs from the pad to resistor **R4476** and a via next to it. Whether R4476 is a pull-up to VCC or a series resistor toward SoC `SIO3` is not resolvable.
  - Pin 2 (VCC): to C312 and a via.
  - Pins 3-8 also carry copper stubs upward, including NC pins 4-6, so a stub alone does not prove a net.
  - Pins 9-16 (incl. 9 = IO2): no copper leaves the pads on the top layer; routed under the package / inner layers. Not resolvable.
- [SVH-007]: chip only, no traces.
- [REF] (Realtek RTL9302D sheet): all six SPI lines (`SPI_CS0`, `SCK`, `SIO0`-`SIO3`) wired SoC → flash through 33 Ω (R51, R54-R58) with 5 pF to GND near the SoC; `SPI_MST_SIO2`/`SIO3` = balls F2/F1. The reference design wires quad.
- QE: fixed 1 (IQ part), so IO2/IO3 are data pins regardless of the board's pull-ups; HOLD#/WP# are disabled.
- **Verdict: the photos cannot decide quad.** Pin 1 is connected (to R4476 + via); pin 9 is not visible. The decider is the read-only quad read test planned in #61 (SFCR2 → Quad Output `0x6B` / Quad I/O `0xEB`, CRC vs Dual I/O). No status-register write is needed.
