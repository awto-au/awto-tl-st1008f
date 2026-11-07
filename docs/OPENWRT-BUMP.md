# OpenWrt bump: b455c5b851 -> main (phase 1 research)

- Date 2026-11-07. Research only: store fetched, nothing built, no hardware, `tmp/openwrt-build` untouched.
- Store: `/mnt/2tb/git_mirror/openwrt/openwrt` (plain `git fetch origin`, no gc/depth).
- Claims: "git" = verified in the store with `git log/diff/show/grep`; "unverified" = inferred, test in phase 2.
- Dry-run apply of our `openwrt/patches/300-*` was attempted and is NOT a result: the working-tree patches
  (7.4-rc1 rebase in progress) already fail on the OLD files-6.18 (300-10/-11/-12/-17/-20/-25/-26/-27/-28) -> unverified.

## 1. Range summary

| Item | Old | New | Evidence |
|---|---|---|---|
| Commit | `b455c5b851` (2026-11-04) | `7e8bfcfe76` (2026-11-07, 'qualcommax: nbg7815: set kernel image size limit') | git |
| Commits | | 45 (`git rev-list --count`) | git |
| Of which realtek | | 10 realtek + 0 generic pending/hack changes that we copy | git |
| Default kernel | 6.18.x | 6.18.60 (`generic/kernel-6.18`); realtek `KERNEL_PATCHVER:=6.18` | git |
| Testing kernel | none | none: no `KERNEL_TESTING_PATCHVER` in realtek/Makefile, no `kernel-7.x` in generic | git |
| Toolchain gcc / musl | | unchanged (nothing under `toolchain/` changed) | git |
| apk / iproute2 / dropbear | | unchanged: iproute2 7.3.0, dropbear 2026.94 (Makefile PKG_VERSION identical) | git |
| busybox | 1.38.0-r4 | 1.38.0-r5: `FEATURE_EDITING_HISTORY` 256 -> 2000, `FEATURE_SH_HISTFILESIZE` n -> y | git |
| nftables / libnftnl / firewall4 | | unchanged (libnftnl 1.3.2, nftables 1.1.7, firewall4 files not in diff) | git |
| Other | | procd r2 (uvol volumes in mount helpers), `base-files` `path_normalize()`, uhttpd HEAD, mac80211 backports, video/DMA-BUF kmods, mpc85xx/rockchip/airoha/qualcommax targets | git |

- Net: small range. OpenWrt main has NO v7.x kernel; our 7.4-rc1 stays an overlay via `KERNEL_TESTING_PATCHVER` (set by `overlay_73`).
- `include/kernel.mk`, `package/kernel/linux/Makefile`, `package/Makefile` still use `$(subst -rc,_rc,...)` (git): `7.4-rc1` becomes apk-valid `7.4_rc1` with no extra patch.

## 2. target/linux/realtek changes

Files-6.18 diff (git, `git diff b455c5b851 origin/main -- target/linux/realtek`): 19 files, +1276/-111. patches-6.18, config-*, Makefile, modules.mk: unchanged.

| Commit | Change | Touches our overlay? |
|---|---|---|
| `5c5a157852` | rtl930x: `rteth_930x_hw_en_rxtx()` sets `CRC_CPU_RC_EN` (MAC_L2_GLOBAL_CTRL0 bits 24:23) = 1; new defines in rtl838x_eth.h | YES: rtl838x_eth.c/.h, ADOPT (below) |
| `c243368acc` | l3: all `sw_r32/sw_w32` -> `regmap_*`, error propagation | l3.c rewritten: our 300-10, 300-17 conflict (certain) |
| `216e4da863` | l3: `otto_l3_alloc_egress_intf()` takes MTU profile (ROUTE_MTU_ID 1, FLOW_MTU_ID 2) | l3.c, 300-17 conflict |
| `9d83aff346` | l3: `resource_lock` mutex; lock order RTNL -> resources -> registers | l3.c/l3.h, 300-17 conflict |
| `76ba875e0e` | l3: `otto_l3_flow_nexthop_get/put()`, `otto_l3_fasttrack()`; nothing enables fasttrack yet | l3.c/l3.h; groundwork for flowtable HW offload |
| `92ca2fdfa1`, `c75816c63e` | dsa: `l2_ctrl_0`, `l2_tbl_flush_ctrl` removed from `struct rtldsa_config` | rtl-otto.h, l2.c, rtl83xx/rtl93xx .c; 300-26 edits rtl-otto.h (context check) |
| `031659df7f` | dsa: RTL930x SABLK/DABLK setup moved from `rtldsa_port_enable()` to `otto_l2_930x_learning_setup()` | dsa.c, l2.c; no patch of ours touches either (grep of `+++ b/` lines) |
| `058f001086`, `4ec4ca8f06` | new boards Lianguo LG510S-4T2XS, Horaco ZX-SW82TS-L2P (+ `hasivo-web-factory.py`, `02_network` MAC helper `mtd_jffs2_get_mac_txt`) | none (other boards) |

