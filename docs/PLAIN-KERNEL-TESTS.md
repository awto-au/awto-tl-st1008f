# Board tests on the plain mainline kernel

Owner decision 2026-11-07: all board tests run on a basic mainline kernel (v7.4-rc1) + minimal initramfs, booted by `./dev.py ramload mainline-kernel`. No OpenWrt.
Driver: `scripts/plain_campaign.py`. Gaps listed here are closed by the bench variant unless marked OPEN.

## What the plain image has (today)

- Kernel `mainline/st1008f-v2.config` on `allnoconfig`: MODULES off, NAMESPACES off, DMA_ENGINE off.
  - On: PERF_EVENTS, HW_PERF_EVENTS, KALLSYMS, DEBUG_FS, DEVMEM, FTRACE, NF_TABLES + FLOW_TABLE + NFT_FLOW_OFFLOAD, NET_PKTGEN, BPF_SYSCALL, THERMAL, IKCONFIG.
  - `/sys/module/rtl838x_eth/parameters` and `/sys/kernel/debug/rteth/rxq` exist when the 300-39 series is in the build (built-in module params).
- Initramfs (`scripts/mainline_initramfs.py`): static BusyBox 1.31 (devmem, taskset, nproc, awk, seq, nc, insmod, wget, tftp, udhcpc) + OpenWrt 24.10.7 ipks (`scripts/initramfs_tools.py`).
  - From ipks: musl libc + loader, libgcc, libatomic, zlib, libelf 0.192, `ip-full` (`/sbin/ip`), tc-tiny, ethtool, nft, iperf3, dropbear.
  - Scripts: `port-up`, `st1008f-selftest` (+ helper/data), `/init` (mounts proc sys dev debugfs tracefs devpts; no network).
- No management IP and no sshd at boot. `port-up <cage> <addr/len>` brings ONE cage up, sets GRO list, starts `dropbear -R -B` (root, blank password).
- Contrast, OpenWrt flow: `set_mgmt_ip` (uci + `ip addr` on `switch.1`), `openwrt_stp`, bridge/STP, fw4, procd, scp. None of it exists here.

## Management IP

| Flow | How |
|---|---|
| OpenWrt (old) | `st1008_ramload.set_mgmt_ip(BENCH_IP)` after STP |
| Plain (new) | `./dev.py ramload ... mainline-kernel --mgmt` runs `port-up <--cage> 192.168.25.56/24` over the console, clears the ssh mux, pings (12 s cap) |

- Direct: `./dev.py ramload mainline-kernel --cage 1 --mgmt` (stock clocks).
- Via our U-Boot: `./dev.py ramload uboot-mainline --then mainline-kernel --cage 1 --mgmt [--pre "turbo cpu=1350,ddr=662,lx=306,sram=500"]`. `--pre` and `--bootargs` only apply with `--then`.
- One cage only (house-LAN loop hazard); the bench has no bridge, no STP needed.

## Gaps per test

Legend: BB = BusyBox applet already in the image; NEW = added by the bench variant.

| Test | Userland needed | Status |
|---|---|---|
| (a) #149 zc + perf | ssh, taskset, awk, ps, perf, nft (NAT) | ssh via `port-up`; taskset/awk/ps BB; perf NEW (push) |
| (b) GDMA | insmod, the two `.ko` | insmod BB; `.ko` built against the bench tree; push by ssh |
| (c) DSS | devmem, cut, printf, seq, ssh | all BB; `/dev/mem` needs DEVMEM (on) |
| (d) selftest, mem-stress, check-log | selftest script, md5sum, dd, tmpfs | in image |
| (d) stress-trace | `st1008f-trace` samplers | OPEN: OpenWrt-only (`openwrt/selftest/st1008f-trace.c`), not in plain image |
| (d) boot-link-check | uboot_chain_env flash boot | OPEN: OpenWrt flash flow; plain has `link` step (carrier read) |

### (a) #149 trigger

- Host side unchanged: `nat_bench.py setup` (detects the mainline shell: SVIs `lan1.991/992`, sets `ip_forward`), `mode route`, `zc_bench.py --perf`.
- Board: ssh, `taskset` (only for `--napi split`), nft/flowtable (in image; `route` mode needs none), no netns on the board (host netns only).
- perf, two options (`scripts/perf_push.py`, works on both images, streams over `ssh cat >` because the dropbear ipk has no scp server):
  - Static: `tmp/perf/perf` from `scripts/build_perf.py` (exists today, no libs). Preferred.
  - Dynamic musl: OpenWrt build_dir perf + `libelf.so.1 libdw.so.1 libtraceevent.so.1 libz.so.1 libfts.so.0` from `tmp/openwrt-build/staging_dir/target-mips_24kc_musl/usr/lib` (OpenWrt build_dir perf not present now).
  - Dest `/tmp` (initramfs RAM). Bench initramfs sets loader path `/tmp:/lib:/usr/lib` (`/etc/ld-musl-mips-sf.path`), so libs resolve; `LD_LIBRARY_PATH=/tmp` also set by the scripts.
- Kernel: PERF_EVENTS, KALLSYMS (on). Bench adds KALLSYMS_ALL. `perf record -e cpu-clock` needs no PMU. PROFILING is not needed (oprofile only).
- Clocks: `--pre "turbo ..."` (picks) or none (stock); tag the campaign `--tag picks|stock`. BogoMIPS is logged by the `pre` step to confirm.

