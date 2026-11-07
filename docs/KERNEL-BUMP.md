# Kernel bump: v7.3-rc6 / next-20261009 -> v7.4-rc1

Owner decision 2026-11-07: base = Linus's latest tag; adopt upstream network-layer changes, keep no workarounds. Desk research only (no hardware, no commits).

- Tags in the store (`tmp/linux-store`): newest Linus tag is `v7.4-rc1` (2026-11-01, `6628e7d4c6b2`). `v7.3` final (2026-10-18, `c03c1a14507d`) and `v7.3-rc7` exist but are not our base. rc2 not in the store (due ~2026-11-08, unverified).
- `next-20261009` = `becb95e45ef0` (2026-10-10), Makefile 7.3-rc6 + next. Not an ancestor of `v7.4-rc1`; merge-base `8a017ab98412`.
- "verified in git" = checked with `git -C tmp/linux-store` (log/diff/grep/ls-tree at the tag). "build" = `tmp/logs/build-kernel-7.4.out`, `tmp/logs/mainline_build_check.log` (2026-11-07 11:17-11:18 +11:00). "unverified" = web/lore only or inferred.
- 7.4 is expected to be the next LTS (It's FOSS 2026-11-04, unverified claim by Linus/Phoronix): https://itsfoss.com/news/linux-7-4-huge-merge-window/

## Summary

| Item | Count |
|---|---|
| Commits v7.3-rc6..v7.4-rc1 (non-merge) | 19188 (verified in git) |
| ...touching net/phy/pcs/mdio dirs | 84 |
| Realtek Otto driver files upstream in rc1 | 17 (list below); no DSA, CPU-port NIC, PCS, SerDes MDIO, thermal, LED upstream (verified: `git ls-tree`, identical file set at rc6, next, rc1) |
| Our patches in `openwrt/patches/` | 38 files |
| Needing a refresh for rc1 | 1 (300-08; rewrite already in `openwrt/patches-v7.4-rc1/`) |
| Dropped because upstream | 0 |
| Superseded in-tree (not applied on any base) | 3 (300-29, 300-31, 300-34; `scripts/kernel_base.py` SUPERSEDED) |
| Breaking API changes hitting our code | 0 compile breaks (build: 0 warnings, rteth, DSA, PCS, GDMA all `=y`) |
| New upstream facility that removes a workaround | 0 verified |
| Upstream bugs still open at rc1 | 1 (flowtable HW offload Ethernet mangle on big-endian, #85) |

- Upstream Realtek files (rc1): `rtl930x.dtsi`, `rtl9302c.dtsi`, `rtl838x.dtsi`, two board DTS, `irq-realtek-rtl.c`, `timer-rtl-otto.c`, `timer-realtek.c`, `gpio-realtek-otto.c`, `i2c-rtl9300.c`, `spi-realtek-rtl.c`, `spi-realtek-rtl-snand.c`, `mdio-realtek-rtl9300.c`, `realtek_otto_wdt.c`, `net/dsa/realtek/*` (rtl8365/8366 SMI/MDIO switches, different family).
- Most 7.4 Otto content (mdio RTL83xx, gpio pinctrl, spi second CS, `arp_table()`) is already in `next-20261009`, so next->rc1 is small for Otto. Per-area next->rc1 diff (verified): `drivers/dma` 8+/9-, `arch/mips` 7+/21-, `include/net/page_pool` 3 files tiny (kernel-doc), `net/core` ~2k lines (hardening, devmem, bpf).
- Web: merge window 18591 non-merge changesets (LWN via Linux News): https://www.linuxnews.net/articles/the-second-part-of-the-7-4-merge-window ; rc1 mail https://lwn.net/Articles/1104653/ . Otto mdio RTL83xx series (Markus Stockhausen, v3 2026-07-05): https://lwn.net/Articles/1081360/ . kernelnewbies has no `Linux_7.4` page yet (fetched 2026-11-07).

## Our patches vs the new tag

Method: `git apply --cached -C1` of each patch alone onto a scratch index of each tag (verified); patches that edit OpenWrt-overlay files (rtl838x_eth, rtl83xx DSA, pcs-rtl-otto, tc.c) cannot be tested alone, so their verdict comes from the full-series build on rc1 (build, 0 warnings, rc1 tree `tmp/linux-v7.4`). Board behaviour on rc1 is untested.

| Patch | Verdict | One line |
|---|---|---|
| 300-04 dram prefetch | needed, unchanged | `board-realtek.c` is an OpenWrt platform file; no upstream change |
| 300-05 hpt from PLL | needed, unchanged | same |
| 300-06 mode-switch driver | needed, unchanged | applies alone on rc1; `drivers/platform/mips/{Kconfig,Makefile}` identical rc6/next/rc1 |
| 300-07 SPI dirmap read | needed, unchanged | applies alone on rc6/next/rc1; `spi-realtek-rtl.c` has no dirmap upstream (grep 0); next==rc1 for the file |
| 300-08 phylink fwnode PCS | NEEDS REFRESH | applies alone on rc6 and next, fails on rc1: `pcs/Makefile` + `pcs/Kconfig` (xpcs split) and `phylink.c` hunk 19; see below |
| 300-09 Kconfig/Makefile hooks | needed, applies | applies alone on next and rc1; fails alone on rc6 (Kconfig context; 7.3 copy exists). DSA tag value 37 unchanged, KS8995 sits below it (verified `include/net/dsa.h`) |
| 300-10 API fixes (l3.c) | needed, unchanged | build OK; uses `arp_table(&init_net)`/`nd_table()` which exist in next and rc1, not rc6 |
| 300-11 TX ring32/BQL/xmit_more | needed | build OK; no ndo/BQL API change in rc1 |
| 300-12 NIC path (RTL930x) | needed | build OK |
| 300-13 HIGHMEM lowmem DMA sync | needed | build OK; `arch/mips/mm/dma-noncoherent.c`, `mm/highmem.c` unchanged rc6..rc1; `include/linux/mm.h` churn (168 lines next->rc1) did not conflict (build) |
| 300-15 wdt keep running | needed | `realtek_otto_wdt.c` unchanged rc6..rc1 |
| 300-16 port LEDs | needed | applies alone on all three |
| 300-17 L3 on-link/default route | needed | build OK |
| 300-18 irqchip single-CPU affinity | needed | `irq-realtek-rtl.c` and `cpuhotplug.h` anchor unchanged (verified) |
| 300-19 cmdline once | needed | platform file |
| 300-20 shared NIC core | needed | build OK |
| 300-21 keep SRAM mapped | needed | platform file |
| 300-22 SRAM bench | needed | applies in series; `drivers/misc/Kconfig` context drifted (13 lines next->rc1), build OK |
| 300-23 LX clock from PLL | needed | |
| 300-24 wdt clamp hw timeout | needed | `realtek_otto_wdt.c` unchanged |
| 300-25 rings in SRAM | needed | |
| 300-26 storm control/loop detect | needed | |
| 300-27 select_queue no hash | needed | |
| 300-28 RX desc cached read | needed | |
| 300-29 / 31 / 34 | not applied (superseded by OpenWrt PCS/L3 rework, #142) | state per `scripts/kernel_base.py`; files still in `openwrt/patches/`: delete or re-port |
| 300-30 aquantia hwmon clamp | needed | upstream `aquantia_hwmon.c` still has `-ERANGE` (line 60), no aquantia commits rc6..rc1 |
| 300-32 jffs2 / 300-33 mtdsplit | OpenWrt-image only | not applied on mainline builds (`OPENWRT_ONLY`) |
| 300-35 / 36 PCS debugfs/clock-sync | needed | overlay file; build OK |
| 300-37 tc flower TCP flags | needed | build OK; `cls_flower.c` fixes in rc1 do not change the key set we use (unverified in depth) |
| 300-38 debugfs rxq steering | needed | |
| 300-39 zc forward prototype | needed | uses `page_pool_put_full_page`/`get_dma_addr`, unchanged API |
| 300-40 CPU queue drop threshold | needed | |
| 300-41 GDMA dmaengine driver | needed, see dmaengine | `drivers/dma/{Kconfig,Makefile}` context drifted vs rc6 only; builds on rc1 (`CONFIG_RTL9300_GDMA=y`) |

- 300-08 detail: rc1 split `pcs-xpcs-plat.o` out of `pcs_xpcs-y` (`PCS_XPCS_PLATFORM`, `PCS_XPCS_ROCKCHIP`, commit `b9e7cb89aac8` and neighbours) and phylink gained phy_port bookkeeping (`b8335326fe06`, `51ebb13c1d96`, `9e7cd33fafb2`). `phylink_config` wol fields unchanged vs next. Upstream still has no fwnode PCS provider: `git grep fwnode_pcs_add_provider|fill_available_pcs|num_possible_pcs` empty at next and rc1 (verified). Series stays ours until Christian Marangi's series lands (unverified status on lore).
- `openwrt/patches/300-08` and `openwrt/patches-v7.4-rc1/300-08` are both rewritten by the porting agent (log `tmp/logs/patch_rebase.log` 2026-11-07T11:14); not re-checked here.

## Breaking changes to adopt now

None break the build. Changes that touch code we carry, in order of relevance:
- Per-netns neigh tables: `arp_table(net)` / `nd_table(net)` (commits `2430df635a59`, `df5f4f372de5`, `cda2962b6e2b`; in next and rc1, not rc6). Our `l3.c` pins to `&init_net`: offload ignores other netns. Adopt: either reject offload when `dev_net(dev) != &init_net` or iterate per net. Verified in `tmp/linux-v7.4/drivers/net/dsa/rtl83xx/l3.c` (lines using `arp_table(&init_net)`).
- `nd_tbl` is still exported as a template only (`include/net/ndisc.h:68`); our `#define nd_tbl (*otto_l3_nd_table())` shim in `l3.c` is the workaround. rc1 also removed `__neigh_lookup()` (`29ff0101dc00`) and renamed `ipv4_neigh_lookup()` -> `ipv4_dst_neigh_lookup()` (`07cc2b151a26`); we use `neigh_lookup()` only (grep), so no hit. Replace the macro shim with explicit `nd_table(&init_net)` calls (cleanup, no behaviour change).
- dmaengine provider header split, `511afae96d89`: `dma_async_device_register()`, `dmaenginem_async_device_register()`, `dma_async_device_unregister()`, `is_slave_direction()` moved from `<linux/dmaengine.h>` to private `drivers/dma/dmaengine.h`. In-tree driver fine (builds). The out-of-tree `kmod/rtl9300_gdma/rtl9300_gdma.c` calls `dma_async_device_register()` and `#include "dmaengine.h"`: it needs the private header on its include path on 7.4 (will not find the prototype from the public header). Verified in git (diff of `include/linux/dmaengine.h`); kmod not rebuilt here.
- `dma_chan::dev` is now a union with `chan_dev` (`6ad1b49cc30d`), helpers `dmaengine_chan_dev()` / `vchan_chan_name()`: use the helpers in the GDMA driver, never `chan->dev` directly. Our driver does not (grep).
- `net: remove ndo_do_ioctl handler` (`d98a52ae914e`), `skb_unshare()` -> `skb_unclone_full()` (`258c3ae4a4af`), `get/put_netmem` renames (`2620efb2cec1`): no use in rteth/DSA/tag_rtl_otto (grep 0).
- `net: reject ops-locked drivers without ndo_set_rx_mode_async` (`05fe748456ea`): applies only to drivers that opt into netdev instance locking; rteth does not (unverified: check `request_ops_lock`/`netdev_need_ops_lock` never set).

## New features to use (ranked)

Result: 7.4 adds nothing for the CPU-port ceiling. The page_pool, GRO, NAPI core are unchanged apart from kernel-doc and netmem renames (`git log` over `net/core/page_pool.c`, `include/net/page_pool/`, `net/core/gro.c`: only `47dbcfdf942a` kdoc, `679f6929a66d`, `de788d8a7032`, `4e3b56eb2ed8`). Items below exist at all three points (so not "new in 7.4") but are unused by us; each is a candidate, benefit unmeasured.

1. page_pool sync length (existing, unused). `rteth_probe()` creates the pool with `PP_FLAG_DMA_SYNC_DEV`, `max_len = PAGE_SIZE`, `offset = 0`, frag size 2048 (`RTETH_PPOOL_FRAG_SIZE`). Recycling via `page_pool_put_full_page()` syncs `min(-1, max_len)` = whole 4 KiB page from page start (`__page_pool_dma_sync_for_device`, rc1 `net/core/page_pool.c:450`), not the used ~1400 B and not the frag's offset. On non-coherent MIPS this is an invalidate of 4 KiB per recycled page. Candidate: set `max_len` to frag size minus headroom and `offset` to headroom, or drop `SYNC_DEV` and invalidate only `frag->len` rounded to cache line in the refill path; test with `rxdrop` (137 kpps at 1400 B, `docs/CPU-PORT.md`). Verified from source; effect on the ceiling unverified (CPU-PORT.md says the ceiling is almost clock independent, so a CPU-side sync saving may not move it).
2. `page_pool_put_page(pool, page, len, true)` with the real length on the TX-completion/zc path (300-39) instead of `put_full_page`: same reason, verified API.
3. Cache-line-tight RX descriptor/buffers, `napi_build_skb` + `skb_mark_for_recycle` + `napi_consume_skb`: already used (`rtl838x_eth.c` lines 689-716, 1396-1403). `napi_gro_receive` used; fraglist GRO on at boot (`docs/NAT.md`).
4. GRO fraglist hardening (`679f6929a66d`, `de788d8a7032`, re-segmentation of oversized TCP GSO `c4076626ba52`/`32bfd220cd6f`): keeps fraglist-GRO'd skbs forwardable to an egress device without `NETIF_F_FRAGLIST` (our rteth/DSA). Relevant to the forward-after-GRO path; no code change, take for free.
5. Threaded NAPI / busy-poll / IRQ suspend: present since 6.x, not changed in 7.4 (log empty). Untried on this board: `napi_threaded` per queue could move RX off VPE0 softirq; effect unmeasured.
6. XDP / XDP_REDIRECT: no `ndo_bpf` in rteth; `xsk_pools` added to `net_device` (`include/linux/netdevice.h` next->rc1). Not a quick win on a 34Kc; skip unless a driver-level fast path is wanted.
7. `net: skbuff: shrink the payload-only part of dataref` (`4957ea03bf26`) and skb helper hardening: free; no API change for us (unverified perf effect).
8. SFP / phy_port: rc1 registers an SFP cage phy_port in phylink (`b8335326fe06`) and tracks ports in `phy_link_topology`; `ethtool` port info for our 8 cages becomes available once 300-08 is refreshed. New SFP quirks that help the lab: `01b99e9d0d62` TP-LINK SM410U, `a9e94a7faa56` XikeStor SKT-2.5G-100M, `0fd5dfa99cfc` ignore LOS on Hisense GPON (all verified in git, in rc1; SM410U is in rc1 not next).
9. Diagnostics (see below).

## Workarounds we can delete

None verified deletable on rc1.
- 300-08 phylink fwnode PCS: remains (upstream has no provider).
- `nd_tbl` macro shim in `l3.c`: replace with `nd_table(&init_net)` (cleanup, not a deletion of function).
- Big-endian flowtable HW offload: bug still in rc1 `nf_flow_table_offload.c` (`flow_offload_eth_src`: `memcpy(&val16, addr, 2); val = val16 << 16;`, lines 266-269; no commit touches the file rc6..rc1). Our driver decode-by-numeric-value workaround (#85, `docs/NAT.md`) must stay; send the upstream fix instead. Verified in git.
- Open question: whether upstream `mdio-realtek-rtl9300.c` (now RTL838x/839x/930x with polling control, page tracking, clock-frequency, commits `6ab6cb66b3b9`, `11b8be84ccaf`, `cc3cb8db1eef`, `72356fed7965`) can replace `mdio-realtek-otto` for the MDIO part; SerDes access stays in `mdio-realtek-otto-serdes`. `MDIO_REALTEK_RTL9300` is off today ("OTTO fork used", `docs/MAINLINE-PORT.md` §8). If adopted we delete the fork's MDIO half per the "take the upstream network layer" rule. Unverified: DT binding and register-access parity.

## Risks / regressions

- Size: rc1 is the largest merge window ever (19671 commits, Phoronix via It's FOSS); expect rc2/rc3 fix churn in `net/core` skbuff/GSO (many `BUG()` -> warn conversions, `7b32bee7db82`, `c7d8bc3dd511`) that is behaviour-sensitive on our fraglist/forward path. Re-run the NAT bench (`docs/NAT.md` picks clocks) and compare with the 7.3 numbers before making rc1 default.
- `ca6854799069` / `f12d2907992d` batch `rt_flush_dev()`/`rt6_uncached_list_flush_dev()` in `netdev_run_todo()`: changes device unregister timing; check `rmmod`/rteth unload.
- `0cb17268887e` (MIPS huge-TLB probe) and `975d4a6a6d4d`: only with hugetlb/THP; we run neither (unverified in our config).
- DSA: `include/net/dsa.h` tag value 37 still free of clashes at rc1 (verified); a new upstream tag taking 37 later would collide again.
- Fallback `v7.3-rc6` lacks `arp_table()`: `openwrt/patches-v7.3-rc6/` copies of 300-10/300-17 must stay in sync.
- OpenWrt side: newest dir is `files-6.18`/`patches-6.18` (`docs/MAINLINE-PORT.md`); OpenWrt's generic pending patches (700, 701, 910, 911, 940) are not re-tested here (unverified on rc1).
- The 7.4 build was done by another agent on a working tree with uncommitted changes; this doc did not rebuild.

## Diagnostics now available (item 5)

- `6fd3ecb72486` watchdog: force console verbose when reporting lockups (soft-lockup detail not dropped at low `loglevel`). We have no hard-lockup detector on MIPS; relevant for soft lockups only.
- `36dd57d0ae96`, `e614d360f387` hung_task: summary line when the warning budget is exhausted and budget reset after recovery.
- panic: `97c358198e73` `arch_do_panic()` hook (MIPS could print VPE state; not implemented), `73554d8db495`/`36c55a9625bb` force-CPU redirect fixes: no MIPS action.
- pstore/ramoops hardening (`7c756181175d`, `1b30df8662ac`, `70fec428c845`): bugfixes only. Ramoops needs a reserved RAM region that survives our U-Boot reset; not configured. Candidate: ramoops in SRAM (`300-21` keeps it mapped) or reserved DDR to keep panic text over `reset`; unverified feasibility, boot-loader must not clear it.
- `f929e61143a2` `lib/test_csd_lock`: stall a CPU on a CSD lock; useful to test VPE cross-call watchdog behaviour (module, test only).
- Nothing new for bus-error / LX-timeout handling: `arch/mips/kernel/traps.c` unchanged rc6..rc1 (no commit in `git log arch/mips`). perf: `d8fd56321d7b` fixes libdw stack reading of a 32-bit task (helps unwinding a MIPS32 profile on an x86 host); `arch/mips/kernel/perf_event_mipsxx.c` unchanged. Our existing `kernel perf+kallsyms` image needs no change; the zc-bench `gro_list_prepare` panic (#149) is not addressed by anything in rc1 that I found (the GRO commits above are the nearest; unverified).

## dmaengine (item 3)

- Core API for a memcpy provider unchanged in substance: `dma_cap_set(DMA_MEMCPY)`, `device_prep_dma_memcpy`, `dma_cookie_*`, `vchan` (`virt-dma.[ch]` only gained `vchan_chan_name()`, `75d8640d7f5f`). Verified in git.
- New helpers consumers may use: `dmaengine_get_copy_align()` and `dmaengine_is_*_aligned()` (`072975a8a578`, `11e801ccaca7`), `dmaengine_has_cap()` (`bbc109e0e686`), `dmaengine_desc_set_callback()` (`562b6ed45db5`). Set `copy_align` in the GDMA driver so consumers can check alignment.
- `f54701da5c05` static channel IDs: optional for our 1-2 channel layout.
- `docs: dmaengine: clarify ordering rules around cookie completion` (`fa89be96e845`): re-read before finalizing completion order in `rtl9300-gdma.c`.
- async_tx / "migrate_offload" memcpy-offload series: not in rc1 (`git grep migrate_offload|folios_mc_copy` empty in `mm`, `include`, `drivers/dma`); mm/migrate.c has only cleanups. Unverified status on lore.
- `641a9b9cc697` DMA fallback uses exact page allocation: ring/descriptor `dma_alloc_coherent` sizes that are not powers of two now waste less; MIPS non-coherent allocs go via `arch_dma_set_uncached`, unaffected otherwise (unverified).

## MIPS / MT (item 4)

- `git log v7.3-rc6..v7.4-rc1 -- arch/mips`: only unrelated work (BPF JIT, Octeon, DEC, vdso, header removals, 2 hugetlb/THP fixes). `smp-mt.c`, `mips-mt.c`, `c-r4k.c`, `dma-noncoherent.c`, `cevt-r4k.c`, `perf_event_mipsxx.c` untouched. No 34Kc cache-op or MT change to adopt (verified).
- `dma-mapping` `95d2fec40c48` rename `dma_opt_mapping_size()`; `4733f2966433` dma-debug MMIO: no effect.
- `arch/mips/net/bpf_jit_comp*.c` gained BSWAP/JMP32_JA/MOVSX/SDIV (7 commits): only matters if BPF JIT is enabled on the image (cBPF/eBPF in nft is not JIT-dependent).

## Not relevant

- r8169 phylink/RTL8127 (`8a3c76523e44`, `97dee72abc37`), `rtase`: other NICs.
- PHY drivers RTL8224/RTL8261/RTL8211F/RTL8365MB (`realtek_main.c`): no copper PHYs on this board (verified in `docs/MAINLINE-PORT.md` §8).
- `net/dsa/realtek` rtl8365mb EEE/VLAN/supplies: different switch family.
- Rockchip XPCS (`b9e7cb89aac8`), Lynx 25GBASE-R (`e8965b0523f2`), RZN1 MIIC: other SoCs; only the `pcs/Makefile`/`Kconfig` context change matters for 300-08.
- Bridge FDB/VLAN rework (`a39c339fd6c5` ... `f1829618e0ad`, ~40 commits): software bridge only. Our offload goes through DSA `switchdev` notifiers, which these commits do not alter in signature (build OK); runtime behaviour of vlan-aware bridge FDB offload on rc1 untested.
- devmem/netmem TX, queue leasing, `netdev_config`, AF_PACKET multicast dumps, `pacing_offload`, RSS key generation: no rteth support/use.
- `act_ct`, `cls_flower` ERSPAN/mask fixes (`58f7989da6e7`, `e0edf25f141a`): no ERSPAN match in our tc.c.
- nf_flowtable tunnel (`d0107f381622`, `3dcafe6cb5e1`, `97874c7c5f2c`), VLAN-id key (`c203ecf90574`): software flowtable path; our `TC_SETUP_FT` callback does not offload tunnels. `net/netfilter/nf_flow_table_ip.c` changed 176 lines next->rc1: re-run the flowtable NAT bench.
- ARM/x86/KVM/AMD GPU churn.

## Open questions

- Does an upstream path exist for the phylink fwnode PCS series (status on lore/netdev)? Not found in this research (searches returned only the Otto mdio threads: https://lwn.net/Articles/1073745/ , https://lwn.net/Articles/1089358/ , https://lwn.net/Articles/1081360/ ); unverified.
- Should `mdio-realtek-otto` (MDIO half) be replaced by upstream `mdio-realtek-rtl9300`? Needs a DT/binding parity check.
- Does the page_pool sync-length change (feature 1) move the 1400 B ceiling? Needs a bench with `rxdrop`; the clock-independence in `docs/CPU-PORT.md` suggests a modest gain at best.
- `kmod/rtl9300_gdma` and `kmod/gdma_bench` need rebuild against rc1 headers; confirm the private `dmaengine.h` include (or keep only the in-tree driver).
- Release timing: rc2..rc7 vs waiting for v7.4 final; the repo pin is `PIN = "v7.4-rc1"` in `scripts/kernel_base.py`.
- Netns scope of `l3.c`: reject non-`init_net` devices or support them?
