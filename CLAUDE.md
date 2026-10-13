# CLAUDE.md

- Follow the user's global agent rules (terse docs, scripts in `./scripts/` in Python, logs in `./tmp/logs/`, ISO 8601, aggressive timeouts).
- Public repo: never commit anything from `private/`; no host paths or secrets in tracked files. IPs, MACs and SFP serials are fine (owner decision 2026-10-10: meaningless here) — do not redact them.
- **House LAN IPs come from the registry:** `awto-dan` repo (private, clone alongside this one) -> `docs/network/ip-registry.toml`, rules in `docs/network/README.md`. Blocks `st1008f-1` = `.48-.55`, `st1008f-2` = `.56-.63`. Never ping-scan for a free IP; never static inside the DHCP pool `.100-.179`. Static values: `/24`, gateway/DNS `.254`, domain `dnt.com.au`.

## Units (owner, 2026-10-12; `scripts/boards.py`)

- **sw1 = st1008f-1**: in service as a house switch, mgmt `.48`, no relay, no serial. Never power-cycle, ramload or flash it; network checks only (`./dev.py switch-check`).
- **sw2 = st1008f-2**: bench unit on the relay (`.49`) and the serial console; every hardware flow targets it. Bench mgmt `.56`.

## Speed sweeps (owner, 2026-10-13)

- Range = stock (known good) to the fastest setting the hardware can be programmed to. Binary search: start at the midpoint; pass → go higher, fail/hang → go lower; stop at the fastest **viable** point = passes ONE quick test. No repeat runs (n=5/n=20) during the sweep.
- Run sweeps in one powered session (`clocks-cycle --session`): passing points need no power-cycle; power-cycle only after a fail or hang.
- Overview table per domain (CPU, SRAM, LX, DDR, SPI) first, then discuss with the owner before repeats or making a setting the default.

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
- Log: `private/serial/st1008-console.log`. The daemon lets autoboot run (policy `pass`, unattended power-up boots to OpenWrt); `ramload`/`stock` flows restart it with `hold`.
- Reboot sw2 in software (owner, 2026-10-13): `reboot` from Linux, `reset` from U-Boot. Every flow goes through `st1008_ramload.restart_board()`; the relay power cycle is only its fallback when no prompt answers or no stock banner follows (logged).
- A power cut stalls the PL2303 RX (`urb stopped: -32`): restart the daemon before power-on (`restart_board` does it). Manual relay: `./dev.py power on|off`.
- **Reboot in software, not by power-cycling** (owner, 2026-10-13): `reboot` from Linux, `reset` from U-Boot. The relay is only for a board that doesn't respond within a bounded wait (logged reason). Warm resets come back by themselves (#105).
- `ramload uboot-mainline --fast` leaves board + daemon at 10.94 MBd; a daemon restart drops the host back to 115200 (board stays fast until power-off).
- On-demand console speed: `./dev.py console-speed [921600|115200]` (our U-Boot or Linux); `restart_board` follows its state file.
- Never type ahead during `rtk network on` (~8 s): input is dropped/garbled (no flow control). Lines >256 chars are rejected; input past ~240 chars drops.

## Hazards

- **Cage loop:** two cages to the same switch with both lasers on = broadcast storm. Light one cage only (`rtk i2c write 8 1 0xfe`); unplug other fibres before `bootm` OpenWrt.
  - **Happened for real 2026-10-10:** house LAN down intermittently from 15:16+11:00, SG2008P Gi1/0/6 `OSW_DET_LOOP`+`OSW_PB` ~20x over 20 h, dropping TrueNAS/HASS/OC200/selwyn each time. First alert 9 min after the 1000 MHz overclock commit; flash held OpenWrt 25.12.4, so every reboot re-bridged. Tracked awto-terminal#56. Flash OpenWrt has bridge STP saved and was verified loop-safe at boot and steady state (#43); the 20 h of alerts trace to a RAM-loaded OpenWrt without STP.
- **sw2 cage loops (owner, 2026-10-13, #110):** 3 ↔ 4 (DAC) and 7 ↔ 8 (fibre); `st1008f-linkcheck` keeps looped cages out of the bridge at every OpenWrt boot, STP is the second layer (docs/MAINLINE-NET-OPS.md).
- Cages 3 ↔ 7 are not cabled (owner, 2026-10-11). (superseded on sw2 by the loops above) Cabling them again with GLC-T modules (which ignore TX-disable) = in-switch loop under OpenWrt; needs bridge STP (#19).
- Bridge STP stays on (fibre cage loops), forward_delay 2 s: ports forward ~4 s after STP on, not 16 s.
- Storm guard is automatic: every `./dev.py` hardware command starts one singleton `storm_watch.py --guard` (1 s ethtool-ioctl sampling, exits 10 min after the last dev.py). Never start storm-watch by hand; not a per-task decision.
- Flash writes (owner, 2026-10-12): allowed without asking EXCEPT the stock U-Boot area `0x0`-`0xDFFFF` (`LOADER`/`u-boot`), which is never written. `u-boot-env` changes only via `./dev.py uboot-chain-env apply|revert`. Writable: `jffs2-log` (our U-Boot), `jffs2-cfg`, `firmware`, the planned `recovery` partition. Still banned at the stock prompt: `saveenv` outside that flow, `savesys`, `setsys`, `upgrade*`, `*force`, `flerase`. OpenWrt `uci commit` fine.
  - LOADER gate enforced by: U-Boot driver (refuses 0x0-0xFFFFF), DTS `read-only` (mainline + OpenWrt), `scripts/flash_guard.py` (flows + every console line via Console and daemon) (#81).
- **Power-up chain (#105, #46):** stock U-Boot → saved `bootcmd` CRC-checks the 512 KiB slot in `jffs2-log` (mismatch → stock `boota`, flash OpenWrt) → ours → 2 s window, stopped by ESC only (`./dev.py uboot-chain-env prompt`) → M1/M2 stock clocks, M3 the `st1008f_turbo` env profile (`uboot-chain-env turbo`) → `bootm 0xb4300000` → flash OpenWrt.
  - The daemon still catches stock's countdown, so `ramload` flows are unchanged. Undo: `./dev.py uboot-chain-env revert`. Details: [docs/DEFAULT-BOOT.md](docs/DEFAULT-BOOT.md#power-up-chain).
- Never run fast SPI (above stock 25.5 MHz) when Linux will read flash (#50): 122.5 MHz corrupts bulk reads; 102.1 MHz passed a bulk md5 but JFFS2 overlay reads failed CRC (config fell back to 192.168.1.1). Fast SPI = U-Boot-only sessions.
- `rtk network on` once per boot, before any GPIO/I2C `rtk` command (before it they hang the console; recover with `./dev.py stock`).
- GPIO21 low = board reset (stock `switch_reset()`); never drive it low from new code (mainline gpio-wdt node is disabled for this reason).
