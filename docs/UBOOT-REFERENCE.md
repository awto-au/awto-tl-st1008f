# TL-ST1008F v2 — stock U-Boot reference

Narrative & dead ends: see [HISTORY.md](HISTORY.md).

Scope: this unit's own LOADER partition, focused on 10G/Ethernet bring-up.

- **Binary:** `private/stock-loader-20261007/loader.bin` (local only) — 896 KiB, CRC32 `e579e61c`,
  SHA256 `0acb263012d910cfbc53815d8a040519242fb08c5531a8e4e15b84384d84a4e1`.
  Two matching `md.b` reads off this unit; identical to `mtd0` of the full-flash backup.
- Related: [hardware.md](hardware.md), [FIRMWARE-ANALYSIS.md](FIRMWARE-ANALYSIS.md), [UBOOT-FUNCMAP.md](UBOOT-FUNCMAP.md).
- Live command output: [../artifacts/](../artifacts/).

Evidence tags: **[BIN]** our loader.bin (offset). **[SRC]** matched GPL source (path:line, relative to
`sources/` in a clone of `github.com/reyalo/Realtek`). **[DTS]** OpenWrt device tree. **[LIVE]** read
off this unit's `RTL9300#`. **SPEC** inferred, not proven.

---

## 0. Source and version match

Method: prove the base by byte-identical git blob SHAs on untouched files, then `grep` for what is custom.

### Base = denx U-Boot v2011.12 (blob SHA match)

| File | reyalo blob SHA | denx v2011.12 blob SHA | match |
|---|---|---|---|
| `README` | `6fe1e0fc…` | `6fe1e0fc2d779acc7551a13fb055e52d2d8c1086` | ✅ |
| `lib/vsprintf.c` | `e497a868…` | `e497a8686ed321acf5119e290fd32b0fd74ed61d` | ✅ |

- `common/main.c`, `common/command.c` differ from upstream = Realtek autoboot/command customisation.
- Banner `U-Boot 2011.12.(3.6.6.55087)`: `2011.12` = denx base; `3.6.6.55087` = rtk SDK driver version.
- Toolchain **[BIN]**: `rtk-ms-2.0.0-linux-mips-3.18-4.8.5-u0.9.33`; `version` prints Realtek MSDK-4.8.5p1 Build 2536.

### rtk command layer = dms1250 family, TP-Link subset; DAL = longan (RTL930x)

- `macsds` **[BIN]** `0xbf89c` (help `0xc00d5`) is in the dms1250 `do_rtk` dispatcher **[SRC]**
  `rtk-dms1250/system/uboot/cmd/uboot_cmd.c:731` and absent from xgs1210's.
- Subset of dms1250: present `macsds`, `eee`; absent `sfp-speed`, `sys-esd`, `parameter version` **[BIN]**.
- `rtk port enable|disable <port>` is not in `help rtk` and its literal string was not found, but works **[LIVE]** (`Disable port (0,8)`).

### Config header = `include/configs/rtl9300.h`

| Constant | Source | Binary / live |
|---|---|---|
| `CONFIG_SYS_PROMPT` | `"RTL9300# "` **[SRC]** `rtl9300.h:38` | `RTL9300#` **[LIVE]** |
| `CONFIG_BAUDRATE` | `115200` **[SRC]** `rtl9300.h:25` | 115200 8N1 **[LIVE]** |
| `CONFIG_SYS_SDRAM_BASE` | `0x80000000` **[SRC]** `rtl9300.h:36` | kernel load `0x80000000` **[LIVE]** |
| default `boardmodel` | — | `RTL8393M_DEMO` **[BIN]** `0xbc0d6`; stored env overrides to `RTL9303_8XGE` |

### Source files that name the functions

- `rtk-dms1250/system/uboot/cmd/uboot_cmd.c` — `do_rtk` dispatcher.
- `rtk-dms1250/system/uboot/cmd/uboot_func.c` — `rtk_network_on`/`off`, SDK init glue.
- `rtk-xgs1210/src/dal/longan/dal_longan_sds.c` — SerDes init, rxCali, link check.
- `rtk-xgs1210/src/dal/longan/dal_longan_construct.c` — 10GR SerDes tables, chip-rev select.
- `rtk-xgs1210/src/dal/longan/dal_longan_waFunc.c` — block-lock check.
- `rtk-xgs1210/system/drv/swcore/chip_probe.c` — chip id/rev.
- `openwrt/target/linux/realtek/dts/rtl9303_tplink_tl-st1008f-v2.dts` — board wiring **[DTS]**.

