# CLAUDE.md — awto-tl-st1008f

Public repo: never commit anything from `private/`; no host paths/secrets in tracked files. IPs, MACs, SFP serials OK (owner 2026-10-10: meaningless here) — don't redact.

IP registry blocks (`awto-dan/docs/network/ip-registry.toml`): `st1008f-1`=`.48-.55`, `st1008f-2`=`.56-.63`. Static: `/24`, gw/DNS `.254`, domain `dnt.com.au`.

## Units (owner 2026-10-12; `scripts/boards.py`)
- **sw1 = st1008f-1**: in-service house switch, mgmt `.48`, no relay, no serial. Never power-cycle/ramload; network checks only (`./dev.py switch-check`). Reflash only on owner request (2026-10-13): `./dev.py openwrt-sysupgrade-ssh --ip 192.168.25.48` (keeps config, backup first).
- **sw2 = st1008f-2**: bench unit on relay (`.49`) + serial console; all hardware flows target it. Bench mgmt `.56`.

## Speed sweeps (owner 2026-10-13)
- Range = stock (known good) → fastest programmable setting. Binary search from midpoint; pass→higher, fail/hang→lower; stop at fastest **viable** = passes ONE quick test. No repeat runs (n=5/n=20) during sweep.
- One powered session (`clocks-cycle --session`): passing points need no power-cycle; power-cycle only after fail/hang.
- Overview table per domain (CPU, SRAM, LX, DDR, SPI) first, then discuss with owner before repeats or making a setting default.

## Entry point `./dev.py`
- All hardware/build/check flows via `./dev.py` (`describe` = JSON command list). Don't hand-type console sequences; extend `dev.py`/scripts.
- `./dev.py ramload uboot-mainline|openwrt|mainline-kernel` = power-cycle → stock prompt → `rtk network on` → one cage → TFTP (size-checked) → run → `boot_log_check`. `./dev.py stock` stops at stock prompt.
- Every boot judged by `./dev.py check-log` (strict allowlist `scripts/boot_log_allowlist.txt`); a new warning fails until reviewed + tied to an issue.

## Layout
- `README.md` — 10G-in-U-Boot recipe, backup, workflow, status.
- `docs/` — reference (present tense). Narrative/dead ends only in `docs/HISTORY.md`.
- `artifacts/` — redacted device captures; regen console excerpts with `scripts/extract_console_excerpts.py`.
- `scripts/` — tooling, see `scripts/README.md`. `scripts/node/` = historical Node helpers; `scripts/ghidra/` = Ghidra scripts.
- `private/` (gitignored) — flash dumps, vendor firmware, serial logs, Ghidra projects. Index `private/README.md`.
- `tmp/` (gitignored) — logs, TFTP root (`tmp/tftp/`), issue drafts.

