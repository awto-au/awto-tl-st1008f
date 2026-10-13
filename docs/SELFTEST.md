# Boot self-test (`st1008f-selftest`, #108)

- One time-bounded test under Linux at every OpenWrt boot: proves the clocks in use and the memory, prints everything else it can read.
- Target ~20 s at the defaults (mem 12 s, CPU 5 s, the rest < 3 s); every step has its own bound.
- Status 2026-10-13: built (OpenWrt toolchain, mainline initramfs) and run on sw2 (results below).

## Files

- `openwrt/linkcheck/files/usr/sbin/st1008f-selftest` — POSIX sh (BusyBox ash). In every OpenWrt image (files/ overlay) and the mainline initramfs.
- `openwrt/linkcheck/files/etc/init.d/st1008f-selftest` — START=99, background: waits ≤ 15 s for bridge `switch`, then runs `--quiet --console`. Never blocks boot.
- `openwrt/selftest/st1008f-stx.c` — static helper `/usr/libexec/st1008f-stx`: `peek` (/dev/mem), `mem`, `slot`, `crc`. Built by `scripts/build_selftest.py`.
- `/usr/share/st1008f-selftest/cpu.xz`, `cpu.md5` — 512 KiB pseudo-text as XZ/LZMA2 (CPU test).
- Kernel: `300-22` adds debugfs `st1008f_sram_test`; `CONFIG_MEMTEST` + `CONFIG_ST1008F_SRAM_BENCH` in `mainline/st1008f-v2.config` and `openwrt/kernel-7.3/config-7.3`.
- OpenWrt config (`build_openwrt.py` `SELFTEST_CFG`): `KERNEL_DEVMEM`, BusyBox `devmem`, `unxz`, `xzcat`, `taskset`, `setsid`.

## Output

