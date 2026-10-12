# TL-ST1008F clocks: operations

How to run and verify clock changes. Facts (registers, formulas, measured results): [CLOCKS.md](CLOCKS.md).

## Defaults

- `clocks fast` (our U-Boot) = CPU 1000 MHz (`PLL_CPU_CTRL0` e208 `0x3a8`, /3) + DDR 650 (`nosr`) + tREFI 4608 clk (7.09 µs) + DRAM controller prefetch (MCR bits 23/22, #52); SPI unchanged. Runs on every power-up (chain, #47) and in `./dev.py ramload uboot-mainline`.
- `ramload` also sets SPI 122.5 MHz (SFCR /2, NOR code 3) in U-Boot-only sessions; never before Linux: 102.1 MHz broke JFFS2 reads (#50). Ladder: `./dev.py spi-linux [D:CODE ...]` (first = baseline). `--stock-clocks` keeps 800 MHz / 25.5 MHz.
- LX stays 175 MHz (204 MHz works in U-Boot, no measured gain; garbles the Linux console because the kernel DTB/UART rate stays 175). DDR stays 650 MHz (675+ unstable, #48).
- Stock U-Boot alone (`./dev.py stock`, `--stock-clocks`) runs stock clocks; every unattended power-up runs `clocks fast` through the chain (#47).

## Read

- `clocks` at the mainline prompt: every rate and DDR timing decoded from the registers.
- Host: `scripts/clock_calc.py decode <md.l dump>`; `scripts/clock_calc.py cpu <MHz>` gives e208/e210 (`PLL_CPU_CTRL0` / `PLL_CPU_MISC_CTRL`).

## Change and verify

| What | Command | Pass |
|---|---|---|
| CPU ladder | `./dev.py cpu-clock <e210> <e208> [e208 ...]` | locked; `clocks` src pll; real rate (host-timed `sleep 5`) within 1 % of decoded; stops at first fail |
| CPU, Linux load | `./dev.py ramload uboot-mainline --then openwrt --cpu <e208>`, then 2x `md5sum /dev/zero`, `./dev.py flash-openwrt-watch --attach` | no reboot, STP holds, temperature flat |
| SPI-NOR | `./dev.py flash-speed [D ...] [--nor CODE ...]` | whole-chip CRC = the /6 baseline at every step; mismatch restores the previous setting |
| LX | `clocks set lx <code> force` | console answers; `./dev.py uboot-test sfp_all ddm laser rtk_port sf_read highmem timer` |
| DDR | `./dev.py ramload uboot-mainline --from-flash --stock-clocks`, then `./dev.py mem-clock 600 650 --nosr` (600 first = stock values through the new sequence; self-refresh mode hangs) | `mem set OK`; `clocks` decodes the bin; crc32 + `md` of 16 MiB copied before the change unchanged; `highmem test` 0 errors |
| DDR above 650 | `./dev.py ramload uboot-mainline --from-flash` (CPU 1000: 800 MHz MEM must stay below CPU), then `./dev.py mem-clock 650 675 700 725 750 775 800 --nosr` | as DDR, plus mark `R` after `P` on the 650 → 675 step (MRS), `ddr3 dram: CL 11 CWL 8` in `clocks`, and `bench` completes (675/700 hang there). `--extra '<opts>'` passes probe options (e.g. `dqshift -8`) to a real set |
| Linux reads under a setting | boot flash OpenWrt the stock way (`./dev.py flash-openwrt-watch --minutes 0`), `./dev.py rootfs-hash stock`; then boot with the setting, `./dev.py rootfs-hash <label> --against stock` | same hash, 0 SQUASHFS errors |
| Whole board | `./dev.py uboot-test` | all pass |
| Throughput | `./dev.py bench run <label>`, `./dev.py bench compare` | table in CLOCKS.md |

- DDR: record the UART marks (`M S P X D` then `C`/`F`), `MPMR0 in SR` (expect 2 in bits 29:28) and `exit` (0), DMCR polls left, routine time. If 600 hangs: retry once with `--nosr`, note the last mark.
- DDR: no `rtk network on` / Ethernet traffic in the same boot before the change (switch DMA must be idle): load ours with `--from-flash`. That boot has no SerDes config (#51), so the `rtk_port` check fails there.
- DDR above 650, isolating a failing bin (start at 650: `./dev.py mem-clock 650 --nosr`; every probe returns to it): `./dev.py mem-tap-sweep` then
  - `once --mhz 650 --extra cl11`: CL 11 / CWL 8 at 650. Bad → the CL 11 config; good → the clock.
  - `mpcr --mhz 675`: SDK PLL rows (#56).
  - `field --mhz 675 --reg b8001050 --fields 28:24,20:16 --values 0-31`: DIDER DQS0/1 read-enable taps (#49).
  - `dqshift --mhz 675 --values -8-8`: all DQ read taps shifted.
  - `field --mhz 675 --reg b8001500 --fields 20:16,12:8 --values 0-31`: DACCR DQS group taps.
  - Add `--extra "mpcr A B C"` to combine with a PLL row. Pass = `canary 0 bad`; result per setting in `tmp/logs/mem_tap_sweep.log` + CSV. Stops on `probe FAIL` (not back cleanly) or a hang.
- DDR above 650: `--from-flash` runs the U-Boot stored in flash; it must be a build with the 675-800 bins (older builds answer `no bin`). A canary failure reverts to the previous bin, MRS included; a hang = power cycle.

## DDR above 650: lead order (#48, #49, #56)

Leads and sources: [DRAM.md](DRAM.md#leads-for-675-800-ranked). Each lead = one configuration; for each, speed is bisected top-down.

- Speed points: bins 800, 775, 750, 725, 700, 675, 662 (CPU 1000 so MEM < CPU). Order per configuration: 800 → 725 → (pass: 775/750; fail: 700) → neighbour. One quick test per point: `mem-clock 650 <MHz> --nosr --extra '<opts>'` → canary 0 bad, then `bench` completes (write hang check). Stop at the first passing point; n = 5 only on the chosen point.
- Configuration order (cheapest first, each kept if it moves the edge up):
  1. DLL reset + ZQCL on every change (needs a `ddr_sram.S` change).
  2. SPL 650 PHY preset: `reg b80015b0 0fffffff`, `reg b80015b4 03000fff`, `reg b80015b8 ffffffff`, `reg b80015bc ffffffff`.
  3. MEM PLL: `mpcr 0000007f c00001ef 26a33860`, then `mpcr 0000007f c00001ef 2ea23980`.
  4. Read + write tap retrain in the SRAM routine (SDK `DDR_Calibration_Full_Scan_Reduce`; needs code). Until then `dqshift` by hand on the read side.
  5. PI phases: `mpcr 000c807f 4000018f <row MPCR2>`; BIS 700 CK 10 / CLKM 8.
  6. DTR2 low nibble `0xB` with CAS_PHY = CL (BIS EN_TCC_DIFF): test only.
- The `reg` override accepts `b8001050..58` and `b8001500..15c4`; the write-tap registers DWDQOR0-3 (`15d0..15dc`) and DCPER `1064` need the range widened first.

## SPI-NOR leads (#50)

Leads and sources: [SPI-NOR.md](SPI-NOR.md#settings-to-try-highest-first).

- Speed points (SFCR /2, NOR code): 153.1 (2), 122.5 (3), 102.1 (4), 87.5 (5), 76.6 (6). Order per configuration: 153.1 → 102.1 → (pass: 122.5; fail: 87.5) → neighbour.
- Quick test per point: U-Boot first (no Linux): whole-chip `crc32` of the window and `sf read` of the same range (PIO 13h, or 0Ch with `m25p,fast-read`); then Linux `./dev.py spi-linux` md5 plus a small-read test (JFFS2 mount or random 16-64 B reads).
- Configuration order:
  1. Discriminator: `sf read` (13h) vs window CRC at 102.1 and 122.5. `sf read` fails + window passes = opcode cause.
  2. `m25p,fast-read` in the DTs (0Ch).
  3. SR3 DRV = 100 % (volatile).
  4. SFRDR `b8001218` coarse 0, 4, 8, 16, 31 (io0-3 together), then fill around the edge.
  5. Linux reads via dirmap quad I/O (ECh class).

## Recovery

- Clock changes are RAM-only. Power cycle (`./dev.py power off` / `on`, or `./dev.py stock`) reruns the stock SPL: stock clocks, fresh DDR init.
- A hang after a change (CPU, LX, DDR) is recovered the same way; nothing to clean up. Clock experiments never write flash.
