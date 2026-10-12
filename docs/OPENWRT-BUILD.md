# Local OpenWrt build (#73 track 1)

Operations: [OPENWRT-BUILD-OPS.md](OPENWRT-BUILD-OPS.md). Script: `scripts/build_openwrt.py` (`./dev.py build-openwrt`).

## Tree

| Item | Value |
|---|---|
| Buildroot | `tmp/openwrt-build` (gitignored), shallow clone of OpenWrt `main` |
| Commit | `e5ec5e199f13` (2026-10-11T22:45:51+02:00, "realtek: l3: rtl839x: do not invent a next-hop L2 entry") |
| Target | `realtek/rtl930x`, device `tplink_tl-st1008f-v2` only |
| Toolchain | OpenWrt-built, GCC 14.4.0 + musl 1.2.6 (`mips_24kc`) |
| Kernel | step 1: OpenWrt 6.18.55 + our backports; step 2: our 7.3-rc6 port (testing kernel) |
| Packages | target defaults + `ip-full ip-bridge tcpdump-mini kmod-pktgen` (nat-bench switch side, [NAT-OPS.md](NAT-OPS.md): a RAM boot cannot `apk add` kmods matching a local kernel). No feeds. |
| Config | seed in `SEED` (build_openwrt.py) + `make defconfig`; `CONFIG_AUTOREMOVE=y` |
| Host prereqs added 2026-10-12 | `perl-IPC-Cmd`, `perl-Time-Piece` (dnf) |

## Step 1: OpenWrt 6.18 + backports

Overlay (re-applied each run on a `git checkout`/`git clean` of `target/linux`):

