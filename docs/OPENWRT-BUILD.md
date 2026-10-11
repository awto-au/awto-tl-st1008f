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

`--kernel 7.3`: OpenWrt's `KERNEL_TESTING_PATCHVER` mechanism, same OpenWrt main tree and userspace.

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

## Image names

- `openwrt-ours` = 7.3 kernel (default-boot RAM test image, [DEFAULT-BOOT.md](DEFAULT-BOOT.md)); `openwrt-ours-6.18` = step 1.
- `./dev.py ramload openwrt-ours[-6.18]` / `--then openwrt-ours[-6.18]`: same bridge STP enforcement as `ramload openwrt`.
