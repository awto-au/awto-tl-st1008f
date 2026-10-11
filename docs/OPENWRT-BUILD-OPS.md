# Local OpenWrt build: operations

Facts, patch status, sizes: [OPENWRT-BUILD.md](OPENWRT-BUILD.md). Log: `tmp/logs/build_openwrt.log`; make output `tmp/logs/build_openwrt-make.log`.

## Build

```
./dev.py build-openwrt                      # step 1: OpenWrt 6.18 + backports -> tmp/tftp/openwrt-ours-6.18-initramfs[-std].bin
./dev.py build-openwrt --kernel-only        # re-patch + kernel + images only (after one full build)
./dev.py build-openwrt --kernel 7.3         # step 2: our 7.3 port as OpenWrt testing kernel -> tmp/tftp/openwrt-ours-initramfs[-std].bin
./dev.py build-openwrt --update             # pull newest OpenWrt main first (re-check every rebased patch)
./dev.py build-openwrt --no-overlay         # stock OpenWrt main (baseline)
```

- Defaults: `-j8`, nice 19, ionice idle. Disk floor 4 GB: checked before each phase and every 30 s during make; on abort a comment goes to #73 (`--no-comment` to skip).
- A rebased patch that stops applying after `--update`: `--prepare-only` (unpacks + patches the kernel tree, stops), fix in a scratch copy, regenerate with `scripts/patch_from_tree.py`.

## Board test (step 1 image)

Single cage, storm-watch running, console log open.

```
./dev.py storm-watch --duration 1800 &
./dev.py ramload openwrt-ours-6.18 --cage 1                       # stock U-Boot bootm, CPU 800 MHz
./dev.py ramload uboot-mainline --then openwrt-ours-6.18 --cage 1 # ours: clocks fast (1 GHz), bootm std copy
./dev.py check-log
```

Expected boot lines (new ones are UNKNOWN to `check-log` until reviewed into the allowlist):

- `RTL930x DRAM controller prefetch on (MCR ...)` (300-04; bits 23/22 set)
- `CPU frequency from PLL: 800MHz` (stock) / `1000MHz` (`--then`, ours) (300-05)
- `tplink-st1008f-mode mode-switch: cur pattern = N` + `pins 17/18/19 = ...` + per-port `media` lines (300-06)
- `dirmap: 0x...+0x... via window, SFCR2 ...` (300-07) or `dirmap: window != PIO ..., using PIO` (#61 failure mode)
- `rteth`/`rtl838x-eth` probe, `lanN` link up on the lit cage (300-11/12)
- 512 MiB visible (`free` total ~500 MB; HIGHMEM)

Then NAT throughput against the stock-OpenWrt baseline (243-248 Mbit/s TCP, [NAT.md](NAT.md)):

```
./dev.py openwrt-static-ip                 # .48 on the RAM-booted image
./dev.py nat-bench setup
./dev.py nat-bench mode nat
./dev.py nat-bench run --secs 20 -P 4
./dev.py nat-bench teardown
```

## Board test (step 2 image, OpenWrt on our 7.3)

```
./dev.py ramload uboot-mainline --then openwrt-ours --cage 1      # ours: clocks fast, bootm std copy
./dev.py ramload openwrt-ours --cage 1                            # stock U-Boot bootm (CPU 800 MHz)
./dev.py check-log
```

- Same expected lines as step 1, plus the 7.3 port's (MAINLINE-NET-OPS.md): rtl83xx DSA probe, `lanN` from the mainline DTS labels, eth0 MAC from env `ethaddr`.
- `default-boot test` ([DEFAULT-BOOT-OPS.md](DEFAULT-BOOT-OPS.md)) uses this image name.
- Then the same `nat-bench` set as step 1; compare against step 1 and the stock baseline.