- Kernel patches → `target/linux/realtek/patches-6.18/` (same names as `openwrt/patches/`).
- `openwrt/backport-6.18/openwrt-tree.patch` (`git apply`):
  - DTS: `gpio-keys` M1/M2/M3 → `mode-switch` node, children `cage@0..7` (not `port@N`: #16 rtl83xx bug).
  - DTS: spi0 `reg` + `reg-names = "regs", "dirmap"`, soc `ranges` += flash window `0x14000000` (32 MiB).
  - DTS memory: already 512 MiB upstream (`0x0` + `0x20000000` banks); unchanged.
  - DTS `watchdog` (gpio-wdt, GPIO21): kept as upstream (enabled; flash OpenWrt 25.12.4 runs with it). Our 7.3 DTS keeps it disabled (#18).
  - `rtl930x/config-6.18`: `CONFIG_MIPS_PLATFORM_DEVICES=y`, `CONFIG_TPLINK_ST1008F_MODE_SWITCH=y` (built in for all rtl930x devices; binds only on our compatible).

| Patch | Status on OpenWrt main 6.18 | Notes |
|---|---|---|
| 300-04 DRAM prefetch | as-is | `board-realtek.c` 300-01..03 identical at `53ec2d0` and main |
| 300-05 CP0 timer from PLL | as-is | |
| 300-06 mode switch driver | as-is | DT node via the tree patch above |
| 300-07 SPI dirmap | rebased → `openwrt/backport-6.18/kernel/` | context: OpenWrt `040-v7.4` (second CS); 6.18 `spi_mem_dirmap_info.op_tmpl` is a struct (7.3: pointer) → `&desc->info.op_tmpl`; dirmap refused for CS != 0 (window + `rtspi_cs()` are CS0 only). Self-check fails on 7.3 (#61): watch the dirmap line |
| 300-11 rteth TX ring/BQL/xmit_more | as-is (offsets −93..−123) | added: 300-12 builds on it |
| 300-12 rteth 930x NIC path | rebased → `openwrt/backport-6.18/kernel/` | main dropped the L2 notification buffer (`membase`/`dmam_alloc_coherent`); doorbell `of_iomap` moved after the regmap lookup |
| 300-20 rteth on the shared NIC core | 7.3 only | needs `rtl930x_nic.h` from `shared/` (`SHARED_FILES`); not in step 1 |
| 300-13 MIPS highmem lowmem fast paths | as-is (offsets) | generic mm |
| 300-08..10 | not used | 7.3 port glue |
| 300-15 watchdog keep-running | not in step 1 | added to `openwrt/patches/` by the default-boot work after this list was set |

Build result 2026-10-12 (host: 30 threads, `-j8`, nice 19 / ionice idle):

- Kernel: the objects our patches touch (`board-realtek`, `dma-noncoherent`, `highmem`, `rtl838x_eth`, `tplink-st1008f-mode`, `spi-realtek-rtl`) compile with 0 warnings.
- Strings in `vmlinux-initramfs`: "RTL930x DRAM controller prefetch on", "CPU frequency from PLL", "cur pattern = ", "dirmap: 0x".
- DTB: `mode-switch` + `cage@0..7`, spi0 `dirmap`, soc `ranges` window present.

| Output | Size (B) |
|---|---|
| `openwrt-...-initramfs-kernel.bin` → `tmp/tftp/openwrt-ours-6.18-initramfs.bin` (magic `0x93030000`) + `-std.bin` (`0x27051956`) | 5,818,812 |
| `openwrt-...-squashfs-sysupgrade.bin` (upstream 29 MiB layout; not for this flash, see [DEFAULT-BOOT.md](DEFAULT-BOOT.md)) | 6,029,612 |
| Upstream 25.12.4 initramfs, for comparison | 5,383,940 |

| Phase | Time |
|---|---|
| tools + toolchain + kernel prepare | 933 s |
| world (packages, kernel, images) | ~460 s (two runs: 238 s to the 300-07 compile error, 223 s after) |
| `--kernel-only` | 132 s |

Disk:

- Peak before pruning: build_dir/host 1.7 GB + build_dir/toolchain 3.8 GB + kernel/target 1.7 GB + staging 0.6 GB + dl 0.43 GB.
- `prune()` deletes `build_dir/host` and `build_dir/toolchain-*` once their install stamps exist (stamps live in `staging_dir`).
- After step 1: tree 4.9 GB.

## Step 2: our 7.3 port as OpenWrt testing kernel

`--kernel mainline` (old name `7.3`; base from `scripts/kernel_base.py`, linux-next since 2026-10-12, [MAINLINE-PORT.md](MAINLINE-PORT.md#baselines)): OpenWrt's `KERNEL_TESTING_PATCHVER` mechanism, same OpenWrt main tree and userspace.

| Piece | Source |
|---|---|
| `generic/kernel-7.3` | `LINUX_VERSION-7.3 = -rc6`, hash `skip` |
| `dl/linux-7.3-rc6.tar.gz` | `git archive v7.3-rc6` of `tmp/linux-v7.3` (OpenWrt would fetch git.kernel.org); 269,765,341 B |
| `realtek/Makefile` | `KERNEL_TESTING_PATCHVER:=7.3`; `.config` `CONFIG_TESTING_KERNEL=y` |
| `realtek/patches-7.3` | `OWRT_VERBATIM` (300-01..03, 309, 330, 331, 712, 714, 718, 722) from `tmp/openwrt` @ `53ec2d0` + every `openwrt/patches/*.patch` (300-04..17 at build time) |
| `realtek/files-7.3` | `OWRT_FILES` from `tmp/openwrt` `files-6.18` @ `53ec2d0` (not main: the port's 300-09..12/16/17 are against it) |
| `generic/pending-7.3` | 700, 701 (nft flowtable) |
| `generic/hack-7.3` | 910 + 911 (`broadcast_uevent`, needed by `gpio-button-hotplug`), 940 (non-empty `modules.builtin`, needed by kmod packaging) |
| `rtl930x/config-7.3` | `openwrt/kernel-7.3/config-7.3` (below) |
| DTS | `mainline/tplink-tl-st1008f-v2.dts`, include → `realtek/rtl930x.dtsi` (mainline dtsi, 1-cell interrupts; OpenWrt's dtsi in the same dir would shadow it) |
| `include/image.mk` | `-Wno-graph_child_address` dropped: 7.3 dtc has no such check (FATAL ERROR) |

- Inputs `OWRT_COMMIT`, `OWRT_VERBATIM`, `OWRT_FILES` are imported from `scripts/mainline_build_check.py`: the OpenWrt-7.3 kernel and `./dev.py build-kernel` stay the same port.
- `config-7.3` (`--regen-config`): OpenWrt generic + rtl930x `config-6.18` merged (`scripts/kconfig.pl`) + `PORT73` port symbols → `olddefconfig` in the prepared 7.3 tree; symbols olddefconfig dropped for unmet deps keep their 6.18 line (`NF_TABLES_IPV4=y` is only reachable once the kmod override sets `NF_TABLES=m`). Fails if a `PORT73` symbol does not survive. 8,762 lines.
- Kconfig notes from the 7.3 configure: `BOOTPARAM_HUNG_TASK_PANIC`/`BOOTPARAM_SOFTLOCKUP_PANIC` value `n` invalid (now int), `NETFILTER_NETLINK` value `m` invalid (bool); harmless.
- Switching `--kernel` rebuilds the toolchain's kernel headers (prepare 217 s) and every kmod.

Generic OpenWrt patches on 7.3 (dry-run in series on the prepared 7.3 tree, 2026-10-12; not applied unless listed above):

| Dir | upstream | applies | fails |
|---|---|---|---|
| `backport-6.18` | 75 | 12 | 89 |
| `pending-6.18` | 10 (incl. 700/701, already in) | 165 | 36 (737-01..05: our 300-08; 400 mtdsplit; 710 bridge BPDU knob; mxl862xx, mtk) |
| `hack-6.18` | 1 | 52 | 12 (200, 251, 259, 260, 402, 651, 770, 901, 902, 904, 905, 970) |

- `pending-6.18/400-mtd-mtdsplit-support` fails on 7.3: the flash (sysupgrade) image needs the `firmware` split (`openwrt,uimage`); the RAM-boot initramfs does not. Forward-port needed before the 7.3 default boot ([DEFAULT-BOOT.md](DEFAULT-BOOT.md)).

Build result 2026-10-12:

| Output | Size (B) |
|---|---|
| `tmp/tftp/openwrt-ours-initramfs.bin` (magic `0x93030000`) + `-std.bin` | 6,021,101 |
| `...-squashfs-sysupgrade.bin` (upstream layout, no mtdsplit on 7.3: not for flash) | 6,291,756 |

- Manifest: `kernel 7.3_rc6~c9690f69...`; same package set as step 1.
- Strings in `vmlinux-initramfs`: prefetch, PLL, `cur pattern = `, `dirmap: 0x`, rteth. DTB: mode-switch, `realtek,rtl9301-eth`, dirmap.
- Times: prepare (incl. toolchain headers) 217 s; `--kernel-only` 111 s. Tree 5.3 GB; 12.5 GB free after.

Build gotchas (2026-10-12):

- `--kernel-only` does not rebuild kmods. After a kernel config change (PREEMPT, SMP) nf_tables and other kmods fail to load with `section size must match ... struct module size`; a full `build-openwrt --kernel mainline` (57 s incremental) fixes it. Use the full build after any config change.
- `config-7.3` regenerated with `MIPS_CMDLINE_DTB_EXTEND=y`: U-Boot `bootargs` (`st1008f.mode`) are appended to the DT ones (OpenWrt realtek default `MIPS_CMDLINE_FROM_DTB` ignores them).

## Board results (2026-10-12)

Conditions: RAM boot via our U-Boot (CPU 1 GHz), one 10G SR in cage 1, SMP.

- OpenWrt-on-7.3 (`openwrt-ours`): boots to shell, both VPEs tick (intc fix, [MAINLINE-PORT.md](MAINLINE-PORT.md) section 9), STP 1, lan1 up at 10G. `check-log` clean except daemon-log interleave fragments in the stock U-Boot part (`RTL9`, `300# # go`), not kernel output.
- OpenWrt 6.18 local (`openwrt-ours-6.18`): boots to shell, STP 1, lan1 up.
  - `check-log`: 41 UNKNOWN / 7 ERROR, all allowlist gaps (`ethernet-switch` node name, 6.18 banner/DRAM/PLL lines), no new faults.
  - MAC `00:e0:4c:00:00:00`: the 6.18 DTS has no nvmem MAC (7.3 uses env `ethaddr` `16:b0:46:e9:0d:c0`).
  - First boot: bridge not up within ramload's 30 s STP cap → powered off; retry had STP on in 14 s. Not reproduced; ramload's STP-failure diag now records uptime, netifd and non-kernel `logread`.
- Images built here carry no default-boot overlay (`st1008f-mode`, DHCP + 192.168.0.1 fallback): `lan` is OpenWrt's 192.168.1.1 static.
- Boot-log rules: OpenWrt on a 7.x kernel is checked with `[openwrt]` + `[mainline]` rules; kmsg spliced into userspace console lines is split out; SMP printk can land inside `Please press Enter`, so all flows share one `OW_READY` regex.

## Upstream OpenWrt on this board

### Flash image (#36)

- `firmware` holds OpenWrt 25.12.4 since 2026-10-08 22:30-22:34 (+11:00): RAM-booted OpenWrt `wget` of `openwrt-25.12.4-realtek-rtl930x-tplink_tl-st1008f-v2-squashfs-sysupgrade.bin` (5,767,474 B), `sysupgrade -T`, `sysupgrade -n`. Kept (owner 2026-10-10, [DECISIONS.md](DECISIONS.md)).
- Found 2026-10-10 by our U-Boot's read-only SPI-NOR driver: whole chip CRC32 `671232ac` (`sf read` = mmio); 2026-10-08 backup `dd984f95`.
- `firmware` @0x300000 header: magic `0x93030000`, name `MIPS OpenWrt Linux-6.18.55`, image time 2026-10-08T07:21:15Z (backup: `RTK_SDK`, stock).
- `u-boot-env`: only change `ethaddr` `00:E0:4C:00:00:00` → `16:b0:46:e9:0d:c0`.

| Partition | Board CRC32 | Backup CRC32 |
|---|---|---|
| `u-boot` | `e579e61c` | same |
| `u-boot-env` | `0b43aa0e` | `096dbc0b` |
| `u-boot-env2` | `deab7e4e` | same |
| `jffs2-cfg`, `jffs2-log` | `956bac74` | same |
| `firmware` | `324ffc55` | `c8f4a2e7` (every MiB differs) |

- Stock firmware exists only in the 2026-10-08 backup (`full-flash.bin`). Since 2026-10-11 `jffs2-log` holds our U-Boot (chain boot).

### Bridge STP (#43)

- Overlay (`rootfs_data`, mtd8) has `network.switch.stp='1'` (checked read-only with `scripts/openwrt_flash_stp.py`), `forward_delay` 2 s since 2026-10-11: ports forward ~4 s after STP is up.
- Boot transient, flash boot 2026-10-11T11:51+11:00 (dmesg): lan1 blocking → listening 27.1 s → learning 35.7 s → forwarding 44.0 s; lan2 blocking → listening 28.7 s → blocking 30.1 s. No port forwards before STP decides.
- Steady state +110 s: `stp_state 1`, lan2 blocking, lan1 + lan8 forwarding, lan3-7 disabled; no storm. Holds the cage-1/cage-2 house-LAN loop.
- Loop-safe at boot and steady state. The 2026-10-10/11 house-LAN alerts traced to a RAM-loaded OpenWrt without STP ([HISTORY.md](HISTORY.md)); `ramload` now enforces STP or cuts power.

### RAM-boot timeline (#26)

Measured 2026-10-10: OpenWrt 25.12.4 initramfs RAM-booted from stock U-Boot, CPU 800 MHz, 3 of 8 cages populated (10GBASE-SR), console 115200. Kernel timestamps:

| t (s) | Event |
|---|---|
| 0 → 2.46 | kernel → `Run /init` |
| 3.33 → 11.44 | preinit failsafe window (8.1 s; lan1 up 5.9, link 7.3, down 11.4) |
| 12.2 | procd init |
| 14.4 → 31 | init scripts, no output (~17 s); dropbear 31 s, uhttpd EC key + cert 34 s |
| 33-36 | netifd, `lan` up |
| 36.9 → 54 | SerDes bring-up, sequential ~1.6 s/port (lan1 36.9, lan2 38.6, lan8 44.3) |
| 47-54 / 67-75 | ports forwarding without STP / with STP forward_delay 15 |

- Serial shell usable at ~25 s.
- 372 of 634 dmesg lines are SerDes RX-calibration debug from `pcs-rtl-otto` (`start_1.x`/`end_1.x`/`vth`/`tap0`/`rtpcs_930x`); each blocks the 115200 console.
- Every RAM boot regenerates dropbear host keys and the uhttpd key + cert (no persistent overlay).
- Suspected contributors, not bisected: calibration printk (fix: `pr_debug` or `loglevel=4`), per-port sequential calibration (8 ports ≈ 13 s), preinit 8 s wait on a RAM boot, key generation, SFP EEPROM retries on empty cages (~59 s).

### Boot warnings (#29, #28)

OpenWrt 25.12.4 initramfs (kernel 6.12.87), 2026-10-10, cages 1, 2, 8 populated:

- `realtek-otto-pcs: pcs_config(10gbase-r)` (ports 0/8/27, sds 2/3/9) and `(sgmii)` (ports 16-26, sds 4-8) `not yet fully implemented`: upstream PCS stub; 10G links still come up.
- `rtpcs_930x_sds_10g_idle WARNING: Waiting for RX idle timed out`, SDS 4..8: SerDes of empty cages never idle.
- `sfp-p4/p5/p6: module slow to respond` → `failed to read EEPROM: -EIO`: empty cages 4-6 read present; cause = GPIO3-5 muxed to the switch-core SPI master by stock `rtk network on` ([MAINLINE-PORT.md](MAINLINE-PORT.md) DTS). Fixed in our U-Boot, 7.3 DTS and the 6.18 backport; verified 2026-10-12 (only sfp-p1 present, no `-EIO`).
- `Failed to find NVMEM device` → random MAC each boot: the upstream image has no MAC source for this board (our 7.3 DTS: nvmem on `u-boot-env`).
- `rtpcs_930x_sds_force_mode: SDS 9 could not reset state machine`: seen once (lan8), unexplained.
- Lines reviewed as benign (#28, `known #28` in `scripts/boot_log_allowlist.txt`):
  - U-Boot `Err:0xf030:FAIL (0xf030)` at the end of `rtk network on`: `phy_enable_set` on PHY-less ports.
  - `Initrd not found or empty - disabling initrd`: initramfs is built in.
  - `Failed to get CPU clock: -2`: no CPU clk provider; DT 800 MHz used.
  - `UNKNOWN_MC_PMASK: 000000001fffffff`: driver debug print of a constant mask (ports 0-28).
  - `gpio_button_hotplug: loading out-of-tree module taints kernel.`
  - `Cannot parse config file '/etc/fw_env.config'`: none for this board.
  - Mainline: `pca953x 8-0038: supply vcc not found, using dummy regulator` (no regulator nodes; fixed rails).
- Never allowlisted: `Ring contention` (storm, #19), `received packet ... with own address as source address` (loop).

#### sw1 in service: OpenWrt SNAPSHOT r36962 / 6.18.55 flash image

`./dev.py switch-logs` (full dmesg + logread over SSH, read-only), 2026-10-12T13:58+11:00, uptime 4185 s (boot ~12:48:43+11:00), 703 dmesg / 964 logread lines. All lines reviewed into `scripts/boot_log_allowlist.txt` (6.18 block); result PASS with these `known` items:
- **AQR113C PHY read timeout** (#90): `Aquantia AQR113C smbus:sfp-p8:11: aqr_gen1_read_status failed: -145` (-ETIMEDOUT on MIPS) at 1012 s → lan8 down, back up at 1116 s (104 s outage).
- **Phantom module on cage 6** (#92): at 14.3 s `sfp-p6` reports cage 1's GLC-T (sn MTC106630), removed at 16.3 s; cage 6 was empty.
- **Warnings without traffic impact** (#93): `SerDes N: waiting for RX idle timed out` on every SerDes config (x13); `thermal_zone3|4: Failed to set trips: -34` on each AQR113C attach (x8); `lower interface lan1 not found` + `fib_add() failed` at 6.7 s; `lan7: selection of interface failed, speed 10000` at 592 s; AQR113C ports report `10Gbps` for ~5 s after a reconfigure before the PHY attaches, then `1Gbps`.
- Benign: `eth0: Failed to create a device link to DSA switch`, `supply vcc not found` (spi-nor, pca953x), `rdinit=/init failed: -2`, netifd `Wireless module not found` (#93).
- **Link drops, explained:**
  - lan4 (10G SR, fibre to sw2 cage 1): 17 downs from 2641 s on; each matches a sw2 relay off/on, sw2 reset or stock boot laser toggle (`tmp/logs/switch_power.log`, console log), e.g. 2641 s = 13:32:43 relay off, 4104 s = 13:57:06 relay off. One at 3094 s (13:40:18) falls while sw2 ran stock Linux during the UART-wire fix. Not a sw1 fault.
  - lan1/lan7/lan8 together at 438-441 s and 1251 s: network reload (`RESETTING CPU_PORT 28`), lan7+lan8 at 591 s: port reconfigure.
  - lan8 alone at 157, 292, 815, 859 s (one 100 Mbit/s link at 175 s): during 2.5G partner tests (#90); lan1 3 s drop at 1002 s: partner side, unexplained.

## Image names

- `openwrt-ours` = 7.3 kernel (default-boot RAM test image, [DEFAULT-BOOT.md](DEFAULT-BOOT.md)); `openwrt-ours-6.18` = step 1.
- `./dev.py ramload openwrt-ours[-6.18]` / `--then openwrt-ours[-6.18]`: same bridge STP enforcement as `ramload openwrt`.