### Binary layout

- Main text at loader offset `0x5080`, linked at `0x83f00000`; raw import base `0x83efaf80`.
- Anchors: `rtk` dispatcher `0x83f1679c`; network-on `0x83f199c4`; SDK-init-once `0x83f14ef4`; register eth device `0x83f1f25c`.
- Ghidra project: `private/ghidra/stock-loader-mapped.gpr` (local only). More names: [UBOOT-FUNCMAP.md](UBOOT-FUNCMAP.md).

### Reference build

- olliver's `realtek_sdk` (GitLab) builds this U-Boot family in Docker (`make 9300 loader`); `tplink_maple` branch = TP-Link ST-series.
- Use: symboled reference binary, or a RAM-run U-Boot with extra commands (e.g. `tftpput`). Flashing it is out of scope.

---

## 1. Commands

Full `help`: [../artifacts/uboot-help.txt](../artifacts/uboot-help.txt). `help rtk`: [../artifacts/uboot-help-rtk.txt](../artifacts/uboot-help-rtk.txt).
No USB, `tftpput`, `nfs`, `dhcp` or `netconsole` commands.

### `rtk` subcommands

Dispatcher `do_rtk` **[SRC]** `uboot_cmd.c:151`, `argv[1]` strcmp chain. All rows present in our binary.
Hazard: 🟢 returns cleanly; 🔴 hangs console (power cycle); ⚠ changes switch/flash state.
"SDK init" = first `rtk network on` of the boot.

| Subcommand | [BIN] off | [SRC] line | Effect | Hazard |
|---|---|---|---|---|
| `rtk init` | `0xbf4d8` | :173 | `uboot_sdk_init` + per-port MAC cfg (`0x83f1784c`) | 🟢 |
| `rtk rtcore-init` | `0xbf4e0` | :180 | RTCORE module init | 🟢 |
| `rtk network on` | `0xbf9c4` | :187 | `rtk_network_on()`: SDK init, per-port `phy_enable_set`; registers `rtl9300#0` and I2C devs 0-8 | 🟢 first run; second run in the same boot has wedged the console once (🔴) |
| `rtk network off` | `0xbf500` | :197 | `phy_enable_set(…, DISABLED)` all ports | ⚠ |
| `rtk unit get/set` | `0xc0115`/`0xc0122` | :209 | SDK unit id (0) | 🟢 |
| `rtk show hw_profile_list` | `0xbfdac` | :256 | profiles (`RTL9303_8XGE` = `9300015`) | 🟢 |
| `rtk comboport …` | `0xbf5a8` | :270 | combo copper/fiber media — N/A on 8XGE | ⚠ |
| `rtk port-isolation on/off` | `0xbf5f4` | :353 | on = pair external ports; off = widen front-port fwd mask (`HWP_PORT_TRAVS_EXCEPT_CPU`, CPU port untouched) | ⚠ |
| `rtk port enable/disable <p>` | — | — | port admin state | ⚠ |
| `rtk eee on/off` | — | :369 | EEE | ⚠ |
| `rtk pinGet <n>` | `0xbfcfb` | :392 | read SoC GPIO | 🔴 before SDK init; 🟢 after |
| `rtk pinSet <n> <st>` | `0xbfd36` | :414 | write SoC GPIO | 🔴 before SDK init; untested after |
| `rtk ext-devInit/ext-pinGet/ext-pinSet` | `0xbf6c0`/`0xbf750`/`0xbf798` | :446-490 | RTL8231 GPIO expander (not fitted) | 🟢 |
| `rtk i2c init sw …` | `0xbfb55` | :522 | create bit-bang I2C group | 🔴 before SDK init; 🟢 after |
| `rtk i2c init hw …` | `0xbfc1a` | :522 | create HW I2C group | 🟢 |
| `rtk i2c read <id> <reg>` | `0xbfcb3` | :522 | dev 0-7 = SFP EEPROM (byte 0 = `0x03`), dev 8 = PCA9534 | 🔴 before SDK init; 🟢 after |
| `rtk i2c write <id> <reg> <d>` | `0xbfcd3` | :522 | `write 8 1 <mask>` + `write 8 3 0` = laser enable | 🟢 after SDK init |
| `rtk phymmd get/set` | `0xbfff0`/`0xc0013` | :652 | clause-45 PHY (8XGE has none) | 🟢 get |
| `rtk sdsreg get <sds> <pg> <reg>` | `0xc0060` | :691 | `hal_serdes_reg_get`; returns `Failed!! 0xf010` before SDK init | 🟢 |
| `rtk sdsreg set <sds> <pg> <reg> <d>` | `0xc0084` | :691 | SerDes write | 🟢 |
| `rtk macsds set <sds> <mode>` | `0xc00d5` | :731 | re-construct SerDes (`10gr` → mode 2) | 🟢 |
| `rtk phytestmode <m> <p> <ch>` | `0xbfdfe` | :801 | PHY test mode (needs a PHY) | ⚠ |
| `rtk testmode [mode] [port]` | `0xbfa36` | :801 | port test mode | ⚠ |
| `rtk boardid [id]` | `0xbf954` | :814 | get (`<NULL>`) / set | get 🟢 / set ⚠ |
| `rtk boardmodel [str]` | `0xbf95c` | :828 | get (`RTL9303_8XGE`) / set | get 🟢 / set ⚠ |
| `rtk 10g PORT <media>` | `0xbff13` | :841 | set media `none/fiber10g/fiber1g/fiber100m/dac50cm/dac100cm/dac300cm` | `0xf002` before SDK init; 🟢 after |