### (b) GDMA dmaengine

- Plain kernel has MODULES off: bench kernel (`--bench`) adds MODULES=y, DMA_ENGINE=y (`mainline/st1008f-v2-bench.config`).
- `.ko` must match the bench kernel (vermagic): existing `kmod/gdma_bench/gdma_bench.ko` is from the OpenWrt 7.3 tree. Build:
  - `make -C tmp/build-mips-bench ARCH=mips CROSS_COMPILE=mips64-linux-gnu- modules_prepare`
  - `make -C tmp/build-mips-bench ARCH=mips CROSS_COMPILE=mips64-linux-gnu- M=$PWD/kmod/rtl9300_gdma modules` (same for `kmod/gdma_bench`)
- Result is in dmesg (`registered 2 memcpy channels`, 8 `gdma_bench: len ...` rows with `bad 0 fails 0`); both modules refuse to stay loaded by design.
- `scripts/gdma_test.py` (single transfer, `kmod/gdma_test`) is hard-wired to the OpenWrt KDIR: OPEN, not used by the campaign.
- Hang risk: a bad GDMA register write can lock the bus (ssh goes silent): campaign kills on stall, pings, stops; coordinator decides on a relay power-cycle.

### (c) DSS

- Needs only `devmem` (BB) over ssh, `CONFIG_DEVMEM` (on), thermal zone (on). `dss_probe.py` and `dss_soak.py` take `--ip`, no OpenWrt dependency.
- Soak load: `(while :; do :; done) &` busy loops (`--load 2`), killed at the end.
- Expect `polls=4096` (never ready) from the probe if the sensors are still in reset (HIDDEN-FEATURES): campaign verdict FAIL with "not-ready N".

### (d) selftest, mem-stress, check-log

- `selftest.py --ip` over ssh (default) or `--console`; `mem_stress.py` console only; `boot_log_check.py --boot -1` host only. No image change.
- Boot-link rounds: coordinator loops `ramload ... --mgmt` then `plain_campaign.py --steps link,checklog`. OpenWrt `boot_link_check.py` stays OpenWrt-only.

### Patch 644 vlan_protocol hook (`vlanproto` step)

- Bridge `brvp` + one DOWN port (`lan2`, no address) enslaved, then `ip link set brvp type bridge vlan_protocol 802.1ad`; cleanup always runs.
- PASS = fails with `VLAN protocol can't be changed on a bridge with switch ports`; FAIL = silent accept (hook missing) or other error.
- Port is down on purpose: the hook needs a switch port in the bridge, not a link; no laser, no loop, lan1 (mgmt) untouched.
- Verdict line: `VERDICT <tag> vlanproto#0: PASS|FAIL rc=0 <s>s extack ok|silent accept...`. Caps 10 s stall/total.

## Changes made (2026-11-07)

| File | Change |
|---|---|
| `scripts/mainline_initramfs.py` | `--bench` / env `ST1008F_INITRAMFS_BENCH=1`: ld-musl path, ed25519 host key at boot; output `st1008f-initramfs-bench.cpio.xz`; default unchanged |
| `mainline/st1008f-v2-bench.config` | MODULES, DMA_ENGINE, KALLSYMS_ALL |
| `scripts/mainline_build_check.py`, `dev.py` | `--bench`: merges the fragment + bench initramfs, out dir `tmp/build-mips-bench` |
| `scripts/st1008_ramload.py` | `--mgmt`: `port-up` + ping on plain kernel boots |
| `scripts/perf_push.py` | ssh-stream transport, `--dest`, `--perf-bin`, static perf preferred |
| `scripts/plain_campaign.py` | the campaign driver |

- `build-kernel --bench` writes the same `tmp/tftp/mainline.bin` as a normal build (next base); rebuild without `--bench` to restore.
- Note: the bench initramfs is selected through the generated `tmp/initramfs/initramfs.config`; a later non-bench build overwrites it.

## Campaign caps

Stall timeout = no output line (or CSV growth) for N s; total = backstop. Source of each number is in `CAPS` in the script.

| Step | Stall s | Total s | Basis |
|---|---|---|---|
| pre, link | 12 | 12 |
| vlanproto | 10 | 10 | 5 ip commands + ssh 5 s | ssh 5 s connect + <1 s |
| perf | 25 | 90 | unmeasured (ssh cipher on MIPS) |
| natsetup | 30 | 90 | unmeasured |
| zc (per run) | 35 | 135 | UDP 10-12 s x2 + perf 15 s = ~45 s, x3 |
| gdma | 15 | 30 | bench ~1 s + ssh |
| dss_probe | 130 | 130 | script bound 120 s |
| dss_soak | 30 | 90 | 60 s run |
| selftest | 35 | 80 | 20-26 s measured, x3 |
| checklog | 15 | 30 | <2 s local |
| memstress | 25 | 105 | ~35 s measured, x3 |

- Unmeasured caps: `secs` in `tmp/logs/plain_campaign.csv` after the first run replaces them.
- Not included: boot to shell (35-40 s) is ramload's cap, not the campaign's.
