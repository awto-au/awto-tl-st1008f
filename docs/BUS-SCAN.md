# Bus scan (#77)

Read-only scan of every I2C/SPI bus the RTL9303 can reach on this board, looking for undocumented devices.
Run: `./dev.py bus-scan` at our prompt ([../scripts/README.md](../scripts/README.md#bus_scanpy)).

## Method

- I2C probe: 0x08-0x77 only. 0x00-0x07 and 0x78-0x7f (general call, reserved) are never put on the bus.
- RTL9300 master probe = 1-byte read of reg 0. It cannot send zero-length transfers.
- i2c-gpio probe = address-only write.
- First read: 16 B from reg 0 per responder. The only bytes written are the register-pointer byte (no data writes).
- Cages: each SDA channel is scanned at 100 kHz (bus default), then at 50 kHz, because MCU-emulated module EEPROMs clock-stretch (`rtk sfp` fallback).
- SPI: flash controller only, with RDID `0x9f` (5 B) and RDSR `0x05`. CS0 = boot flash (baseline); CS1 = ball E1.
  - The driver refuses every other opcode on CS1, including EN4B, WREN and WREAR.
- Registers: `md.l` only (no writes).
- Only write: `rtk laser none`, which sets all TX-disable (the safe direction).

## Not scanned

- I2C MST2: SCL1 = GPIO17 = mode switch M1 pin. Driving it fights the switch. Its registers are read only.
- Switch-core SPI master (`SPI_CTRL1` `0x3a0`): its pins are GPIO3-5 (SCK/MISO/MOSI), GPIO7 (CS0) and GPIO6 (CS1). On this board GPIO0-7 = MOD-DEF0 of cages 1-8.
  - Enabling it would drive module-grounded presence lines.
  - Only the pinmux bits are read (`GPIO_SPI_SEL`, `GPIO6_CSB1_SEL`, `GPIO7_CSB0_SEL`).
- RTL8231 over MDIO (`EXT_GPIO_*` `0xc600`): `EXT_GPIO_GLB_CTRL` is read only. Stock `ext-devInit` fails (`0xf012`); the LEDs use 74HC164s.

## Registers (SDK `swcore_rtl9300.h`)

| reg | offset | fields read |
|---|---|---|
| `GPIO_SEL_CTRL` | `0x200` | `SLV_SPI_CS_SEL_GPIO` [9:5], `SLV_SPI_SDO_SEL_GPIO` [4:0] |
| `MAC_IF_CTRL` | `0x360` | `REG_IF_SEL` [0], `SPI_SO_REF` [1] |
| `MAC_SLV_I2C_CTRL` | `0x364` | `CFG_SDA_DLY` [13:8], `I2C_DATA_ENDIAN_SEL` [0] |
| `MAC_SLV_TIMEOUT` | `0x368` | SPI/I2C timeout set + flag |
| `I2C_MST_GLB_CTRL` | `0x384` | `SDA_SEL` [7:0], open-drain bits |
| `I2C_MST2_CTRL1/2` | `0x388` | `SCL_SEL`, `DEV_ADDR` |
| `SPI_CTRL1` | `0x3a0` | `GPIO_SPI_SEL` [13], `CSB_OUT_SEL` [12], `GPIO6_CSB1_SEL` [11], `GPIO7_CSB0_SEL` [10] |
| `EXT_GPIO_GLB_CTRL` | `0xc600` | `EXT_GPIO_EN` [8], `MDX2/3_EN` |
| `MAC_EEPROM_DOWN_LOAD_CNTRL` | `0xc6e4` | `SCK_FREQ_SEL` [9:8], `EEEPOM_VALID` [7:0] |
| `MAC_EEPROM_DOWN_LOAD_STS` | `0xc6e8` | `NOEEPROM` [0], `EEPROM_COMPL` [1], `EEPROM_VALID_FAIL` [2] |
| `MAC_EEPROM_DOWN_LOAD_*_POS` | `0xc6ec-0xc6f8` | MAC/SerDes/PHY/group-MAC segment start/end |

## Results (2026-10-12T08:53+11:00, main 43d3039, stock clocks)

No undocumented devices (`unknown I2C devices: 0`). Raw: `tmp/bus_scan-77.json`.

### I2C MST1 SDA0-7 (cages 1-8)
- Only the fitted module per cage: 0x50 ID EEPROM (all 8), 0x51 DDM (SR/SX/PTB modules), 0x56 88E1111 PHY (GLC-T, cages 3/7).

### Expander bus (GPIO22/23)
- Only 0x38 TCA9534A (laser TX-disable).

### SPI
- CS0: JEDEC `ef 40 19` (W25Q256), RDSR 00.
- CS1: reads `ff`, nothing attached.
- Switch-core master `SPI_CTRL1 = 0035e000`: GPIO3-5 as SPI, no CS routed, idle; not driven (pins = cage presence).
  - Set by stock `rtk network on` (`ramload` runs it before our U-Boot). It made empty cages 4-6 read "present" (#29); our U-Boot and Linux DTS now mux GPIO3-7 back to GPIO ([hardware.md](hardware.md#cage-presence-pinmux-29)).

### Registers
- MAC EEPROM autoload: NOEEPROM 0, EEPROM_COMPL 1, VALID_FAIL 1: the reset-time download gets an answer (likely cage-1 SFP EEPROM on the shared SDA) and rejects it; nothing loaded.
- I2C/SPI slave (0x360-0x368): 0, unused.
- I2C MST2: idle (CTRL2 0x5003); never scanned (SCL = GPIO17 = mode switch).
- `GPIO_SEL_CTRL` `0x200`: slave-SPI CS/SDO select = 31 (unused); GPIO18/19 as GPIO (mode switch).
- `SPI_CTRL1` `CLK_DIV` 7.

