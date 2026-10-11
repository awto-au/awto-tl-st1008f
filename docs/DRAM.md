# TL-ST1008F DRAM: theory vs measured

Facts only. How to run the measurements: [CLOCKS-OPS.md](CLOCKS-OPS.md). Registers and clock tree: [CLOCKS.md](CLOCKS.md).

## Part and configuration

- One DDR3 die, x16, 4 Gbit = 512 MiB (DCR `21421003`: 8 banks, 15 row + 10 col bits).
- Part (board photo, 2026-10-11): **Zentel A3T4GF40BBF-HP**, DDR3-1866 (933 MHz, CL13), 256M x16, 96-ball FBGA. OpenWrt's TL-ST1008F v2 commit names a Samsung K4B4G1646E-BYMA: other boards or wrong. Datasheet: `sources/README.md`.
- Run by the stock SPL at 600 MHz (DDR3-1200): DRAM CL 9 (controller CL 10), CWL 7, WR 10, tRCD/tRP 15 ns, tRAS 38.3 ns, tRFC 270 ns, tREFI 3.84 µs (2x refresh, the >85 °C rate). MR0-MR3: CLOCKS.md register map.
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
- **DDR clock barely matters**: 600 → 650 changed every test by ≤ 4 %.

## Headroom left (not done)

| Lever | Expected gain | Cost / risk |
|---|---|---|
| Linux `memcpy` uses `pref` (CPU_MIPS32_R2 selects CPU_HAS_PREFETCH; 16 PREF sites in `arch/mips/lib/memcpy.S`); Linux `memset` has none (write-allocate path, helped by MCR prefetch); userspace libc copies: not checked | `memset` up to the `pref 30` figure | kernel `memset.S` change (upstream) |
| tREFI 3.84 → 7.8 µs (normal-temperature refresh) | ≈ 3.5 % of DRAM time; ≈ 0 in practice (access is latency-bound, bus mostly idle) | **decided: keep stock.** DDR3 has no readable temperature (only DDR4/LPDDR do); the SoC sensor peaked at 75 °C under load, heatsink off |
| Tighter timings for a DDR3-1866 part at 600-650 MHz (CL, tRCD, tRP) | a few ns of the 30-45 ns DRAM part only | MRS path exists (675+ bins); no 600/650 tight bin defined |
| Unexplained MCR bits: `ocp0_frq_slower` 9 = 1, `ocp0/1_rbf_f_dis` 5/6 = 1, `sync_ocp0_dram` 0 = 0 | possibly the 65-80 ns bus/controller overhead | unknown semantics (#52) |
| DDR above 650 MHz | ≤ a few % (600 → 650 moved every test ≤ 4 %) | 675-800 implemented (CL 11 / CWL 8 via MRS), untested; PHY taps and PLL loop settings SPEC (#48, #49) |
