# Default boot: operations

Design and facts: [DEFAULT-BOOT.md](DEFAULT-BOOT.md). Issue #73. Steps 4, 6, 8 and revert write flash under the standing approval (owner 2026-10-12; never `0x0`-`0xDFFFF`). The env-flag test writes `u-boot-env` outside `uboot-chain-env`: needs an explicit owner OK. Every write range passes `scripts/flash_guard.py` first (#81).

## Preconditions

- Track-1 buildroot with `openwrt/default-boot/0001-*.patch`, `files/`, `diffconfig` and `openwrt/patches/300-15` applied → `tmp/tftp/openwrt-ours-initramfs.bin`, `openwrt-73-sysupgrade.bin`, `openwrt-recovery-initramfs.bin`.
- `./dev.py default-boot check` → no BAD line (headers, CRCs, slot sizes, split-layout DTB in each kernel).
- `./dev.py storm-watch --duration <s>` running for every board step; console log open.

## Steps

| # | Command | Pass |
|---|---|---|
| 1 | `./dev.py default-boot test` | ramload CLEAN; STP 1, forward_delay 200, lan DHCP, 192.168.0.1/24 up, no DHCP server, `recovery` in `/proc/mtd`, `devmem` reads, `uname` 7.3, dropbear, mode state (`gpio`) matches every port's `isolated` |
| 2 | Short run of the RAM-booted test image: boot, traffic via `nat-bench`, storm-watch on (no long soak: owner 2026-10-12) | storm-watch silent; no SG2008P `OSW_DET_LOOP`; `logread` clean |
| 3 | `./dev.py ramload openwrt` then `scripts/st1008_mtd_backup.py --host 192.168.25.48` | fresh `private/mtd-backup-<ts>/` (the 2026-10-08 one holds stock firmware, not OpenWrt 25.12.4) |
| 4 | `./dev.py build-uboot`; `./dev.py uboot-chain-install --overwrite` (flash, approval) | power-up log: `Boot:  legacy (no image in recovery slot ...)`, flash OpenWrt as before |
| 5 | At our prompt (`ramload uboot-mainline`): `bootsel`, then `bootsel clear; bootsel wdt 2000`; at the caught stock prompt `md.l 0xae000000 3` | board resets ~2.3 s after (6 x 383 ms); record reads `5b007ec0 00000000 ffffffff` = DRAM kept through reset + preloader + stock (else: reset-cause design) |
| 6 | `./dev.py default-boot test`, then `./dev.py default-boot install primary --i-have-owner-approval` | sysupgrade → reboot → `Boot:  legacy` → primary 7.3; shell checks pass |
| 7 | Flash primary: 3 relay power cycles (`./dev.py power off/on`) | each boot: STP on, `.48` reachable, check-log clean |
| 8 | `./dev.py default-boot install recovery --i-have-owner-approval` | read-back md5 matches |
| 9 | Fallback tests (below) | as listed |
| 10 | Mode tests (below) | as listed |

## Fallback tests (step 9)

