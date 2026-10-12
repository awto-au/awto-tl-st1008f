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

## Where the images live: options

| Option | Layout | For | Against |
|---|---|---|---|
| **A (recommended)** | `firmware` 22 MiB (OpenWrt on 7.3: kernel + squashfs + overlay) + `recovery` 7 MiB (OpenWrt initramfs uImage) | One partition for sysupgrade, as upstream; recovery is one read-only blob that `bootm` boots directly; ~16 MiB overlay left | Both images need the split DTS (local build); upstream images must not be flashed (below) |
| B | Two full slots of 14.5 MiB (kernel + squashfs + overlay each) | Fallback keeps its own persistent config | Two overlays to keep in sync; sysupgrade needs a slot-select hook (`platform.sh`), more flash writes |
| C | One image, fallback = TFTP/RAM recovery | Simplest; 29 MiB for one image | Needs a host + `ramload` (stock `rtk network on` + TFTP) to recover; nothing unattended |
| D | One rootfs, two kernels | Small | OpenWrt kmods are bound to one kernel version |
| E | 7.3 image as a file in the JFFS2 overlay | No layout change | U-Boot has no JFFS2 + LZMA; GC moves nodes |
| F | `jffs2-cfg` + `jffs2-log` | Free today | 2 MiB total; image ~6 MiB |

## Flash layout (option A)

| MTD | Flash | Size | Holds | Written by |
|---|---|---|---|---|
| u-boot, u-boot-env, u-boot-env2 | 0x0000000-0x0100000 | 1 MiB | unchanged | - (`u-boot-env` only by an approved `fw_setenv`) |
| jffs2-cfg | 0x0100000 | 1 MiB | unchanged (stock data) | - |
| jffs2-log | 0x0200000 | 1 MiB | our U-Boot (~330 KB) | `uboot-chain-install` |
| **firmware** | 0x0300000-0x1900000 | 22 MiB | OpenWrt on 7.3: uImage + squashfs + overlay | sysupgrade |
| **recovery** | 0x1900000-0x2000000 | 7 MiB | OpenWrt initramfs uImage (fallback) | `default-boot install recovery` |