Per OWRT_FILES entry (git: changed in range?):

| OWRT_FILES path | Changed upstream |
|---|---|
| `drivers/net/dsa/rtl83xx` | yes: l2.c, l3.c, l3.h, dsa.c, rtl-otto.h, rtl838x.c, rtl839x.c, rtl930x.c, rtl931x.c |
| `drivers/net/ethernet/realtek/rtl838x_eth.c/.h` | yes: +7 / +2 lines (FCS) |
| `mdio-realtek-otto*.c`, `pcs-rtl-otto.c`, `tag_rtl_otto.c`, `drivers/soc/realtek`, `realtek-thermal.c`, `otto_common.h`, `otto_table.h`, `mach-rtl-otto` | no |

Our patches vs changed upstream files (git, `+++ b/` of `openwrt/patches/300-*`):

| Our patch | File | Status |
|---|---|---|
| 300-10 (7.3 API drift), 300-17 (onlink/default route offload) | l3.c, l3.h | rewrite needed; rebase onto new l3.c |
| 300-26 (storm control) | rtl-otto.h, common.c, Makefile | rtl-otto.h hunk context near removed `l2_ctrl_0` members: unverified |
| 300-11/12/20/25/27/28/38/39/40 | rtl838x_eth.c/.h | upstream hunks are additive (hw_en_rxtx tail, one define each): small context shifts expected |
| 300-35/36, 300-37 | pcs-rtl-otto.c, tc.c | upstream unchanged: no conflict |

### Adopt instead of workaround

| Upstream | Action | Evidence |
|---|---|---|
| `5c5a157852` CRC_CPU_RC_EN=1 for RTL930x | Adopt as is (comes with the files copy). Check our NIC path (300-12/-20 and `shared/rtl930x-nic/rtl930x_nic.h`) and U-Boot for a competing write of MAC_L2_GLOBAL_CTRL0; delete any of ours. Our TX hands over an uncomputed FCS the same way | git; our-side write: unverified |
| l3.c regmap + error propagation (`c243368acc`) | Adopt; drop our `sw_r32` use in 300-17 additions, rewrite them with `regmap_*` | git |
| `resource_lock`, MTU profiles, flow next hop helpers | Adopt; 300-17 must take `resource_lock` where it touches shared tables | git |
| Flow offload groundwork (`fasttrack`, flow nexthop) | Watch: no consumer in tree (grep `otto_l3_flow_nexthop` only in l3.c/l3.h), no `ndo_setup_tc` flow block yet; nftables `flags offload` still cannot bind (docs/ROUTING-OFFLOAD.md) | git |
| 300-17 content | Not upstream: no `l3_onlink` / `l3_default_v4/v6` module params in new l3.c (grep: none); `!info->dst` still skips default routes (l3.c:3082). Keep, rebase | git |

- Not in this range (so no change to report): NIC page_pool/NAPI, PCS, MDIO, SFP, DSA core: `patches-6.18` unchanged (git). Latest realtek patches-6.18 and generic pending changes before the pin are already in our base.
- openwrt#25129 / #25555 (plappermaul L3): not named in these commits; the L3 series here cites PRs 26346, 26483, 26490, 26515, 26525 (git log bodies). Unverified relation.

## 3. Generic changes that matter

