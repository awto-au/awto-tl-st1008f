# Canary: regression run on sw2

- `./dev.py canary` (`scripts/canary.py`): existing checks in a fixed order, one verdict each, one CSV row per run.
- Why: #138 hang-test passed 2026-10-15, failed on the 2026-11-04 image; nothing ran it routinely.
- Bench unit sw2 only. Refuses `192.168.25.48` and any IP other than `BENCH_IP` (`scripts/boards.py`). Exit 2 = refused.
- Verdicts: PASS, WARN (works, value off or stale baseline), FAIL, NOTRUN (not run: unselected, prerequisite failed, board dead, backstop). NOTRUN is never a PASS or a FAIL.
- Exit 0 = no FAIL. 1 = at least one FAIL. A dead board after a FAIL (ping) stops the run, no power action.
- Each check: stall timeout (no output, or console-log growth for flows that print only at the end) + total cap; run backstop 1800 s. Basis per check in `./dev.py canary --list`.
- Outputs: `tmp/logs/canary.log`, `tmp/logs/canary.csv` (one row: verdict per check, `zc_kpps`, `gdma_ns_4096`, `hang_reset_s`, secs).

## Run

| Command | Does |
|---|---|
| `./dev.py canary` | full run, A then B |
| `./dev.py canary --dry-run` | every command and cap, touches nothing |
| `./dev.py canary --list` | checks, caps, basis |
| `./dev.py canary --only a` / `b` / `zc,gdma` | group or ids. Ids alone assume the board is already in that state |
| `./dev.py canary --no-ramload` | plain kernel (picks) already booted |
| `./dev.py canary --update-baseline` | after a full all-PASS run: write new values, print diff |
| `python3 scripts/canary.py --selftest` | verdict-logic tests, host only |

- A runs on the flash image (needs the chain installed, slot b). B starts with `ramload uboot-mainline --stock-clocks --then mainline-kernel --cage 1 --mgmt` plus two `--pre` lines: `--plain-turbo` (default `turbo cpu=1325,ddr=662,lx=306,sram=500`) and `--plain-raw` (default raw core 608: e220 0x36826, e214 0x478; `''` = none). After the boot it starts dropbear via the console (plain kernel has none).
- Cage loop hazard: one cage lit (cage 1, ramload default); canary lights no other cage.
- Board is left on the RAM plain kernel after B; next reboot returns it to flash OpenWrt (daemon policy `pass` is restored by each dev.py flow).
- `--update-baseline` is never automatic. Edit the baseline table below and commit both files.

## Checks

| Id | Protects | Pass criterion | Typical s | Stall/total s |
|---|---|---|---|---|
| boot_link | #137 SerDes sync, #138 silent console, #116 cage up | 3 rounds `missing none`; 0 of the 4 strings* | 180 | 60/540 |
| hang_test | #138 SoC watchdog resets a hang | reset within 165 s, normal boot after | 100-230 | 170/400 |
| switch | flash image reachable and sane | `switch_check.py` rc 0 | 5 | 45/45 |
| plain_boot | plain 7.4 kernel boots at the final profile (core 608, CPU 1325) | ramload rc 0 | ~120 (est.) | 60/240 |
| pre | bench initramfs tools and nodes | no `MISSING`, not OpenWrt | 2 | 20/30 |
| prep | perf push + NAT setup for zc | both PASS | ~30 (est.) | 40/200 |
| selftest | #108 memory, CPU, clocks, ASIC, SFP, flash | `st1008f-selftest` PASS | 25 | 45/100 |
| vlanproto | patch 644 hook | extack `can't be changed on a bridge with switch ports` | 2 | 20/30 |
| gdma | #62 GDMA dmaengine | 8 rows `bad 0 fails 0`; 4096 B <= ceiling | 5 | 25/60 |
| dss | die-speed sensors out of reset (HIDDEN-FEATURES) | 10 combos, `polls=1` | 5 | 40/40 |
| zc | #149 GRO panic trigger, fast-path rate | median of 2 perf runs within +-10 % | 90 | 45/330 |
| bootlog | #46 boot log allowlist | `boot_log_check --boot -1` rc 0 | 2 | 20/40 |
| consolescan | #149 and any oops | 0 of `Oops`, `BUG`, `Kernel panic`, `gro_list_prepare` in the phase B console delta | 0 | 5/10 |

- *Strings: `could not sync clock`, `clock not ready, retry`, `board silent`, `board alive, console silent`. Counted in the command output, the console-log delta and the `uboot_chain_env.log` delta.
- Total typical ~12 min (A ~5-7 min, B ~5 min). Sum of caps 2065 s; backstop 1800 s.
- Estimates marked est. are unmeasured; `secs` in `canary.csv` replaces them after the first run.
- gdma needs `kmod/gdma_bench/gdma_bench.ko` matching the bench kernel vermagic; missing = NOTRUN, vermagic mismatch = FAIL (rebuild per PLAIN-KERNEL-TESTS.md).

## Baseline

- Machine-readable: `scripts/canary_baseline.json` (committed). Recorded 2026-11-07 (written by hand: selftest `sfp` FAILs, so no all-PASS run for `--update-baseline`).

| Value | Baseline | Rule | Source |
|---|---|---|---|
| zc 1400 B, final profile, under perf | 165.9 kpps | +-10 % PASS, below FAIL, above WARN | canary run 2026-11-07T23:36 (runs 167.8, 163.9) |
| gdma 4096 B | 92.7 us | ceiling 115.9 us (x1.25), over = FAIL | canary 2026-11-07T23:35 |
| hang reset | 93 s | WARN above 130 s | canary hang_test 2026-11-07T23:32 (also 93 s at 2026-11-07T17:54) |
| dss polls | 1 | any other FAIL | 10 rows polls=1 |
| boot-link rounds | 3 | all must pass | 3/3, bounces 0 |

