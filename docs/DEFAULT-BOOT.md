# Default boot: OpenWrt on our 7.3 kernel, recovery OpenWrt fallback (#73)

Design + code 2026-10-12; nothing run on the board. Every flash write needs owner approval. Steps: [DEFAULT-BOOT-OPS.md](DEFAULT-BOOT-OPS.md).

## Goal and constraints

- Default = OpenWrt userspace (uci, netifd, fw4, overlay, sysupgrade, failsafe) on our 7.3 kernel, built in the local OpenWrt buildroot (#73 track 1).
- An OpenWrt fallback that boots without a host.
- Loop safety (#19, storm 2026-10-10): bridge STP on before a second port forwards.
- Boot selection without per-boot flash writes.

## Today

- Power-up: stock U-Boot → saved `bootcmd` → our U-Boot from `jffs2-log` (0x200000) → `clocks fast; bootm 0xb4300000` → flash OpenWrt 25.12.4 (6.18).
- `firmware` 0x300000-0x2000000 (29 MiB), split by OpenWrt `mtdsplit` (boot log 2026-10-11):

| Part | Flash | Size |
|---|---|---|
| kernel (uImage, magic 0x93030000) | 0x0300000-0x0630000 | 3.19 MiB |
| rootfs (squashfs) | 0x0630000-0x0870000 | 2.25 MiB |
| rootfs_data (JFFS2 overlay) | 0x0870000-0x2000000 | 23.56 MiB |

- The installed OpenWrt cannot stay as the fallback bit for bit: its DTS gives `firmware` all 29 MiB and its overlay owns everything after the squashfs, so any second image there gets overwritten by JFFS2 writes and GC.

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
| 1 | Any key during the 1 s `bootdelay` | prompt (as today) |
| 2 | No valid uImage header in `recovery` | legacy = today's single-image boot (`clocks fast; bootm 0xb4300000`); M3 → prompt |
| 3 | Mode switch M2 | prompt (#46 easy mode, needs stage-4 Ethernet) |
| 4 | Mode switch M3 | recovery |
| 5 | Stock env `st1008f_boot=prompt` / `=fallback` | prompt / recovery |
| 6 | Primary uImage header bad | recovery |
| 7 | Attempt record ≥ 2 | recovery |
| 8 | else | attempts + 1, primary |

- Primary `bootcmd`: `clocks fast; bootsel wdt on; bootm 0xb4300000; bootsel wdt off; bootm 0xb5900000` (a bad data CRC falls through to recovery).
- Row 2 keeps today's behaviour until `recovery` is written: the new U-Boot can go into `jffs2-log` first.
- Stock env flag: read-only from `u-boot-env` (0xe0000, 64 KiB, big-endian CRC32 over 0x10000 − 4 at offset 4, checked against the 2026-10-08 backup). Setting it is a flash write: `fw_setenv st1008f_boot fallback` (uboot-envtools, default package) or stock `setenv` + `saveenv`.
- `bootsel` command: slots, flag, record, WDT state, what a chained boot would do now; `bootsel clear`; `bootsel wdt on|off|<ms>`.

### Attempt record (RAM)

- Phys `0x0e000000` (KSEG1 `0xae000000`), 3 words: magic `0x5b007ec0`, attempts, ~attempts. Invalid (cold boot: DRAM content random) = 0.
- Above `bootm` decompression (0x00100000 + ≤ 16 MiB) and below relocated U-Boot (top of 256 MiB). `reserved-memory` `no-map` in both kernels' DTS.
- Confirmed by Linux: `/etc/init.d/st1008f-bootok` (START=99) writes magic + 0 via `devmem` once bridge `switch` has STP on. O_SYNC `/dev/mem` = uncached mapping, so the write is in DRAM before any reset.
- Unconfirmed boots: panic (`CONFIG_PANIC_TIMEOUT=1` in OpenWrt: reboot after 1 s), watchdog reset, hang, or no bridge with STP. Two in a row → recovery.
- Recovery is sticky until a power cycle (DRAM loses the record) or `bootsel clear` / `devmem` clear.
- Depends on DRAM keeping the page across a SoC reset through the stock preloader and stock U-Boot: not measured. Fallback if it does not: reset cause from `RST_GLB_STS` (watchdog reset → recovery once), address to confirm (#62).

### Watchdog

- SoC watchdog `0xb8003260` (Linux `realtek_otto_wdt`, reset-mode soc). Tick = 2^(25+prescale) / LX kHz; LX 175 MHz → 192/383/767/1534 ms, max 33 ticks = 50.6 s.
- `bootsel wdt on` = 12 s (prescale 2, 16 ticks of 767 ms). Covers `bootm` → kernel watchdog probe: chain log 2026-10-11 = ~23 s ours → console, of which kernel 14.3 s and bootdelay 1 s → ~8 s `bootm` (flash read + LZMA at stock SPI) + ~1 s to probe ≈ 9 s, x1.25 → 12 s. Expiry = SoC reset → counted attempt.
- `openwrt/patches/300-15`: probe used to write `CTRL_DEFAULT` (watchdog off). Now an enabled watchdog stays on, `WDOG_HW_RUNNING`: the core pings until procd opens `/dev/watchdog` (procd: 30 s timeout, 5 s ping). Without it, probe (~1 s) → procd (~13 s) is uncovered. The recovery kernel (6.18) needs the same patch.
- Not measured: that a watchdog reset resets the whole board (and whether `RST_GLB_CTRL_0` WD_RST_EN gates it), LX at boot.

### Mode switch

- Stock meaning (`rtk.ko`, our 300-06 driver): speed pattern for 1G/2.5G modules; M3 = pattern 3. 10G optics and copper modules are untouched. M3 as "boot recovery" adds a boot meaning on top; the speed pattern still applies under both images.

## Config (primary and recovery)

`openwrt/default-boot/files/etc/uci-defaults/90-st1008f-defaults` = today's flash OpenWrt config:

```
network.switch.stp='1'
network.switch.forward_delay='2'
network.lan.proto='static'
network.lan.ipaddr='192.168.25.48'
network.lan.netmask='255.255.255.0'
network.lan.gateway='192.168.25.254'
network.lan.dns='192.168.25.254'
```

- On top of OpenWrt's generated defaults for this board (`02_network`): bridge device `switch` = lan1-lan8, bridge-vlan 1, interface `lan` on `switch.1`, MAC from env `ethaddr` (`16:b0:46:e9:0d:c0`).
- uci-defaults run in `/etc/init.d/boot` (START=10), before `network` (START=20): the bridge is created with STP on, forward delay 2 s → ports forward ~4 s after link (listening + learning). rtl83xx offloads the STP port state.
- SSH: dropbear defaults, root with blank password = today's flash OpenWrt. fw4: default lan zone.
- Recovery: `.48` too (only one of the two runs at a time).
- `99_fwenv-store-ethaddr` (OpenWrt realtek) writes `u-boot-env` when `ethaddr` is empty or `00:e0:4c:00:00:xx`; ours is set (#36), so no write.
- Build additions (`openwrt/default-boot/diffconfig`): `KERNEL_DEVMEM`, BusyBox `devmem`; files dir `openwrt/default-boot/files/` (uci-defaults, `st1008f-bootok` + its `rc.d` link).

## Loop safety

- Power-on → Linux: the chain never runs `rtk network on`; lasers stay off (PCA9534 power-on = inputs); DSA setup isolates every port.
- Linux: STP on from bridge creation (uci-defaults). `st1008f-bootok` forces `stp_state` 1 if found off and does not confirm the boot.
- Cages 3 ↔ 7 (GLC-T copper loop, if cabled; #43 says uncabled since 2026-10-11): both in bridge `switch` → STP blocks one.
- `ramload openwrt-ours` keeps its own STP enforcement (relay off on failure).

## Code

| File | What |
|---|---|
| `uboot-port/board/tplink/tl-st1008f/bootsel.c`, `board.c` | Selection, record, watchdog, `bootsel`; builds warning-free (`./dev.py build-uboot`) |
| `openwrt/patches/300-15-watchdog-realtek-otto-keep-running.patch` | Kernel watchdog hand-over; compile-checked on 7.3-rc6 |
| `openwrt/default-boot/0001-*.patch` | OpenWrt DTS/image layout; `cpp` + `dtc` clean, applies to OpenWrt `e5ec5e1` |
| `openwrt/default-boot/files/`, `diffconfig` | uci-defaults, boot confirmation, build options |
| `scripts/default_boot.py` (`./dev.py default-boot`) | `check`, `test`, `status`, gated `install primary|recovery`, gated `revert` |

## Open

- Owner decisions: #73 comment of 2026-10-12.
- Measure: DRAM record across reset, watchdog board reset, `bootm` → probe time, image sizes from the 7.3 OpenWrt build.
