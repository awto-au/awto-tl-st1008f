# Default boot: operations

Design and facts: [DEFAULT-BOOT.md](DEFAULT-BOOT.md). Issue #73. Steps 4, 6, 8, the env-flag test and revert write flash: each needs an explicit owner OK.

## Preconditions

- Track-1 buildroot with `openwrt/default-boot/0001-*.patch`, `files/`, `diffconfig` and `openwrt/patches/300-15` applied → `tmp/tftp/openwrt-ours-initramfs.bin`, `openwrt-73-sysupgrade.bin`, `openwrt-recovery-initramfs.bin`.
- `./dev.py default-boot check` → no BAD line (headers, CRCs, slot sizes, split-layout DTB in each kernel).
- `./dev.py storm-watch --duration <s>` running for every board step; console log open.

## Steps

| # | Command | Pass |
|---|---|---|
| 1 | `./dev.py default-boot test` | ramload CLEAN; STP 1, forward_delay 200, lan .48/.254, `recovery` in `/proc/mtd`, `devmem` reads, `uname` 7.3, dropbear |
| 2 | 24 h soak of the RAM-booted test image (#54 settings) | storm-watch silent; no SG2008P `OSW_DET_LOOP`; `logread` clean |
| 3 | `./dev.py ramload openwrt` then `scripts/st1008_mtd_backup.py --host 192.168.25.48` | fresh `private/mtd-backup-<ts>/` (the 2026-10-08 one holds stock firmware, not OpenWrt 25.12.4) |
| 4 | `./dev.py build-uboot`; `./dev.py uboot-chain-install --overwrite` (flash, approval) | power-up log: `Boot:  legacy (no image in recovery slot ...)`, flash OpenWrt as before |
| 5 | At our prompt (`ramload uboot-mainline`): `bootsel`, then `bootsel clear; bootsel wdt 2000`; at the caught stock prompt `md.l 0xae000000 3` | board resets ~2.3 s after (6 x 383 ms); record reads `5b007ec0 00000000 ffffffff` = DRAM kept through reset + preloader + stock (else: reset-cause design) |
| 6 | `./dev.py default-boot test`, then `./dev.py default-boot install primary --i-have-owner-approval` | sysupgrade → reboot → `Boot:  legacy` → primary 7.3; shell checks pass |
| 7 | 24 h soak of flash primary; 3 relay power cycles (`./dev.py power off/on`) | each boot: STP on, `.48` reachable, check-log clean |
| 8 | `./dev.py default-boot install recovery --i-have-owner-approval` | read-back md5 matches |
| 9 | Fallback tests (below) | as listed |

## Fallback tests (step 9)

| Test | How | Expect |
|---|---|---|
| Confirmed boot | power-cycle | `Boot:  primary (attempt 1/2 ...)`; `logread -e st1008f-bootok` = confirmed |
| Unconfirmed x2 | at primary: `devmem 0x0e000004 32 2; devmem 0x0e000008 32 0xfffffffd; reboot` | `Boot:  fallback (2 primary boots not confirmed ...)`, recovery OpenWrt with STP |
| Sticky until power cycle | `reboot` from recovery | recovery again; after relay off/on → primary |
| M3 | slide to M3, power-cycle (`./dev.py mode-map boot --expect M3` adapted) | `Boot:  fallback (mode switch M3)` |
| M2 | slide to M2, power-cycle | prompt |
| Hang | `bootsel wdt 3000` at our prompt, then `bootm 0xb4300000` with a hung-kernel image (none yet) | not run until a test image exists |
| Env flag (flash write, approval) | `fw_setenv st1008f_boot fallback` at primary; power-cycle; then `fw_setenv st1008f_boot` | recovery; then primary |

## Status

- `./dev.py default-boot status` at any OpenWrt shell: `/proc/mtd`, env flag, attempt word, bootok log, kernel.
- `bootsel` at our U-Boot prompt.

## Revert

- `./dev.py ramload openwrt` (upstream initramfs, stock 29 MiB layout), then `./dev.py default-boot revert --backup private/mtd-backup-<ts> --i-have-owner-approval`: writes the backed-up `firmware` (OpenWrt 25.12.4 + its overlay) back.
- Our U-Boot can stay: no image in `recovery` → legacy boot. Old U-Boot: `uboot-chain-install --overwrite` with the previous build.
- Chain off entirely: `./dev.py uboot-chain-env revert`.
