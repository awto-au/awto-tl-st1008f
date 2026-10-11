# Local OpenWrt build (#73 track 1)

Operations: [OPENWRT-BUILD-OPS.md](OPENWRT-BUILD-OPS.md). Script: `scripts/build_openwrt.py` (`./dev.py build-openwrt`).

## Tree

| Item | Value |
|---|---|
| Buildroot | `tmp/openwrt-build` (gitignored), shallow clone of OpenWrt `main` |
| Commit | `e5ec5e199f13` (2026-10-11T22:45:51+02:00, "realtek: l3: rtl839x: do not invent a next-hop L2 entry") |
| Target | `realtek/rtl930x`, device `tplink_tl-st1008f-v2` only |
| Toolchain | OpenWrt-built, GCC 14.4.0 + musl 1.2.6 (`mips_24kc`) |
| Kernel (step 1) | OpenWrt 6.18.55 + our backports |
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

## Image names

- `openwrt-ours` = 7.3 kernel (default-boot RAM test image, [DEFAULT-BOOT.md](DEFAULT-BOOT.md)); `openwrt-ours-6.18` = step 1.
- `./dev.py ramload openwrt-ours[-6.18]` / `--then openwrt-ours[-6.18]`: same bridge STP enforcement as `ramload openwrt`.
