# Mainline Linux port (issue #16)

Goal: Linux 7.x mainline-based kernel driving the 8 SFP+ ports of the TL-ST1008F v2 (RTL9303). Desk analysis, 2026-10-10; nothing here was run on the switch.

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
| 4 | RAM above 256 MiB (board has 512 MiB in two banks) | TRIV | `300-02` HIGHMEM zone remap applies strict on 7.3; not upstream. Stage 0 uses 256 MiB only |
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
  - Omitted (no upstream driver/binding): switch ports, CPU port, PCS handles, SerDes, LEDs, thermal, 2nd RAM bank.
  - SFP I2C left at the controller default; SFF-8472 module EEPROM is a 100 kHz interface, so default is the rated max.
- `mainline/st1008f-v2.config`: Kconfig fragment on `32r2_defconfig` (big-endian, HIGHMEM from `generic/32r2.config`), `MACH_REALTEK_RTL`, 8250 console, `I2C_RTL9300`, `I2C_GPIO`, `GPIO_REALTEK_OTTO`, `GPIO_PCA953X`, `REALTEK_OTTO_WDT`, MTD SPI-NOR + OF partitions, `SFP`, `MDIO_REALTEK_RTL9300`, `KEYBOARD_GPIO`.
- Build check (2026-10-10, `scripts/mainline_build_check.py`): `dtc` clean (0 warnings), `vmlinux` links (ELF32 MSB MIPS32r2, text 12.1 MB), DTB 6.7 KB. Not booted; `dtbs_check` not run.
- Stage-0 gate (issue #16): serial boot, `i2c-rtl9300` / `gpio-realtek-otto` / `realtek_otto_wdt` / SPI-NOR probe. Needs the image wrapper (#5) and a switch session.

## 5. Next steps (dependency order)

1. Image wrapper for stock U-Boot (uImage magic `0x93030000`, appended DTB, LZMA); boot stage-0 in RAM on a free hardware session, one cage lit.
2. Add `300-01..03` + headers to the 7.3 tree; boot with 512 MiB.
3. Rebase `737-01..08` onto 7.3 properly (hand-merge `737-02`, review fuzz); then `700`/`721`/`722` as one DSA-core patch.
4. Boot the compiled full set with the OpenWrt-style DTS (switch children nodes, `pcs-handle`, `mdio-controller` without `reg` for the OTTO fork, or with `reg = <0xca00 0x200>` for mainline MDIO).
5. Gate per issue #16 stages: CPU port up, MDIO/PCS pages, L2 bridge at 1G, 10GBASE-R link on one cage.

## 6. Not determined

- Runtime behaviour of any out-of-tree driver on 7.3 (nothing was booted).
- Upstream state of the phylink fwnode PCS series and of a Realtek DSA submission on netdev (net-next/lore not searched).
- Whether the OTTO MDIO fork can be replaced by mainline `mdio-realtek-rtl9300` + `031-25..34`.
- Whether mainline `MACH_REALTEK_RTL` needs `MIPS_CPU_SCACHE` for RTL930x (OpenWrt selects it, mainline does not).
- Pinmux assumptions: board DTS sets none; SDA/SCL, SPI and GPIO muxing rely on U-Boot state.
- `dtbs_check` result; U-Boot image wrapper.
