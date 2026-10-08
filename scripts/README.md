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

## Static analysis

### st1008_uboot_funcmap.py
- Purpose: name SDK functions in the stock loader by aligning against the reyalo dms1250 `u-boot` ELF + `System.map` (string-xref and masked content-match).
- Run: `scripts/st1008_uboot_funcmap.py align` / `resolve dal_longan_sds_rxCali ...`
- Inputs: `ST1008_LOADER` (default `private/stock-loader-20261007/loader.bin`), `REALTEK_SRC` (default `private/reyalo-Realtek/sources`; a clone of `github.com/reyalo/Realtek`). Needs `readelf`. Log: `tmp/logs/st1008_uboot_funcmap.log`.

### mips_find_string_refs.py
- Purpose: find code/data references to strings in a raw MIPS32 BE image (pointer words + `lui`/`addiu`/`ori` pairs Ghidra misses).
- Run: `scripts/mips_find_string_refs.py private/stock-loader-20261007/loader.bin 0x83efaf80 "tx dis set"`
- Log: `tmp/logs/mips_find_string_refs.log`.

### extract_console_excerpts.py
- Purpose: cut the redacted `artifacts/` logs from the console log (fixed line ranges; MAC/SFP-serial/IP redaction; refuses on leaks).
- Run: `scripts/extract_console_excerpts.py --map <lan-ip>=<switch-ip> --map <host-ip>=<tftp-server-ip>`
- Log: `tmp/logs/extract_console_excerpts.log`.

### ghidra/TraceLoader.java, ghidra/DecompileSelected.java
- Purpose: Ghidra headless post-scripts. `TraceLoader`: decompile functions at given addresses (`addr` or `addr=exact_<name>` to force a function boundary). `DecompileSelected`: decompile functions by name.
- Run: `analyzeHeadless private/ghidra <project> -process loader.bin -postScript TraceLoader.java <out.c> <addr>[=exact_name] ...`
- Output: the `.c` file given as the first script argument (keep it in `private/ghidra/`; vendor-code decompilation is not published).

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
