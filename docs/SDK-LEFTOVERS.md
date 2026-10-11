# Realtek SDK leftovers (RTL930x)

Facts only. Source: `scripts/sdk_leftovers_scan.py` over the GPL SDK trees (rtk-xgs1210 3.7.0, DMS-1250 3.8.0, olliver 3.5.0), stock ST1008F and managed ST5008F v2 extracts. Output `tmp/sdk_leftovers/scan.json`. Issue: #74.

| Item | Where | What it is | Use on this board | Risk |
|---|---|---|---|---|
| ASIC drop-reason counters | `0xBB00B5B8 + 4*n`, 85 × 16 bit; names: `hal_getDbgCntr`, `src/hal/mac/mac_debug.c` (82 named reasons) | per-reason drop counts: route lookup miss, TTL, MTU, L2 hash full, egress queue, … | explain L3 traps / drops (#59, #65); unused by OpenWrt | read-only (check clear-on-read before polling) |
| SerDes test tools | `src/dal/longan/dal_longan_sds.c` | eye monitor (page 0x2E), PRBS9/PRBS31 generator/checker, TX eye params, loopback, symbol/block error counters | link quality on cages (#25, #48-style margins); OpenWrt has only error counters | test modes disrupt the link while active |
| Packet-buffer auto-recover | `src/dal/longan/dal_longan_waFunc.c` | HW error flags + SW queue-reset workaround; compiled into stock `rtk.ko` | OpenWrt lacks it: candidate robustness fix | writes; port only with the SDK's exact sequence |
| Thermal comparators | thermal meter regs | high/low threshold interrupts, max/min temperature latch; SDK unused | over-temperature handling (#13) | low |
| U-Boot test commands (compiled out of stock) | `board/Realtek/rtl9300/board_cmd.c` | DRAM, GDMA, flash, concurrency, frequency-step tests | port to our U-Boot (DRAM/GDMA tests: #48, #62) | DRAM/flash tests can write; keep flash tests read-only |
| DRAM bring-up material | olliver `ddr_cli_tools` | 2013 Realtek DRAM deck + pre-calibration images (RTL838x/8390 era) | background for DDR work (#48/#49/#56) | none |
| ES-only code paths | `CHIP_TYPE_1` branches | engineering-sample workarounds | none apply (production rev B) | — |
| Dead code | stock `rtk.ko`; `ext_9300.cli` | drivers for unfitted PHYs (8218/8295/8226/8214); extra diag CLI not in stock `diag` | none | — |
| Stray material | SDK trees | internal Realtek URLs, developer paths, an 8051 source (`rtl8213_func.c`) | none | — |

- Security-relevant findings from the scan (access checks in SDK kernel modules, credential handling in the managed firmware) are deliberately not recorded here; handling is an owner decision.
