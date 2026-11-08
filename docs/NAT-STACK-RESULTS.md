# NAT stack comparison: controlled results (sw2)

Plan and gate: [NAT-STACK-TESTS.md](NAT-STACK-TESTS.md). Driver `scripts/stack_compare.py --run`; tables from `python3 scripts/stack_results.py`; raw rows `tmp/controlled/rows.jsonl`, boots `tmp/controlled/boots.jsonl`, snapshots `tmp/controlled/snap-{common,final}/`, gate headers `tmp/controlled/stack_compare_result-*.txt`, failure console tails `tmp/controlled/logs/`.

## Header

- Date 2026-11-08, sw2 only (bench unit .56), cage 1 only (cages 3, 4, 7, 8 unplugged by the owner), RAM boots via `ramload`, no flash writes.
- Clean profile only (no perf / ftrace running). Profile runs not done.
- n = 3 x 15 s per TCP cell, 3 x 10 s per UDP cell; value = mean (min-max). `n=k` = k reps survived (others hit a board panic). `-` = not run or no result, A = never booted at the common clocks.
- Not repeated beyond n = 3 (no cell within 5 % of another stack that needed it; every cell has a >= 20 % spread to the other stack except zcnat UDP 1400/500, which are within 1-3 % and already n = 3).
- Clocks:
  - common: core 508 (e220 `0x30626`) + CPU 1350 + DDR 662 + LX 306 + SRAM 500. Readback `e220 0x30626` verified on every B and C boot.
  - final: core 608 (e220 `0x36826`, e214 `0x478`) + CPU 1325 + DDR 662 + LX 306 + SRAM 500. B and C only.