| Item | State in `7e8bfcfe76` | Evidence |
|---|---|---|
| pending `344` (csum_partial maddu), `644` (DSA vlan protocol), `645` (DSA mcast snooping), `700`/`701` (nft flowtable netdev events / EOPNOTSUPP) | all present, names unchanged, content unchanged in range | git |
| hack `910`, `911`, `940` | present, unchanged. Note `700-swconfig_switch_drivers.patch` (hack) is a different 700 | git |
| Upstream in v7.4-rc1? | `port_vlan_protocol` / mcast-snooping hook absent from `include/net/dsa.h`, `nft_flow_offload` handling absent, `maddu` absent in `arch/mips/lib/csum_partial.S` (store `tmp/linux-store`, tag v7.4-rc1): all five still needed | git |
| Only generic change in range | `hack-6.18/904-debloat_dma_buf.patch` (not copied by us) | git |
| nftables / firewall4 / kmod-nft-offload / flowtable | no package change | git |
| iproute2 7.3.0, dropbear 2026.94 | no change | git |
| procd | r2: `procd.sh` mount helpers find uvol volumes; init START numbering untouched | git |
| netifd | not in diff | git |
| Our init scripts (`st1008f-linkcheck`, `-linkwatch`, `-mode` START=19; `-slot`, `-metricsd`, `-selftest`, `-bootok` START=99) | no upstream change affecting START order; 19 < network 20 still holds | git (files) / unverified (runtime) |
| `perf` apk version string | `perf` PKG_VERSION=`$(LINUX_VERSION)`; OpenWrt maps `-rc` -> `_rc` only. For the v7.4-rc1 tag the version is `7.4-rc1` -> `7.4_rc1`, valid. Our `-next-` -> `_p` sed in `overlay_73` (build_openwrt.py:383) is dead once the base is a tag: delete it (no workaround kept) | git |
| Test/RC kernel naming | No new mechanism: `KERNEL_TESTING_PATCHVER` + `generic/kernel-<PV>` file with `LINUX_VERSION-<PV> = -rc1`, hash `skip` (what `overlay_73` writes) | git |
| Kernel perf package | Still `@KERNEL_PERF_EVENTS` dep; with a tag version `CONFIG_PACKAGE_perf=y` may now be installable (RAM boot has all built in anyway): try once in phase 2 | unverified |

## 4. New features to use

| Area | State | Use |
|---|---|---|
| Boards | LG510S-4T2XS, ZX-SW82TS-L2P (RTL9303/9302) | none for ST1008F |
| L3 offload | regmap + locking + MTU profiles + flow next hop helpers (prep only) | rebase 300-17; re-measure routing after bump (docs/ROUTING-OFFLOAD.md) |
| Hardware flow offload | prepared, not enabled (`fasttrack` never set) | monitor `realtek: l3:` commits; no action |
| Thermal / LED | no change in range | none |
| Bench packages | SEED already has iperf3, tcpdump-mini, ethtool-full, tc-full, ip-full, kmod-pktgen; devmem via busybox (`BUSYBOX_CONFIG_DEVMEM`); busybox now has shell history 2000 + `HISTFILESIZE` | no change; history is a free console quality gain |
| Build system | no ccache/apk index change in range; FEEDS pinned `packages` `5a350e9`, `luci` `59b4e33` (build_openwrt.py:234) must move with the pin | move feeds in phase 2 (feeds are separate repos: not examined, unverified) |
| Kernel config symbols | `rtl930x/config-6.18` unchanged in range: SEED/PORT73 symbols that moved: none from OpenWrt side; the 7.4-rc1 Kconfig churn is the risk (`--regen-config` fails if a PORT73 symbol does not survive) | git / unverified |

## 5. Bump plan (phase 2)

Prerequisite: the other agent's GDMA build in `tmp/openwrt-build` must finish first. `./dev.py build-openwrt --update` runs `reset_overlay()` + `git reset --hard FETCH_HEAD` in that tree, which destroys an in-flight build. Do not start before it ends and its image is booted/archived.

