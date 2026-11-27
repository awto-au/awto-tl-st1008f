# Overclock: survey and first Linux runs 2026-10-13 (history)

Moved unchanged from [../OVERCLOCK.md](../OVERCLOCK.md) (method, register rules, per-unit settings stay there). Conclusions: [../FINDINGS.md](../FINDINGS.md).

## Overview survey (sw2, 2026-10-13T09:10-10:01+11:00, one run per point, our U-Boot RAM-loaded)

One quick test per point: the change reports OK, prompt, 16 MiB `crc32`, temperature (31-34 °C raw at every point). No repeats; the owner picks settings before n=20.

| Domain | Point | Result | Measured | Note |
|---|---|---|---|---|
| CPU | 1050-1400 | pass | real 1097.6 / 1185.6 / 1297.2 / 1395.9 at 1100 / 1200 / 1300 / 1400 | /2 VCO 2200-2800 above 1050; 1100-1400 also n=5 |
| CPU | 1425 | pass | decoded only | `0x378` /2 VCO 2850 |
| CPU | 1450, 1500 | hang | — | inside `clocks set cpu` (no prompt) |
| SRAM | 250 → 500 | pass | uc read 80.4 → 60.0 ns, uc write 22.0 → 15.0 ns, cached fill 26.9 → 23.8 ns/word | DRAM: 80.3 / 14.5 / 26.6 ns; `clocks membench`, CPU 800 |
| LX | 306, 245 | pass | — | UART follows (`clocks set lx 2/3`); Linux side untested |
| DDR | 800, 750, 700 | fail | canary bad, reverted | 700 + dqshift −6 also fails |
| DDR | 675 + dqshift −8 | pass | — | 662.5 and 650 pass plain |
| SPI-NOR (U-Boot, Quad I/O 0xEB, D = 0) | 306 | hang | `crc32` timeout | NOR code 0 |
| SPI-NOR | 204, 153 | fail | CRC wrong | codes 1, 2 |
| SPI-NOR | 122.5 | pass | flash_c 37.0 MB/s, chip CRC 3.5 s | code 3 (as Dual I/O) |

## Linux at the picks (sw2, 2026-10-13T10:36-11:26+11:00, mainline next + SRAM patches)

- Base = `nic-bench boot` clocks: our U-Boot `clocks fast` (CPU 1000, DDR 650, tREFI 4608, prefetch on, SRAM 250, LX 175); points add `turbo` before `bootm` (`ST1008F_RAMLOAD_EXTRA="--pre|turbo …"`).
- Quick test per point now includes a kernel boot to the initramfs shell (`clocks-cycle --session`, default): U-Boot unlzma + kernel initramfs XZ unpack catch CPU faults the 16 MiB `crc32` misses.

### Kernel boot per clock (one boot each)

| turbo | Result |
|---|---|
| cpu=1400,ddr=662,sram=500 | panic `XZ-compressed data is corrupt` (initramfs unpack, 0.59 s) |
| cpu=1400,sram=500 | same panic |
| cpu=1400 | same panic |
| ddr=662 / sram=500 / ddr=662,sram=500 | shell |
| cpu=1300 / 1350 / 1375 | shell |
| cpu=1375,ddr=662,sram=500 | shell (3 boots) |
| cpu=1400,ddr=662,sram=500 + `memtest=4`, from stock clocks | U-Boot `lzma compressed: uncompress error 1`, reset |
| `clocks-cycle --session cpu --lo 1350` from stock clocks | 1375, 1400, 1425: shell (one boot each) |

- CPU 1400: 4 fails, 1 pass; 1425: 1 pass. DRAM is clean at the same clocks (DRAM.md "Memtest"): the fault is CPU-side (decompressor = core + L1 load). 1400/1425 are marginal; 1375 passed all 5 boots.
- Boot self-test XZ load (both VPEs, `selftest --console`, 2026-10-13T12:26): CPU 1375 **1 of 55 decodes wrong**; 1350 161/161 and 1300 157/157 OK (15 s each). 1375 is marginal under sustained load: pick candidate 1350 (owner decision, #103).
- LX 306 under Linux (2026-10-13T11:39, `turbo lx=306` before `bootm`): console clean, shell reached, boot log clean, uptime vs host 12.98 s / 12.98 s. Kernel reads LX/CPU from the PLLs (`300-23`); watchdog probe failed (-EINVAL: DT 30 s > 28.9 s hardware max at LX 306) until `300-24`.

### At the picks vs base (one run each)

| Test | Base | 1375/662/500 | + LX 306 |
|---|---|---|---|
| nic-bench tcp-P4 | 291 Mbit/s | 418 Mbit/s | 436 Mbit/s |
| nic-bench udp1400 900 Mbit/s offered: loss | 26.5 % | 0.2 % | 0.3 % |
| nic-bench udp64 forward | 61.5 kpps | 92.2 kpps | 92.8 kpps |
| sram-bench SRAM uc read / cached miss (ns per access) | 71.8 / 86.9 | — | 43.9 / 51.8 |
| sram-bench DDR uc read / cached miss / uc write (ns) | 100.2 / 103.0 / 61.2 | — | 84.4 / 86.7 / 56.3 |
| mem-stress (416-432 MiB tmpfs fill + md5) | pass, 4.1 s fill | — | pass, 3.2 s fill |

- DDR uncached writes are not slower at the picks (61.2 → 56.3 ns; U-Boot `membench` 12.4 → 9.0 ns, DDR 662 alone no change). The earlier +13 % came from the sram-bench ns column: `div_u64` truncated the u64 divisor to u32; fixed in `300-22` (`div64_u64`).
- `mem-stress` hung the kernel at every clock incl. stock: 300-21's unmap segment hid Linux phys `0x2f000000` (HARDWARE-INVENTORY.md 64 KiB SRAM, #107); 300-21 now maps the SRAM segment only.
- NIC DMA reaches the on-chip SRAM (2026-10-13T11:53, U-Boot `uboot-test net --ethsram`: TX buffers + RX ring-0 slots 0-15 at bus `0x1f005000`-`0x1f00d7ff`): ping, DHCP, TFTP + wget of 475 KB with matching CRC32, netconsole.

## CPU above 1000 MHz (sw2, 2026-10-13, CPU_SRAM_ASY_TIMING written)

| CPU | e208 / DIVN2 (VCO) | `clocks-cycle cpu` n=5 | Real rate (`cpu-clock`, host-timed `sleep 5`) |
|---|---|---|---|
| 1050 | `0x3d8` /3 (3150) | 5/5 | — |
| 1100 | `0x2a8` /2 (2200) | 5/5 | 1097.6 |
| 1150 | `0x2c8` /2 (2300) | — | 1147.2 |
| 1200 | `0x2e8` /2 (2400) | 4/5 + 1 ramload miss | 1185.6 (−1.2 %) |
| 1300 | `0x328` /2 (2600) | — | 1297.2 |

- Pass = PLL locked, prompt, 16 MiB `crc32`, temperature. U-Boot idle temperature 31-32 °C (raw `TEMP_OUT`, meter just enabled) at every point.
- Before the CPU_SRAM_ASY_TIMING fix, 1066.7 MHz (/3, VCO 3200) hung after the PLL write (2026-10-10). /2 with VCO 2200-2600 locks at once.
- Not yet: n=5 at 1300, points above 1300, a Linux load at these rates, n=20 on the pick.
