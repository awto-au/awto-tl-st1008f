# TP-Link TL-ST1008F v2 (RTL9303) reverse engineering

8-port 10G SFP+ unmanaged switch: RTL9303 SoC (`RTL9303_8XGE`), 512 MiB RAM, 32 MiB SPI NOR, stock U-Boot `2011.12.(3.6.6.55087)`.

## Headline: 10G Ethernet in stock U-Boot

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

- Done: 10G TFTP from stock U-Boot; OpenWrt 25.12.4 RAM-boot; verified full-flash backup; stock image unpacked; stock serial-console behaviour explained.
- Open:
  - Download the flash over 10G straight from U-Boot (no TFTP send command in stock U-Boot).
  - Shell on the stock firmware: stock `/dev` nodes are regular files and `rc` runs `diag` in the foreground; `rdinit=/bin/sh` panics.
  - USB host port (on-chip EHCI, 1 port, no connector) — not yet probed.
  - 3-way mode switch (GPIO 17/18/19): positions not mapped.
  - GPIO21 (DTS watchdog toggle) is static high at the U-Boot prompt and the board does not reset: unexplained.
  - Managed ST5008F v2 firmware RAM-booted on this board: not tried.

## Docs

- [docs/hardware.md](docs/hardware.md) — identity, UART, cage↔port↔SerDes map, GPIO/I2C, lasers, hazards.
- [docs/UBOOT-REFERENCE.md](docs/UBOOT-REFERENCE.md) — stock U-Boot: source match, `rtk` commands + hazards, bring-up path, datapath registers.
- [docs/UBOOT-FUNCMAP.md](docs/UBOOT-FUNCMAP.md) — SDK function addresses in the stock loader.
- [docs/FIRMWARE-ANALYSIS.md](docs/FIRMWARE-ANALYSIS.md) — stock flash/kernel/initramfs; related managed firmware.
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

- Never write flash: no `saveenv`, `savesys`, `setsys`, `upgrade`, `*force`, `flerase`, `sf write/erase/update`.
- One cage cabled (or lit) at a time.
- Run `rtk network on` once per boot; run GPIO/I2C `rtk` commands only after it.
- Keep flash dumps private: they can contain configuration and identifiers.

## References

- [OpenWrt v2 support commit](https://github.com/openwrt/openwrt/commit/39b9b491bb), [v2 DTS](https://github.com/openwrt/openwrt/blob/main/target/linux/realtek/dts/rtl9303_tplink_tl-st1008f-v2.dts)
- [NicGiga S100-0800S-M](https://openwrt.org/toh/nicgiga/s100-0800s-m) (same board profile)
- Realtek GPL U-Boot/SDK sources matching this loader: `github.com/reyalo/Realtek`