- Images (sha256 in [NAT-STACK-TESTS.md](NAT-STACK-TESTS.md#images-sha256-built-or-fetched-2026-11-08)): A `openwrt-upstream-r38178-initramfs.bin` 57124dd7..., B `openwrt-ours-clean-initramfs.bin` d4969634..., C `mainline-7.4-rc1-clean3.bin` 29884a80....

### Config state per stack

| Item | A | B | C |
|---|---|---|---|
| Kernel | 6.18.60 | 7.4-rc1 | 7.4.0-rc1-dirty |
| PERF / FTRACE / DYNAMIC_DEBUG / PROFILING | n | n | n |
| Run-time probes (snapshot) | not taken (no boot) | perf n, ftrace n, dyndbg n, kprobes n, lockdep n | same as B |
| Userland | upstream r38178 | OpenWrt r38178 | B's BusyBox / musl / tools |

### Held identical (snapshot-verified on B and C at both clock sets)

- iperf3 3.22 (pushed), ip / tc 7.3.0 (pushed), nft 1.1.7, ethtool 7.2, dropbear 2026.94.
- `fw4-b.nft` sha256 `5eb0c745...` loaded on both; eth0 qdisc `noqueue`; eth0 irq affinity 2 (VPE1); rps / xps 0; offloads and sysctls from the normaliser list.

### Remaining differences from the gate

- Final clocks: gate CONTROLLED (B vs C), every difference listed:
  - kernel version string; `/proc/config.gz` only on C; driver version string follows the kernel.
  - OpenWrt base processes (procd, ubusd, netifd, logd, urngd, linkwatch) on B, not C.
  - native tool binaries are separate builds.
- Common clocks: gate NOT CONTROLLED (1 unlisted difference) for the B and C rows of that set. The sysctl dump differed in `bpf_jit_enable` (B 1, C 0), `tcp_keepalive_time` (B 120, C 7200), `tcp_mem` (RAM size), `tcp_fastopen_key` (random), `tcp_available_ulp`, `tcp_l3mdev_accept`, `bpf_jit_kallsyms`. None is on the forwarding path. Fixed afterwards in `stack_normalize.py` (pins `bpf_jit_enable` 1 and `tcp_keepalive_time` 120; random / RAM-size keys excluded from the diff); only the final-clock set ran with the fix.
- Drift pre vs post (both sets): nft ruleset (the `nattest` / flowtable rules `nat_bench.py` adds per mode), process list (ephemeral helpers). Expected.
- By design, never aligned: kernel generation (A 6.18 vs 7.4), PREEMPT (A NONE vs VOLUNTARY), patch set (A none of 300-xx), C kernel compiler (host GCC 16.2.1), OpenWrt base system absent on C, free memory.
- The pinned-tool sha256 snapshot key (`sha_pinned`) is absent from every snapshot (not diagnosed); versions above are from the `v_*` keys instead.

## Boot success

| Stack | Common clocks | Final clocks | Note |
|---|---|---|---|
| A | no (4 attempts) | not tried | stock clocks: boots (ramload exit 0, ping .56 answers, 16:56) |
| B | yes (11 boots, 9 recoveries after board panics) | yes (1 boot, no panic) | |
| C | yes (1 boot) | yes (1 boot) | no fault |

- A at common clocks: the console turns to garbage right after the kernel starts (baud divisor off), no ping within 30 s, ramload waits 40 s for the prompt and fails. Two tries by the engine (16:53, 16:55), plus 2 from the first attempt at 16:34 that failed on the relay (see failures). One diagnostic boot at stock clocks (no `--pre`): boots. One diagnostic boot at common minus LX (`turbo cpu=1350,ddr=662,sram=500` + core 508): fails the same way. Suspected: the UART clock follows LX, and A has no `300-23`; not tested further. Console tails: `tmp/controlled/logs/bootfail-A-common-*.txt`.
- A at final clocks: not tried (common failed first).

## Results: common clocks (core 508)

TCP in Mbit/s, UDP in kpps (received at the host). A = no data.

| Cell | A | B | C | Note |
|---|---|---|---|---|
| nat P1 fwd | - | 111.1 (109.4-113.7) | 257.5 (254.8-259.9) | |
| nat P1 rev | - | 145.3 (143.9-146.1) | 344.6 (338.7-356.1) | |
| nat P2 fwd | - | 105.5 (105.2-106.1) | 263.2 (257.9-270.5) | |
| nat P2 rev | - | 144.9 (140.6-150.6) | 336.2 (323.1-355.1) | |
| nat P4 fwd | - | 103.1 (101.7-104.7) | 264.0 (263.8-264.3) | |
| nat P4 rev | - | 133.3 (130.9-134.6) | 332.1 (327.6-336.4) | |
| nat-ft P1 fwd | - | 333.0 (332.6-333.3) n=2 | 402.6 (391.7-414.0) | B 1 panic |
| nat-ft P1 rev | - | 409.3 n=1 | 542.5 (540.1-545.9) | B 2 panics |
| nat-ft P2 fwd | - | 352.2 (350.9-353.1) | 454.2 (450.8-459.1) | |
| nat-ft P2 rev | - | 413.9 (410.9-419.1) | 539.7 (538.2-542.8) | |
| nat-ft P4 fwd | - | 344.2 (338.5-349.7) | 478.3 (476.8-481.2) | |
| nat-ft P4 rev | - | 271.8 (253.0-290.5) n=2 | 542.7 (539.8-544.4) | B 1 hang |
| stack UDP 1400 B | - | 19.4 (19.1-19.7) n=2 | 33.7 (33.7-33.8) | B 1 hang |
| stack UDP 500 B | - | 32.0 (31.9-32.1) | 52.1 (51.9-52.3) | |
| stack UDP 64 B | - | 43.1 (43.0-43.2) | 67.2 (67.1-67.3) | |
| zc UDP 1400 B | - | 157.1 (157.1-157.2) | 157.8 (157.8-157.9) | within 1 % |
| zc UDP 500 B | - | 328.5 (328.1-328.8) | 334.4 (334.1-334.8) | within 2 % |
| zc UDP 64 B | - | 452.8 (452.4-453.6) | 431.6 (431.2-432.2) | B +5 % |
| zc+nat P4 fwd | - | none (3 panics) | 1571.1 (1568.7-1574.0) | |
| zc+nat P4 rev | - | 1531.2 (1529.5-1532.9) n=2 | 1567.6 (1565.4-1569.3) | B 1 panic |
| routed L3 off, TCP P4 | n/a | 103.8 (100.7-110.0) | not run | B only |
| routed L3 on, TCP P4 | n/a | 9189.4 (9181.7-9193.3) | not run | B only |
| routed L3 on, UDP 1400 B | n/a | 850.3 (850.2-850.3) | not run | B only |

## Results: final clocks (core 608, CPU 1325)

| Cell | A | B | C | Note |
|---|---|---|---|---|
| nat P1 fwd | - | 114.5 (113.9-115.2) | 271.3 (269.7-272.8) | |
| nat P1 rev | - | 128.3 (125.3-130.2) | 334.0 (332.8-335.8) | |
| nat P2 fwd | - | 97.1 (96.6-97.6) | 282.1 (280.7-283.0) | |
| nat P2 rev | - | 127.0 (126.5-127.3) | 325.7 (325.2-326.4) | |
| nat P4 fwd | - | 102.6 (98.7-110.1) | 264.2 (263.0-264.9) | |
| nat P4 rev | - | 123.6 (122.1-125.2) | 316.5 (313.6-320.4) | |
| nat-ft P1 fwd | - | 339.8 (337.9-342.5) | 429.6 (426.2-435.6) | |
| nat-ft P1 rev | - | 439.3 (432.4-452.1) | 542.6 (540.3-544.8) | |
| nat-ft P2 fwd | - | 368.4 (367.4-370.3) | 472.1 (466.7-477.6) | |
| nat-ft P2 rev | - | 448.2 (444.9-454.5) | 543.5 (540.5-548.5) | |
| nat-ft P4 fwd | - | 358.8 (355.8-361.4) | 491.0 (490.2-491.6) | |
| nat-ft P4 rev | - | 443.5 (442.7-444.4) | 548.9 (547.3-550.5) | |
| stack UDP 1400 B | - | 11.7 (11.7-11.7) | 34.0 (33.9-34.0) | |
| stack UDP 500 B | - | 33.2 (33.1-33.4) | 53.0 (52.9-53.1) | |
| stack UDP 64 B | - | 44.2 (44.0-44.5) | 66.5 (66.4-66.5) | |
| zc UDP 1400 B | - | 164.1 (164.1-164.1) | 163.6 (163.5-163.7) | within 1 % |
| zc UDP 500 B | - | 331.6 (330.6-332.4) | 336.0 (335.1-337.0) | within 2 % |
| zc UDP 64 B | - | 445.7 (444.5-446.4) | 428.9 (427.7-430.0) | B +4 % |
| zc+nat P4 fwd | - | 1585.1 (1575.3-1603.9) | 1614.0 (1613.0-1615.8) | within 2 % |
| zc+nat P4 rev | - | 1604.0 (1600.4-1607.8) | 1610.1 (1607.6-1611.7) | within 1 % |
| routed L3 off, TCP P4 | n/a | 106.3 (105.6-106.9) | not run | B only |
| routed L3 on, TCP P4 | n/a | 9204.1 (9200.0-9210.9) | not run | B only |
| routed L3 on, UDP 1400 B | n/a | 850.0 (849.8-850.3) | not run | B only |

## Failures, hangs, recoveries

- Relay: the first `--run` attempt at 16:34 failed twice on `relay off failed: No route to host` (relay .49 briefly unreachable; ping answered both before and after). Retried at 16:52, relay answered.
- B at common clocks: 9 board panics / hangs, each recovered by ramload (software reset not possible on a dead board; ramload falls back to the relay). Cells and counts:
  - nat-ft P1 fwd (1), nat-ft P1 rev (2), nat-ft P4 rev (1), stack UDP 1400 B (1), zc+nat P4 fwd (3), zc+nat P4 rev (1).
  - Console shows `Oops` + `Call Trace` + `Kernel panic`; the first one is in `gro_list_prepare` (known, #149; the normaliser pins `rx-gro-list` on in all stacks). Two hangs left no oops in the log (ssh timeout only).
  - B at final clocks: no panic in any cell.
  - C: no fault at either clock set.
- Surviving cells after a panic have fewer reps (see `n=`); the panic cells are not retried further.
- Netns race: after a panic the old `natlan` netns stays alive for 1-3 minutes (orphan TCP sockets), `ip link add enp8s0.991` fails with "VLAN device already exists", `nat_bench.py setup` returns 1 and natlan has no route. The engine now retries setup + mode + status up to 10 times, 15 s apart.

## Script fixes (this run)

- `stack_compare.py`
  - `setup` rc 1 is the SVI ping, dropped by fw4 input until `mode` adds the `nattest` rules: no longer fatal; the real check is `status` (natlan to natwan ping) after `mode nat`.
  - setup + mode + status retried up to 10 times, 15 s apart (`hold`), for the netns race above.
  - `normalise()` retried once and returns 99 when no snapshot was written (ssh rc 255 once gave "normalise did not finish", which the engine had treated like the benign rc 1).
- `stack_normalize.py`
  - xps_cpus FAIL lines on single-queue netdevs (sysfs node unreadable): FAIL only when a readable value is not zero.
  - sysctls: pin `net.core.bpf_jit_enable` 1 and `net.ipv4.tcp_keepalive_time` 120; random / RAM-size keys (`tcp_fastopen_key`, `tcp_mem`, `tcp_available_ulp`, `tcp_l3mdev_accept`, `bpf_jit_kallsyms`) excluded from the diff.
- New `scripts/stack_results.py`: rows.jsonl to the tables above.
- Unfixed: `v_busybox` probe returns "applet not found" on all stacks (`busybox` with no args); `sha_pinned` key missing; `run_all` does not run the gate by itself (run `stack_compare.py --gate-only --snapshot-dir tmp/controlled/snap-<set>`).

## End state

- sw2 on its normal chain: `./dev.py uboot-chain-env boot` PASS at 18:53 (power-on, stock, saved chain, ours, flash OpenWrt, STP on).
- `tmp/tftp/uboot-mainline.bin` unchanged (490,681 B, mtime 2026-11-07 20:11). No flash writes. sw1 not touched.
