# NAT stack comparison plan: upstream OpenWrt vs ours vs plain kernel

Status 2026-11-08: plan + config audit + images prepared. Nothing run on hardware. Existing published numbers: [NAT-STACKS.md](NAT-STACKS.md) (audit, legend, gaps), [NAT.md](NAT.md).

- Owner request 2026-11-08: drop the "unknown" rows; one clean comparison on the same kernel generation.
- Every figure from this plan states its profile: **clean** (no tracing, numbers) or **profile** (perf / ftrace on, diagnosis only). Profile figures never share a table with clean ones.
- Driver (dry-run only): `python3 scripts/stack_compare.py [--stacks A,B,C] [--clocks common,final] [--profile clean|profile|both]`; log `tmp/logs/stack_compare.log`. `--run` is refused.

## The three stacks

| | Kernel | Userland | Patches | Image (RAM boot) |
|---|---|---|---|---|
| A upstream | Linux 6.18.60 | OpenWrt SNAPSHOT r38188-7efbba7631 (2026-11-07 20:23 GMT), fw4 | none | `tmp/upstream-snapshot/dl/openwrt-realtek-rtl930x-tplink_tl-st1008f-v2-initramfs-kernel.bin` |
| B ours-OpenWrt | Linux 7.4-rc1 | OpenWrt main r38178-7e8bfcfe76 | full series | `tmp/tftp/openwrt-ours-l3fix2-initramfs.bin` |
| C plain | Linux 7.4-rc1 (`7.4.0-rc1-dirty`) | bench initramfs: BusyBox 1.31 + OpenWrt 24.10.7 ipks, no fw4 | full series | `tmp/tftp/mainline-7.4-rc1-clean.bin` (clean), `mainline-7.4-rc1.bin` (profile) |

