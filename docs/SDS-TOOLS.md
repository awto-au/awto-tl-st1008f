# SerDes test tools (RTL930x, #74)

Port of the Realtek SDK SerDes test functions into our U-Boot as `rtk sds` (syntax: [RTK-COMMANDS.md](RTK-COMMANDS.md#serdes-test-tools-rtk-sds-74)). Code `uboot-port/board/tplink/tl-st1008f/rtk_sdstest.c`; test `./dev.py sds-tools-test`.

- Source: SDK 3.7.0 (rtk-xgs1210) `src/dal/longan/dal_longan_sds.c`: `symErr_get/clear`, `linkSts_get`, `10gRxIdle_get`, `testMode_set`, `eyeParam_get/set`, `eyeMonitor_start`. SDK 3.8.0 (rtk-dms1250) adds `loopback_get/set`. Stock `rtk.ko` exports the same `dal_longan_sds_*` symbols.
- SDK has no PRBS error-counter read for longan (`testModeCnt_get` exists only for cypress/mango) and no eye decode (`eyeMonitor_start` only prints raw words). Both taken from mango (RTL931x), which uses the same page-5 PCS and eye-word format; checked on hardware (below).
- Every register is SerDes indirect access (`0x03b0`/`0x03b4`, [rtk_sds.c](../uboot-port/board/tplink/tl-st1008f/rtk_sds.c)). Logical id: SerDes 3 pages 0-3 live in SerDes 10. Cage N = SerDes N+1.
- Needs `rtk network on` first (refused otherwise).

## Registers

Page 5 = IEEE MMD 3 registers 32+ (10GBASE-R PCS):

- **5/0 bit 12**: 3.32.12 PCS receive link, current; read twice.
- **5/1**: 3.33. Bit 15 = latched block lock and bit 14 = latched high BER (both latch low); bits 13:8 = BER count; bits 7:0 = errored blocks. Clear on read.
- **5/0xa**: 3.42 test-pattern control. Bits 5:4 = PRBS31 (`3` = gen + check); bits 7:6 = PRBS9; bit 3 + bit 1 = square wave.
- **5/0xb**: 3.43 test-pattern error counter. 16 bits, clear on read, saturates at 0xffff.

Other registers:

- **4/1 bit 2**: 3.1.2 receive link, latched low. 0 = the link dropped since the last read.
- **6/0, 6/0xe, 6/0xf**: PRBS datapath set-up (SDK writes `6/0[12:8]=2`, `[14:13]=3`, `6/0xe[8:0]=2`, `6/0xf=2`). Values after `rtk network on`: `0x0000`, `0x015a`, `0x5a5a`.
- **6/1 bit 2**: `FP_TGR1_CFG_AFE_LPK` near-end analog loopback (10GR). Stock CMU check uses it too (`rtk_net.c` `clk_ready`).
- **0/0 bit 4**: `SP_CFG_DIG_LPK` near-end digital loopback (1G modes).
- **6/2 bit 12**: PCS FSM reset (pulse).
- **0x2e/0x15 bit 4**: RX reset (pulse; SDK `rx_rst`).
- **0x1f/2**: debug-out select on the pair's even SerDes. `0x35` = 0x1f/0x14 bit 0/1 RX idle (even/odd), bit 4/5 CMU ready. `0x37` = eye-monitor word.
- **1/24 [2:0], 1/2, 1/3 [15:8]** (1000BASE-X): symbol-error channel select, count low 16 bits, count high 8 bits. Not cleared by reading; `errcnt <cage> clear` writes 0.
- **1/29, 1/30 [8:0]** (1000BASE-X): link status and latched link status.
- **TX eye page** = 0x2f (10GR), 0x25 (SGMII/1000BX/100BX), 0x29 (2500BX/HISGMII). Fields: pre 1[15:11], pre_en 7[0], main 7[8:4], post 6[4:0], post_en 7[3], impedance 0x18[15:12].

Eye monitor (page 0x2e):

- Scan enable 8[14] (toggled 1-0-1), ck_sel 8[15]=0, rsel 7[15:14]=1, bias_adj 0xa[13:12]=1, pi_adj 3[15:14]=1.
- PI (x 0-63): 0x1a[9:6] = {9,c,6,3}[x/16]; 0x1b = thermometer code `0xffff>>(x%16)` (even x/16) or `0xffff0000>>(x%16)` (odd).
- Vref (y 0-63): 0x1a[5:0].
- Sample: 0x1f/2 = 0x37, pulse 0x2e/0[0], read 0x1f/0x14.
- Word: bits 15:14 = 3 when valid. Bits 13:0 = 7 samples of 2 bits: bit 1 = mismatch at (x, Vref), bit 0 = half (1 lower, 0 upper). Map rows: upper 64+y, lower 63-y (mango `eyeMonInfo_update`).

## Sequences

- **prbs**:
  - Save 5/0xa, 6/0, 6/0xe, 6/0xf.
  - Optional near loopback.
  - SDK `testPrbs9/31_set`, 10 ms settle, one discarded read of 5/0xb.
  - Sum a 5/0xb read every 100 ms; poll Ctrl-C every 10 ms.
  - Write the saved values back, loopback off or FSM + RX reset, clear the symbol-error counters.
- **prbs off**: SDK `testDis_set`, except 6/0xe and 6/0xf go back to the values above (the SDK writes 0 there).
- **loopback near**:
  - Save 6/1 and 0/0, set 6/1[2] and 0/0[4], FSM reset, RX reset.
  - The SDK instead re-runs `mode_set`.
  - `off` restores the saved bits and resets again.
- **loopback far**: refused. Neither SDK version nor stock `rtk.ko` has a remote-loopback control for longan.
- **eye**:
  - Save page-0x2e regs 0/3/7/8/0xa/0x1a/0x1b and 0x1f/2.
  - Scan 64 x 64 x frames.
  - Restore the saved registers and report PCS link before and after.
  - One settle read after each PI step: without it, row y=0 read as mismatches at every x (stale first sample after Vref 63 -> 0).
  - Re-read up to 8x until the word is valid: the first read of a scan returned 0.
- **Refusals**: PRBS and loopback on a cage whose MAC or PCS link is up, unless `force`. PRBS only in 10GBASE-R.

## Measured (2026-10-12, our U-Boot after `rtk network on`, CPU 1 GHz)

Setup:

- Cage 1: SFP-10GSR-85, fibre to the house switch, 10GBASE-R, link up.
- Cages 2/6/8: SFP-10GSR-85, no fibre.
- Cages 3/7: GLC-T cabled to each other, SGMII.
- Cage 4: GLC-SX-MM. Cage 5: PTB3370553CN0CS1. Both 1000BASE-X.
- Run: `./dev.py sds-tools-test --label 20261012-final`, 6/6 pass; results `tmp/sds_tools/20261012-final.json`.

PRBS on cages 2, 6, 8 (10GR, near loopback):

- PRBS31, 1 s: **0 errors in 10.31 Gbit** on each cage (BER < 3e-10 at 95 %).
- PRBS9, 1 s: 0 errors on each cage.
- Checker self-test (PRBS31 sent, PRBS9 checked): 0xffff every sample (3/3 saturated). The counter is live.
- First read after pattern start: 0x013c-0x0154 (lock transient), discarded.
- Without loopback (dark RX): 0 errors. An idle input does not count, so a dark-cage 0 proves nothing.
- Registers (5/0xa, 6/0, 6/1, 6/0xe, 6/0xf) identical before and after every run and after Ctrl-C.

Eye, cage 1 (link up, 16 frames, 5.6 s):

- **Centre clean width 17/64 PI steps.** Crossings centred at x ≈ 17 and x ≈ 48, so 1 UI ≈ 31 steps and the width ≈ 0.55 UI.
- **SDK height 101/128 rows** (at x 61). SDK width 64/64: the rows at 64 ± 10 are clean everywhere, so that metric does not separate this eye.
- One frame gives centre width 18-22.
- Link not disturbed: PCS up -> up, latched link 1, blk_err 0, ber 0, block lock latched 1 after the scan.
- Upper half: mismatches across all x from about row 100 up (Vref beyond the signal). Lower half: mismatches only in the crossing columns. Row 63/64 mismatches appear only in the crossing columns.
- Map: `tmp/sds_tools/20261012-final-eye-cage1.txt`.

Eye, dark cages 2/6/8: all clean (128/64). The command flags `RX idle (no signal): map below is not an eye`.

Status and counters after `rtk network on`:

- 10GR cages read `latched 0` on the first read (link events during bring-up), then 1 on cage 1.
- 1G counters: cage 3 = 37-42, cage 7 = 37-40 (GLC-T pair, SGMII), cage 4 = 0, cage 5 = 16777215 (saturated: RX signal, no link).

TX eye after `rtk network on`:

- 10GR cages: pre 0, main 12, post 0.
- 1G cages: main 16.
- Impedance field: 8 on cages 1/3/5/7, 0 on 2/4/6/8.
- Neither the SDK default table (`sds_cfg_rtl9303_80G`) nor the ST5008F per-cage overrides: [MANAGED-FEATURES.md](MANAGED-FEATURES.md) "Board secrets" (#25).

Unexplained event (2026-10-12, first full test run): cage 1's latched receive link (4/1.2) read 0 once in a ~12 s window covering PRBS, loopback, Ctrl-C and txeye on other cages. Each step re-tested alone (eye, PRBS, loopback on cages 2/6, txeye, Ctrl-C): no drop. The test now clears the latch right before the eye scan; later runs show no drop. Far-end blip possible, not proven.

Found while porting: `rtk sdsreg get <x> <sds> <page>` (one argument short) dereferenced a NULL argv and crashed our U-Boot (TLB load exception); now prints the stock parameter error (`rtk_stock.c`).

## Not done

- Far-end loopback (no register known). Square-wave test pattern (SDK has it; no use found).
- Linux: a debugfs equivalent for the 7.3 port (#74).

## RX calibration with no input signal (Linux, #125)

- `pcs-rtl-otto.c` post_config calibrates RX (vth, tap0) once per mode change. With the partner dark, the old code calibrated anyway: the values end at the limits and the port never links once the partner lights.
- Measured sw2, 2026-10-14T21:07-22:36+11:00, DAC lan3 <-> lan4 (SerDes 4/5), both out of the bridge, `./dev.py sds-cal-test` (debug via DYNAMIC_DEBUG):
  - lan3 up first (no signal): SerDes 4 `vth_p = 7, vth_n = 7`, `tap0 even coefficient = 31`; lan3 never linked within 10 s of lan4 up, 4/4.
  - lan4 calibrated with lan3's signal: `vth 1/1`, `tap0 15`, link 0.07 s after config.
  - lan4 up first: both linked, 3/3 (SerDes 5 recovers; not explained).
- Fix `openwrt/patches/300-34` (SDK behaviour: skip when idle): 10GBASE-R with no signal at config -> calibration deferred; a delayed work checks the RX-idle bit once a second (one 10 ms check) and calibrates when a signal appears. 2026-10-14T22:43-22:45: lan3 first 2/2 linked (SerDes 4 calibrated to vth 2/2 0.5 s after lan4 up), lan4 first 1/1; boot-link-check 6/6, check-log clean.
- At boot it also catches the natural case: SerDes 8 (lan7) deferred at 20.7 s, calibrated at 22.6 s when lan8 lit.
