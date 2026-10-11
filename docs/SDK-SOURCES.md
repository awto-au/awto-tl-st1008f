# Realtek switch SDK sources (RTL930x "Longan")

Every public Realtek switch SDK ("rtk-ms-sdk") drop found, its version and whether it carries Longan code. Search date 2026-10-12. Issue #76 (diff summary posted there).

- Version = `RT_VERSION_SDK` in `include/common/rt_version.h`, or the `rtk-ms-sdk-X.Y.Z.REV` dir name. `[SDK_x.y.z]` tags in `include/rtk/*.h` = API change history, **not** the release: DMS-1250 has tags up to 3.8.0 but is release `3.6.9.55156`.
- `REV` (e.g. `55156`) = Realtek SVN revision; branches overlap (3.8.2.55016 is older than 3.6.9.55156).
- Script: `scripts/sdk_version_scan.py scan TREE...` (version + Longan presence), `diff OLD NEW` (Longan-relevant diff). Log `tmp/logs/sdk_version_scan.log`.
- TP-Link GPL tarballs were triaged without saving them: streamed through the browser (`fetch` + `DecompressionStream` + tar header walk) to list paths and read `rt_version.h`.

## Source drops

| Product (GPL) | Date | SDK | Longan content | URL | Local |
|---|---|---|---|---|---|
| TP-Link SG3218XP-M2 V2.0 (`rtk_longan_gpl`) | 2026-04-16 | **4.0.2.55154** (dir name; `rt_version.h` = `TRUNK_CURRENT`; highest API tag 4.0.3; files dated 2023-08-16) | chipdef/longan headers, full `include/rtk`, full `system/drv` (NIC, I2C, GPIO, intr, l2ntfy, swcore), 114 hw profiles. `src/` (dal, hal/mac, rtk) = 0-byte stubs / dangling symlinks; U-Boot build keeps 13 `dal_longan_*.o` with DWARF | https://static.tp-link.com/upload/gpl-code/2026/202604/20260416/SG3218XP-M2(UN)2.0_GPL.gz (686,077,529 B, sha256 `9c688eb3…83bc`) | `private/tplink-gpl-sg3218xp-m2-v2/` |
| TP-Link SG3210X-M2 V1.20 (`rtk_longan_gpl`) | 2025-12-26 | 4.0.2.55154 | same tarball as SG3218XP-M2 (same byte count, same 107,781 entries) | https://static.tp-link.com/upload/gpl-code/2025/202512/20251226/SG3210X-M2(UN)_V1.20_GPL.gz | — |
| TP-Link SG2210XMP-M2 V1.20 (`rtk_longan_gpl`) | 2026-01-29 | 4.0.2.55154 | same SDK layout (746,455,648 B) | https://static.tp-link.com/upload/gpl-code/2026/202601/20260129/SG2210XMP-M2(UN)_V1.20_GPL.gz | — |
| TP-Link SX3008F V2 (`rtk_mango_gpl`, RTL9310) | 2026-08-06 | 4.0.2.55154 | no Longan dal; chipdef only | https://static.tp-link.com/upload/gpl-code/2026/202608/20260806/SX3008F(UN)2.0.tar-GPL.gz (686,773,000 B) | — |
| TP-Link SG3428X-M2 V1.30, SG3428XPP-M2 V2.0 (`rtk_mango_gpl`) | 2026-01-22/23 | 4.0.2.55154 | as SX3008F V2 (same byte count) | Omada product pages | — |
| TP-Link SG3428X V2.0, SX3032F 1.20, SG3452X 1.30, SG3428XF 1.30 | 2025-12 – 2026-09 | — | Marvell AC3/AC5, no Realtek | Omada product pages | — |
| D-Link DMS-1250 series (mirror `github.com/reyalo/Realtek` `sources/rtk-dms1250`) | — | **3.6.9.55156** (API tags to 3.8.0) | full src: dal/longan 29 `.c`, chipdef, system/drv | https://svanheule.net/switches/gpl/DMS-1250-SERIES-GPLSourceCode.tar.gz | `private/reyalo-Realtek/sources/rtk-dms1250` (sparse) |
| Zyxel XGS1210-12 (mirror reyalo `sources/rtk-xgs1210`) | OSC 2020-11-16 | `TRUNK_CURRENT` (API tags to 3.7.0) | full src incl. hal/mac | https://svanheule.net/switches/gpl/XGS1210_OSC_20201116.7z | `private/reyalo-Realtek/sources/rtk-xgs1210` (sparse) |
| Zyxel XGS12xx (olliver) | 2020-2022 | 3.5.0 | full src | https://gitlab.com/olliver/openwrt/realtek_sdk (`github.com/olliver/realtek_sdk`) | not on disk |
| Cudy GP3000 (`github.com/jameywine/GPL-for-GP3000`), BPI-RT2 (`github.com/BPI-SINOVOIP/BPI-RT2`) `rtl82xx` | 2025, 2026 | 3.8.2.55016; `rtk-ms-phyOnly` 3.6.8.55120 (API tags to 4.2.0) | PHY-only SDK (RTL826x drivers): chipdef/longan headers + `include/dal/longan` headers, no dal sources | `linux-5.10.x/drivers/net/ethernet/realtek/rtl82xx/sdk` | — |
| TRENDnet TEG-S750 (`github.com/danieltwagner/teg-s750`) | 2023 | ? | U-Boot `board/Realtek/switch/sdk`: sources are symlinks into a stripped tree | `gpl_oss_of_realtek_sdk3/` | — |
| Zyxel XGS1210-12 v2, XGS1250, XGS1010; Netgear MS108EUP/MS308EUP, MS510TXM | 2020-2023 | not checked (7z/xz/zip; svanheule mirror blocks in-browser streaming) | unknown | https://www.svanheule.net/switches/gpl_source_drops | — |

