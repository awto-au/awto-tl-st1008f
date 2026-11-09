# NAT stack comparison plan: OpenWrt r38178 without project changes vs our build vs plain kernel

Status 2026-11-09: plan + config audit + images built (A, B-clean, B-profile, C-clean2, C-clean3); A7 not buildable; normaliser + gate written. The first TrueNAS B/C common-clock run stopped because its UDP helper required glibc; incomplete rows remain under `tmp/controlled/truenas/`. The corrected run completed 174/174 rows under `tmp/controlled/truenas-static/`: B/C's gate is CONTROLLED, but A's CPU0 IRQ and other differences make the combined A/B/C gate **NOT CONTROLLED**. See [NAT-STACK-RESULTS.md](NAT-STACK-RESULTS.md) for measurements and final state. Earlier numbers: [NAT-STACKS.md](NAT-STACKS.md) (audit, legend, gaps), [NAT.md](NAT.md).

- Owner request 2026-11-08: drop the "unknown" rows; one clean comparison on the same kernel generation.
- Every figure from this plan states its profile: **clean** (no tracing, numbers) or **profile** (perf / ftrace on, diagnosis only). Profile figures never share a table with clean ones.
- Driver: `./dev.py stack-compare [--run] [--stacks A,B,C] [--clocks common,final] [--profile clean|profile|both]`; without `--run` it prints the plan. A failed boot, normalization, benchmark, or post-run snapshot returns nonzero. A uses IRQ CPU0; B/C use CPU1, so their combined results are not controlled. Log `tmp/logs/stack_compare.log`.

## The three stacks

| | Kernel | Userland | Patches | Image (RAM boot) |
|---|---|---|---|---|
| A OpenWrt r38178 | Linux 6.18.60 (`Linux version 6.18.60 ... #0 SMP Fri Nov 6 22:31:19 2026`, built tree) | OpenWrt r38178 (`7e8bfcfe76`, same commit as B), device-profile default packages only, fw4 | OpenWrt's patches, none of ours | `tmp/tftp/openwrt-upstream-r38178-initramfs.bin` (+ `-std`) |
| A7 r38178 + Linux 7.4 | not buildable (below) | | none | none |
| B OpenWrt r38178 + project changes | Linux 7.4-rc1 | OpenWrt r38178-7e8bfcfe76 | this project's driver and platform changes | clean: `tmp/tftp/openwrt-ours-clean-initramfs.bin`; profile: `openwrt-ours-l3fix2-initramfs.bin` |
| C plain | Linux 7.4-rc1 (`7.4.0-rc1-dirty`) | C-clean3: B's own BusyBox 1.38 + applet links, musl, dropbear, nft, ip, tc, ethtool; minimal init; no iperf3 (pushed by the normaliser) | this project's driver and platform changes | clean: `tmp/tftp/mainline-7.4-rc1-clean3.bin` (clean2: BusyBox 1.31 + 24.10.7 iperf3, superseded for the comparison); profile: `mainline-7.4-rc1.bin` (old userland) |

