# CLAUDE.md

- Follow the user's global agent rules (terse docs, scripts in `./scripts/` in Python, logs in `./tmp/logs/`, ISO 8601, aggressive timeouts).
- Public repo: never commit anything from `private/`; no host paths or secrets in tracked files. IPs, MACs and SFP serials are fine (owner decision 2026-10-10: meaningless here) — do not redact them.

## Entry point: `./dev.py`

- Every hardware, build and check flow goes through `./dev.py` (`./dev.py describe` = JSON command list). Do not hand-type console sequences; extend `dev.py` / its scripts instead.
- `./dev.py ramload uboot-mainline|openwrt|mainline-kernel` = power-cycle → stock prompt → `rtk network on` → one cage → TFTP (size-checked) → run → `boot_log_check`. `./dev.py stock` stops at the stock prompt.
- Every boot is judged by `./dev.py check-log` (strict allowlist, `scripts/boot_log_allowlist.txt`); a new warning fails until reviewed and tied to an issue.

## Layout

- `README.md` — 10G-in-U-Boot recipe, backup, workflow, status.
- `docs/` — reference docs (present tense). Narrative and dead ends go only in `docs/HISTORY.md`.
- `artifacts/` — redacted captures from the device; regenerate console excerpts with `scripts/extract_console_excerpts.py`.
- `scripts/` — tooling, documented in `scripts/README.md`. `scripts/node/` = historical Node helpers; `scripts/ghidra/` = Ghidra scripts.
- `private/` (gitignored) — flash dumps, vendor firmware, serial logs, Ghidra projects. Index: `private/README.md`.
- `tmp/` (gitignored) — logs, TFTP root (`tmp/tftp/`), issue drafts.

## Console

- `scripts/switch_console_daemon.py` is the only owner of the UART. Drive the switch with `scripts/switch_console.py`; never open the tty with `tio`/`minicom` while the daemon runs.
- Log: `private/serial/st1008-console.log`. The daemon auto-catches autoboot (policy `hold`).
- A power cut stalls the PL2303 RX (`urb stopped: -32`): restart the daemon before power-on (`./dev.py stock` / `ramload` do it). Power via the relay: `./dev.py power on|off`.
- `ramload uboot-mainline --fast` leaves board + daemon at 10.94 MBd; a daemon restart drops the host back to 115200 (board stays fast until power-off).
- Never type ahead during `rtk network on` (~8 s): input is dropped/garbled (no flow control). Lines >256 chars are rejected; input past ~240 chars drops.

## Hazards

- **Cage loop:** two cages to the same switch with both lasers on = broadcast storm. Light one cage only (`rtk i2c write 8 1 0xfe`); unplug other fibres before `bootm` OpenWrt.
- **Copper loopback (2026-10-10): cages 3 ↔ 7 are cabled to each other (two GLC-T 1000BASE-T).** GLC-T ignores TX-disable (A0 options = 0), so lasers cannot stop it. Stock U-Boot sets cages to 10G (no 1G link); OpenWrt brings lan3-7 up as SGMII → in-switch loop: never boot OpenWrt there without bridge STP (#19). Use it as the Ethernet self-test path (TX cage 3, RX cage 7).
- No flash writes: no `saveenv`, `savesys`, `setsys`, `upgrade*`, `*force`, `flerase`, `sf write/erase/update`.
- `rtk network on` once per boot, before any GPIO/I2C `rtk` command (before it they hang the console; recover with `./dev.py stock`).
- GPIO21 low = board reset (stock `switch_reset()`); never drive it low from new code (mainline gpio-wdt node is disabled for this reason).