| Test | How | Expect |
|---|---|---|
| Confirmed boot | power-cycle | `Boot:  primary (attempt 1/2 ...)`; `logread -e st1008f-bootok` = confirmed |
| Unconfirmed x2 | at primary: `devmem 0x0e000004 32 2; devmem 0x0e000008 32 0xfffffffd; reboot` | `Boot:  fallback (2 primary boots not confirmed ...)`, recovery OpenWrt with STP |
| Sticky until power cycle | `reboot` from recovery | recovery again; after relay off/on → primary |
| M3 | slide to M3, power-cycle (`./dev.py mode-map boot --expect M3`) | `Boot:  primary (...)`; `bootsel: M3: …` turbo or stock-with-reason line (#46) |
| M2 | slide to M2, power-cycle | `Boot:  primary (...)`, autoboot; `st1008f.mode=m2` in `/proc/cmdline` |
| Hang | `bootsel wdt 3000` at our prompt, then `bootm 0xb4300000` with a hung-kernel image (none yet) | not run until a test image exists |
| Env flag (flash write, approval) | `fw_setenv st1008f_boot fallback` at primary; power-cycle; then `fw_setenv st1008f_boot` | recovery; then primary |

## Chain slot check (#105)

sw2 first, all of it; sw1 only after sw2 passes. Rows 1-3 write nothing.

| # | Command | Pass |
|---|---|---|
| 1 | `./dev.py build-uboot` | `chain slot: uboot-mainline-chain.bin, slot CRC32 …`; `python3 scripts/uboot_chain_image.py check tmp/tftp/uboot-mainline-chain.bin` PASS |
| 2 | `./dev.py uboot-chain-env test-bad` (sw2, stock prompt, nothing saved) | `word at 0x…` mismatch, no `U-Boot 2026.07` banner, stock `boota` → flash OpenWrt, STP on = `run` stops on `cmp.l` failure |
| 3 | `./dev.py uboot-chain-env test` with the OLD raw image still in flash | reports FAIL `slot check FAILED -> stock boota -> flash OpenWrt`, OpenWrt up with STP = the new env on a pre-#105 image falls back, no hang |
| 4 | `./dev.py uboot-chain-install --overwrite` (sw2, flash OpenWrt console) | read-back md5 PASS |
| 5 | `./dev.py uboot-chain-env test` | `Total of 1 word were the same`, our banner, `Autoboot in 2 s, ESC for the prompt`, `bootsel: M1: stock clocks …`, flash OpenWrt |
| 6 | `./dev.py uboot-chain-env apply` | slot check OK, all vars as set |
| 7 | `./dev.py uboot-chain-env boot`; `./dev.py uboot-chain-env prompt` | boot PASS (`bootsel: M<n>: …` line); prompt PASS (ESC stops ours); also send a non-ESC byte in the window by hand (`scripts/switch_console.py send --raw x`): autoboot continues |
| 8 | At our prompt (row 7): `clocks set cpu 0x3a8 0x6b439e13 0 force` | `locked after N us (routine M us)`, M > 0 = TC5 counts |
| 9 | At our prompt: `clocks turbo 1000 650 0`, then `clocks` | `clocks: turbo = cpu 1000 MHz, mem 650 MHz, lx 175 MHz …` |
| 10 | Idle reset: at our prompt `setenv bootretry 30` (manual run of the failed-autoboot path), wait | `Timeout waiting for command`, board resets, chain boots again (30 s here only to keep the test short) |
| 11 | sw2: `./dev.py uboot-chain-env turbo show`; `apply --ssh --ip 192.168.25.56` and `turbo set cpu=1000,ddr=650 --ssh --ip 192.168.25.56` from its flash OpenWrt | PASS read-back lines; console `turbo show` matches |
| 12 | sw2 in M3, power-cycle (`./dev.py uboot-chain-env boot`) | `bootsel: M3: turbo cpu 1000 ddr 650 lx 0`, `clocks: turbo = cpu 1000 MHz, mem 650 MHz …` |

sw1 (SSH only, in service), all before its next power-up, after sw2 passes:

1. `./dev.py uboot-chain-install-ssh --ip 192.168.25.48` → read-back CRC PASS.
2. `./dev.py uboot-chain-env apply --ssh --ip 192.168.25.48` → slot OK, chain vars read back.
3. Stock clocks from the next power-up (default, owner 2026-10-13). To keep a turbo: `./dev.py uboot-chain-env turbo set PROFILE --ssh --ip 192.168.25.48` and the owner moves the slider to M3 (position today: unknown).

- The new slot follows the mode switch and the env profile: without both, sw1 boots at stock 800/600.
- Revert: `./dev.py uboot-chain-env revert` (stock `boota`); old U-Boot: `uboot-chain-install --overwrite` with a previous slot build.

## Mode tests (step 10)

Preconditions: DHCP reservation `.48` for the `switch.1` MAC (owner, house DHCP server); host NIC with an extra `192.168.0.2/24` address; two host-side links (two cages, or the host + a second machine) for the isolation test. Only one cage to the house switch at a time, every mode (cage loop hazard; loop tests use a cage-to-cage patch).

| Mode | How | Expect |
|---|---|---|
| all | `cat /proc/cmdline; cat /var/run/st1008f-mode; logread -e st1008f-` | `st1008f.mode=mN st1008f.boot=…`; state `mN <image> <switch or isolated> cmdline`; bootok confirmed |
| all | host on any one cage: `ping 192.168.0.1`, `ping 192.168.25.48`, `ssh root@192.168.0.1` | both answer; `ip -6 a s switch.1` = `fe80::` + SLAAC address (if the LAN has RA) |
| all | from the host: DHCP leases / `nmap -sU -p67 --script dhcp-discover` on the cage | the switch never answers DHCP or RA |
| M1 | `cat /sys/class/net/switch/brif/*/isolated`; `bridge link`; two hosts on two cages ping each other | all 0; ports `forwarding`; pings pass (bridged in hardware: after ARP, CPU-port counters do not follow the ping rate) |
| M1 | `cat /sys/class/net/switch/bridge/stp_state`; patch cage C ↔ cage D to each other (fibre or GLC-T pair; not to the house switch), storm-watch on | 1; `bridge link`: one of C/D `blocking`; no storm |
| M2 | `cat /sys/class/net/switch/brif/*/isolated` | all 1 |
| M2 | two hosts on cages A/B, same subnet (e.g. 192.168.0.2 / .3): ping A→B, ARP broadcast, `iperf3` | no reply, no ARP seen on B; both still reach 192.168.0.1 |
| M2 | patch cage C ↔ cage D to each other, storm-watch on; then `stp_state` 0 for 30 s, back to 1 | STP on: one of C/D `blocking`; STP off: still no storm (isolation alone) |
| M2 | hardware evidence: `grep -i isolation /sys/kernel/debug/rtl838x/drop_counters` before/after the A→B ping | `PORT_ISOLATION` drop counter rises (switch ASIC drops, not the CPU bridge) |
| M3 / fault | as M2, on the recovery image | as M2 |
| change | M2 → M1, power-cycle | `logread`: `st1008f-mode … switch`; one `uci commit` (mode changed); next same-mode boot commits nothing (`uci changes` empty) |

## Status

- `./dev.py default-boot status` at any OpenWrt shell: `/proc/mtd`, env flag, attempt word, bootok log, kernel.
- `bootsel` at our U-Boot prompt.

## Revert

- `./dev.py ramload openwrt` (upstream initramfs, stock 29 MiB layout), then `./dev.py default-boot revert --backup private/mtd-backup-<ts> --i-have-owner-approval`: writes the backed-up `firmware` (OpenWrt 25.12.4 + its overlay) back.
- Our U-Boot can stay: no image in `recovery` → legacy boot. Old U-Boot: `uboot-chain-install --overwrite` with the previous build.
- Chain off entirely: `./dev.py uboot-chain-env revert`.
