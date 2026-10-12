# Stock switch defaults: reg-diff and per-row verdict (#80)

What our `rtk network on` writes from `shared/rtl930x-sw/rtl930x_sw_defaults.h` (SDK "Chip Construct" + bootloader DAL init, [RTK-COMMANDS.md](RTK-COMMANDS.md#stock-switch-init-what-rtk-network-on-writes-80)), measured 2026-10-12 on the board (branch `worktree-agent-a224c1e0dfdf94299`, cage 1 SFP-10GSR-85, stock clocks).

## Method

- `cold`: power-up, stock only copies ours from flash, no network on, `reg-diff capture cold --window` (whole switch core `0xbb000000-0xbb00ffff`, 16384 words). Our eth probe has already masked the NIC IRQs and turned NIC DMA off; `board_late_init` cleared the cage-presence pinmux.
- `stock-net`: power-up, stock `rtk network on`, `capture stock-net --window`.
- `ours-final`: power-up, stock only copies ours, `uboot-test network` (our network on, all rows), `capture ours-final --window`.
- `reg-diff compare stock-net ours-final --sdk`; `sw_defaults_gen.py --verdict cold --ours ours-final`.

## Result: stock vs ours (232 of 16384 words differ, none from the table)

Every register the table writes equals stock. The 232 differing words:

| Group | Words | Reason |
|---|---|---|
| `SPI_DATA[]` 0x464-0x654 | 76 | switch-core SPI master data buffer, unused, random content per boot |
| `DMA_IF_RX_BASE/CUR` 0xdf00-0xdffc | 64 | NIC rings: stock armed its NIC, ours arms at the first eth start (capture taken before) |
| `STAT_*`, `HSA/HSB/HSM` debug | 44 | counters and last-packet debug registers |
| `FC_*_CNT` page/packet counters | 8 | live queue occupancy |
| `L2_LRN_*CONSTRT_CNT` | 11 | learned-address counters (live) |
| NIC TX base/cur, IRQ masks, `DMA_IF_CTRL`, `MAC_L2_PORT_CTRL[28]`, `RX_RING_CNTR` | 10 | same as the rings |
| `MAC_L2_ADDR_CTRL` 0xc714/0xc718 | 2 | ours writes the board MAC (stock leaves `00:e0:4c:00:00:00`) |
| I2C master 0x36c/0x370/0x384 | 3 | last transfer + our I2C driver's GLB config (`0x000000ff` vs stock `0x00a3ffff`); our driver reads every cage |
| pinmux `SPI_CTRL1` 0x3a0 | 1 | ours clears GPIO3-7 SPI mux on purpose (cage presence, #29) |
| SerDes indirect cmd/data 0x3b0/0x3b4 | 2 | last access |
| `TBL_ACCESS_DATA_0` 0xb344 | 1 | last table access |
| `ISR_*` latches, `MAC_LINK_STS` | 4 | live status |
| unnamed words of `STAT_PORT_MIB_CNTR(0)` (0x754) and `STAT_PORT_PRVTE_CNTR(28)` (0x31d8, 0x31dc) | 3 | counter-like, change between reads |
| thermal 0x6c | 0-1 | live |

- Two table errors found by this diff and fixed in `sw_defaults_gen.py`: `EGBW_PORT_CTRL` burst is set for port 0 only by stock (ports 8-27 keep reset `0x8000`); `EGBW_*_SET1` (ports 24-27) are global 2D arrays inside the 0xE300 per-port window (port-major, 12 queues), not per-port block registers.
- Port isolation (a table, not in the window) differs on purpose: stock all-to-all, ours cages -> CPU only.

## Needed or not

- Traffic: `uboot-test net` passes with no row applied (`rtk_sw_defaults=none`, 3/3) and with all 640 (8/8): the table is not needed for CPU traffic on an isolated mgmt port. It is kept so the switch matches stock (forwarding, flow control at 10G, queue thresholds).
- Purpose split (our reading): cpu 108 rows, perf 468, policy 26; no-op (the value equals the cold reset value) 38. The `FC_GLB_SYS_UTIL_THR` row shows "not held": the SDK writes it twice (0x958, then 1).

## Per-row verdict (`sw_defaults_gen.py --verdict cold --ours ours-final`)

| Row | Purpose | Cold -> table | Verdict |
|---|---|---|---|
| `0xca00` construct: SMI_GLB_CTRL.SMI0_POLL_SEL +3 | policy | 0xf00000 -> 0x800000 | policy |
| `0xddf4` construct: TRIG_AUTO_RECOVER_CTRL_INGRESS.EN_SYS_DSC_ERR_TRIG +2 | perf | 0x0 -> 0x0 | no-op |
| `0x7ad0` construct: TRIG_AUTO_RECOVER_CTRL_EGRESS.EN_LD_TX_DSC_ERR_TRIG +1 | perf | 0x0 -> 0x0 | no-op |
| `0x3bfc` construct: TRIG_AUTO_RECOVER_CTRL_MAC.EN_FIFO_ERR_TRIG | perf | 0x0 -> 0x0 | no-op |
| `0x0230` construct: DMY_REG0_CHIP_MISC_R.DUMMY | perf | 0x0 -> 0xfffffff | perf |
| `0x78e4` construct: EGBW_CTRL.RATE_MODE_CPU | cpu | 0x0 -> 0x0 | no-op |
| `0x7824` construct: EGBW_PORT_CTRL[28].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7cbc` construct: EGBW_CPU_Q_MAX_LB_CTRL[0].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7cc4` construct: EGBW_CPU_Q_MAX_LB_CTRL[1].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7ccc` construct: EGBW_CPU_Q_MAX_LB_CTRL[2].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7cd4` construct: EGBW_CPU_Q_MAX_LB_CTRL[3].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7cdc` construct: EGBW_CPU_Q_MAX_LB_CTRL[4].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7ce4` construct: EGBW_CPU_Q_MAX_LB_CTRL[5].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7cec` construct: EGBW_CPU_Q_MAX_LB_CTRL[6].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7cf4` construct: EGBW_CPU_Q_MAX_LB_CTRL[7].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7cfc` construct: EGBW_CPU_Q_MAX_LB_CTRL[8].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d04` construct: EGBW_CPU_Q_MAX_LB_CTRL[9].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d0c` construct: EGBW_CPU_Q_MAX_LB_CTRL[10].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d14` construct: EGBW_CPU_Q_MAX_LB_CTRL[11].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d1c` construct: EGBW_CPU_Q_MAX_LB_CTRL[12].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d24` construct: EGBW_CPU_Q_MAX_LB_CTRL[13].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d2c` construct: EGBW_CPU_Q_MAX_LB_CTRL[14].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d34` construct: EGBW_CPU_Q_MAX_LB_CTRL[15].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d3c` construct: EGBW_CPU_Q_MAX_LB_CTRL[16].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d44` construct: EGBW_CPU_Q_MAX_LB_CTRL[17].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d4c` construct: EGBW_CPU_Q_MAX_LB_CTRL[18].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d54` construct: EGBW_CPU_Q_MAX_LB_CTRL[19].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d5c` construct: EGBW_CPU_Q_MAX_LB_CTRL[20].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d64` construct: EGBW_CPU_Q_MAX_LB_CTRL[21].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d6c` construct: EGBW_CPU_Q_MAX_LB_CTRL[22].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d74` construct: EGBW_CPU_Q_MAX_LB_CTRL[23].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d7c` construct: EGBW_CPU_Q_MAX_LB_CTRL[24].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d84` construct: EGBW_CPU_Q_MAX_LB_CTRL[25].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d8c` construct: EGBW_CPU_Q_MAX_LB_CTRL[26].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d94` construct: EGBW_CPU_Q_MAX_LB_CTRL[27].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7d9c` construct: EGBW_CPU_Q_MAX_LB_CTRL[28].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7da4` construct: EGBW_CPU_Q_MAX_LB_CTRL[29].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7dac` construct: EGBW_CPU_Q_MAX_LB_CTRL[30].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7db4` construct: EGBW_CPU_Q_MAX_LB_CTRL[31].BURST | cpu | 0x8000 -> 0x5 | cpu |
| `0x7664` construct: EGBW_PORT_CTRL[0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3c64` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[0][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3ca4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[0][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cc4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[0][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3ce4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[0][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3c6c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[0][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3ca8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[0][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cc8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[0][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3ce8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[0][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3c74` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[0][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cac` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[0][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3ccc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[0][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3cec` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[0][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3c7c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[0][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cb0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[0][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cd0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[0][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3cf0` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[0][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3c84` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[0][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cb4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[0][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cd4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[0][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3cf4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[0][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3c8c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[0][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cb8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[0][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cd8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[0][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3cf8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[0][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3c94` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[0][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cbc` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[0][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cdc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[0][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3cfc` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[0][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3c9c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[0][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3cc0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[0][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x3ce0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[0][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x3d00` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[0][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x4864` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[8][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48a4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[8][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48c4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[8][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x48e4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[8][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x486c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[8][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48a8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[8][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48c8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[8][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x48e8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[8][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x4874` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[8][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48ac` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[8][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48cc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[8][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x48ec` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[8][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x487c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[8][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48b0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[8][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48d0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[8][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x48f0` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[8][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x4884` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[8][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48b4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[8][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48d4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[8][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x48f4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[8][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x488c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[8][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48b8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[8][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48d8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[8][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x48f8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[8][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x4894` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[8][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48bc` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[8][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48dc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[8][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x48fc` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[8][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x489c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[8][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48c0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[8][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x48e0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[8][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x4900` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[8][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5464` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[16][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54a4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[16][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54c4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[16][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x54e4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[16][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x546c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[16][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54a8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[16][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54c8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[16][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x54e8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[16][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5474` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[16][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54ac` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[16][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54cc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[16][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x54ec` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[16][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x547c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[16][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54b0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[16][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54d0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[16][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x54f0` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[16][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5484` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[16][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54b4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[16][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54d4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[16][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x54f4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[16][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x548c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[16][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54b8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[16][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54d8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[16][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x54f8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[16][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5494` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[16][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54bc` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[16][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54dc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[16][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x54fc` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[16][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x549c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[16][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54c0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[16][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x54e0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[16][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5500` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[16][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5a64` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[20][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5aa4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[20][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ac4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[20][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5ae4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[20][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5a6c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[20][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5aa8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[20][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ac8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[20][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5ae8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[20][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5a74` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[20][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5aac` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[20][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5acc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[20][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5aec` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[20][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5a7c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[20][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ab0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[20][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ad0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[20][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5af0` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[20][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5a84` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[20][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ab4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[20][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ad4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[20][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5af4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[20][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5a8c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[20][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ab8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[20][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ad8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[20][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5af8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[20][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5a94` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[20][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5abc` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[20][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5adc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[20][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5afc` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[20][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5a9c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET0[20][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ac0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET0[20][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0x5ae0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET0[20][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x5b00` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET0[20][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe304` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe490` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe550` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe610` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe30c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe494` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe554` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe614` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe314` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe498` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe558` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe618` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe31c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe49c` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe55c` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe61c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe324` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4a0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe560` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe620` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe32c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4a4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe564` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe624` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe334` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4a8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe568` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe628` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe33c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4ac` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe56c` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe62c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe344` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][8].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4b0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][8].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe570` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][8].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe630` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][8].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe34c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][9].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4b4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][9].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe574` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][9].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe634` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][9].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe354` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][10].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4b8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][10].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe578` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][10].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe638` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][10].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe35c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[24][11].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4bc` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[24][11].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe57c` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[24][11].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe63c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[24][11].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe364` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4c0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe580` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe640` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe36c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4c4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe584` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe644` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe374` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4c8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe588` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe648` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe37c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4cc` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe58c` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe64c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe384` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4d0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe590` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe650` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe38c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4d4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe594` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe654` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe394` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4d8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe598` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe658` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe39c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4dc` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe59c` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe65c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3a4` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][8].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4e0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][8].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5a0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][8].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe660` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][8].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3ac` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][9].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4e4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][9].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5a4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][9].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe664` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][9].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3b4` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][10].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4e8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][10].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5a8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][10].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe668` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][10].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3bc` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[25][11].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4ec` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[25][11].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5ac` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[25][11].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe66c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[25][11].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3c4` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4f0` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5b0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe670` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3cc` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4f4` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5b4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe674` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3d4` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4f8` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5b8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe678` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3dc` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe4fc` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5bc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe67c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3e4` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe500` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5c0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe680` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3ec` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe504` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5c4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe684` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3f4` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe508` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5c8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe688` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe3fc` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe50c` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5cc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe68c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe404` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][8].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe510` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][8].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5d0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][8].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe690` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][8].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe40c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][9].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe514` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][9].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5d4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][9].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe694` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][9].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe414` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][10].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe518` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][10].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5d8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][10].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe698` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][10].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe41c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[26][11].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe51c` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[26][11].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5dc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[26][11].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe69c` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[26][11].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe424` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe520` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][0].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5e0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6a0` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][0].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe42c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe524` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][1].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5e4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6a4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][1].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe434` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe528` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][2].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5e8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6a8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][2].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe43c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe52c` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][3].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5ec` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6ac` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][3].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe444` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe530` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][4].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5f0` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6b0` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][4].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe44c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe534` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][5].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5f4` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6b4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][5].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe454` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe538` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][6].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5f8` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6b8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][6].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe45c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe53c` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][7].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe5fc` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6bc` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][7].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe464` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][8].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe540` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][8].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe600` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][8].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6c0` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][8].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe46c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][9].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe544` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][9].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe604` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][9].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6c4` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][9].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe474` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][10].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe548` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][10].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe608` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][10].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6c8` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][10].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe47c` construct: EGBW_PORT_Q_MAX_LB_CTRL_SET1[27][11].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe54c` construct: EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_SET1[27][11].BURST | perf | 0x8000 -> 0x4000 | perf |
| `0xe60c` construct: EGBW_PORT_Q_ASSURED_LB_CTRL_SET1[27][11].RATE | perf | 0xfffff -> 0x0 | perf |
| `0xe6cc` construct: EGBW_PORT_Q_FIX_LB_CTRL_SET1[27][11].RATE | perf | 0xfffff -> 0x0 | perf |
| `0x7a9c` construct: SCHED_PORT_ALGO_CTRL[28].SCHED_TYPE | cpu | 0x0 -> 0x10000000 | cpu |
| `0x9ae0` construct: PRI_SEL_CTRL.PORT_PRI_REMAP_EN +2 | policy | 0xe00 -> 0x0 | policy |
| `0xa324` construct: QM_CPUQID2QID_CTRL[0].QID +7 | cpu | 0x0 -> 0xfac688 | cpu |
| `0xa334` construct: QM_CPUQID2XGQID_CTRL[0].QID +7 | cpu | 0x0 -> 0x76543210 | cpu |
| `0xa338` construct: QM_CPUQID2XGQID_CTRL[8].QID +3 | cpu | 0x0 -> 0xba98 | cpu |
| `0xd8f4` construct: FC_PORT_THR_SET_SEL[0].IDX | perf | 0x0 -> 0x1 | perf |
| `0x79dc` construct: FC_PORT_EGR_DROP_THR_SET_SEL[0].IDX | perf | 0x0 -> 0x1 | perf |
| `0xdc58` construct: ETE_FC_REMOTE_PORT_THR_SET_SEL[0].IDX | perf | 0x0 -> 0x1 | perf |
| `0xd8f4` construct: FC_PORT_THR_SET_SEL[8].IDX | perf | 0x0 -> 0x10000 | perf |
| `0x79dc` construct: FC_PORT_EGR_DROP_THR_SET_SEL[8].IDX | perf | 0x0 -> 0x10000 | perf |
| `0xdc58` construct: ETE_FC_REMOTE_PORT_THR_SET_SEL[8].IDX | perf | 0x0 -> 0x100 | perf |
| `0xd8f8` construct: FC_PORT_THR_SET_SEL[16].IDX | perf | 0x0 -> 0x1 | perf |
| `0x79e0` construct: FC_PORT_EGR_DROP_THR_SET_SEL[16].IDX | perf | 0x0 -> 0x1 | perf |
| `0xdc58` construct: ETE_FC_REMOTE_PORT_THR_SET_SEL[16].IDX | perf | 0x0 -> 0x10000 | perf |
| `0xd8f8` construct: FC_PORT_THR_SET_SEL[20].IDX | perf | 0x0 -> 0x100 | perf |
| `0x79e0` construct: FC_PORT_EGR_DROP_THR_SET_SEL[20].IDX | perf | 0x0 -> 0x100 | perf |
| `0xdc58` construct: ETE_FC_REMOTE_PORT_THR_SET_SEL[20].IDX | perf | 0x0 -> 0x100000 | perf |
| `0xd8f8` construct: FC_PORT_THR_SET_SEL[24].IDX | perf | 0x0 -> 0x10000 | perf |
| `0x79e0` construct: FC_PORT_EGR_DROP_THR_SET_SEL[24].IDX | perf | 0x0 -> 0x10000 | perf |
| `0xdc58` construct: ETE_FC_REMOTE_PORT_THR_SET_SEL[24].IDX | perf | 0x0 -> 0x1000000 | perf |
| `0xd8f8` construct: FC_PORT_THR_SET_SEL[25].IDX | perf | 0x0 -> 0x40000 | perf |
| `0x79e0` construct: FC_PORT_EGR_DROP_THR_SET_SEL[25].IDX | perf | 0x0 -> 0x40000 | perf |
| `0xdc58` construct: ETE_FC_REMOTE_PORT_THR_SET_SEL[25].IDX | perf | 0x0 -> 0x2000000 | perf |
| `0xd8f8` construct: FC_PORT_THR_SET_SEL[26].IDX | perf | 0x0 -> 0x100000 | perf |
| `0x79e0` construct: FC_PORT_EGR_DROP_THR_SET_SEL[26].IDX | perf | 0x0 -> 0x100000 | perf |
| `0xdc58` construct: ETE_FC_REMOTE_PORT_THR_SET_SEL[26].IDX | perf | 0x0 -> 0x4000000 | perf |
| `0xd8f8` construct: FC_PORT_THR_SET_SEL[27].IDX | perf | 0x0 -> 0x400000 | perf |
| `0x79e0` construct: FC_PORT_EGR_DROP_THR_SET_SEL[27].IDX | perf | 0x0 -> 0x400000 | perf |
| `0xdc58` construct: ETE_FC_REMOTE_PORT_THR_SET_SEL[27].IDX | perf | 0x0 -> 0x8000000 | perf |
| `0xc3f0` construct: FC_PORT_EGR_DROP_CTRL[28].REF_RXCNGST | cpu | 0x2 -> 0x0 | cpu |
| `0xd8f8` construct: FC_PORT_THR_SET_SEL[28].IDX | cpu | 0x0 -> 0x0 | no-op |
| `0xd87c` construct: FC_GLB_DROP_THR.DROP_ALL | perf | 0xfe0 -> 0xff8 | perf |
| `0xd878` construct: FC_GLB_SYS_UTIL_THR.THR | perf | 0x300 -> 0x958 | perf (not held after ours) |
| `0xd880` construct: FC_GLB_HI_THR.ON +1 | perf | 0x3d803c0 -> 0xa2009d0 | perf |
| `0xd884` construct: FC_GLB_LO_THR.ON +1 | perf | 0x33002e5 -> 0x9580908 | perf |
| `0xd888` construct: FC_GLB_FCOFF_HI_THR.ON +1 | perf | 0x3d803c0 -> 0xa2009d0 | perf |
| `0xd88c` construct: FC_GLB_FCOFF_LO_THR.ON +1 | perf | 0x33002e5 -> 0x9580908 | perf |
| `0xd890` construct: FC_JUMBO_HI_THR.ON +1 | perf | 0x3d803c0 -> 0xd300ce0 | perf |
| `0xd894` construct: FC_JUMBO_LO_THR.ON +1 | perf | 0x33002e5 -> 0xc680c18 | perf |
| `0xd898` construct: FC_JUMBO_FCOFF_HI_THR.ON +1 | perf | 0x3d803c0 -> 0xd300ce0 | perf |
| `0xd89c` construct: FC_JUMBO_FCOFF_LO_THR.ON +1 | perf | 0x33002e5 -> 0xc680c18 | perf |
| `0xd8a0` construct: FC_JUMBO_THR_ADJUST.SYS_USED_PAGE_THR | perf | 0x0 -> 0xdc8 | perf |
| `0x79e4` construct: FC_LB_PORT_Q_EGR_DROP_THR.ON +1 | perf | 0x0 -> 0x4e0044 | perf |
| `0x7a98` construct: SC_P_CTRL.DRAIN_OUT_THR_H +1 | perf | 0x980098 -> 0x1400140 | perf |
| `0xdc3c` construct: ETE_FC_CASCADE_PORT_DROP_THR.ON +1 | perf | 0x5070485 -> 0x5070485 | no-op |
| `0xd804` construct: FC_PORT_ACT_CTRL[0].ALLOW_PAGE_CNT | perf | 0x32 -> 0x32 | no-op |
| `0xd824` construct: FC_PORT_ACT_CTRL[8].ALLOW_PAGE_CNT | perf | 0x32 -> 0x32 | no-op |
| `0xd844` construct: FC_PORT_ACT_CTRL[16].ALLOW_PAGE_CNT | perf | 0x32 -> 0x32 | no-op |
| `0xd854` construct: FC_PORT_ACT_CTRL[20].ALLOW_PAGE_CNT | perf | 0x32 -> 0x32 | no-op |
| `0xd864` construct: FC_PORT_ACT_CTRL[24].ALLOW_PAGE_CNT | perf | 0x32 -> 0x32 | no-op |
| `0xd868` construct: FC_PORT_ACT_CTRL[25].ALLOW_PAGE_CNT | perf | 0x32 -> 0x32 | no-op |
| `0xd86c` construct: FC_PORT_ACT_CTRL[26].ALLOW_PAGE_CNT | perf | 0x32 -> 0x32 | no-op |
| `0xd870` construct: FC_PORT_ACT_CTRL[27].ALLOW_PAGE_CNT | perf | 0x32 -> 0x32 | no-op |
| `0xd8a4` construct: FC_PORT_HI_THR[0].ON +1 | perf | 0x98008c -> 0x11b0111 | perf |
| `0xd8c4` construct: FC_PORT_FCOFF_HI_THR[0].ON +1 | perf | 0x98008c -> 0x11b0111 | perf |
| `0xd8b4` construct: FC_PORT_LO_THR[0].ON +1 | perf | 0x27001c -> 0xa00078 | perf |
| `0xd8d4` construct: FC_PORT_FCOFF_LO_THR[0].ON +1 | perf | 0x27001c -> 0xa00078 | perf |
| `0xd8e4` construct: FC_PORT_GUAR_THR[0].THR | perf | 0x10 -> 0x10 | no-op |
| `0xd8a8` construct: FC_PORT_HI_THR[1].ON +1 | perf | 0x98008c -> 0x11b0111 | perf |
| `0xd8c8` construct: FC_PORT_FCOFF_HI_THR[1].ON +1 | perf | 0x98008c -> 0x11b0111 | perf |
| `0xd8b8` construct: FC_PORT_LO_THR[1].ON +1 | perf | 0x27001c -> 0xa00078 | perf |
| `0xd8d8` construct: FC_PORT_FCOFF_LO_THR[1].ON +1 | perf | 0x27001c -> 0xa00078 | perf |
| `0xd8e8` construct: FC_PORT_GUAR_THR[1].THR | perf | 0x10 -> 0x10 | no-op |
| `0xd8ac` construct: FC_PORT_HI_THR[2].ON +1 | perf | 0x98008c -> 0x11b0111 | perf |
| `0xd8cc` construct: FC_PORT_FCOFF_HI_THR[2].ON +1 | perf | 0x98008c -> 0x11b0111 | perf |
| `0xd8bc` construct: FC_PORT_LO_THR[2].ON +1 | perf | 0x27001c -> 0xa00078 | perf |
| `0xd8dc` construct: FC_PORT_FCOFF_LO_THR[2].ON +1 | perf | 0x27001c -> 0xa00078 | perf |
| `0xd8ec` construct: FC_PORT_GUAR_THR[2].THR | perf | 0x10 -> 0x10 | no-op |
| `0xd8b0` construct: FC_PORT_HI_THR[3].ON +1 | perf | 0x98008c -> 0x17d0173 | perf |
| `0xd8d0` construct: FC_PORT_FCOFF_HI_THR[3].ON +1 | perf | 0x98008c -> 0x17d0173 | perf |
| `0xd8c0` construct: FC_PORT_LO_THR[3].ON +1 | perf | 0x27001c -> 0x230019 | perf |
| `0xd8e0` construct: FC_PORT_FCOFF_LO_THR[3].ON +1 | perf | 0x27001c -> 0x230019 | perf |
| `0xd8f0` construct: FC_PORT_GUAR_THR[3].THR | perf | 0x10 -> 0x10 | no-op |
| `0xdc40` construct: ETE_FC_ON_REMOTE_PORT_THR[0].ON +1 | perf | 0x17000d -> 0x17000d | no-op |
| `0xdc48` construct: ETE_FC_OFF_REMOTE_PORT_THR[0].ON +1 | perf | 0x17000d -> 0x17000d | no-op |
| `0xdc50` construct: ETE_FC_REMOTE_PORT_GUAR_THR[0].THR | perf | 0x10 -> 0x10 | no-op |
| `0xdc44` construct: ETE_FC_ON_REMOTE_PORT_THR[1].ON +1 | perf | 0x17000d -> 0x17000d | no-op |
| `0xdc4c` construct: ETE_FC_OFF_REMOTE_PORT_THR[1].ON +1 | perf | 0x17000d -> 0x17000d | no-op |
| `0xdc54` construct: ETE_FC_REMOTE_PORT_GUAR_THR[1].THR | perf | 0x10 -> 0x10 | no-op |
| `0x791c` construct: FC_Q_EGR_DROP_THR[0][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7920` construct: FC_Q_EGR_DROP_THR[0][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x7924` construct: FC_Q_EGR_DROP_THR[0][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7928` construct: FC_Q_EGR_DROP_THR[0][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a08` construct: SWRED_QUEUE_DROP_CTRL[0][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a0c` construct: SWRED_QUEUE_DROP_CTRL[0][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a10` construct: SWRED_QUEUE_DROP_CTRL[0][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x792c` construct: FC_Q_EGR_DROP_THR[1][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7930` construct: FC_Q_EGR_DROP_THR[1][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x7934` construct: FC_Q_EGR_DROP_THR[1][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7938` construct: FC_Q_EGR_DROP_THR[1][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a14` construct: SWRED_QUEUE_DROP_CTRL[1][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a18` construct: SWRED_QUEUE_DROP_CTRL[1][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a1c` construct: SWRED_QUEUE_DROP_CTRL[1][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x793c` construct: FC_Q_EGR_DROP_THR[2][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7940` construct: FC_Q_EGR_DROP_THR[2][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x7944` construct: FC_Q_EGR_DROP_THR[2][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7948` construct: FC_Q_EGR_DROP_THR[2][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a20` construct: SWRED_QUEUE_DROP_CTRL[2][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a24` construct: SWRED_QUEUE_DROP_CTRL[2][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a28` construct: SWRED_QUEUE_DROP_CTRL[2][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x794c` construct: FC_Q_EGR_DROP_THR[3][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7950` construct: FC_Q_EGR_DROP_THR[3][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x7954` construct: FC_Q_EGR_DROP_THR[3][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7958` construct: FC_Q_EGR_DROP_THR[3][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a2c` construct: SWRED_QUEUE_DROP_CTRL[3][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a30` construct: SWRED_QUEUE_DROP_CTRL[3][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a34` construct: SWRED_QUEUE_DROP_CTRL[3][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x795c` construct: FC_Q_EGR_DROP_THR[4][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7960` construct: FC_Q_EGR_DROP_THR[4][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x7964` construct: FC_Q_EGR_DROP_THR[4][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7968` construct: FC_Q_EGR_DROP_THR[4][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a38` construct: SWRED_QUEUE_DROP_CTRL[4][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a3c` construct: SWRED_QUEUE_DROP_CTRL[4][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a40` construct: SWRED_QUEUE_DROP_CTRL[4][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x796c` construct: FC_Q_EGR_DROP_THR[5][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7970` construct: FC_Q_EGR_DROP_THR[5][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x7974` construct: FC_Q_EGR_DROP_THR[5][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7978` construct: FC_Q_EGR_DROP_THR[5][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a44` construct: SWRED_QUEUE_DROP_CTRL[5][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a48` construct: SWRED_QUEUE_DROP_CTRL[5][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a4c` construct: SWRED_QUEUE_DROP_CTRL[5][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x797c` construct: FC_Q_EGR_DROP_THR[6][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7980` construct: FC_Q_EGR_DROP_THR[6][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x7984` construct: FC_Q_EGR_DROP_THR[6][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7988` construct: FC_Q_EGR_DROP_THR[6][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a50` construct: SWRED_QUEUE_DROP_CTRL[6][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a54` construct: SWRED_QUEUE_DROP_CTRL[6][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a58` construct: SWRED_QUEUE_DROP_CTRL[6][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x798c` construct: FC_Q_EGR_DROP_THR[7][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7990` construct: FC_Q_EGR_DROP_THR[7][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x7994` construct: FC_Q_EGR_DROP_THR[7][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x7998` construct: FC_Q_EGR_DROP_THR[7][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a5c` construct: SWRED_QUEUE_DROP_CTRL[7][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a60` construct: SWRED_QUEUE_DROP_CTRL[7][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a64` construct: SWRED_QUEUE_DROP_CTRL[7][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x799c` construct: FC_Q_EGR_DROP_THR[8][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x79a0` construct: FC_Q_EGR_DROP_THR[8][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x79a4` construct: FC_Q_EGR_DROP_THR[8][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x79a8` construct: FC_Q_EGR_DROP_THR[8][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a68` construct: SWRED_QUEUE_DROP_CTRL[8][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a6c` construct: SWRED_QUEUE_DROP_CTRL[8][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a70` construct: SWRED_QUEUE_DROP_CTRL[8][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x79ac` construct: FC_Q_EGR_DROP_THR[9][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x79b0` construct: FC_Q_EGR_DROP_THR[9][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x79b4` construct: FC_Q_EGR_DROP_THR[9][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x79b8` construct: FC_Q_EGR_DROP_THR[9][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a74` construct: SWRED_QUEUE_DROP_CTRL[9][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a78` construct: SWRED_QUEUE_DROP_CTRL[9][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a7c` construct: SWRED_QUEUE_DROP_CTRL[9][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x79bc` construct: FC_Q_EGR_DROP_THR[10][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x79c0` construct: FC_Q_EGR_DROP_THR[10][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x79c4` construct: FC_Q_EGR_DROP_THR[10][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x79c8` construct: FC_Q_EGR_DROP_THR[10][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a80` construct: SWRED_QUEUE_DROP_CTRL[10][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a84` construct: SWRED_QUEUE_DROP_CTRL[10][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a88` construct: SWRED_QUEUE_DROP_CTRL[10][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x79cc` construct: FC_Q_EGR_DROP_THR[11][0].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x79d0` construct: FC_Q_EGR_DROP_THR[11][1].ON +1 | perf | 0x340024 -> 0x11800f0 | perf |
| `0x79d4` construct: FC_Q_EGR_DROP_THR[11][2].ON +1 | perf | 0x340024 -> 0x4e0044 | perf |
| `0x79d8` construct: FC_Q_EGR_DROP_THR[11][3].ON +1 | perf | 0x340024 -> 0x640044 | perf |
| `0x7a8c` construct: SWRED_QUEUE_DROP_CTRL[11][0].RATE +2 | perf | 0x0 -> 0x7f071067 | perf |
| `0x7a90` construct: SWRED_QUEUE_DROP_CTRL[11][1].RATE +2 | perf | 0x0 -> 0x7f04e044 | perf |
| `0x7a94` construct: SWRED_QUEUE_DROP_CTRL[11][2].RATE +2 | perf | 0x0 -> 0x7f02b021 | perf |
| `0x7dc0` construct: FC_CPU_Q_EGR_DROP_THR[0].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[0].EN | cpu | 0x0 -> 0x1 | cpu |
| `0x7dc4` construct: FC_CPU_Q_EGR_DROP_THR[1].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[1].EN | cpu | 0x0 -> 0x2 | cpu |
| `0x7dc8` construct: FC_CPU_Q_EGR_DROP_THR[2].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[2].EN | cpu | 0x0 -> 0x4 | cpu |
| `0x7dcc` construct: FC_CPU_Q_EGR_DROP_THR[3].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[3].EN | cpu | 0x0 -> 0x8 | cpu |
| `0x7dd0` construct: FC_CPU_Q_EGR_DROP_THR[4].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[4].EN | cpu | 0x0 -> 0x10 | cpu |
| `0x7dd4` construct: FC_CPU_Q_EGR_DROP_THR[5].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[5].EN | cpu | 0x0 -> 0x20 | cpu |
| `0x7dd8` construct: FC_CPU_Q_EGR_DROP_THR[6].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[6].EN | cpu | 0x0 -> 0x40 | cpu |
| `0x7ddc` construct: FC_CPU_Q_EGR_DROP_THR[7].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[7].EN | cpu | 0x0 -> 0x80 | cpu |
| `0x7de0` construct: FC_CPU_Q_EGR_DROP_THR[8].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[8].EN | cpu | 0x0 -> 0x100 | cpu |
| `0x7de4` construct: FC_CPU_Q_EGR_DROP_THR[9].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[9].EN | cpu | 0x0 -> 0x200 | cpu |
| `0x7de8` construct: FC_CPU_Q_EGR_DROP_THR[10].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[10].EN | cpu | 0x0 -> 0x400 | cpu |
| `0x7dec` construct: FC_CPU_Q_EGR_DROP_THR[11].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[11].EN | cpu | 0x0 -> 0x800 | cpu |
| `0x7df0` construct: FC_CPU_Q_EGR_DROP_THR[12].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[12].EN | cpu | 0x0 -> 0x1000 | cpu |
| `0x7df4` construct: FC_CPU_Q_EGR_DROP_THR[13].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[13].EN | cpu | 0x0 -> 0x2000 | cpu |
| `0x7df8` construct: FC_CPU_Q_EGR_DROP_THR[14].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[14].EN | cpu | 0x0 -> 0x4000 | cpu |
| `0x7dfc` construct: FC_CPU_Q_EGR_DROP_THR[15].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[15].EN | cpu | 0x0 -> 0x8000 | cpu |
| `0x7e00` construct: FC_CPU_Q_EGR_DROP_THR[16].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[16].EN | cpu | 0x0 -> 0x10000 | cpu |
| `0x7e04` construct: FC_CPU_Q_EGR_DROP_THR[17].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[17].EN | cpu | 0x0 -> 0x20000 | cpu |
| `0x7e08` construct: FC_CPU_Q_EGR_DROP_THR[18].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[18].EN | cpu | 0x0 -> 0x40000 | cpu |
| `0x7e0c` construct: FC_CPU_Q_EGR_DROP_THR[19].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[19].EN | cpu | 0x0 -> 0x80000 | cpu |
| `0x7e10` construct: FC_CPU_Q_EGR_DROP_THR[20].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[20].EN | cpu | 0x0 -> 0x100000 | cpu |
| `0x7e14` construct: FC_CPU_Q_EGR_DROP_THR[21].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[21].EN | cpu | 0x0 -> 0x200000 | cpu |
| `0x7e18` construct: FC_CPU_Q_EGR_DROP_THR[22].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[22].EN | cpu | 0x0 -> 0x400000 | cpu |
| `0x7e1c` construct: FC_CPU_Q_EGR_DROP_THR[23].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[23].EN | cpu | 0x0 -> 0x800000 | cpu |
| `0x7e20` construct: FC_CPU_Q_EGR_DROP_THR[24].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[24].EN | cpu | 0x0 -> 0x1000000 | cpu |
| `0x7e24` construct: FC_CPU_Q_EGR_DROP_THR[25].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[25].EN | cpu | 0x0 -> 0x2000000 | cpu |
| `0x7e28` construct: FC_CPU_Q_EGR_DROP_THR[26].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[26].EN | cpu | 0x0 -> 0x4000000 | cpu |
| `0x7e2c` construct: FC_CPU_Q_EGR_DROP_THR[27].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[27].EN | cpu | 0x0 -> 0x8000000 | cpu |
| `0x7e30` construct: FC_CPU_Q_EGR_DROP_THR[28].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[28].EN | cpu | 0x0 -> 0x10000000 | cpu |
| `0x7e34` construct: FC_CPU_Q_EGR_DROP_THR[29].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[29].EN | cpu | 0x0 -> 0x20000000 | cpu |
| `0x7e38` construct: FC_CPU_Q_EGR_DROP_THR[30].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[30].EN | cpu | 0x0 -> 0x40000000 | cpu |
| `0x7e3c` construct: FC_CPU_Q_EGR_DROP_THR[31].ON +1 | cpu | 0x340024 -> 0x4e0044 | cpu |
| `0xc4dc` construct: FC_CPU_Q_EGR_FORCE_DROP_CTRL[31].EN | cpu | 0x0 -> 0x80000000 | cpu |
| `0xd878` construct: FC_GLB_SYS_UTIL_THR.THR | perf | 0x300 -> 0x1 | perf |
| `0xab54` construct: L3_IPMC_ROUTE_CTRL.DMAC_MISMATCH_ACT +3 | policy | 0x100 -> 0x37e | policy |
| `0xab58` construct: L3_IP6MC_ROUTE_CTRL.DMAC_MISMATCH_ACT +5 | policy | 0x2880 -> 0xdb7e | policy |
| `0xa784` construct: ACL_PORT_LOOKUP_CTRL[0].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0xa7a4` construct: ACL_PORT_LOOKUP_CTRL[8].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0xa7c4` construct: ACL_PORT_LOOKUP_CTRL[16].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0xa7d4` construct: ACL_PORT_LOOKUP_CTRL[20].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0xa7e4` construct: ACL_PORT_LOOKUP_CTRL[24].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0xa7e8` construct: ACL_PORT_LOOKUP_CTRL[25].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0xa7ec` construct: ACL_PORT_LOOKUP_CTRL[26].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0xa7f0` construct: ACL_PORT_LOOKUP_CTRL[27].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0xa7f4` construct: ACL_PORT_LOOKUP_CTRL[28].LOOKUP_EN | policy | 0x0 -> 0x1 | policy |
| `0x9f88` construct: TRK_CTRL.LINK_DOWN_AVOID +1 | policy | 0x0 -> 0x50 | policy |
| `0x9f80` construct: TRK_HASH_CTRL.L3_HASH_MSK | policy | 0x3f0 -> 0x3ff0 | policy |
| `0x82d4` construct: VLAN_CTRL.STP_LEAK_EN | policy | 0x20 -> 0x0 | policy |
| `0x83c4` construct: VLAN_PORT_IGR_FLTR[28].IGR_FLTR_ACT | cpu | 0x1000000 -> 0x0 | cpu |
| `0x8348` construct: VLAN_PORT_PB_VLAN[28].OPVID_FMT +1 | cpu | 0x8002 -> 0x0 | cpu |
| `0x8fd8` construct: L2_CTRL.LINK_DOWN_P_INVLD | policy | 0x80 -> 0x0 | policy |
| `0x9048` construct: L2_GLB_STT_PORT_MV_LRN.LRN | policy | 0x1 -> 0x0 | policy |
| `0x901c` construct: L2_STT_PORT_MV_LRN[0].LRN +8 | policy | 0x1f110101 -> 0x0 | policy |
| `0x903c` construct: L2_STT_TRK_MV_LRN[0].LRN +31 | policy | 0xffffffff -> 0x0 | policy |
| `0x9040` construct: L2_STT_TRK_MV_LRN[32].LRN +31 | policy | 0xffffffff -> 0x0 | policy |
| `0xeb00` construct: L2_NTFY_CTRL.LD_FLUSH_NTFY_EN +1 | policy | 0x0 -> 0x21000 | policy |
| `0x9060` construct: L2_PORT_DABLK_CTRL[28].EN | cpu | 0x10000000 -> 0x0 | cpu |
| `0x905c` construct: L2_PORT_SABLK_CTRL[28].EN | cpu | 0x10000000 -> 0x0 | cpu |
| `0xab50` construct: L3_IP6UC_ROUTE_CTRL.DMAC_MISMATCH_ACT | policy | 0x180 -> 0x0 | policy |
| `0xab44` construct: L3_IP_ROUTE_CTRL.IP_HDR_ERR_ACT +1 | policy | 0x0 -> 0xf | policy |
| `0xd724` construct: PARSER_CTRL.PPPOE_PARSE_EN | policy | 0x0 -> 0x2 | policy |
| `0x000c` construct: RST_GLB_CTRL_0.CHIP_RST_EN +1 | policy | 0x0 -> 0x180 | policy |
| `0xc70c` dal: MAC_L2_CPU_PORT_CTRL.CPU_PORT | cpu | 0x0 -> 0x0 | no-op |
| `0x9064` dal: L2_UNKN_UC_FLD_PMSK.PORTMASK | cpu | 0x1fffffff -> 0x1f110101 | cpu |
| `0x9068` dal: L2_BC_FLD_PMSK.PORTMASK | cpu | 0x1fffffff -> 0x1f110101 | cpu |
| `0xca1c` dal: MAC_FORCE_MODE_CTRL[0].EEE_EN_100M +5 | perf | 0x0 -> 0x0 | no-op |
| `0x3274` dal: EEE_CTRL[0].EEE_TX_EN +1 | perf | 0x3 -> 0x0 | perf |
| `0xca3c` dal: MAC_FORCE_MODE_CTRL[8].EEE_EN_100M +5 | perf | 0x0 -> 0x0 | no-op |
| `0x3474` dal: EEE_CTRL[8].EEE_TX_EN +1 | perf | 0x3 -> 0x0 | perf |
| `0xca5c` dal: MAC_FORCE_MODE_CTRL[16].EEE_EN_100M +5 | perf | 0x0 -> 0x0 | no-op |
| `0x3674` dal: EEE_CTRL[16].EEE_TX_EN +1 | perf | 0x3 -> 0x0 | perf |
| `0xca6c` dal: MAC_FORCE_MODE_CTRL[20].EEE_EN_100M +5 | perf | 0x0 -> 0x0 | no-op |
| `0x3774` dal: EEE_CTRL[20].EEE_TX_EN +1 | perf | 0x3 -> 0x0 | perf |
| `0xca7c` dal: MAC_FORCE_MODE_CTRL[24].EEE_EN_100M +5 | perf | 0x0 -> 0x0 | no-op |
| `0x3874` dal: EEE_CTRL[24].EEE_TX_EN +1 | perf | 0x3 -> 0x0 | perf |
| `0xca80` dal: MAC_FORCE_MODE_CTRL[25].EEE_EN_100M +5 | perf | 0x0 -> 0x0 | no-op |
| `0x38b4` dal: EEE_CTRL[25].EEE_TX_EN +1 | perf | 0x3 -> 0x0 | perf |
| `0xca84` dal: MAC_FORCE_MODE_CTRL[26].EEE_EN_100M +5 | perf | 0x0 -> 0x0 | no-op |
| `0x38f4` dal: EEE_CTRL[26].EEE_TX_EN +1 | perf | 0x3 -> 0x0 | perf |
| `0xca88` dal: MAC_FORCE_MODE_CTRL[27].EEE_EN_100M +5 | perf | 0x0 -> 0x0 | no-op |
| `0x3934` dal: EEE_CTRL[27].EEE_TX_EN +1 | perf | 0x3 -> 0x0 | perf |
| `0xa498` dal: STK_GLB_CTRL.STK_PORT_SEL | policy | 0x0 -> 0x0 | no-op |
| `0xa370` dal: DMY_REG0_QUEUE.FORCE_ALL_PORT_SECOND_EGR_DROP | policy | 0x0 -> 0x0 | no-op |
| `0xa498` dal: STK_GLB_CTRL.MY_DEV_ID +2 | policy | 0x0 -> 0x0 | no-op |
| `0xa4a4` dal: STK_NON_UNICAST_BLOCK_CTRL[0].NON_UNICAST_BLOCK_PM +7 | policy | 0x0 -> 0x0 | no-op |
| `0xa4a8` dal: STK_NON_UNICAST_BLOCK_CTRL[8].NON_UNICAST_BLOCK_PM +7 | policy | 0x0 -> 0x0 | no-op |

cpu: 108, no-op: 38, perf: 468, policy: 26