- `rtk 10g 0 fiber10g` dispatches to `0x83f199b8` = the same per-port wrapper (mode 1) `network on` already runs on every port.
- SerDes reads/writes never hang.

### TP-Link top-level commands

| Command | [BIN] off | Effect | Hazard |
|---|---|---|---|
| `boota` | `0xb8ba4` (param block) | boot from one of two RUNTIME images; passes `bootargs` env to the kernel | 🟢 |
| `flshow` | `0xbf444` | print partition layout | 🟢 |
| `printsys`/`savesys`/`setsys` | `0xbe804`/`0xbe6fc`/`0xbe748` | SYSINFO store (`Invalid system information` on this unit) | print 🟢 / save, set ⚠ |
| `upgrade loader\|runtime1\|runtime2\|rom [FILE]` | `0xbecc8` | TFTP fetch + flash write | ⚠⚠ |
| `loaderforce` and `*force` | `0xbec70` | upgrade without validation; rewrites the bootloader | ⚠⚠⚠ |
| `flerase` | `0xbf468` | partition erase; refuses LOADER (`0xbf404`) | ⚠⚠ |

No flash write is part of this project.

---

## 2. Ethernet / 10G bring-up path

### Call chain **[SRC]**

`rtk network on` → `rtk_network_on()` `uboot_func.c:422`:
1. `uboot_sdk_init(UBOOT_SDK_INIT_PHASE_RTK)` `:427` — the real init.
2. prints `Please wait for PHY init-time ...` `:430`.
3. 8XGE is neither 8380 nor 9310 → generic branch `:454-459`: `phy_enable_set(unit, port, ENABLED)` per port.
4. `osal_time_mdelay(2000)` `:466`.

- `phy_enable_set` on a PHY-less SerDes port returns `0xf030` = `RT_ERR_PORT_NOT_SUPPORTED` (miim.c:511/522); the wrapper prints `FAIL (0x%x)`; the loop ignores it. Benign on every boot.
- Failing chain in the binary: network-on → per-port wrapper `0x83f1994c` → DAL dispatch `0x83f3efdc` → generic callback `0x83f3680c` (prints `Err:0x%x:`) → HAL wrapper `0x83f28848`. Mapper slot `0x5c0`, set by `0x83f3d010`.
- Live profile **[LIVE]**: HAL PHY pointer for port 28 at `0x83ff21e0 + 0xc + 28*4 = 0x83ff225c` is 0; ports 0, 8, 16, 20, 24-27 nonzero.

### SerDes init runs in the bootloader

`uboot_sdk_init(RTK)` → `dal_longan_init` → `dal_longan_sds_init`.
- Not `__BOOTLOADER__`-gated **[SRC]** `dal_longan_mapper.c:157-162` (outside the guards at 143-155, 164+). `dal_longan_sds.c` has no `__BOOTLOADER__` guards.
- Per 10G SerDes **[SRC]** `dal_longan_sds.c:4737-4788`:
  1. `dal_longan_sds_rxCaliConf_set(sds, rtl9300_rxCaliConf_serdes_myParam)` `:4747` (tap0_init_val `0x1f`, vth_min 0, eqHoldEnable, dfeTap1_4Enable, dacLongCableOffset 3).
  2. gate `_dal_longan_sds_10gRxIdleRdy_wait(sds, 10 ms)` `:4770`: even SDS writes `0x35` to page `0x1f` reg `0x2`, reads page `0x1f` reg `0x14` bit 0; OK when `rxIdle == 0`. Odd SDS uses the even sibling, bit 1.
  3. if OK: `osal_time_mdelay(200)`; `dal_longan_sds_rxCali(sds, 0)` — one pass, no retry; a failed cali sets `PHY_SDS_RXCALI_STATUS_FAILED` and returns `RT_ERR_OK` `:4107-4143`.
  4. then `clk_routine` `:4777`, `linkFault_check` `:4780`, `rxCaliConf_cust` `:4783`, `txParam_config_init` `:4786`.