- **A is not 7.4.** Upstream main ships 6.18 (`KERNEL_PATCHVER:=6.18`, snapshot `linux_kernel.version` 6.18.60). Upstream main has `KERNEL_TESTING_PATCHVER:=7.4` and `target/linux/realtek/patches-7.4` (upstream's own 300-xx, none of ours), so "upstream + 7.4, zero of our patches" is buildable (option A7 below); not built (a second OpenWrt tree is ~4 GB of the 4 GB floor).
- Closest same-generation option **A7**: OpenWrt main worktree + `CONFIG_TESTING_KERNEL=y` + `CONFIG_KERNEL_PREEMPT_VOLUNTARY=y` (see preempt note), no `openwrt/patches/*`. Unknown until built: whether upstream 7.4 boots this board (upstream DTS `tplink_tl-st1008f-v2` exists in the profiles) and whether `300-05` (timer from PLL) is needed. Needs owner decision.
- Latest 7.4.x: `v7.4-rc1` is the latest tag in `/mnt/2tb/git_mirror/linux` (2026-11-08; next tags in the store: v7.3-rc7, v7.3-rc6). Updating = store fetch (store job), then `./dev.py kernel-base update` (rewrites PIN in `scripts/kernel_base.py`), `scripts/patch_rebase.py`, record in MAINLINE-PORT Baselines, full rebuild of B and C. Not done.

### A: upstream snapshot as shipped

| Item | Value |
|---|---|
| Snapshot | OpenWrt SNAPSHOT `r38188-7efbba7631`, commit `7efbba7631b5401b9f470e28fca0d6a18f579f83`, downloaded 2026-11-08 from `downloads.openwrt.org/snapshots/targets/realtek/rtl930x/` (Last-Modified 2026-11-07 20:23:44 GMT) |
| Kernel | `Linux-6.18.60` (uImage header), profiles.json `linux_kernel.version` 6.18.60, vermagic `018229039bfd7eafcc23e3a1b5dd2217` |
| initramfs-kernel | 5,559,476 B, sha256 `0e02ff2526a9d5904d3a01d31f6d8b26b3f1c8eccc0097ff4f0b0e1111fccaf6` (= profiles.json; checked) |
| sysupgrade | 6,029,619 B, sha256 `2974daa034ef8fd43fdc60b26bb04ac5eb2229fca0be3f33343ce48dd7e27873` (= profiles.json; checked). Upstream 29 MiB layout: never flash (A/B slot layout needs compat 2.0, [DEFAULT-BOOT.md](DEFAULT-BOOT.md)) |
| Magic | download already carries the Realtek magic `0x93030000` (stock U-Boot `bootm`); std-magic copy for our U-Boot made with `scripts/uimage_std_magic.py`: `tmp/upstream-snapshot/upstream-r38188-initramfs-std.bin`, sha256 `1b4f68417fb1f9889d8e5cfe2b4a505da70d4cc5b23f49e8bcf6b0ee977d41e8` |
| tftp copies | `tmp/tftp/openwrt-upstream-r38188-initramfs.bin` + `-std.bin`; ramload key `openwrt-upstream` (`--then openwrt-upstream`) |

Does it boot on sw2 unpatched? Untested. Expectations, from the code:
- Upstream has the board DTS and the rtl930x drivers; the 2026-10-11 NAT rows ran the earlier snapshot r36962 (flash image), so booting is likely.
- No `300-05`: CP0 timer rate comes from DT `/cpus` `frequency` (default 500 MHz) not the PLL ([CLOCKS.md](CLOCKS.md)). At any CPU rate other than that, switch-side clock-derived values (jiffies, CPU busy %) scale wrongly. iperf3 Mbit/s is host-timed and stays valid; CPU0/CPU1 columns from A are not comparable.
- No `300-04` (DRAM prefetch), `300-21/25` (SRAM), `300-23` (LX from PLL), `300-17` (L3 offload), `300-39/40` (zc): A runs the stack path only; no zc, no L3-offload rows.
- No st1008f-linkcheck: upstream OpenWrt bridges every port with STP off. sw2 has cage loops 3-4 and 7-8: unplug cages 3, 4, 7, 8 (cage 1 only) before booting A (storm hazard, [CLAUDE.md](../CLAUDE.md) Hazards). Use `--no-linkcheck`.
- Boot at the common clock set via `--pre turbo ...` is untested for A; first A boot at stock clocks (`ramload --then openwrt-upstream`, no `--pre`) to see it come up, then the clock sets.

### B: ours, OpenWrt 7.4

- Reference = the l3fix2 image (r38178 + 7.4-rc1 + series), sha256 of the RAM image `2c328eac11ce05af985fac7f095c5657e6586713f47d55f35ef86ee3e85cf4e8`; the `-std` copy `d015e6c494eff150ee017050602676922383874977a2efe8c621977749a0c6d1`.
- Kernel config of the built tree: `tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.4-rc1/.config` (audit below). Not a clean-profile image by the owner's definition: PERF_EVENTS + PROFILING + DYNAMIC_DEBUG compiled in (idle).

### C: plain 7.4

- Existing `mainline-7.4-rc1.bin` = **profile** kernel (FTRACE + function graph + PERF compiled in, HZ 250). sha256 `6f2391f9a4e347a48d7d7b503156fb944428f136ac41cb9eb72a41be733e8db6`.
- New **clean** kernel: `./dev.py build-kernel --bench --clean` = `st1008f-v2.config` + bench fragment + `mainline/st1008f-v2-clean.config` (aligned to B, below). Image `tmp/tftp/mainline-7.4-rc1-clean.bin` (see Builds).
- Userland of C (unchanged): static BusyBox 1.31 (musl 1.1, `sources/busybox/busybox-mips`) + 24.10.7 ipks: nftables 1.1.1 (nojson), iperf3 3.17.1, ethtool 6.11, ip-full / tc-tiny 6.11.0, dropbear 2024.86. No conntrack-tools, no perf in the image (perf is pushed over ssh by `perf_push.py`), no fw4, no procd, no irqbalance.
- Userland gap to B: B runs OpenWrt main userland incl. fw4 hook chains and `fq_codel` on eth0; C has neither. Candidate cause of the unexplained `nat` TCP gap (plain 240 vs image 85.5, [NAT-STACKS.md](NAT-STACKS.md) / #161). Alignment at test time: load B's `nft list ruleset` (saved in `tmp/logs/nat161_openwrt_settings.txt`) into C before `nat` rows, and `tc qdisc replace dev eth0 root fq_codel` is now the kernel default in the clean image. A fresh minimal initramfs with current BusyBox is not worth it: BusyBox does not sit in the forwarding path; the iperf3 / nft / ip versions are the ones that matter. Option for exact parity: stage B's own rootfs (`build_dir/.../root-realtek`) into C's initramfs (owner decision).

## Config audit

Sources: A = derived (generic + rtl930x `config-6.18` of `tmp/openwrt-build/target/linux/realtek` + `config/Config-kernel.in` buildbot defaults; the snapshot ships no kernel `.config`, so values are derived, not read from the binary); B = final `.config` of the built 7.4 tree; C = `tmp/build-mips-v7.4-rc1-bench/.config` (the config of `mainline-7.4-rc1.bin`). Generator: `python3 scripts/config_audit.py` (full per-symbol dump, log `tmp/logs/config_audit.log`). `n` = not set, `-` = absent.

| Option | A upstream 6.18 | B ours 7.4 | C plain 7.4 | Throughput effect |
|---|---|---|---|---|
| DEBUG_KERNEL / DEBUG_FS | y / y | y / y | y / y | none |
| DEBUG_INFO (reduced) | y | y | n | none at run time (vmlinux only) |
| FTRACE, FUNCTION_TRACER, FUNCTION_GRAPH, DYNAMIC_FTRACE | n | n | **y y y y** | `-pg` on every function: nop per call + larger text; tracer idle. Not measured clean-vs-compiled |
| IRQSOFF / TIMERLAT tracers | n | n | n (`--latency` build only) | none |
| KPROBES / UPROBES | n / n | n / - | n / **y** | none |
| PERF_EVENTS / PROFILING | **n** / n | **y** / **y** | **y** / n | idle cost small; `perf record` running costs 15 % (see limits) |
| KALLSYMS / KALLSYMS_ALL | y / n | y / n | y / **y** | none |
| DYNAMIC_DEBUG | n | **y** | n | pr_debug sites compiled in; small |
| LOCKDEP, PROVE_LOCKING, DEBUG_SPINLOCK, DEBUG_ATOMIC_SLEEP | n | n | n | none |
| DEBUG_LIST, DEBUG_VM, DEBUG_NET, PAGE_POISONING, SLUB_DEBUG, PAGE_POOL_STATS | n | n | n | none; only the `--debug` image has them (below) |
| SCHEDSTATS / SCHED_DEBUG / NET_DROP_MONITOR | n / - / - | n / - / - | n / - / - | none |
| MAGIC_SYSRQ / PRINTK_TIME | y / y | y / y | y / y | none |
| Preempt model | NONE (6.18) | VOLUNTARY | VOLUNTARY | 7.x MIPS has no PREEMPT_NONE choice (OpenWrt default would give full PREEMPT, [build_openwrt.py](../scripts/build_openwrt.py) `config()`): A vs B differs in kernel generation and model |
| HZ | 100 | 100 | **250** | tick overhead at 250 vs 100: expected < 1 %, not measured |
| NR_CPUS / SMP / MIPS_MT_SMP | 2 / y / y | 2 / y / y | 2 / y / y | same |
| HIGHMEM | y | y | y | same (`300-13` fast paths in B and C) |
| CPU | MIPS32 R2, IRQ_VI | same | same | same (34Kc, no `-march=34kc` flag; `CPU_MIPS32_R2`) |
| Optimisation | -O2 (PERFORMANCE) | -O2 | -O2 | same flag; compilers differ: A 6.18 OpenWrt GCC (toolchain), B GCC 14.4.0, C host GCC 16.2.1 mips64-linux-gnu |
| STACKPROTECTOR / HARDENED_USERCOPY | y* / y | y / y | **n / n** | canary per function, usercopy check per copy_to_user: expected a few % |
| SLAB_FREELIST_HARDENED / RANDOM / MERGE_DEFAULT | y / y / y* | y / y / y | **n / n / n** | per-alloc cost; expected a few % on skb-heavy paths |
| CGROUPS / MEMCG / NAMESPACES | y* | y / y / y | **n / - / n** | memcg charges skb and slab: expected a few %; C has no netns (bench uses VLAN subifs, not netns, on the switch side) |
| IP_ADVANCED_ROUTER, IP_MULTIPLE_TABLES, IPV6_MULTIPLE_TABLES | y* | y y y | **n n n** | policy routing = fib_rules lookup per forwarded packet: expected to matter on route and nat rows |
| NF_CONNTRACK (m/y), ZONES / TIMEOUT / MARK / PROCFS | m (kmods) | m; y y y y | y; **n n n n** | built-in vs module: no run-time difference; ZONES etc. add a few branches |
| NF_FLOW_TABLE / NFT_FLOW_OFFLOAD | m | m | y | same code |
| CONNTRACK_TIMESTAMP / acct | n / sysctl default 0 | n / 0 | n / 0 | same |
| NETFILTER_EGRESS | n* | n | **y** | one static-key branch on TX; C pays it |
| DEFAULT_NET_SCH / FQ_CODEL | fq_codel / y | fq_codel / y | **unset / n** | eth0 root qdisc: fq_codel + BQL (B) vs pfifo_fast / noqueue (C). Flagged as candidate in [NAT-HISTORY.md](NAT-HISTORY.md) (nat gap); `noqueue` on plain gave 544 vs 528 |
| RPS / RFS_ACCEL / XPS / NET_FLOW_LIMIT / BQL | y y y / y / y | same | same | same defaults; runtime `rps_cpus` differ per image (dumped by `nat161_compare.py`) |
| GRO list / `rx-gro-list` | runtime | runtime | runtime | C's `port-up` sets it on; A and B: OpenWrt netifd default; record per boot |
| rteth driver | built-in, upstream | built-in (`NET_RTL838X=y`) | built-in | none: A has upstream rteth without `300-11..43` (no TX ring 32, no BQL xmit_more, no SRAM rings) |
| MODULES | y | y | y (bench) / n (non-bench) | none |
| BPF_SYSCALL / BPF_JIT | y / y | y / y | y / y | same |
| IKCONFIG | n | n | y | none; C's `/proc/config.gz` is the check that the running kernel is the audited one |
| Cmdline | DTB (`MIPS_CMDLINE_FROM_DTB`) | DTB + bootargs (`DTB_EXTEND`) | same as B | A: no `console=`/bootargs from U-Boot merge; record `/proc/cmdline` per boot (`nat161_compare.py` DUMP does) |
| LOGLEVEL console default | 15 | 15 | 7 | console spam only |

`*` = derived from Config-kernel.in / OpenWrt generic defaults, not read from the snapshot binary; B shows STACKPROTECTOR `y` (regular), and A is expected to match.

### Debug / trace state behind every published number

| Rows ([NAT-STACKS.md](NAT-STACKS.md)) | Kernel config in the image | Tracing / debug active during the number |
|---|---|---|
| 6.18 (OpenWrt SNAPSHOT r36962, 2026-10-11) | upstream defaults (derived): no PERF, no FTRACE; DEBUG_INFO reduced | none |
| 7.3 image rows (2026-11-06) | image built before `29b22a6` (2026-11-07): no PERF / PROFILING | none |
| 7.3 I (plain 7.3, 2026-10-12 to 10-15) | `st1008f-v2.config` since 2026-10-11: PERF_EVENTS + HW_PERF + FTRACE + FUNCTION_TRACER + FUNCTION_GRAPH + DYNAMIC_FTRACE compiled in, HZ 250; no DEBUG_LIST/SLUB_DEBUG/DEBUG_VM | tracer idle (`current_tracer` nop) except the `rteth-ftrace` rows (inflated, not in the table) and `nat_perf` rows (perf running) |
| 7.4 image rows (2026-11-07, 11-08, `openwrt-ours`, `l3fix2`) | PERF_EVENTS + PROFILING + DYNAMIC_DEBUG compiled in (since `29b22a6`); no FTRACE | perf only in the explicit `--perf` runs; zc benches run with no perf process |
| plain 7.4 rows (2026-11-07, 11-08, `mainline-7.4-rc1.bin`) | bench config: FTRACE, FUNCTION_TRACER, FUNCTION_GRAPH, DYNAMIC_FTRACE, PERF, UPROBES, KALLSYMS_ALL compiled in, HZ 250 | tracer idle in the `nat-bench` / `zc_bench` / `nat161` rows. #71 perf table (342 vs 290 Mbit/s "under perf") and the function_graph table (load 56 Mbit/s) are profile figures |
| `openwrt-ours-debug` image | adds DEBUG_LIST, SLUB_DEBUG_ON, DEBUG_NET, PAGE_POOL_STATS, DEBUG_VM, PAGE_POISONING | no throughput figure from it recorded: n/m. Never use for numbers |

- "Idle" is from the docs and scripts (tracers are only started by `rteth_ftrace.py`, perf only by `nat_perf.py` / `zc_bench.py --perf` / `nic-bench perf`); no per-run `current_tracer` check was logged. The clean-C boot (below) removes the question for new numbers.
- Every plain-kernel number to date comes from a kernel with `-pg` function-entry hooks compiled in; every image number after 2026-11-07 10:24 from one with PERF + PROFILING compiled in. How much that costs is unmeasured (first clean-vs-profile A/B in this plan).

### Limits: what moves the numbers

Expected to move numbers (rough, from our own data where marked):
- **Tracing/perf running**: `perf record -a -e cpu-clock -F 2000` on `nat-ft` TCP P4: 342 -> 290 Mbit/s (-15 %, NAT-HISTORY #71); `function_graph`: load falls to 56 Mbit/s (-85 % or worse). Profile-only; never in clean tables. 7.3 image `perf -a` also panicked (#149).
- **FTRACE compiled in (C profile)**: nop at every function entry, larger text, I-cache pressure on a 34Kc: estimated low single-digit %; unmeasured. The clean C vs old C A/B in the matrix measures it.
- **Hardening + memcg + fq_codel + policy routing (B vs old C)**: each a few %; together plausibly 5-15 % on stack rows (`nat`, `nat-ft`, route). zc rows pay less (no skb alloc, no qdisc, no fib lookup). Unmeasured; the clean C vs B A/B measures the sum, not the parts.
- **Userland (fw4 hook chains, procd, irqbalance, rps_cpus default)**: B vs C `nat` gap 85.5 vs 240 Mbit/s is unexplained by config alone (#161); the nft ruleset load into C is the first alignment test.
- **A vs B**: different kernel generation (6.18 vs 7.4), no zc/L3/ring/SRAM/prefetch patches: expected large (A `nat-ft` 243-248 at base clocks on r36962 vs B 267.7 at picks), not attributable to config.
- **Compiler**: B GCC 14.4.0, C host GCC 16.2.1, A OpenWrt toolchain: unknown, keep as a stated difference.
- **Timer rate on A** (no `300-05`): host-timed Mbit/s valid, switch-side CPU % not.

Irrelevant (same in all three, or off the data path): DEBUG_INFO, DEBUG_FS, KALLSYMS, MAGIC_SYSRQ, PRINTK_TIME, SMP/NR_CPUS/HIGHMEM/CPU type, BPF, IKCONFIG, console loglevel, LOCKDEP and friends (all off everywhere), module vs built-in conntrack / flowtable code.

### Alignment: C to B, B to A

C (clean) = `mainline/st1008f-v2-clean.config`, merged last by `build-kernel --bench --clean`:
- Off: FTRACE (+ FUNCTION_TRACER, FUNCTION_GRAPH_TRACER, DYNAMIC_FTRACE), PERF_EVENTS (+ HW_PERF_EVENTS), UPROBES, KALLSYMS_ALL, HZ_250 -> HZ_100, NETFILTER_EGRESS.
- On (as B): STACKPROTECTOR, HARDENED_USERCOPY, SLAB_FREELIST_HARDENED / RANDOM, SLAB_MERGE_DEFAULT, SLAB_BUCKETS, IP_ADVANCED_ROUTER, IP_MULTIPLE_TABLES, IPV6_MULTIPLE_TABLES, IP_MULTICAST, SYN_COOKIES, TCP_CONG_ADVANCED, NET_SCH_FQ_CODEL + DEFAULT_FQ_CODEL, NETFILTER_ADVANCED, NF_CONNTRACK_ZONES / TIMEOUT / MARK / PROCFS, CGROUPS, MEMCG, NAMESPACES, NET_NS.
- Kept different on purpose: IKCONFIG (audit), DEBUG_FS (rteth debugfs knobs the bench uses), KALLSYMS (oops decode), MODULES (GDMA test modules), conntrack / flowtable built-in (no ipk kmods in C), CPU/DDR clocks (set by U-Boot).
- Profile C = today's config without the clean fragment (= existing `mainline-7.4-rc1.bin`). Proposed later split: move the PERF/FTRACE lines out of `st1008f-v2.config` into `st1008f-v2-profile.config` and make clean the default; not done (would change what every existing image means).

B to A (where our patches do not need the difference):
- Drop `CONFIG_KERNEL_PERF_EVENTS`, `CONFIG_KERNEL_PROFILING`, `CONFIG_KERNEL_DYNAMIC_DEBUG` from the B build seed (`scripts/build_openwrt.py` SEED / `shared_config()`), keep `CONFIG_KERNEL_PREEMPT_VOLUNTARY` (7.x has no NONE) -> B-clean. Perf then needs a separate B-profile image (the #148 flow). Full rebuild of B (~minutes incremental, disk 4.2 GB tree exists); not done, needs owner decision.
- Cannot align: kernel generation (A 6.18) unless A7 is built; PREEMPT (NONE vs VOLUNTARY).

## Builds and downloads done 2026-11-08

| Item | Result |
|---|---|
| A snapshot initramfs + sysupgrade + profiles.json + config.buildinfo | `tmp/upstream-snapshot/dl/`, sha256 checked against profiles.json |
| A std-magic copy | `tmp/upstream-snapshot/upstream-r38188-initramfs-std.bin` (+ tftp copies `openwrt-upstream-r38188-initramfs[-std].bin`) |
| `sha256sums` of the snapshot dir | download truncated twice (server resets); profiles.json used for the checksums |
| C clean kernel | built, image + sha256 below |
| B | existing l3fix2 image used as is (not clean, see audit) |
| A7, C with fresh BusyBox, B-clean | not built: need owner decisions below |

C clean build result: built OK (0 warnings, all overlay options survived olddefconfig), out dir `tmp/build-mips-v7.4-rc1-bench-clean`, `mainline_build_check.py --bench --clean`. Verified in its `.config`: FTRACE n, PERF_EVENTS n, HZ 100, STACKPROTECTOR y, MEMCG y, IP_MULTIPLE_TABLES y, NETFILTER_EGRESS n, NF_CONNTRACK_ZONES y, DEFAULT_NET_SCH fq_codel.
- `tmp/tftp/mainline-7.4-rc1-clean.bin` 5,382,583 B, sha256 `ce45cfdca09fd2da2ed7124b86358145d843748d434494b3e4ba075334c322a2`; `-clean-std.bin` sha256 `6eced708b198403f3d24e8243b2c068c86fc01b38eb16e143e2dc4fb1804ee19`.
- Boot: `ramload ... --then mainline-kernel --kernel mainline-7.4-rc1-clean.bin --mgmt`. Untested on hardware.
- Tooling edits (uncommitted): `mainline_build_check.py --clean`, `dev.py build-kernel --clean` (out name `mainline-<base>-clean.bin`), `st1008_ramload.py` key `openwrt-upstream`.

## Test matrix (sw2, nothing run yet)

Clock sets (all via ramload `--stock-clocks --then <img> --cage 1 --pre turbo ... --pre <raw core>`):
- **common**: core 508 (raw e220 `0x30626`) + CPU 1350 + DDR 662 + LX 306 + SRAM 500. Stable on B and C ([NAT-STACKS.md](NAT-STACKS.md) Observations, #161).
- **final**: core 608 (raw e220 `0x36826`) + CPU 1325 + DDR 662 + LX 306 + SRAM 500, where stable (7.4 image and plain: yes; A: untested, may fail).

Tests per stack and clock set (profile clean, perf/ftrace off):

| Cell | A | B | C |
|---|---|---|---|
| NAT TCP `nat` and `nat-ft`, -P 1 / 2 / 4, fwd + rev, 15 s | yes | yes | yes |
| Routed (no NAT) UDP 1400 / 500 / 64 B, kpps, stack path | yes | yes | yes |
| L3 offload off / on (v4 on-link, v4 default) | off only (no `300-17`) | yes (`l3_offload_ab.py -n 1`) | yes |
| zc + NAT TCP P4 fwd / rev; zc UDP 64 / 500 / 1400 B | n/a (no `300-39`) | yes | yes |

- One run per cell (sweep rule, [CLAUDE.md](../CLAUDE.md)); P4 headline cells get 2 more runs only after the owner reviews the overview.
- Per stack, also record the settings dump (`nat161_compare.py` DUMP list: cmdline, sysctls, qdisc, rps, ethtool -k, interrupts, `/proc/config.gz` where present).
- Profile runs (common clocks only, separate table): B and C-profile: `nat_perf.py --callgraph` on `nat-ft` P4 and `zc_bench.py --perf`; C-profile also `rteth_ftrace.py --depth 2`. A: none (no PERF/FTRACE compiled in).
- Boots: clean 3 stacks x 2 clock sets = 6, profile 2 (B, C) = 8 ramload boots (A at final clocks may drop out). Estimate from `stack_compare.py`: about 1.7 h of bench plus ramload failures (plain boots fail ~1 in 6 at ramload, one retry each, per `nat161_compare.py`). Add ~25 min per clean boot for the 2 P4 repeats.
- Order: C-clean first at common clocks (answers "what does the clean config buy" against the 2026-11-08 plain row 240 / 323 / 1565), then B, then A (A needs cages 3, 4, 7, 8 unplugged).
- `nat161_compare.py` stays for the two-stack #161 flow; `stack_compare.py` generalises to three stacks and the cell list above (dry-run only; execution wiring is the owner's release).

## Owner decisions

1. A: accept 6.18.60 snapshot as "upstream as shipped", or also build A7 (upstream main + testing kernel 7.4, zero patches)? A7 needs a second OpenWrt tree (~4 GB) and may not boot without `300-05`.
2. B: rebuild B-clean (drop PERF / PROFILING / DYNAMIC_DEBUG from the seed) so B itself meets "clean = no tracing"?
3. C userland: keep BusyBox 1.31 + 24.10.7 ipks (plus B's nft ruleset), or stage B's own rootfs into the initramfs for exact userland parity?
4. Unplug cages 3, 4, 7, 8 on sw2 for A (no linkcheck/STP in upstream OpenWrt)?
5. Release hardware runs and the clock sets (is core 608 for A worth a boot).
