# Owner decisions

Index of owner decisions, newest first. One line each: date (AEDT), decision, link. Superseded entries stay, marked **superseded by** the newer one. Facts and measurements live in the linked docs and issues.

## 2026-10-12

- **SFP power: no per-cage limits.** Every cage 2000 mW (SFF-8472 max; OpenWrt's borrowed 2.9/1.5/2.0 W split made modules fail in cages 2/3/6/7). Instead sum the power all fitted modules declare and warn if over the board budget. #30.
- **SFP power budget:** default 16 W = 24 W input (12 V 2 A) − est. 6-8 W board draw (unmeasured); copper modules counted from a datasheet table; warn only, never block. Configurable (U-Boot env `sfp_budget_mw`, Linux `power_budget_mw`). [hardware.md](hardware.md#sfp-power), #30.
- **README stays high-level:** no pins, register values or measurements; link to docs/. [README.md](../README.md).
- README headline: Linux 7.3 port + OpenWrt tracking + default boot, mode-switch table, improvements vs stock/OpenWrt, comparison with managed ST5008F. [README.md](../README.md).
- **Flash writes: standing approval** except the stock U-Boot area: never write `0x0`-`0xDFFFF` (`LOADER`/`u-boot`); `u-boot-env` only via `./dev.py uboot-chain-env apply|revert`; `jffs2-log`, `jffs2-cfg`, `firmware`, `recovery` writable without asking. Supersedes the 2026-10-11 "no flash writes except approved flows" entries. [CLAUDE.md](../CLAUDE.md), #73.
- **Mode switch at boot (new meaning):** M1 = switch mode (bridge + STP); M2 = isolated management (every port reaches only the CPU, no port-to-port forwarding); M3 = recovery image, isolated management. Supersedes 2026-10-11 #46 (M2 = DHCP/U-Boot over LAN, stop at prompt; M3 = TFTP netboot). #73, #46.
- **Management address:** DHCP client + always-present static fallback `192.168.0.1/24`; house LAN gives it `.48` by DHCP reservation. Supersedes the 2026-10-11 "static `.48` on the flash OpenWrt" entry. #73.
- **Flash layout as designed:** 22 MiB primary (OpenWrt on our 7.3) + 7 MiB recovery (OpenWrt 6.18, fixed config); stock U-Boot, `u-boot-env`, `jffs2-log` untouched; `jffs2-cfg` spare. [DEFAULT-BOOT.md](DEFAULT-BOOT.md), #73.
- M3 boots the recovery image; automatic fallback to recovery after 2 consecutive unconfirmed primary boots, sticky until power cycle; SSH root keeps a blank password (as today's flash OpenWrt). #73.
- No 24 h (or other long) soaks: removed from the default-boot rollout (short RAM run + 3 relay power cycles instead); #54 stays parked. [DEFAULT-BOOT-OPS.md](DEFAULT-BOOT-OPS.md).
- Markdown tables: ≤5 short columns; long detail goes in per-item blocks ([HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) layout). Markdown word wrap + preview CSS set in `.vscode/`.
- Default boot = OpenWrt userspace (uci, netifd, overlay, sysupgrade) on our 7.3 kernel, built locally; not a custom config system. Rollout: RAM test → check-log + storm guard → flash. #73, [OPENWRT-BUILD.md](OPENWRT-BUILD.md).
- Take all work in and test it: local OpenWrt build with our patches backported, keep the 7.3 port current with upstream, 7.3 as default boot, upstream contributions as drafts. #73.
- Upstream posting (OpenWrt, Linux, U-Boot): drafts only; posting needs the owner's explicit go (scrub + three checks). Drafts in `private/upstream-pr-*`. #53, #59, #73.
- `l3_default` split per family: `l3_default_v4` / `l3_default_v6`, both off by default; NAT box keeps v4 = 0 (ASIC cannot NAT), v6 may be on. `l3_onlink` opt-in. [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md), #59.
- Fix #59 in code (on-link host routes + default route), off by default because ASIC-routed traffic skips nftables (#66). #59.
- Storm guard is automatic: one singleton guard per `./dev.py` hardware command; not a per-task decision, never started by hand. [CLAUDE.md](../CLAUDE.md), `scripts/storm_watch.py`.
- eFuse stays unread (`EFUSE_ACCESS_EN` never written; permanent-damage risk). #75 closed.
- Hidden-register experiments: volatile switch registers may be written (logged, restored, power cycle recovers); never burn eFuse; never touch DDR controller, PLLs, flash, GPIO21, reset or watchdog from those probes. #68.
- Hidden-hardware catalogue is generic (all undocumented features), not framed around NAT; NAT = one answered row. [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md), #68.
- Generic SDK sweep (every Longan module/API vs who uses it) and newer-SDK hunt. [SDK-FEATURE-MAP.md](SDK-FEATURE-MAP.md), [SDK-SOURCES.md](SDK-SOURCES.md), #76.
- Realtek developer-portal registration: owner fills it in himself (needs a Realtek contact; not guaranteed). [SDK-SOURCES.md](SDK-SOURCES.md).
- Stock-firmware login request: dropped by the owner.
- LED snake + latched error / fallback / panic patterns in U-Boot and Linux (`300-16`). [RTK-COMMANDS.md](RTK-COMMANDS.md#port-leds), #9.
- Port SerDes test tools (PRBS, eye, loopback) and test the crypto engine. [SDS-TOOLS.md](SDS-TOOLS.md), [CRYPTO.md](CRYPTO.md), #74, #62.
- Full I2C + SPI bus scan for undocumented devices. [BUS-SCAN.md](BUS-SCAN.md), #77.
- Smart Packet Generator: port as `rtk spg` with the staged safe plan (read-only → dark cage → ≤1000 frames to host → benchmarks); never an unbounded stream toward the house LAN. #70.
- Park all work in issues for a later restart; index #72.
- SMP (both VPEs) is the default 7.3 build; `--up` for A/B. #16.
- Add an issue to review, trace and perf-test the Linux NAT path. #71.
- Stock U-Boot only chain-loads ours; every flow must work as if stock never ran (no dependency on stock `rtk network on`); `ramload` flows move to our U-Boot's network. [DEFAULT-BOOT.md](DEFAULT-BOOT.md#power-up-chain), #80, #81.
- Stock `bootdelay` stays 1 (`bootdelay=0` dropped: lockout risk for a 1 s saving). #81.
- Layered write gates for the stock U-Boot area (driver, DTS read-only, `flash_guard.py`; W25Q256 block-protect last). [DEFAULT-BOOT.md](DEFAULT-BOOT.md#stock-u-boot-area-protection-81), #81.
- Feature-rich U-Boot: CPU-port Ethernet, web failsafe, netconsole/wget/fastboot, unmanaged-switch mode; no SSH, no router in U-Boot. [UBOOT-MAINLINE.md](UBOOT-MAINLINE.md#feature-scope-80-owner-2026-10-12), #80.
- U-Boot drivers reuse Linux/OpenWrt code via shared OS-independent cores (`shared/`), U-Boot side = DM glue only. [UBOOT-MAINLINE.md](UBOOT-MAINLINE.md#driver-reuse-audit-83), #83.

## 2026-10-11

- HIGHMEM kept: use all 512 MiB and fix the MIPS DMA highmem cost (`300-13`) rather than turn HIGHMEM off. #27.
- Port all of OpenWrt's realtek target to our 7.3 kernel and optimise NAT there (step 1); full OpenWrt userspace on 7.3 = step 2. #16.
- Local OpenWrt buildroot lives in the repo `tmp/` on the host data disk, low priority (`nice 19`, `-j8`): keep host cores free. Keep the switch's CPU threads free too: everything the ASIC can do stays in the ASIC. [OPENWRT-BUILD.md](OPENWRT-BUILD.md).
- NIC profiling: ftrace `function_graph` + CP0 Count first; musl toolchain + static `perf` only if ftrace cannot attribute the per-packet cost; no OpenWrt buildroot perf. [NAT-OPS.md](NAT-OPS.md), #67.
- CPU-port 10G register test skipped until the CPU path nears 1 Gbit/s; no register-poke kernel module. #60, #65.
- Fast-NAT work: research + measure, IPv6-first strategy, PIE to keep non-NAT traffic off the CPU. [NAT.md](NAT.md), #65.
- Mode switch reverse-engineered from vendor `rtk.ko` and made permanent in U-Boot and Linux (`300-06`); our test is not the reference. #64.
- LEDs: copy stock's behaviour (LED profile + laser park) in our `rtk network on`. #9.
- Stage 4 (`rtk network on`) ported from the Realtek SDK + stock RE; OpenWrt is a cross-check only. #51.
- Finish the U-Boot port first (#51, #25, #33/#35/#41/#31, #8/#46) in one pass; then NIC/offload/flash work.
- Push `main` as-is: one historical commit keeps a host path (fixed at the tip); no history rewrite.
- Old `awto-st1008f` notes repo retired to the machine wastebasket; its web references moved to `sources/README.md`.
- Cages 3 ↔ 7 are not cabled. [CLAUDE.md](../CLAUDE.md).
- Bridge STP stays on, forward delay 2 s (owner questioned STP delay; loop risk outweighs 16 s). [CLAUDE.md](../CLAUDE.md), #43.
- Linux SPI stays at stock 25.5 MHz (102.1 MHz broke JFFS2 reads); `clocks fast` leaves SPI unchanged. [CLOCKS.md](CLOCKS.md), #50.
- DDR stays at 650 MHz: 675/700 pass CRC only after a read-tap shift and hang under bench writes; 725 hangs in the change; gain ≤ 2 %. A speed passes only if `bench` completes too. #48.
- DRAM part = Zentel A3T4GF40BBF-HP (owner photo). DRAM tooling to be reusable on other boards/parts. #57.
- Add a 24 h soak issue (#54) — **superseded by** 2026-10-12 "no long soaks".
- Skip the 10-minute soak; no long waits during work.
- Fastest settings as power-up default: CPU 1 GHz, DDR 650 (`nosr`), tREFI 4608 clk (7.09 µs), DRAM prefetch on. [CLOCKS-OPS.md](CLOCKS-OPS.md).
- Refresh: no readable DRAM temperature exists, so decide from data; do not re-raise DRAM temperature. Superseded in part by "fastest settings" (tREFI 7.09 µs). [DRAM.md](DRAM.md).
- Decide rather than ask when a condition cannot be measured.
- OpenWrt patch enabling the DRAM controller prefetch (owner: off is a mistake); add our fixes to the 7.3 kernel build. `300-04`, `300-05`, #53, #55.
- Own VS Code extension "run task by name" only; a "run any command" extension was not built (blocked as an RCE surface). `tools/vscode-run-task/`.
- Docs: facts and operations in separate files (`X.md` / `X-OPS.md`); doc names are board-specific (TL-ST1008F), not generic RTL9303.
- Chain-boot option A approved ("a to write"): our U-Boot → `jffs2-log`, stock `bootcmd` change. #47 — **superseded by** 2026-10-12 standing flash approval.
- No flash writes except approved flows (`uboot-chain-install`, `uboot-chain-env`) — **superseded by** 2026-10-12 standing flash approval.
- OpenWrt's own config writes (`uci commit`) need no special permission.
- Mode switch boot policy: M1 normal (ports isolated until OpenWrt), M2 easy mode (DHCP, U-Boot over LAN), M3 undecided → TFTP recovery — **superseded by** 2026-10-12 mode-switch decision. #46.
- Lock the board at 1 GHz; push CPU, RAM, flash and serial as fast as they go. #32, #38.
- Static IPs from the house registry (`awto-dan` `docs/network/ip-registry.toml`): switch `.48`, host `enp7s0` `.30`, relay `.49` (claimed; router reservation pending) — switch part **superseded by** 2026-10-12 management-address decision.

## 2026-10-10

- Keep OpenWrt 25.12.4 in flash (installed by `sysupgrade` 2026-10-08); do not restore stock. #36.
- No code copied from Ghidra decompiles; implementations come from GPL SDK / OpenWrt sources and register-level RE notes.
- Clocks are derived from the PLL registers (one clock provider), never hard-coded 800/175 MHz. [CLOCKS.md](CLOCKS.md#clock-provider-u-boot-implemented-hardware-checks-41).
- `phyreg` / `phymmd`: print a "no PHY on TL-ST1008F" note and close #34.
- Full `rtk` parity with stock including hidden verbs, each tested; flash-writing verbs refused. [RTK-COMMANDS.md](RTK-COMMANDS.md).
- Serial console ≥ 2 MBd target; push to the UART maximum. #32.
- Our U-Boot carries the board fixes (512 MiB, DRAM timings, overclock, flash speed). #32.
- Good mainline U-Boot port first, then the latest Linux. U-Boot path = mainline U-Boot (v2026.07) chainloaded from stock, built from a `uboot-port/` scaffold in this repo (UNVR pattern), not the clean-room `uboot/` and not a branch of the empty `awto-uboot` fork. [UBOOT-MAINLINE.md](UBOOT-MAINLINE.md), #23.
- Every hardware/build/test flow scripted behind `./dev.py`; no hand-typed console sequences. [CLAUDE.md](../CLAUDE.md).
- Strict allowlist boot-log checker for U-Boot and Linux boots. `scripts/boot_log_check.py`, #28.
- Per-cage SFP power values are borrowed and unverified; documented as such. **Superseded by** 2026-10-12 "SFP power: no per-cage limits". #30.
- IPs, MACs and SFP serials are fine in this public repo; post issues/comments here directly (no approval step). Host paths, secrets and `private/` still excluded.
- All uncommitted files in the repo belong to this work; sort them out (commit or remove).
- Quick wins (#11, #8, #5) before the benchmark.
- Cheap agent for the Linux 7.3 port groundwork. #16.
- The UNVR is not the NAT box (one port). US-48 NAT question answered (no NAT) and its issue draft dropped. [HISTORY.md](HISTORY.md).