## Console
- `scripts/switch_console_daemon.py` is the only UART owner. Drive via `scripts/switch_console.py`; never open the tty with `tio`/`minicom` while the daemon runs.
- Log `private/serial/st1008-console.log`. Daemon lets autoboot run (policy `pass`, unattended power-up boots OpenWrt); `ramload`/`stock` restart it with `hold`. `dev.py` resets policy to `pass` after every console flow (#133).
- Reboot sw2 in software (owner 2026-10-13): `reboot` from Linux, `reset` from U-Boot. Every flow goes through `st1008_ramload.restart_board()`; relay power-cycle is fallback only when no prompt answers / no stock banner follows, or a board doesn't respond within a bounded wait (logged). Warm resets come back by themselves (#105).
- Power cut stalls PL2303 RX (`urb stopped: -32`): restart daemon before power-on (`restart_board` does it). Manual relay `./dev.py power on|off`.
- `ramload uboot-mainline --fast` leaves board+daemon at 10.94 MBd; a daemon restart drops host to 115200 (board stays fast until power-off).
- On-demand console speed: `./dev.py console-speed [921600|115200]` (our U-Boot or Linux); `restart_board` follows its state file.
- Never type ahead during `rtk network on` (~8 s): input dropped/garbled (no flow control). Lines >256 chars rejected; input past ~240 chars drops.

## Hazards
- **Cage loop:** two cages to same switch, both lasers on = broadcast storm. Light one cage only (`rtk i2c write 8 1 0xfe`); unplug other fibres before `bootm` OpenWrt.
  - **Real incident 2026-10-10:** house LAN intermittently down from 15:16+11:00, SG2008P Gi1/0/6 `OSW_DET_LOOP`+`OSW_PB` ~20x over 20 h, dropping TrueNAS/HASS/OC200/selwyn each time. First alert 9 min after the 1000 MHz overclock commit; flash held OpenWrt 25.12.4 so every reboot re-bridged. awto-terminal#56. Flash OpenWrt has bridge STP saved, verified loop-safe at boot + steady state (#43); the 20 h traces to a RAM-loaded OpenWrt without STP.
- **sw2 cage loops (owner 2026-10-13, #110):** 3↔4 (DAC) and 7↔8 (fibre); `st1008f-linkcheck` keeps looped cages out of the bridge at every OpenWrt boot, STP is the second layer (docs/MAINLINE-NET-OPS.md).
- Cages 3↔7 not cabled (owner 2026-10-11) (superseded on sw2 by loops above). Re-cabling with GLC-T modules (ignore TX-disable) = in-switch loop under OpenWrt; needs bridge STP (#19).
- Bridge STP stays on (fibre cage loops), forward_delay 2 s: ports forward ~4 s after STP on, not 16 s.
- Storm guard automatic: every `./dev.py` hardware command starts one singleton `storm_watch.py --guard` (1 s ethtool-ioctl sampling, exits 10 min after last dev.py). Never start storm-watch by hand.
- Flash writes (owner 2026-10-12): allowed without asking EXCEPT the stock U-Boot area `0x0`-`0xDFFFF` (`LOADER`/`u-boot`), never written. `u-boot-env` changes only via `./dev.py uboot-chain-env apply|revert`. Writable: `jffs2-log` (our U-Boot), `jffs2-cfg`, `firmware`, the planned `recovery`. Banned at stock prompt: `saveenv` outside that flow, `savesys`, `setsys`, `upgrade*`, `*force`, `flerase`. OpenWrt `uci commit` fine.
  - LOADER gate: U-Boot driver (refuses 0x0-0xFFFFF), DTS `read-only` (mainline+OpenWrt), `scripts/flash_guard.py` (flows + every console line via Console and daemon) (#81).
- **Power-up chain (#105, #46):** stock U-Boot → saved `bootcmd` CRC-checks the 512 KiB slot in `jffs2-log` (mismatch → stock `boota`, flash OpenWrt) → ours → 2 s window, stopped by ESC only (`./dev.py uboot-chain-env prompt`) → M1/M2 stock clocks, M3 the `st1008f_turbo` env profile (`uboot-chain-env turbo`) → A/B slot from `bootstate` (trial gets 2 unconfirmed boots then the good slot; no record = slot a) → `bootm` slot a `0xb4300000` / b `0xb5180000` → flash OpenWrt.
  - A/B (#117, owner 2026-10-14): `firmware_a` 0x300000 + `firmware_b` 0x1180000, 14.5 MiB each, per-slot overlay; sysupgrade writes the idle slot. Images compat 2.0: a 1.0 (single 29 MiB `firmware`) image must never be flashed. `st1008f-slot` on the box. docs/DEFAULT-BOOT.md#ab-slots.
  - Daemon still catches stock's countdown, so `ramload` flows unchanged. Undo `./dev.py uboot-chain-env revert`. docs/DEFAULT-BOOT.md#power-up-chain.
- Never run fast SPI (above stock 25.5 MHz) when Linux will read flash (#50): 122.5 MHz corrupts bulk reads; 102.1 MHz passed a bulk md5 but JFFS2 overlay reads failed CRC (config fell back to 192.168.1.1). Fast SPI = U-Boot-only sessions.
- `rtk network on` once per boot, before any GPIO/I2C `rtk` command (before it they hang the console; recover with `./dev.py stock`).
- GPIO21 low = board reset (stock `switch_reset()`); never drive it low from new code (mainline gpio-wdt node disabled for this reason).