## Binary-only (firmware, no source)

| Firmware | SDK string |
|---|---|
| TL-ST1008F v2 stock (`/bin/diag`, `rtk.ko`) | 3.6.6.55087 |
| TL-ST5008F v2 1.2.0, ST5008 v1 1.0.1 (`core`, `diag`) | 3.6.9.55156 |
| SX3008F V2 2.0.0 build 20260720 (`core`, RTL9310) | 4.0.2.55154 |

## Not found

- No public drop newer than 4.0.2.55154. `[SDK_4.2.0]` / `[SDK_3.6.10]` tags in the GP3000 phy-only tree prove later releases exist.
- No GPL from Hasivo, XikeStor, Horaco, ONTi (`github.com/carlosz1986/mod_hasivo_switch_firmware` = stock-firmware tooling). TP-Link China (ST1008F/ST5008F) publishes no GPL.
- GitHub code search (`dal_longan`, `RT_VERSION_SDK`, `[SDK_3.9`, `[SDK_4.`, `rtk-ms-sdk`) finds only the repos above plus OpenWrt/LEDE forks.

## 4.0.2.55154 vs 3.6.9.55156 (DMS-1250), Longan only

Reproduce: `scripts/sdk_version_scan.py diff private/reyalo-Realtek/sources/rtk-dms1250 private/tplink-gpl-sg3218xp-m2-v2/rtk-ms-sdk-4.0.2.55154/sdk`.

