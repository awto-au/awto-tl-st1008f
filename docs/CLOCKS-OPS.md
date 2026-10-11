# TL-ST1008F clocks: operations

How to run and verify clock changes. Facts (registers, formulas, measured results): [CLOCKS.md](CLOCKS.md).

## Defaults

- `./dev.py ramload uboot-mainline` applies, after `go`: CPU 1000 MHz (`e208 0x3a8`, /3) and SPI 122.5 MHz (SFCR /2, NOR source code 3). `--stock-clocks` keeps 800 MHz / 25.5 MHz.
- LX stays 175 MHz (204 MHz works, no measured gain). DDR stays 600 MHz until `mem-clock` passes.
- Applies only to our RAM-loaded U-Boot; stock U-Boot and unattended boots run stock clocks (#47).

## Read

- `clocks` at the mainline prompt: every rate and DDR timing decoded from the registers.
- Host: `scripts/clock_calc.py decode <md.l dump>`; `scripts/clock_calc.py cpu <MHz>` gives e208/e210.

## Change and verify

| What | Command | Pass |
|---|---|---|
| CPU ladder | `./dev.py cpu-clock <e210> <e208> [e208 ...]` | locked; `clocks` src pll; real rate (host-timed `sleep 5`) within 1 % of decoded; stops at first fail |
| CPU, Linux load | `./dev.py ramload uboot-mainline --then openwrt --cpu <e208>`, then 2x `md5sum /dev/zero`, `./dev.py flash-openwrt-watch --attach` | no reboot, STP holds, temperature flat |
| SPI-NOR | `./dev.py flash-speed [D ...] [--nor CODE ...]` | whole-chip CRC = the /6 baseline at every step; mismatch restores the previous setting |
| LX | `clocks set lx <code> force` | console answers; `./dev.py uboot-test sfp_all ddm laser rtk_port sf_read highmem timer` |
| DDR | `./dev.py ramload uboot-mainline --from-flash --stock-clocks`, then `./dev.py mem-clock 600 650 --nosr` (600 first = stock values through the new sequence; self-refresh mode hangs) | `mem set OK`; `clocks` decodes the bin; crc32 + `md` of 16 MiB copied before the change unchanged; `highmem test` 0 errors |
| Whole board | `./dev.py uboot-test` | all pass |
| Throughput | `./dev.py bench run <label>`, `./dev.py bench compare` | table in CLOCKS.md |

- DDR: record the UART marks (`M S P X D` then `C`/`F`), `MPMR0 in SR` (expect 2 in bits 29:28) and `exit` (0), DMCR polls left, routine time. If 600 hangs: retry once with `--nosr`, note the last mark.
- DDR: no `rtk network on` / Ethernet traffic in the same boot before the change (switch DMA must be idle): load ours with `--from-flash`. That boot has no SerDes config and cage 8 reads empty (#51), so `rtk_port` / `sfp_a0` checks fail there.
- DDR 650 is not a default yet: one pass so far; needs a soak (Linux load) first.

## Recovery

- Clock changes are RAM-only. Power cycle (`./dev.py power off` / `on`, or `./dev.py stock`) reruns the stock SPL: stock clocks, fresh DDR init.
- A hang after a change (CPU, LX, DDR) is recovered the same way; nothing to clean up. Clock experiments never write flash.
