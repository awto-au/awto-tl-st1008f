# RTL9303 SDK feature map (Longan)

Every API slot and hardware feature group the Realtek SDK compiles for the RTL930x (Longan), and who uses it. Issue #76.

- Do not repeat: register-level hidden items [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (#68), debug/test leftovers [SDK-LEFTOVERS.md](SDK-LEFTOVERS.md) (#74), datasheet features [DATASHEET-AUDIT.md](DATASHEET-AUDIT.md) (#69), SoC blocks [HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md) (#62), NIC tuning [VENDOR-NIC-TUNING.md](VENDOR-NIC-TUNING.md).
- Script: `scripts/sdk_feature_map.py` (offline). Full machine tables: `tmp/sdk_feature_map/sdk_feature_map.json`, `api.csv` (1409 rows), `regs.csv` (1308), `tables.csv` (35).
- `--write-doc` regenerates the [generated block](#generated-tables).

## Sources

- **[GPL]** `github.com/reyalo/Realtek` `sources/rtk-xgs1210` (SDK 3.7.0) = primary; `rtk-dms1250` (3.8.0) = diff. Sparse clone needs `include/{rtk,dal,hal}`, `src/{rtk,dal,hal/common}`, `system/include/hwp`, `src/app/diag_v2`.
- olliver `realtek_sdk` 3.5.0: not on disk (env `OLLIVER_SDK` unset); not used.
- **[STOCK]** TL-ST1008F `rtk.ko` (relocatable, symbols): call graph from relocations.
- **[MGD]** ST5008F v2 1.2.0 `core` (user-mode SDK, stripped, 33651 `.dynsym`): call graph from `jal` targets.
- **[OWRT]** OpenWrt `target/linux/realtek/files-6.18` (= our 7.3 port driver). **[OURS]** `uboot-port/board/tplink/tl-st1008f`, `openwrt/patches`.

## Method

- API slot = function pointer in `dal_mapper_t` (`include/dal/dal_mapper.h`). `dal_mgmt` fills all with `dal_common_unavail` (RT_ERR_CHIP_NOT_SUPPORTED), hooks `dal_phy` (PHY-layer, chip-independent), then the chip mapper overrides.
- States: `impl` (Longan DAL), `partial` (Longan DAL returns not-supported for some arguments), `phy` (only `dal_phy`; needs an external PHY driver), `unavail`.
- `#if 0` / `#if CODE_TBC` (defined 0 in `rt_type.h`) regions are dropped.
- Use = callers of `rtk_*` outside the SDK layers (prefix filter `rtk_|dal_|hal_|drv_|rt_|...`). Static only: a call site is not proof it runs.
- HW groups = `CONFIG_SDK_CHIP_FEATURE_*` sections of `rtk_longan_reg_list.c` / `table_list.c`. SDK ref = `LONGAN_<NAME>r|t` name in DAL / HAL / system / diag (both trees).
- OpenWrt / ours ref = register offset or `RTL930X_<NAME>` match on 930x lines: heuristic upper bound. Code using raw constants (I2C, LED, SerDes drivers) shows as unreferenced in the SDK columns.

## Counts

- 1409 API slots; Longan: 796 impl + 7 partial + 87 phy-only = 890 usable; 519 unavail. Mango 1050, RTL8390 700, RTL8380 594.
- SDK 3.8.0 (DMS-1250) adds 1 Longan slot (`port_phySds_set`); no slot removed.
- No Longan slot is a pure stub; `Applicable:` doc lines in `src/rtk/*.c` agree with the mapper (0 slots documented for 9300 but unavail).
- Modules with no Longan implementation: OpenFlow (73), MPLS (29), BPE/802.1BR (27), tunnel (17), VXLAN (9), EEE-plus (2), time/PTP (22, phy-only).
- 1308 registers, 35 tables, 59 feature groups. SDK names 426 registers (DAL 378); OpenWrt touches ~139, ours ~37. All 35 tables are used by the SDK.
- [STOCK] vendor code calls 27 APIs; everything else is `dal_longan_init` defaults (26 module inits).
- [MGD] TP-Link `drv*Realtek|Longan` layer (721 functions) calls 270 APIs; 588 implemented Longan APIs are never called by the managed firmware.

## Ranked shortlist

Ranked by value to this board (CPU offload, routing, monitoring, robustness). "New" = not in #62/#68/#69/#74 docs.

| # | Item | Status | Value here | Ref |
|---|---|---|---|---|
| 1 | Packet-buffer occupancy + peak watermarks | new; no API | monitoring, buffer tuning | [1](#1-packet-buffer-occupancy-and-peak-watermarks) |
| 2 | Interrupts SDK/OpenWrt never enable | new | robustness | [2](#2-unused-interrupt-sources) |
| 3 | Attack-prevention engine + hit status | engine #69; status new | CPU protection | [3](#3-attack-prevention-hit-status) |
| 4 | L2 learn limits + counters | limits #69; counters new | CPU protection | [4](#4-l2-learn-limits-and-learn-counters) |
| 5 | Per-meter colour counters | new; no API | policer debug | [5](#5-per-meter-colour-counters) |
| 6 | Parser drop reason, internal ports 29/30 | new; no API | drop diagnosis | [6](#6-parser-drop-reason-and-ports-2930) |
| 7 | Switch-IP / CAPWAP special traps | new; no API | CPU path | [7](#7-switch-ip-and-capwap-special-traps) |
| 8 | No ECMP, VRF, tunnels, IP-MAC bind, PTP | answered | routing scope | [8](#8-absent-ecmp-vrf-tunnels-ip-mac-binding-ptp) |
| 9 | VRRP router MAC in hardware | new; impl, unused | routing HA | [9](#9-vrrp-in-hardware) |
| 10 | IPMC counters, flexible MIB range | new; impl, unused | monitoring | [10](#10-ip-multicast-counters-flexible-mib-range) |
| 11 | MAC EEPROM autoload | new; undocumented | probe only | [11](#11-mac-eeprom-autoload) |
| 12 | I2C slave register interface | new; undocumented | none | [12](#12-i2c-slave-register-interface) |
| 13 | SMI PHY-register checker | new; undocumented | none | [13](#13-smi-phy-register-checker) |
| 14 | 802.1Qav / AVB SR classes | impl, unused | none | [14](#14-8021qav--avb) |
| 15 | RLDP/RLPP frame trap | impl, unused | loop safety (minor) | [15](#15-rldp--rlpp-trap) |

### 1. Packet-buffer occupancy and peak watermarks

- Regs: `FC_GLB_PAGE_CNT` 0xD8FC, `FC_GLB_PAGE_PEAKCNT` 0xD974, `FC_PORT_PEAK_PAGE_CNT` 0xD9EC + 4*port (cur [27:16], peak [11:0]), `FC_PORT_PAGE_CNT` 0xD900, `FC_PORT_CUR_PAGE_CNT` 0xD978.
- Per queue: `FC_PORT_Q_EGR_PAGE_CNT_SET0/1`, `FC_PORT_Q_EGR_PKT_CNT_SET0/1`, `FC_CPU_Q_EGR_PAGE_CNT` 0x7E40, `FC_CPU_Q_EGR_PKT_CNT` 0x7EC0; replication queue `FC_REPCT_Q_HSM/HSA_CNT` (cur + peak).
- No SDK API reads any of them (only `swcore_rtl9300.h` defines); not in OpenWrt or ours.
- Use: buffer high-water per port/queue under the 10G-to-CPU and routed bursts; tune `FC_GLB_*` thresholds (#69 row 22); CPU-queue backlog for #60. Read-only.

### 2. Unused interrupt sources

- `IMR_*` / `ISR_*` 0xC62C-0xC694: `SERDES_LINK_FAULT_P`, `SERDES_RX_SYM_ERR`, `OAM_DYGASP`, `TM_RLFD`, `AUTO_REC`, `SDS_UPD_PHYSTS`, `ROUT_LPBUF` (`ROUT_PBUF`, `ROUT_L2_NTFY_BUF`), `EXT_GPIO0/1`.
- SDK DAL names 2 of 28; OpenWrt uses the link-change pair only.
- Use: IRQ on SerDes link fault / symbol errors (cages, #25) and on packet-buffer auto-recover events (#74) instead of polling.

### 3. Attack-prevention hit status

- Engine (`ATK_PRVNT_*` 0xA1A8-0xA1C8): 17 of 25 `sec_*` slots impl; [MGD] uses 3; OpenWrt none. Feature list: #69 row 31.
- New: `ATK_PRVNT_STS` 0xA1C4, one status flag per check (19 flags: `DA_EQUAL_SA`, `LAND`, `UDP/TCP_BLAT`, `POD`, `IPV6_FRAG_LEN_MIN`, `ICMP_FRAG_PKT`, `ICMPV4/6_PING_MAX`, `SMURF`, `TCP_HDR_MIN`, `SYN_SPORT_LESS_1024`, `NULL_SCAN`, `XMAS`, `SYN_FIN`, `SYN_RST`, `TCP_FRAG_OFF_MIN`, `IPV4_INVLD`, `ARP_INVLD`).
- No Longan getter; Mango has `sec_attackPreventHit_get`. Use: drop malformed WAN traffic in the ASIC before the CPU, with visibility.

### 4. L2 learn limits and learn counters

- Impl, unused by OpenWrt: `l2_limitLearningNum/Action`, `l2_fidLimitLearningEntry` (8 FID/VLAN entries), `l2_macLearningCnt_get`, `l2_entryCnt_get`, `l2_hashAlgo`/`bucketHashAlgo`, `l2_hashIdx_get`. [MGD] uses FID limits + aging.
- New: `L2_CONSTRT_{PORT,TRK,SYS,VLAN}_CNT_DBG` 0x93F0-0x9400 (below-zero flags), `L2_STT_PORT/TRK_MV_ACT` 0x9010/0x9020 (station-move action), `L2_PORT_{L2,IP4,IP6}_MC_LM_ACT`.
- Use: cap a MAC flood on the CPU-facing side; station-move action as a loop symptom (#43).

### 5. Per-meter colour counters

- `METER_CNTR_CTRL` 0xA0E8 (meter index [10:3], unit, clear); `METER_{GREEN,YELLOW,RED,TOTAL}_CNTR_STS` 0xA0EC-0xA0F8 (32 bit); `METER_LB_CTRL/LB_PPS_CTRL` 0xA0FC/0xA100.
- One meter at a time. No SDK API. Use: verify the 256 policers (#69 row 47) and storm meters.

### 6. Parser drop reason and ports 29/30

- `PARSER_DROP_REASON` 0x3288 + 0x40*port, 4-bit code; `PORT29/30_DBG_REG0/1` 0xDA68-0xDA74 (`P29_PAR_DP_CNT`: parser drops on internal ports 29/30).
- No SDK reader. Complements the drop-reason counters (#74). Code meanings not in the SDK.

### 7. Switch-IP and CAPWAP special traps

- `SPCL_SWITCH_IPV4_ADDR_CTRL` 0xA220, `SPCL_SWITCH_IPV6_ADDR_CTRL` 0xA224 (128 bit), `SPCL_TRAP_CAPWAP_PORT_CTRL` 0xA234 (UDP dport); `SPCL_TRAP_CTRL` 0xA238 `IP_CMP`, `CAPWAP`, `CAPWAP_TRAP_TARGET`.
- SDK uses `SPCL_TRAP_CTRL` for other actions only; the address compare has no API.
- Use: classify frames to the switch's own IP (management) apart from routed traffic on the CPU path (#60). Untested.

### 8. Absent: ECMP, VRF, tunnels, IP-MAC binding, PTP

- `rtl9300_capacityInfo`: `max_num_of_l3_ecmp` 0, `vrf` 0, `tunnel` 0, `ip_mac_bind_entry` 0, `time_nsec_max` 0, `wred_weight_max` 0.
- Longan reg list has no ECMP, binding, CFM/CCM, ingress-queue bandwidth, private-VLAN or PTP-timestamp register.
- `time_*` slots resolve to `dal_phy` only: PTP needs a PHY with 1588 (none here; #62 row PTP).
- [MGD] still calls `rtk_l3_ecmp_create`, `oam_cfmCcm*`, `trap_routeExceptionAction_set`: these return not-supported on the 9303 (shared multi-chip code).
- Mango-implemented, Longan-unavail slots: vlan 20, oam 42 (CFM CCM, ETH-DM), rate 10 (ingress-queue BW), sec 8 (IP-MAC bind, hit), l3 8 (ECMP, intf stats), stack 9, pie 6, trap 4, flowctrl 4. Register absence checked for the items named above only.

### 9. VRRP in hardware

- `l3_vrrp_add(vid, vrId)/del/delAll/get` impl: writes the VRRP virtual MAC into the router-MAC table (64 entries) for a VLAN. [MGD] uses add/del.
- Use: two routers sharing a gateway MAC with ASIC routing intact. Not in OpenWrt.

### 10. IP-multicast counters, flexible MIB range

- `ipmc_statCntr_get/reset`, `stat_flexibleCntRange_get/set` (packet-length bucket for a MIB counter), `stat_tagLenCntIncEnable`: impl, unused by [MGD] and OpenWrt.
- Low value (no multicast routing here).

### 11. MAC EEPROM autoload

- `MAC_EEPROM_DOWN_LOAD_CNTRL` 0xC6E4 (`SCK_FREQ_SEL`, `EEEPOM_VALID`), `_STS` 0xC6E8 (`NOEEPROM`, `EEPROM_COMPL`, `EEPROM_VALID_FAIL`), `_MAC/SERDES/PHY/GROUP_MAC_POS` 0xC6EC-0xC6F8.
- Reset-time register load from a serial EEPROM (unmanaged-switch mode). Not in the DS, no SDK code.
- Board: CPU-managed; `_STS` (read-only) shows whether an autoload EEPROM is present. Not probed.

### 12. I2C slave register interface

- `MAC_IF_CTRL` 0x360, `MAC_SLV_I2C_CTRL` 0x364 (`CFG_SDA_DLY`, `I2C_DATA_ENDIAN_SEL`), `MAC_SLV_TIMEOUT` 0x368.
- External-CPU register access over I2C; the DS documents only the SPI slave (#69 row 3). None here.

### 13. SMI PHY-register checker

- `SMI_REG_CHK1..5_{CTRL0,CTRL1,PMSK,DATA,DATA_10G,RESULT}` 0xCA94-0xCB08: hardware polls one MDIO PHY register per set across a port mask and compares (mode [22:21], page).
- No SDK code. None here (no MDIO PHYs; GLC-T PHYs sit behind I2C).

### 14. 802.1Qav / AVB

- `qos_avbStreamReservationConfig`, `qos_portAvbStreamReservationClassEnable` impl; `AVB_PORT_CLASS_A/B_EN` 0xA240/0xA244, `AVB_CTRL` 0xA248.
- Per-port SR class A/B enable + SR config. No AV traffic here (#69 row 55).

### 15. RLDP / RLPP trap

- `RLDP_RLPP_CTRL` 0xA250: `RLDP_RLPP_TRAP`, `DROP_MY_DEV`, `MY_DEV_ID`, `STK_PORT_SEL`. Hardware only recognises Realtek loop-detect frames; detection is software.
- Bridge STP covers loops (#43); a software RLDP would need this trap.

## Other facts

- SKU gating: none for features. One `rtl9300_capacityInfo` for RTL9301/9301H/9302A-F/9303. DAL chip-ID checks select only port map, SerDes TX parameters, FC threshold model and stacking e2e FC (`dal_longan_construct.c`, `_sds.c`, `_stack.c`). Consistent with #68 (CHIP_MODE read-only).
- `partial` slots: `mcast_group_create/destroy`, `mcast_nextHop_*` (IP group types only), `l2_conflictAddr_get`, `eee_portEnable_set` (port-type dependent).
- [STOCK] vendor callers: SFP media/autoneg/admin/FC (`tpSfpSetType`, `tpSfpElecSetType`, `tp_flowctrl_init`), jumbo (`adPortJumboInit`), OAM PDU trap (`adPortOAMInit`), power-on LED blink (`tp_led_powerOn_blink`), SerDes eye/LEQ utilities, `_rt_test_*` hooks. `rtk_port_10gMedia_set` and `phySdsEyeParam_*` go through `dal_phy`.
- [MGD] uses: L3 22 APIs (intf, nexthop, host, route, router MAC, VRRP), PBR (`drvPbr*`), sFlow + RSPAN, ACL 11 + PIE 8, meters, storm control, port/queue egress shaping, CPU egress rate mode, attack prevention, MSTP, LAG, IGMP/MLD + IPMC, ERPS/MRP (software CCM), SerDes eye params, 802.1X.

## Capacity (`rtl9300_capacityInfo`, all RTL930x SKUs)

| Resource | Size | Resource | Size |
|---|---|---|---|
| L3 host / route (LPM) | 6144 / 512 | nexthop / egress intf | 2048 / 128 |
| router MAC / MTU profiles | 64 / 8 | MC group nexthop | 130 |
| PIE blocks x entries / counters | 16 x 128 / 2048 | templates (user 5-9) | 10 |
| meters / blocks | 256 / 16 | range checks (L4/VLAN/IP) | 16 / 8 IP |
| VLAN ingress / egress xlate | 1024 / 512 | VLAN profiles / MAC-subnet groups | 8 / 8 |
| L2 learn limit max | 0x4040 | MC entries | 1024 |
| mirror sets / LAG groups x members | 4 / 64 x 8 | MSTI | 64 |
| CPU queues / stack queues | 32 / 12 | max frame | 12288 |
| RMA user-defined | 4 | LED entities | 4 |
| sFlow rate max | 0xFFFF | stack units | 16 |

## Generated tables

<!-- generated:begin -->
### API slots per module (`dal_mapper_t`)

| Module | Slots | Longan / Mango (incl. phy) | Stock / ST5008F use | 9300-doc but unimpl |
|---|---|---|---|---|
| qos | 151 | 95 / 95 | 0 / 12 |  |
| vlan | 148 | 102 / 122 | 0 / 27 |  |
| l2 | 127 | 85 / 85 | 2 / 42 |  |
| port | 104 | 101 / 102 | 13 / 32 |  |
| rate | 89 | 75 / 83 | 0 / 16 |  |
| flowctrl | 84 | 56 / 52 | 0 / 2 |  |
| trap | 75 | 49 / 53 | 1 / 4 |  |
| of | 73 | 0 / 73 | 0 / 0 |  |
| oam | 67 | 15 / 57 | 0 / 6 |  |
| acl | 67 | 32 / 30 | 0 / 11 |  |
| l3 | 51 | 39 / 47 | 0 / 22 |  |
| trunk | 41 | 31 / 33 | 0 / 15 |  |
| pie | 36 | 30 / 36 | 0 / 8 |  |
| switch | 31 | 23 / 23 | 1 / 4 |  |
| mpls | 29 | 0 / 25 | 0 / 0 |  |
| bpe | 27 | 0 / 27 | 0 / 0 |  |
| sec | 25 | 17 / 25 | 0 / 3 |  |
| stack | 23 | 14 / 22 | 0 / 9 |  |
| mirror | 22 | 20 / 20 | 0 / 11 |  |
| time | 22 | 20 / 20 | 0 / 17 |  |
| sds | 18 | 17 / 18 | 5 / 2 |  |
| tunnel | 17 | 0 / 17 | 0 / 0 |  |
| stat | 15 | 13 / 13 | 2 / 3 |  |
| ipmc | 12 | 12 / 12 | 0 / 5 |  |
| led | 12 | 12 / 12 | 3 / 3 |  |
| vxlan | 9 | 0 / 9 | 0 / 0 |  |
| stp | 8 | 8 / 8 | 0 / 5 |  |
| mcast | 8 | 8 / 8 | 0 / 7 |  |
| diag | 6 | 6 / 4 | 0 / 2 |  |
| init | 5 | 5 / 1 | 0 / 0 |  |
| eee | 5 | 5 / 5 | 0 / 2 |  |
| eeep | 2 | 0 / 0 | 0 / 0 |  |

### HW feature groups (`CONFIG_SDK_CHIP_FEATURE_*`)

| Group | Regs / tables | SDK refs (DAL / any) | OpenWrt | Ours |
|---|---|---|---|---|
| 802_1qav | 4 / 0 | 3 / 3 | 0 | 0 |
| 802_1q_vlan___qinq | 17 / 2 | 13 / 14 | 7 | 0 |
| acl | 3 / 3 | 2 / 2 | 1 | 0 |
| application_trap | 5 / 0 | 2 / 2 | 1 | 0 |
| attack_prevention | 10 / 0 | 8 / 8 | 0 | 0 |
| auto_recovery | 34 / 0 | 7 / 7 | 0 | 0 |
| bist___bisr | 144 / 0 | 1 / 1 | 0 | 0 |
| chip_information | 2 / 0 | 0 / 0 | 0 | 0 |
| congestion_avoidance | 9 / 0 | 4 / 4 | 0 | 0 |
| debugging__ale__loopback__drop_mechanism__fc_and_qm | 5 / 0 | 0 / 0 | 0 | 0 |
| debug_counter | 85 / 0 | 0 / 0 | 1 | 0 |
| device_control | 6 / 0 | 5 / 5 | 0 | 0 |
| egress_bandwidth_control | 31 / 0 | 22 / 22 | 1 | 0 |
| flowcontrol___backpressure | 80 / 0 | 35 / 35 | 0 | 0 |
| hsm | 95 / 0 | 0 / 0 | 0 | 0 |
| hw_misc | 47 / 0 | 1 / 1 | 0 | 1 |
| ingress_bandwidth_control | 8 / 0 | 6 / 6 | 2 | 0 |
| ingress_priority_decision | 17 / 0 | 16 / 16 | 3 | 0 |
| interface | 24 / 0 | 0 / 0 | 0 | 2 |
| interrupt | 28 / 0 | 2 / 2 | 4 | 0 |
| l2_entry_notification | 21 / 0 | 2 / 2 | 2 | 0 |
| l2_misc | 1 / 0 | 0 / 0 | 0 | 0 |
| layer_3_routing | 21 / 13 | 18 / 18 | 11 | 0 |
| led | 52 / 0 | 4 / 4 | 8 | 11 |
| link_aggregation | 10 / 2 | 8 / 8 | 6 | 0 |
| mac_control | 107 / 0 | 26 / 38 | 24 | 7 |
| mac_forwarding_control | 42 / 5 | 33 / 33 | 12 | 0 |
| meter_marker | 11 / 1 | 3 / 3 | 1 | 1 |
| mib_control | 6 / 0 | 5 / 5 | 3 | 0 |
| mib_counter | 2 / 0 | 2 / 2 | 1 | 0 |
| mirroring | 6 / 0 | 5 / 5 | 3 | 0 |
| misc | 10 / 0 | 0 / 0 | 0 | 0 |
| modifier_hsa | 23 / 1 | 0 / 0 | 0 | 0 |
| nic___dma | 20 / 0 | 2 / 2 | 8 | 1 |
| oam | 6 / 0 | 4 / 4 | 0 | 0 |
| parser | 4 / 0 | 2 / 2 | 0 | 0 |
| parser_hsb | 31 / 1 | 0 / 0 | 0 | 0 |
| phy___serdes | 28 / 0 | 11 / 11 | 7 | 6 |
| pie_template | 13 / 0 | 12 / 12 | 5 | 1 |
| pll___bias | 16 / 0 | 0 / 0 | 0 | 5 |
| port_isolation | 5 / 1 | 3 / 3 | 0 | 0 |
| power_saving | 40 / 0 | 2 / 2 | 1 | 0 |
| private_counter | 9 / 0 | 5 / 5 | 1 | 0 |
| range_check__port_vlan_ip_l4port | 4 / 0 | 3 / 3 | 0 | 0 |
| remarking | 18 / 1 | 17 / 17 | 0 | 0 |
| reset | 6 / 0 | 1 / 1 | 0 | 0 |
| rldp___rlpp | 1 / 0 | 1 / 1 | 0 | 0 |
| rma | 17 / 0 | 16 / 16 | 8 | 0 |
| rspan | 5 / 0 | 3 / 3 | 0 | 0 |
| scheduling___queue_management | 25 / 0 | 19 / 19 | 4 | 0 |
| sflow | 2 / 0 | 2 / 2 | 0 | 0 |
| smart_packet_generator | 24 / 0 | 0 / 23 | 0 | 0 |
| spanning_tree | 2 / 1 | 1 / 1 | 1 | 0 |
| storm_control__b_m_um_dlf | 29 / 0 | 25 / 25 | 0 | 0 |
| table_access | 18 / 0 | 2 / 14 | 12 | 2 |
| vlan_profile | 2 / 0 | 1 / 1 | 1 | 0 |
| vlan_range_check | 5 / 0 | 4 / 4 | 0 | 0 |
| vlan_translation | 9 / 4 | 7 / 7 | 0 | 0 |
| ieee802_1v__protocol_based_vlan | 3 / 0 | 2 / 2 | 0 | 0 |

<!-- generated:end -->

- Stock / ST5008F use = slots with at least one caller outside the SDK layers. 9300-doc but unimpl = `Applicable:` lists 9300, mapper unavail.
- HW columns: register counts; SDK = DAL-referenced / referenced by any SDK layer; OpenWrt / ours = offset match (heuristic).