- Our U-Boot boots `bootm 0xb4300000` (primary) or `bootm 0xb5900000` (recovery) from the mmio window.
- Recovery budget: upstream 25.12.4 initramfs = 5,383,940 B; 7 MiB leaves ~1.6 MiB.
- Primary budget: OpenWrt 6.18 kernel 3.19 MiB + squashfs 2.25 MiB today; the 7.3 kernel without initramfs is ~2.9 MB LZMA (ours, fewer drivers) → expect ~6 MiB image, ~16 MiB overlay.
- Build: `openwrt/default-boot/0001-realtek-tl-st1008f-v2-recovery-slot.patch` (DTS `firmware` 0x1600000 + `recovery` + reserved-memory; `IMAGE_SIZE := 22528k`), applied to the local buildroot for both images.
- `u-boot` (LOADER) stays `read-only` in the split layout: upstream DTS has it, patch 0001 leaves partition@0 alone. `default-boot check`/`install` refuse an image whose DTB lacks it, and every install/revert range goes through `scripts/flash_guard.py` first (#81).
- Hazard: an upstream image (29 MiB layout) booted from this flash grows its overlay over `recovery`. Only images built with patch 0001 go on this flash; RAM-booting upstream initramfs images is fine (they mount nothing from flash unless asked).

## Images

| Image | Kernel | Rootfs / config | File (`tmp/tftp/`) |
|---|---|---|---|
| primary | 7.3 + `openwrt/patches/300-*` | squashfs + JFFS2 overlay; uci-defaults on first boot, then owner config persists (sysupgrade keeps it) | `openwrt-73-sysupgrade.bin` |
| recovery | OpenWrt 6.18 (local build, same commit) | initramfs, tmpfs overlay: uci-defaults every boot = immutable known-good config | `openwrt-recovery-initramfs.bin` |
| RAM test | as primary | initramfs | `openwrt-ours-initramfs.bin` (`ramload openwrt-ours`) |

- Recovery can `sysupgrade` the primary (its DTS has the same split layout), so it is also the reflash path.

## Boot selection (our U-Boot, `uboot-port/board/tplink/tl-st1008f/bootsel.c`)

Chained boot only (`ramload` boots never autoboot). First match wins:

| # | Condition | Boot |
|---|---|---|
| 1 | ESC during the 2 s `bootdelay` | prompt, no idle reset |
| 2 | No valid uImage header in `recovery` | legacy = single-image boot (`bootm 0xb4300000`) |
| 3 | Stock env `st1008f_boot=prompt` / `=fallback` | prompt / recovery |
| 4 | Primary uImage header bad | recovery |
| 5 | Attempt record ≥ 2 | recovery |
| 6 | else | attempts + 1, primary |

- The mode switch picks clocks, not the image (owner #46, 2026-10-13): [Clocks by mode](#clocks-by-mode-46). Linux still gets `st1008f.mode` ([Modes](#modes)). Invalid switch read = M1 (+ LED error latch).
- `bootargs` per `bootm`: `st1008f.mode=m1|m2|m3 st1008f.boot=primary|fallback|legacy` (the primary's in-line fallback re-sets `boot=fallback`).
- Primary `bootcmd` (LED hooks omitted): `setenv bootretry 300; bootsel fast; setenv bootargs …boot=primary; bootm 0xb4300000; bootsel wdt on; setenv bootargs …boot=fallback; bootm 0xb5900000; bootsel wdt off` (a bad data CRC falls through to recovery; the fallback `bootm` runs under a fresh watchdog).

### Autoboot stop and prompt (#46, #105)

- Countdown `Autoboot in 2 s, ESC for the prompt`: ESC (0x1b) only (`CONFIG_AUTOBOOT_KEYED`, stop string `\x1b`); other bytes are ignored, so line noise cannot stop an unattended boot. Owner 2026-10-13.
- Always on: the build fails without `AUTOBOOT_KEYED` / `BOOT_RETRY` (`#error` in `bootsel.c`); `bootsel` sets `bootdelay=2` and clears `bootstopkey` / `bootdelaykey` (env is RAM-only, `ENV_IS_NOWHERE`).
- Ctrl-C is ignored while `bootcmd` runs (keyed autoboot without `AUTOBOOT_KEYED_CTRLC`).
- Prompt after a failed autoboot: `bootcmd` sets `bootretry=300` first, so the prompt resets the board after 300 s without console input (`CONFIG_RESET_TO_RETRY`); each command restarts the 300 s. ESC never runs `bootcmd`, so a stopped prompt never times out. `BOOT_RETRY_TIME=-1` = off for `ramload` sessions.
  - 300 s = time for someone at the console to start typing; not a hardware wait. Reset → attempt count → recovery after 2.
- Not covered: env flag `st1008f_boot=prompt` (owner-chosen prompt, no timeout).
- Row 2 keeps today's behaviour until `recovery` is written: the new U-Boot can go into `jffs2-log` first.
- Stock env flag: read-only from `u-boot-env` (0xe0000, 64 KiB, big-endian CRC32 over 0x10000 − 4 at offset 4, checked against the 2026-10-08 backup). Setting it is a flash write: `fw_setenv st1008f_boot fallback` (uboot-envtools, default package) or stock `setenv` + `saveenv`.
- `bootsel` command: slots, flag, record, WDT state, what a chained boot would do now + its `st1008f.mode`; `bootsel clear`; `bootsel wdt on|off|<ms>`.

### Attempt record (RAM)

- Phys `0x0e000000` (KSEG1 `0xae000000`), 3 words: magic `0x5b007ec0`, attempts, ~attempts. Invalid (cold boot: DRAM content random) = 0.
- Above `bootm` decompression (0x00100000 + ≤ 16 MiB) and below relocated U-Boot (top of 256 MiB). `reserved-memory` `no-map` in both kernels' DTS.
- Confirmed by Linux: `/etc/init.d/st1008f-bootok` (START=99) writes magic + 0 via `devmem` once bridge `switch` is loop-safe for its mode: `switch` = STP on; `isolated` = every bridge port `isolated` 1. O_SYNC `/dev/mem` = uncached mapping, so the write is in DRAM before any reset.
- Unconfirmed boots: panic (`CONFIG_PANIC_TIMEOUT=1` in OpenWrt: reboot after 1 s), watchdog reset, hang, no bridge, STP off (switch), a port not isolated (isolated; forced on), no mode state. Two in a row → recovery.
- Recovery is sticky until a power cycle (DRAM loses the record) or `bootsel clear` / `devmem` clear.
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
  - Keys `cpu`, `ddr`, `lx` in MHz, any subset (missing = stock); `sram=250`, `spi=25` accepted at stock only (SRAM 500 not in this build; SPI #50). ≤ 62 chars, values ≤ 4 digits.
  - Supported: cpu 1000 1050 1100 1150 1200 1300 (tested points, [OVERCLOCK.md](OVERCLOCK.md)); ddr = a `clocks set mem` bin; lx 175 204 245 306.
  - Missing, bad env CRC, unknown key, bad number, unsupported value → stock clocks, one `bootsel: M3: …: stock clocks` line, LED fallback latch `turbo`.
  - Apply = `clocks turbo <cpu> <ddr> <lx>`: DDR (nosr), CPU, tREFI 4608 clk if DDR ≥ 600 and changed, DRAM prefetch, LX last.
  - Written only by a dev.py env flow (CLAUDE.md env rule); not scripted yet.
- Unfinished change (watchdog reset during it): record word `REC+3` still set → next boot stock clocks, the one after retries.
- CPU PLL no lock: re-lock at the previous values; still off the PLL → `reset` with the record word set (next boot stock); a reset that returns → the armed watchdog fires.
- `clocks fast` (prompt) = `clocks turbo 1000 650 0`, as before.

### Clock-change bounds (#105)

- CPU PLL lock: `CPU_PLL_READY` poll bounded by SoC timer TC5 (1 MHz from LX, `0xb8003250`), not the CPU clock: 250 us (no datasheet lock time; 200 us assumed worst, x1.25). READY was set on the first poll in 415 logged changes. Expiry: CPU stays on the alternate clock, `clocks: CPU PLL not locked after 250 us`.
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
