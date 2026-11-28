# sw1 kernel panics: evidence, candidate causes, test order (#186)

Owner rules 2026-11-23: not a temperature issue; unhandled/spurious interrupts must be explained; every other cause is tested before any slow-clock test.

## Handover 2026-11-27
- State: sw1 powered on by the owner 2026-11-27 ~10:40+11:00, up after its own panic reboots (see Findings 2026-11-27). sw2 (.56): plain rc4b image, slot b, config restored, up.
- Done off-hardware: RX driver read (no stray writer found), DMA masters on sw2 (only the NIC active), `dbg` image (slab poison, red zones, DEBUG_LIST) on sw2: `xfer_check` clean, `nat_bench rxdrop` flood clean (debug kernel only takes ~9.5 kpps).
- Next, in order:
  - ~~Network-free copy/compare~~ done 2026-11-27: kernel panic in round 5, no NIC load (Findings 2026-11-27).
  - `./dev.py nat-bench rxdrop` on sw2 plain image (reaches higher pps than `dbg`).
  - Flash `tmp/openwrt-7.4stk-sysupgrade.bin` to sw1 (watchdog pretimeout panic, 16 KiB stacks); `--pull` mode, verify md5 and slot flip (ssh pushes crash sw1).
  - `tmp/openwrt-7.4dbg-debug-sysupgrade.bin` on sw1 (slab poison, DEBUG_LIST): a use-after-free reports instead of crashing.
  - Same U-Boot slot on sw1 as sw2 (candidate 8), then the rest of the list below; slow-clock test last.
- Flash tool bug found 2026-11-27 (sw2, slot a -> b): `openwrt_sysupgrade_ssh.py` printed `TIMEOUT 105 s waiting for the unit to drop off`, the unit booted slot b with default config (DHCP, .119) instead of the saved static .56. Recovery: `ssh ... 'cat > /tmp/restore.tar.gz' < private/sysupgrade-backup/<ip>-<stamp>.tar.gz`, then `sysupgrade -r /tmp/restore.tar.gz; reboot`. Cause not found; check before the next A/B flash.
- Console: the daemon was not running; `./dev.py console-restart` started it, `scripts/switch_console.py send "<cmd>"` drives the serial shell.

## Evidence (sw1 = st1008f-1, new image, CPU 1325 / core 608; sw2 same image does not panic)
- Panics: boot #11 up 188 s `Fatal exception in interrupt`; #13 up 65 s `copy_pte_range` BadVA 0x1d in `sh` fork; #14 up 216 s `epc 0x40000000` out of `except_vec_vi_end+0xc4` (idle task); #19 up 810 s `__pgd_free` with a garbage instruction word; further reboots at 120 s, 560 s, 2120 s with no record.
- Common: a corrupted pointer or code word in generic code, different place each time = a stray write or CPU fault, not one driver function.
- At the crash the CPU port is quiet to the last 10 ms sample (rx <= 7 packets, irq <= 6 per 10 ms, no drops, rings flat); no change in 256 KiB of kernel head + DTB watched ten times a second (`scripts/tools/fastsample.c`).
- Crashes cluster at the start of 9 Gbit/s ASIC-forwarded traffic through sw1 and at boot-time selftest stress. Not reproduced by: 12 idle minutes, 6 x bench setup/teardown, 6 x offload on/off (no traffic).
- Not the cause: eth0 IRQ pin (removed), DDR 662 vs 600, selftest alone (disabled).
- Static interrupt check: only hwirq 5/7/13/23/24/30 enabled in the intc (all have consumers), switch IMR_GLB = 1 (link only). `ERR` (spurious_interrupt) about 1 per 5 min on both units: source unknown, logging patch 300-48.

