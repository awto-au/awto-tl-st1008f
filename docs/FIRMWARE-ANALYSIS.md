# TL-ST1008F stock firmware and related TP-Link firmware

Narrative & dead ends: see [HISTORY.md](HISTORY.md).

## Stock TL-ST1008F flash (full-flash backup, 32 MiB)

Acquired via RAM-booted OpenWrt ([README](../README.md#full-flash-backup)); unpacked with `scripts/st1008_stock_extract.py`.

| Region | Offset | Size | Content |
|---|---|---|---|
| LOADER | `0x0000000` | `0x0e0000` | U-Boot; identical to the two-read serial LOADER dump (CRC32 `e579e61c`) |
| BDINFO | `0x00e0000` | `0x010000` | U-Boot env (`baudrate`, `boardmodel`, `bootcmd`, …) |
| SYSINFO | `0x00f0000` | `0x010000` | all `0xFF` |
| JFFS2_CFG | `0x0100000` | `0x100000` | all `0xFF` |
| JFFS2_LOG | `0x0200000` | `0x100000` | all `0xFF` |
| RUNTIME1 | `0x0300000` | `0xe80000` | kernel image at `0x300000`; identical second copy at `0x800000` |
| RUNTIME2 | `0x1180000` | `0xe80000` | all `0xFF` |

- The unit stores no configuration: SYSINFO and both JFFS2 regions are erased.
- Full-image CRC32 `dd984f95` = the U-Boot `crc32` over `0xb4000000`+32 MiB taken before acquisition.
- OpenWrt's MTD view: [../artifacts/openwrt-proc-mtd.txt](../artifacts/openwrt-proc-mtd.txt) (`u-boot`, `u-boot-env`, `u-boot-env2`, `jffs2-cfg`, `jffs2-log`, `firmware` = `0x300000`-end). Labels are OpenWrt's, not stock content types.

### Kernel

- Legacy uImage layout, Realtek magic `0x93000000`, name `RTK_SDK`, LZMA, `0x4b0a6e` bytes, load `0x80000000`, entry `0x80283850`, data CRC OK, created 2022-01-19T16:37:57Z.
- Linux 3.18.24; built-in cmdline `console=ttyS0,115200`; no IKCONFIG.
- Initramfs: gzip cpio at vmlinux+`0x3c66ec` (`0xc2b400` bytes). No squashfs after the kernel.
- Build path string: `smb2_switch_ST1008F_scm/20191126_ST1008/SDK3.6.6.55087`.
- `/etc/version`: Realtek SDK version 3.2.0, built 2022-01-19.

### Userspace and the silent console

Excerpts: [../artifacts/stock-initramfs-excerpts.md](../artifacts/stock-initramfs-excerpts.md).

- `inittab`: `::sysinit:/etc/rc`, `ttyS0::respawn:/bin/sh`.
- `passwd`: root, empty password, shell `/bin/cli` (absent from the image).
- `rc`: mounts devpts/proc, insmods `rtcore`, `rtk`, `rtnic`, `rtdrv` (plus optional `model`, `rise`, `rlapp`), `ifconfig eth0 192.168.1.1`, then runs `diag` (Realtek SDK shell) in the foreground. `diag` never returns, so init never reaches the `ttyS0` respawn.
- Every `/dev` entry in the cpio (`console`, `ttyS0`, `null`, …) is a 0-byte regular file, not a device node. Kernel printk reaches the UART; userspace stdio goes to RAM files.
- Result: printk during boot, then silence. No getty, no shell, no CLI on serial.
- BREAK (0.3 s, 0.5 s) and BREAK + SysRq `h`/`9`/`l` produce nothing; `kernel.sysrq` is not enabled.
- `bootargs` are honoured by `boota`:
  - `console=ttyS0,115200 rdinit=/bin/sh` → `/etc/rc` skipped, then `Kernel panic - not syncing: Attempted to kill init! exitcode=0x00000000` (sh reads EOF from the fake console).
  - `rdinit=/bin/sh -c "mknod /dev/s c 4 64; exec /bin/sh </dev/s >/dev/s 2>&1"` → same panic, exit 0; the words after `rdinit=` do not appear to reach init's argv.
  - No `panic=` and no watchdog reset → power cycle after each panic.
  - Log: [../artifacts/stock-rdinit-sh-test-20261008.log](../artifacts/stock-rdinit-sh-test-20261008.log).

### USB

- On-chip EHCI (`rtk_gen1-ehci`, `io mem 0x18021000`, irq 28), 1 root-hub port, USB 2.0. Nothing enumerates at stock boot.
- Stock kernel registers `usb-storage` and `usbtmc` (built in). Host only; no gadget.
- Sibling rootfs hotplug is `mdev` with no `mdev.conf` → no automount/autorun.
- OpenWrt 25.12.4 initramfs has no USB bus.

### Flash and MAC

- Boot reports `WINBOND/EF4019/MMIO32-2/ModeC 1x32 MB`; OpenWrt DTS: one `jedec,spi-nor`. SPI NOR, not NAND; seven stock partitions on one chip.
- U-Boot env: 65,536 bytes from `0xe0000` (BDINFO). `ethaddr` = Realtek OUI with placeholder NIC bytes. `printsys` → `Invalid system information`. No unique factory MAC location found.
- [stock-flash-layout.json](stock-flash-layout.json) covers exactly 33,554,432 contiguous bytes.

## Related managed-switch firmware

No public TL-ST1008F firmware exists on its official download pages. Related official updates were acquired for comparison.

| Model/revision family | Versions | Build dates |
| --- | --- | --- |
| TL-SX3008F v1 | 1.0.0, 1.0.1, 1.0.4, 1.0.5 | 20210316, 20220623, 20230131, 20230702 |
| SX3008F v1/v1.20 | 1.20.0, 1.20.2, 1.20.3, 1.20.7, 1.20.12, 1.20.18, 1.20.23 | 20231011, 20241206, 20250121, 20250430, 20251031, 20260310, 20260509 |
| SX3008F v2 | 2.0.0 | 20260720 |
| TL-ST5008 v1 (copper 10G) | 1.0.1 | 20231129 |
| TL-ST5008F v2 (SFP+) | 1.2.0 | 20260506 |

- 14 ZIPs, all pass `unzip -t`. SHA-256 values are local provenance, not vendor signatures. No TL-ST5008F v1 download found.
- SX v1 GPL archive acquired; SX v2 GPL listed but not acquired.

### Container decoding

- Update BINs are DES-CBC encrypted. Key/IV come from `DesDecode.c` in the SX v1 GPL source (`ldk_marvell/u-boot-2013.01-2016_T1.0.eng_drop_v6/common/`); crypto padding disabled.
- [scripts/node/decode_firmware.mjs](../scripts/node/decode_firmware.mjs) reads key/IV from that GPL file (not embedded), refuses to overwrite output, reproduces all 14 decodes.

| Family | Decoded image name | SquashFS offset | Kernel |
| --- | --- | --- | --- |
| SX v1 | `mv-bobk.all.bin`; earliest `tl-sx3008.all.bin` | `0x200` | FIT; ARM zImage + DTBs |
| SX v2 | `rtk-mango.all.bin` | `0x200` | custom legacy uImage magic `0x93000000`, LZMA |
| ST5008 | `tl-st5008.all.bin` | `0xa00` | standard uImage, gzip |
| ST5008F v2 | `tl-st5008f_v2.all.bin` | `0xa00` | standard uImage, LZMA |

- Length fields: SX rootfs/kernel at `0xe8`/`0xec`; ST at `0xec`/`0xf0` (after an extra config-length field).
- Verified: uImage header/payload CRCs, FIT container size, SquashFS listings. Not verified: outer metadata/signing scheme, FIT embedded hashes.
- Decoded images are not TL-ST1008F backups and not safe to cross-flash.

### What runs

| Image | Userspace | Kernel | Application stack |
| --- | --- | --- | --- |
| SX v1 1.20.23 | ARM LE, EABI5 | Linux 3.10.70, Marvell toolchain | `core`, `httpd`, `cli_server`, SNMP, routing, cloud |
| SX v2 2.0.0 | MIPS32r2 BE, uClibc | Linux 4.4.153, Realtek MSDK | Realtek Mango SDK + TP-Link services |
| ST5008 1.0.1 | MIPS32r2 BE, uClibc | Linux 3.18.24, Realtek MSDK | TP-Link CLI/HTTP/SSH/SNMP + switch SDK |
| ST5008F v2 1.2.0 | MIPS32r2 BE, uClibc | Linux 3.18.24, Realtek MSDK | TP-Link CLI/HTTP/SSH/SNMP + switch SDK |

- SquashFS = application tree, not the whole root. ST5008/ST5008F boot a separate initramfs that mounts the app partition, loads switch modules, starts a monitor/SCM process manager (CLI, HTTP, SSH).
- Serial console in siblings:
  - ST5008 1.0.1: `inittab` respawns `getty -L ttyS0 38400 vt100`; root password empty; `ttyS0` in `securetty`.
  - ST5008F v2 1.2.0: getty on `ttyS0`, default baud; root password empty.
  - SX v2 2.0.0: getty line commented out.
- Autoboot stop key: ST1008F stock = Esc at 115200; ST5008F v2 loader = Ctrl+B at 38400.
- `CONFIG_MAGIC_SYSRQ` is compiled in; no sysrq-enabling bootarg, no kgdb.

### Software base age

| | ST1008F stock | ST5008F v2 1.2.0 | OpenWrt 25.12.4 (same hardware) |
|---|---|---|---|
| Kernel | Linux 3.18.24, build #36, 2022-01-19 | Linux 3.18.24, build #3, 2026-05-06 | Linux 6.12.87 |
| Compiler | GCC 4.8.5 (20150209 prerelease, Realtek MSDK-4.8.5p1 Build 2536) | same | GCC 14.3 |
| libc | uClibc 0.9.33.2 | uClibc 0.9.33.2 | musl |
| U-Boot | 2011.12 | 2011.12 | — |
| Userspace base | BusyBox | Buildroot 2015.11.1 | OpenWrt |

- Linux 3.18 is EOL (no later 3.18.x patches pulled in); uClibc is unmaintained (succeeded by uClibc-ng).
- Cause: pinned to Realtek's RTL93xx SDK/MSDK toolchain.

### Management surfaces (managed siblings only)

| Firmware | Login surface | Evidence |
| --- | --- | --- |
| ST5008 | `/logon/LogonRpm.htm` | HTML form posts here |
| SX v2 | `/`, login module, `./data/login.json` | frontend assets; `auto_login.html` exists |
| ST5008F v2 | `/web/login`, `/stok=<token>/ds` | httpd strings, Vue frontend |

- Web assets: custom `OW`-magic bundle (ST5008 784 files, SX v2 836).
- `auto_login` asset name and `cli_consoleLogin` symbol are not authentication bypasses. ST5008F `access_telnet_directly=0` is a setting, not a listener measurement.
- The stock ST1008F image contains none of `httpd`, `cli_server`, `core`.

### OpenWrt comparison (upstream `d09134f6edeff8d445cb96ed3689f4d072a9666f`)

- ST1008F v2 DTS: RTL9303, 512 MiB, SFP cages, I2C, GPIO expander, mode-switch inputs, watchdog.
- SX v1 = Marvell ARM; irrelevant to RTL9303.
- SX v2, ST5008, ST5008F share the Realtek/MIPS SDK lineage (RTL9300/9303 SerDes, Mango VLAN/L2/port symbols).
- SX v2 `dal_mango_vlan_portIgrFilter_set` ↔ OpenWrt `rtl930x_set_igr_filter`; `dal_mango_port_rxEnable_set` dispatches via the vendor port driver (OpenWrt uses DSA/phylink). Functional comparison only.

## Related U-Boot images

| Model | Embedded U-Boot | Build date |
|---|---|---|
| ST5008 v1 | `2011.12.(3.6.9.55156)` | 2023-11-29 |
| ST5008F v2 | `2011.12.(3.6.9.55156)` | 2026-05-06 |
| SX3008F v2 | `2011.12.(4.0.2.55154)-c009c5be9` | 2026-05-25 |

- ST5008 and ST5008F loaders contain `RTL9303_8XGE`; ST5008F default env has `boardmodel=RTL9303_8XGE`. Not found in the SX3008F v2 tail.
- All three: `Enable network`, `Please wait for PHY init-time`, `rtl9300#0`, `rtk 10g PORT` help. ST loaders add `Init Switch Ethernet Driver`, `Unit %u NIC chip family: %x`.
- Loader starts in decoded containers: `0xe9a304` (ST5008), `0x100a3c4` (ST5008F); both begin with MIPS jump `0x0bf0117c` → `0x9fc045f0`.

### Stock vs ST5008F v2 loader (Ghidra)

| Image | Main text at loader offset | Linked at | Matching `jal` targets | Raw import base |
|---|---|---|---|---|
| ST1008F stock | `0x5080` | `0x83f00000` | 708 / 900 | `0x83efaf80` |
| ST5008F v2 | `0x5060` | `0x87f00000` | 773 / 1004 | `0x87efafa0` |

Projects (local only): `private/ghidra/stock-loader-mapped.gpr`, `private/ghidra/managed-loader.gpr`. Names prefixed `inferred_` are semantic labels, not recovered symbols.

| Role | Stock | ST5008F |
|---|---|---|
| `rtk` dispatcher | `0x83f1679c` | `0x87f223ec` |
| network-on | `0x83f199c4` | `0x87f235a0` |
| SDK init once | `0x83f14ef4` | `0x87f22018` |
| register eth device | `0x83f1f25c` | `0x87f2aeb8` |

- `RTL9303_8XGE` profile: `0x610` identical bytes from relative `0x54` (stock `0xa2c24`, managed `0x9d194`); differ from `0x664`.
- Network-on differs: stock enables every valid profile port via the per-port wrapper; managed selects one port per unit (preferred-port byte at offset `0xe` of a referenced struct, else first valid port) and calls three per-port ops.
- Managed extra ops use PHY callback slots `0x184`/`0x188`. In the stock PHY descriptor (`0x83fa3638`, driver `0x83e638e0`) both point to `0x83f3f0b4`, a stub returning `0xf030`; slot `0x1a8` (media select) is implemented.
- TX callbacks clear the tag-present bit in both; packet struct `0x54` bytes (stock) vs `0x58` (managed).

## Official sources

- [SX3008F firmware catalogue](https://support.omadanetworks.com/en/download/firmware/sx3008f/)
- [TL-SX3008F firmware catalogue](https://support.omadanetworks.com/en/download/firmware/tl-sx3008f/)
- [TL-ST5008F v2 update](https://resource.tp-link.com.cn/pc/docCenter/showDoc?id=1787121359784596)
- [TL-ST5008 v1 update](https://resource.tp-link.com.cn/pc/docCenter/showDoc?id=1707112849710707)
- [SX v1 GPL archive](https://static.tp-link.com/upload/gpl-code/2024/202412/20241206/SX3008F_GPL.tar.gz)
- [GPL model listing](https://www.tp-link.com/phppage/gpl-res-list.html?model=SX3008F&appPath=us)
- [OpenWrt TL-ST1008F v2 support commit](https://github.com/openwrt/openwrt/commit/39b9b491bb)
- [OpenWrt v2 DTS](https://github.com/openwrt/openwrt/blob/main/target/linux/realtek/dts/rtl9303_tplink_tl-st1008f-v2.dts)
- [NicGiga S100-0800S-M (same board profile)](https://openwrt.org/toh/nicgiga/s100-0800s-m)
- GPL U-Boot/SDK sources matching this loader: `github.com/reyalo/Realtek` (`sources/uboot-dms1250`, `sources/rtk-dms1250`, `sources/rtk-xgs1210`).
- Buildable SDK U-Boot: olliver's `realtek_sdk` on GitLab (`tplink_maple` branch).
