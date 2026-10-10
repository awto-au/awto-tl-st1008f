# `rtk` command parity: stock loader vs our U-Boot

Goal: every stock `rtk` subcommand (visible and hidden) in our mainline U-Boot, direct register access, no vendor SDK, each one testable against stock.

- Stock: U-Boot 2011.12 + Realtek SDK 3.6.6, dispatcher `do_rtk` [BIN] `0x83f1679c`. Ours: `uboot-port/board/tplink/tl-st1008f/` (`cmd_rtk.c` dispatch, `rtk_stock.c` stock verbs, `rtk_sds.c` SerDes, `rtk_ours.c` extras).
- Inventory method: `strcmp` chain of the stock dispatcher + its string table, cross-read against the GPL source it was built from [SRC] `rtk-dms1250/system/uboot/cmd/uboot_cmd.c` (reyalo/Realtek). Related: [UBOOT-REFERENCE.md](UBOOT-REFERENCE.md), [UBOOT-FUNCMAP.md](UBOOT-FUNCMAP.md).
- Source tags: **[SRC]** GPL SDK path:line (`dms1250/` = `sources/rtk-dms1250/`). **[OWRT]** OpenWrt `target/linux/realtek/files-6.18`. **[BIN]** stock `loader.bin` VA, where only the binary shows it. **[LIVE]** seen on this unit's console. **SPEC** inferred, unverified.
- `help rtk` = stock text verbatim, then a `--- TL-ST1008F additions ---` section (laser, sfp, port, mode, temp, help-ours, hidden stock verbs). The parity check drops that section (`drop:` mask).
- Parity test = `./dev.py rtk-parity` ([below](#parity-harness)); the list is `scripts/rtk_parity_cmds.json`.

## Status counts (40 leaf forms)

| Status | n | Forms |
|---|---|---|
| done (existed, now aligned to stock text) | 6 | `i2c init sw`, `i2c init hw`, `i2c read`, `i2c write`, `pinGet`, `pinSet` |
| implemented now | 22 | `unit get/set`, `port enable/disable`, `show hw_profile_list`, `comboport copper/fiber`, `ext-devInit/pinGet/pinSet`, `ledtest` (2 forms), `phyreg get/set/setbymask/dump-top`, `phymmd get/set`, `sdsreg get/set`, `boardid` get, `boardmodel` get |
| needs ethernet + SerDes stage | 9 | `init`, `rtcore-init`, `network on/off`, `port-isolation on/off`, `macsds set`, `10g`, `send` |
| refused | 3 | `boardid <id>`, `boardmodel <str>` (flash writers), `phytestmode` (needs a PHY; none fitted) |

- In `help rtk` but not dispatched (stock prints Usage): `testmode`, `10g ... fiber100m`. Not in stock at all: `eee`. Ours matches (Usage).
- Hidden (dispatched, not in `help rtk`): `init`, `rtcore-init`, `port enable|disable`, `comboport`, `port-isolation`, `send`, `phyreg dump-top|setbymask`.
- Unknown verb or short argv: stock prints `Usage:\n<usage line>\n` ([BIN] `0x83fb9668`) and returns 1; ours identical. Stock dereferences a missing `argv[2]`/`argv[3]` for some verbs (e.g. `rtk network`, `rtk port enable`); ours prints Usage instead.
- Numbers parse like stock: `dectoul`, so `0x` prefixes work in any field.

## Stock verbs

Unit = `rtk unit set` value (default 0); a unit >= 6 prints `\nUnit %u invalid unit id \n` after the header line.

| Verb + args | What stock does | Stock output | Flash write | Our status | Parity test |
|---|---|---|---|---|---|
| `init` | SDK init, per-port MAC cfg [SRC] uboot_cmd.c:173 | SDK banner | no | needs-eth: prints `not yet`, rc 1 | none (hangs/changes state) |
| `rtcore-init` | RTCORE module init :180 | `RTCORE Driver Module Initialize`... | no | needs-eth | none |
| `network on` / `off` | PHY enable/disable per port, SDK init once :187/:197 | `Enable network` / `Disable network` + banner | no | needs-eth | none (once per boot) |
| `unit get` | print unit [SRC] :209 | `unit: %u` | no | done | `rtk unit get` |
| `unit set <n>` | set unit; n>5 prints `Invalid unit: %u` but still sets [BIN] | `Change to unit: %u` | no | done | `rtk unit get; rtk unit set 0; rtk unit get` |
| `port enable\|disable <p>` | SDK admin state [SRC] :369 ff.; hidden | `Enable port (%d,%d)` / `Disable port (%d,%d)` | no | done: RMW `MAC_L2_PORT_CTRL(p)` bits 1:0 (`0x3268 + p*0x40`, [OWRT] dsa.c:339,407). SPEC: stock may touch more | state: `port disable 8; md.l 0xbb003468 1; port enable 8; md.l ...` (compares register) |
| `show hw_profile_list` | list profile table [BIN] `0x83f9348c` | `      Available profiles are:` + 25 rows `        NAME (ID)` + `      (uboot: setenv boardmodel 'YOUR_HARDWARE_PROFILE_NAME')` | no | done (table copied from the binary data) | `rtk show hw_profile_list` |
| `comboport copper\|fiber` | combo media; no combo ports on 8XGE [SRC] :270 | `ComboPort: Copper mode` / `ComboPort: Fiber mode` | no | done (message only) | 3 forms |
| `port-isolation on\|off` | rewrites per-port forwarding masks via ASIC table [SRC] :353 | `isolation: %2u <--> %2u` rows | no | needs-eth (ASIC table access) | none |
| `pinGet <n>` | SoC GPIO input read [SRC] :392 | `pin%d:\t%d\n\n` | no | done: driver read, no claim; pins 0-23 (stock usage says 0~7) | `rtk pinGet 7`, `pinGet 0`, bad args |
| `pinSet <n> <0\|1>` | SoC GPIO output [SRC] :414 | `pin%d:\t%d\n\n` | no | done; GPIO21 low refused without `force` | usage/invalid forms only (hardware pins) |
| `ext-devInit <addr>` | RTL8231 MDC init; the SDK rejects ext dev 1 (`0xf012`) [BIN] `0x83f1fcd0` | `The generalCtrl GPIO device init failed.` | no | done | `rtk ext-devInit`, `... 1` |
| `ext-pinGet <n>` / `ext-pinSet <n> <s>` | not initialised -> `0xf00f` | `The pinNum (%d) is invalid.` (`The status (%d) is invalid.` for s>1) | no | done | 5 forms |
| `i2c init sw ...` | creates a bit-bang I2C id [SRC] :522 | none | no | done: buses fixed by DT; id mapped to cage (sda pin) or expander (sck 22/sda 23) | `rtk i2c init sw 1 2` (param error) |
| `i2c init hw ...` | creates a HW I2C id | none | no | done (as above, sda pin = cage-1) | param error form |
| `i2c read <id> <reg>` | one byte [SRC] | `data 0x%x` / `FAIL (%d)`; unknown id `FAIL (61455)` | no | done | `i2c read 0 0`, `0 2`, `7 0`, `8 3`, `9 1` |
| `i2c write <id> <reg> <d>` | one byte | `OK` / `FAIL (%d)` | no (I2C) | done; module EEPROM ids 0-7 refused | param error form; writes not in list |
| `ledtest` | all LEDs on 200 ms, off, walking one, restore [SRC] uboot_func.c:1830 ff. | `\n all led on \n`, `\n all led off \n`, `\n walking one \n` | no | done: SW LED regs below; ~10 s | slow: `rtk ledtest` |
| `ledtest <port> <led>` | one LED on until a key | `\n press any to end.\n`; `The port (%d) is invalid.`; `The led index (%d) is invalid.` | no | done; key wait capped at 30 s | key: `rtk ledtest 0 0`; bad args |
| `phyreg get\|set <port> <page> <reg> [d]` | PHY page/reg via MIIM [SRC] :652 | `Get Unit %u Port %02d page %02d reg %02d  val: 0x%04X ` | no | done as no-PHY stub: get returns 0, set accepted. SPEC: stock result on a SerDes-only port unverified | `rtk phyreg get 0 0 0 0` |
| `phyreg setbymask <mask> <page> <reg> <d>` | write every port in mask; hidden | `Set Unit %u PortMask %08x page %02d reg %02d val: 0x%04X ` | no | done (stub, header only) | none |
| `phyreg dump-top` | stub, returns 1; hidden | none | no | done | `rtk phyreg dump-top` |
| `phymmd get\|set <ignored> <port> <mmd> <reg> [d]` | clause-45 access | `Get Unit %u Port %02d mmd-address %02d mmd-reg %02d  val: ...` ; set seen [LIVE] `Set Unit 0 Port 00 mmd-address 04 mmd-reg 50241 val: 0x0008 ` | no | done (stub; matches the live set) | `rtk phymmd get 0 0 4 0xc441` |
| `sdsreg get <ignored> <sds> <page> <reg>` | SerDes read [SRC] :691 | `Get unit %u sds %02d page %02d reg %02d  val: 0x%04X ` [LIVE]; error `    Failed!! 0x%x ` | no | done: indirect access (below) | 4 reads + usage forms |
| `sdsreg set <ignored> <sds> <page> <reg> <d>` | SerDes write | `Set unit %u sds %02d page %02d reg %02d val: 0x%04X ` [LIVE] | no | done | state: rewrite of the value just read |
| `macsds set <sds> <mode>` | re-construct SerDes in `<mode>` [SRC] :731; 34 names | `sds=%u mode=%s`, `unit %u sds %u mode %u`; bad mode: `sdsmode error` + 44-row list (10 blank) | no | needs-eth: validation, mode list and first line done; the set itself prints `not yet` | `macsds set 2`, `... bogus` |
| `phytestmode <m> <p> <ch>` | PHY test mode | `Usage: testmode ...` when no args | no | refused (no PHY) | `rtk phytestmode` (usage) |
| `boardid` | print env `boardid`; returns 1 | `Board Model ID: %s` (`<NULL>` unset) | no | done | `rtk boardid` |
| `boardid <id>` | `setenv` + env sector erase/write [BIN] `0x83f19894` | none | **yes** | **REFUSED** | denylist |
| `boardmodel` | print env `boardmodel`; returns 1 | `Board Model: RTL9303_8XGE` | no | done: default env `boardmodel=RTL9303_8XGE` in the board header | `rtk boardmodel` |
| `boardmodel <str>` | `setenv` + env sector write [BIN] `0x83f1991c` | none | **yes** | **REFUSED** | denylist |
| `10g <port> <media>` | per-port media (none, fiber10g, fiber1g, dac50cm, dac100cm, dac300cm) | `FAIL (0xf002)` before SDK init | no | needs-eth (media = SerDes mode); bad media prints Usage | `rtk 10g 0 bogus` |
| `send` | transmit a fixed 74-byte frame; hidden | none | no | needs-eth; also puts a frame on the wire (storm risk) | denylist |

## Registers (all base `0xBB000000` unless noted)

- SerDes indirect access (`sdsreg`) [OWRT] `drivers/net/mdio/mdio-realtek-otto-serdes.c:37-42,308-327,396-419`:
  - CMD `+0x03b0`: bit0 BUSY, bit1 WRITE, [6:2] sds, [12:7] page (6 bit), [17:13] reg. DATA `+0x03b4`.
  - Read: write CMD, poll BUSY clear, read DATA. Write: write DATA, then CMD.
  - Poll cap 1 ms (10 us x 100); OpenWrt polls every 30 us. Expiry prints SerDes/page/reg. No measurement of the real latency yet.
  - Range: sds 0-11, page 0-63, reg 0-31; outside -> `Failed!! 0xf00c` (code SPEC).
- SerDes mode field (used by `rtk port`) [OWRT] `pcs-rtl-otto.c:75-80,1905-1916`: 5-bit fields in `0x194`, `0x2a0`, `0x2a4`, `0x198`; `0x1a` = 10GBASE-R, `0x1f` = off.
- LED software control (`ledtest`) [SRC] `dms1250/system/include/private/drv/swcore/swcore_rtl9300.h:3127-3138`, sequence `system/uboot/cmd/uboot_func.c` (`rtk_swled_init/out/uninit`):
  - `LED_PORT_SW_EN_CTRL` `0xCC4C + (port>>3)*4`, 4 bits per port (`(port&7)*4`); 7 = software controlled.
  - `LED_PORT_SW_CTRL` `0xCC5C + port*4`: 3 bits per LED, copper LEDs [11:0], fibre LEDs [23:12]; 7 = on (`LEDON`).
  - Ours writes both copper and fibre fields (stock selects by LED layout; layout for this board not known), saves and restores both registers, 300 ms after each pattern as stock.
- Port admin: `MAC_L2_PORT_CTRL(p)` `0x3268 + p*0x40` ([UBOOT-REFERENCE.md](UBOOT-REFERENCE.md) §4; [OWRT] dsa.c link up/down). SDK port numbers: cage 1-8 = 0, 8, 16, 20, 24, 25, 26, 27; CPU 28. Cage N = SerDes N+1.
- Thermal (`rtk temp`) [OWRT] `drivers/thermal/realtek-thermal.c:35-47,136-165`, recipe [hardware.md](hardware.md#thermal): `CTRL_1 0x64` [31:16] = `0x0800`, `CTRL_2 0x68` bit 16 = 1 (RMW), `RESULT_0 0x6c` bit 24 valid, [23:16] deg C, `RESULT_1 0x70` max [14:8] / min [6:0].
- Mode switch (`rtk mode`): `gpio0 DATA 0xB800330C` bits 17-19 (active low), decode per [hardware.md](hardware.md#mode-switch-stock-firmware): (0,1,1) -> 1, (1,0,1) -> 2, else 3.

## Our extra commands (no stock equivalent)

| Command | What it does | Test |
|---|---|---|
| `rtk laser [status\|<cage>\|none\|all force]` | TX-disable expander `0x38`; one cage by default (cage loop #19) | `uboot_mainline_test.py laser` |
| `rtk sfp [cage [raw\|brief]]` | module EEPROM/DDM decode ([UBOOT-MAINLINE.md](UBOOT-MAINLINE.md)) | `sfp_all`, `ddm` |
| `rtk port` / `rtk port status` | per cage: port, SerDes id, presence, module PN, laser on/off, SerDes mode, RX light (page 5 reg 0 bit 12), MAC link (`0xCB10`), LED owner (hw/sw). Read-only | `rtk_port` |
| `rtk mode` | M1/M2/M3 position: `mode: pins 17/18/19 = a/b/c -> pattern N (Mx, ...)`. Pin 17 reading low at all positions is an open question (hardware.md) | `rtk_mode` |
| `rtk temp` | enables the thermal meter if off (RMW), waits for a valid sample (cap 100 ms, no measured settling time yet), prints deg C and min/max since enable | `rtk_temp` |
| `rtk help-ours` | lists the above | none |

`help rtk` text is the stock text (typos included); extras are only in `rtk help-ours`.

## Parity harness

- `./dev.py rtk-parity capture --side stock [--state] [--slow]` at the stock `RTL9300#` prompt; runs the `pre` phase, `rtk network on`, then the `post` phase.
- `./dev.py rtk-parity capture --side ours` at `st1008f-mainline #`; `./dev.py rtk-parity compare`; `both` chains stock capture -> `st1008_ramload.py uboot-mainline --no-cycle --no-network` -> ours capture -> compare.
- Verdicts: PASS, DIFF (stock/ours text printed in the log), ONLY-OURS, NO-STOCK/NO-OURS. Per-command `mask` regexes hide volatile values.
- Never sent: `saveenv savesys setsys upgrade flerase erase protect boota bootm bootp tftpboot reset go`, `sf write|erase|update`, `rtk boardid|boardmodel <arg>`, `rtk init|rtcore-init|network|port-isolation|send`, a real `macsds set`, any `*force`.
- `--state` adds `sdsreg set` (rewrites the value just read) and `port disable/enable 8`; `--slow` adds the `ledtest` forms.
- Log `tmp/logs/rtk_parity.log`; captures `tmp/logs/rtk_parity-{stock,ours}.json`.
- First DIFFs expected (unverified guesses): `phyreg`/`phymmd get` value, `port` register delta, `ledtest` text; stock unit-range/`sds` range error codes.

## Open

- Stock output for `phyreg`/`phymmd get`, out-of-range `sdsreg`, `comboport`, `phytestmode`, `ext-devInit` not yet captured; harness will show them.
- Admin-state register for `port enable|disable` is from Linux behaviour, not from the SDK sources (stock path is a driver-table call).
- LED layout (copper vs fibre fields) for the 8XGE profile.
- Stage 4 (ethernet + SerDes bring-up) unlocks: `init`, `rtcore-init`, `network`, `port-isolation`, `macsds set`, `10g`, `send`.
