# Default boot: OpenWrt on our 7.3 kernel, recovery OpenWrt fallback (#73)

Design + code 2026-10-12 (modes: owner 2026-10-12); nothing run on the board. Flash writes: standing approval except the stock U-Boot area (CLAUDE.md). Steps: [DEFAULT-BOOT-OPS.md](DEFAULT-BOOT-OPS.md).

## Goal and constraints

- Default = OpenWrt userspace (uci, netifd, fw4, overlay, sysupgrade, failsafe) on our 7.3 kernel, built in the local OpenWrt buildroot (#73 track 1).
- An OpenWrt fallback that boots without a host.
- Loop safety (#19, storm 2026-10-10): bridge STP on before a second port forwards.
- Mode switch picks switch or isolated-management behaviour (owner 2026-10-12, [Modes](#modes)).
- Boot selection without per-boot flash writes.

## Today

- Power-up: stock U-Boot → saved `bootcmd` → CRC check → our U-Boot from `jffs2-log` (0x200000) → 2 s ESC window → `bootsel fast` (clocks by mode, [below](#clocks-by-mode-46)) → `bootm 0xb4300000` → flash OpenWrt.
- `firmware` 0x300000-0x2000000 (29 MiB), split by OpenWrt `mtdsplit` (boot log 2026-10-11):

| Part | Flash | Size |
|---|---|---|
| kernel (uImage, magic 0x93030000) | 0x0300000-0x0630000 | 3.19 MiB |
| rootfs (squashfs) | 0x0630000-0x0870000 | 2.25 MiB |
| rootfs_data (JFFS2 overlay) | 0x0870000-0x2000000 | 23.56 MiB |

- The installed OpenWrt cannot stay as the fallback bit for bit: its DTS gives `firmware` all 29 MiB and its overlay owns everything after the squashfs, so any second image there gets overwritten by JFFS2 writes and GC.

## Power-up chain

Chain-load from stock (#47 option A, live since 2026-10-11, fd16464).

- Stock env (`./dev.py uboot-chain-env apply`, one `saveenv`, 0.7 s; #105):
  - `bootcmd_stock=boota` (stock's own flash boot)
  - `ub_ld=cp.b 0x94200000 0x81000000 0x80000` (512 KiB slot from the mmio window)
  - `ub_ck=crc32 0x81000000 0x7fffc 0x80ffff00; cmp.l 0x80ffff00 0x8107fffc 1` (slot CRC vs its last word)
  - `ub_go=mw.l 0xa0f80000 0xa5a51008; go 0x81000000` (marker, run)
  - `bootcmd=run ub_ld ub_ck ub_go; run bootcmd_stock`
  - Stock has no hush and no `crc32 -v`: `run` stops at the first var whose last command fails (`cmp.l` rc 1, U-Boot 2011.12 `do_run`), `;` goes on → mismatch = stock `boota` = flash OpenWrt at stock clocks, not a hang. Not yet verified on the board: `uboot-chain-env test-bad` ([OPS](DEFAULT-BOOT-OPS.md#chain-slot-check-105)).
  - Stock `crc32` = zlib CRC32 (whole-flash `dd984f95` matched the host, 2026-10-08).
  - Each var ≤ 14 words (stock `CONFIG_SYS_MAXARGS` 16).
  - `bootdelay=1` kept: stock's 1 s Esc window is the only serial path in if our U-Boot or its env breaks; `bootdelay=0` dropped (owner 2026-10-12, #81; [UBOOT-REFERENCE.md](UBOOT-REFERENCE.md#boot-timing-before-the-countdown-81)).
- Slot (`tmp/tftp/uboot-mainline-chain.bin`, `scripts/uboot_chain_image.py`): 512 KiB; `u-boot.bin` at 0, 0xff pad, trailer at 0x7ffc0 = magic `ST1008F-UBOOT` + v1, image size, image CRC32, build name; last word = CRC32 of bytes 0-0x7fffb.
  - Image ≤ 0x7ffc0 B (build fails above).
  - Code at offset 0: the pre-#105 env (`cp.b …; go`, no check) still boots a new slot; the new env falls back to `boota` on a pre-#105 raw image (its last word is erased flash). Install and env apply work in either order.
- Our U-Boot: `./dev.py uboot-chain-install` → `jffs2-log` (mtd4, 0x200000-0x2fffff, unmounted by OpenWrt; overlay is `rootfs_data`); host checks the slot CRCs before sending; blank check before the first write; read-back md5 (console) or read-back + CRC re-check on the host (SSH).
- `uboot-chain-env apply` checks the flash slot with the stock commands before `saveenv`; refuses on a mismatch unless `--allow-fallback`.
- `uboot-chain-env apply|revert|turbo --ssh --ip A.B.C.D` (no console, e.g. sw1): checks `/etc/fw_env.config` = the single `u-boot-env` copy (`/dev/mtdN 0x0 0x10000`, #86) and that `fw_printenv` reads (ethaddr present); `apply` also pulls the jffs2-log slot and checks its CRCs on the host; one `fw_setenv -s` write; `fw_printenv` read-back of every var + `ethaddr` unchanged. board_guard is skipped for `--ssh` (SSH only, no console or relay).
- Marker `0xa5a51008` @ `0xa0f80000` (cleared on read) = chained boot → autoboot; RAM-loaded (no marker) = prompt.
- Our U-Boot accepts the Realtek uImage magic, so `bootm 0xb4300000` boots the flash OpenWrt directly.
- Timing (2026-10-11, `uboot-chain-env boot`, real power cycle): ours up 2.4 s after power-on; `clocks fast` (CPU 1 GHz) 1.1 s later; flash OpenWrt console 23.2 s later; bridge STP on. Re-verified 2026-10-11T21:30+11:00.
- SPI stays at stock 25.5 MHz in this chain: 122.5 MHz corrupted squashfs reads under Linux (#50).
- Stock U-Boot does chain-load only (#81): every flow is to work as if stock never ran, with no dependency on stock `rtk network on` (#80, #51).
- Undo: `./dev.py uboot-chain-env revert` (`bootcmd=boota`, `ub_*` cleared). Interrupting the stock countdown still gives the stock prompt.
- Options not taken (#47): B = replace the stock U-Boot payload in `u-boot`, keeping the stock SPL (must match the SPL's hard-coded copy length `0xc1c78`; a bad write bricks without an external programmer); C = own SPL (DDR/PLL init), needed for DDR overclock at boot. Both write `0x0`-`0xDFFFF`, which is banned.

## Stock U-Boot area protection (#81)

Layered gates against writing `0x0`-`0xDFFFF` (stock LOADER):

- U-Boot SPI driver (0c8e150): refuses program/erase starting in `0x0`-`0xFFFFF`, chip erase, WRSR1/2/3, block lock/unlock ([UBOOT-MAINLINE.md](UBOOT-MAINLINE.md#spi-nor-stage-3-read-only)).
- DTS: mainline `tplink-tl-st1008f-v2.dts` has every partition `read-only`; upstream OpenWrt DTS has `u-boot` and `u-boot-env2` `read-only`, `u-boot-env` writable (`fw_setenv` needs it). Checked in the built DTBs (mainline 7.3, `openwrt-ours-initramfs`, upstream `openwrt-initramfs`).
- `scripts/flash_guard.py` (`./dev.py flash-guard` selftest, 59/59):
  - `check_range`: refuses any overlap with `0x0`-`0xDFFFF`, empty or off-chip ranges.
  - `check_mtd`: refuses unknown names and mtd0 (upstream, stock-label and split layouts).
  - `check_cmd`: `sf write/update/erase`, OpenWrt `mtd write/erase/-e`, `flashcp`, `flash_erase`, `dd of=`, `> /dev/mtd`, rw `mount` of an mtd, U-Boot `cp`/`mw`/`erase` into the flash window, `flerase`, `upgrade loader|rom`, `*force`, `sysupgrade`, `fw_setenv`, `saveenv`.
  - Called by `Console.send`/`send_checked`, by the console daemon on every completed line (refused line → Ctrl-C on the board + error reply; `policy` op too), and up front in `uboot-chain-install`, `uboot-chain-env`, `default-boot install|revert`.
  - Limit: U-Boot `$vars` in `cp`/`mw` are not resolved; in `sf` they are refused (fails closed).
- Open: W25Q256 status-register block protect (BP/TB) for the bottom region. Power-of-two granularity also covers the env sectors, so it is last, once the env is final.

## A/B slots

Chosen 2026-10-14 (#117, owner): two full slots. Replaces option A (22 MiB primary + 7 MiB recovery initramfs); the old options table is in git history.

| MTD | Flash | Size | Holds | Written by |
|---|---|---|---|---|
| u-boot, u-boot-env, u-boot-env2 | 0x0000000 | 1 MiB | stock | - |
| jffs2-cfg | 0x0100000 | 1 MiB | stock data | - |
| jffs2-log | 0x0200000 | 960 KiB | our U-Boot (512 KiB slot) | `uboot-chain-install` |
| bootstate | 0x02f0000 | 64 KiB | good + trial slot | Linux (`st1008f-slot`) |
| firmware_a | 0x0300000 | 14.5 MiB | uImage + squashfs + overlay | sysupgrade |
| firmware_b | 0x1180000 | 14.5 MiB | uImage + squashfs + overlay | sysupgrade |

- Slots = stock TP-Link `runtime1` / `runtime2` (same offsets and size, `scripts/flash_guard.py`).
- Per-slot overlay, not shared: `rootfs_data` = the slot after its image. sysupgrade's keep-config writes the config into the new slot; a rollback boots the old slot with the config that went with it. No fstools change.
- Slot use, 2026-10-14 image (6,816,425 B), sw2: kernel 0x310000 (3.1 MiB), squashfs to 0x650000 (3.3 MiB), `rootfs_data` 0x830000 (8.2 MiB); overlay used 368 KiB (config + our files).
- Only the booted slot is split: `openwrt,cmdline-match` on both slot nodes, honoured by the uImage splitter (`openwrt/patches/300-33`). Slot a = `!st1008f.slot=b` (default: stock `boota` passes no slot), slot b = `st1008f.slot=b`.
- Image: `IMAGE_SIZE := 14848k`, `DEVICE_COMPAT_VERSION := 2.0`; board.d sets the device to 2.0. A 1.0 image (single 29 MiB `firmware`) is refused without `-F`: written into a slot it would split slot a's range.
- Migration from a 1.0 image: `./dev.py openwrt-sysupgrade-ssh --ip IP --force` once (image lands in slot a, config kept).

### bootstate record

- One line at the start of `bootstate`: `S1AB g=<a|b> t=<a|b|-> c=<crc32 hex of the first 12 bytes>`. No valid record = slot a, as before A/B.
- Written only by Linux: `/lib/st1008f-slot.sh` (CRC32 from the gzip trailer; `mtd write`, read back). U-Boot only reads it (mmio window), so U-Boot still writes no flash.
- sysupgrade (`/lib/upgrade/st1008f-ab.sh`, `platform.sh` hook): writes the slot not running, then `g=<running> t=<new>`. A failed record write leaves the running slot booting next.
- `/etc/init.d/st1008f-slot` (START 99, every image): bridge `switch` with STP on within 15 s → `st1008f-slot mark-good`: `g=<booted> t=-`, attempt record 0. A trial that never confirmed is logged (`trial slot X did not confirm`).
- By hand: `st1008f-slot` (show), `st1008f-slot boot a|b` (trial on next boot).

### Boot selection (our U-Boot, `uboot-port/board/tplink/tl-st1008f/bootsel.c`)

Chained boot only (`ramload` boots never autoboot). First match wins:

| # | Condition | Boot |
|---|---|---|
| 1 | ESC during the 2 s `bootdelay` | prompt, no idle reset |
| 2 | Stock env `st1008f_boot=prompt` | prompt |
| 3 | No valid bootstate | legacy: slot a, watchdog off before `bootm` |
| 4 | Good slot uImage header bad, other slot fine | other slot |
| 5 | No trial, or stock env `st1008f_boot=good` | good slot |
| 6 | Trial slot header bad | good slot (LED `trial-bad`) |
| 7 | Attempt record ≥ 2 | good slot (LED `unconfirmed`) |
| 8 | else | attempts + 1, trial slot; its `bootm` falls through to the good slot |

- `bootargs`: `st1008f.mode=m1|m2|m3 st1008f.slot=a|b st1008f.boot=good|trial|legacy`.
- `bootm 0xb4300000` (a) / `0xb5180000` (b) from the mmio window.
- The mode switch picks clocks, not the slot (owner #46): [Clocks by mode](#clocks-by-mode-46).

### Measured on sw2 (2026-10-14T21:25-21:41+11:00)

- Our U-Boot with no bootstate, old 1.0 image: `Boot: legacy (no bootstate record: slot a as before A/B)`, boots as before.
- `--force` migration: slot a split (`firmware_a` → kernel, rootfs, `rootfs_data` 0x830000), config kept, `slot a marked good`. First-boot overlay erase 23.3 s (131 blocks, 178 ms each: blocks carry old JFFS2 cleanmarkers, so 300-32 skips none).
- Upgrade from a: `A/B: running slot a, writing slot b` → `Boot: trial (trial slot b attempt 1/2, fallback slot a)` → `st1008f.slot=b`, only `firmware_b` split, config kept, `slot b marked good`.
- Rollback: `st1008f-slot boot a`, two boots stopped at our prompt (unconfirmed) → attempts 1/2, 2/2 → `Boot: good (2 trial boots of slot a not confirmed by Linux)` → slot b logs `trial slot a did not confirm: back on slot b`, record `good b, trial -`, attempts 0.
- First run of the hook failed safe: stage2's ramdisk lacked `head`, the record write failed, the board stayed on slot a (`RAMFS_COPY_BIN += head`).
- Hang during a trial (2026-10-15T01:07-01:10+11:00): `st1008f-slot boot a`, then `./dev.py uboot-chain-env hang-test --slot a` (attempt 1/2, `init=/bin/sh`). Slot a held the pre-#138 image (no `watchdog.open_timeout`): no reset in 60 s, as before #138. After a warm reboot: `Boot: trial (trial slot a attempt 2/2, fallback slot b)`, normal boot, `slot a marked good`. Same test on the #138 image (slot b): SoC reset 6 s after `/bin/sh`.

### Autoboot stop and prompt (#46, #105)

- Countdown `Autoboot in 2 s, ESC for the prompt`: ESC (0x1b) only (`CONFIG_AUTOBOOT_KEYED`, stop string `\x1b`); other bytes are ignored, so line noise cannot stop an unattended boot. Owner 2026-10-13.
- Always on: the build fails without `AUTOBOOT_KEYED` / `BOOT_RETRY` (`#error` in `bootsel.c`); `bootsel` sets `bootdelay=2` and clears `bootstopkey` / `bootdelaykey` (env is RAM-only, `ENV_IS_NOWHERE`).
- Ctrl-C is ignored while `bootcmd` runs (keyed autoboot without `AUTOBOOT_KEYED_CTRLC`).
- Prompt after a failed autoboot: `bootcmd` sets `bootretry=300` first, so the prompt resets the board after 300 s without console input (`CONFIG_RESET_TO_RETRY`); each command restarts the 300 s. ESC never runs `bootcmd`, so a stopped prompt never times out. `BOOT_RETRY_TIME=-1` = off for `ramload` sessions.
  - Waits for: a person at the console to start typing. Expected ≤ 240 s, x1.25 = 300 s (owner accepted 2026-10-13). Expiry: `Timeout waiting for command`, reset → attempt count → good slot after 2.
- Not covered: env flag `st1008f_boot=prompt` (owner-chosen prompt, no timeout).
- Stock env flag: read-only from `u-boot-env` (0xe0000, 64 KiB, big-endian CRC32 over 0x10000 − 4 at offset 4, checked against the 2026-10-08 backup). Setting it is a flash write: `fw_setenv st1008f_boot fallback` (uboot-envtools, default package) or stock `setenv` + `saveenv`.
- `bootsel` command: slots, flag, record, WDT state, what a chained boot would do now + its `st1008f.mode`; `bootsel clear`; `bootsel wdt on|off|<ms>`.

### Attempt record (RAM)

- Phys `0x0e000000` (KSEG1 `0xae000000`), 3 words: magic `0x5b007ec0`, attempts, ~attempts. Invalid (cold boot: DRAM content random) = 0.
- Above `bootm` decompression (0x00100000 + ≤ 16 MiB) and below relocated U-Boot (top of 256 MiB). `reserved-memory` `no-map` in both kernels' DTS.
- Confirmed by Linux: `st1008f-slot mark-good` (every image, [bootstate record](#bootstate-record)) and, in `--default-boot` images, `/etc/init.d/st1008f-bootok` (START=99), which also checks `isolated` mode. Both write magic + 0 via `devmem`. O_SYNC `/dev/mem` = uncached mapping, so the write is in DRAM before any reset.
- Unconfirmed boots: panic (`CONFIG_PANIC_TIMEOUT=1` in OpenWrt: reboot after 1 s), watchdog reset, hang, no bridge, STP off (switch), a port not isolated (isolated; forced on), no mode state. Two in a row on a trial slot → good slot.
- A power cycle loses the record (DRAM): the trial slot gets 2 fresh attempts.
- DRAM keeps the record across a SoC watchdog reset and a switch-core reset through the stock preloader and stock U-Boot (sw2, 2026-10-13T10:05-10:07+11:00: `5b007ec0 00000000 ffffffff` read back at the stock prompt after each, #105).

### Watchdog

- SoC watchdog `WDTCNTRR` `0xb8003260`, `WDTINTRR` `+4`, `WDT_CTRL` `+8` (Linux `realtek_otto_wdt`; `WDT_RESET_MODE` 0 = SDK "full chip"). Tick = 2^(25+prescale) / LX kHz; LX 175 MHz → 192/383/767/1534 ms, max 33 ticks = 50.6 s.
- `bootsel fast` arms it on every mode (re-armed after a turbo change, at the new LX); the primary's fallback `bootm` re-arms it (`bootsel wdt on`); disarmed only before the prompt or the legacy `bootm`.
- `bootsel wdt on` = 12 s (prescale 2, 16 ticks of 767 ms). Covers `bootm` → kernel watchdog probe: chain log 2026-10-11 = ~23 s ours → console, of which kernel 14.3 s and bootdelay 1 s → ~8 s `bootm` (flash read + LZMA at stock SPI) + ~1 s to probe ≈ 9 s, x1.25 → 12 s. Expiry = SoC reset → counted attempt.
- `openwrt/patches/300-15`: probe used to write `CTRL_DEFAULT` (watchdog off). Now an enabled watchdog stays on, `WDOG_HW_RUNNING`: the core pings until procd opens `/dev/watchdog` (procd: 30 s timeout, 5 s ping). Without it, probe (~1 s) → procd (~13 s) is uncovered. The recovery kernel (6.18) needs the same patch.
- `bootsel fast` (#101) arms it (13 s) before `clocks fast`; legacy boots disarm before `bootm`.
- Warm resets come back by themselves (sw2, 2026-10-13, chain on, #105):
  - flash OpenWrt (W25Q256 in 4-byte mode), procd feeding stopped (`ubus call system watchdog '{"stop":true}'`): SoC reset 30 s later → stock → ours (`bootsel fast`, 1000/650) → OpenWrt console, no relay;
  - our U-Boot after `sf probe` (EN4B): `reset` (switch-core RST_GLB_CTRL) → stock banner, SPL reads flash fine;
  - our U-Boot `bootsel wdt 1000`: SoC reset after ~1.2 s → stock banner.
- `watchdog.open_timeout=92` (OpenWrt board DTS bootargs, #138): after it the kernel no longer feeds the running SoC watchdog while userspace has `/dev/watchdog` closed, so a hang before or between procd's opens resets the board instead of sitting until power is cut (2026-10-15 boot-link-check: console silent ~30 s after `Run /sbin/init` until the relay).
  - Sizing: the deadline also governs procd's close/re-open (preinit -> init). Last `procd: - watchdog -` over 182 logged 6.18 boots (2026-10-15): 5.73-73.38 s, median 12.38 s; the 73 s boots are first boots after a sysupgrade with the pre-300-32 overlay erase. 73.38 x 1.25 = 92 s.
  - 5 s (first attempt, sized from procd's first open only, 1.89-3.28 s over 204 boots) reset sw2 at procd's re-open at 5.73 s in 1 of 8 rounds.
  - Not in the mainline DTS: its initramfs `/init` is a shell and never opens the watchdog.
- Not measured: LX at boot.

## Modes

Owner decision 2026-10-12 (#73, #46); U-Boot side changed 2026-10-13 (#46): the switch no longer selects the recovery image.

| Switch | U-Boot clocks | Linux mode | Ports |
|---|---|---|---|
| M1 | stock | switch | all cages bridged, forwarding, STP on, forward_delay 2 |
| M2 | stock | isolated | every cage reaches only the CPU; no port-to-port forwarding |
| M3 | turbo profile | isolated (`st1008f-mode` m3 rule, unchanged) | as M2 |
| any | recovery (fault fallback) | isolated | as M2 |

- Open (#46): M2 = U-Boot networking on all front ports, waiting for commands; not built yet (M2 autoboots like M1). M3 → Linux `isolated` follows the 2026-10-12 table; owner to confirm for the turbo position.
- Management (all modes): bridge `switch` stays one bridge with lan1-lan8, STP on; isolation = per-port `isolated` flag. Plug a host into any cage → management.
- Fault fallback in M1 = isolated: the recovery image is a management image. One-line change in `st1008f-mode` (`want=` rule) if switching should continue.
- `/etc/init.d/st1008f-mode` (START=19, before `network` at 20):
  - mode from `/proc/cmdline` `st1008f.mode` / `st1008f.boot`; none (RAM boot, legacy U-Boot) → debugfs `/sys/kernel/debug/st1008f-mode-switch/state` `position` (300-06); none → `unknown` = isolated.
  - sets uci `isolate` 1/0 on each port's `device` section (02_network creates one per lanN for its MAC; created if missing); `uci commit` only when it changed = flash write only on a mode change.
  - state → `/var/run/st1008f-mode` (`<mode> <image> switch|isolated cmdline|gpio`).
- netifd (`device.c` `isolate`, `system-linux.c`) writes `brport/isolated` right after `SIOCBRADDIF`; with STP on the port is still listening, so no frame forwards before isolation.
- Mode is read at boot only; moving the switch at runtime changes nothing until the next boot (the 1G/2.5G speed pattern still follows at runtime, 300-06).
- Legacy boot (no recovery image, flash OpenWrt 25.12.4 on 6.18 upstream): kernel ignores `bootargs` (`MIPS_CMDLINE_FROM_DTB`), no `st1008f-mode` → M2 = switch as today, STP saved (#43).

### Clocks by mode (#46)

- `bootsel fast` in `bootcmd`: M1, M2, invalid → stock clocks (CPU 800, DDR 600, LX 175, SPI 25.5): `bootsel: M1: stock clocks (turbo profile only in M3)`.
- M3 → profile from the stock env (CRC-checked, read-only), stored like `ethaddr`: `st1008f_turbo=cpu=1100,ddr=650,lx=175`.
  - Keys `cpu`, `ddr`, `lx`, `sram` in MHz, any subset (missing = keep); `spi=25` accepted at stock only (#50). ≤ 62 chars, values ≤ 4 digits.
  - Supported: cpu 800 (stock /4), 1000, 1050 (/3), 1100-1425 step 25 (/2, VCO 2200-2850; 1450+ hung, [OVERCLOCK.md](OVERCLOCK.md)); ddr = a `clocks set mem` bin; lx 175 204 245 306; sram 250 500.
  - Missing, bad env CRC, unknown key, bad number, unsupported value → stock clocks, one `bootsel: M3: …: stock clocks` line, LED fallback latch `turbo`.
  - Apply (`otto_turbo`, clocks.c): raising = DDR (nosr) first, CPU (+ SRAM select, same re-lock) last; lowering CPU = CPU first (#101: DDR changes at the lower CPU rate); tREFI 4608 clk if DDR > 600; DRAM prefetch with an overclock; LX last (console follows). Any failure → revert to the starting clocks, `clocks: turbo reverted = …` with the reason above it.
- `turbo` command at our prompt, any mode (M1/M2 too): `turbo` = stored profile, `turbo show` = profile + live clocks, `turbo cpu=1400 ddr=662 lx=306 sram=500` (or one domain) = ad hoc, env untouched. Same checks. Host: `./dev.py turbo [PROFILE|show] [--no-cycle]` (power-cycle, ESC, command).
  - Written only by `./dev.py uboot-chain-env turbo set PROFILE [--ssh --ip A.B.C.D]` (host checks it with the same rules first); `apply` and the installers never write one.
- **Default = stock clocks, as TP-Link ships (CPU 800, DDR 600, LX 175, SRAM 250, SPI 25.5), in every mode** (owner 2026-10-13): no `st1008f_turbo`, or one at stock values → stock. Installing this slot therefore lowers sw1/sw2 from today's `clocks fast` 1000/650 to stock at the next power-up, until a profile is written and the slider is in M3. `uboot-chain-install` and `uboot-chain-env apply` print this.
- Turbo needs the switch in M3 on each unit; M1/M2 run stock 800/600 whatever the profile.
  - sw2: M1 (console log, every chained boot through 2026-10-13T10:23+11:00, `Mode:  M1 switch, pins 17/18/19 = 0/1/1`).
  - sw1: not known (no console; flash OpenWrt 6.18 has no mode readout). Owner to check the slider before its next power-up.
- Unfinished change (watchdog reset during it): record word `REC+3` still set → next boot stock clocks, the one after retries.
- CPU PLL no lock: re-lock at the previous values; still off the PLL → `reset` with the record word set (next boot stock); a reset that returns → the armed watchdog fires.
- `clocks fast` (prompt) = `turbo cpu=1000 ddr=650`, as before.

### Clock-change bounds (#105)

- CPU PLL lock: `CPU_PLL_READY` poll bounded by SoC timer TC5 (1 MHz from LX, `0xb8003250`), not the CPU clock. Expected ≤ 200 us (no datasheet lock time; assumed worst), x1.25 = 250 us (owner accepted 2026-10-13). READY was set on the first poll in 415 logged changes. Expiry: CPU stays on the alternate clock, `clocks: CPU PLL not locked after 250 us`.
- `clocks: locked after N us (routine M us)`: M comes from TC5 = proof the time base counts.
- UART drain before a change: 17 chars x 10 bits at the console baud, x1.25 (1.8 ms at 115200), `timer_get_us`; expiry logged, the change goes ahead.
- CPU on the alternate clock: `get_tbclk()`, `clocks`, `ft_board_setup` use a measured rate (2 x CP0 Count over 1000 us of TC5, once per episode). TC5 not counting (1000 us not reached within 750000 Counts = 1.25 ms at 1.2 GHz) → logged, PLL-decoded rate kept.

### Hardware offload of isolation

- rtl83xx (`files-6.18` and our 7.3 copy, identical): `port_pre_bridge_flags` accepts `BR_ISOLATED`; `port_bridge_flags` stores it and calls `rtldsa_update_port_member()`.
- `rtldsa_update_port_member()`: two ports forward to each other only if not both isolated; CPU port always in the mask; written with `traffic_set()` = RTL930x `PORT_ISO_CTRL` table (per source port: allowed egress mask). Hardware-enforced for forwarded and flooded frames, no patch needed.
- Bridge (software) also drops isolated → isolated (`br_skb_isolated`), for frames that reach the CPU.
- Not measured on the board: test in [DEFAULT-BOOT-OPS.md](DEFAULT-BOOT-OPS.md) "Mode tests".

### Kernel command line

- OpenWrt realtek default `MIPS_CMDLINE_FROM_DTB` ignores U-Boot `bootargs`. Both images use `MIPS_CMDLINE_DTB_EXTEND`: DT `bootargs` (`earlycon`) + U-Boot argv (`fw_init_cmdline()` in `realtek_fixup_fdt`).
  - 6.18 (recovery): `openwrt/backport-6.18/openwrt-tree.patch` (`config-6.18`).
  - 7.3 (primary): `PORT73` in `scripts/build_openwrt.py`; needs `build-openwrt --kernel mainline --regen-config` (the overlay logs a WARN while `config-7.3` lacks it).
- Stock U-Boot `bootargs` is empty (`ramload` paths): nothing added. `MTD_CMDLINE_PARTS=y`: a `mtdparts=` in `bootargs` would override the DT layout; neither U-Boot sets one.

### Mode switch hardware

- Stock meaning (`rtk.ko`, our 300-06 driver): speed pattern for 1G/2.5G modules (M2 = cages 1-4 1G, 5-8 2.5G); M3 = pattern 3. 10G optics and copper modules are untouched. Boot/isolation meanings are on top; the speed pattern still applies under both images.
- Runtime switch moves under the 300-06 driver (2026-10-11T23:25+11:00, 7.3 minimal kernel 8914a2d, RAM boot, #64): boot M1 pattern 1 (pins 0/1/1); M2 pattern 2 (1/0/1), split works (cage 3 GLC-T media 2, cage 7 GLC-T `will not set because of unmatched pattern`); M3 pattern 3 (1/1/0), both GLC-T refused; back to M1 pattern 1. 10G modules unaffected; no reset, no oops.
  - Mid-travel M1 → M2 reads 1/1/1 (no pin grounded between detents) → a full re-apply at pattern 3 (stock would reset the switch here). No debounce beyond the stock 30 ms settle; open (#64).
  - Classification (M1 smoke boot, 80ab8df): GLC-SX-MM (1G) is classed `10G fiber insert` / media 5 (its EEPROM sets 10G compliance bits; same as stock); PTB3370553 matches no vendor class → media 7, untouched.
  - Speed changes themselves not yet tested (need switch netdevs).

## Config (primary and recovery)

`openwrt/default-boot/files/etc/uci-defaults/90-st1008f-defaults`, on top of OpenWrt's generated defaults for this board (`02_network`: bridge device `switch` = lan1-lan8, bridge-vlan 1, interface `lan` on `switch.1`, per-port `device` sections with MACs from env `ethaddr` `16:b0:46:e9:0d:c0`):

| uci | Value | Why |
|---|---|---|
| `network.switch.stp` / `forward_delay` | 1 / 2 | loop safety (#19), ports forward ~4 s after link |
| `network.lan.proto` | dhcp | house LAN: reservation `.48` (below) |
| `network.lan_fb` | static 192.168.0.1/24 on `switch.1` | always-present fallback, TP-Link convention |
| `network.lan6` | dhcpv6 on `switch.1`, `reqprefix no` | SLAAC (+ DHCPv6 if offered); link-local is automatic |
| `dhcp.lan` | `ignore 1`, `dhcpv6`/`ra`/`ndp` disabled | never a DHCP/RA server on someone's LAN |
| firewall zone `lan` | + `lan_fb`, `lan6` | input accept on the fallback |

- Bridge name stays `switch` (OpenWrt realtek default; `ramload`, `st1008f-bootok`, `default-boot` rely on it), not `br-lan`.
- Aliases bind to `switch.1` directly, not `@lan`: an alias on a DHCP interface stays down until a lease.
- DHCP reservation (owner action): `.48` (registry block `st1008f-1`) for the `switch.1` MAC (expected `16:b0:46:e9:0d:c0`; check `ip link show switch.1`). Until then `ramload`/`mode-watch` tools that use `.48` need it, or reach `192.168.0.1` from a host with a 192.168.0.x/24 address.
- Fallback address change: edit `network.lan_fb.ipaddr`/`netmask` (`uci set …; uci commit network; /etc/init.d/network reload`) on the primary (persists, sysupgrade keeps it); for both images edit `90-st1008f-defaults` and rebuild. Avoid the house subnet 192.168.25.0/24 (clash).
- uci-defaults run in `/etc/init.d/boot` (START=10), before `st1008f-mode` (19) and `network` (20): the bridge is created with STP on, forward delay 2 s → ports forward ~4 s after link (listening + learning). rtl83xx offloads the STP port state.
- SSH: dropbear defaults, root with blank password = today's flash OpenWrt. fw4: default lan zone.
- Recovery: same config (tmpfs: uci-defaults every boot = immutable known-good).
- `99_fwenv-store-ethaddr` (OpenWrt realtek) writes `u-boot-env` when `ethaddr` is empty or `00:e0:4c:00:00:xx`; ours is set (#36), so no write.
- Build additions (`openwrt/default-boot/diffconfig`): `KERNEL_DEVMEM`, BusyBox `devmem`; files dir `openwrt/default-boot/files/` (uci-defaults, `st1008f-mode`, `st1008f-bootok` + `rc.d` links).

## Loop safety

- Power-on → Linux: the chain never runs `rtk network on`; lasers stay off (PCA9534 power-on = inputs); DSA setup isolates every port.
- Linux: STP on from bridge creation (uci-defaults), all modes. Isolated modes: ports isolated in hardware from bridge join → no loop through the switch at all.
- `st1008f-bootok` forces STP (switch) or `isolated` (isolated) on if found off and does not confirm the boot.
- Cages 3 ↔ 7 (GLC-T copper loop, if cabled; #43 says uncabled since 2026-10-11): switch mode → STP blocks one; isolated → no path between them.
- `ramload openwrt-ours` keeps its own STP enforcement (relay off on failure).

## Code

| File | What |
|---|---|
| `uboot-port/board/tplink/tl-st1008f/bootsel.c`, `board.c` | Selection, record, watchdog, `bootsel`; builds warning-free (`./dev.py build-uboot`) |
| `openwrt/patches/300-15-watchdog-realtek-otto-keep-running.patch` | Kernel watchdog hand-over; compile-checked on 7.3-rc6 |
| `openwrt/default-boot/0001-*.patch` | OpenWrt DTS/image layout; `cpp` + `dtc` clean, applies to OpenWrt `e5ec5e1` |
| `openwrt/default-boot/files/`, `diffconfig` | uci-defaults, `st1008f-mode`, boot confirmation, build options |
| `openwrt/backport-6.18/openwrt-tree.patch`, `scripts/build_openwrt.py` `PORT73` | `MIPS_CMDLINE_DTB_EXTEND` (mode on the cmdline) |
| `scripts/default_boot.py` (`./dev.py default-boot`) | `check`, `test`, `status`, gated `install primary|recovery`, gated `revert` |

## Measured: modes on OpenWrt-on-7.3, RAM boot (2026-10-12)

Image: `./dev.py build-openwrt --kernel 7.3 --default-boot` (OpenWrt main e5ec5e1, our 7.3 port SMP with 300-18/300-19, mainline DTS with `bootrec@e000000`). Boot: `./dev.py ramload uboot-mainline --then openwrt-ours --bootargs "st1008f.mode=mN st1008f.boot=primary"` (simulates bootsel; mode switch physically at M1). One 10G SR in cage 1 to the house switch.

| Check | M1 | M2 (cmdline) |
|---|---|---|
| `/proc/cmdline` | `earlycon st1008f.mode=m1 st1008f.boot=primary` | `... m2 ...` |
| `/var/run/st1008f-mode` | `m1 primary switch cmdline` | `m2 primary isolated cmdline` |
| `brif/*/isolated` | all 0 | all 1 (8 ports) |
| bridge STP | 1 | 1 |
| bootok | confirmed (switch) | confirmed (isolated) |
| IPv4 on `switch.1` | 192.168.0.1/24 + DHCP 192.168.25.138 | same |

- DHCP lease .138 is from the pool: the `.48` reservation does not exist yet (owner action).
- No DHCP/RA server in the image: no dnsmasq/odhcpd, no `/etc/config/dhcp`; the `dhcp.lan.*` lines of `90-st1008f-defaults` do nothing.
- Mode-switch sysfs: `power_total_mw` 1000, `power_cage_mw` `1000 0 0 0 0 0 0 0`, budget 15000; debugfs `position ... = M1`.
- Bridge appears 21-24 s after the shell; first-boot dropbear key generation delays rc S19/S20 (one boot: `st1008f-mode` ran at 42 s uptime). ramload's STP wait is 45 s.
- Not run: two-host isolation ping and `PORT_ISOLATION` drop counter (one fitted module; `drop_counters` debugfs path not found on 7.3); M2->M1 change commit; M3/recovery image.

### Fixed for this test
- Mainline DTS had no `reserved-memory`: `st1008f-bootok`'s `/dev/mem` write hit kernel RAM. Added `bootrec@e000000` (no-map).
- `300-19`: bootloader args were in `/proc/cmdline` twice without a space (`...primaryst1008f.mode=m1 ...`): OpenWrt's realtek `fixup_fdt()` and generic `plat_mem_setup()` both run `fw_init_cmdline()`. `st1008f-mode` parsed garbage and bootok reported "no mode".
- `build-openwrt --default-boot` copies `openwrt/default-boot/files` + `diffconfig` into the buildroot; without the flag no overlay is included.

## Open

- Owner decisions: #73 comment of 2026-10-12.
- Measure: DRAM record across reset, watchdog board reset, `bootm` → probe time, image sizes from the 7.3 OpenWrt build, hardware isolation (M2).
