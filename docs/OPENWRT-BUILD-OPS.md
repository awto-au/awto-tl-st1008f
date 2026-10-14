# Local OpenWrt build: operations

Facts, patch status, sizes: [OPENWRT-BUILD.md](OPENWRT-BUILD.md). Log: `tmp/logs/build_openwrt.log`; make output `tmp/logs/build_openwrt-make.log`.

## Build

```
./dev.py build-openwrt                      # step 1: OpenWrt 6.18 + backports -> tmp/tftp/openwrt-ours-6.18-initramfs[-std].bin
./dev.py build-openwrt --kernel-only        # re-patch + kernel + images only (after one full build)
./dev.py build-openwrt --kernel mainline    # step 2: our port on the kernel-base (linux-next) as OpenWrt testing kernel -> tmp/tftp/openwrt-ours-initramfs[-std].bin
./dev.py build-openwrt --update             # pull newest OpenWrt main first (re-check every rebased patch)
./dev.py build-openwrt --no-overlay         # stock OpenWrt main (baseline)
```

- Defaults: `-j8`, nice 19, ionice idle. Disk floor 4 GB: checked before each phase and every 30 s during make; on abort a comment goes to #73 (`--no-comment` to skip).
- After any kernel config change (PREEMPT, SMP, `--regen-config`): full `./dev.py build-openwrt --kernel mainline`, not `--kernel-only` (stale kmods fail with `section size must match`).
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

## Flash install on sw2 (step 1 image, upstream layout)

Writes only `firmware` (flash_guard, #81). Never on sw1.

```
./dev.py ramload openwrt-ours-6.18            # RAM boot of the image to install from
./dev.py openwrt-static-ip --ip 192.168.25.56
./dev.py openwrt-install                      # sysupgrade -T, sysupgrade -n, reboot via stock autoboot, STP saved
./dev.py openwrt-luci --ip 192.168.25.56      # apk from the upstream feeds (needs internet)
./dev.py openwrt-snmp --ip 192.168.25.56
./dev.py uboot-chain-env boot                 # software reboot: stock -> saved chain -> ours -> flash OpenWrt, STP on
./dev.py switch-check --ip 192.168.25.56 --wait 50
```

- First flash boot formats the JFFS2 overlay: `sync` or the STP `uci commit` blocks up to ~70 s; the flow allows 90 s.
- A new install has a new dropbear host key; the flow drops the old one from `known_hosts` first. If a step still reports "REMOTE HOST IDENTIFICATION HAS CHANGED", run `ssh-keygen -R 192.168.25.56` and rerun that step.
- `openwrt-install --after-reboot` resumes after the sysupgrade when the console step failed.
- `openwrt-sysupgrade-ssh` timing (sw2, 2026-10-14, 6816044 B image r0-0ad1348): SSH stays up through the flash write; `sysupgrade` start to `Rebooting system` 61 s. `DOWN_S` 80 = x1.25 (was 60: timed out on this image).
- First boot after a sysupgrade (sw2, 2026-10-14T11:12+11:00, same image): jffs2 overlay format; OpenWrt console at kernel 73.5 s vs 7.9-8.6 s for normal boots (last 11 chain boots). `uboot-chain-env boot` extends its console wait by 82 s (65 s x1.25) when it sees `jffs2_build_filesystem(): unlocking` (#132).
- Moving the buildroot (`build-openwrt --update`) and the mainline pin (`OWRT_COMMIT`) go together: rebuild with `build-kernel` and boot `ramload mainline-kernel` once.
