# Vendor CPU-NIC tuning on RTL9303 (vs OpenWrt)

Question (#60): do the vendor's managed RTL9303 boxes run a faster CPU network path than OpenWrt `rtl838x_eth`?

**Answer: no.** No vendor build tunes the CPU NIC. Every Realtek SDK drop and both TP-Link firmwares use the same SDK defaults. The managed TL-ST5008F is slower by design: user-space NIC driver, packets bridged into Linux over netlink, CPU port shaped to 600 pps. OpenWrt is already ahead on RX (NAPI, page_pool, deeper rings).

## Sources

| Source | SDK version | Where |
|---|---|---|
| Realtek SDK, Zyxel XGS1210-12 GPL | SDK 3.7.0 (nic.c r95761, 2019-03) | `reyalo/Realtek` `sources/rtk-xgs1210/system/drv/nic/`, `system/linux/rtnic/` |
| Realtek SDK, D-Link DMS-1250 GPL | SDK 3.8.0 | `reyalo/Realtek` `sources/rtk-dms1250/` |
| Realtek SDK, Zyxel XGS1x U-Boot | SDK 3.5.0 | `olliver/realtek_sdk` `loader/.../sdk/system/drv/nic/` |
| TL-ST1008F v2 stock | SDK 3.6.6.55087, kernel 3.18.24 (2022-01-19) | flash `stock-extract`: `rtcore.ko`, `rtnic.ko`, `rtk.ko`; decompiles `private/ghidra/stock-rtcore-full.c`, `stock-rtnic.c` |
| TL-ST5008F v2 1.2.0 (managed) | SDK 3.6.9.55156, kernel 3.18.24 (2026-05-06) | `private/china/st5008f-v2-extracted/`: `rtcore.ko`, `ethdriver.ko`, `mgntPort.ko`, `usrImage/app/sbin/core`; decompiles `private/ghidra/vendor-nic/` |
| OpenWrt `rtl838x_eth` | kernel 6.18, OpenWrt `53ec2d05a4` | `target/linux/realtek/files-6.18/drivers/net/ethernet/realtek/` |

- Other RTL93xx GPL drops searched (GitHub code search, web): only the copies above carry `nic_rtl9300.c`. XikeStor SKS8300, Zyxel XGS1250-12, Netgear: no public SDK NIC source found.
- Regenerate: `scripts/vendor_nic_decompile.py` (Ghidra headless; `scripts/ghidra/DecompileMatching.java`), `scripts/vendor_nic_values.py` (ring-size tables from ELF data).

## Architecture per firmware

- **SDK / ST1008F stock (kernel-mode SDK):** `rtcore.ko` holds `drv/nic` (rings, ISR); `rtnic.ko` registers `eth0` and calls `drv_nic_init`. RX handled in hard-IRQ context (`drv_nic_isr_handler` → `_nic_isr_rxRoutine`, rings walked 31 → 0), skb handed up with `netif_rx`. No NAPI.
- **ST5008F managed (user-mode SDK):**
  - `rtcore.ko` `_nic_intr_handler`: on any RX_DONE/RX_RUNOUT/TX_DONE writes 0 to the three mask registers (0xE010/0xE014/0xE018) and wakes `nic_intr_wait_queue`.
  - User-space `core` runs the SDK NIC driver (`drv_nic_init`, `r9300_*`, `rtnic_pkt_alloc`) with `CONFIG_SDK_NIC_RX_CB_IN_THREAD`: `nic_rx_thread_create` (stack 0x1FA0, priority 0), per-queue depth 800.
  - Linux sees traffic only via `ethdriver.ko`: netdev `tp-eth`, 1 TX / 1 RX queue, netlink protocol 22; RX = netlink from `core` → `netif_rx_ni`, TX = skb → netlink to `core`. Every management packet crosses user space twice.
  - In-kernel fast path only for ERPS CCM (`_rtk_nic_tx_ccm`, `_rtk_ccm_detect`).
- **Both vendor kernels are uniprocessor:** version banners `#36 Wed Jan 19 …` (ST1008F) and `#3 Wed May 6 …` (ST5008F) carry no `SMP`. VPE1 is unused by every vendor build.

## Table: vendor vs SDK vs OpenWrt

| Knob | SDK 3.5 / 3.7 / 3.8 | ST1008F stock | ST5008F managed | OpenWrt 6.18 |
|---|---|---|---|---|
| RX rings used | 32 (`NIC_9300_RXRING_NUM`) | 32 | 32 | 2 (`RTETH_RX_RINGS`) |
| RX descriptors / ring | 8 (`rxRingIdSize_9300`) | 8 (`rtcore.ko .data+0xf1b8`) | 8 (`core .data`, addr 0x1526c28) | 128 |
| RX total descriptors | 256 | 256 | 256 | 256 |
| HW ring size reg (`DMA_IF_RX_RING_SIZE` 0x7C60) | = descriptors (8) | 8 | 8 | 128 / frags-per-packet |
| TX rings × size | 2 × 32 | 2 × 32 (`rtcore.ko .data+0xf1b0`) | 2 × 32 | 2 × 16 (`RTETH_TX_RING_SIZE`) |
| RX buffer | 1600 B (`RTNIC_MAX_PKTLEN`), truncate 0x640 | 0x640 (`rtnic.ko` init) | 1600 | 1568 B frags, page_pool, truncate off |
| Jumbo | multi-descriptor (`more` bit) reassembly | same | same | multi-frag, MTU up to 12288 |
| IRQ masks | RX_DONE + RX_RUNOUT all rings, TX_DONE + TX_ALL_DONE 0x3 | same | all masked in ISR, re-armed by user thread | per-ring, NAPI |
| Interrupt coalescing | none: DMA_IF has no timer/count register (only `DMA_L2MSG_TMROUT` 0xE054 for L2-notify) | none | none (mask + thread drain) | none (NAPI) |
| RX context | hard IRQ, `netif_rx` (`rtnic_drv.c:587`) | hard IRQ | user thread → netlink → `netif_rx_ni` | NAPI poll |
| NAPI budget | — | — | — | default weight |
| TX doorbell | per packet: RMW of `DMA_IF_CTRL` fetch bit (`nic.c:969`) | same | same (user space; `_rtk_nic_tx_ccm` in kernel) | per packet: poll-read + write `DMA_IF_CTRL` (`rtl838x_eth.c:1168`) |
| xmit_more / BQL | — | — | — | no / no |
| netdev queues | 1 TX, `tx_queue_len` 1000 | 1 TX, 1000 | `tp-eth` 1 TX / 1 RX | 1 |
| Offload flags | none | none | none | `NETIF_F_RXCSUM` |
| TX csum / TSO | no HW support (CPU tag has no csum fields) | — | — | — |
| CPU port 28 `MAC_FORCE_MODE_CTRL` (0xCA8C) | `r9300_cpuForceLinkupEnable_set`: FC_EN=1, RX/TX pause=0, FORCE_LINK, MAC_FORCE; **SPD_SEL untouched** | same (`stock-rtcore-full.c` 0x2c038) | same; `drvCpuPortSetRealtek` = stub | write 0x217 (SPD_SEL=2, 1G) |
| CPU port egress bandwidth (EGBW port 28) | not set at init (`dal_longan_rate_init` skips CPU) | off | **on, packet mode, 600 pps** (1200 pps in mode 1) — `tpPktCtlCpuPortSpeedSet(SPEED_LIMIT)` → `drvPortCpuEgressRateSetRealtek` → `subDrvPortCpuModeTransSpeed` | off |
| Per-trap (CPU code) rate limits | none | none | TPCL/ACL meters per CPU code (`swTpclCpuDefEntrySpeedSet`, `drvPktCtlSpeedSetRealtek`: rate, burst = 2 × rate) | none |
| Trap reason → RX ring (`QM_RSN2CPUQID_CTRL_0..7`, 0xA344+) | API only (`dal_longan_trap_mgmtFrameQueue_set`, named fields e.g. `ARP_REQ_REP`); init keeps HW reset map | HW reset map | HW reset map + TP-Link `adPktCtlSpecificReason2CPU` (values not extracted) | `reason % 2` round robin |
| SMP / VPE1 | — | UP kernel | UP kernel | SMP available, all NAPI on one VPE |
| IRQ affinity / RPS | — | — | — | none set |

## What this rules out

- No hidden vendor CPU-port speed setting: SPD_SEL is never written by SDK, ST1008F or ST5008F. After the stock loader (no `rtk network on`) `MAC_FORCE_MODE_CTRL(28)` `0xbb00ca8c` reads `0x217` = 1G (2026-10-11). The loader (`0x83f67548`) writes bits 9/8/7/1/0 of it, so this is not the raw reset value; 1G is consistent with the hardware default but unmeasured (needs a read before the stock loader).
- No hardware interrupt coalescing exists to copy.
- No vendor ring depth larger than OpenWrt's.
- No vendor use of the second VPE.

## Ranked: what to adopt (feeds #60, #16)

Gains below are the pre-measurement estimates. Measured outcome per item: [NAT.md](NAT.md) "NIC path" and [MAINLINE-PORT.md](MAINLINE-PORT.md) section 9.

Status (2026-10-12):
- Item 1: RPS onto VPE1 measured worse on 6.18 (213 → 128 Mbit/s NAT + flowtable). SMP 7.3: eth0 on CPU1 ≈ UP, no gain (MAINLINE-PORT section 9). TX completion on the other VPE (`300-14` `tx_cpu=0`, eth0 on CPU1): throughput drops to ~44 %; 300-14 parked (MAINLINE-PORT section 9).
- Item 2: done and exceeded: `300-11` (ring 32, BQL, xmit_more) then `300-12` (ring 128, lockless doorbell, reclaim in xmit): UDP 64 B 55.8 → 70 kpps, TCP NAT 302 → 358 Mbit/s.
- Items 3, 4: not done.
- Item 5: SPD_SEL A/B deferred until the CPU path nears 1 Gbit/s (owner, 2026-10-11).

1. **Use VPE1 (SMP kernel + RPS, or second RX ring's NAPI on VPE1 via the multi-parent irqchip).** No vendor precedent; the only idle compute. Expected 1.2–1.6x pps on MIPS MT (shared pipeline, gain from hiding uncached-MMIO and cache-miss stalls). Highest value.
2. **TX ring 32 per ring (SDK value) + `xmit_more` doorbell batching + BQL.** SDK depth is 2x OpenWrt; batching is not in any vendor code but removes one uncached read+write per packet under bursts. Expected: fewer `NETDEV_TX_BUSY` requeues; single-digit to ~15 % at burst load.
3. **Trap reason → ring map** via the SDK's named `QM_RSN2CPUQID` fields (`dal_longan_trap_mgmtFrameQueue_set`): ARP/STP/LACP/BPDU on a high ring, routed/NAT traffic on another, NAPI per ring. No throughput gain; keeps the control plane alive when routed traffic saturates the CPU. Pair with item 4.
4. **Optional CPU protection, ST5008F style but high limit:** EGBW port 28 in packet mode at ~1.25x the measured max CPU pps (e.g. ~25 kpps), or per-reason meters. Protects against storms (#43 loop). Not a throughput gain; do not copy the 600 pps value.
5. **CPU port SPD_SEL:** no vendor code writes it; after the stock loader it reads 1G (`0x217`; stock writes bits 9/8/7/1/0 only). Raw reset value unread (needs a pre-loader read); test 10G (4) / 2.5G (5) instead of forcing 1G. Gain unknown; ASIC limiters on port 28 already measured off.
6. **Keep OpenWrt's RX design** (NAPI, page_pool, 2 × 128): ahead of every vendor build. Do not port the SDK's hard-IRQ `netif_rx` or the ST5008F user-space thread.

Refs: #60 #16 #7 #15 #43.
