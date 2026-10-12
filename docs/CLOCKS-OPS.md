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

## Recovery

- Clock changes are RAM-only. Power cycle (`./dev.py power off` / `on`, or `./dev.py stock`) reruns the stock SPL: stock clocks, fresh DDR init.
- A hang after a change (CPU, LX, DDR) is recovered the same way; nothing to clean up. Clock experiments never write flash.
