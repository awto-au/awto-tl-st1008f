# TP-Link TL-ST1008F v2 (RTL9303): open firmware

8-port 10G SFP+ unmanaged switch: RTL9303 SoC (`RTL9303_8XGE`), 512 MiB RAM, 32 MiB SPI NOR, stock U-Boot `2011.12.(3.6.6.55087)`.
This repo turns it into a managed switch/router on open firmware: our mainline U-Boot + Linux 7.3 with OpenWrt's RTL930x drivers.

## Headline: two tracks

| Track | What | State |
|---|---|---|
| **Linux 7.3 port** | mainline 7.3 + all of OpenWrt's realtek target (DSA, NIC, L3 offload, PCS/SerDes, SFP) + our patches `openwrt/patches/300-*` | boots, switches, routes, NAT; RAM-boot (#16) |
| **OpenWrt tracking** | local OpenWrt buildroot on OpenWrt main; our patches backported to 6.18; then OpenWrt userspace on our 7.3 kernel | in progress (#73) |
| **Default boot** | OpenWrt on 7.3 (22 MiB) + recovery OpenWrt 6.18 (7 MiB), selected by our U-Boot | designed, not flashed (#73, [docs/DEFAULT-BOOT.md](docs/DEFAULT-BOOT.md)) |

- Power-up today: stock loader → our U-Boot → flash OpenWrt 25.12.4. Stock U-Boot is never written.
- Upstream: patches are prepared for OpenWrt / Linux; posting needs owner approval.

## Mode switch (front panel M1 / M2 / M3)

Wiring and measurements: [docs/hardware.md](docs/hardware.md).

| Position | Our firmware at boot (#73, #46) | Stock vendor meaning (Linux `rtk.ko`) |
|---|---|---|
| **M1** | switch mode: all cages bridged, STP | pattern 1: 1G modules at 1G, 2.5G forced to 1G |
| **M2** | isolated management: every cage reaches only the box | pattern 2: cages 1-4 as M1, 5-8 as M3 |
| **M3** | recovery OpenWrt (isolated management) | pattern 3: 2.5G modules at 2.5G, 1G left down |

- 10G modules ignore the speed pattern.
- Management address in every mode: DHCP + fallback `192.168.0.1`.
- Not yet flashed: today M2 stops at our U-Boot prompt and M3 needs the recovery image (#73).

## What we improved

| Area | Stock firmware | OpenWrt 25.12.4 | Ours |
|---|---|---|---|
| CPU / RAM | 800 MHz, DDR3 600, prefetch off | inherits U-Boot clocks | 1 GHz, DDR3 650, DRAM prefetch (RAM write +68 %, read +49 %) |
| Bootloader | 2011 U-Boot, no network | stock | mainline U-Boot: `rtk` parity incl. `network on`, SerDes eye/PRBS, LEDs, crypto test, boot fallback |
| Kernel | Linux 3.18 (EOL) | 6.18 | 7.3, minimal config, 512 MiB with fixed highmem path |
| NAT + flowtable (TCP) | none (unmanaged) | 243-248 Mbit/s | 365-370 Mbit/s; UDP 1400 B ~750 Mbit/s |
| L3 offload | — | gateway routes only | + on-link hosts, default route v4/v6 (opt-in, `300-17`, #59) |

- IPv6 routed in the ASIC: 9.08 Gbit/s at 0 % CPU (#65). IPv4 NAT ceiling on this CPU ≈ 1 Gbit/s; 2.5G NAT not reachable (#65).
- Also: LED snake/error/panic patterns, mode-switch driver, SerDes test tools, crypto engine (#62), automatic storm guard.
- Full lists: [docs/NAT.md](docs/NAT.md), [docs/CLOCKS.md](docs/CLOCKS.md), [docs/MAINLINE-PORT.md](docs/MAINLINE-PORT.md), [docs/DECISIONS.md](docs/DECISIONS.md).

## Compared with TP-Link's managed firmware (TL-ST5008F v2, same chip)

| | Managed ST5008F v2 1.2.0 | Ours |
|---|---|---|
| Kernel / userspace | Linux 3.18 (EOL), uClibc, 2015 Buildroot | Linux 7.3 (+ OpenWrt userspace, in progress) |
| Management UI | web UI, CLI, SSH, SNMP, Omada | SSH + shell today; LuCI/uci with OpenWrt on 7.3 |
| CPU packet path | NIC driver in userspace; CPU port capped at 600 pps | kernel NAPI driver, ~65 kpps forwarded |
| Routing / NAT | L3 features in the SDK; no NAT | ASIC L3 incl. IPv6; CPU NAT + flowtable |
| Clocks | 800 MHz, DDR 600 | 1 GHz, DDR 650 |

- Better than managed: performance, modern kernel, IPv6 hardware routing exposed, NAT, open and patchable.
- Managed still ahead: polished UI, SNMP/Omada integration, and a tested feature set. Ours closes the UI gap once OpenWrt runs on 7.3 (#73).
- Not yet compared head-to-head on the same unit (managed firmware has not been RAM-booted here, #6).

## 10G Ethernet in stock U-Boot

Stock U-Boot can `tftpboot` over the SFP+ cages. No flash write, no custom bootloader.

- The SFP lasers sit behind a PCA9534 GPIO expander @ `0x38` (tx-disable, active-high). Power-on state = all inputs → **all 8 lasers off**.
- U-Boot never drives it, so every link test from the bootloader fails silently: the switch receives light, the far end sees nothing.
- `rtk network on` registers the expander as `rtk i2c` device 8. Two writes turn the lasers on.

### Recipe (fresh boot, at `RTL9300#`)

Interrupt autoboot with one Esc (`bootdelay=1`; `scripts/switch_console_daemon.py` does it automatically). Serve the
[OpenWrt 25.12.4 `tplink_tl-st1008f-v2` initramfs](https://downloads.openwrt.org/releases/25.12.4/targets/realtek/rtl930x/)
as `st1008f.bin` from a TFTP server (`scripts/tftpd.py`).

```
rtk network on                       # once per boot; ends "Err:0xf030:FAIL (0xf030)" — benign
rtk i2c write 8 1 0xfe               # PCA9534 output reg: bit N=1 keeps cage N+1 off; 0xfe = cage 1 only
rtk i2c write 8 3 0                  # PCA9534 config reg: all pins output
setenv ipaddr <switch-ip>; setenv serverip <tftp-server-ip>
tftpboot 0x84f00000 st1008f.bin      # 5383940 bytes
iminfo 0x84f00000                    # "Verifying Checksum ... OK"
bootm 0x84f00000                     # OpenWrt in RAM; unplug other cages first (below)
```

- Cage 2 only: `rtk i2c write 8 1 0xfd`. Readback: `rtk i2c read 8 1`.
- Verified on cage 1 and cage 2 with 10GBASE-SR modules. Full session: [artifacts/uboot-10g-tftp-bootm-20261008.log](artifacts/uboot-10g-tftp-bootm-20261008.log).
- Nothing is saved: no `saveenv`. Laser state survives a warm `reset`, not a power cycle.

### Hazard: cage loop

- Two cages cabled to the same switch + both lasers on + `rtk network on` → U-Boot's SDK forwards front-port to front-port → **broadcast storm** (tens of millions of multicast frames per minute).
- Light one cage only (`0xfe`/`0xfd`, never `0x00` with two fibres in). Recover with `rtk port disable <sdk-port>` (cage 2 = SDK port 8).
- OpenWrt's initramfs lights every laser and bridges every port (no STP): **unplug the other fibres before `bootm`**.

### Check traffic with MIB counters

- `md.l 0xBB000700 8` (cage 1 / SDK port 0), `md.l 0xBB000F00 8` (cage 2 / SDK port 8). Counters climb with traffic.
- Do not use the SerDes block-lock register (`rtk sdsreg get 0 2 1 30`): it reads `0x0000`/`0x0100` here even with traffic flowing. `MAC_LINK_STS` (`0xBB00CB10`) shows forced bits, not link.

## Full-flash backup

1. RAM-boot OpenWrt as above (one cage cabled).
2. Give it an address on your LAN if needed: `ip addr add <switch-ip>/24 dev switch.1` (RAM only; default is `192.168.1.1/24`).
3. From the host: `scripts/st1008_mtd_backup.py --host <switch-ip>`.
   - Reads `/dev/mtdNro` over SSH, SHA-256 on device and host per partition, checks sizes against `/proc/mtd`.
   - Writes `private/mtd-backup-<timestamp>/` with each MTD, `full-flash.bin` (32 MiB) and `SHA256SUMS`.
   - 32 MiB in ~40 s on 2026-10-08. Full-image CRC32 matched U-Boot's own whole-chip `crc32`.
4. Unpack the stock image: `scripts/st1008_stock_extract.py private/mtd-backup-<timestamp>/full-flash.bin`.

Never run `sysupgrade`, `mtd write`/`erase`, `firstboot`, or mount the stock JFFS2 regions read-write.

- Flash state: `firmware` = OpenWrt 25.12.4 (sysupgrade 2026-10-08; owner decision: keep it; LAN static 192.168.25.48, bridge STP on); `jffs2-log` (0x200000) = our mainline U-Boot; stock env `bootcmd` chainloads it (`bootcmd_stock=boota` kept, #47). Loader stock. Stock firmware only in the 2026-10-08 backup (#36).

## Firmware family

| | TL-ST1008F v2 (this unit) | TL-ST5008F v2 (managed sibling) |
|---|---|---|
| U-Boot | `2011.12.(3.6.6.55087)` | `2011.12.(3.6.9.55156)` |
| Console | 115200 | 38400 |
| Stop autoboot | Esc | Ctrl+B |
| Board profile | `RTL9303_8XGE` | `RTL9303_8XGE` |

## Workflow

Details per script: [scripts/README.md](scripts/README.md).

1. `scripts/switch_console_daemon.py --dev /dev/serial/by-id/<adapter>` — owns the UART, logs both directions, auto-catches U-Boot.
2. Power-cycle the switch → daemon stops at `RTL9300#`. Drive it with `scripts/switch_console.py send "<cmd>"`.
3. `sudo scripts/tftpd.py` with the initramfs at `tmp/tftp/st1008f.bin`.
4. Recipe above: `rtk network on`, laser writes, `tftpboot`, `iminfo`; unplug other cages; `bootm`.
5. `scripts/st1008_mtd_backup.py --host <switch-ip>`.
6. `scripts/st1008_stock_extract.py private/mtd-backup-<timestamp>/full-flash.bin`.

## Status

- Done:
  - 10G TFTP from stock U-Boot; full-flash backup; stock image unpacked.
  - Our U-Boot chain-loaded on every power-up at 1 GHz / DDR 650 (#47); `rtk network on` without stock (#51).
  - Linux 7.3 with OpenWrt drivers: traffic, NAT, NIC path fixes, 512 MiB, mode-switch driver (#16, #60, #64).
  - Mode switch mapped (#8); bus scan: no undocumented devices (#77); hidden hardware catalogued (#68).
- Open: default boot install (#73), ACL firewall for ASIC-routed traffic (#66), L3 offload board tests (#59), SMP test (#60), NAT path review (#71). Index: #72.
- USB host (EHCI) is on-chip but not wired (#5). GPIO21 watchdog behaviour unexplained (#18).
- Managed ST5008F v2 firmware RAM-booted on this board: not tried (#6).

## Docs

- [docs/hardware.md](docs/hardware.md) — identity, UART, cage↔port↔SerDes map, GPIO/I2C, lasers, hazards.
- [docs/UBOOT-REFERENCE.md](docs/UBOOT-REFERENCE.md) — stock U-Boot: source match, `rtk` commands + hazards, bring-up path, datapath registers.
- [docs/UBOOT-FUNCMAP.md](docs/UBOOT-FUNCMAP.md) — SDK function addresses in the stock loader.
- [docs/FIRMWARE-ANALYSIS.md](docs/FIRMWARE-ANALYSIS.md) — stock flash/kernel/initramfs; related managed firmware.
- [docs/DEFAULT-BOOT.md](docs/DEFAULT-BOOT.md) — OpenWrt on 7.3 as default boot, recovery fallback (design, #73).
- [docs/HISTORY.md](docs/HISTORY.md) — history / how we did it: timeline, wrong turns, what resolved them.
- [artifacts/](artifacts/) — captured U-Boot and boot logs (redacted).

## Layout

```
README.md            this file
docs/                reference docs, board photos (CC BY-SA 4.0)
artifacts/           text captured from the device
scripts/             Python tooling; scripts/node/ (historical Node helpers), scripts/ghidra/ (Ghidra scripts)
private/             gitignored: flash dumps, vendor firmware, serial logs, Ghidra projects
tmp/                 gitignored: logs (tmp/logs/), TFTP root (tmp/tftp/), scratch
```

## Safety rules used throughout

- Never write the stock U-Boot area (`0x0`-`0xDFFFF`); stock env only via `./dev.py uboot-chain-env`; no `savesys`, `setsys`, `upgrade`, `*force`, `flerase` at the stock prompt (CLAUDE.md).
- One cage cabled (or lit) at a time.
- Run `rtk network on` once per boot; run GPIO/I2C `rtk` commands only after it.
- Keep flash dumps private: they can contain configuration and identifiers.

## References

- [OpenWrt v2 support commit](https://github.com/openwrt/openwrt/commit/39b9b491bb), [v2 DTS](https://github.com/openwrt/openwrt/blob/main/target/linux/realtek/dts/rtl9303_tplink_tl-st1008f-v2.dts)
- [NicGiga S100-0800S-M](https://openwrt.org/toh/nicgiga/s100-0800s-m) (same board profile)
- Realtek GPL U-Boot/SDK sources matching this loader: `github.com/reyalo/Realtek`
