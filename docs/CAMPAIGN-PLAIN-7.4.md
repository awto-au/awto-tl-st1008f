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