Steps:
1. Edit `OWRT_COMMIT` in `scripts/mainline_build_check.py` to `7e8bfcfe76204efc9433be341642901876eb555b` (or newer `origin/main` at that time); update comment.
2. Move `tmp/openwrt` (`OWRT_PIN`, source of `OWRT_VERBATIM`/`OWRT_FILES`) to the same commit: `overlay_73` exits if `tmp/openwrt` HEAD != `OWRT_COMMIT`. `--update` moves only `tmp/openwrt-build`, not `tmp/openwrt`.
3. `./dev.py build-openwrt --kernel mainline --prepare-only --update`: kernel tree patched, stops before the world build; read rejects.
4. Rebase patches with `scripts/patch_rebase.py` against the new files-6.18; expected rejects: 300-10, 300-17 (l3.c), possibly 300-26 (rtl-otto.h). Keep `OWRT_FILES` list unchanged (no entry added or removed upstream).
5. Delete our own workarounds the new tree covers: any CRC_CPU_RC_EN write of ours; `-next-` -> `_p` sed in `overlay_73`; revisit the `include/image.mk` `-Wno-graph_child_address` edit (check it still applies; unverified).
6. `PENDING73`/`HACK73` unchanged. `OWRT_GENERIC_PENDING` (`344`, `644`) unchanged. Verify the pending patches still apply on the 7.4-rc1 tree (dry-run in `--prepare-only`).
7. Move `FEEDS` commits (packages, luci) to the feed heads matching the pin.
8. `./dev.py build-openwrt --kernel mainline --regen-config` -> new `openwrt/kernel-7.4/config-7.4` (old dir `kernel-7.3` is selected by `PV`; rename via git mv, `config73()` is PV-keyed). Review the diff; fix `PORT73` failures.
9. Full `./dev.py build-openwrt --kernel mainline` (not `--kernel-only`: config changed). Also `./dev.py build-openwrt` (6.18 step 1) to confirm the 6.18 path with the new tree.
10. How kernel_base interacts: `PIN` (Linus tag, now v7.4-rc1) gives `PV=7.4`, `VER=7.4-rc1`; `overlay_73` writes `KERNEL_TESTING_PATCHVER:=7.4` into realtek/Makefile and `generic/kernel-7.4`. OpenWrt main itself has no testing kernel, so no conflict. A new Linus tag = `kernel-base update` + `patch_rebase.py` only, independent of this bump.

Expected breakages (all unverified until phase 2):
- 300-10, 300-17 against regmap l3.c; 300-17 locking.
- 7.4 API drift in the Kconfig/driver glue (300-08/-09 PCS provider and Kconfig hooks).
- `config-7.4` dropped symbols.
- `Makefile` string replace in `overlay_73` (`KERNEL_PATCHVER:=6.18\n`) still matches (git: same line).
- Stale `kernel-7.3` dir/name references in scripts (`config73()`, PORT73 warnings).

Bench test list (RAM boot only, sw2 only, never sw1; `./dev.py ramload openwrt-ours` flows; reboot in software):
1. `ramload` boots; `./dev.py check-log` clean against `scripts/boot_log_allowlist.txt` (new warnings reviewed + issue).
2. Both VPEs tick; BogoMIPS; kernel version string `7.4-rc1`; `uname -r` and `apk` accept it.
3. Links: lan1 10G, SFP cages per hardware table; STP/linkcheck ordering at boot (START=19 before network).
4. FCS check: CPU-originated frames reach link partner (ping/ARP both directions) with upstream CRC_CPU_RC_EN, with our write removed.
5. L3: 300-17 params (`l3_onlink`, `l3_default_v4/v6`) off by default: routing sanity; then on: gateway-routed and on-link throughput (docs/ROUTING-OFFLOAD-OPS.md).
6. NIC path regression: `nat_matrix.py` / `cpuport_speed_ab.py` short run vs last result; no `--rounds` loops.
7. Storm control (300-26) loop-detect sanity; tc flower tcp flags (300-37).
8. `perf` (kernel PC sampling), `devmem`, iperf3, tcpdump, ethtool present.
9. `st1008f-slot`, `-bootok`, `-mode` init scripts run (logread).
10. 6.18 step-1 image (`build-openwrt` without `--kernel`) boots on sw2 for comparison.

