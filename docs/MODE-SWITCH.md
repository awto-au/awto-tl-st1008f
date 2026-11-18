# Mode slider: M1, M2, M3

The 3-position slider on the unit. Read once at power-up by our U-Boot and by Linux; moving it while running changes nothing until the next boot.

## What each position does

| Position | Clocks (CPU / DDR) | Switching in Linux | U-Boot network window |
|---|---|---|---|
| M1 | turbo profile (built-in default) | on: all cages bridged and forwarding, STP on | off |
| M2 | stock 800 / 600, always | off: every cage reaches only the CPU | on: cage 1, 192.168.1.1 |
| M3 | turbo profile, as M1 | off, as M2 | off |
| any (fault fallback), invalid slider | stock | off, as M2 | off |

- M2 is the escape position: stock clocks, no switching, network access to U-Boot. Always safe.
- Turbo default (owner 2026-11-18): `cpu=1350,ddr=662,lx=306,sram=500`, built into U-Boot (`TURBO_DEFAULT` in bootsel.c). No setting needed.
- Stock clocks = what TP-Link ships: CPU 800, DDR 600, LX 175, SRAM 250, SPI 25.5 MHz. Used in M2 and on any failure.
- "Switching off" = Linux per-port `isolated` flag; the bridge `switch` still holds lan1-lan8 so a host on any cage still manages the unit.
- Fault fallback = the boot fell back to the recovery path; always isolated.

## The setting (optional override)

| Setting | Meaning | Written by |
|---|---|---|
| `st1008f_turbo` | replaces the built-in profile in M1 and M3, e.g. `cpu=1100,ddr=650`; keys `cpu ddr lx sram swcore`, MHz, any subset | `./dev.py uboot-chain-env turbo set PROFILE [--ssh --ip A.B.C.D]` |

- Stored in the stock env (`u-boot-env` flash area, CRC-checked). Absent or empty = the built-in default. `apply` and the installers never write it.
- An invalid override (unknown key, bad number, unsupported value) = stock clocks, one `bootsel: M1: ...: stock clocks` console line, LED latch `turbo`.
- Supported values and apply order: docs/DEFAULT-BOOT.md#clocks-by-mode-46; limits: docs/OVERCLOCK.md.
- No setting for the network window: M2 turns it on.

## M2 network window (#80)

- Before the 2 s autoboot window U-Boot starts the switch network (about 10 s, 17 s with a 10GBASE-T module), lights cage 1 only, sets 192.168.1.1/24, sends its console text as a broadcast on 192.168.1.255 and listens on UDP :6666.
- ESC sent to UDP :6666 stops autoboot; `./dev.py netboot IMAGE` does that from the host and boots an image from RAM, no serial cable.
- Cost: only in M2. M1 and M3 boots are unchanged.
- Details, guards, host side: docs/UBOOT-MAINLINE.md#power-up-network-window-80-2026-11-17.

## How to read the position

- Console at power-up: `Mode:  M1 switch, pins 17/18/19 = 0/1/1`.
- Kernel command line: `st1008f.mode=m1` (`/proc/cmdline`); state file `/var/run/st1008f-mode`.
- Units: sw2 = M1 (cmdline 2026-11-18). sw1 = not known (no console).

## Linux side

- `/etc/init.d/st1008f-mode` (before `network`): reads the mode from `st1008f.mode` / `st1008f.boot`, sets uci `isolate` per port, `uci commit` only on a change. Details: docs/DEFAULT-BOOT.md#modes.
- Clocks, A/B slots, power-up chain: docs/DEFAULT-BOOT.md.
