# CLAUDE.md

- Follow the user's global agent rules (terse docs, scripts in `./scripts/` in Python, logs in `./tmp/logs/`, ISO 8601, aggressive timeouts).
- Public repo: never commit anything from `private/`; no host paths or secrets in tracked files. IPs, MACs and SFP serials are fine (owner decision 2026-10-10: meaningless here) — do not redact them.
- **House LAN IPs come from the registry:** `awto-dan` repo (private, clone alongside this one) -> `docs/network/ip-registry.toml`, rules in `docs/network/README.md`. Blocks `st1008f-1` = `.48-.55`, `st1008f-2` = `.56-.63`. Never ping-scan for a free IP; never static inside the DHCP pool `.100-.179`. Static values: `/24`, gateway/DNS `.254`, domain `dnt.com.au`.

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
  - **Happened for real 2026-10-10:** house LAN down intermittently from 15:16+11:00, SG2008P Gi1/0/6 `OSW_DET_LOOP`+`OSW_PB` ~20x over 20 h, dropping TrueNAS/HASS/OC200/selwyn each time. First alert 9 min after the 1000 MHz overclock commit; flash held OpenWrt 25.12.4, so every reboot re-bridged. Tracked awto-terminal#56. Flash OpenWrt has bridge STP saved and was verified loop-safe at boot and steady state (#43); the 20 h of alerts trace to a RAM-loaded OpenWrt without STP.
- **Copper loopback (2026-10-10): cages 3 ↔ 7 are cabled to each other (two GLC-T 1000BASE-T).** GLC-T ignores TX-disable (A0 options = 0), so lasers cannot stop it. Stock U-Boot sets cages to 10G (no 1G link); OpenWrt brings lan3-7 up as SGMII → in-switch loop: never boot OpenWrt there without bridge STP (#19). Use it as the Ethernet self-test path (TX cage 3, RX cage 7).
- No flash writes: no `saveenv`, `savesys`, `setsys`, `upgrade*`, `*force`, `flerase`, `sf write/erase/update`. Owner-approved exceptions (2026-10-11, #47): `./dev.py uboot-chain-install` (our U-Boot → `jffs2-log`) and `./dev.py uboot-chain-env apply|revert` (stock `bootcmd`). OpenWrt's own config writes (`uci commit`) are fine.
- **Power-up chain (2026-10-11):** stock U-Boot → saved `bootcmd` copies our U-Boot from flash `0x200000` → ours autoboots (`clocks fast` = CPU 1 GHz; `bootm 0xb4300000`) → flash OpenWrt. Any byte on the console during our 1 s countdown stops it. The daemon still catches stock's countdown, so `ramload` flows are unchanged. Undo: `./dev.py uboot-chain-env revert`.
- Never run fast SPI (`clocks set`/SFCR above stock) when Linux will read flash: SQUASHFS errors at 122.5 MHz (#50).
- `rtk network on` once per boot, before any GPIO/I2C `rtk` command (before it they hang the console; recover with `./dev.py stock`).
- GPIO21 low = board reset (stock `switch_reset()`); never drive it low from new code (mainline gpio-wdt node is disabled for this reason).
