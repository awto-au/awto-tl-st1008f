# sw1 kernel panics: evidence, candidate causes, test order (#186)

Owner rules 2026-11-23: not a temperature issue; unhandled/spurious interrupts must be explained; every other cause is tested before any slow-clock test.

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
- `scripts/openwrt_sysupgrade_ssh.py` now fails when the booted slot did not flip (a panic during the flash gave a false PASS).

## Candidate causes and tests (status)
0. Same family as #149 ([GRO-CORRUPTION-149.md](GRO-CORRUPTION-149.md), writer never identified): OpenWrt image + our patches panicked 9 of 11 boots at fast clocks in `gro_list_prepare` with a bad list node inside the NIC private memory (`napi->poll_list`), BadVA 1 / small values as pointers; the plain minimal-initramfs kernel survived the same clocks. sw1 (busier OpenWrt userland: lldpd, snmpd, collectd, linkwatch, metricsd) may hit the same bug more often. Its diagnostics (`rtl838x_eth.gro_diag=1`, `DEBUG_NET=y`, patch 300-45) exist and were never run on sw1. CP0 Cause.TI (0x40000000) is set in every oops incl. #149's (Compare unused): not specific.
1. NIC RX DMA writes outside its buffers / page reuse (rteth page pool, rx-gro-list, GRO fraglist; #149 history). Test: sw1 with `rx-gro-list` off; debug image (`--debug`: SLUB_DEBUG_ON, PAGE_POISONING, DEBUG_LIST) on sw1 so a use-after-free reports instead of crashing. NOT DONE.
2. Another DMA master writing RAM: RTL9300 GDMA memcpy engine (300-41), SPI-NOR dirmap reads (300-07), L2 notification ring, SRAM window remap (300-21). Test: list which are bound on sw1 (`dmesg`, `/proc/iomem`), widen the stray-write detector to all kernel text + the page-table pool. NOT DONE.
3. DRAM faults on sw1's own chip (training, refresh): Test: U-Boot `memtest` on sw1 at the live profile, long pass. NOT DONE.
4. CPU erratum / MT-SMP (34Kc branch + return prediction on, both VPEs): Test: `maxcpus=1` (one VPE) and a build that sets Config7 BP/RPS off, compare crash rate. NOT DONE.
5. Spurious interrupts: Test: log each one with both intc banks and CP0 cause/status (300-48, image `spur`). IN PROGRESS.
6. sw1's SerDes 8 (lan7, #171) RX calibration worker failing every ~30 s with `rtpcs_93xx_rx_cali_work` on a deprecated workqueue: periodic kernel work on SFP/cable-specific state (sw1 has AQR113C copper, DAC, fibre; sw2 does not). Test: take lan7's SFP out of the bridge / tx-disable it and rerun the soak; check crash times against the 30 s cycle. NOT DONE.
7. Our patches (rebased at the OpenWrt bump; loop detect 300-26 sends a probe every second, L3 300-17, 300-43): sw1 ran the previous image 19 h 50 min idle with the fast profile without a panic. Test: bisect by building without 300-26, then 300-17, then 300-43. NOT DONE.
8. Different U-Boot on sw1 (installed 2026-11-21, sw2 2026-11-23: MCR reads `0x20e41e60` vs `0x20e41c60` in logs). Test: install the same U-Boot slot on sw1 (ssh, allowed). NOT DONE.
9. Per-unit config: sw1 loop detect, STP, VLAN 991/992 tags, SFP set. Test: sw2 config on sw1 and reverse. NOT DONE.
10. Power / load step (not temperature): Test: ramped versus stepped traffic onset on sw1. NOT DONE.
11. Slow-clock test (stock clocks): LAST, only after 1-10.

## Tools
- `scripts/tools/fastsample.c` + `scripts/fastsample_rx.py`: 100 Hz CPU-port counters, IRQ counts, ring frames, stray-write watch, UDP to the host.
- `scripts/sw1_crash_soak.py`: sustained ASIC-routed traffic with a 1 Hz sw1 poll. `scripts/irq_stream_matrix.py`: IRQ placement x stream count.
- sw1 crash record: `/sys/kernel/debug/st1008f-blackbox/last`, `/sys/fs/pstore/console-ramoops-0` (2 KiB; the enlarged region in the DTS did not take effect in the image).
