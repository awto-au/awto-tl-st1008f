# RTL9303 datasheet feature audit

Every feature of the RTL9303-CG datasheet against stock firmware, OpenWrt, our U-Boot / 7.3 port and this board's router goal (#65). Issue: #69. SoC blocks (SRAM, GDMA, crypto, USB, timers) are covered in [HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md) and listed here only by reference. Hidden rewrite hardware and register-map gaps are not covered here; they are tracked separately (#58, #63).

## Documents

The doc hunt (2026-10-11) is recorded in [sources/README.md](../sources/README.md): URLs, revisions, page counts, and what was searched and not found.

| Document | Status | Use here |
|---|---|---|
| RTL9303-CG datasheet Rev 1.1-1 (55 p) | have; the only public revision; every mirror is byte-identical | primary; read in full for this audit |
| RTL9301-CG datasheet Rev 1.1-1 (71 p) | downloaded | same text as the RTL9303 DS, plus §7.24 Stacking and QSGMII/RXAUI+/XSGMII; nothing else new |
| RTL9301 design guide 0.1, RTL930x power sequence note, RTL9301 power consumption | downloaded | board-level only |
| RTL9300 LED application note V1.0 | downloaded | register-level LED engine (#9) |
| RTL9302D datasheet excerpt + 1 schematic sheet | downloaded | excerpt only |
| RTL9311 draft 0.5, RTL9313 Rev 0.5 datasheets | downloaded | comparison |
| RTL9310 register file v1.0, developer guide 1.00, architecture overview, CPU/memory/peripherals | downloaded | closest programming docs (Mango). The 9310 DG §11.1 NIC matches the RTL9300 SDK `DMA_IF_*` layouts |
| RTL9300 register file / developer guide / SDK API guide | **not public** | substitute: GPL SDK `rtk_longan_reg_list.c` (`scripts/sdk_regdump.py`) |
| RTL9302A/B/C datasheets, errata, RTL9303 reference schematic, product brief | **not found** | - |

## Sources and tags

- **DS** `sources/rtl9303-cg-brief.pdf` Rev. 1.1-1. `§x p.N` = section and printed page; PDF page = N + 6.
- **SDK** register database `rtk_longan_reg_list.c` / `rtk_longan_regField_list.c` (GPL, D-Link DMS-1250, SDK 3.8.0). Dump them with `scripts/sdk_regdump.py <regex>`. Addresses are `0xBB00xxxx`.
- **Stock**: TL-ST1008F stock `rtk.ko` runs `dal_longan_{acl,eee,flowctrl,ipmc,l2,l3,led,mcast,mirror,oam,pie,port,qos,rate,sds,sec,stack,stat,stp,switch,trap,trunk,vlan}_init` with SDK defaults. It is an unmanaged switch with no user configuration. "init" below means only that default.
- **OWRT**: OpenWrt `target/linux/realtek/files-6.18` at `53ec2d05a4` (`rtl83xx` DSA, `rtl838x_eth`, `pcs-rtl-otto`).
- **Ours**: U-Boot `rtk` commands / 7.3 mainline port. The 7.3 port has no switch driver yet (MAINLINE-PORT.md), so the 7.3 column is "N" unless stated.
- **Value** for this board means: 8x SFP+, router with NAT on the CPU path (228 Mbit/s ceiling, NAT.md), IPv6 routed in the ASIC, keep CPU cores free.
  - **CPU** marks a feature that removes per-packet CPU work or protects the CPU.
  - **R** marks a feature that improves the router use case.
- **Effort**: S = register writes or an existing kernel hook; M = new driver code (tc/DSA op, about 100-300 lines); L = new subsystem.

## Feature table

| # | Feature (DS wording) | DS ref | SDK registers / module | Stock | OWRT | Ours | Value here | Effort |
|---|---|---|---|---|---|---|---|---|
| 1 | 160 Gbps switch capacity, 8x 10G MAC | §2 p.2, Fig.1 p.5 | - | Y | Y | U-Boot `network on` | used; 9.69 Gbit/s each way measured (ROUTING-OFFLOAD.md) | - |
| 2 | External CPU mode: port 28 SGMII or port 27 10G-R/USXGMII/HISGMII/1000BASE-X/SGMII on S0 | §2 p.2, §6.5 p.18 | `MAC_L2_CPU_PORT_CTRL` 0xC70C `INTF_P28_SEL` | N | N | N | none: S0 not wired (DS: pull low) | - |
| 3 | SPI slave register access for an external CPU; strap `REG_IF_SEL` | §2 p.2, §6.9 p.20, §6.12 p.22 | - | N | N | N | none: not wired | - |
| 4 | SPI NOR up to 64 MB (2 CS, 1/2/4-bit, mmio + cached reads) | §2, §8.2 p.39 | SoC SPI | Dual I/O mmio | PIO 1-bit | stock mode | high for boot/flash speed (#61); not on the packet path | M |
| 5 | SPI NAND up to 512 MB (PIO + DMA) | §2, §8.2 | SoC | N | N | N | none: no NAND | - |
| 6 | Flash-only solution; ROM boot (`BOOT_SEL`); flash decrypt (`EN_DECRYPT`); `CPU_SLEEP` strap | §2, §6.12 p.22 | - | NOR boot | - | - | none | - |
| 7 | 64 KB SP-SRAM | §1 p.1, §2 | SoC | SPL only | N | DDR/clock routines | see HARDWARE-INVENTORY.md | - |
| 8 | USB 2.0 host | §2, §6.10 p.21 | SoC EHCI | driver, nothing wired | N | N | none: not wired (#5) | - |
| 9 | MIPS 34Kc, MMU, 32+32 KB L1, up to 800 MHz, MIPS16e | §2, §8.1 p.39 | - | 800 MHz, UP kernel | 800 MHz, SMP 2 VPE | 1 GHz (#38) | used; 1 GHz is over the DS rating (CLOCKS.md) | - |
| 10 | Two UARTs | §2, §6.2 p.18 | SoC | UART0 | UART0 | UART0 | UART1 shares EJTAG balls | - |
| 11 | 8-set I2C master, 2-set SPI master | §2 p.2 | `I2C_MST1/2` | SFP I2C | `i2c-rtl9300` | Y | used (SFP EEPROM/DDM) | - |
| 12 | IVL / SVL / IVL+SVL per VLAN | §1, §7.2 p.25 | VLAN profile | init | DSA default | N | low | - |
| 13 | 802.1Q 4K VLAN table; per-port ingress/egress filtering | §2, §7.8 p.29 | `vlan` | init | Y (DSA bridge) | N | used (VLANs 991/992 bench, LAN/WAN split) | - |
| 14 | Q-in-Q: 3 tags, 4 outer + 4 inner + 1 extra TPID, forward on inner or outer VID | §7.8 p.29 | `VLAN_PORT_TAG*` | init | N for 930x (TPID code is 931x only) | N | low (no S-tag service here) | M |
| 15 | Protocol-, MAC-, IP-subnet-, flow-based VLAN (8 protocol, 1K MAC/subnet) | §1, §7.8 p.29 | `vlan` | init | N | N | low | M |
| 16 | VLAN translation: 1K ingress, 512 egress (§7.9 says "512K": typo), N:1, ACL-based | §2 p.2, §7.9 p.29 | `vlan` IVC/EVC tables | init | partial: tc `vlan push/pop` via PIE | N | low-medium: an ISP VLAN tag in HW if needed | M |
| 17 | 16K L2 table, 2-left 4-way, 2 hash algorithms | §2, §7.2.2 p.26 | `L2_CTRL` 0x8FD8 | init | Y | N | used | - |
| 18 | Source/destination MAC filtering | §2 p.2 | L2 entry flags | init | static fdb only | N | low | S |
| 19 | Per-port aging disable; age-out and new-learn notification to CPU | §2, §7.2.2 | `L2_AGE_CTRL` 0x8FDC, `L2_NTFY_*` 0xEB00 | init | aging Y; notification N on 930x (839x only) | N | low: avoids SA-learn polling | M |
| 20 | L2 learning limits: system / port / trunk / 8 VLANs; drop / trap / copy / forward | §7.3 p.26 | `L2_LRN_CONSTRT_CTRL` 0x909C, `L2_LRN_PORT_CONSTRT_CTRL` 0x90A4 | init | N | N | **CPU** low-medium: caps a MAC flood before it reaches the CPU and the table | S |
| 21 | Independent 1K multicast table | §2 p.2 | `mcast` | init | Y (mdb) | N | used | - |
| 22 | 12 Mbit packet buffer | §2 p.2 | `FC_GLB_*` 0xD878-D884 | init | defaults | N | **R** absorbs 10G to slower-WAN bursts on the ASIC path; thresholds untuned | S |
| 23 | Jumbo frames up to 12 KB | §2 p.2 | `MAC_L2_PORT_MAX_LEN_CTRL` | init | Y (MTU up to 12288 - overhead) | N | low for NAT (WAN MTU 1500); CPU cost is per packet, so jumbo helps only LAN-terminated traffic | - |
| 24 | 48 reserved multicast addresses: 01-80-C2-00-00-00..2F + 4 user; lookup / drop / trap | §7.6 p.27 | `RMA_CTRL_0..` 0x9E60 | init | BPDU/LLDP/EAPOL/PTP actions set | N | used | - |
| 25 | Port isolation: per-port mask + 16 VLAN-based sets | §7.4 p.26 | `PORT_ISO_CTRL`, `PORT_ISO_VB_ISO_PMSK_CTRL` 0xA940, `PORT_ISO_RESTRICT_ROUTE_CTRL` 0xA8A0 | init | per-port Y (`BR_ISOLATED`); VLAN-based N | U-Boot: all front ports isolated (cage loop) | **R** medium: guest/IoT VLAN client isolation at line rate | S |
| 26 | STP/RSTP/MSTP, 64 instances | §2, §7.7 p.28 | `stp` | init (no STP daemon: unmanaged) | Y (stp + MST state) | N | required: loop incident #43 | - |
| 27 | Link aggregation: 64 groups x 8 ports, 4 hash algorithms (SPP/MAC/VID/IP/L4/proto/flow label), HW failover, MC/flood separation | §2 p.3, §7.10 p.29 | `TRK_HASH_CTRL` 0x9F80, `trunk` | init | Y (`lag.c`) | N | low: single uplink | - |
| 28 | Port mirroring: 4 sets, ingress/egress, isolation, cross-VLAN | §2 p.3, §7.11 p.30 | `MIR_CTRL` 0xA2A0 | init | Y (`mirror.c`, tc mirred) | N | low-medium: debug sniff port | - |
| 29 | RSPAN; flow-based mirror via ACL | §2, §7.11 | `MIR_CTRL` MIR_MODE | init | flow mirror via tc; RSPAN N | N | low | M |
| 30 | sFlow: per-port ingress/egress sample rate, trap reason to CPU | §2, §7.11 p.30 | `SFLOW_CTRL` 0xBEA0, `SFLOW_PORT_RATE_CTRL` 0xBEA4 | init | N | N | **CPU R** medium: flow statistics for ASIC-routed traffic (invisible to the CPU) at a 1/N packet cost | M |
| 31 | Attack prevention: LAND, UDP/TCP blat, PoD, smurf, NULL/XMAS scan, SYN+FIN, SYN+RST, SYN sport<1024, min TCP header, TCP frag offset, ICMP frag, ping size, IPv6 frag, DA=SA, invalid length; drop or trap; per port | §2 p.3, §7.12 p.30 | `ATK_PRVNT_CTRL` 0xA1AC (19 types), `ATK_PRVNT_PORT_EN` 0xA1A8 | init (off, SPEC) | N | N | **CPU R** medium-high: WAN junk dropped at wire speed before the CPU or the LAN; no per-packet cost | S |
| 32 | Storm control: unknown UC, UC, unknown MC, MC, BC; pps or bps per port; EXCEED flags | §2 p.3, §7.15.3 p.32 | `STORM_PORT_{UC,MC,BC}_CTRL` 0x8A70/0x8B60/0x8C50, `STORM_CTRL` 0x8A60 | init (off, SPEC) | N on 930x (debugfs readout is 838x/839x only) | N | **CPU R** high: caps flood traffic into the CPU port and the LAN; would have contained the #43 loop | S |
| 33 | Per-protocol storm meters: ARP, DHCP, BPDU, IGMP per port (SDK only, not in DS) | - | `STORM_PORT_PROTO_{ARP,DHCP,BPDU,IGMP}_CTRL` 0x9A18/0x98A4/0x9920/0x999C | init | N | N | **CPU** high: rate-limits exactly the frames that are trapped to the CPU | S |
| 34 | OAM 802.3ah loopback (wire speed, MAC swap) | §2 p.3, §7.27 p.38 | `OAM_CTRL` 0xA120, `OAM_PORT_ACT_CTRL` 0xA124 | init | N | N | medium as a test tool: link/all-port tests (#22) without a second 10G host | S |
| 35 | OAM dying gasp (`PWRMON` ball, HW-sent) | §7.27 p.38, §6.11 p.21 | `OAM_CTRL` | init | N | N | low: PWRMON wiring unknown | S |
| 36 | IPv4/IPv6 unicast routing: 64 router MAC, 6K host (2K v6 per §2, 3K v6 per §7.14.1), 512 LPM (128 v6), 2K next hop, 128 L3 interfaces | §2 p.3, §7.14.1 p.31 | `l3` tables, `L3_HOST_TBL_CTRL` 0xAB48 | init, no routes | gateway routes only; on-link + default trap (#59) | N | **CPU R** highest: 9.08 Gbit/s IPv6 at 0 % CPU today; on-link neighbours as host routes would move downstream v6 and inter-VLAN off the CPU (#59) | M |
| 37 | uRPF strict and loose, default-route option | §1, §2, §7.14.1 | `L3_PORT_IP_ROUTE_CTRL` 0xAB7C, `L3_PORT_IP6_ROUTE_CTRL` 0xABF0, `L3_IP_ROUTE_CTRL.URPF_BASE_SEL` | init | N | N | **CPU R** medium: anti-spoof on the ASIC path (kernel `rp_filter` never sees it) | S |
| 38 | Policy-based routing | §2, §7.14.1 | PIE action `UNICAST_ROUTING` | init | used inside `l3.c` for prefix routes; no user PBR | N | **R** medium: source/DSCP-based uplink choice in HW | M |
| 39 | L3 exception handling: TTL/HL fail, MTU fail, IP options, HBH, bad SIP/DIP, DMAC mismatch actions; 8 MTU profiles per family | §7.14 (SDK) | `L3_IPUC_ROUTE_CTRL` 0xAB4C, `L3_IP6UC_ROUTE_CTRL` 0xAB50, `L3_IP_MTU_CTRL` 0xAB5C [8] | init | defaults; one 1536 B MTU for all interfaces | N | low: decides what traps to the CPU; per-interface MTU matters only with PPPoE/tunnels | M |
| 40 | Per-route HW counters (4 sets, 64-bit; SDK only) | - | `L3_ENTRY_COUNTER_CTRL` 0xAC64, `_DATA` 0xAC74 | init | route HIT flag only (debugfs) | N | **R** medium: byte/packet accounting for ASIC-routed flows | S |
| 41 | IPv4/IPv6 multicast routing: (S,G,V)/(*,G,V), 2K v4 / 1K v6 entries, 512 OIL, RPF; PIM-SM/DM/SSM, DVMRP, MOSPF, MVR | §2 p.3, §7.14.2 p.31 | `L3_IPMC_ROUTE_CTRL` 0xAB54, `ipmc` | init | N ("multicast routing not offloaded") | N | low: no multicast service here (IPTV would change it) | L |
| 42 | IGMP v1/v2/v3 and MLD v1/v2 snooping | §2, §7.5 p.27 | `VLAN_APP_PKT_CTRL` | init | Y (trap + mdb) | N | used | - |
| 43 | PIE: 2K entries, 16 blocks x 128, VLAN-ACL and ingress-ACL phases, L2/L3/L4 + user fields, range checks (VLAN, IP, L4 port, length) | §1, §2 p.3, §7.13 p.30 | `PIE_CTRL` 0xA77C, `PIE_BLK_PHASE_CTRL` 0xA5A4, `pie` | init | tc flower: eth, VLAN, IPv4/IPv6 addrs, ports; no TCP flags, no ranges | N | **CPU R** high: the only filter on the ASIC-routed path (#66) | M |
| 44 | ACL actions: drop, permit, redirect, copy to CPU, log, mirror, police, inner/outer VLAN translate, priority, CPU QID, 1p/DSCP remark, tag status, bypass, metadata, loopback, IP reserved-flag invert | §1, §2, §7.13.1 p.30 | PIE action fields | init | drop, trap, redirect, mirred, VLAN push/pop | N | **CPU R** high: CPU QID (control plane on its own ring), police per class, DSCP remark | M |
| 45 | 2K 64-bit log counters, byte or packet | §2 p.3, §7.13.3 p.31 | PIE log | init | tc HW stats (immediate) | N | **R** medium: per-rule accounting | - |
| 46 | OpenFlow metadata field | §7.13 p.30 | PIE metadata | init | N | N | none | - |
| 47 | 256 policers in 16 blocks: DLB, srTCM, trTCM, color-aware; pps or bps, 16 kbps granularity | §2 p.3, §7.15.2 p.32, §7.21 p.35 | `METER_GLB_CTRL` 0xA0A0, meter table | init | N (only port-level police) | N | **CPU R** medium: per-flow / per-trap-class limits | M |
| 48 | Ingress bandwidth control per port, 16 kbps to 10 Gbps, optional PAUSE, EXCEED flag | §2 p.4, §7.15.1 p.32 | `IGBW_PORT_CTRL`, `IGBW_CTRL` 0x8060 (admit BPDU/ARP/DHCP/IGMP/RIP bypass) | init | Y (tc police ingress) | N | low-medium | - |
| 49 | 8 queues per port; 32 queues on the CPU port | §2 p.4, §7.17 p.33 | `QM_INTPRI2QID_CTRL` 0xA320, `QM_CPUQID2QID_CTRL` 0xA324 | init | 2 of 32 CPU queues, round robin by reason (#60) | N | **CPU** medium: see CPU NIC section | S |
| 50 | Priority decision: 8 sources (port, VACL, DSCP, inner/outer tag, MAC/subnet VLAN, protocol VLAN, routing) with weights | §2 p.4, §7.16 p.33 | `PRI_SEL_TBL_CTRL` 0x9B28 | init | DSCP to queue default map | N | **R** medium with #51 | S |
| 51 | Scheduling SP + WFQ (bytes) or WRR (packets); egress shaping per port and per queue: max / fixed / assured, 16 kbps steps | §2 p.4, §7.17 p.33 | `SCHED_PORT_ALGO_CTRL` 0x7A9C, `EGBW_*`, `SCHED_PORT_Q_CTRL_*` | init | port egress police only | N | **R** medium: shape the WAN port to the ISP rate with priority queues for ASIC-routed v6 | M |
| 52 | CPU-port egress rate limit, bps or pps | §7.17 p.33 | `EGBW_CTRL.RATE_MODE_CPU` 0x78E4, `EGBW_CPU_PPS_LB_CTRL` 0x78E8, `EGBW_CPU_Q_MAX_LB_CTRL` [32] 0x7CB8 | off | off | N | **CPU** medium: protection, not throughput (#60 item 4) | S |
| 53 | Egress remarking: inner 1p, outer 1p, DSCP, DEI | §2 p.4, §7.18 p.34 | `rmk` regs | init | N | N | low-medium | M |
| 54 | SWRED: 3 colours, per-queue min/max/rate, drop counters | §2 p.4, §7.22 p.36 | `SWRED_QUEUE_DROP_CTRL` 0x7A08, `SWRED_DROP_CNTR` 0xB5A8 | init | N for 930x (WRED code is 839x only) | N | **R** medium: AQM where 10G meets a slower WAN on the ASIC path | S |
| 55 | Ethernet AV: 802.1Qav (credit-based shaper); 1588v2 "supported by PHY" | §2 p.4 | - | - | N | N | none: no PHY for 1588; no AV traffic | - |
| 56 | 802.3x flow control; ingress-side page counting | §7.19 p.34 | `FC_*`, CPU port `FC_EN` | init | phylink pause; CPU port FC_EN = 1 | N | low: TCP handles drops; PAUSE from the CPU port would throttle all ports (SPEC) | - |
| 57 | Half-duplex backpressure (jam / defer) | §7.20 p.35 | - | - | - | - | none: full duplex only | - |
| 58 | MIB counters: RFC 1213 / 3635 / 2863 / 2819 / 1493 / 2674 + private; 4 sets 64-bit | §2 p.4, §7.23 p.37 | `MIB_*` | Y | Y (`ethtool -S`, rmon, debugfs drops) | U-Boot `md` | used | - |
| 59 | NIC + CPU tag (RX: port, reason, ACL index, errors; TX: forced port mask) | §7.24 p.37 | `DMA_IF_*` | see below | see below | N | see [CPU NIC / DMA](#cpu-nic--dma-interface-724) | - |
| 60 | Indirect table access | §7.25 p.37 | `TBL_ACCESS_*` | Y | Y (`otto_table`) | N | used | - |
| 61 | External PHY access over MDC/MDIO (4 SMI buses) | §6.11 p.21, §7.26 p.38 | `SMI_*` 0xCA00 | init | Y | U-Boot SMI init | none: no PHYs; GLC-T copper SFPs on I2C | - |
| 62 | EEE per port, per speed, TX/RX separate | §2 p.4, §7.28 p.38 | `EEE_CTRL` 0x3274, `EEE_TX_*` 0xC72C.. | init | Y (`set_mac_eee`) | N | none: optics and GLC-T do not negotiate EEE | - |
| 63 | SerDes: SGMII on S0; 10GBASE-R on S2-S9; electrical tables for SGMII, 1000BASE-X, 10GBASE-R only | §6.5-6.6 p.18-20, §9.4.2-9.4.7 p.41-42 | `pcs-rtl-otto` | 10G (+1G via `rtk 10g`) | 1000BASE-X, 2500BASE-X, 10GBASE-R, USXGMII, SGMII per lane | `rtk 10g` 1G/10G | **R** medium: 2.5GBASE-X SFP for a 2.5G ISP modem port; 2.5G/5G not characterised in the DS | S |
| 64 | LED: serial (`LED_MDC/MDIO`) or scan mode, system LED | §6.7 p.20, §9.4.13 p.46 | `LED_*` 0xCC00 | Y | Y | U-Boot `network on` LED config | medium (#9) | - |
| 65 | Hardware / software resets: CPU+memory, NIC, switch soft reset | §7.1 p.25 | `RST_GLB_CTRL_0` 0x000C | Y | NIC reset at init | `syscon-reboot` | used | - |
| 66 | Interrupt output pin `INT` (external CPU); internal interrupt controller | §6.11 p.21, Fig.1 | SoC `GIMR/IRR` | Y | Y | Y | see CPU NIC section (delayed IRQ) | - |
| 67 | Power saving | §2 p.4 | EEE only | - | - | - | none beyond EEE | - |
| 68 | Thermal sensor | not in DS | `0xBB000060..70` [SDK] | off (#13) | `realtek-thermal` | `rtk temp` | used; DS gap | - |
| 69 | Stacking: up to 16 units, line/ring/star over ports 24-27, stacking header, 2 stacked trunks (described only in the RTL9301 DS §7.24 p.50) | Fig.1 p.5 | `stack` (`STK_*`) | init | N | N | none: single unit | - |
| 70 | Crypto engine, OpenFlow, timers, watchdog (block diagram only) | Fig.1 p.5 | SoC | - | - | - | see HARDWARE-INVENTORY.md | - |
| 71 | Electrical: SPI master 51 MHz typ., DDR3 600 MHz typ. (§8.3 says up to DDR3-1600), MDC 2.55 MHz, XTAL 25 MHz ±50 ppm, Ta 0-70 °C, Tj 125 °C max | §9 p.40-47 | - | - | - | CPU 1 GHz, DDR 650 | SPI above 25.5 MHz corrupts reads under Linux (#50), against the 51 MHz in Table 26 | - |

### Datasheet inconsistencies

- IPv6 host entries: §2 p.3 says 2K, §7.14.1 p.31 says 3K.
- Egress VLAN translation: §2 says 512 entries, §7.9 says "512K" (typo).
- §7.14.2 adds PIM-SSM, which §2 does not list.
- DDR: §8.3 says up to 800 MHz (DDR3-1600), Table 25 gives fCK typ. 600 MHz. The MEM_TYPE strap (§6.12) still has a DDR2 option.
- The cover says 29 June 2018 for Rev. 1.1-1; the revision history says 2018/9/5.
- Not described anywhere: the thermal sensor; the crypto engine, stacking and OpenFlow beyond Fig. 1; 2.5G/5G SerDes electricals; any CPU NIC register.

## CPU NIC / DMA interface (§7.24)

The DS gives §7.24 one paragraph plus Fig. 11. There are no DMA registers, timing or performance figures in the DS. The SDK register database is the full per-chip list, including reserved and dummy registers. Below is every CPU-port and NIC register in it (`scripts/sdk_regdump.py '^DMA_|^NIC_|^L2_NTFY|^MAC_L2_CPU|CPU_Q|CPU_PPS|CPUQID|FLAG2CPU'`).

Per-packet cost today: RX 20-23 µs, TX 17-23 µs. It is the same at 64 B and 1400 B (NAT.md, #65), so the cost is per packet, not per byte.

### `DMA_IF_CTRL` 0xBB00E028

Read value `0x06400000`, taken 2026-10-11 at the U-Boot prompt with the NIC idle (`hw-probe`). The register has no field for burst length, descriptor prefetch, bus width, coalescing or ring arbitration. The 9 bits [15:7] and the 2 bits [31:30] are RESERVED.

| Field | Bits | Read | What it does | SDK / stock | OWRT | Effect on µs/pkt |
|---|---|---|---|---|---|---|
| RESERVED | 31:30 | 0 | - | - | - | - |
| RX_TRUNCATE_LEN | 29:16 | 0x640 = 1600 | Frames to the CPU longer than this are cut to this length when enabled | 1600 (`RTNIC_MAX_PKTLEN`) | left at 1600 | - |
| RESERVED | 15:7 | 0 | - | - | - | - |
| RX_TRUNCATE_EN | 6 | 0 | Enables the truncation (`dal_longan_switch_cpuPktTruncateEnable_set`) | SDK sets it with len 0x640 | cleared | none for NAT: a forwarded packet needs its payload for TX. Header-only RX suits only copy-to-CPU (sFlow, mirror-to-CPU) where the ASIC forwards the original |
| TX_EN | 5 | 0 | TX DMA enable | 1 at NIC init | 1 (`tx_rx_enable` 0x30) | - |
| RX_EN | 4 | 0 | RX DMA enable | 1 | 1 | - |
| TX_HIGH_FETCH | 3 | 0 | Doorbell, TX ring 1 (high). Self-clearing; the NIC then reads descriptors whose OWN bit is set (9310 DG §11.1.2, Table 11-2) | RMW per packet | `300-12`: one write of a cached value per kick, no read-poll | read-poll + regmap lock + `ktime` -> one `writel`: UDP 64 B forwarding +9 % (NAT.md "NIC path", #60) |
| TX_LOW_FETCH | 2 | 0 | Doorbell, TX ring 0 (low); higher ring ID = higher priority | same | same (mask `GENMASK(3,2)`) | same |
| TX_HIGH_BUSY | 1 | 0 | TX ring 1 DMA busy, "for debugging" (RO) | polled | - | - |
| TX_LOW_BUSY | 0 | 0 | TX ring 0 DMA busy, "for debugging" (RO) | polled | - | - |

- The RTL9310 Developer Guide (§11.1, Table 11-2) documents the same `DMA_IF_CTRL` layout bit for bit. It describes RX_TRUNCATE_EN as "truncate jumbo frame".
- Descriptor (9310 DG Table 11-1):
  - BUF_ADDR, 4-byte aligned.
  - BUF_SIZE (14 bit).
  - MORE (chained jumbo).
  - PKT_OFFSET (14 bit).
  - BUF_LEN.
  - CPU tag.
- The descriptor has no checksum or offload fields.

### Other NIC and CPU-port registers

| Register | Addr | Fields | Purpose | SDK / stock | OWRT | Effect on µs/pkt |
|---|---|---|---|---|---|---|
| `DMA_IF_RX_BASE_DESC_ADDR_CTRL` [32] / `_CUR_` | 0xDF00 / 0xDF80 | ADDR | RX ring base / current descriptor | 32 rings | 2 rings | - |
| `DMA_IF_TX_BASE_DESC_ADDR_CTRL` [2] / `_CUR_` | 0xE000 / 0xE008 | ADDR | TX ring base (low, high) | 2 x 32 | 2 x 128 (`300-12`; OpenWrt 16) | ring size is set by the WRAP bit only; 128 fixed the overload collapse (#60) |
| `DMA_IF_INTR_RX_RUNOUT_MSK/STS` | 0xE010 / 0xE01C | 1 bit per ring | Ring-full IRQ | all on | per ring | - |
| `DMA_IF_INTR_RX_DONE_MSK/STS` | 0xE014 / 0xE020 | 1 bit per ring | RX IRQ, one per packet when unmasked; **no count or timer field** | all on, hard IRQ | NAPI masks while polling | none at saturation: NAPI already polls with the IRQ masked |
| `DMA_IF_INTR_TX_DONE_MSK/STS` | 0xE018 / 0xE024 | TX_DONE[1:0], TX_ALL_DONE[3:2] | TX completion IRQ per ring | on | off (lazy reclaim) | small: earlier page_pool recycling |
| `DMA_IF_PHYSICAL_ADDR_MSK` | 0xE02C | MSK[31:0] | Physical-address mask for DMA addresses (SPEC: DMA reach) | default | default | none; relevant to highmem buffers (#27) |
| `DMA_IF_PKT_CTRL` | 0xCE00 | TRAP_PKT_TAG 4, FWD_PKT_TAG 3, TRAP_PKT_FMT 2, FWD_PKT_FMT 1, PKT_VLAN_FMT 0 | Fields (9310 DG Table 11-4, same bits as the 9300 SDK): `*_PKT_FMT` = original (0) or modified (1) packet for trapped/copied vs forwarded frames; `PKT_VLAN_FMT` = original or modified VLAN tag; `*_PKT_TAG` = insert the CPU tag, only with an external CPU | default (not read) | not written | none directly. "Modified" gives the CPU the frame as the pipeline rewrote it (MAC/TTL/VID done), relevant to #63 |
| `DMA_IF_RX_RING_SIZE` [32] | 0x7C60 | SIZE[9:0], 3 per word | Packets a ring holds before the queue manager treats it as full | 8 | 128 / frags per packet | none; depth only |
| `DMA_IF_RX_RING_CNTR` [32] | 0x7C8C | CNTR[9:0] | Packets pending in a ring; the driver writes back the released count | per packet | per NAPI poll | one MMIO write per poll |
| `DMA_RDMA_CNT_SEL` | 0xE05C | CFG_FRC_RX_READY_F 6, CFG_FRC_TX_READY_F 5, CNT_SEL[4:0] | Debug counter select, force-ready (debug, SPEC) | - | - | none |
| `DMA_L2MSG_TMROUT` | 0xE054 | SPDUP 17, EN 16, SEL[15:0] | Timeout of the L2-notification DMA (learn/age events), not packets | - | - | none |
| `DMA_L2MSG_CNT_SEL` | 0xE058 | CNT_SEL[3:0] | L2-notification counter select | - | - | none |
| `L2_NTFY_CTRL` / `_PKT_TIMEOUT` / `_RST` | 0xEB00 / 0xEB04 / 0xEB08 | NTFY_TYPE, per-event enables, BP_THR, MAX_EVENT, TIMEOUT | L2 learn/age events DMA'd to a separate ring | SDK | 839x only | none on the packet path |
| `NIC_DBG_SEL_0/1`, `NIC_BIST_CTRL_0/1`, `DMY_REG0/1_NIC`, `DMY_REG0_NIC_SYS` | 0xE030-E040, 0xE060, 0xEB0C | debug mux, BIST, dummy | Test only | - | - | none |
| `MAC_L2_CPU_PORT_CTRL` | 0xC70C | INTF_P28_SEL 1, CPU_PORT 0 | Port 28 = internal NIC or external CPU interface (SPEC) | default | default | none |
| `MAC_L2_CPU_TAG_ID_CTRL` | 0xC710 | CPU_TAG_ID[15:0] | CPU-tag identifier | default | default | none |
| `MAC_L2_CPU_MAX_LEN_CTRL` | 0xA3A0 | CPU_PORT_TX_MAX_LEN[13:0] | Largest frame the switch hands to the CPU | - | MTU + overhead | none |
| `MAC_FORCE_MODE_CTRL(28)` | 0xCA8C | SPD_SEL etc. | `0x217` (1G) after the stock loader, raw reset value unread (#60) | untouched | 0x217 | none measured; every CPU path is below 250 Mbit/s |
| `QM_RSN2CPUQID_CTRL_0..8` | 0xA344-A364 | 5-bit queue per reason (ARP_REQ_REP, DHCP, ND, L3 traps, NORMAL_FWD, ...) | Trap reason to CPU queue (= RX ring) | reset map | `reason % 2` | none; control-plane isolation (#60 item 3) |
| `QM_FLAG2CPUQID_CTRL_0/1` | 0xA368 / 0xA36C | 5-bit queue per flag (NEW_SA, ACL_HIT, MIR_HIT, L2/L3_ERR, ATK_TYPE, ...) | Flag to CPU queue, not used by OpenWrt | reset | reset | none |
| `QM_CPUQID2QID_CTRL` / `QM_CPUQID2XGQID_CTRL` [32] | 0xA324 / 0xA334 | QID[2:0] / QID[3:0] | CPU queue to internal egress queue of port 28 | reset | reset | none |
| `SCHED_CPU_Q_CTRL` [32] | 0x7F44 | STRICT_EN 7, WEIGHT[6:0] | Per-CPU-queue strict priority / weight | reset | reset | none; control-plane priority |
| `EGBW_CPU_Q_MAX_LB_CTRL` [32], `EGBW_CPU_PPS_LB_CTRL`, `EGBW_CTRL` | 0x7CB8, 0x78E8, 0x78E4 | EN, RATE, BURST; pps tick/token; RATE_MODE_CPU | Per-CPU-queue and CPU-port rate limits | off (ST5008F: 600 pps) | off | none; protection |
| `FC_CPU_Q_EGR_DROP_THR` [32], `_DROP_CTRL`, `_FORCE_DROP_CTRL`, `_PAGE_CNT`, `_PKT_CNT` | 0x7DC0, 0xC468, 0xC4DC, 0x7E40, 0x7EC0 | ON/OFF pages; peak counters | Per-CPU-queue buffer budget | reset | reset; peak 0x340 pages under flood (NAT.md) | none: drops happen at the DMA ring, not here |

### SoC-level knobs outside DMA_IF

| Knob | Addr | Fields | Status | Effect on µs/pkt |
|---|---|---|---|---|
| Delayed interrupt `TC0..TC5_DLY_INTR` | 0xB8003080-94 | ITI_TRIG 31, DELAYED_IP_SEL[3:0] (SDK PLR `register_map.h`, 9300) | unused by every build | Timer TCn holds CPU interrupt line IP n until it fires, which coalesces by time the whole line the NIC is routed to (`IRR0-5`). Semantics SPEC. ~0 at saturation (NAPI already masked); fewer IRQs at mid load |
| LX bus arbitration `LBPRICR`, `LX0..2_ARB_CFG0-3` | 0xB800000C, 0xB8000010-3C | LX0/1/2_ARB_MODE; 32 slot owners per bus (reset `0x10101010`, alternating masters 0/1) | reset | none unless another LX master (GDMA, USB) competes; the NIC's bus and master ID are unknown |
| LX clock | `0xBB00E220[12:9]` | 175 MHz stock; 204 MHz tested stable (CLOCKS.md) | stock | SPEC: speeds NIC DMA and possibly switch-register MMIO; the MMIO share of 20-23 µs is unmeasured, so expected effect is small |
| DRAM controller prefetch, MCR | 0xB8001000 | IP_REF / DP_REF (on in our builds, #52) | on | already counted in the measured baseline |

### Verdict

- Words like "performance", "turbo", "fast path" or "burst" appear nowhere in the DS. In the SDK NIC registers they appear only in non-packet fields:
  - `CFG_L2MSG_TMROUT_SPDUP` (L2 notification).
  - `SPD_UP_REFILL` (`DMY_REG0_EGRESS_CTRL` 0x7918, egress shaper token refill).
- The NIC has no hardware knobs for:
  - interrupt coalescing (9310 DG §11.1: RX_DONE per packet). The only candidate is the SoC delayed-interrupt timer, SPEC;
  - checksum or TSO (the TX CPU tag has no such bits; the RX tag has only `L2_ERR_PKT`/`L3_ERR_PKT`);
  - descriptor prefetch or burst size;
  - cache-coherent DMA.
- What the NIC hardware does offer:
  - 32 RX rings fed by reason and flag mapping.
  - 2 TX rings, high and low.
  - Per-CPU-queue scheduling and rate limits.
  - These isolate traffic classes; they do not raise throughput.
- The 20-23 µs per packet is CPU-side work: descriptor handling, uncached MMIO, cache invalidate and writeback, skb/page_pool. No register removes it. The fast path Realtek built is the ASIC pipeline (L3 + PIE), not the NIC.
- Fixes stay in the driver (#60): `xmit_more` batching, BQL, `300-12` (lockless doorbell, TX ring 128, reclaim in xmit; NAT.md "NIC path"), and the trap-reason ring map.
- Optional SoC delayed-interrupt test, low expected gain.

## Ranked: unused features worth enabling

CPU-offload and router value first. Section refs are DS printed pages.

1. **On-link neighbours as L3 host routes + default-route offload** (§7.14.1 p.31; #59). Moves downstream IPv6 and inter-VLAN routing off the CPU. Effort M.
2. **PIE as the firewall for ASIC-routed traffic** (§7.13 p.30-31; #66). Add TCP flags and ranges to the tc offload. Effort M.
3. **Storm control + per-protocol ARP/DHCP/BPDU/IGMP meters** (§7.15.3 p.32; SDK `STORM_PORT_PROTO_*`). Caps what reaches the CPU port; would have contained #43. Effort S.
4. **Hardware attack prevention** (§7.12 p.30; `ATK_PRVNT_CTRL` 0xA1AC). Drops WAN junk at line rate before the CPU. Effort S.
5. **Trap-reason to CPU-queue map + CPU queue scheduler and rate limits** (§7.17 p.33, §7.24 p.37; `QM_RSN2CPUQID`, `SCHED_CPU_Q_CTRL`, `EGBW_CPU_Q_MAX_LB_CTRL`). Keeps the control plane alive while NAT saturates VPE0 (#60). Effort S.
6. **uRPF strict/loose** (§7.14.1 p.31; `L3_PORT_IP_ROUTE_CTRL` 0xAB7C). Anti-spoof on the ASIC path. Effort S.
7. **WAN egress shaping + priority queues + SWRED** (§7.17 p.33, §7.22 p.36). Bufferbloat control for ASIC-routed v6 where 10G meets the ISP rate. Effort M.
8. **ACL policers (srTCM/trTCM) + CPU-QID action** (§7.13.1 p.30, §7.15.2 p.32, §7.21 p.35). Per-class limits and steering into the CPU. Effort M.
9. **sFlow + per-route / ACL counters** (§7.11 p.30, §7.13.3 p.31; `L3_ENTRY_COUNTER_*`). Visibility of traffic the CPU never sees. Effort M.
10. **VLAN-based port isolation + L2 learning limits** (§7.4 p.26, §7.3 p.26). Guest/IoT isolation and MAC-flood protection in HW. Effort S.

Also: OAM loopback as a test tool for #22 (§7.27 p.38), 2.5GBASE-X SFP for a 2.5G modem port (§2 p.2, PCS supports it), SoC delayed interrupt (SPEC).
