# TL-ST1008F v2 board photos

- [Top side](tl-st1008f-v2-board-top.jpg) — includes the 4-pad serial header silkscreened `DH GND RX TX`.
- [Bottom side](tl-st1008f-v2-board-bottom.jpg)
- Close-ups (downscaled to 1200 px from `sources/photos-svanheule/`), parts in [../BOM.md](../BOM.md):
  - [U109 TCA9534A](svanheule-u109-tca9534a.jpg) (`_001`)
  - [U23 74HC164](svanheule-u23-74hc164.jpg) (`_011`)
  - [U108 TPS568230](svanheule-u108-tps568230.jpg) (`_005`)
  - [U7 PT7A7514 supervisor](svanheule-u7-supervisor.jpg) (`_006`)
  - [U11 W25Q256JVFIQ flash](svanheule-u11-flash.jpg) (`_007`)
  - [Per-cage SFP filter: L18/L19, D18/D19 MMBD7000](svanheule-sfp-vcc-filter.jpg) (`_008`)

Source: [TL-ST1008F V2 hardware page](https://www.svanheule.net/switches/tl-st1008f), photos by Oliver.
Licensed [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) per the source page; these copies
are redistributed under the same licence with attribution.

- `DH` function is not established by the photo; leave it disconnected. UART needs only GND, RX, TX.