- `/tmp/st1008f-selftest.log` — full decoded log. `/tmp/st1008f-selftest.json` — per item status, detail, data. `/tmp/st1008f-selftest.summary` — the summary line.
- Summary (console with `--console`, syslog, stdout): `st1008f-selftest: PASS [items] (N s) warn [..] skip [..] clocks PROFILE` or `FAIL [failed items] ...`.
- Persistent: `/etc/st1008f-selftest.last.json` (≤ 16 KiB) and `/etc/st1008f-selftest.loader` (first loader CRC). Not written while SPI runs above stock (#50).
- Exit 0 PASS, 1 FAIL, 2 usage / already running (lock `/tmp/st1008f-selftest.lock`).
- Item status: PASS, FAIL, WARN (reported, not a fail), SKIP (tool or kernel feature missing).

## Steps

| Item | Bound | FAIL when |
|---|---|---|
| clocks | 2 s | /dev/mem unreadable; SPI SCK > 25.6 MHz |
| mode | 2 s | GPIO unreadable |
| thermal | 2 s | never (WARN ≥ 90 °C raw) |
| env | 2 s | `fw_printenv` fails; `ethaddr` missing, placeholder, not unicast |
| flash | 2 s | chain env set and slot bad; loader CRC changed |
| sfp | 2 s | never (WARN: module present, EEPROM unreadable) |
| asic | 2 s | switch-core registers unreadable |
| kmemtest | 2 s | dmesg `bad mem` |
| sram | 2 s | any pattern error; refused (segment unmapped) |
| cpu | ceil(CPU_SECS × 1.25) + 1 | any XZ decode md5 wrong; fewer decodes than CPUs |
| mem | ceil(MEM_SECS × 1.25) + 1 | any pattern error; helper setup error |

- Bound = ceil(expected × 1.25) + 1 s (the killer is a BusyBox `sleep`, 1 s resolution). Each step runs as `sh $0 --step ITEM` in its own process group (`setsid`); expiry = TERM to the group, item FAIL `timeout after N s`.
- Order: clocks, mode, thermal, env, flash, sfp, asic, kmemtest, sram, cpu, mem (cheap reads first; flash skipped when clocks found fast SPI).

### clocks + registers

- Read through `/dev/mem` (`st1008f-stx peek`, fallback BusyBox `devmem`). Formulas: [CLOCKS.md](CLOCKS.md).
  - CPU = VCO(`PLL_CPU_CTRL0`) / (`PLL_CPU_MISC_CTRL[6:4]` + 2); VCO = 25 MHz × (4 if SEL_DIV4) × (NCODE + 2) × 2 / 2^PREDIV.
  - LX / NOR = VCO(`PLL_SW_CTRL0`) / (2 × (`PLL_SW_DIV_CTRL` LXB / SPI_NOR + 2)); SPI = NOR / (2 × (`SFCR[31:29]` + 1)).
  - DDR = 25 × (`SYS_MEM_PLL_CTRL3[31:24]` + 2) / (2 << `SYS_MEM_PLL_CTRL2[15:14]`); SRAM = 500 if `PLL_SRAM_CTRL.sram_pll_sel` else 250 MHz.
- Profile: `stock` when live = cpu 800, ddr 600, lx 175, sram 250; else `cpu=..,ddr=..,lx=..,sram=..`. Also logs stored `st1008f_turbo` and bootargs `st1008f.mode`.
- Registers dumped and decoded (names: [REGISTERS.md](REGISTERS.md)): `PLL_GLB_CTRL0`, `PLL_CPU_*`, `PLL_SW_*`, `SYS_MEM_PLL_CTRL2/3`, `PLL_SRAM_CTRL`, `MCR` (`ip_ref`/`dp_ref` prefetch), `DCR`, `DTR0-2` (CL, tWR, CWL, tRTP, tWTR, tREFI, tRP, tRCD, tRRD, tFAW, tRFC, tRAS), `CPU_SRAM_ASY_TIMING`, `SFCR`/`SFCR2`, `SYS_STATUS`, `CPU_SRAM_SEG0-3_ADDR` + seg0 size/base, `UMSAR0-3`, `UMSSR0`.

### mode (switch position, #8 #46)

- Raw `PABCD_DAT` (`0xb800330c`) read twice, `PABCD_DIR`, `0xb8003300` (raw, function select bits 17-19).
- Pins 17/18/19 → position from pins 18/19 (1/1 M1, 0/1 M2, 1/0 M3, else invalid); vendor pattern (stock `custom_judge_pattern_mode`, `scripts/mode_watch.py`).
- WARN: invalid position; pin 17 not one-hot (low at M1 only) = stuck suspect (#8); pins changed between reads; pins not inputs; position ≠ bootargs `st1008f.mode`; ≠ 300-06 driver debugfs `st1008f-mode-switch/state` (whole file logged).
- Also logs gpiolib lines 17-19 from debugfs `gpio`.

### asic (switch core, read-only)

- Per cage (lanN = cage N, SDK port 0/8/16/20/24-27, SerDes N+1):
  - MAC-side `SDS_MODE_SEL_0/1/2` mode (SGMII, 1000BASE-X, 2500BASE-X, 10GBASE-R, off, ...). A mode forced inside the SerDes (WDIG) is not visible here.
  - `MAC_LINK_STS` (second of two reads: latched low) and `MAC_LINK_SPD_STS` speed.
  - netdev operstate, carrier, speed, duplex; bridge, bridge-port STP state, `isolated`; hardware STP from rtl83xx debugfs `rtl838x/lanN/stp_state`; `cpu_only` = standalone or isolated.
  - LED owner from `LED_PORT_SW_EN_CTRL` (0 = hardware engine).
- `LED_GLB_CTRL` decoded (LED_MOD, LED_ACTIVE, SYS_LED_EN, SYS_LED_MODE, BLINK_TIME_SEL); `st1008f-leds` state.
- Bridges: `stp_state`, `forward_delay`, `vlan_filtering`; `bridge vlan show`; nft flowtables with `flags offload`; `hw-tc-offload` per port.
- Not read: the port isolation table (`PORT_ISO_CTRL`) needs the table-access engine, which the DSA driver uses concurrently. Bridge `isolated` flags stand in.

### sfp

- Per lanN: `ethtool -m` A0/A2 → identifier, vendor, PN, SN; DDM (A0 92 bit 6) temperature, Vcc, bias, TX/RX power (0.1 µW), soft RX_LOS (A2 110 bit 1); presence pin (`PABCD_DAT` bit cage-1, low = present); carrier.
- Logs the 300-06 driver power table (declared mW per cage, budget).
- Read-only; unlike `st1008f-linkcheck` it never changes STP.

### env, flash

- env: `fw_printenv` (uboot-envtools); `ethaddr`, `bootcmd` chain type (`crc` = `ub_ck`, `nocrc`, `none`), `st1008f_turbo`, `st1008f_turbo_bad`, `st1008f_boot`.
- flash: `jffs2-log` slot checked like `scripts/uboot_chain_image.py` (slot CRC32 vs trailer, magic, image size + CRC); loader `u-boot` (0x0-0xDFFFF) CRC32 vs the first recorded value. Read-only.

### kmemtest

- Kernel `early_memtest` result from dmesg when bootargs carry `memtest=N`; MIPS covers lowmem only.
- Off by default: `memtest=N` is not in any default bootargs (boot time; boot-log allowlist). Enable with U-Boot bootargs, e.g. `ramload ... --bootargs memtest=4`.

### sram

- debugfs `st1008f_sram_test` (300-22): largest free chunk of the mmio-sram pool (≤ 64 KiB minus bench/clock users); patterns addr, walk1, walk0, check, icheck, rand; uncached (KSEG1) then cached (KSEG0, write-back + invalidate between write and read). Errors: pa, want, got, XOR (≤ 16 lines per unit).
- Refuses when `CPU_SRAM_SEG0_ADDR` is not enabled at the pool address (#103 #107).

### cpu

- One loop per online CPU (pinned with `taskset` when it works): `xzcat cpu.xz | md5sum` vs `cpu.md5` until CPU_SECS. The CPU 1400 fault showed as XZ corruption ([OVERCLOCK.md](OVERCLOCK.md)).
- BusyBox has no XZ compressor: decode only.

### mem

- `st1008f-stx mem`: MemAvailable − MEM_RESERVE (64 MiB) as one anonymous mapping; `oom_score_adj` 1000 (an OOM kills the test, not a service).
- Page-in (≤ 1/4 of the budget; region cut if slower), then `/proc/self/pagemap` → DRAM address per page: phys ≥ `0x20000000` = high bank (DRAM 256-512 MiB). Logs MiB low / high covered.
- Patterns in order rand, addr, walk1, walk0, check, icheck (same generators as U-Boot `memtest.c`); write all, then read all. A pattern starts only if it fits; the write stops at half the remaining budget and the written part is checked.
- Per error: region, test, DRAM address, want, got, XOR, re-read (= got: stored wrong). Per pattern: bit counts, bank / row / col histograms (decode as `memtest.c`).
- Cached userspace: the 32 KiB D-cache is negligible against hundreds of MiB, so reads come from DRAM. Default budget = one rand pass over ~400 MiB; `--full` = all six.

## Options and config

- `st1008f-selftest [--quiet] [--console] [--mem-secs S] [--cpu-secs S] [--full] [--mark-turbo-bad] [--no-persist]`.
- `/etc/st1008f-selftest.conf` (sh): `ENABLED=0` (init.d off), `MEM_SECS`, `CPU_SECS`, `MEM_RESERVE`, `MARK_TURBO_BAD=1`, `PERSIST_ON=0`.
- Mainline initramfs: in the image; `/init` starts it in the background only with bootargs `st1008f.selftest=1` (console flows expect a quiet prompt).

## Turbo-fail marker (opt-in)

- With `--mark-turbo-bad` or `MARK_TURBO_BAD=1`: on FAIL with a non-stock profile, `fw_setenv st1008f_turbo_bad <failed items>@<profile>` (one u-boot-env write).
- Off by default: the env write is outside `./dev.py uboot-chain-env` (CLAUDE.md env rule); enable per unit by owner decision.
- Our U-Boot does not read `st1008f_turbo_bad` yet; the fallback to stock clocks belongs to bootsel (#46, #105).

## Host side

- `./dev.py selftest [--ip IP]` — SSH run, summary + JSON to `tmp/logs/`. `--console` at the initramfs prompt; `--last` reads the last result (the only mode on sw1). [scripts/README.md](../scripts/README.md).
- `./dev.py switch-check` prints the last summary (`selftest=`), not part of its PASS.

## Measured on sw2 (2026-10-13T12:25-12:30+11:00, mainline initramfs, `./dev.py selftest --console`)

| Clocks (CPU / DDR / LX / SRAM) | Summary | cpu (XZ decodes, both VPEs) | mem (401 MiB) |
|---|---|---|---|
| 800 / 600 / 175 / 250 (stock) | FAIL [sfp] | 36 OK (5 s) | rand: 8632 ms, 1 of 6 patterns in 12 s; step 9869 ms |
| 1375 / 662 / 306 / 500 | FAIL [cpu] | **1 of 55 wrong** (cpu0) | rand 5014 + addr 6050 ms, 2 of 6; step 11972 ms |
| 1350 / 662 / 306 / 500 (`--cpu-secs 15`) | PASS | 161 OK | pass |
| 1300 / 662 / 306 / 500 (`--cpu-secs 15`) | PASS | 157 OK | pass |

- sfp at stock: `timeout after 2 s` with 7 modules (the 2 s bound is too tight at 800 MHz; 1410 ms at the picks).
- env, kmemtest SKIP in the initramfs (no `fw_printenv`; no `memtest=` on the cmdline). flash: jffs2-log slot CRC mismatch reported (`a8ac0713` vs trailer `ffffffff`).
- `./dev.py selftest --console`: the JSON read back over the console is unreadable (3470 B); the summary and the log are fine.
- Memory step: 401 MiB per pattern ~5-6 s at the picks, ~8.6 s at stock: the 12 s budget covers 1-2 of the 6 patterns.

