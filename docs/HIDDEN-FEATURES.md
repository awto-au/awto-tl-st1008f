# Hidden / undocumented hardware in the RTL9303 (Longan)

Catalogue of RTL9303 hardware that the datasheet omits, the SDK leaves unused, or the board does not enable. Issue #68 (catalogue, probes, experiments). Related: #62 ([HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md)), #70 (SPG), #74 ([SDK-LEFTOVERS.md](SDK-LEFTOVERS.md)), #75 (eFuse enable decision).

## Sources

- **[GPL]** Realtek SDK `github.com/reyalo/Realtek` `sources/rtk-xgs1210` and `rtk-dms1250`: `include/hal/chipdef/longan/*`, `src/hal/chipdef/longan/rtk_longan_{reg,regField,table,tableField}_list.c`, `system/include/private/drv/swcore/swcore_rtl9300.h`, `src/hal/mac/drv/drv_rtl9300.c` (table access), `src/hal/chipdef/chipdef.c` (SKUs), `src/dal/longan/dal_longan_construct.c`. Both trees: same 1308 registers, 35 tables.
- **[BIN]** stock TL-ST1008F `rtk.ko` and ST5008F v2 1.2.0 `core` (private): both embed `rtk_longan_reg_list` (148-byte entries with names) and `rtk_longan_table_list` (152-byte entries).
- **[SOC]** SDK U-Boot `uboot-xgs1210/arch/otto40/plr/src/platform/9300/register_map.h` (SoC side `0xb8xxxxxx`).
- **[DS]** `sources/rtl9303-cg-brief.pdf` Rev 1.1-1, `rtl9301-cg-datasheet-rev1.1.pdf`, `rtl9302d-cg-datasheet-excerpt-anoatech.pdf`.
- **[8390]** Realtek SDK 2.1.4 U-Boot `board/Realtek/switch/rtk/mac/rtl8390/rtl8390_init.c` (`github.com/tobyw121/Openwrt_RTL`): eFuse read sequence.
- **[MANGO]** same SDK, `chipdef/mango`, `dal_mango_openflow.c`. **[8686]** same SDK, `uboot-xgs1210/arch/otto/cpu/rlx5281/rtl8686/asicregs.h` (RTL865x-derived gateway ALE).
- **[LIVE]** measured on this board 2026-10-12 (details: [Measured](#measured-2026-10-12)).
- Offline scans: `scripts/hidden_sdk_scan.py` -> `tmp/hidden/sdk_scan.json`; `scripts/sdk_leftovers_scan.py` (#74). Live: `./dev.py hidden-probe`, `./dev.py hidden-write-probe`.

## Catalogue

| Item | What it is | Evidence | Measured value / behaviour | Possible use | Risk | Issue |
|---|---|---|---|---|---|---|
| Smart Packet Generator (SPG) | per-port line-rate traffic generator, `SPG_*` regs, `SMART_PACKET_GENERATOR` feature (Longan only) | GPL diag driver; absent from DS | `SPG_GLB_CTRL/TX_GRP_CTRL/GLOBAL_STS` 0x7AB0 = 0 (idle) [LIVE] | port/link stress test without a host; cage-loop test traffic | transmits frames: storm risk on the house LAN | #70 |
| `ROUTER_SMAC_SEL` + 48-bit SMAC | ECO knob: `DMY_REG1_PKT_ENCAP` 0xCF0C bit 16 + SMAC[47:32], `DMY_REG0_PKT_ENCAP` 0xCE20 SMAC[31:0]; SDK never references it | [GPL] field names | live flops: 0xCE20 r/w 32 bits, 0xCF0C r/w mask `0x0001ffff`; reset 0 [LIVE] | override router source MAC on routed frames (untested) | low (volatile) | #68 |
| `DMY_REG0_EGRESS_CTRL` 0x7918 | ECO knobs `STRIC_WFQ_JUMBO`[17], `SPD_UP_REFILL`[16], `AMP_FACTOR`[15:0] | [GPL] | reset `0x00030200` (both flags 1, AMP_FACTOR 0x200); dummy bits [31:18] r/w [LIVE] | egress shaper tuning (jumbo WFQ, token refill) | changes scheduling | #68 |
| `DMY_REG0_CHIP_MISC` 0x78 | `CFG_VOL_PRB_SEL`[4:2] (voltage probe select), `DSS_SEL`[1:0] (die speed sensor select) | [GPL] | reset `0x1c` (VOL_PRB_SEL 7, DSS_SEL 0); dummy [31:5] r/w; named fields not written [LIVE] | on-die voltage / speed observation (#38 overclock margins) | analog test mux: unknown | #68 |
| `DMY_REG0_CHIP_MISC_R` 0x230 "SS-501" | ECO enable written by SDK `dal_longan_construct.c` = `0xfffffff` | [GPL] | 0 after reset; `0x0fffffff` after stock `rtk network on` [LIVE] | already applied by stock; check OpenWrt/mainline do it too | none (SDK default) | #68 |
| Other `DMY_REG*` | 90 dummy registers across all blocks | [GPL] | 72/80 tested fully r/w flops, all 0 at reset; HSA/HSM dummies 0xB578, 0xB90C-0xB918 read-only 0; 0xA370 bits 30:5 r/w (+ `FORCE_ALL_PORT_SECOND_EGR_DROP`[31], `SFLOW`[4:0]); PLL/AFE dummies 0xE234/0xE288/0xE294 not written [LIVE] | unknown ECO knobs; none has a documented effect | writes may enable unknown ECO logic | #68 |
| CHIP_MODE / bonding | SKU select (RTL9301/9302x/9303 port + SerDes configuration) | `BONDING_REDEFINE_REG` 0x7C, `MAC_EFUSE_CTRL` 0xC6FC, `BOND_DBG` 0x228 [GPL]; SDK picks SKU from `MODEL_NAME_INFO` only | CHIP_MODE 14, BONDING_DEFINE_EN 1; writes of 15 and 0 to both regs ignored, whole-window diff 0 words: read-only reset-time copy [LIVE] | none: no software SKU change | - | #68 |
| eFuse / OTP | 256 x 16-bit, indirect `EFUSE_ACCESS_*` 0xC698-0xC6A4; SDK never reads it; RTL8390 stores SerDes (reg, value) patches in its eFuse | [GPL], [8390] | autoload at reset (`CTRL_DONE` 1); SW read path returns 0 for all 256 words with `EFUSE_ACCESS_EN` = 0; loaded copies: `CALIB_CTRL_2-4` `033c03f1 81308128 00000188`, `CODE_PROTECT_STATE` 0 [LIVE] | trim/patch values, unique ID | programming is permanent; `ACCESS_EN` meaning unknown | #62, #75 |
| `CHIP_INFO` 0x08 | extra ID register behind `CHIP_INFO_EN` = 0xA | [GPL] | `0x100a6487`: RL_VID 1, MCID 0, RL_ID 0x6487 [LIVE] | rev/variant identification | none | #62 |
| Unused table codes | free codes on the indirect table controllers: L2 3, CTRL_0 9-15, L3 6-7, HSB/HSA 1 | no BIST memory for them [GPL] | no RAM behind any: L2 3 and L3 6/7 complete with data untouched; CTRL_0 9-15 and HSB 1 never complete (controller locked until power cycle); HSA path unusable even for code 0 [LIVE] | none | a stuck controller blocks VLAN/ACL/meter access until power cycle | #68 |
| Register gaps (unnamed decode) | 44 holes >= 16 words in the 64 KiB switch window outside per-port blocks | [GPL] scan | every word of 43 holes reads 0; 0xE300-0xE91C was a scan miss (SET1 queue arrays); whole window readable, no hang; outside it (0xBB010000, 0xBB100000, 0xBB800000) the bus hangs [LIVE] | none found | reads safe in-window; out-of-window reads hang the CPU | #68 |
| Stock-only registers 0x98 / 0xD0 | link-fault mask / status, written by stock `LinkFaultMonIsrThread`, no SDK name | [BIN] | both 0 [LIVE] | link-fault interrupt | low | #68 |
| ALE loopback re-entry | `ACL_LB_ACT`, `LB_TTL`, `LB_PKT`, `TEST_MODE_ALE_LOOPBACK_CTRL` 0x7AAC: recirculate a frame through the pipeline | [GPL] | 0 [LIVE] | two-pass lookups (#63) | loop if misconfigured | #63 |
| HSB/HSA/HSM snapshots | parser output, modifier input and mid-pipeline state of the last frame, readable | [GPL] | hold the last LAN frame after `rtk network on` [LIVE] | per-frame pipeline debugging | none (read-only) | #68 |
| OCP / LX bus-timeout monitors | `TO_CTRL` 0xb8005100, `LB*TCR` 0xb8005200; GIMR `OCPTO`/`LXMTO`/`LXSTO` | [SOC] | not probed | turn a hung bus access (as above) into an IRQ with the address | low | #62 |
| GDMA / bus traffic generator | `LX0/1/2_GDMA_CTRL` 0xb8144000 / 0xb800a000 / 0xb8018000 + BTG regs; not in DS | [SOC] | not probed (clock-gated reads may hang) | memcpy/memset offload; DDR stress (#48) | DMA writes RAM | #62 |
| Speed sensors (ring osc) | `SPD_SENSOR0-8` 0xb8000618 | [SOC] | not probed | die speed for overclock limits (#38) | low | #62 |
| Timer TC5 | sixth timer; DS shows "Timer*5", SDK lists TC0-TC5 0xb8003200 | [DS], [SOC] | not probed | spare timer | low | #62 |
| Thermal comparators + max/min latch | high/low threshold interrupts, temperature latch; SDK unused | [GPL] | sensor 0x60-0x70 used; comparators not probed | over-temperature IRQ (#13) | low | #74 |
| ASIC drop-reason counters | `0xBB00B5B8 + 4*n`, 85 x 16 bit, 82 named in `mac_debug.c` | [GPL] | not probed | explain L3 traps/drops (#59, #65) | read-only (check clear-on-read) | #74 |
| SerDes test tools | eye monitor, PRBS9/31, TX eye params, loopback, error counters (`dal_longan_sds.c`) | [GPL] | not probed | cage link quality (#25) | disrupts the link while active | #74 |
| Packet-buffer auto-recover | HW error flags + SW queue reset (`dal_longan_waFunc.c`), in stock `rtk.ko`, not in OpenWrt | [GPL], [BIN] | not probed | robustness fix for OpenWrt/mainline | writes: use the SDK sequence | #74 |
| Crypto engine | `IPSEC_*` 0xb800c000 (legacy DES/3DES/AES, MD5/SHA1 SPEC) | [DS], [SOC] | see inventory | flash decrypt / legacy ciphers | low | #62 |
| NAT / IP or L4 rewrite | hardware NAT or header rewrite fused off or undocumented | see [below](#nat--ip-rewrite-hardware-none) | none exists | - | - | #68 |

## NAT / IP rewrite hardware: none

- Answered: no. The egress modifier has no input that could carry a new IP address or L4 port, its memories are all accounted for, and no free table code has RAM behind it (measured). NAT stays on the CPU path ([NAT.md](NAT.md)).
- Pipeline (clock-gate bits `PS_GATCLK_EN` 0xC7A4 `[5:0]`): IGR_CTRL -> PKT_PRS (output HSB) -> ALE (output HSA) -> EGR_CTRL -> PKT_ENCAP (modifier) -> MAC. `[31:6]` reserved.
- **HSB** (30 words, 0xB4A0): `SIP`, `DIP`, `SPORT`, `DPORT`, `IPV4_CHKSUM_OK`, `L4_HDR_CHK` = match keys only.
- **HSA** (modifier input, 22 words, 0xB520): 601 of 704 bits named. Edit inputs: `L3_SA_IDX`, `L3_DA_IDX`, `TTL_DEC`, `ROUTED_PKT`, `IP_RSVD_INVERT`, `INT_DSCP`, tag/VID fields, `CTX_*` (CPU TX tag). Largest unnamed run 15 bits `[63:49]`. No checksum/TSO field (CPU-port offload: none).
- **HSM2/HSM3 `DATA27`** (0xB898 / 0xB908): egress-edit flags `L3_DA_REP`, `L3_SA_REP`, `L3_TTL_DEC` only.
- **Encap RAMs** (`ENCAP_SRAM_CTRL0/1` 0xC7CC/0xC7D0): `ENCAP_TCAM`, `ENCAP_ACT`, `ENCAP_UT`, `ENCAP_MAC`, `ENCAP_SMAC`, `ENCAP_RMKOPRI`, `ENCAP_RMKIPRI` = VLAN_EGR_CNVT, UNTAG, L3_EGR_INTF_MAC, REMARK.
- Vendor builds: stock `rtk.ko` and ST5008F `core` have 1308/1308 regs, 35/35 tables, 0 offset/field differences vs GPL [BIN]; decompiled direct writes outside the map: only 0x98, 0xD0.
- SKUs: one reg/table list and one `rtl9300_capacityInfo` for RTL9301/9301H/9302A-F/9303 [GPL]; RTL9301 and 9303 same PBGA533, identical L3 text [DS].
- Rewrite exists in other dies only: **RTL9310 Mango** [MANGO] (`IP_TUNNEL`, `L2_TUNNEL`, `MPLS_VPLS`, `OPENFLOW`, `FLOW_BASED_COUNTER`; OpenFlow set-field `IP4_SIP`, `IP4_DIP`, `L4_SPORT`, `L4_DPORT`, `IP_TTL`, `IP_DSCP`, `SA`, `DA`, `VLAN_*`, `MPLS_*`; tables `TUNNEL_START*`, `VXLAN_*`, `MPLS_*`, `FT_*`, `ACTION_BUCKET`) and **RTL865x / RTL8686 gateway ALE** [8686] (tables `L4_TCP_UDP`, `L4_ICMP`, `EXT_INT_IP`, `SERVER_PORT`, `ALG`, `PPPOE`; regs `EnL4ChkCal`, `NAPTF2CPU`, `NATTM`, `L4TOCR`; switch core at `0xBB800000`, which does not decode on this die).

## Table index space (`drv_rtl9300.c` `rtl9300_table_read`)

| Controller | Addr | TBL bits | Used codes | Free |
|---|---|---|---|---|
| `TBL_ACCESS_L2_CTRL` | 0xB320 | `[17:16]` | 0 L2 hash, 1 L2 CAM, 2 MC_PORTMASK | 3 |
| `TBL_ACCESS_CTRL_0` | 0xB340 | `[15:12]` | 0 IVC/MAC/IP VLAN, 1 VLAN, 2 IACL/VACL, 3 LOG, 4 MSTI, 5 METER, 6 PORT_ISO, 7 LAG, 8 SRC_TRK_MAP | 9-15 |
| `TBL_ACCESS_CTRL_1` (L3) | 0xB3A0 | `[15:13]` | 0 ROUTER_MAC, 1 HOST, 2 PREFIX, 3 NEXTHOP, 4 EGR_INTF, 5 EGR_INTF_LIST | 6, 7 |
| `TBL_ACCESS_CTRL_2` (egress) | 0xCE04 | `[13:12]` | 0 UNTAG, 1 VLAN_EGR_CNVT, 2 L3_EGR_INTF_MAC, 3 REMARK | none |
| `TBL_ACCESS_HSB_CTRL` / `HSA_CTRL` | 0xD600 / 0x7880 | `[6]` / `[8]` | 0 | 1 |

- L3 BIST memories: `L3MEM` (x12), `L3MEM_HIT`, `L3TCAM` (x8), `CAMACT`, `MACTCAM`, `NXH`, `OIL`, `OTG` = the 6 used L3 codes.
- Unnamed bits per entry: no 32-bit unnamed run except the IPv4 formats of shared v4/v6 L3 tables. `L3_NEXTHOP` `[31:22]`, `L3_EGR_INTF` `[31]`, `[63:53]`.

## Probes (`scripts/hidden_probe.py`, `./dev.py hidden-probe`)

- Default: named registers only, `md.l`, 1 s per read: IDs/bonding, eFuse status, clock gates, encap block, table-access ctrl, HSB/HSA/HSM snapshots, L3 lookup-test regs, SPG ctrl, stock-only 0x98/0xD0, all `DMY_REG*`.
- `--holes`: first/middle/last 4 words of each of the 44 holes.
- `--alias`: 0xBB010000, 0xBB100000, 0xBB800000. Each one hangs the bus; recover: `./dev.py stock`.
- `--list` prints the `md.l` commands only.
- Snapshot values mean something only after traffic: run after `rtk network on` and a test flow.

## Write-probes (`scripts/hidden_write_probe.py`, `./dev.py hidden-write-probe`)

- Owner-approved (#68). Writes only to an allowlist of volatile switch-core registers; each write journaled (addr, old, new, readback) in `tmp/hidden/hwp-*.json` and restored; power cycle recovers.
- Never written: eFuse `WDATA` 0xC6A0, `RWOP`=1, `EFUSE_ACCESS_EN` (decision: #75), PLL/AFE 0xE200-0xE2FF, DDR/SPI/GPIO/reset/WDT.
- `snapshot`/`diff`: whole 64 KiB window, 0x100 words per `md.l`, ~29 s at 115200.
- `chipinfo`, `efuse`, `chipmode <n> [--reg 7c|c6fc] [--snap]`, `tables [--ctl C --codes N]`, `dmy`.

## Measured 2026-10-12

Base commit `ef7f00e`; our U-Boot from flash, stock clocks, no `rtk network on` unless noted.

- **Bus decode**: `md.l` of 0xBB010000, 0xBB100000, 0xBB800000 each hangs the CPU (no output, no exception; power cycle). The switch core decodes 64 KiB only.
- **Whole window** 0xBB000000-0xBB00FFFF: readable, no hang; 3212 of 16384 words nonzero; two snapshots in one boot identical. Between boots only power-up SRAM differs (`SPI_DATA` 0x460-0x65C, 0x31D4-0x31E0) plus thermal 0x6C.
- **Holes** (`--holes`, 3 x 4 words per hole): all 0 except 0xE300-0xE91C = `EGBW_PORT_Q_*_SET1` / `SCHED_PORT_Q_CTRL_SET1` (ports 24-27, 12 queues; two-index arrays `hidden_sdk_scan.py` missed; real hole 0xE298-0xE2FC only) holding 0x000FFFFF / 0x8000 / 1 (rate/burst/sched defaults). Whole-window snapshot: every word of the other 43 holes = 0.
- **IDs**: `MODEL_NAME_INFO` `0x93030001`; `CHIP_INFO` (EN = 0xA) `0x100a6487`.
- **Bonding**: `BONDING_REDEFINE_REG` `0x0001fffe`, `MAC_EFUSE_CTRL` `0x0003fffe` (BONDING_DEFINE_EN 1, CHIP_MODE 14, EN_DRAM 1, DUMMY_BONDING 0xfff), `BOND_DBG` `0x00ffffff`, `VOIP_BONDING_CTRL` 0xB8000040 = 0.
- **CHIP_MODE writes**: 14 -> 15 and 14 -> 0 on 0x7C and on 0xC6FC: readback unchanged, whole-window diff 0 words.
- **eFuse**: `CTRL_DONE` = 1 at power-up. Read sequence (`CTRL` = CMD[9] + ADDR[8:1], RWOP 0): CMD self-clears, ADDR latches, BUSY 0, `RDATA` = 0 for all 256 addresses with `EFUSE_ACCESS_EN` = 0. `ACCESS_EN` not written (#75).
- **Free table codes** (read command, ADDR 0, data regs pre-filled `0xA5A5A5A5`):

| Controller | Code | EXEC | Data | Verdict |
|---|---|---|---|---|
| L2 0xB320 | 0 (ref) | clears | overwritten | RAM |
| L2 | 3 | clears | pattern kept | no RAM |
| CTRL_0 0xB340 | 1 (ref, VLAN) | clears | overwritten | RAM |
| CTRL_0 | 9-15 (one per boot) | **stuck** | pattern kept, data regs then read-only | no RAM; controller locked until power cycle |
| CTRL_1 (L3) 0xB3A0 | 0 (ref) | clears | overwritten | RAM |
| CTRL_1 | 6, 7 | clears | pattern kept | no RAM |
| CTRL_2 0xCE04 | 0 (ref) | clears | overwritten | RAM |
| HSB 0xD600 | 0 (ref) | clears | power-up noise | RAM |
| HSB | 1 | **stuck** | pattern kept | no RAM |
| HSA 0x7880 | 0 (ref), 1 | **stuck** both, also after `rtk network on` | data regs ignore writes, read power-up noise | access path unusable; code 1 inconclusive |

- **DMY**: see catalogue rows; per-register results in `tmp/hidden/hwp-dmy-b1.json`.
- **After stock `rtk network on`** (cage 1 lit): `DMY_REG0_CHIP_MISC_R` 0x230 = `0x0fffffff`; HSB/HSA/HSM0-2 hold the last LAN frame; `TBL_ACCESS_CTRL_0` = `0x0001601b` (last access: PORT_ISO write, entry 27).
