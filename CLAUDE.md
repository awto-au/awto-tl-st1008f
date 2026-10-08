# CLAUDE.md

- Follow the user's global agent rules (terse docs, scripts in `./scripts/` in Python, logs in `./tmp/logs/`, ISO 8601, aggressive timeouts).
- Public repo: never commit anything from `private/`; no host paths, secrets, MACs, SFP serials or house-LAN details in tracked files.

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

## Hazards

- **Cage loop:** two cages to the same switch with both lasers on = broadcast storm. Light one cage only (`rtk i2c write 8 1 0xfe`); unplug other fibres before `bootm` OpenWrt.
- No flash writes: no `saveenv`, `savesys`, `setsys`, `upgrade*`, `*force`, `flerase`, `sf write/erase/update`.
- `rtk network on` once per boot, before any GPIO/I2C `rtk` command (before it they hang the console; power cycle needed — the user does it).