- Conditions: flash 6.18.60 slot b on the safe chain profile (cpu=1350,ddr=662,sram=500, no swcore: flash console garbles at LX 304, #159); plain v7.4-rc1 + series, final profile above, cage 1, route mode.
- Plain zc without perf: 168.7-170.3 kpps (5 boots below).
- Rebaseline only on a deliberate, understood change (new kernel, driver change); record the reason in the commit.

## Verdicts 2026-11-07 (sw2, final profile)

| Check | Verdict | Value |
|---|---|---|
| boot_link | PASS | 3/3, bounces 0, 193 s |
| hang_test | PASS | reset 93 s after /bin/sh (run 1 of 1, #157 did not show) |
| switch | PASS | 24 s |
| plain_boot | PASS | 31-43 s |
| pre | PASS | BogoMIPS 872 |
| prep | PASS | perf, natsetup |
| selftest | FAIL | `sfp` only: `timeout after 2 s` (7 modules, PASS at core 408). Also at 2026-11-07T17:56 (core 608). Other items PASS |
| vlanproto | PASS | |
| gdma | PASS | 92720 ns |
| dss | PASS | 10 rows polls=1 |
| zc | WARN vs the old 143.3 baseline | 165.9 kpps (+15.7 %); new baseline above |
| bootlog | PASS | CLEAN (allowlist from 2db6655) |
| consolescan | PASS | 0 hits |

- First full run 2026-11-07T23:26 failed B (7 FAIL): plain kernel has no dropbear, canary did not start it. Fixed in `canary.py` (`ensure_ssh`).
- Open: selftest `sfp` 2 s timeout at core 608 (fails the canary until the bound or the cause is fixed).

## Five plain boots at the final profile (2026-11-08T00:05-00:18+11:00)

- `scripts/plain_final_boots.py`: ramload (final profile), NAT-mode iperf3 TCP P4 120 s, zc+nat 1400 B 10 s, integrity (1400/500/64 B). Pass: no oops, integrity PASS, ssh alive; temperature logged only (owner 2026-11-07). Rows `tmp/logs/plain_final_boots.jsonl`.

| Boot | Result | zc+nat kpps | TCP P4 NAT (stack) Mbit/s | Temp C |
|---|---|---|---|---|
| 1 | PASS | 170.0 | 241.9 | 51.9 |
| 2 | PASS | 168.7 | 241.1 | 51.9 |
| 3 | FAIL (ramload rc 1) | - | - | - |
| 4 | PASS | 170.1 | 242.8 | 51.9 |
| 5 | PASS | 169.9 | 242.9 | 51.9 |

- Boot 3: kernel booted to the shell, no oops; the ramload console step after `bootm` returned rc 1 and the load did not run. Same on 1 of 5 boots in an earlier set (2 of 15 ramloads in all). Cause not found; the console at LX 304 is garbled (#159).
- No hang, no oops, no relay power-cycle in any boot.

## After a new image or kernel/OpenWrt bump

- Flash image changed (build, sysupgrade, new chain U-Boot): `./dev.py canary --only a`.
- Plain kernel or series changed (rebase, bump, new patch): rebuild the bench `.ko` and initramfs, then `./dev.py canary --only b`.
- Before declaring a bump done: full `./dev.py canary`; on a FAIL, bisect with `--only <id>`.
- A new expected value after a deliberate change: full run all PASS, then `--update-baseline`.

## FAIL: first step

| Check | First step |
|---|---|
| boot_link | read `tmp/logs/boot_link_check.log`; which string/cage; grep the console-log delta around `Run /sbin/init` |
| hang_test | `/sys/class/watchdog/` on the board; `watchdog.open_timeout` in cmdline; compare with the #138 patch (kernel stops feeding) |
| switch | `./dev.py switch-check --ip 192.168.25.56 --wait 60`; if unreachable, console log |
| plain_boot | `tmp/logs/st1008_ramload.log`; kernel file name and TFTP size |
| pre | `MISSING x` in the verdict: bench initramfs lacks the tool or debugfs node |
| prep | `tmp/logs/plain_campaign.log` for perf/natsetup; host netns `natlan`/`natwan` |
| selftest | `./dev.py selftest --ip 192.168.25.56`; the failing section |
| vlanproto | patch 644 applied? `silent accept` = hook missing, other error = text in verdict |
| gdma | `.ko` vermagic vs kernel; `bad+fails` > 0 = driver bug; slow = clock set wrong (BogoMIPS 897 at picks) |
| dss | sensors in reset: `polls=4096`; check clocks/boot order (HIDDEN-FEATURES) |
| zc | clocks really picks? (BogoMIPS); low rate = regression, check queue/GRO; panic = #149 trace in console log |
| bootlog | `./dev.py check-log`; new warning needs review + issue |
| consolescan | the matching lines in `private/serial/st1008-console.log` after the phase B start |

## Not covered

- Optics, DDM, cage links beyond lan1: #135 `cabling_map.py`, #127.
- Cage loop protection (`st1008f-linkcheck`, STP) beyond boot-link's lan1 check: #110.
- Stock-clock plain run, ceilings (`ceiling_rxtx`, #148), NAT bench rates, mem-stress, DSS soak, SPI/flash speed (#50).
- sysupgrade, A/B slot logic and trial boots (#117), sw1.
- Flaky-trigger odds: #149 reproduced 2 of 5 boots on OpenWrt 7.3; two perf runs on one boot is a smoke test, not a statistical one.
