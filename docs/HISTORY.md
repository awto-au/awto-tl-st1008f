# History — how the 10G-in-U-Boot result was reached

Lab notebook. Times are AEDT (+11:00). Sources: the local serial logs (`private/serial/`), dated notes from
earlier versions of the reference docs, and the original tracking issue. Reference facts live in
[hardware.md](hardware.md), [UBOOT-REFERENCE.md](UBOOT-REFERENCE.md), [FIRMWARE-ANALYSIS.md](FIRMWARE-ANALYSIS.md).

## Starting point

- Goal: preserve the stock flash, RAM-boot Linux, reverse the stock boot and switch init.
- Upstream OpenWrt supports TL-ST1008F **v2** only; its documented install is YMODEM (`loady 0x82000000`, `bootm`) and states stock U-Boot networking is broken.

## 2026-10-07

- ~15:00–15:35 — Related managed firmware (14 SX3008F / ST5008 / ST5008F releases + SX v1 GPL) acquired and decoded with the GPL DES routine. Ghidra on ST5008 CLI and SX v2 SDK functions. Outcome: shared Realtek SDK lineage; no evidence of a hidden GUI on the ST1008F.
- ~15:40–16:22 — LAN discovery and a read-only port retest of known hosts. Outcome: other TP-Link devices found; none is the ST1008F (unmanaged, no IP).
- 16:37 — New CH341 adapter, receive-only, 30 s at 115200: 0 bytes (switch already booted, silent).
- 16:48 — Receive-only capture during a power cycle: 4,776 bytes of readable U-Boot + Linux at 115200. RTL9303, 512 MB, 32 MB Winbond flash, `RTL9303_8XGE`, `Hit Esc key to stop autoboot`.
- 16:54 — One Esc at the prompt → `RTL9300#`. Read-only: `help`, `version`, `help sf`, `flinfo`, `flshow`, `printsys`, `printenv`, `md.b b4300000 80` (RUNTIME1 uImage header).
- ~16:56 — `rtk network on` → `Err:0xf030:FAIL`. Host 10G link up; no U-Boot transfer path.
- 16:59 — Full-flash serial backup started (`scripts/node/serial_flash_backup.mjs`: target CRC32, two `md.b` reads, compare). Target whole-chip CRC32 = `dd984f95`.
- ~17:05 — Backup stopped at user request at 671,744 bytes. SFP moved to the first cage: `network on` still `0xf030` but registers `ethact=rtl9300#0`. The ping used U-Boot's default `192.168.0.x` env (wrong subnet; invalid test). Reset test: `Net Initialization Skipped`, `No ethernet found` until `network on`.
- 17:06–17:20 — LOADER-only two-read acquisition (~7 min per read): both 917,504-byte reads match, CRC32 `e579e61c`.
- 17:22–17:42 — Ghidra: stock and ST5008F loaders mapped (main text `0x5080` → `0x83f00000`). `0xf030` traced to the per-port wrapper; live RAM read shows port 28 has a null PHY pointer. Same-subnet ping: U-Boot NIC TX counter 2 → 4, 0 failures, host capture 0 frames from the switch. TX ring descriptors not stuck. `rtk init` + `network on`: same. `help rtk` captured.
- 17:48 — Hardware revision v2 confirmed. OpenWrt 25.12.4 v2 initramfs downloaded (5,383,940 bytes, SHA256 `e1d56194…74fc5`, matches published sums).
- ~18:09 — First YMODEM attempt (`scripts/node/ymodem-send.mjs`).
- ~18:20–18:24 — Baud check: 38400 capture = 234 bytes of garbage during U-Boot; 115200 after boot = silence; CR at each rate: no response.

## 2026-10-08 morning: YMODEM and the console

- ~10:11 — Prompt-aware watcher (`boot-interrupt.mjs`) caught autoboot, sent Esc, got `RTL9300#`.
- ~10:27 — `loady 0x82000000` + `sb`: repeated `NAK on sector` on the first block; no block acknowledged. CH341 write errors `-32` in the kernel log; target state unknown afterwards. `bootm` not sent. YMODEM abandoned.
- ~11:27–11:33 — Prolific (PL2303) adapter: receive-only showed stock Linux boot; then TX enabled. `rtk boardid` → `<NULL>`, `rtk boardmodel` → `RTL9303_8XGE`, `rtk show hw_profile_list`, `help rtk`.
- ~11:38 — Reboot after removing the cage-2 1G module: `10G fiber insert` lines 4 → 2, `port 1 media 5` gone → stock Linux media messages use module indices, not SDK ports.
- ~11:41 — Watcher re-armed to send `rtk 10g 0 fiber10g` after the prompt.
- 11:45 — Clean stock boot captured ([../artifacts/stock-boot-20261008.log](../artifacts/stock-boot-20261008.log)).
- 12:04 — `tio` dropped the PL2303 when stdin was not a terminal; replaced by the pyserial daemon (`scripts/switch_console_daemon.py`) with auto-catch.