## Findings 2026-11-23 (image rc4b: Linux v7.4-rc4, 62 KiB pstore, 300-48/49/50, bus monitors enabled by devmem)
- Spurious interrupts explained on sw2: UART hwirq 30 (IP3) and NIC hwirq 24 (IP5) glitches; benign, no ERR source left unexplained. `masked source pending` lines for hwirq 7/8 (timer bits) and 17 are raw GISR status of lines masked on that CPU, not faults.
- Unaligned-access fixups: SPI driver fixed (300-50).
- Flash-time crash (sysupgrade, up 63 s): `copy_pte_range` ll on BadVA 0x1d, PTE word 0x21cd7609 (above RAM end) = a corrupted user PTE, same BadVA 0x1d as boot #13. Page-table memory corrupted, same family as #149.
- Traffic-onset crash (up 72 s, no oops, hang): bench setup started, rx on eth0 went 25 -> 18494 pps in the last second; flood samples show 800-1600 frames per 10 ms with ring 0 level at 1024 (full) then a 137 ms gap, then dead. CPU port was NOT quiet here. Cause 1/2 candidate: ring-full/overrun path in the rteth RX driver.
- Crash with GRO and rx-gro-list OFF (up 197 s, 3 s after a 90 kpps one-way UDP flood hit the CPU port): `__netif_receive_skb_one_core` BadVA 0x9 (skb->dev == 1) in `process_backlog`. GRO is not the cause.
- GRO-on crash (up 608 s): `list_add corruption` in `gro_receive_skb`, list head `prev` points inside an `skbuff_head_cache` object = a GRO list entry freed or overwritten.
- Pattern across every record: a pointer replaced by the small integer 1 (BadVA 1, 0x1d, 0x9; `a0 == 1` folio pointer; `epc 0x40000000` earlier), in different generic code each time. A stray write of the word 1 into freed or reused memory. Candidates: an RX ring/descriptor ownership word written through a stale address, or another DMA master. The hang crashes (no oops) fit the same writer hitting something fatal.
- Trigger: 90-160 kpps into sw1's CPU port (flooded one-way UDP, or the bench setup burst); 500 Mbit/s x 4 UDP completed once, crashed within seconds twice. sw2 handles the same load. Reproducer without the ASIC path: host-to-sw1 UDP flood on the CPU alone (nat_bench local).
- Watchdog: SoC watchdog runs (29 s). Image `stk` (not yet on sw1) adds the pretimeout panic (phase-1 IRQ at 24 s) so a hang with interrupts on leaves an oops, 16 KiB stacks (300-51) and stack-overflow checks.
- Data corruption on sw1, not on sw2 (`scripts/xfer_check.py`: random 8 MB pushed over ssh into /tmp, md5 + diff). sw2: 8 of 8 rounds clean. sw1: rounds with 1-3 flipped bytes (single bits, mostly bit 3 cleared: 7b->73, ca->c2, ef->e7, 5f->57, b8->b0), one round with a 5194-byte stretch of wrong data; a stall or crash within 4 rounds each time. Same with rx checksum offload off, so the corruption happens after the software checksum, in CPU/RAM/DMA-coherence land.
- Userspace RAM test (`scripts/tools/memtest.c`, 280 MB, 4 patterns, 40 s each, physical addresses): 0 mismatches on sw1 and sw2. CPU-only RAM traffic is clean; the faults appear with NIC DMA + copy traffic.
- sw1 went unreachable for more than 5 min after the xfer test (link up on sw2's DAC side, no ping reply, SoC watchdog did not bring it back).
- `scripts/openwrt_sysupgrade_ssh.py` now fails when the booted slot did not flip (a panic during the flash gave a false PASS).

## Findings 2026-11-27 (sw1, rc4b image, CPU 1325 / core 608, BogoMIPS 875.72)
- Idle panic (no test running, up 5340 s, ~12:09+11:00): NULL deref in `hrtimer_start_range_ns_user` from `usleep_range_state` <- `rtl9300_i2c_do_xfer` <- `st_media_work` (SFP media poll). Panic reboot by itself. Record: `tmp/logs/sw1_pstore_20261127.log`.
- Network-free copy test (`scripts/copy_check.py`: 16 MiB urandom in /tmp, per round `cp` + md5 of src and dst on the box, only status lines over ssh): rounds 1-4 clean (1.44-1.49 s each, 64 MiB copied, 0 flipped bytes), panic in round 5 at up 14425 s (16:09:16+11:00), back on ssh 55 s later.
  - Oops: `inode_permission+0xd0` from `statx` in `st1008f-metrics`, BadVA 4 = `lhu 2(s0)` with s0 = 2: an inode pointer replaced by the small integer 2. Same fingerprint as every earlier record.
  - Record: `tmp/logs/sw1_copycheck_crash_20261127T1609.log`.
- Verdict: the kernel-pointer corruption does not need NIC bulk traffic; CPU + RAM (page-cache) churn alone triggers it within seconds. Bulk copied data stayed intact, so the fault hits kernel objects, not the copy buffers. Weights candidates 3 (DRAM on sw1), 4 (CPU/MT-SMP) and 8 (U-Boot/DDR init) over 1, 2 and 6 (NIC/DMA/SerDes).
- Temperatures, both idle (95 % idle), read 2026-11-27T16:47+11:00, same clocks: sw1 SoC `cpu-thermal` 82.9 °C (up 37 min) vs sw2 58.4 °C (up 3 h 50 min). Critical trip 105 °C, no passive trip. sw1 SFP DDM 40.8-49.1 °C, copper module 59.9 °C; sw2 sfp_p8 57.2 °C. Per-chip sensor offset not ruled out.
- `masked source pending` hwirq 7/8 lines run at ~10 per 5 s on sw1 up to the oops (raw GISR of masked lines, see 2026-11-23).
- Hang ~21:24+11:00 (boot 16:10, up 18869 s): no oops, no pstore record, blackbox `state=unclean (hang, watchdog or power cut)`, boot 64.
- First boot with the same U-Boot slot as sw2 + `ddr=662` (candidate 8) at ~21:25+11:00: idle, up 10 h 47 min at 2026-11-28T08:12+11:00, no panic, no new pstore record. SoC 79.0 °C vs sw2 54.5 °C.

## Findings 2026-11-28 (after the swap: sw2 at the lab spot, rc4b image, CPU 1325 / DDR 662 / core 608)
- sw2 at the lab spot now carries the lab load: SFP-10G-T copper module on lan1 (house uplink, 1000 Mb/s), 10GSR on lan5-8; config still its bench config (#188).
- 2 h stress, 08:47-10:48+11:00: `stress_trace.py --full --duration 7200` (93 selftest runs, CPU + all memory patterns) plus `copy_check.py --rounds 3000 --stall-s 60` alongside. Result: PASS, no ping loss, 0 of 3000 copy rounds corrupted (16 MiB each), no oops, no pstore record, dmesg clean.
- Temps (`rail_watch.py`, one sample per 1.6 s median, 4474 samples): SoC 55.8-59.7 °C; copper module PHY 65.2-66.7 °C; SFP modules 36.8-45.7 °C.
- 3.3 V cage rail (SFP DDM Vcc): per cage range ≤ 14 mV over the run, 3.268-3.309 V overall (SFF-8472 range 3.135-3.465 V). No droop under load.
- 10 ms Vcc polling (`vcc_watch.py`, on-box `vccsample`, SCHED_FIFO), 2026-11-28T13:33+11:00, 150 s incl. one selftest run (CPU 60 s + mem 30 s):
  - Read cost per cage: ~0.9 ms (10GSR), ~8.7 ms (SFP-10G-T in cage 1) -> cage 1 read once per second, the other 4 every tick.
  - 97 sweeps/s achieved (14568), 2.5 % late (371); slowest sweep 190 ms (kernel I2C users on the same master, e.g. sfp poll / `st_media_work`).
  - Module Vcc resolution ~13-14 mV per step (3277 <-> 3290); cage 7 toggles ~40 times/s = module updates at least that fast.
  - Range: 3261-3309 mV; lowest = one step on cage 8; 0 dips >= 30 mV below the previous second's mean.
- Two SFP-10G-T (AQR113C) in sw2 cages 3 + 4, cabled to each other, 2026-11-28T13:53-13:55+11:00 (`rail_watch.py`):
  - Ports admin down: cage 3 Vcc 3.322 V, cage 4 3.188-3.192 V; cage 4 case temp still rising (45.2 -> 47.2 °C) = `ip link set down` does not power the module down.
  - Ports up, 10 Gb/s link: cage 3 3.322 -> 3.213-3.222 V (-100 mV), cage 4 3.190 -> 3.097-3.103 V (-90 mV); PHYs 63.6 -> 67.1 °C within 45 s (critical 70).
  - Cage 4 at 3.10 V is below the SFP+ supply minimum (3.135 V, SFF-8431); DDM Vcc accuracy is +/-3 % (SFF-8472), so it is at the limit, not proven under.
  - Other cages unchanged (3.275-3.295 V) = the drop is local to the loaded cages (cage filter / module), not a sag of the shared 3.3 V rail.
  - 10G link 13:55-14:00, no traffic: cage 4 PHY 65.6 -> 85.9 °C (~4 °C/min, still rising), case 74.3 °C (module case rating 70 °C), Vcc down to 3.072 V. Cage 3 PHY sensor frozen at 66.875 °C for 8 min while its case went 31 -> 55 °C, and lan3 kept carrier 1 after the far end dropped = cage 3 module PHY hung.
  - After lan4 went to a netns (link down ~14:00) the link never returned (2 min in the netns, 1 min back in the main ns); cage 4 PHY cooled to 59.6 °C by 14:03.
- Verdict: the lab-spot load (copper module, house uplink, fast clocks) does not make sw2 fault, and the 3.3 V rail holds. sw1's fault and heat stay with sw1 so far; sw1 at the bench is the next check.

## Off-hardware review 2026-11-24 (sw2 + driver source, sw1 off)
- RX path (`rteth_hw_receive`, `rteth_create_skb`, page pool: `PP_FLAG_DMA_SYNC_DEV`, `max_len` = PAGE_SIZE, 2 frags of 2048 per page): no stray write found. Ordering is rmb / dma_wmb correct, the new page is allocated before the old one is consumed, ring and descriptor memory is coherent DDR (`sram_rings` = 0 on sw2).
- Cache model: 34Kc needs no post-DMA flush, so correctness rests on the page-level sync at recycle (whole page, invalidate). No path found where the CPU dirties a posted buffer's lines.
- Not excluded: zero-copy forward (`zc`, line ~1961 header write-back of 128 bytes), GRO frag pages held while a sibling frag is on the ring.
- DMA masters on sw2: two GDMA channels (`dma0chan0`, `dma1chan0`, 0 transfers, no client), SPI dirmap (14000000, reads only), SRAM 0x1f000000 (rings not in it). Nothing active besides the NIC.
- Bit-3-cleared flips (7b->73, ca->c2, ...) look like one weak data-path bit (cache or bus), not a software writer. Network-free copy test on sw1 decides.
- Debug image `dbg` (slab poison/red zone/sanity, DEBUG_LIST) on sw2 (slot a, trial), 2026-11-24: `xfer_check` 8 + 3 rounds clean; `nat_bench rxdrop` 15 s at 64 B (TrueNAS flood, 1.1 Mpps sent, CPU0 99 % softirq, debug kernel takes ~9.5 kpps, rings overrun): no poison, redzone, list or fragment error, no oops, sw2 up. The debug kernel is too slow to reach 90 kpps at the CPU; plain-image flood on sw2 is the matching test.

## Candidate causes and tests (status)
0. Same family as #149 ([GRO-CORRUPTION-149.md](GRO-CORRUPTION-149.md), writer never identified): OpenWrt image + our patches panicked repeatedly at fast clocks in `gro_list_prepare` (2026-11-08 counts void: contended shared-host generator, #165; traces stay forensic evidence) with a bad list node inside the NIC private memory (`napi->poll_list`), BadVA 1 / small values as pointers; the plain minimal-initramfs kernel survived the same clocks. sw1 (busier OpenWrt userland: lldpd, snmpd, collectd, linkwatch, metricsd) may hit the same bug more often. Its diagnostics (`rtl838x_eth.gro_diag=1`, `DEBUG_NET=y`, patch 300-45) exist and were never run on sw1. CP0 Cause.TI (0x40000000) is set in every oops incl. #149's (Compare unused): not specific.
1. NIC RX DMA writes outside its buffers / page reuse (rteth page pool, rx-gro-list, GRO fraglist; #149 history). Test: sw1 with `rx-gro-list` off; debug image (`--debug`: SLUB_DEBUG_ON, PAGE_POISONING, DEBUG_LIST) on sw1 so a use-after-free reports instead of crashing. NOT DONE.
2. Another DMA master writing RAM: RTL9300 GDMA memcpy engine (300-41), SPI-NOR dirmap reads (300-07), L2 notification ring, SRAM window remap (300-21). Test: list which are bound on sw1 (`dmesg`, `/proc/iomem`), widen the stray-write detector to all kernel text + the page-table pool. NOT DONE.
3. DRAM faults on sw1's own chip (training, refresh): Test: U-Boot `memtest` on sw1 at the live profile, long pass. NOT DONE.
4. CPU erratum / MT-SMP (34Kc branch + return prediction on, both VPEs): Test: `maxcpus=1` (one VPE) and a build that sets Config7 BP/RPS off, compare crash rate. NOT DONE.
5. Spurious interrupts: Test: log each one with both intc banks and CP0 cause/status (300-48, image `spur`). Explained on sw2 (see Findings 2026-11-23); sw1 NOT DONE.
6. sw1's SerDes 8 (lan7, #171) RX calibration worker failing every ~30 s with `rtpcs_93xx_rx_cali_work` on a deprecated workqueue: periodic kernel work on SFP/cable-specific state (sw1 has AQR113C copper, DAC, fibre; sw2 does not). Test: take lan7's SFP out of the bridge / tx-disable it and rerun the soak; check crash times against the 30 s cycle. NOT DONE.
7. Our patches (rebased at the OpenWrt bump; loop detect 300-26 sends a probe every second, L3 300-17, 300-43): sw1 ran the previous image 19 h 50 min idle with the fast profile without a panic. Test: bisect by building without 300-26, then 300-17, then 300-43. NOT DONE.
8. Different U-Boot on sw1 (installed 2026-11-21, sw2 2026-11-23: MCR reads `0x20e41e60` vs `0x20e41c60` in logs). Test: install the same U-Boot slot on sw1 (ssh, allowed). NOT DONE.
9. Per-unit config: sw1 loop detect, STP, VLAN 991/992 tags, SFP set. Test: sw2 config on sw1 and reverse. NOT DONE.
10. Power / load step (not temperature): Test: ramped versus stepped traffic onset on sw1. NOT DONE.
11. CPU writer vs DMA writer (complements 2): MIPS WatchLo/Hi on the corrupted word, both VPEs, value-filtered, `dump_stack()` on hit. Watch fires = CPU writer named; silent watch + corrupt word = DMA. NOT DONE.
12. Slow-clock test (stock clocks): LAST, only after every other candidate.
13. Power supply / power budget (owner 2026-11-28): fast profile (CPU 1325, DDR 662, core 608) plus copper 10G-T modules (SFP-10G-T, AQR113C) at the lab position; no budget kept. Sensor: SFP DDM Vcc per cage = the 3.3 V cage rail (`scripts/rail_watch.py`, one sample per 1.6 s: sees a steady sag only, not ms-scale dips). Test: sw2 at the lab spot (copper module, house uplink) under 2 h stress + copy load, rails logged; sw1 at the bench without the copper load. sw2 half DONE 2026-11-28: no fault, 3.3 V rail flat (Findings 2026-11-28); sw1 at the bench NOT DONE. Core rail unmeasured (no sensor). No interrupt or DMA path for Vcc: SFP has no alert pin (board wires MOD-DEF0 + TX_DISABLE only, no LOS/TX_FAULT), the switch-core I2C master is trigger + poll with a 16-byte window and no IRQ/DMA field (docs/REGISTERS.md `I2C_MST1_CTRL1/2`). A ms-scale dip needs a scope on the rail. 10 ms polling: `scripts/vcc_watch.py` (Findings 2026-11-28).

## Tools
- `scripts/tools/fastsample.c` + `scripts/fastsample_rx.py`: 100 Hz CPU-port counters, IRQ counts, ring frames, stray-write watch, UDP to the host.
- `scripts/xfer_check.py IP`: data over ssh into /tmp, md5 + diff (NIC RX path). `scripts/copy_check.py IP`: same check with on-box data, no NIC load; stall guard 1.25 x slowest round, `--stall-s` alongside other load. `scripts/rail_watch.py IP`: SFP Vcc (3.3 V rail) + temps.
- `scripts/sw1_crash_soak.py`: sustained ASIC-routed traffic with a 1 Hz sw1 poll. `scripts/irq_stream_matrix.py`: IRQ placement x stream count.
- sw1 crash record: `/sys/kernel/debug/st1008f-blackbox/last`, `/sys/fs/pstore/console-ramoops-0` (2 KiB; the enlarged region in the DTS did not take effect in the image).