- Adaptive re-calibration (waMon thread) is `#ifndef __BOOTLOADER__`; runs only under Linux.
- **[LIVE]** sds2 page `0x1f` reg `0x14` = `0x15BC` after `network on` (gate passes).

### Link registers

- Block-lock **[SRC]** `dal_longan_waFunc.c:443-465`: page 1 reg 30 read three times; up iff low 9 bits = `0x1ff` on reads 2 and 3. **[LIVE]** reads `0x0000`/`0x0100` on this unit even with traffic flowing → not usable here.
- Signal detect: page 5 reg 0, bit `0x1000` (`0x100D` lit, `0x000C` dark).
- Traffic: MIB counters ([hardware.md](hardware.md#link-and-traffic-checks)).

### TFTP requirements

- Boot prints `Net: Net Initialization Skipped` / `No ethernet found`. Bare `tftpboot` before `rtk network on` resets the board.
- After `rtk network on`, `tftpboot` uses `rtl9300#0`. Frames leave the switch only once the SFP laser is enabled (PCA9534, §3).

---

## 3. GPIO / expander map

From **[DTS]** `rtl9303_tplink_tl-st1008f-v2.dts` unless noted.

| gpio0 pin | Function | Active | DTS line |
|---|---|---|---|
| 0–7 | SFP cage 1–8 MOD-DEF0 (presence) | LOW | :80,89,…,143 |
| 9–16 | SFP data-I2C SDA, cage 1–8 | — | :161 |
| 17/18/19 | mode switch M1/M2/M3 (`gpio-keys`, EV_SW) | LOW | :27/:35/:44 |
| 21 | external watchdog toggle | — | — |
| 22 | i2c-gpio SCL (open-drain) | HIGH | :66 |
| 23 | i2c-gpio SDA (open-drain) | HIGH | :67 |

- SFP data I2C = `i2c_mst1` per-port: `scl_pin = 8 + 9*(port/4)`, `sda_pin = port/2`, `interface = 1-(port/4)`, 8-bit reg **[SRC]** `rtdrv_netfilter_ext_9300.c`. EEPROM `0x50`, DOM `0x51`.
- PCA9534 `gpioexp0` @ `0x38` on `i2c_gpio` (SCL 22 / SDA 23, `delay-us = 2`) **[DTS]** :61-71. Pin N = cage N+1 tx-disable, ACTIVE_HIGH :81,90,…,144.
- Reset default: all inputs → tx-disable high → lasers off. U-Boot never writes it.
- Two separate I2C buses: SFP data (GPIO 9-16 + derived SCL) and the expander bus (GPIO 22/23).

### Laser control from U-Boot **[LIVE]**

- `rtk network on` registers the PCA9534 as `rtk i2c` device 8 (TP-Link profile; nine `I2C device init` lines = SFP EEPROMs 0-7 + expander).
- `rtk i2c write 8 1 <mask>; rtk i2c write 8 3 0` (bit N = 1 keeps cage N+1 off; `0xfe` = cage 1 only).
- `SFP insert init` (`FUN_83f212b8`) only sets GPIO0-7 as inputs. EEPROM/media/`tx dis set` strings at `0xc24xx` have no code references (Linux RTCORE only).
- `rtk ext-pinSet` drives an RTL8231 (wrong chip) **[SRC]** `uboot_cmd.c:468`.

---

## 4. Switch internals

### Boot flow

- Preloader (file offset 0 → `0x5080`) → U-Boot main text (`0x83f00000`) → `Hit Esc key to stop autoboot` (`bootdelay=1`) → `bootcmd=boota`.
- `boota` builds the kernel parameter block (`bootargs %lu`, `memsize`, `initrd_start`, `flash_start`, `ethaddr` at `0xb8ba4`+) and passes `bootargs` (empty by default → kernel built-in `console=ttyS0,115200`).
- RUNTIME header **[LIVE]**: magic `0x93000000`, name `RTK_SDK`, LZMA, 4,917,870 bytes, load `0x80000000`, entry `0x80283850`. Loaded from `0x81000000`.

### Hardware profile `RTL9303_8XGE`

- `rtk show hw_profile_list` → `RTL9303_8XGE` = `9300015` **[LIVE]**.
- From relative offset `0x54`, `0x610` bytes are identical between our loader (`0xa2c24`) and the ST5008F v2 loader (`0x9d194`): packed SDK ports 0, 8, 16, 20, 24, 25, 26, 27, 28 (index 0-7; port 28 index `0xff`). Records differ from `0x664`.

### Chip revision

- **[SRC]** `chip_probe.c:_drv_swcore_cid9300_get:342-347`: `RTL9300_MODEL_NAME_INFO_ADDR = 0x4` → MMIO `0xBB000004`; rev = bits[3:0] (1 = B, 2 = C, 3 = D); `(reg >> 4) & 0x3` nonzero = 8XG variant.
- This unit: **rev B** (OpenWrt `SoC Type: Realtek RTL9303 rev B (6487)`). `md.l 0xBB000004` not read live.

### SerDes 10GR construct tables **[SRC]**

`rtk sdsreg set 0 <sds> <page> <reg> <data>`; table picked by `HWP_CHIP_REV` (`dal_longan_construct.c:2712-2726`, `:1102,1112`).

rev B `rtl9300_bT_sds_10gr_1000Bx[]` /*10G*/ `dal_longan_construct.c:72-78`:
```
{0x21,0x02,0x03C0}{0x21,0x05,0x40B0}{0x21,0x08,0x0000}{0x2E,0x00,0x0748}
{0x2E,0x01,0x2088}{0x2E,0x02,0xD020}{0x2E,0x09,0xF000}{0x2E,0x13,0x027F}
{0x2E,0x14,0x1179}{0x2E,0x16,0x00CB}{0x2E,0x17,0xA100}{0x2E,0x18,0xBE48}
{0x2E,0x1E,0x07FF}{0x2A,0x12,0x2034}{0x2F,0x02,0x1007}{0x2F,0x05,0x787C}
{0x2F,0x07,0x8100}{0x2F,0x0A,0x7C7F}{0x2F,0x0F,0x0121}{0x2F,0x11,0x8840}
{0x2F,0x13,0x0050}{0x2F,0x16,0x4000}{0x2F,0x17,0x4108}{0x2F,0x18,0xAE83}
```

rev C `rtl9300_cT_sds_10gr_1000Bx[]` /*10G*/ `dal_longan_construct.c:134-140`:
```
{0x2E,0x00,0x8648}{0x2E,0x01,0x2088}{0x2E,0x02,0xD020}{0x2E,0x09,0xF000}
{0x2E,0x13,0x027F}{0x2E,0x14,0x1279}{0x2E,0x16,0x00CB}{0x2E,0x17,0xA100}
{0x2E,0x18,0x3E48}{0x2E,0x1E,0x07FF}{0x2E,0x12,0x2044}{0x2F,0x02,0x1007}
{0x2F,0x05,0x787C}{0x2F,0x07,0x8100}{0x2F,0x0A,0x7C7F}{0x2F,0x0F,0x01A1}
{0x2F,0x11,0x8840}{0x2F,0x13,0x0050}{0x2F,0x16,0x4000}{0x2F,0x17,0x4108}
{0x2F,0x18,0xAE83}{0x2F,0x19,0x4906}{0x2F,0x1A,0xA12B}{0x2F,0x1C,0x6109}{0x2F,0x1F,0x3500}
```
- Both preceded by `{0x21,0x02,0x03C0}{0x21,0x05,0x40B0}{0x21,0x08,0x0000}` and a /*1G*/ block (pages `0x24/0x25`, 1000Base-X).
- Construct values only; the driver also runs rxCaliConf, rxCali, clk_routine, linkFault_check, txParam around them.

### Datapath registers and hand-derived pokes

Base `0xBB000000`.

| Register | Address | Notes |
|---|---|---|
| `RTL9300_SMI_GLB_CTRL` | `0xCA00` | `entftp` writes `0x0fcb5500` |
| `MAC_FORCE_MODE_CTRL(port)` | `0xCA1C + (port<<2)` | port 0 `0xCA1C`, CPU 28 `0xCA8C`. bit0 MAC_FORCE_EN, bit1 FORCE_LINK_EN, bit2 DUP, [6:3] SPD, bit9 FORCE_FC. `0x217` force-links port 0 |
| `MAC_L2_PORT_CTRL(port)` | `0x3268 + (port<<6)` | port 0 `0x3268`, CPU `0x3968`. bit0 RX_EN, bit1 TX_EN. Live port 0 = `0x33` |
| `L2_UNKN_UC_FLD_PMSK` | `0x9064` | bits[28:0] portmask; includes port 0 + CPU 28 after `network on` |
| `L2_BC_FLD_PMSK` | `0x9068` | as above |
| `MAC_L2_CPU_PORT_CTRL` | `0xC70C` | |
| `MAC_LINK_STS` | `0xCB10` | force-mode bits; `0x10000001` = port 0 + CPU 28 forced up |
| `RTL9300_TBL_PORT_ISO_CTRL` | indirect table | per-source dest matrix, `v = dest_matrix << 3` (OpenWrt `rtl930x.c:113-139`); HW default all-forward |
| MIB port N | `0x0664 + (N+1)*256 - 4 - offset` | port 0 TX ucast `0x708`, RX ucast `0x70C`, TX mcast `0x710`, TX bcast `0x718` |
| GPIO block | `0xB8003300` | see [hardware.md](hardware.md) Method B |

- Vendor `entftp` / `enp0` recipe (D-Link DMS-1250, `uboot-dms1250/include/configs/cameo/dlink_customer.h`), all accepted by this loader:
  ```
  entftp = rtk network on; mw 0xBB00ca00 0x0fcb5500; mw 0xBB00ca1c 0x00000217; run enp0
  enp0   = rtk sdsreg set 0 2 7 17 0x54f; rtk sdsreg set 0 2 6 14 0x55a;
           rtk sdsreg set 0 2 7 16 0x6003; rtk sdsreg set 0 2 6 19 0x68c1;
           rtk sdsreg set 0 2 6 20 0xf021; rtk phymmd set 0 0 4 0xc441 0x8
  ```
  `enp0` targets sds2 = cage 1. Values are DMS-1250-specific; not needed on this unit.
- NIC driver (`drv_nic_init`) configures only CPU port 28: UNKN_UC flood mask, `MAC_L2_PORT_CTRL(28)` TX/RX enable, MAC force link-up. The 9310 path also adds CPU to the BC mask + VLAN 1; the 9300 path does not.
- Bootloader compiles out front-port L2 setup **[SRC]** `dal_longan_mapper.c:147-262` (`dal_longan_switch_init`, QoS/VLAN/STP/ACL, port admin). Reduced `dal_longan_init` set: sds/phy/flowctrl/port/l2/eee/trunk/stack.
- Despite that, front↔front forwarding is active after `network on` (the cage loop, [hardware.md](hardware.md#hazards)).
- Manual L2 recipe derived from source (RMW, after `rtk network on`; not needed on this unit): `0xBB003268 |= 0x3`, `0xBB003968 |= 0x3`, `0xBB00CA8C |= 0x203`, `0xBB009064 |= 0x10000001`, `0xBB009068 |= 0x10000001`.
- Software NIC counters **[LIVE]**: successful TX submissions `0x83fc2758`, failures `0x83fc2754` (incremented by `0x83f1ed80`); NIC init flag `0x83fc27e0` = 1; chip-family index `0x83fa1dc4` = 0. TX ring `0xa3df4078`; doorbell callback `0x83f678e0` writes offset `0xe028`. RTL9300 tag callback `0x83f67e8c` builds no tag when the tag-present bit is clear (both loaders clear it).

### Runs only under Linux

- waMon (adaptive RX re-cali on link change), SFP framework (laser, DOM, LOS), full L2/VLAN/STP/CPU-tag config.

---

## 5. Recipe

Fresh boot, at `RTL9300#`:
```
rtk network on
rtk i2c write 8 1 0xfe        # cage 1 laser only
rtk i2c write 8 3 0
setenv ipaddr <switch-ip>; setenv serverip <tftp-server-ip>
tftpboot 0x84f00000 st1008f.bin
iminfo 0x84f00000
```
Verified on cage 1 and cage 2 (5,383,940 bytes, `iminfo` checksum OK). Session: [../artifacts/uboot-10g-tftp-bootm-20261008.log](../artifacts/uboot-10g-tftp-bootm-20261008.log).

## Open

- `md.l 0xBB000004` live chip-rev read (OpenWrt already reports rev B).
- `rtk macsds set` mode enum beyond `10gr` = 2.
- Whether a TFTP send path exists anywhere in the loader (no `tftpput` string).