## 2026-10-08 midday: the SerDes / forwarding theories (all wrong)

- 12:30 — Baud probe for a faster serial dump: 1,500,000, 921,600, 500,000 each reverted to 115200 within seconds.
- 12:41 — Serial `md.b` dump of RUNTIME started at 115200 (later stopped at ~952 KiB).
- 12:42–12:49 — `rtk pinGet 0` → `pin0: 0` (cage 1 present), then the console stopped answering; power cycle. Repeated: same. Later found: GPIO/I2C `rtk` commands hang only before SDK init.
- 12:51–12:53 — `printenv`, `help`, `help sf`, `sf probe 0` (clean).
- 12:54 — `rtk i2c init sw 0 0 8 0 0 8 0x50 1 0 0` + reads: returned `0x0`. (These pins are GPIO8/GPIO0 = MOD-DEF0, not SFP I2C.)
- 12:58–13:00 — `rtk network on`, `rtk 10g 0 fiber10g`, the D-Link `enp0` SerDes pokes on sds2 and the `entftp` datapath pokes (`mw 0xBB00ca00 0x0fcb5500`, `mw 0xBB00ca1c 0x217`). All accepted. `MAC_LINK_STS` `0x10000001` (force bits). `ping` → host not alive; host capture 0 frames.
- 13:01–13:02 — sds2 page 5 reg 0 `0x100D` vs dark sds3 `0x000C`: RX light present on cage 1.
- 13:04 — DOM/EEPROM reads via bit-bang groups on GPIO8: all `0x0`.
- 13:07 — `rtk port-isolation off`: ping still fails.
- 13:11 — MIB: port 0 TX ucast/mcast/bcast stay 0 across a ping. Conclusion at the time: frames dropped inside the switch.
- 13:15–13:19 — sds2 page 1 reg 30 = `0x0000`/`0x0100` (not `0x1ff`) → "no block-lock, L1 down". L2 registers read: `MAC_L2_PORT_CTRL(0)` = `0x33`, flood masks include port 0 + CPU → forwarding already configured.
- Source work in parallel: `0xf030` = benign null-PHY return; `dal_longan_sds_init` incl. one-shot rxCali runs in the bootloader; waMon (adaptive re-cali) does not; 10GR construct tables extracted; chip-rev register found. Hypothesis: one-shot rxCali fails to converge.
- Hidden-command hunt: loader tokens `port_cali_enable/disable`, `link_chg_enable/disable`, `wa_enable` are RTL8295R external-PHY diag code (`phy_rtl8295.c`), not reachable for 8XGE; `comboport` is for combo copper/fiber ports (none on 8XGE); `wa_enable` is not waMon. No standalone `rtk` command calibrates or enables the SFP SerDes.
- rxIdle-gate theory: rxCali is skipped if the RX sees idle for 10 ms at init → proposed forcing the far end to 10G fixed. Dropped when the gate register read `0x15BC` (passes).
- Function map built to call `dal_longan_sds_rxCali` via a `go <addr>` stub ([UBOOT-FUNCMAP.md](UBOOT-FUNCMAP.md)); stub dropped once lasers were found off.
- 13:26 — Second `rtk network on` in the same boot: returned `0xf030`, then the console went dead; power cycle.
- 13:29 — Fresh boot, `network on`: page 1 reg 30 still `0x0100`.
- 13:32 — NicGiga-style bare `setenv ipaddr/serverip; tftpboot` (no `network on`): board reset.
- 13:35 — `network on` + `tftpboot` (olliver's recipe): `Loading: *T T` timeouts; host capture 0 frames, no ARP.
- 13:39–13:41 — `help rtk` re-read. `rtk i2c init sw 5 0 22 0 23 8 0x38 1 0 0` (PCA9534 bus) **before** `network on`: console hung; power cycle.

## 2026-10-08 afternoon: lasers off

- Hypothesis (user): the SFP TX lasers are off. DTS: tx-disable = PCA9534 @ `0x38`, active-high; power-on = all inputs → lasers off; nothing in U-Boot drives it.
- 13:41 — Fresh boot. 13:47: `rtk sdsreg` before SDK init → `Failed!! 0xf010`. 13:49: `rtk network on` (first of this boot). 13:50: rxIdle gate register `0x15BC` (bit 0 clear, gate passes) — rxCali theory weakened.
- 13:51 — GPIO block snapshot `md.l 0xb8003300`: `PABCD_DIR` `0x00e00000`, `PABCD_DAT` `0x00ec00c4`.
- 13:51–13:58 — PCA9534 driven by raw GPIO bit-bang (`scripts/st1008_pca9534.py`, ~40 s per write sequence): read `0xff/0xff/0x00/0xff` (all inputs), wrote reg1 = `0x00`, reg3 = `0x00` → all 8 lasers on. The LAN switch showed the ports active.
- 13:59 — `setenv ipaddr/serverip/bootfile`; second `rtk network on` of this boot (returned normally). page 1 reg 30 still `0x0000`/`0x0100`.
- 14:00 — MIB counters in the millions on ports 0 **and** 8, mirrored: cages 1 and 2 both cabled to the same LAN switch → broadcast storm (TX mcast ~39M in ~1 min). `rtk port disable 8`; PCA9534 reg1 → `0xfe` (cage 1 only).
- 14:02 — `tftpboot 0x84f00000 st1008f.bin` → 5,383,940 bytes; `iminfo`: OpenWrt Linux-6.12.87, checksum OK. **10G in stock U-Boot works.** Block-lock register never showed `0x1ff` → not a valid indicator here.
- 14:06–14:07 — Cage 2 only (`port disable 0`, `port enable 8`, reg1 `0xfd`): `tftpboot` OK on cage 2 too.
- 14:08 — After SDK init, `rtk pinGet 0` and `rtk i2c init sw 5 0 22 0 23 8 0x38 …` + `rtk i2c read/write 5 …` work. The earlier hangs were all before SDK init. `setenv` 16-arg limit → laser macro split into `laser1/2/3`.
- 14:12 — `rtk i2c read 8 1/3` return the values written by bit-bang: `network on` already registers the PCA9534 as **device 8** (devices 0-7 = SFP EEPROMs, byte 0 = `0x03`). `read 9 1` → `FAIL (61455)`.
- 14:17 — Native laser macro: `laser1 = rtk i2c write 8 1 0xfd`, `laser2 = rtk i2c write 8 3 0`. Bit-bang retired.
- 14:13–14:16 — Ghidra: `SFP insert init` (`FUN_83f212b8`) only sets GPIO0-7 as inputs; `tx dis set` strings unreferenced (`scripts/mips_find_string_refs.py`). No TP-Link laser command exists.
- 14:23 — Serial full-flash `md.b` dump started; stopped (~496 KiB). 14:29: `rtk macsds set 2 10gr` → `mode 2`, block-lock register unchanged. 14:32: `printsys`, `flshow`, BDINFO dumped over serial (64 KiB at 2.0 KB/s).
- 14:53 — Same boot: `tftpboot` (one `T` retry) → `iminfo` OK. Cage-1 fiber unplugged first (OpenWrt lights every laser and bridges every port).
- 14:54 — `bootm 0x84f00000` → OpenWrt 25.12.4 to a root shell. SoC `RTL9303 rev B`. OpenWrt runs `rtpcs_930x_sds_do_rx_calibration` on SDS 2/3; `lan2` (cage 2) `Link is Up - 10Gbps/Full`. `/proc/mtd` captured. Static address added on `switch.1` (RAM only).
- 14:59:13–14:59:53 — `scripts/st1008_mtd_backup.py`: all six MTDs over SSH, device and host SHA-256 match, 32 MiB `full-flash.bin` in 40 s. Full-image CRC32 = `dd984f95` = the U-Boot `crc32` from 2026-10-07 16:59.
- 15:01 — `scripts/st1008_stock_extract.py`: `RTK_SDK` kernel (Linux 3.18.24), gzip initramfs, second kernel copy at `0x800000`, RUNTIME2 blank. `/dev` entries are regular files; `rc` runs `diag` in the foreground → silent console explained.
- 15:03 — `setenv bootargs console=ttyS0,115200 rdinit=/bin/sh; boota` → `rc` skipped (bootargs honoured), kernel panic `Attempted to kill init! exitcode=0x00000000`.
- 15:05 — `rdinit=/bin/sh -c "mknod /dev/s c 4 64; exec /bin/sh </dev/s >/dev/s 2>&1"` → same panic, exit 0. Power cycle after each (no `panic=`, no watchdog reset).

## Wrong turns and what resolved them

| Belief | Why it looked right | Resolved by |
|---|---|---|
| Stock U-Boot networking is broken (upstream note) | `0xf030`, `No ethernet found`, timeouts | Lasers were off; `0xf030` is a benign null-PHY return |
| L2 forwarding / CPU-port path missing | MIB TX 0, 0 frames on host | L2 registers already set; frames flowed once lasers were on |
| SerDes not block-locked (page 1 reg 30 ≠ `0x1ff`) | SDK's own link check | Register never reads `0x1ff` on this unit even with traffic |
| rxCali never runs / fails in U-Boot | waMon is bootloader-gated | `sds_init` runs rxCali once; gate passes; not the fault |
| GPIO/I2C `rtk` commands always hang | reproducible hangs | Hangs only before SDK init |
| Need bit-bang to reach the PCA9534 | `rtk i2c` hung on that bus | PCA9534 is pre-registered as `rtk i2c` device 8 |
| YMODEM RAM-boot | upstream procedure | `NAK on sector` on this adapter; TFTP replaced it |

## 2026-10-10: mainline U-Boot, storm proof, overclock

One line per result; detail in the linked docs/issues. Owner decisions: [DECISIONS.md](DECISIONS.md).

- US-48 (gen 1) NAT question (side task): firmware v7.5.15 unpacked (`scripts/ubnt_fw_unpack.py`, extract in `private/unifi-us48/`): BCM53344 + BCM56150 (Hurricane2), 52 ports, kernel 3.6.5 has conntrack but no NAT targets → no NAT. UNVR ruled out as NAT box (one port). Issue draft dropped.
- Quick wins: SFP ID + DDM from stock `rtk i2c` (#11); USB host present but not wired (#5 closed); mode switch read live (#8).
- Storm proof: stock OpenWrt RAM boot bridged lan1/2/8 without STP → host bcast+mcast 5 → 13,354 pps in ~80 s, `eth0: Ring contention` and hang at 253 s; STP from first boot blocks it (US-48 sends no BPDUs). `storm_watch.py` trip lowered 50k → 2000 pps (#19).
- PL2303 RX stalls after a power cut (`urb stopped: -32`): daemon restart before power-on.
- Linux 7.3-rc6 groundwork agent: upstream already boots the SoC to a console; DSA/NIC/PCS missing; real blocker = phylink PCS series `737-01..08`. First boot: GPIO21 wdt node reset the board → disabled; GPIO21 = reset line (#16, #18).
- Strict allowlist boot-log checker (#28, #29); power budget values shown borrowed (#30).
- Mainline U-Boot v2026.07 stage 0 boots via `./dev.py ramload uboot-mainline`; `dev.py` becomes the single entry point. Stages: GPIO, I2C master + laser expander, SFP decode (ethtool port), all 8 cages read; serials shown.
- Serial: every divisor to 10.94 MBd works on stock and ours; PL2303 clone runs fast; long lines drop chars (#31, #32).
- `rtk` parity: 62/62 stock forms match, hidden verbs documented, flash writers refused (#34). 512 MiB via `highmem`. Flash found to hold OpenWrt 25.12.4 (sysupgrade 2026-10-08); kept (#36).
- Clocks decoded (CPU 800, LX 175, SPI 25.52, DDR 600); clock provider derives all rates from PLLs. CPU overclock: 1000 MHz passes the full suite, 1066.7 hangs (#38).
- 15:12: OpenWrt RAM-booted from our U-Boot at 1 GHz without confirmed STP looped via cages 3↔7; the watcher's single relay request timed out → house LAN alerts for ~20 h (SG2008P `OSW_DET_LOOP`) until the relay was cut 2026-10-11 11:38 (#43, awto-terminal#56).

## 2026-10-11: chain boot, fastest settings, NAT, 7.3 network port

- Storm fixes: `kill()` downs lan* over serial then retries the relay; STP step silences kmsg, cuts power on failure. Flash OpenWrt proven loop-safe (STP saved) (#43 closed).
- Static addresses from the house registry: switch `.48`, host `.30`, relay `.49` (claimed).
- Chain boot option A live: our U-Boot in `jffs2-log`, stock `bootcmd` chainloads it, `clocks fast`, flash OpenWrt (#47 closed). Owner approval "a to write".
- VS Code: "ST1008 console" task + own "run task by name" extension (`tools/vscode-run-task/`).
- Flash speed: U-Boot to 122.5 MHz; Linux corrupts at 122.5 and JFFS2 fails at 102.1 → Linux SPI stays stock (#50).
- DRAM: writes stuck at 237 MB/s regardless of clocks = miss-latency bound; MCR `ip_ref`/`dp_ref` prefetch (off in stock) → write +68 %, read +49 % (#52). OpenWrt patch `300-04` (#53); DRAM theory-vs-measured review → [DRAM.md](DRAM.md).
- DDR 650 via `nosr` (self-refresh method hangs); fastest power-up set CPU 1000 / DDR 650 / tREFI 7.09 µs / prefetch → writes 433, reads 460 MB/s. `300-05` CPU frequency from PLL (#55). DRAM = Zentel A3T4GF40BBF-HP. DDR 675-725 tried, unstable → 650 stays (#48).
- U-Boot port finished in one pass: stage 4 `rtk network on` from SDK + stock RE (`0xca04` SMI MAC type fix), ports up without stock (#51 closed); Linux SFP mode table; #31/#33/#35/#41 closed; stock LED profile copied (#9).
- Mode switch measured one-hot (pin 17 not stuck; earlier reads wrong); vendor `rtk.ko` logic ported to Linux (`300-06`, #64); #8 closed.
- Hybrid-NAT chat filed (#63, full archive in a comment). Old `awto-st1008f` repo moved to the wastebasket; web refs carried to `sources/README.md`.
- Minimal 7.3 kernel (417 options) boots to an initramfs shell; hardware inventory (#62).
- Fast NAT (#65): OpenWrt 6.18 NAT + flowtable 243-248 Mbit/s TCP; IPv6 ASIC-routed 9.08 Gbit/s at 0 % CPU; 2.5G IPv4 NAT not reachable on the CPU; clock sensitivity = compute-bound. No hardware NAT (#58), none hidden (#68). Datasheet read in full (#69); firewall bypass on ASIC routing (#66).
- OpenWrt realtek drivers ported to 7.3; port-node lookup bug (`port@N` in the mode-switch node) fixed; 7.3 beats 6.18 on NAT. NIC path `300-12` (doorbell, reclaim, ring 128): TCP ~350 Mbit/s, UDP 1400 B ~750 Mbit/s (#60). HIGHMEM kept + `300-13`; 512 MiB in Linux (#27).

## 2026-10-12: parking, hidden hardware, default-boot plan

- Work parked in issues (#72); SMP default (untested boot); `300-14` parked; SPG `rtk spg` parked on `parked/spg-wip` (#70).
- Hidden-register probes: CHIP_MODE read-only, no free table has memory, no hidden NAT; eFuse left unread (#68, #75). SDK leftovers (#74), SDK feature map (#76), newer SDK 4.0.2 found (ours = 3.6.9) ([SDK-SOURCES.md](SDK-SOURCES.md)).
- #59 on-link + default-route offload (`300-17`), per-family `l3_default_v4/v6`, opt-in, untested on hardware.
- SerDes test tools `rtk sds` (PRBS31 0 errors, eye scan) ([SDS-TOOLS.md](SDS-TOOLS.md)); crypto engine 25/25 KATs, AES-128 ~29 MB/s ([CRYPTO.md](CRYPTO.md), #78); bus scan finds nothing undocumented ([BUS-SCAN.md](BUS-SCAN.md), #77 closed).
- LED snake + latched error/fallback/panic patterns (`300-16`); watchdog (`300-15`).
- Default-boot plan: OpenWrt on 7.3 + 6.18 recovery, 22 + 7 MiB, local OpenWrt build (#73). Standing flash-write approval except stock U-Boot area.
- Doc audit of the whole session: [DECISIONS.md](DECISIONS.md) created; gaps filled (hardware.md modules + network identity, NAT ceiling, SPG status, scripts README).
- Local OpenWrt builds: main + 6.18 + backports (step 1), OpenWrt userspace on our 7.3 (step 2); 7.3 flash image blocked by `mtdsplit` (#73, [OPENWRT-BUILD.md](OPENWRT-BUILD.md)).
- Board lost power twice mid-session (10:24, 10:27): the bench relay itself rebooted (uptime 64 s) and comes up OFF; first suspected HA "lights off". `switch_power.py check` now flags relay reboots ([hardware.md](hardware.md#bench-power-relay-84), #84).
- First SMP boots hung (mainline and OpenWrt-on-7.3): mainline dtsi routes every IRQ to IP2, VPE1 never ticks. Board DTS 2-cell intc fixes it; `300-18` single-CPU affinity lets eth0 run on CPU1; UP still fastest on throughput by a few % ([MAINLINE-PORT.md](MAINLINE-PORT.md) section 9, #73).

## NAT experiments

- Every NAT/NIC measurement, dead end and "which combination won" (2026-10-11 onward): [NAT-HISTORY.md](NAT-HISTORY.md).
- Today's state: [NAT.md](NAT.md). CPU-port sweeps: [CPU-PORT.md](CPU-PORT.md).


## Kernel baselines (7.3-rc6, linux-next)

Moved verbatim from docs/MAINLINE-PORT.md on 2026-11-07 (owner: one base, Linus's latest tag; linux-next and 7.3-rc6 retired).

### Baselines table rows

| Item | Value |
|---|---|
| Mainline target | linux-next `next-20261009` (Makefile `7.3-rc6` + `-next-20261009`; pinned `PIN` in `scripts/kernel_base.py`, `./dev.py kernel-base update` moves it), from 2026-10-12 ([DECISIONS](DECISIONS.md)) |
| Fallback | `v7.3-rc6` (`KERNEL_BASE=v7.3-rc6`; tree `tmp/linux-v7.3`, out dir `tmp/build-mips-v7.3-rc6`); board-tested base for sections 7 and 9. Its `openwrt/patches-v7.3-rc6/` copies of 300-10/300-17 predate the `0ad1348` pin: rebase them (`scripts/patch_rebase.py`) before using the fallback |

### Former section 8

### 8. Status of every OpenWrt realtek patch and file (7.3-rc6, linux-next)

Method: `scripts/openwrt_patch_status.py --tree <base>` (series order; reverse-apply = upstream) plus a source check of each `fails`; next column re-checked on `next-20261009` 2026-10-12 (`tmp/owrt_status_next.tsv`). Ported / applied = in our build (verbatim or forward-ported, section 7). Dropped = not built for this board. Refreshed = forward-port rebased for next; the 7.3 copy stays in `openwrt/patches-v7.3-rc6/`.

#### `patches-6.18`

| Patch | 7.3-rc6 | next | Evidence / reason |
|---|---|---|---|
| `021` gpio-regmap shadowed-output cache | dropped | dropped | No gpio-regmap user on this board (RTL8231 only) |
| `022`, `023-01/02` | upstream | in next | reverse-apply |
| `024-01/03` dt-bindings `enet-phy-pair-order` | dropped | dropped | RTL8224 binding docs; no RTL8224 |
| `024-02` RTL8224 pair order | upstream | in next | `realtek_main.c` has pair-order support (different context) |
| `024-04` | upstream | in next | reverse-apply |
| `025-01`, `026`, `027-01..04`, `027-06/07` i2c-rtl9300 | upstream | in next | `i2c-rtl9300.c` has the `bus_freq` enum, `F_BUSY`, `rd_reg`, `max_read_len` quirk, clk, RTL9607 config |
| `025-02`, `027-05`, `027-08` | upstream | in next | reverse-apply |
| `028`, `029` lm75, `030` RTL8226 MDI swap | upstream | in next | reverse-apply |
| `031-01..24` mdio-realtek-rtl9300 (v7.2) | upstream | in next | `-16`, `-18..20`, `-22`, `-23` reverse-apply; the rest present with later context. Driver not built (OTTO fork used) |
| `031-25..34` mdio-realtek-rtl9300 (v7.4) | dropped | dropped: in next | next: `-25..27`, `-30`, `-31`, `-34` reverse-apply; polling setup (`-28`), page tracking (`priv->page[]`, `-29`), RTL838x/839x (`-32/33`) present with later context. `MDIO_REALTEK_RTL9300` stays off (OTTO fork) |
| `032-06..08` irqchip select / shuffle / multi-parent | upstream | in next | `intc_select`, multi-parent setup, onecell xlate |
| `033-01` | upstream | in next | reverse-apply |
| `033-02` i2c-gpio shared SCL | upstream | in next | `i2c-gpio.c` has the shared-SCL code |
| `034-01`, `035`, `036`, `037` | upstream | in next | reverse-apply (`037`: later context) |
| `034-02` wdt clock enable | upstream | in next | `devm_clk_get_enabled` |
| `039-01/02` gpio raw IO / overridable bank IO (v7.4) | dropped | dropped: in next | reverse-apply on next |
| `040` SPI second CS (v7.4) | dropped | dropped: in next | reverse-apply on next; `init_hw()` now sets `SFCSR = CSB0\|CSB1` (section 4, #61) |
| `300-01..03` platform / board setup | ported | applied | verbatim |
| `301` RTL960x platform | dropped | dropped | other SoC |
| `308` mtune 4kec | dropped | dropped | RTL838x only; needs the generic mtune-24kc hack |
| `309` csum_partial maddu | ported | applied | verbatim |
| `318` clk-rtl83xx | dropped | dropped | OpenWrt sets `COMMON_CLK_REALTEK` off for 930x; fixed clocks |
| `330` thermal hook | ported | applied | verbatim |
| `331` otto_table hook | ported | applied | verbatim |
| `700` DSA max ports / u64 masks | ported | refreshed | forward-port, `300-09` |
| `705` sfp `i2c_block_size` init (v7.1) | upstream | in next | line present in `sfp_i2c_configure()` |
| `706-01` sfp I2C quirks (v7.2) | upstream | in next | `sfp.c` has the `max_read_len` handling |
| `706-02` | upstream | in next | reverse-apply |
| `712` MDIO SMBus library | ported | applied | verbatim |
| `714` SFP over SMBus | ported | applied | verbatim |
| `716` rtl838x eth hook | ported | refreshed | forward-port, `300-09` (+ `select PAGE_POOL`) |
| `717` RTL960x GMAC | dropped | dropped | other SoC |
| `718` DSA hook | ported | applied | verbatim |
| `720` multiport PHY (RTL8214/8218) | dropped | dropped | no copper PHYs on board |
| `721` tag rtl-otto hook | ported | refreshed | forward-port, `300-09`: tag 36 on 7.3, 37 on next (KS8995 took 36) |
| `722` trapped-frame metadata | ported | applied | verbatim |
| `723` aux MDIO | dropped | dropped | RTL8231 bus only |
| `730` PCS hook | ported | refreshed | forward-port, `300-09` |
| `743` RTL8224 SerDes config | dropped | dropped | no RTL8224 |
| `802-804` RTL8231 MFD / pinctrl / LEDs | dropped | dropped | no RTL8231 |
| `806`, `808` MDIO otto / SerDes hooks | ported | refreshed | forward-port, `300-09` |
| `809`, `810`, `813` Hasivo MCU | dropped | dropped | other boards |
| `816-01..03`, `817-819` PSE | dropped | dropped | no PoE (`816-03` is upstream) |
| `820` RTL960x MDIO, `821`, `822` PCIe | dropped | dropped | other SoC / no PCIe use |

#### Our patches (`openwrt/patches/`) on next

| Patch | next | Change for next |
|---|---|---|
| `300-04..07` | applied | none |
| `300-08` phylink fwnode PCS | refreshed | context only (`phylink.c` hunk applied at fuzz 2) |
| `300-09` Kconfig/Makefile hooks | refreshed | DSA tag value 37; MDIO Kconfig context |
| `300-10` API fixes | refreshed | `l3.c`: global `arp_tbl` removed (ARP table per netns) -> `arp_table(&init_net)` |
| `300-11..13`, `300-15` | applied | none |
| `300-16` port LEDs | refreshed | Kconfig context after `300-06` (fuzz 2 on both bases; one copy serves both) |
| `300-17` L3 on-link / default route | refreshed | its own `arp_tbl` uses -> `arp_table(&init_net)` |
| `300-18`, `300-19` | applied | none |
| `300-21`, `300-22` | new on next | written on next-20261009; W=1 clean (2026-10-13) |
| `300-23`, `300-24` | new on next | written on next-20261009 (2026-10-13) |
| `300-26` | new on next | written on next-20261009; W=1 clean (2026-10-13); not built on v7.3-rc6 (same copied rtl83xx files there) |

- None of ours is in next. Generic `pending-6.18/700`, `701` and `hack-6.18/910`, `911`, `940` apply to next as-is.
- Build: `./dev.py build-kernel --w1` on `next-20261009` (2026-10-12, GCC 16.2, SMP default config): 0 warnings, W=1 on the 12 objects our patches touch: 0 warnings; 618 `=y`; kernel raw 12,366,208 B, `mainline.bin` 4,891,140 B (16 MiB bootm limit).
- Boot (2026-10-12T14:07+11:00, sw2, `./dev.py ramload mainline-kernel`, merged main ec17cd4): initramfs shell up, `check-log` CLEAN (allowlist: `-next-YYYYMMDD` version, sw2 MAC via nvmem). NIC/NAT numbers vs 7.3 blocked by the bench path (#96).
- OpenWrt-on-next config: `./dev.py build-openwrt --kernel mainline --regen-config` -> `openwrt/kernel-7.3/config-7.3` (next symbols added, `QCOM_PAS`/`QCOM_SCM` gone). Image not built.

#### `files-6.18`

| File(s) | Status | Note |
|---|---|---|
| `arch/mips/include/asm/mach-rtl-otto/*` | ported | verbatim |
| `drivers/clk/realtek/*`, `include/dt-bindings/clock/rtl83xx-clk.h` | dropped | see `318` |
| `drivers/net/dsa/rtl83xx/*` (incl. `l3.c` v4+v6 routing offload, `l2`, `tc`, `pie`, `qos`, `lag`, `mirror`, `stp`, `vlan`, `debugfs`) | ported | verbatim + `300-10` |
| `drivers/net/ethernet/realtek/rtl838x_eth.[ch]` | ported | verbatim + `300-11` + `300-12` + `300-20` (+ shared `rtl930x_nic.h`) |
| `drivers/net/ethernet/realtek/rtl960x_gmac.[ch]` | dropped | other SoC |
| `drivers/net/mdio/mdio-realtek-otto.c`, `mdio-realtek-otto-serdes.c` | ported | verbatim |
| `drivers/net/mdio/mdio-realtek-otto-rtl960x.c` | dropped | other SoC |
| `drivers/net/pcs/pcs-rtl-otto.c` | ported | verbatim |
| `drivers/net/phy/realtek/realtek_multiport.c` | dropped | see `720` |
| `drivers/pci/controller/pcie-realtek.c`, `drivers/phy/realtek/phy-rtk-pcie.c` | dropped | no PCIe use |
| `drivers/soc/realtek/*`, `include/linux/soc/realtek/otto_table.h` | ported | verbatim |
| `drivers/thermal/realtek-thermal.c` | ported | verbatim |
| `net/dsa/tag_rtl_otto.c` | ported | verbatim |

#### OpenWrt `target/linux/generic` patches the realtek code depends on (scope for step 2)

| Generic patch | Needed by | Here |
|---|---|---|
| `pending-6.18/737-01..07` phylink fwnode PCS provider | `pcs-rtl-otto` (provider), `rtl83xx/dsa.c` (`fwnode_phylink_pcs_parse`, `fill_available_pcs`) | forward-ported (`300-08`); `737-02/04/05/06` fail verbatim on 7.3 |
| `pending-6.18/700`, `701` nft flowtable device events / offload `EOPNOTSUPP` | nft `flags offload` flowtables over DSA ports | apply on 7.3; not applied |
| `pending-6.18/720-*`, `721-*`, `742`, `743` Realtek RTL82xx PHYs | boards with RTL822x/826x PHYs | not needed (SFP only) |
| `hack-6.18` mtune 24kc | `308` | not needed |

The rest of `generic/` (backports, other vendors' PHY/DSA/Ethernet, MediaTek PPE, bridge BPDU knob `710`) is not referenced by the realtek files above.

### Retired decision (2026-10-12)

- **Kernel base: track linux-next** (pinned `next-YYYYMMDD` in `scripts/kernel_base.py`, `./dev.py kernel-base update`), not v7.3-rc6: newest Realtek MDIO/SPI/GPIO fixes (the 7.4 sets), 7.3 not released. v7.3-rc6 stays selectable (`KERNEL_BASE=v7.3-rc6`). [MAINLINE-PORT.md](MAINLINE-PORT.md#baselines), #16.