- **Registers/tables: none new.** All five `chipdef/longan` reg/table headers are byte-identical.
- `rtk_longan_uboot_feature_def.h` now defines: `NIC___DMA`, `VLAN_PROFILE`, `IEEE802_1V__PROTOCOL_BASED_VLAN`, `VLAN_RANGE_CHECK`, `DEBUG_COUNTER`, `HSM`, `DEBUGGING__ALE__LOOPBACK__DROP_MECHANISM__FC_AND_QM_` (U-Boot build features; same registers).
- New chip families: `bumblebee` (RTL9311B/BR/BM), `tigershark` (RTL9330). `RTL9302DE_CHIP_ID` removed from `chip.h`.
- rtk API: 1618 → 1755 (+148/-11). Almost all new calls are 9311B/9330-only. New ones that list 9300: `rtk_chip_attach/detach`, `rtk_exit`, `rtk_diag_regField_read`, `rtk_diag_regArrayField_read/write`, `rtk_vlan_portProtoDblVlan_get/set`, `rtk_port_serdesMedia_get/set` (rename of removed `rtk_port_10gMedia_*`). Also removed: `rtk_port_fiberDownSpeedEnable_*`, `rtk_capwap_*`, `rtk_unit_attach/detach`.
- New API modules (9311B/9330): `ser`, `buffmgmt`, `tsn`, `evpn`, `flow`, `otp`, `ecn`, `nv`.
- **NIC (`system/drv/nic/nic.c`, kernel-mode driver used on 9300)**:
  - RX buffer alloc failure no longer stalls the ring: ring marked in the `NIC_RX_RUNOUT` interrupt mask, refilled later; mailbox routine now per ring.
  - Packet headers cache-flushed after refill (`osal_cache_memory_flush`); headers aligned (`aligned_pktHdr_size`).
  - RX copy reads through `UNCACHE()` addresses; `buf_addr` no longer forced uncached.
  - New `drv_nic_exit`, `_nic_ring_buff_release` (unload path), `drv_nic_desc_init`; `drv_nic_isr_handler` removed.
- `nic_rtl9300.c`: + `r9300_cpuTxTagFromRaw_cnvt` (decode a raw TX CPU tag: fwd_type, ACL/L3 act, priority, FVID, SPN, dst port masks), + `r9300_cpuTagLen_get`. No ring/DMA changes.
- New `nic2.c` driver is built only for 9311B/9330.
- `i2c_rtl9300.c`: the two `while(1)` waits on `I2C_MST{1,2}_CTRL1.I2C_TRIG` became `WAIT_COMPLETE(1000000)` with `RT_ERR_FAILED` on timeout (bus hang no longer locks the CPU).
- `intr` / `l2ntfy` / `swcore` / `watchdog` / `uart`: init/exit split (module unload), l2ntfy gains age/learn thresholds and congestion-drop config, `hsuart_baudrate_set`. `gpio.c`: GPIO bit-bang I2C (`drv_gpio_i2c_*`) and PoE-reset GPIO hooks.
- **Prebuilt `dal_longan_*.o` (U-Boot, `-g -Os`, GCC 4.8.5, MIPS32r2)**: 13 modules (common, construct, eee, flowctrl, l2, mapper, port, sds, stack, stp, switch, trunk, vlan). New symbols vs 3.6.9 source:
  - sds: `dal_longan_sds_rxCaliStatus_get`, `_dal_longan_sds_rxCali_a_start_1d2d6` (extra RX-calibration step).
  - construct: `dal_longan_construct_phy_sdsRx_reset`, `dal_longan_construct_sdsPortPolling_enable/disable`, `dal_longan_construct_macpollingphy_phy_init`.
  - port: `_dal_longan_port_macForceSpeed_set`; l2: `_dal_longan_l2_getL2Entry_srch`.
  - Missing from the `.o` (PRBS/test-pattern setters, `*_init_config`) = U-Boot build config, not removal.
- Not obtainable from any 4.x drop: dal/longan C source, `hal/mac` (SerDes/reg access), `dal_longan_waFunc` (workarounds), rtcore/rtnic Linux glue. Errata/workaround diff is limited to the `.o` symbols above.
- hw profiles: 31 added (TP-Link boards `rtl9302c_sg3210x_m2`, `rtl9302c_sg3218xp_m2`, `rtl9302c_sg2210xmp_m2`; `rtl9303_2x8264*`; 9311B/9330 boards). `rtl9303_8xge` (8× 10GBASE-R, = this board's layout): same ports/SerDes 2-9, only the hwp struct format changed (`chip_id = HWP_CHIP_AUTOPROBE`, `.sds = HWP_1SDS(n)` replaces `.sds_idx`, new `phy_mdi_pin_swap`, `led_signal_invert`).