Phase 2 can start immediately for steps 1-4 (edit pin, `--prepare-only` in a way that does not reset the live tree is NOT possible: `--update` resets `tmp/openwrt-build`). Steps involving `tmp/openwrt-build` wait for the GDMA build.

## 6. Phase 2 results (2026-11-07, build only, no hardware)

Pin `7e8bfcfe76` (store head, same as phase 1), kernel `v7.4-rc1`, feeds `packages` `1c248d7e25`, `luci` `9a62efcc5a`.

| Item | Result |
|---|---|
| Series on new files-6.18 | all 41 patches apply; only 300-17 (4 hunks) and 300-20 (1 hunk) needed hand work; 300-10/12/25/37 had fuzz-2 hunks, regenerated with `patch_rebase.py` |
| 300-17 (on-link neighbours, default routes) | rebased: includes, v6 host hash in `find_slot()` (regmap read), neighbour hook in the net-event worker, flush worker. Locking: `l3_neigh_update()` and the poll take RTNL then `resource_lock` (upstream order); fib event hooks already run under both. `alloc_egress_intf()` takes `ROUTE_MTU_ID`. Still not upstream |
| 300-10 | regenerated, content unchanged |
| 300-20 (shared NIC core) | `rteth_930x_hw_en_rxtx()` = `rtl930x_nic_enable()` + upstream `CRC_CPU_RC_EN=1` write kept (taken on; no competing write of ours existed; `uboot-port/` has no `MAC_L2_GLOBAL_CTRL0` write either, report only) |
| 300-26 / 11 / 27 / 28 / 38..41 | apply without edits |
| Plain kernel build with the series | `mainline_build_check.py`, 0 warnings, rc 0 |
| `overlay_73` | `-next-` -> `_p` sed deleted; `modules_link` deleted (release string is `7.4-rc1`, kmods land in `lib/modules/7.4-rc1`); `NO_RUST/NO_MYPY` set in `run()` |
| `perf` apk | NOT usable: perf Makefile uses raw `7.4-rc1` as apk version ("package version is invalid"); with a `_rc` fix the image unpacks to 34.0 MiB > 32 MiB `SYS_BOOTM_LEN`. Dropped from SEED; use `scripts/build_perf.py` |
| `--regen-config` | passes; failure cause was `ST1008F_SRAM_BENCH` depending on `CONFIG_SRAM`, now in `PORT73`. `openwrt/kernel-7.3/config-7.3` -> `openwrt/kernel-7.4/config-7.4` |
| Pending 344/644/645/700/701, hack 910/911/940 | apply as in phase 1; `include/image.mk` edit still applies |

Process note: running `mainline_build_check.py` / `patch_rebase.py` rewrites the shared `tmp/linux-v7.4` tree and `tmp/patch_rebase.index`; an in-progress `300-42` snapshot of another session was clobbered (garbage copy: `tmp/300-42-clobbered-by-owrt-bump.patch`), regenerate it on the new base.

Images (`build_openwrt.py --kernel mainline [--debug]`, rc 0 each):

| Image | Size (B) | Unpacked |
|---|---|---|
| `openwrt-ours-initramfs.bin` / `-std` | 8,159,118 | 25.3 MiB |
| `openwrt-ours-debug-initramfs.bin` / `-std` | 8,225,235 | 25.6 MiB |

- Load: TFTP to `0x84f00000`, `bootm` decompresses to `0x80100000`; limit `SYS_BOOTM_LEN=0x2000000` (32 MiB unpacked). Same load address for both.
- Debug kernel: `DEBUG_LIST`, `SLUB_DEBUG_ON` (OpenWrt symbol `KERNEL_SLUB_DEBUG_ON`), `DEBUG_NET`, `PAGE_POOL_STATS`, `DEBUG_VM` (`KERNEL_DEBUG_VM`), `PAGE_POISONING`. MIPS has no KASAN, KFENCE, DEBUG_PAGEALLOC.
- Bench: `./dev.py ramload openwrt-ours`, `./dev.py ramload openwrt-ours-debug`, `./dev.py ramload openwrt-ours-7.3` (old A/B); test list in section 5.
