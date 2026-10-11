# Default boot: OpenWrt on our 7.3 kernel, recovery OpenWrt fallback (#73)

Design + code 2026-10-12 (modes: owner 2026-10-12); nothing run on the board. Every flash write needs owner approval. Steps: [DEFAULT-BOOT-OPS.md](DEFAULT-BOOT-OPS.md).

## Goal and constraints

- Default = OpenWrt userspace (uci, netifd, fw4, overlay, sysupgrade, failsafe) on our 7.3 kernel, built in the local OpenWrt buildroot (#73 track 1).
- An OpenWrt fallback that boots without a host.
- Loop safety (#19, storm 2026-10-10): bridge STP on before a second port forwards.
- Mode switch picks switch or isolated-management behaviour (owner 2026-10-12, [Modes](#modes)).
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
| 3 | Mode switch M3 | recovery |
| 4 | Stock env `st1008f_boot=prompt` / `=fallback` | prompt / recovery |
| 5 | Primary uImage header bad | recovery |
| 6 | Attempt record ≥ 2 | recovery |
| 7 | else (M1, M2, invalid) | attempts + 1, primary |

- M2 selects like M1; only Linux behaves differently ([Modes](#modes)). Invalid switch read = M1 (+ LED error latch).
- `bootargs` per `bootm`: `st1008f.mode=m1|m2|m3 st1008f.boot=primary|fallback|legacy` (the primary's in-line fallback re-sets `boot=fallback`).
- Primary `bootcmd` (LED hooks omitted): `clocks fast; bootsel wdt on; setenv bootargs …boot=primary; bootm 0xb4300000; bootsel wdt off; setenv bootargs …boot=fallback; bootm 0xb5900000` (a bad data CRC falls through to recovery).
- Row 2 keeps today's behaviour until `recovery` is written: the new U-Boot can go into `jffs2-log` first.
- Stock env flag: read-only from `u-boot-env` (0xe0000, 64 KiB, big-endian CRC32 over 0x10000 − 4 at offset 4, checked against the 2026-10-08 backup). Setting it is a flash write: `fw_setenv st1008f_boot fallback` (uboot-envtools, default package) or stock `setenv` + `saveenv`.
- `bootsel` command: slots, flag, record, WDT state, what a chained boot would do now + its `st1008f.mode`; `bootsel clear`; `bootsel wdt on|off|<ms>`.

### Attempt record (RAM)

- Phys `0x0e000000` (KSEG1 `0xae000000`), 3 words: magic `0x5b007ec0`, attempts, ~attempts. Invalid (cold boot: DRAM content random) = 0.
- Above `bootm` decompression (0x00100000 + ≤ 16 MiB) and below relocated U-Boot (top of 256 MiB). `reserved-memory` `no-map` in both kernels' DTS.
- Confirmed by Linux: `/etc/init.d/st1008f-bootok` (START=99) writes magic + 0 via `devmem` once bridge `switch` is loop-safe for its mode: `switch` = STP on; `isolated` = every bridge port `isolated` 1. O_SYNC `/dev/mem` = uncached mapping, so the write is in DRAM before any reset.
- Unconfirmed boots: panic (`CONFIG_PANIC_TIMEOUT=1` in OpenWrt: reboot after 1 s), watchdog reset, hang, no bridge, STP off (switch), a port not isolated (isolated; forced on), no mode state. Two in a row → recovery.
- Recovery is sticky until a power cycle (DRAM loses the record) or `bootsel clear` / `devmem` clear.
- Depends on DRAM keeping the page across a SoC reset through the stock preloader and stock U-Boot: not measured. Fallback if it does not: reset cause from `RST_GLB_STS` (watchdog reset → recovery once), address to confirm (#62).

### Watchdog

- SoC watchdog `0xb8003260` (Linux `realtek_otto_wdt`, reset-mode soc). Tick = 2^(25+prescale) / LX kHz; LX 175 MHz → 192/383/767/1534 ms, max 33 ticks = 50.6 s.
- `bootsel wdt on` = 12 s (prescale 2, 16 ticks of 767 ms). Covers `bootm` → kernel watchdog probe: chain log 2026-10-11 = ~23 s ours → console, of which kernel 14.3 s and bootdelay 1 s → ~8 s `bootm` (flash read + LZMA at stock SPI) + ~1 s to probe ≈ 9 s, x1.25 → 12 s. Expiry = SoC reset → counted attempt.
- `openwrt/patches/300-15`: probe used to write `CTRL_DEFAULT` (watchdog off). Now an enabled watchdog stays on, `WDOG_HW_RUNNING`: the core pings until procd opens `/dev/watchdog` (procd: 30 s timeout, 5 s ping). Without it, probe (~1 s) → procd (~13 s) is uncovered. The recovery kernel (6.18) needs the same patch.
- Not measured: that a watchdog reset resets the whole board (and whether `RST_GLB_CTRL_0` WD_RST_EN gates it), LX at boot.

## Modes

Owner decision 2026-10-12 (#73, #46). M2 used to mean "stop at the U-Boot prompt"; it now boots the primary.

| Switch | Image | Linux mode | Ports |
|---|---|---|---|
| M1 | primary | switch | all cages bridged, forwarding, STP on, forward_delay 2 |
| M2 | primary | isolated | every cage reaches only the CPU; no port-to-port forwarding |
| M3 | recovery | isolated | as M2 |
| any | recovery (fault fallback) | isolated | as M2 |

- Management (all modes): bridge `switch` stays one bridge with lan1-lan8, STP on; isolation = per-port `isolated` flag. Plug a host into any cage → management.
- Fault fallback in M1 = isolated: the recovery image is a management image. One-line change in `st1008f-mode` (`want=` rule) if switching should continue.
- `/etc/init.d/st1008f-mode` (START=19, before `network` at 20):
  - mode from `/proc/cmdline` `st1008f.mode` / `st1008f.boot`; none (RAM boot, legacy U-Boot) → debugfs `/sys/kernel/debug/st1008f-mode-switch/state` `position` (300-06); none → `unknown` = isolated.
  - sets uci `isolate` 1/0 on each port's `device` section (02_network creates one per lanN for its MAC; created if missing); `uci commit` only when it changed = flash write only on a mode change.
  - state → `/var/run/st1008f-mode` (`<mode> <image> switch|isolated cmdline|gpio`).
- netifd (`device.c` `isolate`, `system-linux.c`) writes `brport/isolated` right after `SIOCBRADDIF`; with STP on the port is still listening, so no frame forwards before isolation.
- Mode is read at boot only; moving the switch at runtime changes nothing until the next boot (the 1G/2.5G speed pattern still follows at runtime, 300-06).
- Legacy boot (no recovery image, flash OpenWrt 25.12.4 on 6.18 upstream): kernel ignores `bootargs` (`MIPS_CMDLINE_FROM_DTB`), no `st1008f-mode` → M2 = switch as today, STP saved (#43).

### Hardware offload of isolation

- rtl83xx (`files-6.18` and our 7.3 copy, identical): `port_pre_bridge_flags` accepts `BR_ISOLATED`; `port_bridge_flags` stores it and calls `rtldsa_update_port_member()`.
- `rtldsa_update_port_member()`: two ports forward to each other only if not both isolated; CPU port always in the mask; written with `traffic_set()` = RTL930x `PORT_ISO_CTRL` table (per source port: allowed egress mask). Hardware-enforced for forwarded and flooded frames, no patch needed.
- Bridge (software) also drops isolated → isolated (`br_skb_isolated`), for frames that reach the CPU.
- Not measured on the board: test in [DEFAULT-BOOT-OPS.md](DEFAULT-BOOT-OPS.md) "Mode tests".

### Kernel command line

- OpenWrt realtek default `MIPS_CMDLINE_FROM_DTB` ignores U-Boot `bootargs`. Both images use `MIPS_CMDLINE_DTB_EXTEND`: DT `bootargs` (`earlycon`) + U-Boot argv (`fw_init_cmdline()` in `realtek_fixup_fdt`).
  - 6.18 (recovery): `openwrt/backport-6.18/openwrt-tree.patch` (`config-6.18`).
  - 7.3 (primary): `PORT73` in `scripts/build_openwrt.py`; needs `build-openwrt --kernel 7.3 --regen-config` (the overlay logs a WARN while `config-7.3` lacks it).
- Stock U-Boot `bootargs` is empty (`ramload` paths): nothing added. `MTD_CMDLINE_PARTS=y`: a `mtdparts=` in `bootargs` would override the DT layout; neither U-Boot sets one.

### Mode switch hardware

- Stock meaning (`rtk.ko`, our 300-06 driver): speed pattern for 1G/2.5G modules (M2 = cages 1-4 1G, 5-8 2.5G); M3 = pattern 3. 10G optics and copper modules are untouched. Boot/isolation meanings are on top; the speed pattern still applies under both images.

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

## Open

- Owner decisions: #73 comment of 2026-10-12.
- Measure: DRAM record across reset, watchdog board reset, `bootm` → probe time, image sizes from the 7.3 OpenWrt build, hardware isolation (M2).
