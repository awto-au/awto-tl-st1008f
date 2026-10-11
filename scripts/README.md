# Scripts

Run everything from the repo root. Python 3; `pyserial` for the console scripts.
Logs go to `tmp/logs/<name>.log`; captures and dumps go to `private/` (gitignored).

Hazards that apply to every script that talks to the switch:
- **The console daemon owns the UART.** Nothing else opens the tty while it runs (no `tio`, `minicom`, `screen`).
- **Never send flash-writing U-Boot commands:** `saveenv`, `savesys`, `setsys`, `upgrade*`, `*force`, `flerase`, `erase`, `sf write/erase/update`.
- **Cage loop:** two cages cabled to the same switch + both lasers on = broadcast storm. Light one cage only; unplug the others before `bootm` (OpenWrt lights all lasers and bridges all ports).
- Run `rtk network on` once per boot, before any GPIO/I2C `rtk` command.

End-to-end workflow: [../README.md#workflow](../README.md#workflow).

## Console

### switch_console_daemon.py
- Purpose: single owner of the serial port. Mirrors RX and TX markers to one log; unix-socket control channel; auto-catches the U-Boot autoboot banner and sends Esc.
- Run: `scripts/switch_console_daemon.py --dev /dev/serial/by-id/<adapter> --baud 115200 [--policy hold|boota|<cmd>]`
  - `--dev` defaults to `$ST1008_SERIAL`, else the generic PL2303 by-id name.
- Output: `private/serial/st1008-console.log` (`--log` to change); `tail -f` it. Socket and pid in `$XDG_RUNTIME_DIR/tio-st1008.daemon.{sock,pid}`.
- Ops: `send`, `break` (real UART BREAK), `break_cmd` (BREAK + SysRq byte), `baud`, `read`, `status`, `policy`, `dump_range` (bulk `md.b` parsed inside the daemon), `quit`.
- Notes: `tio` drops the PL2303 when stdin is not a terminal; pyserial holds it. Policy `hold` stays at `RTL9300#`.

### switch_console.py
- Purpose: client for the daemon; one request per invocation, prints what the switch replied.
- Run: `scripts/switch_console.py status | send "rtk network on" | send --raw $'\r' | esc | break [--dur 0.3] | baud 115200 | policy hold | read --secs 3`
- Output: stdout; everything is also in the daemon log.

### catch_uboot.py
- Purpose: watch the daemon log for `Hit Esc key to stop autoboot`, send Esc + CR, confirm `RTL9300#`. Superseded by the daemon's built-in catch; useful when the daemon runs with a booting policy.
- Run: `scripts/catch_uboot.py --wait 180`, then power-cycle the switch. `--wait` = time for you to power-cycle.
- Exit: 0 caught, 3 Esc sent but no prompt, 2 nothing seen. Log: `tmp/logs/catch_uboot.log`.

## Laser / network bring-up

### st1008_pca9534.py
- Purpose: drive the PCA9534 tx-disable expander by raw GPIO bit-bang (`md.l`/`mw.l` on `0xb8003300`), with no SDK init. Historical: `rtk network on` + `rtk i2c write 8 …` replaces it.
- Run: `scripts/st1008_pca9534.py probe | read | enable-tx --out 0xfe [--per-line 6]` (at `RTL9300#`, via the daemon).
- Output: `tmp/logs/st1008_pca9534.log`. ~40 s per `enable-tx`; every byte ACK-checked; aborts if the prompt does not return.
- Hazard: preserves GPIO21 (DTS watchdog toggle) output-high; refuses if it is not. `--out 0x00` lights all 8 lasers (cage loop).

### routing_wirespeed.py
- Purpose: measure HW-L3 routed throughput through the switch and prove the ASIC (not CPU) forwards, watching error counters on switch + host. Gateway-routed hairpin over one 10G host NIC (two netns in far subnets behind per-VLAN gateways → both directions HW-forwardable; on-link would trap to CPU).
- Run: `routing_wirespeed.py setup | run [--secs N --streams P --udp MBPS] | probe | status | teardown`. Needs ssh to the switch (blank root pw) + host sudo. Log: `tmp/logs/routing_wirespeed.log`.
- Result (snapshot 6.18): 9.19 Gbit/s TCP / 9.53 Gbit/s UDP routed, 0.000 % via CPU, 0 errors. See `docs/ROUTING-OFFLOAD.md`.
- Config lands on OpenWrt overlay only (not U-Boot/vendor flash); `teardown` reverts it; mgmt VLAN1 untouched.

### tftpd.py
- Purpose: minimal TFTP server. RRQ for `tftpboot`; WRQ accepted for future uploads; blksize/tsize negotiation.
- Run: `sudo scripts/tftpd.py` (udp/69; stock U-Boot always uses 69) or `scripts/tftpd.py --port 6969 --once`.
- Input/output: serves and stores inside `--root` (default `tmp/tftp/`); put the initramfs at `tmp/tftp/st1008f.bin`. Log: `tmp/logs/tftpd.log`.
- Notes: per-packet wait 5 s (U-Boot's own TFTP retransmit timer), 5 retries, then the block number is logged and the transfer aborts.

## Backup and unpack

### st1008_mtd_backup.py
- Purpose: copy every MTD off a RAM-booted OpenWrt over SSH; SHA-256 on device and host; sizes vs `/proc/mtd`; concatenates `full-flash.bin` when the partitions cover 32 MiB.
- Run: `scripts/st1008_mtd_backup.py --host <switch-ip> [--out DIR]` (default host = OpenWrt's `192.168.1.1`).
- Output: `private/mtd-backup-<YYYYMMDD-HHMMSS>/` (`mtdN-<name>.bin`, `full-flash.bin`, `proc_mtd.txt`, `SHA256SUMS`). Log: `tmp/logs/st1008_mtd_backup.log`.
- Notes: read-only (`cat /dev/mtdNro`). SSH as root with no password (OpenWrt initramfs default); host keys not stored.

### st1008_stock_extract.py
- Purpose: unpack the stock RUNTIME image from a full-flash dump: uImage header + CRC check, LZMA kernel → `vmlinux.bin`, embedded cpio(s) → `initramfs-N/`, any squashfs after the kernel.
- Run: `scripts/st1008_stock_extract.py private/mtd-backup-<ts>/full-flash.bin [--out DIR]` (default `<dump dir>/stock-extract/`).
- Needs `cpio`, `unsquashfs`. Log: `tmp/logs/st1008_stock_extract.log`.
- Notes: a false-positive plain-cpio hit (`initramfs-0`, cpio errors) is expected; the gzip cpio (`initramfs-1`) is the real one. Device nodes are not created (unprivileged).

### dump_flash_mdb.py
- Purpose: read a flash range over U-Boot `md.b` through the daemon; resumable; verifies with U-Boot's own `crc32`.
- Run: `scripts/dump_flash_mdb.py --start 0x300000 --len 0xe80000 --out private/stock-runtime/runtime.bin [--no-verify]` (at `RTL9300#`).
- Output: `<out>.partial` until complete. Log: `tmp/logs/dump_flash_mdb.log`.
- Notes: ~2 KB/s at 115200; superseded by the OpenWrt route. Per-chunk wait is derived from the daemon's baud (`md_wait`).

### auto_dump_runtime.py
- Purpose: wait for the daemon to catch U-Boot, try a higher baud (1.5 Mbaud, CRC-checked probe), then dump RUNTIME with `dump_flash_mdb.py`.
- Run: `scripts/auto_dump_runtime.py --wait 1800`, then power-cycle.
- Output: `private/stock-runtime-<ts>/runtime.bin`. Log: `tmp/logs/auto_dump_runtime.log`.
- Notes: on 2026-10-08 every higher rate fell back to 115200. Superseded by the OpenWrt route.

### st1008_ramload.py
- Purpose: one-shot RAM load: relay off → daemon restart → relay on → catch stock prompt → `rtk network on` → light one cage → TFTP (byte count checked) → `go`/`bootm` → wait for the image's done marker → `boot_log_check`.
- Run via `./dev.py ramload uboot-mainline|openwrt|mainline-kernel|stock [--cage N] [--no-cycle] [--no-network]`.
- `ramload uboot-mainline --then openwrt|mainline-kernel`: ours runs `clocks fast` (CPU 1 GHz, SPI stock), then `bootm` of the std-magic copy of that image.
- Log: `tmp/logs/st1008_ramload.log`. Every wait has a console marker + stated cap; a stock banner mid-run = unexpected reset = FAIL.
- Measured 2026-10-10: power-off → mainline U-Boot prompt 18 s (catch 2.1 s, network on 7.9 s, TFTP 5.1 s incl. one 5 s first-block retransmit).

### boot_log_check.py
- Purpose: strict allowlist check of console boots (U-Boot, OpenWrt, mainline, stock). Every line must match a reviewed regex in `boot_log_allowlist.txt`; DENY-word lines (warning/error/failed/timed out/-Exxx/panic/Call Trace/loop signature …) fail unless the entry cites `known #NN`.
- Run: `scripts/boot_log_check.py [--boot -1 | --all] [--from-line N] [--show-ok]` (default: last boot in `private/serial/st1008-console.log`).
- Exit 0 clean, 1 UNKNOWN lines, 2 ERROR. Log: `tmp/logs/boot_log_check.log`.
- Notes: after a shell prompt only kernel-timestamped lines are checked (our own command output is skipped); U-Boot replies to `md`/`rtk i2c` skipped; stack-dump lines fold into their WARNING/Oops. Benign DENY lines: #28; OpenWrt driver gaps: #29. `own address as source` (bridge loop) always fails.

### switch_power.py
- Purpose: power-cycle the switch via its ESPHome relay (REST `switch/relay`).
- Run: `scripts/switch_power.py cycle|off|on [--gap 1.0]`. Log: `tmp/logs/switch_power.log`.
- Notes: the state read right after a command can lag (shows the old state); re-read before trusting it. Prefer separate `off` then `on` calls a few seconds apart: back-to-back off/on in the same second left the board half-reset.
- **After any power cut, restart `switch_console_daemon.py` before power-on**: the PL2303 RX URB stalls (`urb stopped: -32`) and the daemon keeps running deaf.

### storm_watch.py
- Purpose: watch a host NIC's rx broadcast+multicast rate (`ethtool -S`) and cut the switch relay (`switch_power.py off`) on a storm. Unicast/iperf ignored.
- Run: `scripts/storm_watch.py [--nic enp7s0] [--abs-pps 2000] [--duration 900] [--observe --hold 3]`.
- Log: `tmp/logs/storm_watch.log`.
- Notes: trip = max(abs, 20× 3 s baseline) for 2 samples (0.5 s). A loop through OpenWrt's default bridge ramps slowly (13k pps at ~+80 s) and hangs the CPU port (`Ring contention`) by ~+250 s.

### st1008_sfp_ddm.py
- Purpose: SFP ID EEPROM (`0x50`) dump + SFF-8472 decode, and live DDM (`0x51`: temp/Vcc/bias/TX/RX) from stock U-Boot `rtk i2c`, through the console daemon.
- Run (after `rtk network on`): `scripts/st1008_sfp_ddm.py probe`; `dump --dev <cage-1>`; `ddm --dev <cage-1> --intf 0 --sda <cage-1>`.
- Output: `private/sfp/<YYYYMMDD-HHMMSS>/cageN-*.bin`. Log: `tmp/logs/st1008_sfp_ddm.log`. Serial numbers shown (not sensitive here).
- Notes: batches `cmd; cmd; …` lines ≤200 chars (U-Boot rejects >256, UART drops input past ~240). DDM uses scratch dev 10 via `rtk i2c init hw 10 0 <cage-1> 8 0x51 0 0` (7-bit addr, intf 0). Read-only.

### mainline_uimage.py
- Purpose: wrap a mainline `vmlinux` + DTB into a uImage stock U-Boot boots: objcopy → append DTB (`MIPS_RAW_APPENDED_DTB`) → LZMA-alone (real size in header) → legacy header, OpenWrt RTL930x magic `0x93030000`. Load/entry read from the ELF.
- Run: `scripts/mainline_uimage.py --vmlinux <build>/vmlinux --dtb <build>/arch/mips/boot/dts/realtek/tplink-tl-st1008f-v2.dtb [--out tmp/tftp/mainline.bin]`, then `tftpboot 0x84f00000 mainline.bin; bootm 0x84f00000`.
- Log: `tmp/logs/mainline_uimage.log`.
- Notes: refuses kernel+DTB over 16 MiB (bootm limit). Stage-0 boots to the initramfs shell `st1008f-linux # ` (`mainline_initramfs.py`); GPIO21 watchdog node stays disabled (enabled, it resets the board at probe, #16, #18).

### ubnt_fw_unpack.py
- Purpose: split a Ubiquiti UBNT firmware `.bin` (e.g. UniFi `US.bcm5334x`) into PART payloads; decompress the uImage; extract embedded xz/gzip/LZMA-alone streams (built-in initramfs cpio).
- Run: `scripts/ubnt_fw_unpack.py <fw.bin> <out-dir>`; entropy map only: `scripts/ubnt_fw_unpack.py x x --entropy <file> [--block 0x400]`.
- Output: `<out>/<idx>-<name>.bin`, `.img` (decompressed uImage), `.<kind>@<off>` streams. Log: `tmp/logs/ubnt_fw_unpack.log`.
- Notes: LZMA-alone detection takes any lc/lp/pb (US.bcm5334x initramfs uses props `0x6d`, missed by a fixed `0x5d` magic). Unpack the cpio with `cpio -idm --no-absolute-filenames -D <empty dir>`.

## Static analysis

### st1008_uboot_funcmap.py
- Purpose: name SDK functions in the stock loader by aligning against the reyalo dms1250 `u-boot` ELF + `System.map` (string-xref and masked content-match).
- Run: `scripts/st1008_uboot_funcmap.py align` / `resolve dal_longan_sds_rxCali ...`
- Inputs: `ST1008_LOADER` (default `private/stock-loader-20261007/loader.bin`), `REALTEK_SRC` (default `private/reyalo-Realtek/sources`; a clone of `github.com/reyalo/Realtek`). Needs `readelf`. Log: `tmp/logs/st1008_uboot_funcmap.log`.

### mips_find_string_refs.py
- Purpose: find code/data references to strings in a raw MIPS32 BE image (pointer words + `lui`/`addiu`/`ori` pairs Ghidra misses).
- Run: `scripts/mips_find_string_refs.py private/stock-loader-20261007/loader.bin 0x83efaf80 "tx dis set"`
- Log: `tmp/logs/mips_find_string_refs.log`.

### diag_listener_audit.py
- Purpose: decide whether stock `/bin/diag` is a network agent (imports `bind`/`listen`/`accept`) or a console-only REPL, from its ELF dynamic-import table and strings. Static only; does not execute the (MIPS BE) target.
- Run: `scripts/diag_listener_audit.py private/stock-initramfs/bin/diag` (or set `DIAG_BIN`). Needs binutils (`readelf`, `nm`, `strings`).
- Log: `tmp/logs/diag_listener_audit.log`. If it reports a LISTENER, follow up with `ghidra/DiagSocketAudit.java`.

### extract_console_excerpts.py
- Purpose: cut the redacted `artifacts/` logs from the console log (fixed line ranges; MAC/SFP-serial/IP redaction; refuses on leaks).
- Run: `scripts/extract_console_excerpts.py --map <lan-ip>=<switch-ip> --map <host-ip>=<tftp-server-ip>`
- Log: `tmp/logs/extract_console_excerpts.log`.

### ghidra/TraceLoader.java, ghidra/DecompileSelected.java
- Purpose: Ghidra headless post-scripts. `TraceLoader`: decompile functions at given addresses (`addr` or `addr=exact_<name>` to force a function boundary). `DecompileSelected`: decompile functions by name.
- Run: `analyzeHeadless private/ghidra <project> -process loader.bin -postScript TraceLoader.java <out.c> <addr>[=exact_name] ...`
- Output: the `.c` file given as the first script argument (keep it in `private/ghidra/`; vendor-code decompilation is not published).

### vendor_nic_decompile.py, ghidra/DecompileMatching.java
- Purpose: Ghidra headless decompile of the TL-ST5008F v2 1.2.0 CPU-NIC code: `core` functions matching a regex (NIC, CPU port, rate limits, RX threads) + `rtcore.ko`/`ethdriver.ko`/`mgntPort.ko` in full. Feeds `docs/VENDOR-NIC-TUNING.md`.
- Run: `scripts/vendor_nic_decompile.py [st5008f-core|st5008f-core-extra|st5008f-rtcore|...]` (`core` takes ~3.5 min).
- Output: `private/ghidra/vendor-nic/<name>.c` (not published). Log: `tmp/logs/vendor_nic_decompile.log`.

### vendor_nic_values.py
- Purpose: find the RTL9300 NIC ring-size tables (tx[2] + rx[32] uint32) in vendor ELF data sections.
- Run: `scripts/vendor_nic_values.py <elf> ...`. Log: `tmp/logs/vendor_nic_values.log`.

### sdk_regdump.py
- Purpose: RTL9300 (longan) register offsets and field layouts from the GPL SDK tables (`rtk_longan_reg_list.c`, `rtk_longan_regField_list.c`). Also decodes a read value into fields. Feeds `docs/DATASHEET-AUDIT.md`.
- Run: `scripts/sdk_regdump.py '<name regex>' [--decode NAME=0xVALUE] [--fetch]`. The first run fetches the tables with `gh api` into `tmp/datasheet-audit/sdk/longan/`. Log: `tmp/logs/sdk_regdump.log`.

### ghidra/DumpBytes.java
- Purpose: print the memory-block map and raw bytes at given addresses of a loaded program (reads initialised `.data`/`.rodata` tables the decompiler shows only as `DAT_`).
- Run: `analyzeHeadless private/ghidra <proj> -process <bin> -noanalysis -readOnly -postScript DumpBytes.java <out.txt> <addr>:<nbytes> ...`
- Used for issue #8: `gpio_pin[] = {17,18,19}` and the `DAT_003576f0` first-pass flag in stock `rtk.ko` (project `stock-gpio17`, built with `-import <module> -postScript DecompileAll.java <out.c>`).

### ghidra/DiagSocketAudit.java
- Purpose: in `diag`, find and decompile the functions that call the socket-server API (`bind`/`listen`/`accept`/`dup2`/`execve`/`socket`) — the listener loop reveals the port, the config gate, and the `dup2(sock,…)`+`execve` shell handoff.
- Run: `analyzeHeadless private/ghidra <project> -process diag -postScript DiagSocketAudit.java <out.c> [import ...]`
- Output: the `.c` given as the first arg (keep it in `private/ghidra/`; vendor-code decompilation is not published). Untested against `diag` here — the binary lives in `private/`.

## Mainline U-Boot

### build_uboot_mainline.py
- Purpose: stage `uboot-port/` into pinned mainline U-Boot `v2026.07` (`tmp/u-boot-v2026.07`, override `$UBOOT_TREE`), patch the Kconfig/Makefile hooks idempotently, build stage 0 (RAM chainload) out-of-tree. Doc: [../docs/UBOOT-MAINLINE.md](../docs/UBOOT-MAINLINE.md).
- Run: `scripts/build_uboot_mainline.py [--clean] [--cross mips64-linux-gnu-]`
- Output: `tmp/tftp/uboot-mainline.{bin,elf}` (load `tftpboot 0x81000000 uboot-mainline.bin; go 0x81000000`), build dir `tmp/uboot-mainline-build`, log `tmp/logs/build_uboot_mainline.log`.
- Timeout: 6 s per `make` call (clean build measured 4 s, x1.5); expiry kills make and logs the elapsed time.
- Resets tracked files in the tree (`git checkout -- .`) before staging; the tree must be a throwaway clone.

### default_boot.py

- OpenWrt on 7.3 as default boot + recovery OpenWrt fallback (#73). `./dev.py default-boot check | test | status | install primary|recovery | revert --backup DIR`. Docs: [../docs/DEFAULT-BOOT.md](../docs/DEFAULT-BOOT.md), [../docs/DEFAULT-BOOT-OPS.md](../docs/DEFAULT-BOOT-OPS.md).
- `check` (host): uImage header + data CRC, slot fit, split-layout DTB (`recovery`, `bootrec@e000000`) inside each kernel; prints the flash-write plan.
- `test`: `ramload openwrt-ours` + shell checks (STP, uci, `/proc/mtd`, `devmem`, 7.3, dropbear). `status`: read-only at an OpenWrt shell.
- `install` / `revert`: flash writes; without `--i-have-owner-approval` they print the plan and exit 2.
- Timeouts: sysupgrade 390 s, `mtd write` recovery 290 s, revert 1600 s = W25Q256 datasheet worst erase/program x1.25. Log: `tmp/logs/default_boot.log`.

### mode_switch_map.py

- Mode switch (#8) and its boot policy (#46). `./dev.py mode-map live | boot --expect M1|M2|M3`.
- `live`: at our U-Boot prompt; logs `OWNER: slide the mode switch to Mx`, polls `rtk mode` every 0.5 s until the pins change and hold 3 polls; order M1 -> M2 -> M3 -> M1. PASS = 3 distinct patterns, decode == label.
- `boot`: owner sets the switch first; power-cycle with the saved chain. M1 -> flash OpenWrt (STP set); M2/M3 -> our prompt, `boot_mode=Mx`.
- Timeout: 180 s per owner move (request is relayed through chat). Log: `tmp/logs/mode_switch_map.log`.

### hw_probe.py

- Read-only presence probes of the RTL9303 blocks in [../docs/HARDWARE-INVENTORY.md](../docs/HARDWARE-INVENTORY.md) (#62): `md.l` of ID/ctrl registers only.
- Run: `./dev.py hw-probe [--label L] [--gated]` at our prompt (stock `RTL9300#` also works). Order: SoC core, switch core, then gated IP blocks (GDMA, crypto, SPI-NAND/ECC) only if their enable bit is set, or all with `--gated` (a read of a clock-gated block may hang: SPEC).
- SRAM data at `0xbf000000` read only while `CPU_SRAM_SEG0` holds the stock window (`0x1f000001`; `highmem map` clears it).
- Skipped: UART RBR/IIR/LSR/MSR, SPI SFDR (read side effects), status/W1C, MIB counters, latched link bits; list printed at the end.
- Timeout: 1 s per `md.l` (≤ 24 words ≈ 40 ms at 115200); a timeout or exception banner stops the run (console state unknown; recover with `./dev.py stock`).
- Output: Markdown table, `tmp/hw_probe-<label>.json` (saved per probe). Log: `tmp/logs/hw_probe.log`.

### hidden_sdk_scan.py

- Offline search for hidden/disabled hardware (#68, [../docs/HIDDEN-FEATURES.md](../docs/HIDDEN-FEATURES.md)). No hardware access.
- Inputs: GPL SDK clone (`github.com/reyalo/Realtek`, `sources/`) via `--sdk` or `REALTEK_SRC` (default `private/reyalo-Realtek/sources`); stock `rtk.ko`, ST5008F `core` and decompiles from `private/` when present.
- Reports: switch-core address holes, free table codes per access controller, unnamed bits per table entry, NAT-ish names, BIST memory list, longan vs mango features, named regs no SDK code uses, vendor reg/table lists vs GPL, decompile literal addresses outside the named map.
- Output: `tmp/hidden/sdk_scan.json`. Log: `tmp/logs/hidden_sdk_scan.log`.

### hidden_probe.py

- Read-only `md.l` probes for the candidates in HIDDEN-FEATURES.md (#68): bonding/eFuse status, clock gates, encap block, table-access ctrl, HSB/HSA/HSM snapshots, L3 lookup-test regs, SPG ctrl (#70), all 90 `DMY_REG*`.
- Run: `./dev.py hidden-probe [--label L] [--holes] [--alias] [--list]`. `--holes` samples the 44 unnamed holes (a word may be a clear-on-read counter); `--alias` reads outside the 64 KiB switch window (may bus-hang); `--list` prints the commands only.
- Timeout: 1 s per `md.l` (≤ 30 words ≈ 50 ms at 115200; reuses `hw_probe.md`); a timeout or exception stops the run (recover with `./dev.py stock`).
- Output: Markdown table, `tmp/hidden_probe-<label>.json`. Log: `tmp/logs/hidden_probe.log`.

### hidden_write_probe.py

- Owner-approved write probes (#68): `snapshot`/`diff` (whole 64 KiB switch window, read-only), `chipinfo`, `efuse` (read sequence only: CMD + ADDR, RWOP 0), `chipmode <n>`, `tables` (read command on free table codes, data regs pre-filled `0xA5A5A5A5`), `dmy` (dummy-bit r/w test).
- Writes only to an allowlist of volatile switch-core regs; refuses eFuse WDATA, RWOP=1, PLL/AFE 0xE200-0xE2FF. Each write journaled (addr, old, new, readback) and restored at the end.
- A free table code whose EXEC never clears locks that controller until power cycle: one code per boot (`--ctl CTRL_0 --codes 10`).
- Timeout: 1 s per console command (a 0x100-word `md.l` ≈ 0.32 s at 115200); expiry = hang, recover with `./dev.py stock`.
- Run: `./dev.py hidden-write-probe <cmd>` at our prompt (`ramload uboot-mainline --from-flash --stock-clocks`). Output `tmp/hidden/hwp-<cmd>-<label>.json`. Log: `tmp/logs/hidden_write_probe.log`.

### sfp_decode_host_test.py

- Builds the U-Boot SFP decoder (`uboot-port/board/tplink/tl-st1008f/sfp/`) on the host with shim headers.
- Run: `scripts/sfp_decode_host_test.py dump <a0.bin> [<a2.bin>]` (decode raw EEPROM dumps) or `selftest` (external-cal vectors and dBm vs double math).
- Log: `tmp/logs/sfp_decode_host_test.log`.

### udivdi3_host_test.py

- Runs our `uboot-port/arch/mips/lib/udivdi3.c` (replaces mainline's, #33) as a freestanding MIPS32 BE program under `qemu-mips-static`: 211 u64 `/` `%` cases vs Python; also shows mainline's `(long long, int)` signature seeing divisor 0.
- Run: `scripts/udivdi3_host_test.py`. Needs `mips64-linux-gnu-gcc`, `qemu-mips-static`. Log: `tmp/logs/udivdi3_host_test.log`.

### clock_calc.py

- Host-only RTL930x clock calculator; formulas and tables: [../docs/CLOCKS.md](../docs/CLOCKS.md).
- Run: `scripts/clock_calc.py decode <md.l dump>` (same decode as U-Boot `clocks`), `cpu-table`, `mem-table`, `cpu <MHz>` (`0xbb00e208/e210` values, VCO kept in 2400-3200 MHz), `dtr <MHz> [--die-mbit 4096]` (DTR0-2 from the stock bins), `ddr-bin <MHz>...` (675-800: PLL, DTR0-2, MR0/MR2 from the DRAM datasheet + SDK formulas; prints the C rows), `mr <DTR0 hex>` (MR words the stock SPL derives).
- Log: `tmp/logs/clock_calc.log`.

## Repo maintenance

### gh_issue_from_draft.py
- Purpose: create a GitHub issue from a Markdown draft; title = first `# ` line; relative links rewritten to absolute blob URLs (issues don't resolve relative links).
- Run: `scripts/gh_issue_from_draft.py tmp/issue-draft-<name>.md [--close] [--dry-run]` (needs an authenticated `gh`).
- Log: `tmp/logs/gh_issue_from_draft.log`.

## Historical Node helpers (scripts/node/)

Kept as used on 2026-10-07/08. New tooling is Python. Run from the repo root with Node ≥ 20; serial helpers need `SERIAL_PORT=/dev/serial/by-id/<adapter>` and nothing else on the port.

| Script | Purpose | Output |
|---|---|---|
| `decode_firmware.mjs` | Decode TP-Link SX/ST update BINs (DES-CBC, key/IV read from the GPL `DesDecode.c`); prints hashes and component bounds as JSON. `node --openssl-legacy-provider scripts/node/decode_firmware.mjs <DesDecode.c> <update.bin> <new-output.bin>` | decoded image (refuses to overwrite) |
| `serial_flash_backup.mjs` | Two complete `md.b` reads of the 32 MiB flash with target/host CRC32, compare, carve 7 partitions. `node scripts/node/serial_flash_backup.mjs <serial-port> <new-dir> [--loader-only]` | the given directory |
| `serial-live.mjs` | Receive-only capture at 38400 or 115200. `SERIAL_PORT=… node scripts/node/serial-live.mjs 115200` | `private/serial/live.log` |
| `boot-interrupt.mjs` | Wait for the autoboot prompt, send one Esc; optional `--fiber10g-port0` sends `rtk 10g 0 fiber10g` | `private/serial/live.log` |
| `serial-network-test.mjs` | Same-subnet ping / NIC-counter / `--init-test` / `--help-only` / `--inspect-phy` U-Boot tests; restores `ipaddr`/`serverip` afterwards. Needs `SWITCH_IP`, `HOST_IP` | `private/serial/*-20261007.log` |
| `ram-transfer.mjs` | `loady 0x82000000` + `sb --ymodem` of the initramfs (`IMAGE` env). Failed with `NAK on sector`; use TFTP | `private/serial/ram-transfer-<ts>.log` |
| `ymodem-send.mjs` | In-process YMODEM sender (same goal; same outcome) | `private/serial/ymodem-protocol-20261007.log` |

- These open the tty directly: stop the console daemon first.
- Timeouts inside them are the original values (not re-derived).

### diag_reverse_bundle.py
- Purpose: grepable static-analysis bundle for an ELF (default stock `diag`) — ELF header, dyn-syms, relocs, offset-tagged strings, and a net/shell import summary with MIPS o32 syscall numbers for a raw-syscall scan. Static only.
- Run: `scripts/diag_reverse_bundle.py [elf] [out_dir]` (default out `private/diag-analysis/<name>/`). Needs binutils.
- Log: `tmp/logs/diag_reverse_bundle.log`.

### ghidra/DiagNetScan.java
- Purpose: in a Realtek SDK ELF, scan for raw `syscall` sites (with the v0 o32 number) and thunk-aware callers of socket/bind/listen/accept/connect/system/dup2/execve, decompiled. Finds network code the libc PLT hides.
- Run: `analyzeHeadless private/ghidra <proj> -process <bin> -noanalysis -postScript DiagNetScan.java <out.c> [import ...]`
- Output: the `.c` first arg (keep in `private/ghidra/`; vendor decompilation not published).

### st1008_cpu_punt_probe.py
- Purpose: find the process that answers CPU-punted frames. Sends trapped-class frames (ARP/ICMP/LLDP/STP-BPDU/Realtek-0x8899) at the switch over one cabled port and logs every reply + unsolicited emission. ARP/ICMP reply = Linux kernel; any L2-protocol reply = an SDK responder (the sought interface). Non-destructive: secondary `ip addr add`, removed on exit. Raw AF_PACKET (needs root).
- Precondition: switch booted into STOCK firmware (rc up, eth0 configured); ONE port cabled to `<iface>` (cage-loop hazard).
- Run: `sudo scripts/st1008_cpu_punt_probe.py <iface> [--target 192.168.1.1] [--ip 192.168.1.2/24] [--listen 5]`
- Log: `tmp/logs/st1008_cpu_punt_probe.log`.

## Mainline port (issue #16)

Desk-only; no switch access. Needs `tmp/openwrt` (sparse clone of openwrt, `target/linux/realtek` + `target/linux/generic`), `tmp/linux.git` (blobless bare clone of torvalds/linux), `tmp/linux-v7.3` (shallow clone of `v7.3-rc6`) and a `mips64-linux-gnu-` cross gcc. Results: [../docs/MAINLINE-PORT.md](../docs/MAINLINE-PORT.md).

### mainline_inventory.py
- Purpose: compare OpenWrt `files-6.18` and version-tagged `patches-6.18` against a mainline ref (exists? first release? subject merged?).
- Run: `scripts/mainline_inventory.py [--ref v7.3-rc6]`
- Output: markdown tables on stdout and `tmp/logs/mainline_inventory.log`.

### mainline_patch_check.py
- Purpose: apply OpenWrt's realtek patches (+ generic phylink PCS series) in order onto a scratch copy of the mainline tree (strict, then fuzz 2, then fuzz 3), overlay `files-6.18`, optionally build with `make -k`.
- Run: `scripts/mainline_patch_check.py [--build]`; `--rebuild` skips patching and reruns the hand fixups + build. Delete `tmp/linux-fp` before a fresh patch run.
- Output: `tmp/logs/mainline_patch_check.log` (patch table, then make output), build tree `tmp/build-fp`.

### mainline_build_check.py
- Purpose: build the mainline kernel against `tmp/linux-v7.3`: OpenWrt realtek patches applied verbatim (`OWRT_VERBATIM`), driver files copied from `files-6.18` (`OWRT_FILES`), then `openwrt/patches/*.patch` (300-04..11: ours + forward-ports); `allnoconfig` + `mainline/st1008f-v2.config` (+ `st1008f-v2-smp.config` with `--smp`) + generated initramfs fragment. Checks `tmp/openwrt` is at the pinned OpenWrt commit.
- Run: `scripts/mainline_build_check.py [--dtb-only] [--apply-only] [--smp] [--jobs N]` (or `./dev.py build-kernel [...]`, which also wraps `tmp/tftp/mainline.bin`). Runs at nice 19, default `-j8` (owner limit).
- Output: `tmp/logs/mainline_build_check.log`, build tree `tmp/build-mips`; prints the `=y` count.
- Fails, listing them, if `olddefconfig` drops or changes any fragment line.
- Notes: `--out` must be absolute (relative paths resolve inside the kernel tree). Patch/file status table: [../docs/MAINLINE-PORT.md](../docs/MAINLINE-PORT.md).

### openwrt_patch_status.py
- Purpose: classify each OpenWrt patch against the 7.3 tree in series order: `upstream` (reverse-applies), `applies` (kept applied so series stack), `fails`. Resets the tree before and after.
- Run: `scripts/openwrt_patch_status.py [--dir tmp/openwrt/target/linux/generic/pending-6.18] [--glob '7*.patch'] [--out tmp/x.tsv]`.
- Output: `tmp/openwrt_patch_status.tsv`; log `tmp/logs/openwrt_patch_status.log`.
- Notes: `applies` can be a false positive (705 applies into another function; its line is already upstream). `fails` often means upstream in a different form; check the source.

### rteth_ftrace.py
- Purpose: ftrace `function_graph` timing of the CPU-port NIC path (`rteth_poll_rx`, `rteth_start_xmit`) under `nat_bench.py run` load on the mainline initramfs (#65, #67). Per (depth, function): calls, total, avg µs.
- Run: `./dev.py rteth-ftrace [--depth N] [--roots f,g] [--load "--secs 3 -P 4"]` after `nat-bench setup` + `mode`.
- `--count f,g`: plain function tracer on f,g only; calls per eth0 RX packet by (function, caller). Not yet run on hardware (#27).
- Notes: tracer overhead inflates every number (all functions keep the mcount hook); use the split, not the absolute µs. Depth >= 2 overruns the buffer: per-call averages stay valid. Raw: `tmp/rteth_ftrace/`; log `tmp/logs/rteth_ftrace.log`.

### mem_stress.py
- Purpose: RAM check from the mainline initramfs shell (#27): meminfo (MemTotal floor, HighTotal), tmpfs of MemFree - 48 MiB filled with copies of a 16 MiB urandom seed, md5 of every copy, 2 passes; dmesg Oops/BUG/OOM scan.
- Run: `./dev.py mem-stress [--passes N] [--min-total-kb K]` at the `st1008f-linux #` prompt (`--min-total-kb 240000` for a `--no-highmem` kernel).
- Notes: tmpfs pages are highmem-first, so the run covers bank 1 (HighFree ~0 when full). Log `tmp/logs/mem_stress.log`.

### nic_path_bench.py
- Purpose: before/after suite for rteth driver changes on the mainline 7.3 kernel (#60, #65).
- Run: `./dev.py nic-bench boot [--no-ramload]`; `./dev.py nic-bench run --tag T [--runs 3] [--only L ...]`; `./dev.py nic-bench table [T ...]`.
- Suite (NAT + flowtable): TCP P4; UDP 1400 B at 600/700/900 Mbit/s offered (overload curve); UDP 64 B at 100 Mbit/s offered. Rows in `tmp/logs/nat_bench.jsonl` (label `nic-*`, tag T); qdisc drops per test in `tmp/logs/nic_path_bench.jsonl`; log `tmp/logs/nic_path_bench.log`.
- Notes: house LAN, one cage; run `./dev.py storm-watch` alongside. `fwd kpps` = eth0 TX pps.

### patch_from_tree.py
- Purpose: regenerate the diff body of a patch on existing files (e.g. `300-12` on `rtl838x_eth.[ch]`) from the edited `tmp/linux-v7.3`; keeps the patch header.
- Run: copy the files as the earlier patches leave them to an orig dir first, then `python3 scripts/patch_from_tree.py openwrt/patches/<patch> --orig-dir <dir> <tree paths>`. Log: `tmp/logs/patch_from_tree.log`.

### patch_refresh.py
- Purpose: rewrite the new-file hunks of an `openwrt/patches/*.patch` from the patched tree (`tmp/linux-v7.3`) after editing a file the patch creates (e.g. the 300-06 mode-switch driver).
- Run: `python3 scripts/patch_refresh.py openwrt/patches/<patch> [--tree DIR]`. Log: `tmp/logs/patch_refresh.log`.

### mainline_initramfs.py
- Purpose: initramfs: static BusyBox (`sources/busybox/busybox-mips`, sha256-checked) + `/init` -> shell `st1008f-linux # ` on the console, plus NAT test tools from `initramfs_tools.py` and `/usr/sbin/port-up` (one cage at a time). Called by `mainline_build_check.py`.
- Output: `tmp/initramfs/st1008f-initramfs.cpio.xz` (deterministic newc, xz CRC32), `tmp/initramfs/initramfs.config`. Log: `tmp/logs/mainline_initramfs.log`.
- Notes: `/init` configures no network; all ports stay down and unbridged.

### initramfs_tools.py
- Purpose: `nft`, `iperf3`, `ethtool`, `tc`, `ip` for the initramfs: pinned OpenWrt 24.10.7 `mips_24kc` packages (musl, dynamic) + dependency closure; sha256 from the feed index / `sha256sums`.
- Run: called by `mainline_initramfs.py`; standalone lists the staged files. Missing `.ipk` are fetched with `playwrong --pdf URL -o PATH` into `sources/openwrt-24.10.7-ipk/` (gitignored, manifest `sources/README.md`).
- Log: `tmp/logs/initramfs_tools.log`.

### spi_dirmap_test.py
- Purpose: A/B SPI-NOR reads under the mainline kernel (#61): per `dirmap` mode (0 PIO, 2 cached window, 1 uncached) time `dd` of a partition and md5sum it.
- Run: `./dev.py ramload mainline-kernel`, then `./dev.py spi-dirmap-test [--part firmware] [--modes 0,2,1]`.
- PASS = dirmap active at probe, equal md5 in every mode, cached faster than PIO. Read-only. Log: `tmp/logs/spi_dirmap_test.log`.

- `rtk_parity.py` + `rtk_parity_cmds.json`: run the `rtk` command list on stock and on our U-Boot and diff (`./dev.py rtk-parity`; see docs/RTK-COMMANDS.md). Never sends flash writers. Both sides run `rtk network on` between the pre and post phases.

### sds_tables_gen.py
- Purpose: extract the stock 10GBASE-R SerDes construct lists (even/odd SerDes) from `private/stock-loader-20261007/loader.bin` into `uboot-port/board/tplink/tl-st1008f/rtk_sds_tables.h`; fails if a list length differs (120 / 106).
- Run: `python3 scripts/sds_tables_gen.py`. Log: `tmp/logs/sds_tables_gen.log`.

### stock_led_profile.py
- Purpose: dump the LED part of a hw profile compiled into the stock loader (profile list `0x83f9348c`): per-port LED set / layout, `led_if_sel`, `led_active`, `led_definition_set[4][5]`. Source of the `led_config()` values in `rtk_net.c` (#9).
- Run: `python3 scripts/stock_led_profile.py private/stock-loader-20261007/loader.bin [PROFILE]` (default `RTL9303_8XGE`). Log: `tmp/logs/stock_led_profile.log`.

### serial_speed_test.py

- Purpose: console UART baud ladder at the mainline prompt (#32). One self-restoring command line per divisor (`mw.b` divisor, `md.b` 16 KiB, restore 115200); pass = byte-exact vs a 115200 baseline.
- Host side: clone PL2303HX runs faster than requested; the script sweeps the requested rate down from the last good factor.
- Run: `./dev.py serial-speed [divisor ...]`. Log: `tmp/logs/serial_speed_test.log`.

### cpu_clock_step.py

- Purpose: CPU PLL ladder at the mainline prompt (#38): `clocks set cpu` per value, then `sleep 5` vs host clock = real CPU rate (CP0 Count = CPU/2). Stops at the first fail or hang.
- Run: `./dev.py cpu-clock <e210> <e208> [e208 ...]` (values: `scripts/clock_calc.py cpu <MHz>`). Log: `tmp/logs/cpu_clock_step.log`.

### mem_clock_step.py

- Purpose: DDR3 clock ladder at the mainline prompt (#39): `clocks set mem <MHz> force` per bin (self-refresh, MEM PLL, DTRs from SRAM), then `clocks` decode, `crc32` + `md` of a 16 MiB region copied before the first change (contents kept), `highmem test` (256 MiB). Stops at the first fail or hang.
- Run: `./dev.py mem-clock 600 650 [--nosr]` (600 first = stock values through the new sequence); above 650: `./dev.py mem-clock 650 675 700 725 750 775 800 --nosr` (MRS bins, CPU 1000 first). Log: `tmp/logs/mem_clock_step.log`.

### mem_tap_sweep.py

- Purpose: isolate a failing DDR bin (#48 #49 #56): one `clocks set mem <MHz> nosr probe ... force` per setting (change, canary at the new clock, always revert), logs canary bad / 1024, XOR of bad bits, first bad word.
- Modes: `field` (PHY register fields = each value), `dqshift` (all DQ read taps + n), `mpcr` (SDK PLL rows), `once` (`--extra` only). Stops on `probe FAIL` or a hang.
- Run: `./dev.py mem-tap-sweep field --mhz 675 --reg b8001050 --fields 28:24,20:16 --values 0-31`; recipes in [../docs/CLOCKS-OPS.md](../docs/CLOCKS-OPS.md). Log: `tmp/logs/mem_tap_sweep.log`; table `tmp/mem_tap_sweep-<YYYYMMDD-HHMMSS>.csv`.

### uimage_std_magic.py

- Purpose: copy an OpenWrt Realtek-magic (`0x93030000`) uImage with the standard magic `0x27051956` for mainline `bootm`; header CRC recomputed, payload untouched.
- Run: called by `./dev.py ramload uboot-mainline --then openwrt|mainline-kernel [--cpu E208]`. Log: `tmp/logs/uimage_std_magic.log`.

### openwrt_flash_stp.py

- Purpose: from RAM-booted OpenWrt, mount the flash overlay (`rootfs_data`) and set `network.switch.stp=1` in the flash OpenWrt's config (#43). Refuses if the overlay has no `etc/config/network`.
- Run: `./dev.py ramload openwrt` then `./dev.py openwrt-flash-stp`. Log: `tmp/logs/openwrt_flash_stp.log`.

### flash_openwrt_watch.py

- Purpose: boot the flash OpenWrt as an unattended power-up would (autoboot caught, no `rtk network on`, `boota`), then sample uptime (reboot detection), `stp_state`, lan* STP port states, SoC temperature (#43).
- Run: `./dev.py flash-openwrt-watch [--minutes 10] [--every 30] [--attach]` with `./dev.py storm-watch` alongside. Log: `tmp/logs/flash_openwrt_watch.log`.


- `sdk_leftovers_scan.py`: offline scan of Realtek SDK trees + stock/managed firmware for debug/test/disabled features; output `tmp/sdk_leftovers/scan.json`, log `tmp/logs/sdk_leftovers_scan.log`; `--decompile` adds a Ghidra pass (private/). Results: docs/SDK-LEFTOVERS.md, #74.
