# Hidden / disabled hardware in the RTL9303 (Longan)

Question: is NAT or packet-header rewrite in the die but disabled, fused off or undocumented? Issue #68. Prior: #58 (no NAT in datasheet/SDK API), #63 (hybrid NAT), #62 ([HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md)), [NAT.md](NAT.md), [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md).

## Verdict

- **No.** The egress modifier has no input that could carry a new IP address or L4 port, its memories are all accounted for, and its table controller has no free code.
- NAT stays on the CPU path ([NAT.md](NAT.md)).
- Realtek did build L3/L4 rewrite, but in other dies: RTL9310 (Mango) OpenFlow set-field, and the RTL865x/8686 gateway NAPT tables.
- Hidden non-NAT hardware found: Smart Packet Generator (#70), `ROUTER_SMAC_SEL` ECO in a dummy register.

## Sources

- **[GPL]** Realtek SDK `github.com/reyalo/Realtek` `sources/rtk-xgs1210` and `rtk-dms1250`: `include/hal/chipdef/longan/*`, `src/hal/chipdef/longan/rtk_longan_{reg,regField,table,tableField}_list.c`, `system/include/private/drv/swcore/swcore_rtl9300.h`, `src/hal/mac/drv/drv_rtl9300.c` (table access), `src/hal/chipdef/chipdef.c` (SKUs). Both trees: same 1308 registers, 35 tables.
- **[BIN]** stock TL-ST1008F `rtk.ko` and ST5008F v2 1.2.0 `core` (private): both embed `rtk_longan_reg_list` (148-byte entries with names) and `rtk_longan_table_list` (152-byte entries).
- **[DS]** `sources/rtl9303-cg-brief.pdf` Rev 1.1-1, `rtl9301-cg-datasheet-rev1.1.pdf`, `rtl9302d-cg-datasheet-excerpt-anoatech.pdf`.
- **[MANGO]** same SDK, `chipdef/mango`, `dal_mango_openflow.c`. **[8686]** same SDK, `uboot-xgs1210/arch/otto/cpu/rlx5281/rtl8686/asicregs.h` (RTL865x-derived gateway ALE).
- Offline scan: `scripts/hidden_sdk_scan.py` -> `tmp/hidden/sdk_scan.json`. Live probe: `./dev.py hidden-probe`.

## Pipeline and where a rewrite would have to live

- Stages (clock-gate bits `PS_GATCLK_EN` 0xC7A4 `[5:0]`): IGR_CTRL -> PKT_PRS (parser, output HSB) -> ALE (lookup, output HSA) -> EGR_CTRL -> PKT_ENCAP (modifier) -> MAC. `[31:6]` reserved.
- **HSB** (parser output, 30 words, 0xB4A0): has `SIP`, `DIP`, `SPORT`, `DPORT`, `IPV4_CHKSUM_OK`, `L4_HDR_CHK`. Match keys only.
- **HSA** (modifier input, SDK feature `MODIFIER_HSA`, 22 words, 0xB520): 601 of 704 bits named. Edit inputs: `L3_SA_IDX`, `L3_DA_IDX`, `TTL_DEC`, `ROUTED_PKT`, `IP_RSVD_INVERT`, `INT_DSCP`, tag/VID fields, `CTX_*` (CPU TX tag). Largest unnamed run 15 bits `[63:49]`.
- **HSM2/HSM3 `DATA27`** (0xB898 / 0xB908, mid-pipeline snapshot): egress-edit flags `L3_DA_REP`, `L3_SA_REP`, `L3_TTL_DEC` only.
- **Encap block RAMs** (`ENCAP_SRAM_CTRL0/1` 0xC7CC/0xC7D0): `ENCAP_TCAM`, `ENCAP_ACT`, `ENCAP_UT`, `ENCAP_MAC`, `ENCAP_SMAC`, `ENCAP_RMKOPRI`, `ENCAP_RMKIPRI` = VLAN_EGR_CNVT, UNTAG, L3_EGR_INTF_MAC, REMARK.
- Egress table controller `TBL_ACCESS_CTRL_2` 0xCE04: `TBL[13:12]`, codes 0-3 = UNTAG, VLAN_EGR_CNVT, L3_EGR_INTF_MAC, REMARK. Full.

## Table index space (`drv_rtl9300.c` `rtl9300_table_read`)

| Controller | Addr | TBL bits | Used codes | Free |
|---|---|---|---|---|
| `TBL_ACCESS_L2_CTRL` | 0xB320 | `[17:16]` | 0 L2 hash, 1 L2 CAM, 2 MC_PORTMASK | 3 |
| `TBL_ACCESS_CTRL_0` | 0xB340 | `[15:12]` | 0 IVC/MAC/IP VLAN, 1 VLAN, 2 IACL/VACL, 3 LOG, 4 MSTI, 5 METER, 6 PORT_ISO, 7 LAG, 8 SRC_TRK_MAP | 9-15 |
| `TBL_ACCESS_CTRL_1` (L3) | 0xB3A0 | `[15:13]` | 0 ROUTER_MAC, 1 HOST, 2 PREFIX, 3 NEXTHOP, 4 EGR_INTF, 5 EGR_INTF_LIST | 6, 7 |
| `TBL_ACCESS_CTRL_2` (egress) | 0xCE04 | `[13:12]` | 0-3 (above) | none |
| `TBL_ACCESS_HSB_CTRL` / `HSA_CTRL` | 0xD600 / 0x7880 | `[6]` / `[8]` | 0 | 1 |

- L3 BIST memories: `L3MEM` (x12), `L3MEM_HIT`, `L3TCAM` (x8), `CAMACT`, `MACTCAM`, `NXH`, `OIL`, `OTG` = the 6 used L3 codes. None left for codes 6/7.
- Unnamed bits per entry: no table has a 32-bit unnamed run except the IPv4 formats of shared v4/v6 L3 tables (the unused IPv6 address bits). `L3_NEXTHOP` `[31:22]`, `L3_EGR_INTF` `[31]`, `[63:53]`.

## Candidates

| # | Candidate | Evidence | Confidence it is NAT/rewrite | Read-only probe |
|---|---|---|---|---|
| 1 | IP/L4 rewrite in the egress modifier | HSA and HSM `DATA27` carry no address/port value; encap RAMs all mapped; egress TBL codes full [GPL] | none | HSA 0xBB00B520 x22, HSM2/3 `DATA27` after a routed packet: only `TTL_DEC`/`ROUTED_PKT`/`L3_*_REP` change |
| 2 | Hidden NAPT/flow table | BIST lists every RAM/TCAM; all map to known tables; no NAPT/L4/flow names in 1308 regs or 35 tables [GPL] | none | `--holes` sample; free-code table reads need a write (below) |
| 3 | Registers present in vendor builds but not in GPL | stock `rtk.ko`, ST5008F `core`: 1308/1308 regs, 35/35 tables, 0 offset/field differences [BIN] | none | - |
| 4 | Direct writes outside the named map | decompile literals: only 0x98, 0xD0 (stock `LinkFaultMonIsrThread` mask/status) [BIN] | none (link fault) | `md.l bb000098 1`, `md.l bb0000d0 1` |
| 5 | Feature fused off per SKU | one reg/table list and one `rtl9300_capacityInfo` for RTL9301/9301H/9302A-F/9303 [GPL]; RTL9301 and 9303: same PBGA533, identical L3 text [DS]; SKU = `CHIP_MODE` (ports/SerDes) | very low | `BONDING_REDEFINE_REG` 0x7C, `BOND_DBG` 0x228, `MAC_EFUSE_CTRL` 0xC6FC |
| 6 | Address holes (unnamed decode) | 120 runs >= 4 words; 44 outside MAC per-port blocks; largest 0xACD4-0xB31C (after L3 regs), 0xE298-0xE91C, 0xD29C-0xD5FC (after encap dummies), 0xBF14-0xC2FC [GPL] | low: nothing in HSA to consume them | `./dev.py hidden-probe --holes` |
| 7 | Free table codes L2 3, CTRL_0 9-15, L3 6-7, HSA/HSB 1 | no BIST memory for them [GPL] | low | needs a ctrl write: not in the probe |
| 8 | ECO bits in 90 `DMY_REG*` | named ECO knobs exist: `DMY_REG1_PKT_ENCAP.ROUTER_SMAC_SEL` + 48-bit SMAC (0xCE20/0xCF0C), `DMY_REG0_EGRESS_CTRL` (`STRIC_WFQ_JUMBO`, `SPD_UP_REFILL`, `AMP_FACTOR`), `DMY_REG0_CHIP_MISC` (`CFG_VOL_PRB_SEL`, `DSS_SEL`); SDK never references `DMY_REG*_PKT_ENCAP` [GPL] | low (an SMAC override, not IP) | all 90 read by `hidden-probe` |
| 9 | Hidden CPU-port checksum offload / TSO | HSA `CTX_*` = documented TX CPU-tag fields, no checksum field; `DMA_IF_*` has none; reserved tag bits do not reach HSA [GPL] | none | - |
| 10 | Internal loopback re-entry (`ACL_LB_ACT`, `LB_TTL`, `LB_PKT`; `TEST_MODE_ALE_LOOPBACK_CTRL` 0x7AAC) | recirculates a frame; no rewrite on the way [GPL] | none (useful for #63 only) | `md.l bb007aa8 2` |
| 11 | eFuse content | `EFUSE_ACCESS_*` 0xC698-0xC6A4, 8-bit addr, 16-bit data; SDK never reads it [GPL] | very low | dump needs a command write: not in the probe |
| 12 | Smart Packet Generator (not NAT) | `SMART_PACKET_GENERATOR` (Longan only), `SPG_*` regs, GPL diag driver; absent from DS (#70) | n/a | `SPG_GLB_CTRL` 0x7AB0 x3 |

## Where rewrite does exist (for comparison)

- **RTL9310 Mango** [MANGO]: features `IP_TUNNEL`, `L2_TUNNEL`, `MPLS_VPLS`, `OPENFLOW`, `FLOW_BASED_COUNTER` (not in Longan). OpenFlow set-field types `IP4_SIP`, `IP4_DIP`, `L4_SPORT`, `L4_DPORT`, `IP_TTL`, `IP_DSCP`, `SA`, `DA`, `VLAN_*`, `MPLS_*`. Tables `TUNNEL_START*`, `VXLAN_*`, `MPLS_*`, `FT_*`, `ACTION_BUCKET`. BIST has `ENCAP_GLB`/`ENCAP_TCAM` for the tunnel engine.
- **RTL865x / RTL8686 gateway ALE** [8686]: tables `L4_TCP_UDP`, `L4_ICMP`, `EXT_INT_IP`, `SERVER_PORT`, `ALG`, `PPPOE`; regs `EnL4ChkCal` (L4 checksum recalc), `NAPTF2CPU`, `NATTM`, `L4TOCR`. Switch core at `0xBB800000`, tables at `0xBB000000 + 0x10000*type`. None of these names exist in Longan.

## Probes (`scripts/hidden_probe.py`, `./dev.py hidden-probe`)

- Default: named registers only, `md.l`, 1 s per read: IDs/bonding, eFuse status, clock gates, encap block, table-access ctrl, HSB/HSA/HSM snapshots, L3 lookup-test regs, SPG ctrl, stock-only 0x98/0xD0, all `DMY_REG*`.
- `--holes`: first/middle/last 4 words of each of the 44 holes. Decode unknown: a word could be a clear-on-read counter.
- `--alias`: 0xBB010000, 0xBB100000, 0xBB800000 (gateway switch-core base). No decode expected; a bus hang stops the run (recover: `./dev.py stock`).
- `--list` prints the `md.l` commands only.
- Snapshot values mean something only after traffic: run after `rtk network on` and a test flow.

## Write-probes (owner approval needed, not scripted)

- eFuse dump: `EFUSE_ACCESS_EN` 0xC698, then per address `EFUSE_ACCESS_CTRL` 0xC69C `EFUSE_ADDR[8:1]`, `EFUSE_CMD[9]`, read `EFUSE_RDATA` 0xC6A4.
- Free table codes: `TBL_ACCESS_CTRL_1` 0xB3A0 with `EXEC=1 CMD=0 TBL=6|7 ADDR=0`, then `TBL_ACCESS_DATA_1` 0xB3A4; same for the other controllers. A read command only; result is all-zero or garbage if no RAM answers.
- `CHIP_INFO` 0x08: needs `CHIP_INFO_EN` = 0xA written first.
