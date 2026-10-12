# TL-ST1008F DRAM: theory vs measured

Facts only. How to run the measurements: [CLOCKS-OPS.md](CLOCKS-OPS.md). Registers and clock tree: [CLOCKS.md](CLOCKS.md).

## Part and configuration

- One DDR3 die, x16, 4 Gbit = 512 MiB (DCR `21421003`: 8 banks, 15 row + 10 col bits).
- Part (board photo, 2026-10-11): **Zentel A3T4GF40BBF-HP**, DDR3-1866 (933 MHz, CL13), 256M x16, 96-ball FBGA. OpenWrt's TL-ST1008F v2 commit names a Samsung K4B4G1646E-BYMA: other boards or wrong. Datasheet: `sources/README.md`.
- Run by the stock SPL at 600 MHz (DDR3-1200): DRAM CL 9 (controller CL 10), CWL 7, WR 10, tRCD/tRP 15 ns, tRAS 38.3 ns, tRFC 270 ns, tREFI 3.84 µs (2x refresh, the >85 °C rate). MR0-MR3: CLOCKS.md register map.
- What the SoC can identify (#57): DCR `0xb8001004` gives DDR generation, banks, row/col bits, bus width → die size (`clocks` prints it; `clocks set mem` refuses anything but one x16 die of 512 Mbit-8 Gbit). Vendor, part and speed grade are not readable: DDR3 MPR (MR3) returns only a fixed training pattern, soldered DRAM has no SPD, and ID mode-register reads exist only on LPDDR/DDR4+. They come from the board (photo, BOM, DT).
- Bins: 300-650 = SDK/stock SPL rows, part-agnostic (JEDEC DDR3-1333+ timings); 675-800 = generated from the Zentel datasheet minima (`scripts/clock_calc.py ddr-bin`, CLOCKS.md), tRFC by die density (#57).
- Only the CPU uses DRAM for its own work. Switching uses the on-chip packet buffer; DRAM speed does not change forwarding.

## Theory (from the live timings)

| Quantity | DDR3-1200 (stock) | DDR3-1300 | Chip rating DDR3-1866 |
|---|---|---|---|
| Peak bandwidth, x16 | 2400 MB/s | 2600 MB/s | 3732 MB/s |
| 32 B cache line on the bus | 8 clk = 13.3 ns | 12.3 ns | 8.6 ns |
| Read latency at the DRAM, row hit / closed / conflict | 30 / 45 / 60 ns | ≈ 28 / 43 / 58 ns | — |
| Refresh busy (tRFC / tREFI) | 7.0 % (3.5 % at the normal 7.8 µs) | same | — |

## Measured (U-Boot `bench`, 2026-10-11, heatsink off)

| Test | 800 / DDR 600 | 1000 / DDR 600 | 1000 / DDR 650 | 1000 / DDR 600 + MCR prefetch | % of 2400 MB/s peak (best) |
|---|---|---|---|---|---|
| Random cached miss latency | 120 ns | 109 ns | 107 ns | 109 ns | 2.5-3.6x the DRAM's 30-45 ns |
| Random uncached word latency | 116 ns | 106 ns | 104 ns | 106 ns | |
| Sequential read (plain loop) | 291.4 | 336.3 | 342.7 | **433.0** | 18 % |
| Sequential read, `pref 0` 4 lines ahead | 763.3 | **983.5** | 977.2 | 732.7 | 41 % |
| memset (write-allocate) | 237.6 | 237.7 | 237.0 | **400.1** | 17 % |
| Store with `pref 30` (no fill) | 1286.6 | **1565.7** | 1562.4 | 1566.5 | **65 %** |
| Uncached store | 363.5 | 432.6 | 449.1 | 432.6 | 19 % |
| Uncached read | 53.5 | 60.7 | 63.0 | 60.7 | 2.6 % |
| memcpy (U-Boot generic C) | 158.2 | 162.4 | 162.4 | 156.3 | |

(MB/s unless marked.)

## What the gap is

- **Latency, not bandwidth.** A plain loop has one 32 B miss outstanding: 32 B / 120 ns = 267 MB/s (measured 291); at 109 ns = 294 MB/s. The DRAM bus is idle most of the time.
- **Most of the miss time is outside the DRAM chip.** The DRAM needs 30-45 ns; a miss costs 109-120 ns. CPU 800 → 1000 MHz cuts it 9 %; DDR 600 → 650 cuts it ≤ 2 %. The extra ~65-80 ns sits in the CPU-side bus (OCP) / controller path, which runs on the CPU clock.
- **Write-allocate doubles write traffic.** memset reads each line before writing it: 237.6 MB/s. PrepareForStore skips the read: 1286-1566 MB/s, 65 % of peak. So the bus and controller can stream; plain code can't feed them.
- **The controller prefetch** (MCR `ip_ref`/`dp_ref`, off in stock) recovers part of it for plain code: read +26 %, memset +61 % at 800 MHz; +49 % / +68 % combined with 1 GHz. It competes with software prefetch (−9 % / −26 % on the `pref 0` loop).
- **Who sets the MCR prefetch** (checked 2026-10-11, #52): the stock SPL writes MCR with `ip_ref`/`dp_ref` = 0; stock U-Boot and the Realtek SDK Linux never touch MCR (the fields appear only in preloader headers and `soc/rtk_mem_test/memctl_dram.c`, which enables them as write 0 then 1). OpenWrt only reads DCR, so Linux inherits the bootloader's value.
  - Our U-Boot `clocks fast` sets both bits; real power-up via the chain: MCR `20e41e60`, flash OpenWrt rootfs hash = stock-boot hash, 0 SQUASHFS errors (2026-10-11, #52).
  - Kernel patch `openwrt/patches/300-04` sets them at prom init (RTL930x only; 838x/839x/931x MCR layouts not checked). Boot via **stock** U-Boot (MCR left at `20241e60`), 2026-10-11: `RTL930x DRAM controller prefetch on (MCR 20e41e60)` (#53). Applies to OpenWrt main `e5ec5e1` (6.18.55) after 300-01..03 and builds warning-free.
- **DDR clock barely matters**: 600 → 650 changed every test by ≤ 4 %.

## Headroom left (not done)

| Lever | Expected gain | Cost / risk |
|---|---|---|
| Linux `memcpy` uses `pref` (CPU_MIPS32_R2 selects CPU_HAS_PREFETCH; 16 PREF sites in `arch/mips/lib/memcpy.S`); Linux `memset` has none (write-allocate path, helped by MCR prefetch); userspace libc copies: not checked | `memset` up to the `pref 30` figure | kernel `memset.S` change (upstream) |
| tREFI 3.84 → 7.8 µs (normal-temperature refresh) | ≈ 3.5 % of DRAM time; ≈ 0 in practice (access is latency-bound, bus mostly idle) | **decided: 7.09 µs (4608 clk at 650) in `clocks fast`** (owner: fastest settings, 2026-10-11; first decided keep-stock, superseded). DDR3 has no readable temperature (only DDR4/LPDDR do); the SoC sensor peaked at 75 °C under load, heatsink off |
| Tighter timings for a DDR3-1866 part at 600-650 MHz (CL, tRCD, tRP) | a few ns of the 30-45 ns DRAM part only | MRS path exists (675+ bins); no 600/650 tight bin defined |
| Unexplained MCR bits: `ocp0_frq_slower` 9 = 1, `ocp0/1_rbf_f_dis` 5/6 = 1, `sync_ocp0_dram` 0 = 0 | possibly the 65-80 ns bus/controller overhead | unknown semantics (#52) |
| DDR above 650 MHz | ≤ a few % (600 → 650 moved every test ≤ 4 %) | 675-800 implemented (CL 11 / CWL 8 via MRS); 675/700 pass CRC + highmem only after a read-tap shift and hang in `bench` writes, 725 hangs (2026-10-11); 650 stays (CLOCKS.md procedure (b), #48, #49) |

## Above 650 MHz: what init does per speed and `clocks set mem` skips (#48, #49, #56)

Code reading, 2026-10-13. Sources: `SDK` = GPL SDK 4.0.2 `loader/u-boot-2011.12/arch/otto40/plr/src/` ([SDK-SOURCES.md](SDK-SOURCES.md)); `BIS` = `github.com/jameywine/bismarck-preloader` @ `2f127fb4` (Realtek RTL9603C-vd / Apollo Pro / Phoebus preloaders, same DDR controller + PHY register map); `[BIN]` = stock SPL disassembly.

### Does Realtek ever run this controller above 650?

- RTL9300 SDK: no. MEM PLL rows stop at 600 (`platform/9300/cg/cg_mem.c:29-49`), PHY preset and DTR rows at 650 (`boot0412/memctl.c:1445-1556`), demo project 600 (`project/9300_nor_demo/parameters.c:53`).
- RTL9310 SDK: DDR3 800 (`project/9310_nor_demo/parameters.c:135`, `jedec_ddr3_1600.h` CL 11 / CWL 8). Different PHY (DPI): full training in `platform/9310/dram/memcntlr_cali.c:1921` = VREF, write leveling, CK/CS/DQS/DQ PI scans, DQS-enable scan, RX/TX DQ tap scans, RX FIFO/ODT maps. Not portable, shows the step list.
- RTL9603C-vd (BIS): **DDR3 700/750/800 rows on the RTL9300 register map** (MEM PLL `0xb8000234`, DIDER `1050`, DACCR `1500`, DACDQ `1510/1550`, DCSDCR `15b0`, DWDQSOR `15c4`, DWDQOR `15d0`). Its PLL formula is `25 x (n_code + 3) / 2` (RTL9300: `+ 2`): PLL values are candidates, not facts.

### Stock SPL PHY preset per speed [BIN] `0x9fc02664` (decoded 2026-10-13)

| Register | 600 / 625 | 650 (and 400/450) | 550/575 |
|---|---|---|---|
| DCSDCR0 `15b0` (CKE/CS/ODT/RAS/CAS/WE taps) | `08888888` | `0fffffff` | `0fffffff` |
| DCSDCR1 `15b4` (DQS1/DQS0 out taps, BA) | `12120888` | `03000fff` | `0a0f0fff` |
| DCSDCR2/3 (A0-A15 taps) | `88888888` | `ffffffff` | `ffffffff` |
| DWDQSOR `15c4` / DCDQMR `1590` | `110f0000` / `0d0c0000` | same | `1f1a0000` / `00000000` |

- Every speed: DIDER `9f9f0000` (DQS read-enable tap 31 + half clock, never trained), DACCR `80000030`, DWDMOR 0.
- SPL 650 = SDK source 650. SPL 600 DCSDCR1 `12120888` ≠ SDK source `0c0d0888` (the only binary/source difference).
- Our 650-800 bins keep the 600 preset. At 650 Realtek moves command/address taps 8 → 15 and the write-DQS taps 18 → 0/3.

### Speed-dependent steps: SDK cold init vs our runtime change

| Step | SDK / BIS cold init | `clocks set mem` |
|---|---|---|
| MEM PLL row | per-speed row ≤ 600; BIS 600-800: MPCR1 `cco_band` 3, MPCR2 `2ea23980` | 600 row for 625-800 |
| PHY preset (DCSDCR, DWDQSOR, DCDQMR) | per speed (table above) | 600 values |
| Read DQ taps (DACDQ_IDX_RR/FR 12:8) | trained (`DDR_Calibration`, `memctl_cali_dram.c:851`) | kept; `dqshift` by hand |
| Write DQ taps (DACDQ_IDX_RR 28:24 `phase_shift_90`, DWDQOR0-3) | trained in the same scan (`:216-260`, `:698-786`) | kept at the 600 result |
| DQS group read tap (DACCR 20:16 / 12:8) | BIS auto-K loop (`memctl_cali_dram.c:552-584`) | kept (0) |
| DRAM DLL | MR1 DLL off → MR1 on → MR0 DLL reset → MR2 → MR3 → PHY FIFO reset (`boot0412/memctl.c:2101-2144`) | MR2, MR0 + DLL reset only when CL changes (675+); 625-662: no DLL reset |
| ZQ | controller pad ZQ (`DDZQPCR 1094`), DRAM ZQCL (`D3ZQCCR` bit 31), periodic ZQCS (`memctl.c:1917-1973, 2147-2167`) | none (ZQCS stays on) |
| Frequency transition | cold: no DRAM content | refresh off, MEM clock gated (clk_oe 0) ~405 µs with CKE high, no self-refresh (`nosr`; PM_MODE 2 hangs) |
| DTR2 bits 3:0 | BIS 700-800: `0xB` "EN_TCC_DIFF, TAC = PHY - CWL" (`ext/9603cvd/autok/memctl.c:1020-1032`); RTL9300 header: `no_use` | 0 |
| Write leveling | none on RTL9300; BIS has one for this PHY (DMCR bit 25, CK/DQS PI sweep, result in DCFDRR/DCFDFR `1594-15a0`, `memctl.c:2417-2510`) | none |

- Read/write tap selection (SDK, `memctl_cali_dram.c:216-249`): window starting at tap 0 → read tap = len - 12; else window centre. Write tap = start + len/3 (start 0) or centre. BIS scales the 12 with frequency: holdtime = ((10^6 / MHz / 2 - 150) / 2) / 20 → 15 at 650, 14 at 700, 11 at 800 = **≈ 20 ps per tap**, 32 taps ≈ 640 ps.
- Live 600 DQ0: `081b0f00` = write tap 8, read window 0-26, read tap 15 (len 27 - 12). The window starts at tap 0 on every DQ: the true left edge lies below the tap range.
- The SDK also has a hardware read-tap tracker on this PHY: per-DQ `dqn_r_ac_en` (DACDQ bit 31) with min/max = cur ± 10 and a silence pattern at DACSPAR; the RTL839x preloader enables it (`arch/mips/cpu/mips34kc/rtl839x/.../plr_memctl_cali_dram.c:672-755`). Off on this board (bit 31 = 0).
- MEM PLL post-PI phases (MPCR0 CK/CLKM/DQS0/DQS1, MPCR1 DQ0-7/DQ8-15, 1/32-clock steps) scale with the clock; the DCSDCR/DACDQ taps are fixed-time. SDK runtime setters exist: `cg_mem_pll_config_dqs_pi` / `cg_mem_pll_config_dq_pi` (`cg_mem.c:85-108`, clk_oe off, 5 µs, on, 200 µs). BIS: a PI ≥ 16 needs its MPCR3 oesync bit (bit 5 DQ0-7, 4 DQ8-15, 3 DQS1, 2 DQS0, 1 CLKM, 0 CK; `memctl.c:2213-2265`).

### Settle steps after the change: `ddr_sram.S` vs JEDEC DDR3 / SDK (owner question)

| Step | JEDEC / SDK | Ours |
|---|---|---|
| Clock stop | only in self-refresh or precharge power-down | clock gated with CKE high, banks as left: **outside JEDEC** |
| Refresh | ≤ 8 postponed (≈ 70 µs) | off ≈ 1.8 ms (≈ 230 tREFI); within the 64 ms retention, outside the postpone rule |
| DLL reset (MR0 A8) + tDLLK 512 clk | every frequency change | 675+ only (with the CL change), 1 µs wait = ≥ 512 clk at ≥ 512 MHz: OK when done; **625-662: skipped** |
| MR1 DLL off/on | SDK does it before MR0 | skipped (MR1 value unchanged) |
| ZQCL, tZQoper 256 clk | SDK at init; JEDEC does not require it on a frequency change | skipped; periodic ZQCS still on |
| tXSDLL 512 clk before a read | after SR exit | n/a (no SR); 10 µs + 20 µs before the canary: long enough |
| PHY FIFO pointer reset | after PHY changes | done twice: OK |
| Read gate / read DQ / write DQ retrain | `DDR_Calibration` at init | **skipped** (lead 1) |

### Leads tested on sw2 (2026-10-13T10:15-10:45+11:00, one quick test per point: change OK + 16 MiB `crc32` + prompt)

Each config adds to the previous one; points 800 → 725 → down to the first pass.

| Config | 800 | 725 | 700 | 675 |
|---|---|---|---|---|
| (a) `dll`: MR1 DLL off/on, MR0 DLL reset, MR2, MR3, ZQCL every change | fail | fail | fail | fail |
| (b) + SPL 650 PHY preset (DCSDCR0-3) | fail | fail | fail | fail (540 bad) |
| (c) + BIS PLL row (MPCR1 `c00001ef`, MPCR2 `2ea23980`) | hang | hang | hang | hang |
| (d) (a) + per-DQ read-tap retrain (`./dev.py ddr-retrain`) | no window (DQ1/DQ4) | no window | **pass** | **pass** |
| (e) (d) + DQS PI 4 / 8 / 12 (MPCR0 26:22, 31:27) | no window (PI 8) | no window (all three) | — | — |

| (d') (a) + read **and write** retrain (`ddr-retrain --write`; write test = write + read back 1024 words at the new clock in the SRAM routine) | — | no read window (DQ3) | **pass** | — |
| (d') + DQS group read tap (DACCR 20:16 / 12:8) 8 / 16 | — | 750: no read window (8); every bit wrong, data shifted (16) | — | — |

- (d') at 700 (2026-10-13T10:48): read shifts −14…−12, write taps `9 7 9 8 7 9 8 9 10 10 16 9 9 10 10 10` → `10 6 9 8 6 9 8 9 15 13 16 12 13 14 14 14` (DQ8-15 +3…+5, DQ0-7 ±1), write test clean, 16 MiB crc32 pass. Midpoint search 700..800: 750 fail, 725 fail → **700**.
- "no window" = some DQ fails at every read shift −16…+10 from the 600 training (its taps would have to go below 0). DQ1/DQ4 are the earliest to fail, as on sw1.
- Fail = canary bad, reverted cleanly; hang = no prompt after the change (PLL row).
- (d) at 700: read-tap shifts −13 (window −16…−11), taps RR 5-8, FR 0-4. Write taps not retrained: `bench` writes not run (they hung at 675/700 on sw1).
- Not done: refresh kept on through the change (the ~1.8 ms gap), write-tap/DQS-group retrain, PI ≥ 16 (needs the MPCR3 oesync bits).

### Leads for 675-800, ranked

1. **Retrain read + write DQ taps at the target speed.** Port `DDR_Calibration_Full_Scan_Reduce` (`boot0412/memctl_cali_dram.c:566-847`) into the SRAM routine: 8 KiB scratch target, 2-tap steps, 16 x 16 writes + reads per pass. Only DRAM contents in the scratch buffer are lost. Covers the measured read failure (DQ4 late at 675) and the `bench` write hang (write taps still at the 600 result).
2. **SPL 650 PHY preset for 650-800**: DCSDCR0 `0fffffff`, DCSDCR1 `03000fff`, DCSDCR2/3 `ffffffff` (Realtek's only preset above 600). BIS alternatives: DCSDCR1 DQS taps `0d`-`12`, DWDQSOR `1f1f0000`.
3. **DLL reset + ZQCL on every change**: SDK sequence MR1 DLL off, MR1 on, MR0 + DLL reset, MR2, MR3; wait tDLLK (512 clk); ZQCL (D3ZQCCR bit 31, poll); PHY FIFO reset. Cheap; today 625-662 change frequency without any DLL reset.
4. **MEM PLL loop row** (#56): MPCR1 `cco_band` 3 (`c00001ef`), then MPCR2 `2ea23980` (BIS rows 600-800). VCO band is the knob CLOCKS.md listed as missing.
5. **CK / DQS / DQ PI phases** (write side, clock-relative): SDK rows ≠ 600 use CK 8 / CLKM 6 / DQ0-7 12 (`000c807f`, `4000018f`); BIS 700: CK 10 / CLKM 8. Sweep with clk_oe off.
6. DTR2 bits 3:0 = `0xB` with CAS_PHY = CL (BIS 700-800). RTL9300 header calls these bits unused: test only.
7. Hardware read-tap tracking (RTL839x `_memctl_enable_hw_auto_cali`) to follow drift after the change.
8. Frequency change in true self-refresh (JEDEC) instead of `nosr`: BIS reset path uses MPMR0 bit 29 + 800 µs; our PM_MODE = 2 hangs on exit (encoding unverified).

### Cold re-init at the target speed (owner question, #48)

- What it would run (all SDK, `template/9300_nor/ab_memcntlr_setup.c` includes): `cg_mem_pll_init` (`cg_mem.c:60`), `memctlc_init_dram` (`boot0412/memctl.c:1847`) = PHY preset, DTR + MRS, pad ZQ, ZQCL/ZQCS, DLL reset, `DDR_Calibration`, size detect, DCR/MCERAWCR0 patches.
- Size: the whole stock SPL (CPU/LX/SPI/DRAM init + calibration + printf) is `0x5080` = 20 KiB, so DRAM init + calibration fits in the 64 KiB SRAM with a stack.
- Needs from the SPL environment: SRAM mapped (UMSAR), stack in SRAM, `cg_info_query.dev_freq` (MEM MHz for `board_DRAM_freq_mhz`), `puts/printf` (stub), `writeback_invalidate_dcache_all`, the calibration target `0x80b00000` (cached, 8 KiB). Nothing in flash `0x0`-`0xDFFFF` is written.
- After it: reload our U-Boot from the memory-mapped window (`0xb4200000`, flash `0x200000`) into DRAM, flush caches, jump. Switch DMA must be stopped and the watchdog armed first.
- Speed-specific work it adds over lead 1 + 3: the PHY preset (lead 2, a register write) and the DRAM-content-destroying size detect. Pad ZQ is not speed-dependent. So it buys no step that 1-3 cannot do in place; it costs a U-Boot reload and a second boot path. Rank: after leads 1-3.
