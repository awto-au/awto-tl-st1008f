# Campaign: plain Linux 7.4-rc1 on sw2 (2026-11-07)

- Unit: sw2 (192.168.25.56), cage 1 (lan1) only, host netns natlan/natwan.
- Kernel: v7.4-rc1 + our series, bench config (`./dev.py build-kernel --bench`: MODULES, DMA_ENGINE, KALLSYMS_ALL; `CONFIG_RTL9300_GDMA=y`), bench initramfs, no OpenWrt. `uname -r` = `7.4.0-rc1-dirty`.
- Driver: `scripts/plain_campaign.py`, CSV `tmp/logs/plain_campaign.csv`. Method: docs/PLAIN-KERNEL-TESTS.md.
- Trigger (#149): `zc_bench.py --secs 10 --perf` = fast-path UDP load (route mode, 1400 B) with `perf record -a -e cpu-clock -F 2000`, 3 runs per clock set, one boot per set.

## Clock sets

| Set | CPU | LX | DDR | SRAM | BogoMIPS |
|---|---|---|---|---|---|
| stock | 800 MHz | 175 MHz | stock | stock | 530.94 |
| picks | 1350 MHz | 306.25 MHz | 663 MHz | 500 MHz | 897.02 |

- Stock = `ramload mainline-kernel` (no `--pre`); picks = `ramload uboot-mainline --then mainline-kernel --pre "turbo cpu=1350,ddr=662,lx=306,sram=500"`.
- Kernel dmesg picks: `LX frequency from PLL: 306250 kHz, CPU 1350000 kHz`. Selftest clocks line: `cpu=1350,ddr=663,lx=306,sram=500`.

## #149 (rteth RX GRO NULL deref)

| Run | Clocks | Trigger | Result | Uptime at fail |
|---|---|---|---|---|
| stock 1 | 800/175 | zc + perf 2 kHz | no panic, 119.4 kpps zc | none |
| stock 2 | 800/175 | zc + perf 2 kHz | no panic, 119.3 kpps zc | none |
| stock 3 | 800/175 | zc + perf 2 kHz | no panic, 119.4 kpps zc | none |
| picks 1 | 1350/306 | zc + perf 2 kHz | no panic, 142.5 kpps zc | none |
| picks 2 | 1350/306 | zc + perf 2 kHz | no panic, 143.8 kpps zc | none |
| picks 3 | 1350/306 | zc + perf 2 kHz | no panic, 143.7 kpps zc | none |

- Verdict: 0/3 at stock, 0/3 at picks on the plain 7.4-rc1 kernel. Board uptime after the runs 3-5 min (clean boots, no reset).
- perf confirmed running each run (`/tmp/perf.data` written, report in `tmp/logs/perf_1400.txt`).
- Stack (non-zc) rate, same runs: stock 44.4 / 44.4 / 44.5 kpps; picks 62.1 / 51.4 / 63.2 kpps (picks stack rate noisy, zc rate stable +-1 %).
- zc/stack ratio: stock 2.7; picks 2.3-2.8.
- Not reproduced here: n=3 per set is small, the OpenWrt 7.3 panics were intermittent (exact rate not known); the difference to those runs is the kernel (7.4-rc1 vs 7.3), userland (plain vs OpenWrt, no bridge/STP/fw4) and the build config.
- dmesg during runs: `zc miss:` hexdump lines (zc bench debug print, not errors); once at picks `rtl838x_eth eth0: tx ring 0 busy, waiting for slot 16` (113 s uptime, during selftest).

## GDMA dmaengine (in-tree, patch 300-41)

- Probe (both sets): `rtl9300-gdma 1800a000.dma-controller: memcpy channel, burst 3` and `rtl9300-gdma 18018000.dma-controller: memcpy channel, burst 3`; `/sys/class/dma/` = `dma0chan0 dma1chan0`.
- `kmod/gdma_bench` (iters 200, `dma_map_single` + prep_memcpy + `dma_sync_wait`), all 8 sizes `bad 0 fails 0`:

| Len B | stock gdma | stock MB/s | picks gdma | picks MB/s |
|---|---|---|---|---|
| 64 | 54.0 us | 1 | 40.3 us | 1 |
| 1400 | 80.2 us | 17 | 56.2 us | 24 |
| 4096 | 144.9 us | 28 | 97.8 us | 41 |
| 16000 | 452.2 us | 35 | 310.6 us | 51 |
| 65000 | 1775.6 us | 36 | 1239.9 us | 52 |

- Out-of-tree polled reference (docs/HIDDEN-FEATURES.md, 7.3 picks, burst 3): 4096 B = 13.8 us (298 MB/s), 64 B = 1.3 us.
- In-tree driver through dmaengine is ~7x slower than that at 4096 B (picks 97.8 us) and has ~40 us fixed cost per transfer (64 B: 40.3 us vs 1.3 us). Fixed cost scales with CPU clock (54 -> 40 us), so it is software path (completion/wait), not the bus. Not investigated further.
- CPU memcpy for reference at 4096 B: stock 1133 MB/s, picks 1815 MB/s; at 32/65 kB (cache misses) 119-141 MB/s, still above GDMA 36-54 MB/s.
- Takeaway: GDMA via dmaengine is correct (0 bad) and not a speedup for memcpy.

## DSS die-speed probe (`dss_probe.py`, `dss_soak.py`)

- Sensors run (not in reset): 10 combos, `polls=1` (ready at once), no not-ready, count1 nonzero in 10/10 (both sets).
- count0 (sensor 0) is constant over combos; count1 varies with `ws`/`rs`:

| Set | count0 | count1 range | soak 1 min, 2 busy loops |
|---|---|---|---|
| stock | 17788 | 9727-17845 | counts 17917 / 13272 / 21394 / 15850 / 14731 / 9768 / 12235 / 11956 / 14584 / 12317 |
| picks | 30156 (30781 in a first read) | 16497-30262 | counts 30443 / 22544 / 36382 / 26929 / 25042 / 16610 / 20785 / 20310 / 24785 / 20941 |

- count0 picks/stock = 1.70 = CPU clock ratio 1350/800 (1.69): the count follows the CPU clock; so the unit is cycles of the sensor window against the CPU-derived clock, not die delay alone. Counts at picks vs stock scale 1.69-1.70 across all combos.
- Temperature (thermal_zone0, readings quantised ~1.3 C): stock 48.05 C after the 1 min soak; picks 46.76 C at the probe, 48.05 C after the soak. Short runs only.
- Soak: 6 samples, 0 fails, both sets.

## vlanproto (patch 644 hook)

- PASS at stock and picks: `VLAN protocol can't be changed on a bridge with switch ports`, extack ok, cleanup ran.

## Other steps

| Step | stock | picks |
|---|---|---|
| selftest | PASS (21 s) | PASS (20 s) |
| link | lan1 carrier up | lan1 carrier up |

## Surprising / problems fixed

- `./dev.py ramload mainline-kernel` loaded the old `tmp/tftp/mainline.bin` (2026-10-15 build), not the fresh `mainline-7.4-rc1.bin`. Fixed in `scripts/st1008_ramload.py` (file name from `kernel_base`).
- The ramload prompt marker `st1008f-linux # ` was split by kernel log lines on the bigger kernel: 10 s timeout. Marker now also matches `st1008f-initramfs: up`.
- `plain_campaign.py` bugs: reader thread never sent the EOF sentinel (every step "stalled" until the cap); stdin not detached; `gdma` step loaded the removed out-of-tree `rtl9300_gdma.ko`.
- `selftest.py` used `StrictHostKeyChecking=accept-new`: fails on the plain image (host key regenerated each boot). Now `no` + `/dev/null` known_hosts.
- `port-up`'s dropbear was gone in 2 of 3 boots (bench initramfs keygen race): `plain_mgmt` now starts it again if absent.
- Bench kmod build needed `make modules` once in the build tree (no `Module.symvers` after `build-kernel`).
- Boot log check: GDMA probe lines added to the allowlist (#62). `sfp ... Host maximum power 2.0W` lines get interleaved into other lines in the console log and show up as UNKNOWN (log interleave, not a new message).
- `nat_bench.py setup` ends with `ping natlan -> 10.99.2.2: FAIL` the first time; the following `mode route` makes it work (zc ran fine).

## GDMA completion latency (2026-11-07, #62)

- Before: kthread did run + complete; `device_issue_pending()` only woke it. Bench loop (`dma_map` x2, prep, `dma_sync_wait`, unmap x2, memset, memcmp) 4096 B: 144.9 us stock / 97.8 us picks; 64 B 54.0 / 40.3 us.
- After (`drivers/dma/rtl9300-gdma.c`, patch 300-41 refreshed): `issue_pending` runs the queue inline when the engine is idle and the head transfer is <= 16 KiB (`GDMA_INLINE_MAX`, ~55 us busy-wait at burst 3, bounded by the existing `limit_us`); bigger ones go to the kthread. Callbacks run from a tasklet. `busy` flag claims the engine under the spinlock (irqsave); runner re-checks the list before releasing it.
- Why inline poll, not IRQ: a 4 KiB transfer is ~14 us on the bus; IRQ entry + tasklet/wakeup costs the same order (the kthread wake alone was ~40 us), and the GDMA IRQ line (shared with the bus traffic generator) is untested. IRQ stays an option for transfers > 16 KiB.
- `kmod/gdma_bench` now also prints `xfer` = prep -> `dma_sync_wait` only (no map/unmap, memset, memcmp). 3 runs each, all 8 sizes bad 0 fails 0, spread < 3 %:

| Len B | stock xfer | stock loop | picks xfer | picks loop |
|---|---|---|---|---|
| 64 | 2.8 us | 5.4 us | 1.7 us | 3.3 us |
| 1400 | 9.3 us | 37 us | 6.0 us | 24.6 us |
| 4096 | 23.5 us | 101 us | 15.0 us | 66 us |
| 16000 | 85.7 us | 388 us | 57.8 us | 258 us |
| 65000 | 408 us | 1773 us | 276 us | 1225 us |

- Picks targets met (4096 B <= 20 us, 64 B <= 5 us). Loop time fell 44 us (stock) / 32 us (picks) at 4096 B = the removed fixed cost; the rest of the loop is cache maintenance in `dma_map_single`/`unmap` (non-coherent 34Kc), not the driver.
- Remaining gap to the old polled module (13.8 us at 4096 B): prep (`kzalloc`) + cookie + 8-block setup; remaining engine time ~ bus rate (4096 B at 15 us = 273 MB/s picks).

## #149 A/B on the OpenWrt 7.3 image (2026-11-07)

- Image `tmp/tftp/openwrt-ours-initramfs.bin` (next-20261009 + OpenWrt userland), cage 1, `scripts/panic_ab_trial.py` (fresh ramload, `nat-bench setup`, perf push, `zc_bench.py --nat --napi irq1 --secs 12 --len 1400 --perf`).

| Trial | Clocks | zc rate | Panic |
|---|---|---|---|
| picks 1 | 1350/306/662 | 114.5 kpps | no |
| picks 2 | same | 141.1 kpps | no |
| picks 3 | same | 139.6 kpps | no |
| stock 1 | 800 | 118.7 kpps | no |
| stock 2 | 800 | 108.9 kpps | no |
| stock 3 | 800 | 106.3 kpps | no |

- 0/6 panics; board alive after each (uptime 75-100 s at the end of the run, 54-60 C).
- Fixed on the way: `set_mgmt_ip` waited for the plain prompt (wrong on OpenWrt) and OpenWrt dropbear stayed bound to the old lan address; direct `ramload openwrt-ours` did not set the bench IP.

## #149 original reproducer: CPU 1350 / LX 204 (2026-11-07, 9 boots)

- Profile `turbo cpu=1350,ddr=662,lx=204,sram=500` (LX also 245, 175), cage 1, `scripts/panic_repro_trial.py`: fresh software-reboot ramload, read-only ssh polls (5 s) until uptime >= 90 s, then `nat-bench setup`, `zc_bench.py --nat --napi irq1 --secs 12 --len 1400` without perf, then with `--perf`.
- OpenWrt = `tmp/tftp/openwrt-ours-initramfs.bin` (7.3-next-20261009, in-tree GDMA). Plain = `mainline-7.4-rc1.bin` (12:00 build, after the 12:00 patch 300-41 refresh), bench config.

| Trial | Kernel | LX | Panic | Uptime at panic |
|---|---|---|---|---|
| 1a | OpenWrt 7.3 | 204 | no (zc 134.6 / 135.2 kpps) | - |
| 1b | OpenWrt 7.3 | 204 | yes, at start of no-perf zc | 101.6 s |
| 1c | OpenWrt 7.3 | 204 | no (132.3 / 131.6 kpps) | - |
| 2a | plain 7.4-rc1 | 204 | no (idle 172 s, zc started late: 134.2 / 134.2) | - |
| 2b | plain 7.4-rc1 | 204 | no (134.0 / 134.0) | - |
| 2c | plain 7.4-rc1 | 204 | no (132.0 / 134.3) | - |
| 3a | OpenWrt 7.3 | 245 | yes, in the perf zc (no-perf zc passed, 136.0 kpps) | 131.4 s |
| 3b | OpenWrt 7.3 | 175 | no (122.0 / 122.1 kpps) | - |

- Oops identical in 1b and 3a: `CPU 1 Unable to handle kernel paging request at virtual address 00000001`, epc `gro_list_prepare+0xac`, ra `dev_gro_receive+0x164` <- `gro_receive_skb+0x74` <- `rteth_hw_receive+0x24c` <- `rteth_poll_rx` <- `net_rx_action`. Task on CPU 1: `snmpd` (1b), `ksoftirqd/1` (3a): interrupted context differs, the faulting NAPI poll is the same. Kernel then `Kernel panic - not syncing: Fatal exception in interrupt`, reboot after 3 s; next boot cmdline `st1008f.lastreset=panic`.
- Idle phase (no traffic) to 90-94 s uptime: 0 panics in 3 OpenWrt LX 204 boots, 3 plain boots. The 37 s / 39 s panics of the first 7.3 builds did not recur; panics here came at the first fast-path UDP load.
- State at 90 s idle, OpenWrt LX 204: 57.1-59.7 C, BogoMIPS 892.92, dmesg `LX frequency from PLL: 204166 kHz, CPU 1350000 kHz`. After the zc runs 58-61 C (plain 48-49 C).
- Panic rate: OpenWrt 7.3 at CPU 1350: 2/5 across LX 204/245/175 (1/3, 1/1, 0/1); plain 7.4-rc1 at LX 204: 0/3 (campaign above: 0/6 at stock and LX 306). n is small; LX 175 and 306 earlier passed OpenWrt too, so no monotonic LX dependence is visible.
- Verdict: reproduces on the OpenWrt 7.3 image at CPU 1350 with LX 204 and 245 (traffic-triggered, perf not required: 1b was without perf); plain 7.4-rc1 does not (0/3 here, 0/6 earlier). Points at kernel build (7.3-next + OpenWrt config) or userland (snmpd, fw4, bridge/STP) rather than the clock alone. Not run: plain 7.4 at CPU 800 / LX 204 (skipped: plain did not panic).
- Script notes: `ramload` returns rc=1 on LX 204/245/175 boots because `boot_log_check` flags the new clock lines (`clocks: lx now 204166 kHz`, `turbo ...`) as UNKNOWN; boots are fine. Plain `--mgmt` boot 2a: lan1 NO-CARRIER at `port-up`, dropbear absent; `panic_repro_trial.py` now starts it over the console if ssh is refused.

## zc cache maintenance: header-only sync (2026-11-07)

- Hypothesis: the 1400 B size-dependent cost is cache maintenance over the whole frame; the CPU touches only the headers, so payload-line ops are unnecessary.
- Finding before the test: the zc TX path already wrote back only 128 B (V1 is the shipped behaviour). The remaining whole-buffer op is the 4096 B `DMA_FROM_DEVICE` invalidate in `page_pool_put_full_page` on TX done (last fragment of the page only).
- Patch 300-42 (default unchanged): `zc_sync_bytes` (default 128; TX writeback length), `zc_rx_part` (default 0; on TX done invalidate `zc_sync_bytes`+4 B at the frame and put the page with a 1 B pool sync).
  - Only for pages the stack never held: per-pfn bit set in `rteth_create_skb`/`rteth_append_skb`, cleared when the first fragment of a page is posted (a sibling fragment held by the stack keeps the full sync; page_pool syncs the whole page only on the last put).
  - Not `page->private`: page_pool overlays it with `pp_ref_count`. The first build used it and panicked at 7.7 s uptime in `kfree_skb_list_reason` with every variant off (my bug, not baseline; fixed).
- Setup: plain 7.4-rc1 bench kernel, picks 1350/306/662/500, cage 1, `zc_bench.py --nat --napi irq1 --zc-only --secs 12`, 3 rounds interleaved (`scripts/zc_sync_ab.py`, tag picks, `tmp/logs/zc_sync_ab.jsonl`). Series applied on OpenWrt 7e8bfcfe (isolated tree).

| Variant | 1400 B kpps | 500 B kpps | 64 B kpps | Integrity |
|---|---|---|---|---|
| base (TX 128 B, full recycle sync) | 144.0 (+-0.1 %) | 330.5 (+-0.2 %) | 415.7 (+-0.7 %) | PASS x3 |
| txfull (TX writeback of 1536 B, control) | 144.2 (+0.1 %) | 331.2 (+0.2 %) | 415.9 (0.0 %) | PASS x3 |
| rxpart (V2 = V3: header-only recycle) | 144.0 (0.0 %) | 330.2 (-0.1 %) | 409.7 (-1.5 %) | PASS x3 |

- Spread = (max-min)/mean over 3 runs. VPE1 99 % busy in all runs.
- Integrity: `zc_bench.py --nat --integrity`: udpblast pattern payload (sequence + derived filler), checked per packet by `udpcheck` in natwan; 1400/500/64 B, ~290k/660k/830k frames per variant per round, 0 bad.
- Verdict: falsified. Writing back the whole frame costs nothing measurable (+0.1 % at 1400 B); header-only recycle gives 0.0 % at 1400/500 B and -1.5 % at 64 B (outside spread, so slightly worse). The size-dependent cost is not cache maintenance; the remaining candidates are bus/DRAM traffic of the RX and TX DMA.
- No default change. No panic with 300-42 as built (fixed version): 0 oops over the A/B and integrity runs.

## CPU-port ceiling by direction: rx-only vs tx-only (2026-11-07, #147)

- Setup: plain 7.4-rc1 bench kernel built from committed HEAD cdbc252 without 300-42 (`scripts/head_bench_build.py`, isolated tree/out dir), picks 1350/306/662/500, cage 1, `--napi irq1` (NIC IRQ + softirq on VPE1), `scripts/ceiling_rxtx.py`, 6 s per run, logs `tmp/logs/ceiling_rxtx.jsonl`.
- rx-only = `nat_bench rxdrop` (host UDP flood 430-1700 kpps offered, dropped at lan1 netdev ingress). `rxx` = same with generic XDP drop (`--xdp skb`; native `drv` attach: "Not supported").
- tx-only = in-kernel pktgen on lan1 -> VLAN 992 -> host (far end counted on the host NIC, 100 % delivered); `tx2` = pktgen on both VPEs. Sizes are UDP payload bytes (pktgen frame = size + 42).
- Forwarding column = in-place path, `docs/CPU-PORT.md` frame-size sweep.

| UDP payload | rx-only kpps | tx-only kpps (1 / 2 threads) | forwarding kpps | ASIC drops per run |
|---|---|---|---|---|
| 64 | 228.3 (4.3 %, n=8) | 76.3 / 114.2 | 490.7 | EGR_QUEUE ~33k |
| 200 | 216.2 (1.8 %, n=3) | 94.3 / 119.7 | 409.6 | EGR_QUEUE ~27k |
| 500 | 193.9 (4.5 %, n=7) | 81.5 / 106.0 | 313.6 | EGR_QUEUE ~35k |
| 800 | 175.6 (8.2 %, n=3) | 80.8 / 94.9 | 225.6 | EGR_QUEUE ~33k |
| 1100 | 174.2 (8.3 %, n=3) | 79.2 / 86.0 | 173.0 | EGR_QUEUE ~30k |
| 1400 | 143.3 (0.3 %, n=2; 4 first runs 143.0-143.5) | 68.0 / 79.6 | 142.5 | EGR_QUEUE ~50k |

- Spread = (max-min)/mean over the valid runs. tx spread 8-52 % (pktgen is generator-bound, see below). ASIC drops = mean of the `EGR_QUEUE` count per rx run (clear-on-read); no other reason except `PORT_ISOLATION` 1-8; tx runs: 0 drops.
- rxx (generic XDP drop): 64 B 255.6 kpps, 200 B 236.7, 500 B 196.9, 800 B 172.5, 1100 B 151.6 (spread 0.1-2.3 %, n=3 each); 1400 B one valid run 132.7.
- CPU queue 1 peak (FC_CPU_Q_EGR_PAGE_CNT / PKT_CNT, clear-on-read, per run): 1025-1028 pages at every rx size, packets 1026 (64 B) / 513 (500 B) / 206 (1400 B). Threshold (300-40) at start: queue 1 ON 1024 / OFF 1008 pages, queues 0/2/3 78/68. Peak sits at the ON threshold in every valid rx run: the queue is full and the chip drops there; at 1400 B it holds 206 packets, at 64 B 1026.
- VPE1 busy 98.5 % at every rx size; VPE0 < 1 %. rx cost per packet 4.3 us (64 B) -> 6.9 us (1400 B) = ~1.9 ns/B on the skb path; XDP skb 3.9 -> 7.5 us.
- tx (pktgen): VPE0 88-92 % busy with VPE1 1-3 % at 1 thread = 12-14 us per packet; 2 threads saturate both VPEs (73-95 %) at only 1.1-1.6x the rate. Generator-bound: the TX-only rate of the driver is not reached; per-byte part 12.1 -> 13.5 us per packet (~1 ns/B), includes pktgen's own fill.
- Verdict (RX stage):
  - rx-only alone reproduces the forwarding ceiling at 1400 B (143.3 vs 142.5 kpps) and at 1100 B (174.2 vs 173.0): the ceiling does not need both directions; below 1100 B rx-drop is slower than forwarding (4.3 us vs 2.0 us at 64 B: skb alloc + GRO + stack against the in-place path).
  - Forwarding sends the same 143 kpps out through the CPU-port TX path (far end counted by the bench), so TX carries at least that rate at 1400 B; the tx column is a generator limit, not a TX ceiling.
  - Ceiling = ASIC -> CPU queue 1 -> NIC DMA -> VPE1 softirq (queue full at its threshold, chip drops `EGR_QUEUE`, VPE1 98 % busy). Per-byte RX cost ~1.9-2.7 ns/B of the ~4 ns/B forwarding total; the rest (~1-1.5 ns/B) is TX-side.
  - Not resolved: how much of the RX per-byte time is DMA/bus wait vs cache maintenance (falsified earlier, #147).
- Problem (new): rx flood runs go dead after the first 1-3 runs of a series: no frame reaches the CPU queue (queue peak 2 pages, `EGR_QUEUE` 0), lan1 `dot1dTpPortInDiscards` +845k in a 3 s flood while the MAC counts all 1.17 M frames, host sends normally, no oops, no `rx_MacDiscards`. Ping and ssh still work; a state with 0.0 kpps for 5 runs in a row recovered after pause/other traffic, then ran at 143 kpps again. Valid-run counts above are n valid of n runs in `tmp/logs/ceiling_rxtx.jsonl` (stalled runs: kpps < 5 or VPE1 < 90 %; 43 of 69 rx runs, 23 of 38 rxx). The XDP tool leaves ~3 zombie `st1008f-xdp` processes per run on sw2 (initramfs init does not reap).

## Flash image: boot-link-check x10 and #138 hang-test (2026-11-07)

- Image: flash OpenWrt 6.18.60 (built 2026-11-04 21:34+11:00), sw2 slot b, picks off (`bootsel fast` default clocks), chain installed. Console log byte range 27277549 .. end, grepped with `grep -a`-equivalent on the bytes.
- `./dev.py boot-link-check --rounds 10` (13:07-13:17+11:00): 10/10 rounds `up ['lan1']; missing none; linkwatch bounces 0`; 10 `Run /sbin/init`.

| String (per round, rounds 1-10) | Count |
|---|---|
| `could not sync clock` | 0 in every round |
| `clock not ready, retry` | 0 in every round |
| `board silent` | 0 in every round |
| `board alive, console silent` | 0 in every round |

- #138: 0 silent boards in 10 (previous run 2026-10-15: console silent ~30 s after `Run /sbin/init` until the relay). #137: 0 `could not sync clock` in 10 boots (earlier logs: SerDes 6/9 at ~21 s uptime).
- `./dev.py uboot-chain-env hang-test` (slot b, `init=/bin/sh`, `bootsel wdt on` 13 s): FAIL. Kernel cmdline had `watchdog.open_timeout=92`; `Run /bin/sh as init` at 1.95 s; no SoC reset within the 165 s limit (uptime 167 s), shell still alive at 216 s (`/sys/class/watchdog/`: watchdog0 = `18003260.watchdog`, watchdog1 = a virtual `watchdog` device). Recovered with `reboot -f` over the console. DEFAULT-BOOT.md records the same test passing on 2026-10-15 (reset 6 s after `/bin/sh`, #138 image); this image is newer (OpenWrt bump 2026-11-04) -> the open_timeout stop-feeding path does not reset the board here. Not diagnosed; file against #138.

## Two-ring receive split, PIE CPU-queue rule (2026-11-07, #146)

- Setup: plain 7.4-rc1 bench kernel + 300-43 (`tmp/tftp/mainline-7.4-rc1-ring.bin`), picks 1350/306/662/500, cage 1, `rtl838x_eth.cpuq0_drop_pages=1024` (queue 1 1024 by default, both 1024/1008 pages), threaded NAPI ring N on VPE N, `tx_by_cpu=1`, eth0 `noqueue`, zc on both rings (`zc_ring 2`, TX ring = CPU & 1), udpblast 1400 B, 64 flows (source port 40000+i, one destination port), 10 s per run, n=3 interleaved, `scripts/ring_split_ab.py --tag ring2` (rows `tmp/logs/ring_split_ab.jsonl`).
- Variants: rt0 / rt1 = `l3_net_route` ring 0 / 1; par = rt1 + PIE `sport 1 0 0` and `sport 1 1 1` (UDP, action = CPU queue id only); par_acl1 = par + `acl_hit` queue 1.
- Busy % = non-idle jiffies / run wall time (counters read idle before and after: ssh to the board stalls while a loaded ring carries the control plane; a windowed first attempt was discarded). Integrity = udpcheck pattern run per variant and round (bad payloads / reorder per source port).

| Variant | kpps (min-max) | VPE0 / VPE1 busy % | ring0 / ring1 frames (mean per run) | tag QID 0 / 1 | EGR_QUEUE per run | bad / reorder |
|---|---|---|---|---|---|---|
| rt0 | 143.3 (142.8-143.5) | 100 / 0 | 1.46 M / 36 | 1.46 M / 36 | 39201 | 0 / 0 |
| rt1 | 136.7 (136.4-136.9) | 0 / 87 | 58 / 1.44 M | 58 / 1.44 M | 50863 | 0 / 0 |
| par | 124.0 (115.3-128.5) | 96 / 56 | 0.67 M / 0.65 M | same | 14967 | 0 / 0 |
| par_acl1 | 128.2 (126.8-128.9) | 100 / 63 (one run 156 / 66: jiffy accounting) | 0.69 M / 0.70 M | same | 33315 | 0 / 0 |

- Steering works: the ACL CPU-QID action overrides the reason queue of the L3-trapped frame (ring share 50 / 50 in every par run, tag QID 0 and 1 equal, no forward action needed, route trap kept); `acl_hit` queue is not needed.
- zc TX ring full on ring 0: `ring0_zc_busy` 78-104 k per run (frames fall back to the skb path), ring 1 0.
- Verdict (rule of #146): FAIL, "rate drops with both VPEs busy": 124-128 kpps with both VPEs busy vs 143.3 (rt0) / 136.7 (rt1) with one. The shared 34Kc pipeline, not one VPE, is the limit; splitting receive does not raise the ceiling. EGR_QUEUE drops fall (par 15 k vs rt1 51 k) but the rate does not.
- Side result: with all traffic on ring 0 / VPE0 the rate is 143.3 kpps vs 136.7 on ring 1 / VPE1 (earlier 143 on VPE1 with `irq1` softirq instead of the NAPI thread).
- Panics: none (#149 `gro_list_prepare` not seen; stack path is not used on the zc path).

## Switch-core clock vs the 1400 B ceiling (2026-11-07, hypothesis from #147)

- Setup: plain 7.4-rc1 bench kernel (`mainline-7.4-rc1.bin`), picks 1350/306/662/500, cage 1, `--napi irq1`, route mode. Logs `tmp/logs/swc_<mhz>_*.log`.
- Change: after `turbo ...`, `--pre "mw.l 0xbb00e220 <v>"` (DIVN2_SWCORE bits 8:5 only), then relock `mw.l 0xbb00e200 0x0001c0ff` / `0x4001c0ff` (e200 bit 30 0 -> 1; reads back `0001c0ff`). No U-Boot code change.
- Switch-core clock = SW VCO / (2 x (code + 2)), codes 0..3 tried; Realtek's SPL never writes this field (glb_pll.h default code 1).

| Switch core | e220 | rx-only 1400 B kpps | forwarding zc+nat 1400 B kpps | rx-only 64 B kpps | integrity | notes |
|---|---|---|---|---|---|---|
| 245 MHz (code 3) | 0002c466 | 86.6 (0.8 %, n=3) | not obtained | 224.6 (n=1) | - | -39.6 % rate for -40 % clock |
| 306 MHz (code 2) | 0002c446 | 108.1 (0.5 %, n=3) | 110.0 (n=1) | 231.8 (n=1) | PASS 1400/500/64 | -24.7 % for -25 % |
| 408 MHz (code 1, stock) | 0002c426 | 143.5 (0.2 %, n=3) | 144.8 (n=1) | 220.9 (n=1) | PASS 1400/500/64 | baseline |
| 612 MHz (code 0) | 0002c406 | 182.3 (177.2 / 182.8 / 187.0, n=3) | not obtained | 223.3 (n=1) | - | +27 % for +50 % clock; board unreachable after the rx runs |

- Verdict: hypothesis confirmed. The 1400 B receive and forwarding ceiling scales 1:1 with the switch-core clock downward (rate ratio 0.753 / 0.603 vs clock ratio 0.75 / 0.60) and the VPE ns per packet follows it (6.9 us at 408, 9.1 us at 306, 5.4-5.6 us at 612). 64 B is not affected (220-232 kpps at every clock: VPE-bound).
- Upward: +50 % clock gives +27 % (sub-proportional: a second limit enters, VPE1 still 98.9 % busy). Stable for the three rx runs; afterwards sw2 stopped answering on lan1 (ping, ssh dead; console alive, kernel up, NIC IRQ count not rising).
- Not obtained: forwarding and integrity at 245 and 612. In the zc-only flows (`nat_bench setup` ~8 s after boot) lan1 went silent right after setup at both clocks (also at 612 in a clean boot, once with manual setup 15 s after boot). Unexplained; whether it is clock related or the harness is unknown. 408 and 306 ran the same flow without it.
- Silent corruption: none at 408 and 306 (udpcheck good 221k-847k per length, bad 0, reorder 0). ASIC `EGR_QUEUE` drops in rx runs unchanged in kind (rx flood fills queue 1 at every clock).
- Console grep after all boots: no oops/panic (no `gro_list_prepare`), #149 not seen.
- Boot-check note: `ramload ... --pre mw.l/md.l` reports `rc 1` from `boot_log_check` UNKNOWN lines (`clocks: ... lx now`, `turbo ...`) when the console log is checked late; board boots fine.

## Switch-core clock: why 612 fails, stable range (2026-11-07, #148)

- Setup: plain 7.4-rc1 bench kernel, `turbo cpu=1350,ddr=662,lx=306 (245 for the 575/658 rows),sram=500`, cage 1, route mode, `--napi irq1`. Driver `scripts/swcore_step.py` (ramload + clock change + rx / forwarding / integrity per boot), logs `tmp/logs/swcore_step_*.log`, state dumps `scripts/swcore_diag.py`.
- Clock change: SW VCO = 50 MHz x (e214 NCODE + 2) (e214 `0x2f8` = 47 -> 2450 MHz); switch core = VCO / (2 x (code + 2)). e214 acts at once (no relock needed) and changes LX/NOR as well: write e220 (new LX/NOR codes) and e214 in one U-Boot line, then relock (e200 bit 30).

### The 612 failure

- Wedge: CPU queue 1 stays full (1030 pages / 206+ packets), ring-1 DMA stops. Evidence at the wedge (3 of 3 times):
  - ring 1 has 128 free descriptors (all owned by the ASIC), `RX_RING_CNTR` 0, `DMA_INTR_RX_DONE_STS`/`RUNOUT_STS` 0, masks open (3), `DMA_IF_CTRL` unchanged, NIC IRQ count frozen.
  - Not a link fault: lan1 / sw1 lan4 stay `Link detected: yes`, 10G; sw1 lan4 logged one Down/Up in the relock second at boot, none later.
  - Not a register wipe: `MAC_FORCE_MODE_CTRL(28)` 0x217, `MAC_L2_CPU_PORT_CTRL` 0, `THR[1]` 0x040003F0, `QM_CPUQID2QID`, `QM_CPUQID2XGQID`, DMA base registers read identical right after the relock and at the wedge.
  - Recovery: `ip link set eth0 down; up` (NIC queue reset); slowing the clock live to 408, toggling `DMA_IF_CTRL` RX/TX enable, and writing `RX_RING_CNTR` do not recover.
- Trigger: forwarding (RX+TX together), not rx-only. rx-only 1400 B n=3 twice plus 64 B ran clean at 612 (one 64 B run in a row read 6 pps for 8 s, then recovered). Forwarding wedged in the stack-baseline / zc run or the first integrity run: 4 of 4 tries at 612 (fresh boot x2, live from 408 x2); never at 408, 508, 575, 608, 658 (15 boots).
- Order: clock change before `turbo` wedges the same as after (`--swc-first`). So the order is not the cause.
- Cause narrowed to the divider code, not the frequency: code 0 (VCO / 4, VCO 2450) wedges; code 1 at VCO 3650 = 608 MHz (same speed) passes 3 of 3 boots with the best forwarding. Code 0 is never used by Realtek's SPL (glb_pll.h default 1); candidate: the /4 output of the divider (duty / edge) feeding the queue-manager-to-DMA handshake.

### Steps (1400 B, picks, rx-only n=3 per boot; zc+nat forwarding 12 s; integrity 1400/500/64)

| Switch core | SW VCO / code / LX | rx-only kpps | zc+nat fwd kpps | integrity | boots |
|---|---|---|---|---|---|
| 408 (stock) | 2450 / 1 / 306 | 143.5 | 144.8 | PASS | 1 |
| 508 | 3050 / 1 / 305 | 164.0, 171.8, 167.6 | 159.4, 159.2, 158.9 | PASS x3 | 3 |
| 575 | 3450 / 1 / 246 | 173.5, 145.4 (one 81 run), 168.9 | 153.2, 153.7, 153.4 | PASS x3 | 3 |
| 608 | 3650 / 1 / 304 | 173.0, 174.6, 175.9 | 170.4, 170.0, 170.3 | PASS x3 | 3 |
| 658 | 3950 / 1 / 247 | 182.4, 175.7, 155.3 (spread 30 %) | 153.5, 153.3, 153.2 | PASS x3 | 3 |
| 612 | 2450 / 0 / 306 | 173-182 | wedge | not reached | 4 wedges |

- Conditions: 2026-11-07, sw2, cage 1 to sw1 lan4, host NIC 10G, kernel `7.4.0-rc1-dirty`; rx numbers vary +-5 % with the host flood (sent 430-830 kpps); one 575 rx run (80.9 kpps) coincided with a low host send rate.
- Forwarding depends on LX as well: 575 and 658 (LX 246) forward 153 kpps, 608 and 508 (LX 305) 159-170, rx-only does not. LX is part of the rate; compare rows with equal LX only.
- Gain stops near 170-182 kpps rx (VPE1 98-99 % busy, 5.4-5.7 us per packet): the CPU-port ceiling stops being the clock above ~500 MHz.
- Temperature: sensor `thermal_zone0` reads 49.3 -> 53.2 C over all steps (never above 53.2 C); abort limit 85 C.
- Panics: none in the step runs (no `gro_list_prepare`, #149 not seen). The one `kfree_skb_list_reason` panic in the console log is from 12:46, before this work.
- Link at boot: lan1 comes up ~4 s after `port-up` (one ramload check ran before it, `BOOT FAIL` in the harness only); the SW PLL relock drops the cage 1 link for ~1 s (sw1 lan4 Link Down/Up 0.9 s apart), not SerDes related: the link is up and clean before and after at every setting.
- Harness notes: dropbear is not started when `port-up` finds no carrier (`dropbear -R -B` from the console); `ssh` host-key warnings go to stderr; a raw `mw.l 0xbb00e214` garbles the console until e220 re-codes LX, so e220 + e214 + relock go in one line.

## Old options re-tested at 608 MHz (2026-11-07, owner rule: re-test after a core-clock move)

- Setup: sw2, plain 7.4-rc1 bench kernel (ring image for the split), picks 1350/662/500, core 608 = SW VCO 3650 / code 1 (e214 `0x478`, e220 `0x36826`, LX 304); 408 = stock. One NAT interface (`nat-bench setup`, route mode), cage 1, `--napi irq1` unless stated. Driver `scripts/retest_options.py` (rows `tmp/logs/retest_options.jsonl`), ring split `scripts/ring_split_ab.py`.
- Method: one 6 s run per option point against baselines of the same boot; repeats only within 5 % of baseline. Verdict: wins >= 1.03 x, loses <= 0.97 x, else ties; metric = zc+nat forwarding 1400 B (rx-only 1400 B varies +-6 % with the host flood: 177.2 / 180.6 / 160.8 on the same boot, forwarding 169.2-170.7).
- SPI safety check (608, read live): e220 `0x36826` NOR code 11 -> NOR clock 3650 / 26 = 140.4 MHz, SFCR `0x5fc00244` divide 6 -> SCK 23.4 MHz (stock 25.5): below stock, no fix needed. 408 reads code 6 / divide 6 = 25.5 MHz.

Baselines (same boot per column):

| metric | 408 | 608 |
|---|---|---|
| rx-only 1400 B kpps (VPE0/VPE1 busy %) | 142.1 (3/98) | 177.2 / 180.6 / 160.8 (2/99) |
| rx-only 64 B kpps | 219.1 (3/98) | 220.4 (6/98) |
| zc+nat fwd 1400 B kpps | 144.8 (0/98) | 169.2 / 169.4 / 169.2 / 170.7 / 170.2 (1/98) |
| zc+nat fwd 64 B kpps | 421.9 (0/98) | 424.5 (3/97) |
| stack path fwd 1400 B kpps | - | 60.2 (1/98) |
| NAT TCP P4 zc+nat fwd / rev Mbit/s | 1458 / 1463 | 1634 / 1631 |
| NAT TCP P4 stack fwd / rev Mbit/s | 413 / 409 | 422 / 413 |

Options (kpps = zc+nat fwd 1400 B unless stated):

| option | 408 baseline | 608 | verdict | VPE0/VPE1 busy |
|---|---|---|---|---|
| two-ring split par (ring image, rt0 = 163.6 mean of 5) | par 124.0 vs rt0 143.3 | par 123.8, par_acl1 110.9, rt1 145.8 | loses (-24 %) | par 122/71 |
| NAPI split (ring thread per VPE) | - | 165.3, 151.0, 166.2 vs 169.3 | loses | 2/97, 3/68, 2/99 |
| NAPI threaded, unpinned | - | 162.6, 157.5, 164.6 | loses (-3 to -7 %) | 11/81, 45/39, 83/14 |
| tx_by_cpu=1 | - | 168.5 | ties | 6/96 |
| noqueue | - | 169.2 | ties | 3/99 |
| tx_by_cpu=1 + noqueue | - | 170.2 | ties | 1/99 |
| CPU queue 1 threshold 78 / 512 / 4095 pages | - | 169.1 / 169.5 / 169.4 | ties | 1-2/99 |
| CPU queue 0 threshold 78 / 4095 (ring image, rt0) | - | 161.5 / 164.2 vs 163.6 | ties | 100/6-43 |
| zc fast path vs stack | 144.8 vs 44.4-62.1 | 169.3 vs 60.2 | zc wins 2.8x | 1/98 |
| GRO fraglist off, NAT TCP P4 stack | - | 275 / 271 vs 422 / 413 Mbit/s | loses (-35 %) | not read |
| GRO fraglist off, NAT TCP P4 zc+nat | - | 1630 / 1642 vs 1634 / 1631 | ties | not read |
| rings in SRAM (`sram_rings=3`) | no traffic | no traffic (eth0 up, no ping), as at 408 | dead | - |
| cache variants (300-42 `zc_sync_bytes`, `zc_rx_part`) | < 0.3 % at 1400 B | not run: the plain image lacks the parked params; needs a kernel build with 300-42 | open | - |
| SRAM-resident packet buffers | - | no driver parameter exists | not testable | - |

- Second CPU: no option makes it useful. Forwarding is 97-99 % busy on VPE1 (the NIC IRQ + softirq CPU) at 608 and 408; every arrangement that loads VPE0 as well (par, split, threaded) is slower. Ring 0 / VPE0 alone does 163.6 vs 169.3 on VPE1.
- Best at 608: zc+nat forwarding 1400 B 169-171 kpps (+17 % on 408), NAT TCP P4 zc+nat 1634 / 1631 Mbit/s (+12 %), 64 B forwarding 424.5 kpps (unchanged: VPE-bound).
- Ring image reorder: rt0 / rt1 rounds in the first run showed reorder 5272 / 3273 (udpcheck, 64 flows, bad 0); later rt0 runs 0. Not diagnosed.
- Hangs / recoveries: none. Panics: none (no `gro_list_prepare`, #149 not seen; console scan clean for all rows). Temperature 49.3-53.2 C.
- `nat_bench setup` returns rc 1 (`ping natlan -> natwan: FAIL`) in every boot here, benches ran fine afterwards.
