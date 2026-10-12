# Docs index

- Reference docs are facts, present tense. Run/verify/recover steps live in the matching `*-OPS.md`.
- Narrative, timeline and dead ends: [HISTORY.md](HISTORY.md). Owner decisions: [DECISIONS.md](DECISIONS.md).
- Issues link here; results live in these docs, not only in issue comments.

## Board and hardware

- [hardware.md](hardware.md) — identity, UART, cage↔port↔SerDes map, GPIO/I2C, lasers, bench rig, hazards.
- [BOM.md](BOM.md) — component list from board photos: parts, markings, rails, flash IO2/IO3 wiring (#87, #61).
- [HARDWARE-INVENTORY.md](HARDWARE-INVENTORY.md) — every SoC block: on chip, wired, who uses it (#62).
- [BUS-SCAN.md](BUS-SCAN.md) — I2C/SPI bus scan; no undocumented devices (#77).
- [DATASHEET-AUDIT.md](DATASHEET-AUDIT.md) — RTL9303 datasheet features vs stock/OpenWrt/ours (#69).
- [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) — undocumented/unused RTL9303 hardware (#68).
- [CRYPTO.md](CRYPTO.md) — SoC crypto engine (#62, #78).

## Clocks and memory

- [CLOCKS.md](CLOCKS.md) — clock tree, PLLs, overclock results. Ops: [CLOCKS-OPS.md](CLOCKS-OPS.md).
- [DRAM.md](DRAM.md) — DRAM theory vs measured; per-speed init steps and leads above 650 MHz (#48).
- [SPI-NOR.md](SPI-NOR.md) — SPI-NOR controller fields, flash limits, Linux read opcode (#50).
- [OVERCLOCK.md](OVERCLOCK.md) — overclock method, ratio-dependent register rules, per-unit settings (#101, #103). Ops: [OVERCLOCK-OPS.md](OVERCLOCK-OPS.md).

## U-Boot

- [UBOOT-REFERENCE.md](UBOOT-REFERENCE.md) — stock U-Boot: source match, `rtk` commands, bring-up path, datapath registers.
- [UBOOT-FUNCMAP.md](UBOOT-FUNCMAP.md) — SDK function addresses in the stock loader.
- [UBOOT-MAINLINE.md](UBOOT-MAINLINE.md) — our mainline U-Boot port (#23).
- [RTK-COMMANDS.md](RTK-COMMANDS.md) — `rtk` command parity, stock vs ours.
- [SW-DEFAULTS.md](SW-DEFAULTS.md) — stock switch defaults in our `rtk network on`: reg-diff vs stock, per-row verdict (#80).
- [SDS-TOOLS.md](SDS-TOOLS.md) — SerDes test tools `rtk sds` (#74).

## Boot and OS

- [DEFAULT-BOOT.md](DEFAULT-BOOT.md) — OpenWrt on 7.3 as default boot + recovery (#73). Ops: [DEFAULT-BOOT-OPS.md](DEFAULT-BOOT-OPS.md).
- [MAINLINE-PORT.md](MAINLINE-PORT.md) — Linux 7.3 port of the OpenWrt RTL930x drivers (#16). Ops: [MAINLINE-NET-OPS.md](MAINLINE-NET-OPS.md).
- [OPENWRT-BUILD.md](OPENWRT-BUILD.md) — local OpenWrt build (#73). Ops: [OPENWRT-BUILD-OPS.md](OPENWRT-BUILD-OPS.md).
- [FIRMWARE-ANALYSIS.md](FIRMWARE-ANALYSIS.md) — stock flash/kernel/initramfs; related managed firmware.
- [MANAGED-FEATURES.md](MANAGED-FEATURES.md) — TL-ST5008F v2 managed feature inventory vs ours (#79).

## Routing, NAT, NIC

- [NAT.md](NAT.md) — NAT path, ceilings, measured results (#65). Ops: [NAT-OPS.md](NAT-OPS.md).
- [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md) — HW L3 routing offload (#59). Ops: [ROUTING-OFFLOAD-OPS.md](ROUTING-OFFLOAD-OPS.md).
- [UPSTREAM-L3.md](UPSTREAM-L3.md) — upstream path for L3 offload: survey of router/flowtable offload code, shared `fib_offload` helper proposal (#85).
- [VENDOR-NIC-TUNING.md](VENDOR-NIC-TUNING.md) — vendor CPU-NIC tuning vs OpenWrt `rtl838x_eth` (#60).

## Realtek SDK

- [SDK-SOURCES.md](SDK-SOURCES.md) — public Realtek switch SDK drops with Longan code.
- [REGISTERS.md](REGISTERS.md) — every register our code touches: SDK name, fields, writers; where we differ from the SDK (#102).
- [SDK-FEATURE-MAP.md](SDK-FEATURE-MAP.md) — SDK API/feature groups vs users (#76).
- [SDK-LEFTOVERS.md](SDK-LEFTOVERS.md) — debug/test/disabled SDK features (#74).

## Other

- [stock-flash-layout.json](stock-flash-layout.json) — stock flash partition table.
- [photos/](photos/) — board photos (CC BY-SA 4.0).