- **A is not 7.4.** Upstream main ships 6.18 (`KERNEL_PATCHVER:=6.18`, built tree: 6.18.60).
- Owner decision 2026-11-08: OpenWrt version identical across stacks. A = upstream built at B's commit (r38178). The downloaded snapshot r38188 (`7efbba7631`) is kept only as a note: files `tmp/upstream-snapshot/`, ramload key `openwrt-upstream-snapshot`, not used in the comparison.
- **A7 (upstream main + testing kernel 7.4, zero of our patches) cannot be built (owner asked 2026-11-08; checked in `git ls-tree HEAD` of OpenWrt main 7e8bfcfe76, also the store's `origin/main`):**
  - no `KERNEL_TESTING_PATCHVER` in `target/linux/realtek/Makefile` (our overlay adds it); no `generic/kernel-7.4`, no `generic/{backport,pending,hack}-7.4`, no `realtek/patches-7.4`, `files-7.4`, `rtl930x/config-7.4`.
  - the earlier statement that upstream main carries `patches-7.4` was wrong: those directories are created by `build_openwrt.py` `overlay_73()` from our port (`OWRT_VERBATIM` = 9 of upstream's 112 `patches-6.18`, plus 42 patches including this project's changes and forward-ports, `files-7.4` 12 paths, generic pending 700/701/344/644/645, hack 910/911/940).
  - A7 would be "upstream's 6.18 patch set rebased to 7.4-rc1" = the port itself; the other 103 patches fail or are superseded on 7.4. Not attempted (no second tree built).
  - Snapshot commit `7efbba7631` is not in the OpenWrt store (store `origin/main` = 7e8bfcfe76); not fetched (shared store).
- Closest same-generation substitute: none. A stays 6.18.60 (upstream OpenWrt, no local patches).
- Latest 7.4.x: `v7.4-rc1` is the latest tag in the shared Linux mirror (2026-11-08; next tags in the store: v7.3-rc7, v7.3-rc6). Updating = store fetch (store job), then `./dev.py kernel-base update` (rewrites PIN in `scripts/kernel_base.py`), `scripts/patch_rebase.py`, record in MAINLINE-PORT Baselines, full rebuild of B and C. Not done.

### A: OpenWrt r38178, Linux 6.18.60, no project changes

| Item | Value |
|---|---|
| Source | `git worktree` of the shared OpenWrt store at `7e8bfcfe76204efc9433be341642901876eb555b` (= B's `OWRT_COMMIT`, r38178); no local patches, overlay files, linkcheck or build seed |
| Config | `target realtek/rtl930x`, device `tplink_tl-st1008f-v2`, `make defconfig` from 3 lines (target, subtarget, device) + dl dir; `tmp/owrt-config-A-upstream-r38178.config`, kernel `tmp/kernel-config-A-upstream-r38178.config` |
| Feeds | none installed (device default package set is all in the base tree; no feed update, no extra packages) |
| Kernel | `Linux version 6.18.60 (... GCC 14.4.0 toolchain-c0e63334e4, GNU ld 2.46.1) #0 SMP Fri Nov 6 22:31:19 2026` (built-tree vmlinux) |
| initramfs-kernel | `tmp/tftp/openwrt-upstream-r38178-initramfs.bin`, 5,353,577 B, sha256 `57124dd796cdfdddaf7555c322756e67ed9be5e3a47af97e58047d7d1ade51d4`; Realtek magic `0x93030000` straight from the OpenWrt build (same image rule as every other image) |
| std magic | `tmp/tftp/openwrt-upstream-r38178-initramfs-std.bin`, sha256 `14f140308d88ce10075b2d2a5dbdf92ccb0185fd13170aa9db6cba236880db93` (`scripts/uimage_std_magic.py`) |
| sysupgrade | built (5,767,475 B) but not copied to tmp: upstream 29 MiB layout, never flash |
| Build | 2026-11-08, `make -j20`, 1992 s wall at load ~45-70 (shared box), 11 GB tree + 1.7 GB dl copy on `/home` |
| Toolchain | identical to B: `toolchain-mips_24kc_gcc-14.4.0_musl`, `mips-openwrt-linux-musl-gcc (OpenWrt GCC 14.4.0 toolchain-c0e63334e4) 14.4.0`, binutils 2.46.1, musl (same `CONFIG_*` in both `.config`) |
| Ramload key | `openwrt-upstream` (`--then openwrt-upstream`); snapshot r38188 note: key `openwrt-upstream-snapshot`, sha256 `0e02ff2526a9d5904d3a01d31f6d8b26b3f1c8eccc0097ff4f0b0e1111fccaf6` |

OpenWrt r38178 booted on sw2 and initially passed management ping and SSH. Its kernel includes OpenWrt's own Linux patches; "no local patches" means none of this repository's patches or overlay files.
- No `300-05`: CP0 timer rate comes from DT `/cpus` `frequency` (default 500 MHz) not the PLL ([CLOCKS.md](CLOCKS.md)). At any CPU rate other than that, switch-side clock-derived values (jiffies, CPU busy %) scale wrongly. iperf3 Mbit/s is host-timed and stays valid; CPU0/CPU1 columns from A are not comparable.
- No `300-04` (DRAM prefetch), `300-21/25` (SRAM), `300-23` (LX from PLL), `300-17` (on-link and default-route offload), `300-39/40` (zc). A can hardware-route eligible gateway routes, but not the directly connected paths in this test; it has no zc or on-link offload rows.
- No st1008f-linkcheck: upstream OpenWrt bridges every port with STP off. sw2 has cage loops 3-4 and 7-8: unplug cages 3, 4, 7, 8 (cage 1 only) before booting A (storm hazard, [CLAUDE.md](../CLAUDE.md) Hazards). Use `--no-linkcheck`.
- At common clocks, A's OpenWrt kernel keeps the 115200 divisor based on LX 175 MHz while the UART clock follows LX 305 MHz; the host switches to 200000 baud at U-Boot's `Starting kernel ...` handoff. The shell is readable, but some early kernel output is garbled during the transition.
- The owner confirmed cages 3, 4, 7, and 8 unplugged. An initial CPU1 normalization lost management before its snapshot. A subsequent CPU0 normalization retained management and verified `irq24 1`; this supports, but does not prove, the suspected CPU1 failure. A lacks `300-18`, and that affinity stopped the NIC before the fix ([MAINLINE-PORT.md](MAINLINE-PORT.md#irq-affinity-300-18-devpy-irq-check)). `stack-normalize` refuses A with `--napi irq1`; the owner chose an A-only CPU0 run while preserving B/C's CPU1 results.
- On the fresh common-clock boot, U-Boot read back `0x30626`; the serial log and recovered kernel ring passed `check-log` after reviewing the split informational initrd line. Some early serial bytes were garbled at the baud handoff; the ring cannot recover messages never entered into it.

### B: OpenWrt r38178 with project changes, Linux 7.4-rc1

- **B-clean** (`openwrt-ours-clean`): same tree, patches (incl. `300-17` fixes) and selftest helper (strict check passed) as l3fix2; `build_openwrt.py --kernel mainline --clean` drops `CONFIG_KERNEL_DYNAMIC_DEBUG / PERF_EVENTS / KALLSYMS / PROFILING` from the seed (logged: `CLEAN profile: seed without ...`). KALLSYMS stays `y`: OpenWrt's `KERNEL_KALLSYMS` defaults to y (`default y if !SMALL_FLASH`), as upstream.
- **B-profile** = l3fix2 (r38178 + 7.4-rc1 + series; PERF_EVENTS + PROFILING + DYNAMIC_DEBUG compiled in, idle). Perf / dyndbg runs only.
- Kernel configs saved: `tmp/kernel-config-B-clean.config`, `tmp/kernel-config-B-profile.config`; buildroot `.config`: `tmp/owrt-config-B-clean.config`, `tmp/owrt-config-B-profile.config`.
- Build tree moved to scratch storage (symlink `tmp/openwrt-build`): the rebuilt toolchain pushed the shared build filesystem below the 4 GB floor (make killed by the disk guard once at 3.1 GB). Shared `dl/` and ccache stay on that filesystem.

### C: plain 7.4

- Existing `mainline-7.4-rc1.bin` = **profile** kernel (FTRACE + function graph + PERF compiled in, HZ 250). sha256 `6f2391f9a4e347a48d7d7b503156fb944428f136ac41cb9eb72a41be733e8db6`.
- New **clean** kernel: `./dev.py build-kernel --bench --clean` = `st1008f-v2.config` + bench fragment + `mainline/st1008f-v2-clean.config` (aligned to B, below). Image `tmp/tftp/mainline-7.4-rc1-clean.bin` (see Builds).
- **C-clean2** userland (`mainline_initramfs.py --bench --owrt-userland`): static BusyBox 1.31 (`sources/busybox/busybox-mips`) as shell; tools copied from B's `staging_dir/target-mips_24kc_musl/root-realtek` with their DT_NEEDED closure: nft (nftables-json 1.1.7 + libnftables, libnftnl 1.3.2, libmnl, libjansson), ip-full 7.3.0, tc-full 7.3.0, ethtool-full 7.2, dropbear 2026.94 (+ dropbearkey), musl 1.2.6, libgcc_s 14.4.0, libbpf 1.8.0, libelf, libxtables, libz. Same binaries as B.
- C-clean2 only; not in B, so not "the same as B": iperf3 (B has no iperf3; C keeps 24.10.7 iperf3 3.17.1 + libatomic for `zc_bench`), conntrack (neither image has it), BusyBox (C 1.31 static vs B 1.38).
- fw4: `mainline/fw4-b.nft` (B's fw4 table from `tmp/logs/nat161_openwrt_settings.txt`, counters and `nattest` rules removed) is in the image as `/etc/fw4-b.nft`; `nat_bench.py set_mode` loads it when present (plain kernel only) and inserts the same `nattest` accept rules with C's SVI names. Hook chains and policies as B (input/forward/output policy drop, mangle/raw/nat hooks).
- C kernel fragment `mainline/st1008f-v2-clean-fw4.config` adds the nf_tables expressions the ruleset needs (LIMIT, LOG, REJECT*, FIB*, REDIR, QUOTA, NUMGEN, HASH); all survived olddefconfig. No perf in the image (`perf_push.py` over ssh), no procd, no irqbalance, no netifd.
- **C-clean3** (`./dev.py build-kernel --bench --clean --owrt-busybox`; `mainline_initramfs.py --owrt-busybox`): same kernel config as clean2; initramfs uses the OpenWrt root-realtek BusyBox 1.38.0 (dynamic, musl) + applet symlinks, musl 1.2.6, libgcc_s, dropbear 2026.94, nft + libs, ip-full, tc-full, ethtool 7.2 (DT_NEEDED closure); `/init` = mount proc/sys/dev/debugfs, shell on `/dev/console` (this BusyBox has no cttyhack/stty), no selftest, no tracefs; `port-up` starts dropbear; `/etc/fw4-b.nft`. Nothing from 24.10.7: iperf3 comes from the normaliser (pinned, below). The B and C snapshots show different native binary hashes despite the common build-tree origin. Out dir `tmp/build-mips-v7.4-rc1-bench-clean-owrt3`.
- Profile C (`mainline-7.4-rc1.bin`) keeps the old userland (no `/etc/fw4-b.nft`: `nat_bench.py` skips fw4).
- Userland gap to B (old C): B runs OpenWrt main userland incl. fw4 hook chains and `fq_codel` on eth0; old C had neither (C-clean2 has both). Candidate cause of the unexplained `nat` TCP gap (plain 240 vs image 85.5, [NAT-STACKS.md](NAT-STACKS.md) / #161). Alignment at test time: load B's `nft list ruleset` (saved in `tmp/logs/nat161_openwrt_settings.txt`) into C before `nat` rows, and `tc qdisc replace dev eth0 root fq_codel` is now the kernel default in the clean image. A fresh minimal initramfs with current BusyBox is not worth it: BusyBox does not sit in the forwarding path; the iperf3 / nft / ip versions are the ones that matter. Exact parity (B's own BusyBox etc.) = C-clean3, owner 2026-11-08.

## Config audit

Sources: A = final kernel `.config` of the built upstream r38178 tree (`tmp/kernel-config-A-upstream-r38178.config`), read, not derived; B = final `.config` of the built 7.4 tree; C = `tmp/build-mips-v7.4-rc1-bench/.config` (the config of `mainline-7.4-rc1.bin`). Generator: `python3 scripts/config_audit.py` (full per-symbol dump, log `tmp/logs/config_audit.log`). `n` = not set, `-` = absent.

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
| Preempt model | NONE (6.18, `PREEMPT_NONE=y`) | VOLUNTARY | VOLUNTARY | 7.x MIPS has no PREEMPT_NONE choice (OpenWrt default would give full PREEMPT, [build_openwrt.py](../scripts/build_openwrt.py) `config()`): A vs B differs in kernel generation and model |
| HZ | 100 | 100 | **250** | tick overhead at 250 vs 100: expected < 1 %, not measured |
| NR_CPUS / SMP / MIPS_MT_SMP | 2 / y / y | 2 / y / y | 2 / y / y | same |
| HIGHMEM | y | y | y | same (`300-13` fast paths in B and C) |
| CPU | MIPS32 R2, IRQ_VI | same | same | same (34Kc, no `-march=34kc` flag; `CPU_MIPS32_R2`) |
| Optimisation | -O2 (PERFORMANCE) | -O2 | -O2 | same flag; compiler: A and B identical (OpenWrt GCC 14.4.0 toolchain-c0e63334e4, musl, binutils 2.46.1); C host GCC 16.2.1 mips64-linux-gnu |
| STACKPROTECTOR / HARDENED_USERCOPY | y / y | y / y | **n / n** | canary per function, usercopy check per copy_to_user: expected a few % |
| SLAB_FREELIST_HARDENED / RANDOM / MERGE_DEFAULT | y / y / y | y / y / y | **n / n / n** | per-alloc cost; expected a few % on skb-heavy paths |
| CGROUPS / MEMCG / NAMESPACES | y / y / y | y / y / y | **n / - / n** | memcg charges skb and slab: expected a few %; C has no netns (bench uses VLAN subifs, not netns, on the switch side) |
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

A column read from the built `.config` (no derived values left).

### Debug / trace state behind every published number

| Rows ([NAT-STACKS.md](NAT-STACKS.md)) | Kernel config in the image | Tracing / debug active during the number |
|---|---|---|
| 6.18 (OpenWrt SNAPSHOT r36962, 2026-10-11) | upstream defaults (derived, earlier snapshot): no PERF, no FTRACE; DEBUG_INFO reduced | none |
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
- **Compiler**: A and B identical (OpenWrt GCC 14.4.0 toolchain-c0e63334e4, verified from both trees); C host GCC 16.2.1 stays a stated difference.
- **Timer rate on A** (no `300-05`): host-timed Mbit/s valid, switch-side CPU % not.

Irrelevant (same in all three, or off the data path): DEBUG_INFO, DEBUG_FS, KALLSYMS, MAGIC_SYSRQ, PRINTK_TIME, SMP/NR_CPUS/HIGHMEM/CPU type, BPF, IKCONFIG, console loglevel, LOCKDEP and friends (all off everywhere), module vs built-in conntrack / flowtable code.

### Alignment: C to B, B to A

C (clean) = `mainline/st1008f-v2-clean.config`, merged last by `build-kernel --bench --clean`:
- Off: FTRACE (+ FUNCTION_TRACER, FUNCTION_GRAPH_TRACER, DYNAMIC_FTRACE), PERF_EVENTS (+ HW_PERF_EVENTS), UPROBES, KALLSYMS_ALL, HZ_250 -> HZ_100, NETFILTER_EGRESS.
- On (as B): STACKPROTECTOR, HARDENED_USERCOPY, SLAB_FREELIST_HARDENED / RANDOM, SLAB_MERGE_DEFAULT, SLAB_BUCKETS, IP_ADVANCED_ROUTER, IP_MULTIPLE_TABLES, IPV6_MULTIPLE_TABLES, IP_MULTICAST, SYN_COOKIES, TCP_CONG_ADVANCED, NET_SCH_FQ_CODEL + DEFAULT_FQ_CODEL, NETFILTER_ADVANCED, NF_CONNTRACK_ZONES / TIMEOUT / MARK / PROCFS, CGROUPS, MEMCG, NAMESPACES, NET_NS.
- Kept different on purpose: IKCONFIG (audit), DEBUG_FS (rteth debugfs knobs the bench uses), KALLSYMS (oops decode), MODULES (GDMA test modules), conntrack / flowtable built-in (no ipk kmods in C), CPU/DDR clocks (set by U-Boot).
- Profile C = today's config without the clean fragment (= existing `mainline-7.4-rc1.bin`). Proposed later split: move the PERF/FTRACE lines out of `st1008f-v2.config` into `st1008f-v2-profile.config` and make clean the default; not done (would change what every existing image means).

B to A (where our patches do not need the difference):
- Done: `build_openwrt.py --clean` drops `CONFIG_KERNEL_PERF_EVENTS`, `CONFIG_KERNEL_PROFILING`, `CONFIG_KERNEL_DYNAMIC_DEBUG`, `CONFIG_KERNEL_KALLSYMS` from the seed -> B-clean; `CONFIG_KERNEL_PREEMPT_VOLUNTARY` kept (7.x has no NONE). Perf uses the l3fix2 image (#148 flow).
- Cannot align: kernel generation (A 6.18.60; A7 not buildable); PREEMPT (NONE vs VOLUNTARY).

## What is held identical / what still differs

Normaliser `./dev.py stack-normalize --stack A|B|C` runs over ssh before every bench (`--dry-run` prints the commands); snapshot per stack `tmp/logs/stack_snapshot-<S>.json`. Use it on RAM-booted comparison images: it replaces tool symlinks in the running root. A requires `--napi irq0` or `--napi default`, not the default `irq1`. The gate diffs snapshots and writes the result header; an unlisted difference or failed readback = NOT CONTROLLED.

| Item | Identical value | How | A | Why / residual |
|---|---|---|---|---|
| iperf3 | one static 3.22 binary (musl, B's GCC 14.4.0 toolchain), `tmp/stack-tools/iperf3` | pushed to `/tmp/stack-tools`, linked to `/usr/bin/iperf3` | pushed | A's image has none; `scripts/build_iperf3_static.py` |
| ip, tc, bridge | ip-full / tc-full 7.3.0, bridge + libs from the OpenWrt root | pushed (`./dev.py stack-normalize --pack` builds the set) | pushed | A has BusyBox `ip` and no `tc` or `bridge`; the latter is needed for test VLAN setup |
| BusyBox, musl, dropbear | native; musl and dropbear versions recorded | native | native | binaries are separate builds; the BusyBox version probe reported `applet not found` |
| ethtool | full 7.2 + libs from the OpenWrt root | pushed for new runs | pushed | A and C used the same full binary; B's recorded native full binary was a separate build |
| nft | version recorded, not pinned | stack-native | native | ruleset load is not in the forwarding path; the gate compares `nft -v` |
| nft ruleset | `mainline/fw4-b.nft` (sha256 in snapshot) | firewall stop, flush, load; plus one `stack-mgmt` accept (C's mgmt is `lan1`) | verified | `nattest` rules added per mode by `nat_bench.py` |
| RPS / XPS | `rps_cpus` = `xps_cpus` = 0 on every netdev | sysfs | verified | no cross-CPU packet steering: B/A boot with rps 1 (packet_steering init), C with 0 |
| eth0 qdisc | `noqueue` | `tc qdisc replace` | verified | A/B default fq_codel on mq; removes qdisc + queueing as a variable |
| Offloads | GRO and rx-gro-list on; rx-udp-gro-forwarding and tx-nocache-copy off | `ethtool -K`, readback on eth0 and lan1 | verified | GSO is requested on but effective off on all three; A additionally reports `tls-hw-record: off [fixed]` |
| sysctls | list `SYSCTLS` in the script (conntrack, flowtable, tcp_*, rmem/wmem, budget, rp_filter 0, printk) | `/proc/sys` writes and readback | verified | A's conntrack buckets, skb_defer_max and tcp_comp_sack_slack_ns were aligned to B/C; six 7.4-only keys remain absent on A |
| IRQ | A affinity 1 (VPE0); B/C affinity 2 (VPE1) | `smp_affinity` | verified | Existing B/C results use CPU1; the combined comparison is not controlled |
| Services | collectd, lldpd, uhttpd, sysntpd, dnsmasq, odhcpd, snmpd, metricsd, rpcd, cron, irqbalance stopped | `init.d stop` | verified | kept: dropbear, network, procd/ubusd/netifd, logd, urngd, fan/led/gpio/poe, linkwatch (B only) |
| Kernel debug/perf/trace | none compiled in B-clean, C-clean3, A (read from built `.config`) | build + runtime probes in snapshot | n | listed per stack in the result header |
| Clocks, cage, host, topology, cells | common / final sets, cage 1, same netns bench | `stack_compare.py` | same | A: cages 3, 4, 7, 8 unplugged |

Cannot be aligned (listed in every result header):
- Kernel version: A 6.18.60 vs B/C 7.4-rc1; A7 (upstream + 7.4) not buildable. PREEMPT NONE (A) vs VOLUNTARY (B, C).
- OpenWrt base: A and B both r38178 (aligned). C has no OpenWrt base (own BusyBox/musl copied from B).
- Driver and platform changes: A uses OpenWrt's own driver, including gateway-route hardware offload. B/C add this project's packet-ring and memory tuning, on-link and default-route hardware offload, zero-copy forwarding and CPU-timer correction.
- Compiler for the kernel: A = B (OpenWrt GCC 14.4.0, same toolchain dir name and `--version`); C host GCC 16.2.1 differs.
- OpenWrt base system (procd, netifd, hotplug) on A and B, absent on C; local linkwatch runs on B only. Optional daemons stop.
- A's and B's kernel configs are read from the built trees (no IKCONFIG on the boards); only C has `/proc/config.gz`, so build-time config for A and B stays a document, run-time probes (perf, ftrace, dyndbg, kprobes, lockdep, schedstat, `current_tracer`) go in the snapshot.
- Free memory, BogoMIPS (not compared).

A's tiny ethtool returned `Could not change any device features` when GSO was requested on but remained effectively off. The full ethtool succeeds, and the snapshot checks both the request and actual state; the gate still reports the full feature differences. The old broad `sysctl -a` snapshot triggered a deprecated IPv6-neighbour warning (#161); targeted reads avoid it, and the fresh boot remained warning-free after normalization.

## Builds and downloads done 2026-11-08

| Item | Result |
|---|---|
| A upstream r38178 (no local patches) | built, `tmp/tftp/openwrt-upstream-r38178-initramfs[-std].bin`, below |
| Snapshot r38188 (note only) | `tmp/upstream-snapshot/dl/`, sha256 checked against profiles.json |
| Snapshot std-magic copy | `tmp/upstream-snapshot/upstream-r38188-initramfs-std.bin` (+ tftp copies `openwrt-upstream-r38188-initramfs[-std].bin`) |
| `sha256sums` of the snapshot dir | download truncated twice (server resets); profiles.json used for the checksums |
| C clean kernel | built, image + sha256 below |
| B | existing l3fix2 image used as is (not clean, see audit) |
| B-clean | built 2026-11-08 (`--clean`), below |
| C with B's userland (C-clean2) | built 2026-11-08, below |
| A7 | not buildable: upstream main has no 7.4 support (see A7 above) |

C clean build result: built OK (0 warnings, all overlay options survived olddefconfig), out dir `tmp/build-mips-v7.4-rc1-bench-clean`, `mainline_build_check.py --bench --clean`. Verified in its `.config`: FTRACE n, PERF_EVENTS n, HZ 100, STACKPROTECTOR y, MEMCG y, IP_MULTIPLE_TABLES y, NETFILTER_EGRESS n, NF_CONNTRACK_ZONES y, DEFAULT_NET_SCH fq_codel.
- `tmp/tftp/mainline-7.4-rc1-clean.bin` 5,382,583 B, sha256 `ce45cfdca09fd2da2ed7124b86358145d843748d434494b3e4ba075334c322a2`; `-clean-std.bin` sha256 `6eced708b198403f3d24e8243b2c068c86fc01b38eb16e143e2dc4fb1804ee19`.
- Boot: `ramload ... --then mainline-kernel --kernel mainline-7.4-rc1-clean.bin --mgmt`. Untested on hardware.
- Tooling edits (uncommitted): `mainline_build_check.py --clean`, `dev.py build-kernel --clean` (out name `mainline-<base>-clean.bin`), `st1008_ramload.py` key `openwrt-upstream`.

## Planned test matrix (sw2)

The completed TrueNAS run covered common clocks only; actual rows and gate are in [NAT-STACK-RESULTS.md](NAT-STACK-RESULTS.md).

Clock sets (all via ramload `--stock-clocks --then <img> --cage 1 --pre turbo ... --pre <raw core>`):
- **common**: core 508 (raw e220 `0x30626`) + CPU 1350 + DDR 662 + LX 306 + SRAM 500. Stable on B and C ([NAT-STACKS.md](NAT-STACKS.md) Observations, #161).
- **final**: core 608 (raw e220 `0x36826`) + CPU 1325 + DDR 662 + LX 306 + SRAM 500, where stable (7.4 image and plain: yes; A: untested, may fail).

Tests per stack and clock set (profile clean, perf/ftrace off):

| Cell | A | B | C |
|---|---|---|---|
| NAT TCP `nat` and `nat-ft`, -P 1 / 2 / 4, fwd + rev, 15 s | yes | yes | yes |
| Routed (no NAT) UDP 1400 / 500 / 64 B, kpps, stack path | yes | yes | yes |
| Directly connected routing (no NAT), CPU / switch chip, TCP P4 fwd | CPU not run; switch-chip option unavailable | yes | not run (owner: B only) |
| zc + NAT TCP P4 fwd / rev; zc UDP 64 / 500 / 1400 B | n/a (no `300-39`) | yes | yes |

- One run per cell (sweep rule, [CLAUDE.md](../CLAUDE.md)); P4 headline cells get 2 more runs only after the owner reviews the overview.
- Per stack, also record the settings dump (`nat161_compare.py` DUMP list: cmdline, sysctls, qdisc, rps, ethtool -k, interrupts, `/proc/config.gz` where present).
- Profile runs (common clocks only, separate table): B and C-profile: `nat_perf.py --callgraph` on `nat-ft` P4 and `zc_bench.py --perf`; C-profile also `rteth_ftrace.py --depth 2`. A: none (no PERF/FTRACE compiled in).
- Boots: clean 3 stacks x 2 clock sets = 6, profile 2 (B, C) = 8 ramload boots (A at final clocks may drop out). Estimate from `stack_compare.py`: about 1.7 h of bench plus ramload failures (plain boots fail ~1 in 6 at ramload, one retry each, per `nat161_compare.py`). Add ~25 min per clean boot for the 2 P4 repeats.
- Order: C-clean first at common clocks (answers "what does the clean config buy" against the 2026-11-08 plain row 240 / 323 / 1565), then B, then A (A needs cages 3, 4, 7, 8 unplugged).
- `nat161_compare.py` stays for the two-stack #161 flow; `stack_compare.py` generalises to three stacks and the cell list above (dry-run only; execution wiring is the owner's release).

## Owner answers 2026-11-08 and what was done

1. A: upstream r38178 built, no local patches (done; replaces snapshot r38188, 2026-11-08 owner decision: identical OpenWrt version) and A7: not buildable (above).
2. B: B-clean built; perf-enabled l3fix2 kept as PROFILE.
3. C: tools of B copied into C's initramfs (C-clean2).
4. Cages 3, 4, 7, 8 unplugged by the owner for every A run (upstream OpenWrt: no linkcheck, no STP: storm hazard, [CLAUDE.md](../CLAUDE.md) Hazards).
5. Hardware runs were subsequently released for the TrueNAS common-clock rerun on 2026-11-09; see [NAT-STACK-RESULTS.md](NAT-STACK-RESULTS.md).

## Images (sha256, built or fetched 2026-11-08)

| Stack | File (`tmp/tftp/`) | Bytes | sha256 |
|---|---|---|---|
| A | `openwrt-upstream-r38178-initramfs.bin` | 5,353,577 | `57124dd796cdfdddaf7555c322756e67ed9be5e3a47af97e58047d7d1ade51d4` |
| A std | `openwrt-upstream-r38178-initramfs-std.bin` | 5,353,577 | `14f140308d88ce10075b2d2a5dbdf92ccb0185fd13170aa9db6cba236880db93` |
| A snapshot r38188 (note) | `openwrt-upstream-r38188-initramfs.bin` | 5,559,476 | `0e02ff2526a9d5904d3a01d31f6d8b26b3f1c8eccc0097ff4f0b0e1111fccaf6` |
| A7 | not built | | |
| B-clean | `openwrt-ours-clean-initramfs.bin` | 7,994,858 | `d49969634ddb6ee98ac80c86f2d52f3145f27608cedf11159c4b608bba6c8172` |
| B-clean std | `openwrt-ours-clean-initramfs-std.bin` | 7,994,858 | `33affe72f7fe69d565cb5d1f9e550fdc39f97405757bef9df359fd965de4e188` |
| B-profile | `openwrt-ours-l3fix2-initramfs.bin` | 8,160,679 | `2c328eac11ce05af985fac7f095c5657e6586713f47d55f35ef86ee3e85cf4e8` |
| B-profile std | `openwrt-ours-l3fix2-initramfs-std.bin` | 8,160,679 | `d015e6c494eff150ee017050602676922383874977a2efe8c621977749a0c6d1` |
| C-clean2 | `mainline-7.4-rc1-clean2.bin` | 6,781,186 | `e8242ab3c42b01fca14c0f9874dc9a5486beda260738e2d736d8248ae046a95a` |
| C-clean2 std | `mainline-7.4-rc1-clean2-std.bin` | 6,781,186 | `3be10dff84920d9ac019b9f90c315a8aa7aedf6de20f4b4c0b98e311bd9455e2` |
| C-clean3 | `mainline-7.4-rc1-clean3.bin` | 6,173,267 | `29884a80224a4fa89c21e48f02959fcfc7dd0c415d554cf17aae0ff57958fd83` |
| C-clean3 std | `mainline-7.4-rc1-clean3-std.bin` | 6,173,267 | `5a43f2ea32bc7be48b152155ee206ced17056a7d5c3359a9aefe7327015b869c` |
| C-clean (old userland) | `mainline-7.4-rc1-clean.bin` | 5,382,583 | `ce45cfdca09fd2da2ed7124b86358145d843748d434494b3e4ba075334c322a2` |
| C-profile | `mainline-7.4-rc1.bin` | | `6f2391f9a4e347a48d7d7b503156fb944428f136ac41cb9eb72a41be733e8db6` |

- C-clean2: out dir `tmp/build-mips-v7.4-rc1-bench-clean-owrt` (0 warnings), `./dev.py build-kernel --bench --clean --owrt-userland` (names the image `-clean2`).
- B-clean also left `tmp/openwrt-ours-clean-sysupgrade.bin` (8,388,915 B; never flash, A/B layout not applied).

## Debug / perf / trace state per stack (from the built `.config`)

| Option | A (built .config) | B-clean | B-profile | C-clean2 | C-profile |
|---|---|---|---|---|---|
| PERF_EVENTS | n | n | **y** | n | **y** |
| PROFILING | n | n | **y** | n | n |
| DYNAMIC_DEBUG | n | n | **y** | n | n |
| FTRACE (+ function tracers) | n | n | n | n | **y** |
| KPROBES | n | n | n | n | n (UPROBES y) |
| KALLSYMS / _ALL | y / n | y / n | y / n | y / n | y / **y** |
| LOCKDEP / PROVE_LOCKING | n | n | n | n | n |
| HZ | 100 | 100 | 100 | 100 | 250 |
| DEBUG_FS | y | y | y | y | y |

- A from the built r38178 tree `.config` (`tmp/kernel-config-A-upstream-r38178.config`): PERF_EVENTS n, PROFILING n, DYNAMIC_DEBUG n, FTRACE n, KPROBES n, SCHEDSTATS n, KALLSYMS y, HZ 100, DEBUG_INFO y (reduced), DEBUG_FS y, PREEMPT_NONE y; buildroot `KERNEL_DEBUG_FS/KALLSYMS/DEBUG_KERNEL/DEBUG_INFO(_REDUCED)` y, `KERNEL_PERF_EVENTS` and `KERNEL_FTRACE` not set.
- DEBUG_INFO (reduced, vmlinux only) y in A and B, n in C: no run-time effect.

## Diff summary

- **A7 vs B-clean `.config`: not possible (A7 not built).** Substitute: A's built `.config` (`tmp/owrt-config-A-upstream-r38178.config`) vs B-clean's: A has no `KERNEL_*` debug/perf symbol beyond the OpenWrt defaults; remaining differences are packages (device default set in A vs ours plus feeds in B), the kernel generation and PREEMPT (A: NONE on 6.18; B: VOLUNTARY on 7.4).
- **B-clean vs B-profile kernel `.config`** (`diff` of `tmp/kernel-config-B-{profile,clean}.config`): only `PERF_EVENTS`, `HW_PERF_EVENTS`, `PROFILING`, `DYNAMIC_DEBUG` + `DYNAMIC_DEBUG_CORE` (profile y, clean n), and `MODULES_TREE_LOOKUP`, `DEBUG_PERF_USE_VMALLOC` / `CGROUP_PERF` / `FW_LOADER_DEBUG` / `TEST_DYNAMIC_DEBUG` Kconfig-dependent lines, plus the `INITRAMFS_SOURCE` path (tree moved to `/home`). Buildroot `.config`: only `KERNEL_PERF_EVENTS`, `KERNEL_PROFILING`, `KERNEL_DYNAMIC_DEBUG` (and `PACKAGE_perf` unset in both).
- **C-clean2 vs C-clean** (kernel): + `NFT_LIMIT / LOG / REJECT / REJECT_INET / REJECT_IPV4 / REJECT_IPV6 / FIB* / REDIR / QUOTA / NUMGEN / HASH`; initramfs differs (B's tools, `/etc/fw4-b.nft`).

## Command list

`./dev.py stack-compare --stacks A,B,C --clocks common,final --profile both` prints every command (log `tmp/logs/stack_compare.log`). Boot lines per stack and clock set (common clocks shown; `final` swaps in `turbo cpu=1325,...` and raw `0x36826`):

```
# A (cages 3,4,7,8 UNPLUGGED by the owner first)
python3 dev.py ramload uboot-mainline --stock-clocks --then openwrt-upstream --no-linkcheck --linux-console-baud 200000 --cage 1 --pre "turbo cpu=1350,ddr=662,lx=306,sram=500" --pre "<raw core 508>"
# B-clean
python3 dev.py ramload uboot-mainline --stock-clocks --then openwrt-ours-clean --no-linkcheck --cage 1 --pre "turbo ..." --pre "<raw core>"
# C-clean3
python3 dev.py ramload uboot-mainline --stock-clocks --then mainline-kernel --kernel mainline-7.4-rc1-clean3.bin --mgmt --cage 1 --pre "turbo ..." --pre "<raw core>"
# profile runs (common clocks only): B-profile --then openwrt-ours-l3fix2 ; C-profile --kernel mainline-7.4-rc1.bin
```

- Each boot is followed by `./dev.py stack-normalize --stack X` (A also needs `--napi irq0`) and, after the cells, `--snapshot-only --tag post`; evaluate common-clock snapshots with `./dev.py stack-compare --gate-only --snapshot-dir tmp/controlled/truenas-static/snap-common`.
- UDP traffic uploaded to TrueNAS uses a static-musl helper; the benchmark builds it automatically with `musl-gcc` (or explicitly with `./dev.py nat-bench build-udpblast`).
- Cells per stack: `scripts/stack_compare.py` output (nat / nat-ft P1/2/4 fwd+rev, stack UDP 1400/500/64, directly connected hardware routing on/off for B, zc cells for B and C; A lacks the zc and on-link offload extensions).
- A7 rows: none.
