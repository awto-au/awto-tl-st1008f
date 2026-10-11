# Mainline Linux port (issue #16)

Goal: Linux 7.x mainline-based kernel driving the 8 SFP+ ports of the TL-ST1008F v2 (RTL9303). Desk analysis 2026-10-10; network driver port built 2026-10-11 ([section 7](#7-openwrt-realtek-network-drivers-on-73-delivered-2026-10-11)). Nothing here has run on the switch yet; bring-up: [MAINLINE-NET-OPS.md](MAINLINE-NET-OPS.md).

## Baselines

| Item | Value |
|---|---|
| Mainline target | `v7.3-rc6` (7.3 not yet released on 2026-10-10) |
| OpenWrt source | `main` @ `53ec2d0` (2026-10-09); newest kernel dir is `files-6.18` / `patches-6.18` (no 6.19 or 7.x dir exists) |
| Tooling | OpenWrt sparse clone and mainline clones under `tmp/` (gitignored); cross gcc `mips64-linux-gnu-` (GCC 16.2, `-mabi=32` multilib) builds MIPS32r2 BE |
| Scripts | `scripts/mainline_inventory.py` (inventory vs mainline), `scripts/mainline_patch_check.py` (apply OpenWrt patches onto 7.3 + build), `scripts/mainline_build_check.py` (stage-0 DTS + config build) |
| Logs | `tmp/logs/mainline_inventory.log`, `mainline_patch_table.log`, `mainline_patch_check.log`, `mainline_build_check.log` |

## Result in one paragraph

- Mainline 7.3-rc6 already has everything for a serial-console boot (platform, irqchip, timer, UART, SPI-NOR, GPIO, I2C master, watchdog, MDIO controller). It has no switch, CPU-port, SerDes/PCS, thermal or LED driver.
- The whole OpenWrt RTL930x driver set (DSA, CPU-port Ethernet, PCS, SerDes MDIO, otto_table, thermal, tagger, ~30k lines) compiles and links into a 7.3-rc6 `vmlinux` after: one identifier rename, one DSA tag number change, one Kconfig-hook rebase, and a hand-rebased generic phylink PCS series. Compile only; no run.
- The real blocker is not driver code drift but a non-mainline generic prerequisite: the phylink fwnode PCS provider series (12 patches, pending upstream, not in 7.3).
- 10G link-up behaviour (SerDes calibration) is the unverifiable-at-desk risk.
- 2026-10-11: delivered as `./dev.py build-kernel` (section 7): warning-free build, 573 `=y`, `mainline.bin` 4.59 MB.

## 1. Inventory: OpenWrt realtek target for RTL930x

Paths relative to `target/linux/realtek/files-6.18/` unless noted. Lines = `wc -l`. "Mainline" = state at `v7.3-rc6`; release = first release containing it.

| Subsystem | OpenWrt file(s) | Lines | Mainline 7.3-rc6 |
|---|---|---|---|
| MIPS board glue | `arch/mips/generic/board-realtek.c` (+ patches `300-01..03`, ~14 KB) | mainline 79 + OpenWrt adds ~300 | Base upstream (6.11). `300-*` adds SoC id/revision, DRAM size probe, HIGHMEM zone remap, `soc_info`, 32 KiB FDT fixup: not upstream |
| MIPS headers | `arch/mips/include/asm/mach-rtl-otto/{ioremap,kmalloc,mach-rtl-otto,spaces}.h` | 117 | Not upstream; `dsa.c` includes `mach-rtl-otto.h` |
| MIPS tuning | `308-tune-switch-4kec`, `309-mips-csum-partial-maddu` | 1 KB, 7 KB | Not upstream; optional |
| Platform DTS | `dts/rtl930x.dtsi` (OpenWrt) | 462 | `arch/mips/boot/dts/realtek/rtl930x.dtsi` (6.11) has CPU, intc, spi, timer, wdt, gpio, uart, i2c, mdio, reboot; no eth/PCS/serdes/table/thermal/LED/pinmux nodes |
| IRQ | `drivers/irqchip/irq-realtek-rtl.c` | 274 | Upstream (5.12). Select/shuffle/multi-parent patches `032-06..08` in 7.3-rc1; binding allows 1 or 2 interrupt cells |
| Timer | `timer-rtl-otto.c` | 303 | Upstream (6.11); `036` raw IO in 7.3-rc1 |
| UART | 8250 (`ns16550a`) | - | Upstream |
| SPI-NOR ctrl | `spi-realtek-rtl.c` | 207 | Upstream (5.12); `037` in 7.3-rc1; second-CS `040` is 7.4 (not needed, single CS0) |
| GPIO | `gpio-realtek-otto.c` | 470 | Upstream (5.13); `021` (gpio-regmap) 6.19; `039-01/02` raw IO / overridable bank IO are 7.4 (not needed for 930x) |
| Watchdog | `realtek_otto_wdt.c` | 367 | Upstream (5.17); `034`/`035` in 7.2/7.3 |
| I2C master | `i2c-rtl9300.c` | 670 | Upstream (6.13); `025..027` bus speeds, per-SoC fields in 7.0/7.1; `rtl9303` compatible in binding |
| I2C GPIO | `i2c-gpio.c` | - | Upstream; shared-SCL patch `033` in 7.3-rc1 (not needed: expander uses own SCL/SDA) |
| GPIO expander | `gpio-pca953x.c` (`nxp,pca9534`) | - | Upstream |
| SFP | `drivers/net/phy/sfp.c` | 3503 | Upstream; I2C block-size/SMBus patches `705` (7.1), `706-01/02` (7.2), MOD_DEF0-less presence (7.2) merged |
| MDIO (Ethernet) | `drivers/net/mdio/mdio-realtek-otto.c` | 1269 | Same hardware, mainline driver `mdio-realtek-rtl9300.c` (770 lines, 6.16). `031-01..24` (7.2, `-24` RTL931x landed 7.3-rc5); `031-25..34` (polling, page tracking, timeout, RTL838x/839x) are 7.4, not in 7.3. Both drivers bind `realtek,rtl9301-mdio` |
| MDIO SerDes | `mdio-realtek-otto-serdes.c` | 618 | Not upstream |
| MDIO aux / RTL8231 | `723`, `802-804` | - | Not upstream; not needed (no GPIO-expander MDIO, no RTL8231) |
| MDIO SMBus lib | `712`, `714` | 11 KB, 1.5 KB | Not upstream; only for copper SFP modules, not for SR optics |
| PCS/SerDes | `drivers/net/pcs/pcs-rtl-otto.c` | 4844 | Not upstream. Needs phylink fwnode PCS provider (`generic/pending-6.18/737-*`), also not upstream |
| CPU-port Ethernet | `drivers/net/ethernet/realtek/rtl838x_eth.c`, `.h` | 1998 + 364 | Not upstream |
| DSA switch | `drivers/net/dsa/rtl83xx/` (32 C/H files) | 20490 total | Not upstream. Core for 930x (`common`, `dsa`, `rtl930x`, `l2`, `vlan`, `stp`, `stats`, `rtl-otto.h`, `mac.h`) = 7759; the rest is l3/pie/tc/qos/lag/mirror/debugfs (11819 incl. other-SoC backends 1196) |
| DSA tagger | `net/dsa/tag_rtl_otto.c` + `721`, `722`, `700` | 47 | Not upstream; needs 3 DSA core edits (section 3) |
| Switch tables | `drivers/soc/realtek/otto_table.c`, `include/linux/soc/realtek/otto_table.h` | 686 + 308 | Not upstream |
| Thermal | `drivers/thermal/realtek-thermal.c` | 269 | Not upstream |
| LEDs | in DSA driver (`rtl930x.c`, `common.c` read node `realtek,rtl9300-leds`) | - | Not upstream; no binding |
| Clock | `drivers/clk/realtek/clk-rtl83xx.c` | 870 (+ SRAM asm) | Not upstream; not needed: `rtl930x.dtsi` uses `fixed-clock`, OpenWrt sets `COMMON_CLK_REALTEK` off for 930x |
| Pinmux | `pinctrl-single` nodes | - | Upstream driver; board DTS uses none |
| Out of scope | RTL960x GMAC/MDIO, PCIe + PCIe PHY, `realtek_multiport` PHY, PSE/Hasivo MCU, RTL8231 | ~2.7k in files | Not needed |

Totals: 34996 lines under `files-6.18`; about 30k relevant to RTL930x.

`patches-6.18` (113 files): version-tagged `v6.19..v7.3` entries are all present in 7.3-rc6 (verified by commit subject, log in `tmp/logs/mainline_inventory.log`). Tagged `v7.4` and not in 7.3: `031-25..34`, `039-01/02`, `040`. Untagged (OpenWrt-only): `300-*`, `308`, `309`, `318`, `330`, `331`, `700`, `712`, `714`, `716..723`, `730`, `743`, `8xx`.

## 2. Compile experiment (7.3-rc6 + OpenWrt realtek set)

`scripts/mainline_patch_check.py --build`, 2026-10-10. Patches applied in order on a scratch copy; result = strict (fuzz 0) / fuzz / fail. Build: stage-0 config + `RTL930X`, DSA, tagger, eth, PCS, MDIO otto + SerDes, otto_table, thermal.

| Patch / piece | Result on 7.3-rc6 | Note |
|---|---|---|
| `generic/pending 737-01..08` (phylink fwnode PCS) | `737-02` fuzz3 (hand-merge); rest apply | `struct phylink_config` gained WoL fields (`wol_phy_legacy`, `wol_phy_speed_ctrl`, `wol_mac_support`), moving the context of `pcs_interfaces` / `num_possible_pcs` / `fill_available_pcs` |
| `031-25..34` (MDIO 7.4 set) | apply; `031-29` (page tracking) fuzz3 | Applies to in-tree `mdio-realtek-rtl9300.c`, not to the OTTO fork |
| `039-01/02`, `040` | apply | 7.4 items; not needed for this board |
| `300-01` | fuzz | `MACH_REALTEK_RTL` select list differs |
| `300-02`, `300-03`, `309`, `330`, `331`, `718` | apply | |
| `700` (`DSA_MAX_PORTS` 12 to 56, `u32` to `u64` port masks) | fuzz3 | RTL930x has ports 0..28; u32 masks suffice with a limit of 32 |
| `721` (tag enum) | fuzz3 | Enum value 32 is taken by `DSA_TAG_PROTO_MXL862` in 7.3; use 36 (next free) |
| `722` (trapped flag in `dst_metadata.h`/`net/dsa/tag.c`) | fuzz | |
| `716` (eth Kconfig hook) | hunk 1 fails | `PARPORT` dependency gone from `NET_VENDOR_REALTEK`; trivial |
| `730` (PCS Kconfig hook) | fuzz3 | Placement checked, correct |
| `806`, `808` (MDIO Kconfig hooks) | fuzz3 misplaced | Landed inside the `MDIO_THUNDER` entry (duplicate-help Kconfig error); hand-replayed |
| `drivers/net/dsa/rtl83xx/*` | compiles | 1 error: `l3.c` parameter `at_least` collides with `#define at_least static` in `compiler_types.h`; rename (trivial) |
| `rtl838x_eth.c`, `pcs-rtl-otto.c`, `mdio-realtek-otto*.c`, `otto_table.c`, `realtek-thermal.c`, `tag_rtl_otto.c` | compile unchanged | No `dsa_switch_ops`, phylink MAC/PCS ops, page_pool or NAPI signature break at compile level |

- Link: the whole set, built in, links into a MIPS32r2 BE `vmlinux` (75 MB with debug info).
- Not covered by a compile: semantic changes (phylink resolve order, DSA bridge/FDB offload behaviour, switchdev notifier timing), runtime SerDes bring-up.

## 3. Gap list for 7.3 (boot to shell, 8 SFP+ ports usable)

Classes: UP = already upstream; TRIV = trivial rebase; API = needs API rework (named); LARGE = large / unverifiable at desk.

| # | Item | Class | Detail |
|---|---|---|---|
| 1 | Serial boot: platform, irqchip, timer, UART, SPI-NOR, GPIO, I2C, WDT | UP | 6.11..7.3; stage-0 DTS and config build ([section 4](#4-first-step-delivered-stage-0-dts-and-config)) |
| 2 | Board DTS | TRIV | `mainline/tplink-tl-st1008f-v2.dts`; needs a `tplink,tl-st1008f-v2` entry in `realtek-rtl.yaml` to pass `dtbs_check` (not run: no `dtschema`) |
| 3 | SFP core, I2C SMBus block quirks, MOD_DEF0/TX-disable GPIOs, PCA9534 | UP | `sfp.c` + 7.1/7.2 I2C patches merged |
| 4 | RAM above 256 MiB (board has 512 MiB in two banks) | TRIV | `300-02` HIGHMEM zone remap applies strict on 7.3; not upstream. DTS declares both banks (`0x0` + `0x20000000`, 256 MiB each): MemTotal 508264 kB, `./dev.py mem-stress` fill-verify of 432 MiB 0 errors (#27). `300-13`: lowmem fast paths for the HIGHMEM per-packet cost |
| 5 | Kernel image wrapper for stock U-Boot | unknown | OpenWrt uses uImage magic `0x93030000`; stock U-Boot has no FDT, so DTB must be appended (`MIPS_RAW_APPENDED_DTB`). Wrapper tool not written |
| 6 | MIPS `mach-rtl-otto` headers + `300-01..03` | TRIV | `300-01` fuzz on Kconfig |
| 7 | DSA core hooks: `DSA_TAG_PROTO_RTL_OTTO`, `DSA_MAX_PORTS`, trapped flag | API (small) | Tag number 32 to 36; `DSA_MAX_PORTS` 12 to 32; `722` touches `dst_metadata.h`. Out-of-tree only; `700`/`722` are the upstream-hostile part |
| 8 | Phylink fwnode PCS provider series (`737-01..08` of a 12-patch series, ~60 KB) | API | `phylink_config` WoL fields moved context; not merged in 7.3. DSA `dsa.c` uses `fill_available_pcs`/`num_possible_pcs`/`pcs_interfaces`; PCS driver uses `fwnode_pcs_provider`. Largest non-driver dependency; upstream status of the series not verified |
| 9 | CPU-port Ethernet `rtl838x_eth.c` | TRIV | Compiles unchanged; Kconfig hook `716` hunk 1 |
| 10 | DSA driver `rtl83xx/` | TRIV (compile) / LARGE (behaviour) | One rename. 20.5k lines; 7.8k for a minimal L2 core. Behaviour change 6.18 to 7.3 untested |
| 11 | Tagger `tag_rtl_otto.c` | TRIV | Compiles unchanged |
| 12 | PCS/SerDes `pcs-rtl-otto.c` | TRIV (compile) / LARGE (10G bring-up) | 4844 lines; list `a` construct tables (production chip, not `bT`) + `rtpcs_930x_sds_do_rx_calibration` (issue #16 stage 5) |
| 13 | SerDes MDIO `mdio-realtek-otto-serdes.c` | TRIV | Compiles unchanged |
| 14 | MDIO: OpenWrt OTTO fork vs mainline `mdio-realtek-rtl9300` + `031-25..34` | decision | Same compatible `realtek,rtl9301-mdio`. Mainline 7.3 lacks polling/page tracking (7.4). Not needed for PHY-less SFP ports; whether DSA/PCS call OTTO-specific symbols is unchecked |
| 15 | `otto_table.c` | TRIV | Compiles; hook `331` applies |
| 16 | Thermal `realtek-thermal.c` | TRIV | Compiles; hook `330` applies; SoC meter only |
| 17 | LEDs | not upstream | Programmed by DSA driver from a `realtek,rtl9300-leds` DT node (no binding) |
| 18 | Per-cage SFP thermal zones | unknown | Provider of `#thermal-sensor-cells` on `sff,sfp` not found in OpenWrt realtek/generic patches; stage 6 polish |
| 19 | DT bindings for switch children (eth, pcs, serdes-mdio, table, thermal, leds) | LARGE (upstreaming only) | `realtek,rtl9301-switch.yaml` has `additionalProperties: false` and allows only `ethernet-ports`, `reboot`, `i2c`, `mdio-controller`; out-of-tree use needs none |
| 20 | `clk-rtl83xx.c` | not needed | `fixed-clock` on 930x |
| 21 | RTL8231, PSE/Hasivo, PCIe, RTL960x, multiport PHY, MDIO aux/SMBus | not needed | |

Upstream-hostile items to carry out-of-tree: #7 (`700`, `722`), #8 until merged, #4/#6 `300-*`. DSA/eth/PCS/tagger are switchdev-shaped (see issue #16 comment) and are the upstreaming candidates.

## 4. First step delivered: stage-0 DTS and config

- `mainline/tplink-tl-st1008f-v2.dts`: includes mainline `rtl930x.dtsi`; compatible `tplink,tl-st1008f-v2`, `realtek,rtl9302-soc` (the board matcher in `board-realtek.c` keys on the latter).
  - Uses only upstream bindings: `uart0`, `spi0` + `jedec,spi-nor` + fixed partitions (same layout as OpenWrt), `i2c0` (`realtek,rtl9303-i2c`, `realtek,scl = <0>`, channels 0..7 = one SDA per cage), mode switch on gpio0 17..19 (`tplink,st1008f-mode-switch`, our patch 300-06, #64; was `gpio-keys`), `i2c-gpio` + `nxp,pca9534` @0x38 (SCL GPIO22, SDA GPIO23), 8x `sff,sfp` (MOD-DEF0 gpio0 0..7, TX-disable expander pins 0..7), `linux,wdt-gpio` on GPIO21, `realtek,rtl9303-switch` compatible.
  - Switch ports, CPU port, PCS/SerDes, table, thermal, LED set: section 7. Still omitted: 2nd RAM bank.
  - SFP I2C left at the controller default; SFF-8472 module EEPROM is a 100 kHz interface, so default is the rated max.
- `mainline/st1008f-v2.config`: complete board config on `allnoconfig` (no `32r2_defconfig`): MIPS32r2 BE UP, HIGHMEM, 8250 OF console + earlycon, GPIO otto + PCA953X, I2C rtl9300 + i2c-gpio, `MFD_SYSCON`, mode switch (300-06), watchdog, SPI + MTD SPI-NOR + OF parts, NET/INET/PACKET/UNIX, PHYLIB/SFP/MDIO rtl9300, initrd (xz), devtmpfs, debugfs, SysRq. `MODULES`, IPv6, wireless, VT, input off.
  - `scripts/mainline_build_check.py` fails and lists every fragment line that `olddefconfig` drops.
  - Size (2026-10-11, incl. initramfs): 939 `=y` / raw 15.28 MB / `mainline.bin` 5.46 MB on `32r2_defconfig` -> 417 `=y` / raw 6.74 MB / 2.60 MB.
  - `RTL930X` enabled with the network port (section 7); MT SMP (2 VPEs) is the opt-in `--smp` fragment.
- 300-06 Kconfig: mode switch `select PHYLINK` + `select SFP` (nothing else selects `PHYLINK` without a MAC driver).
- `mainline_uimage.py` refuses kernel+DTB over 16 MiB (our U-Boot `SYS_BOOTM_LEN`; stock's limit unrecorded).

### Stage-0 initramfs (#16)

- `scripts/mainline_initramfs.py` (called by the build): newc cpio, mtime 0, xz (CRC32, LZMA2) -> `tmp/initramfs/st1008f-initramfs.cpio.xz` + generated `CONFIG_INITRAMFS_SOURCE` fragment.
- Contents: static BusyBox 1.31.0 (musl, MIPS-I o32 BE; `sources/README.md`), `/init`, `/dev/console` (5,1).
- `/init`: `busybox --install -s`, mount proc/sysfs/devtmpfs/debugfs, print `st1008f-initramfs: up (Linux <ver>)`, `exec setsid cttyhack sh` with prompt `st1008f-linux # `.
- `./dev.py ramload mainline-kernel` waits for that prompt (cap 10 s after `bootm`) and fails on any kernel panic.

### SPI-NOR dirmap reads (#61, `openwrt/patches/300-07`)

- DTS: `&soc` gains range `0x14000000` (32 MiB flash window); `spi0` reg 2 = window, `reg-names = "regs", "dirmap"`. All flash partitions `read-only`.
- Driver: spi-mem `dirmap_create`/`dirmap_read`; window read mode = stock SFCR2 (`0xbbc14a00`, Dual I/O 0xBB, 4-byte address). Writes/erase stay PIO.
- `dirmap_create` takes 1-1-1 read ops with 4-byte addresses only, then compares 64 B PIO vs window at offset 0 and at half size; mismatch -> warning + PIO fallback.
- Cached window, `dma_cache_inv` per read (PIO program/erase cannot leave stale lines).
- `/sys/module/spi_realtek_rtl/parameters/dirmap`: 0 PIO, 1 uncached window, 2 cached (default); read per call.
- A/B: `./dev.py spi-dirmap-test` (dd time + md5 of `firmware` per mode).
- Build check (2026-10-10, `scripts/mainline_build_check.py`): `dtc` clean (0 warnings), `vmlinux` links (ELF32 MSB MIPS32r2, text 12.1 MB), DTB 6.7 KB. Not booted; `dtbs_check` not run.
- Stage-0 gate (issue #16): serial boot, `i2c-rtl9300` / `gpio-realtek-otto` / `realtek_otto_wdt` / SPI-NOR probe. Needs the image wrapper (#5) and a switch session.

## 5. Next steps (dependency order)

1. Boot the section-7 kernel per [MAINLINE-NET-OPS.md](MAINLINE-NET-OPS.md): probe order, `ip link`, one cage, ping, no loop.
2. 10GBASE-R link on one cage (PCS calibration, issue #16 stage 5); then NAT bench (`docs/NAT-OPS.md` flow, adapted to the initramfs tools).
3. Profile the CPU-port NIC path (#65): perf counters + function_graph are in the config; a `perf` binary is not (no pinned build, see section 7).
4. Try `--smp` (VPE1: RPS, second RX ring NAPI).
5. Step 2 (separate task): full OpenWrt userspace on 7.3 via a buildroot kernel bump; generic-patch dependencies listed in section 8.

## 6. Not determined

- Runtime behaviour of any out-of-tree driver on 7.3 (nothing was booted).
- Upstream state of the phylink fwnode PCS series and of a Realtek DSA submission on netdev (net-next/lore not searched).
- Whether the OTTO MDIO fork can be replaced by mainline `mdio-realtek-rtl9300` + `031-25..34`.
- Whether mainline `MACH_REALTEK_RTL` needs `MIPS_CPU_SCACHE` for RTL930x (OpenWrt selects it, mainline does not).
- Pinmux assumptions: board DTS sets none; SDA/SCL, SPI and GPIO muxing rely on U-Boot state.
- `dtbs_check` result; U-Boot image wrapper.

## 7. OpenWrt realtek network drivers on 7.3 (delivered 2026-10-11)

Built with `./dev.py build-kernel` (GCC 16.2); booted 2026-10-12 with IP traffic on lan1 at 10G (#16). OpenWrt source pinned at `53ec2d0` (`OWRT_COMMIT` in `scripts/mainline_build_check.py`, checked each run).

### What the build applies

| Step | Content |
|---|---|
| OpenWrt patches verbatim (`OWRT_VERBATIM`) | `300-01..03`, `309`, `330`, `331`, `712`, `714`, `718`, `722` |
| OpenWrt files verbatim (`OWRT_FILES`) | `mach-rtl-otto` headers, `drivers/net/dsa/rtl83xx/`, `rtl838x_eth.[ch]`, `mdio-realtek-otto.c`, `mdio-realtek-otto-serdes.c`, `pcs-rtl-otto.c`, `drivers/soc/realtek/`, `otto_table.h`, `realtek-thermal.c`, `tag_rtl_otto.c` |
| `openwrt/patches/300-04..07` | ours: DRAM prefetch, HPT freq, mode switch, SPI dirmap. 300-06: speed re-applied only when the ethtool readback differs from the one after our last set (was: every 0.57 s on GLC-T cages 3/7, phylink normalises the request) |
| `300-08` | generic `pending-6.18/737-01..07` phylink fwnode PCS provider, forward-ported |
| `300-09` | Kconfig/Makefile hooks: forward-ports of `700`, `716`, `721`, `730`, `806`, `808` |
| `300-10` | 7.3 API fixes on the copied files |
| `300-11` | rteth TX: 32-slot ring, BQL, xmit_more doorbell (owner input, #65) |
| `300-12` | rteth NIC path: RTL930x lockless doorbell, `napi_consume_skb` reclaim, overload fix (128-slot TX ring, reclaim in xmit, kick batch) (#60, #65) |
| `300-13` | MIPS HIGHMEM lowmem fast paths (#27) |
| `300-15` | `realtek_otto_wdt`: a watchdog armed by U-Boot stays on at probe (`WDOG_HW_RUNNING`), for the default boot ([DEFAULT-BOOT.md](DEFAULT-BOOT.md), #73) |
| `300-16` | port LED patterns: `panic_blink`, sysfs error latch, boot-pattern release (`CONFIG_TPLINK_ST1008F_LEDS`, #9; [RTK-COMMANDS.md](RTK-COMMANDS.md#port-leds)) |
| `300-17` | `l3.c`: on-link neighbour host entries (v4+v6) + default-route offload, opt-in module parameters `l3_onlink` / `l3_default_v4` / `l3_default_v6` ([ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md), #59) |

### 6.18 -> 7.3 drift fixes (one line each; details in the patch headers)

- `l3.c`: parameter `at_least` renamed `min_len`; 7.3 `compiler_types.h` defines `at_least` as a macro.
- `NET_RTL838X` selects `PAGE_POOL` (nothing else selects it on our `allnoconfig` base).
- `DSA_TAG_PROTO_RTL_OTTO` = 36 (32-35 taken in 7.3).
- `platform_data/dsa.h`, Ethernet, PCS, MDIO Kconfig/Makefile context moved: hooks re-placed (`700`, `716`, `730`, `806`, `808`); MDIO hooks no longer need the aux-MDIO (`723`) context.
- `phylink.h`: `phylink_config` gained `wol_*` fields; `737-02` fields re-placed.
- `I2C_SMBUS` is only user-visible with `I2C_HELPER_AUTO` off; `712` makes `SFP` select `MDIO_SMBUS`, which depends on it (fragment sets both).
- `705` dropped: already in 7.3 `sfp_i2c_configure()`; applied verbatim it lands in `sfp_hwmon_insert()`.

### Config and size

| Build | `=y` | kernel raw | `mainline.bin` (LZMA) |
|---|---|---|---|
| Before (main, 2026-10-11 22:52) | 417 | 6,739,744 B | 2,597,955 B |
| After, default (UP) | 573 | 11,502,624 B (initramfs xz 1,649,584 B inside) | 4,586,227 B |
| After, `--smp` | 600 | not wrapped | - |

- Bootm limit 16 MiB raw (`mainline_uimage.py`): 4.9 MiB headroom.
- Fragment additions: `RTL930X`, `IPV6`, `BRIDGE` (+ VLAN filtering), `VLAN_8021Q`, `ETHERNET`, `NET_RTL838X`, `NET_DSA` + `RTL83XX` + `TAG_RTL_OTTO`, `REALTEK_OTTO_TABLE`, `PCS_RTL_OTTO`, `FWNODE_PCS`, `MDIO_REALTEK_OTTO(+_SERDES)`, `PHYLINK`, `MDIO_SMBUS`, `MARVELL_PHY` (GLC-T copper SFPs), netfilter/nf_tables/NAT/masq/ct/flowtable (inet, v4, v6), `NET_SCHED` + ingress + flower + gact + mirred, `PERF_EVENTS` + `HW_PERF_EVENTS`, `FUNCTION_TRACER` + `FUNCTION_GRAPH_TRACER` + `DYNAMIC_FTRACE`, `THERMAL_OF` + `REALTEK_THERMAL`, `NVMEM` + `NVMEM_LAYOUT_U_BOOT_ENV` (MAC), `COMPAT_32BIT_TIME` (BusyBox 1.31 is pre-time64 musl: without it `ping` fails `clock_gettime(MONOTONIC)`), `HIGH_RES_TIMERS`, `NET_PKTGEN`, `NF_TABLES_NETDEV` (nat-bench pktgen / rxdrop).
- `MDIO_REALTEK_RTL9300` off: OpenWrt's `mdio-realtek-otto` binds the same `realtek,rtl9301-mdio`, and the DSA driver waits for its buses (`rtldsa_mdio_loaded()`).
- The DSA driver still builds all four SoC backends (838x/839x/930x/931x) and l3/pie/tc/qos/lag/mirror: they share files with the 930x code; trimming is a refactor, not done.
- `--smp` (`mainline/st1008f-v2-smp.config`): `SMP`, `MIPS_MT_SMP`, `NR_CPUS=2`, `RPS`, `XPS`. Builds warning-free; default stays UP.

### DTS (`mainline/tplink-tl-st1008f-v2.dts`)

- `&switch0` compatible `realtek,rtl9303-switch`, `realtek,rtl9301-switch` (DSA match), `realtek,otto-switch`, `syscon`, `simple-mfd`.
- Children from OpenWrt `rtl930x.dtsi`: `ethernet` (`realtek,rtl9301-eth`, IRQ 24, fixed-link 1G), `mdio-serdes`, `pcs` (SerDes 0-11), `table`, `thermal`; `led_set` node and a `cpu-thermal` zone at root.
- Ports: cage N = `lanN`. Switch port / SerDes: 0/2, 8/3, 16/4, 20/5, 24/6, 25/7, 26/8, 27/9; CPU port 28. `phy-mode = "1000base-x"`, `managed = "in-band-status"`, `sfp = <&sfp(N-1)>` (OpenWrt `SWITCH_PORT_SFP`).
- Mainline `mdio-controller@ca00` + 4 buses enabled with the OTTO compatible added; no PHYs on them.
- 1-cell interrupts: 7.3 `irq-realtek-rtl` uses `irq_domain_xlate_onecell` (OpenWrt DTS has 2 cells).
- Mode-switch children are `cage@N`, not `port@N`: rtl83xx `rtldsa_ports_probe()` walks every node named `port` in the tree (`for_each_node_by_name`). Named `port@0`, the mode switch's reg-0 child cleared `has_pcs` of switch port 0 (lan1), so lan1 was never added to the CPU port's isolation mask: no traffic to the CPU, `Port node N has neither pcs-handle nor phy-handle` x8 (#16).
- `ethernet` gets `nvmem-cells = <&macaddr_uboot 0>` from a `u-boot,env` nvmem layout on `u-boot-env`: eth0 = env `ethaddr` (`16:b0:46:e9:0d:c0`, same as the flash OpenWrt bridge). Stock `rtk network on` leaves the switch MAC registers at `00:e0:4c:00:00:00`.
- Not carried: OpenWrt `gpio-keys` (replaced by the mode switch, 300-06); `#thermal-sensor-cells` on SFP nodes + `sfp-thermal` zone (provider not in 7.3 or the ported set); GPIO21 watchdog stays disabled.

### CPU-port NIC (`300-11`, `300-12`)

- RX unchanged (NAPI, page_pool, 2 rings x 128).
- TX ring 128 slots (16 upstream, SDK 32): holds two RX polls of forwarded frames; with 32 the 1G CPU port drained one ring per poll and forwarding collapsed under overload (#60).
- BQL; doorbell at the end of an `xmit_more` batch, every 16 frames of a batch, on a full ring, or when the queue stops.
- Doorbell on RTL930x: one `writel_relaxed` of a cached `DMA_IF_CTRL` (fetch/busy bits clear), no read-poll, regmap lock or `ktime`. SDK `r9300_nicTxFetch_set` writes the field without a poll. Other families keep the RTL838x read-poll + RMW under `tx_lock`.
- No TX-done IRQ: reclaim runs at the start of each RX NAPI poll and inline in xmit when the ring is full (queue stops only if still full); `napi_consume_skb` (skb cache, direct page_pool recycle). xmit schedules NAPI when it stops a queue; the poll repolls while a stopped queue has frames owned by hardware.
- TX packet/byte counters per ring under the txq lock (`ndo_get_stats64`).
- CPU port MAC force register (`0xbb00ca8c`, power-up 0x217 = 1G): left as the driver sets it.

### Safety defaults (house LAN; loop of 2026-10-10)

- `/init` configures no network: every `lanN` and `eth0` stay down; no bridge exists.
- DSA setup (`rtldsa_93xx_setup`) isolates every port: port N forwards only to itself; `port_enable` adds the CPU port only. Port-to-port forwarding needs a Linux bridge.
- Lasers: Linux touches them only through the SFP state machine. `sfp` asserts TX-disable at probe (expander pin N-1 high = laser off) and releases it when `lanN` goes up. GLC-T copper modules (cages 3 and 7, cabled to each other) ignore TX-disable.
- `/usr/sbin/port-up <cage> [addr/len] [vid]` brings up one `lanN` (+ optional VLAN subif and address); refuses while another `lanN` is up or any bridge exists. It also sets `rx-gro-list on` (eth0 + lanN, as OpenWrt) and starts dropbear (root, blank password, like the flash OpenWrt) for `nat-bench`.
- A bridge made by hand needs `stp_state 1`: STP is off by default in Linux bridges.
- Before the drivers probe, the switch runs whatever U-Boot left: `./dev.py ramload` runs stock `rtk network on` (one cage lit, `--cage N`) and the ASIC forwards until `rtldsa_93xx_setup` isolates the ports.

### Reliance on U-Boot state

- `rtk network on` is not needed by the drivers: eth, PCS/SerDes, MDIO polling, table access and L2 setup are programmed by Linux.
- CPU-port MAC: from the U-Boot env via nvmem (DTS above); the switch MAC registers U-Boot leaves are only the fallback.
- Pinmux: DTS sets none; I2C SDA/SCL, SPI and GPIO muxing rely on U-Boot state (as before).

### Not done here

- `perf` userspace (#67): OpenWrt 24.10.7 publishes no `perf` package for realtek, and the host cross toolchain has no libc. Kernel side (perf events, 34K counters, function_graph) is in. Whether the CP0 perf-counter IRQ is wired on this platform (needed for sampling) is unchecked.
- `generic/pending-6.18/700`, `701` (nft flowtable device events, ignore `EOPNOTSUPP` on offload): apply on 7.3, not applied; software flowtables do not need them.
- Results of the first boots: [NAT.md](NAT.md) "Mainline 7.3"; operations: [MAINLINE-NET-OPS.md](MAINLINE-NET-OPS.md).

## 8. Status of every OpenWrt realtek patch and file (7.3-rc6)

Method: `scripts/openwrt_patch_status.py` (series order; reverse-apply = upstream) plus a source check of each `fails`. Ported = in our build (verbatim or forward-ported, section 7). Dropped = not built for this board.

### `patches-6.18`

| Patch | Status | Evidence / reason |
|---|---|---|
| `021` gpio-regmap shadowed-output cache | dropped | No gpio-regmap user on this board (RTL8231 only) |
| `022`, `023-01/02` | upstream | reverse-apply |
| `024-01/03` dt-bindings `enet-phy-pair-order` | dropped | RTL8224 binding docs; no RTL8224 |
| `024-02` RTL8224 pair order | upstream | 7.3 `realtek_main.c` has pair-order support (different context) |
| `024-04` | upstream | reverse-apply |
| `025-01`, `026`, `027-01..04`, `027-06/07` i2c-rtl9300 | upstream | 7.3 `i2c-rtl9300.c` has the `bus_freq` enum, `F_BUSY`, `rd_reg`, `max_read_len` quirk, clk, RTL9607 config |
| `025-02`, `027-05`, `027-08` | upstream | reverse-apply |
| `028`, `029` lm75, `030` RTL8226 MDI swap | upstream | reverse-apply |
| `031-01..24` mdio-realtek-rtl9300 (v7.2) | upstream | `-16`, `-18..20`, `-22`, `-23` reverse-apply; the rest is in 7.3 with later context. Driver not built (OTTO fork used) |
| `031-25..34` mdio-realtek-rtl9300 (v7.4) | dropped | Apply (`-29` fails), but `MDIO_REALTEK_RTL9300` is off: `mdio-realtek-otto` is used, as in OpenWrt |
| `032-06..08` irqchip select / shuffle / multi-parent | upstream | 7.3 has `intc_select`, multi-parent setup, onecell xlate |
| `033-01` | upstream | reverse-apply |
| `033-02` i2c-gpio shared SCL | upstream | 7.3 `i2c-gpio.c` has the shared-SCL code |
| `034-01`, `035`, `036`, `037` | upstream | reverse-apply |
| `034-02` wdt clock enable | upstream | 7.3 uses `devm_clk_get_enabled` |
| `039-01/02` gpio raw IO / overridable bank IO (v7.4) | dropped | GPIO works on 7.3 without them; needed for RTL960x |
| `040` SPI second CS (v7.4) | dropped | One flash, on CS0 |
| `300-01..03` platform / board setup | ported | verbatim |
| `301` RTL960x platform | dropped | other SoC |
| `308` mtune 4kec | dropped | RTL838x only; needs the generic mtune-24kc hack |
| `309` csum_partial maddu | ported | verbatim |
| `318` clk-rtl83xx | dropped | OpenWrt sets `COMMON_CLK_REALTEK` off for 930x; fixed clocks |
| `330` thermal hook | ported | verbatim |
| `331` otto_table hook | ported | verbatim |
| `700` DSA max ports / u64 masks | ported | forward-port, `300-09` |
| `705` sfp `i2c_block_size` init (v7.1) | upstream | line present in 7.3 `sfp_i2c_configure()` |
| `706-01` sfp I2C quirks (v7.2) | upstream | 7.3 `sfp.c` has the `max_read_len` handling |
| `706-02` | upstream | reverse-apply |
| `712` MDIO SMBus library | ported | verbatim |
| `714` SFP over SMBus | ported | verbatim |
| `716` rtl838x eth hook | ported | forward-port, `300-09` (+ `select PAGE_POOL`) |
| `717` RTL960x GMAC | dropped | other SoC |
| `718` DSA hook | ported | verbatim |
| `720` multiport PHY (RTL8214/8218) | dropped | no copper PHYs on board |
| `721` tag rtl-otto hook | ported | forward-port, `300-09` (tag 36) |
| `722` trapped-frame metadata | ported | verbatim |
| `723` aux MDIO | dropped | RTL8231 bus only |
| `730` PCS hook | ported | forward-port, `300-09` |
| `743` RTL8224 SerDes config | dropped | no RTL8224 |
| `802-804` RTL8231 MFD / pinctrl / LEDs | dropped | no RTL8231 |
| `806`, `808` MDIO otto / SerDes hooks | ported | forward-port, `300-09` |
| `809`, `810`, `813` Hasivo MCU | dropped | other boards |
| `816-01..03`, `817-819` PSE | dropped | no PoE (`816-03` is upstream) |
| `820` RTL960x MDIO, `821`, `822` PCIe | dropped | other SoC / no PCIe use |

### `files-6.18`

| File(s) | Status | Note |
|---|---|---|
| `arch/mips/include/asm/mach-rtl-otto/*` | ported | verbatim |
| `drivers/clk/realtek/*`, `include/dt-bindings/clock/rtl83xx-clk.h` | dropped | see `318` |
| `drivers/net/dsa/rtl83xx/*` (incl. `l3.c` v4+v6 routing offload, `l2`, `tc`, `pie`, `qos`, `lag`, `mirror`, `stp`, `vlan`, `debugfs`) | ported | verbatim + `300-10` |
| `drivers/net/ethernet/realtek/rtl838x_eth.[ch]` | ported | verbatim + `300-11` + `300-12` |
| `drivers/net/ethernet/realtek/rtl960x_gmac.[ch]` | dropped | other SoC |
| `drivers/net/mdio/mdio-realtek-otto.c`, `mdio-realtek-otto-serdes.c` | ported | verbatim |
| `drivers/net/mdio/mdio-realtek-otto-rtl960x.c` | dropped | other SoC |
| `drivers/net/pcs/pcs-rtl-otto.c` | ported | verbatim |
| `drivers/net/phy/realtek/realtek_multiport.c` | dropped | see `720` |
| `drivers/pci/controller/pcie-realtek.c`, `drivers/phy/realtek/phy-rtk-pcie.c` | dropped | no PCIe use |
| `drivers/soc/realtek/*`, `include/linux/soc/realtek/otto_table.h` | ported | verbatim |
| `drivers/thermal/realtek-thermal.c` | ported | verbatim |
| `net/dsa/tag_rtl_otto.c` | ported | verbatim |

### OpenWrt `target/linux/generic` patches the realtek code depends on (scope for step 2)

| Generic patch | Needed by | Here |
|---|---|---|
| `pending-6.18/737-01..07` phylink fwnode PCS provider | `pcs-rtl-otto` (provider), `rtl83xx/dsa.c` (`fwnode_phylink_pcs_parse`, `fill_available_pcs`) | forward-ported (`300-08`); `737-02/04/05/06` fail verbatim on 7.3 |
| `pending-6.18/700`, `701` nft flowtable device events / offload `EOPNOTSUPP` | nft `flags offload` flowtables over DSA ports | apply on 7.3; not applied |
| `pending-6.18/720-*`, `721-*`, `742`, `743` Realtek RTL82xx PHYs | boards with RTL822x/826x PHYs | not needed (SFP only) |
| `hack-6.18` mtune 24kc | `308` | not needed |

The rest of `generic/` (backports, other vendors' PHY/DSA/Ethernet, MediaTek PPE, bridge BPDU knob `710`) is not referenced by the realtek files above.

## 9. SMP: interrupt routing, throughput, latency (#73, #60, #16)

Measured 2026-10-12, mainline 7.3-rc6, `ramload uboot-mainline --then mainline-kernel` (CPU 1 GHz), one 10G SR in cage 1 (lan1), nic-bench = NAT + flowtable, one run each (`./dev.py nic-bench`).

### Boot hang (fixed in the board DTS, 264e6ee)
- Mainline `rtl930x.dtsi`: 1-cell intc, every source on output 0 = CPU IP2.
- `vsmp_init_secondary()` (non-GIC) unmasks only IP0/1/6/7 on VPE1: CPU1's otto timer never ticks; boot hangs at the first CPU1-bound sleep (console hand-over `synchronize_srcu`, after `bootconsole [early0] disabled`). Independent of preempt mode and CPU clock.
- Board DTS: 2-cell intc, parents IP2-6, outputs as OpenWrt `rtl930x.dtsi` (timers on output 4 = IP6, UART 1, switch 2, NIC 3). IP7 (CP0 timer/perf) not claimed.
- Same DTS for OpenWrt-on-7.3 (the 7.3 OpenWrt build uses it).

### IRQ affinity (`300-18`, `./dev.py irq-check`)
- Before 300-18: default `smp_affinity` 3 -> effective 3; GIMR enabled on both VPEs, but VPE1 has IP2-5 masked, so only CPU0 takes eth0/UART/switch IRQs. ERR count unchanged under load (2).
- Before 300-18: `smp_affinity` 2 for eth0 -> NIC dead (IRQ never taken, ping 0/3); restoring 3 recovers.
- 300-18: effective affinity = one online CPU; a cpuhp STARTING hook sets the intc parent IM bits on each secondary. eth0 on CPU1 works (47k IRQs on CPU1 during a run).

### Throughput (one run each)

| Build | tcp-P4 Mbit/s | udp1400-900 kpps | udp64 kpps |
|---|---|---|---|
| UP | 346 | 60.5 | 66.9 |
| SMP, eth0 CPU0 | 322-325 | 55.8-57.6 | 64.4-64.9 |
| SMP + 300-18, eth0 CPU1 | 334 | 59.3 | 67.9 |

- One NAPI context: the softirq runs on the CPU that takes eth0; the other VPE idles (CPU1 busy 0.1-0.6 % with eth0 on CPU0).
- eth0 on CPU1 recovers the SMP loss: CPU0 also carries the UART, timers' housekeeping and RCU.

### Latency (`build-kernel --latency`: timerlat + irqsoff tracers)
timerlat per CPU, 10 s idle / 12 s under nic-bench tcp-P4. irqsoff = max IRQs-off section in a separate window of the same length; with the function tracer active it is an upper bound.

| Build / state | CPU | IRQ min/avg/max us | thread min/avg/max us | irqsoff max us |
|---|---|---|---|---|
| UP idle | 0 | 6.1 / 8.6 / 25.6 | 32.6 / 35.3 / 315 | 181 |
| UP load | 0 | 4.5 / 19.3 / 4571 | 32.6 / 1162 / 7934 | 321 |
| SMP idle | 0 / 1 | 7.4 / 17.5 / 95 ; 9.3 / 17.0 / 43 | 42 / 64 / 519 ; 55 / 76 / 244 | 446 |
| SMP load, eth0 CPU0 | 0 / 1 | 10.6 / 39.1 / 5929 ; 12.5 / 42.9 / 111 | 56 / 1628 / 9728 ; 58 / 138 / 562 | 935 |
| SMP load, eth0 CPU1 | 0 / 1 | 5.4 / 39.0 / 106 ; 9.6 / 40.5 / 5920 | 47 / 133 / 327 ; 56 / 1631 / 9408 | 584 |

- The CPU running the NIC softirq sees ms-scale timer IRQ and thread latency under load (NAPI/softirq); the other VPE stays at ~0.1 ms IRQ / ~0.5 ms thread max.
- SMP idle IRQ latency is about 2x UP (two VPEs share one pipeline).
- irqsoff worst: `__schedule`->`finish_task_switch` (rcu_sched, idle) and `_raw_spin_lock_irqsave` in ksoftirqd (load).
