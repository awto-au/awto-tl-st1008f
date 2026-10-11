# sources

Downloaded vendor documents. `*.pdf` is gitignored; this manifest is tracked.

## rtl9303-cg-brief.pdf
- URL: https://www.svanheule.net/switches/_media/software/rtl9303-cg-layer-3-managed-8-10g-port-switch-controller.pdf
- Revision: RTL9303-CG datasheet Rev. 1.1-1, Track ID JATR-8275-15 (marked confidential, mirrored by svanheule.net). Cover date 29 June 2018; revision history dates 1.1-1 2018/9/5.
- Good copy: 55 pages, 2,565,291 bytes; contains "6.10. USB Interface" with `DM F4` and `DP G4`.
- Newest public revision (doc hunt 2026-10-11): the tomocha.net, jameywine/realtek-doc, VerifyL and CSDN copies are byte-identical. Anoatech and pdfcoffee hold watermarked 10-page excerpts. No errata found.

## RTL930x family and RTL931x comparison documents (doc hunt 2026-10-11)

Base `JW` = `https://raw.githubusercontent.com/jameywine/realtek-doc/main/datasheets/` (mirrors: `youngfunchina/realtek-switch-doc`, `VerifyL/realtek-doc`). All fetched with playwrong `pdf`. Feature audit: `docs/DATASHEET-AUDIT.md`.

| File | Revision | URL | Good copy: pages, bytes, must contain |
|---|---|---|---|
| `rtl9301-cg-datasheet-rev1.1.pdf` | RTL9301-CG Rev 1.1-1, 29 June 2018, JATR-8275-15 (same family as the RTL9303 DS; adds §7.24 Stacking, QSGMII/RXAUI+/XSGMII) | https://www.svanheule.net/switches/_media/software/rtl9301-cg-layer-3-managed-24x10-100-1000m_4x10g_port_switch_controller.pdf | 71, 3,083,541, `LAYER 3 MANAGED 24*10/100/1000M + 4*10G` |
| `rtl9301-design-guide-v0.1.pdf` | RTL9301 hardware design guide Rev 0.1, 2017-11-27 | `JW` `RTL9301%20Design%20Guide%200.1.pdf` | 21, 923,648, `DESIGN GUIDE` |
| `rtl9301-power-consumption-v1.0.pdf` | Rev 1.0, 2017-02-24 | `JW` `RTL9301%20Power%20Consumption%201.0.pdf` | 5, 183,296, `Power Consumption` |
| `rtl930x-power-sequence-note-v1.0.pdf` | RTL930x family, Rev 1.0, 2017-01 | `JW` `RTL930x%20Power%20Sequence%20Note%201.0.pdf` | 6, 333,824, `Power Sequence` |
| `rtl9300-led-app-note-v1.0.pdf` | RTL9300 LED application note V1.0, 2017-04-21 (register level) | `JW` `RTL9300_LED_Application_Note_V1.0.pdf` | 26, 2,544,640, `LED_GLB_CTRL` |
| `rtl9302d-cg-datasheet-excerpt-anoatech.pdf` | RTL9302D-CG excerpt, no revision, watermarked | https://www.anoatech.com/wp-content/uploads/2026/01/RTL9302D-CG_Datasheet.pdf | 10, 1,523,265, `24-port 2.5G and 2-port 10G` |
| `rtl9302d-reference-schematic-anoatech.pdf` | RTL9302D, one schematic sheet (flash, crystal, SoC) | https://www.anoatech.com/wp-content/uploads/2026/01/RTL9302D%E5%8E%9F%E7%90%86%E5%9B%BE.pdf | 1, 167,693, `9300_SPI_CS0` |
| `rtl9311-cg-datasheet-draft0.5.pdf` | RTL9311-CG draft 0.5, 2018-07-05 | https://www.svanheule.net/switches/_media/software/rtl9311-cg_datasheet_draft_0.5.pdf | 69, 3,910,548, `LAYER 3 STACKABLE 48*10/100/1000M + 6*10G` |
| `rtl9313-cg-datasheet.pdf` | RTL9313-CG Rev 0.5, 2019-10-14 | `JW` `RTL9313-CG.pdf` | 69, 5,980,402, `LAYER 3 STACKABLE 12*10G PORT SWITCH CONTROLLER` |
| `rtl9310-register-file-v1.0.pdf` | RTL9310 Register Reference File v1.0 (2018). Mango, not Longan: names often match, addresses differ | `JW` `RTL9310_RegisterFile_v1.0.pdf` | 1640, 6,019,072, `Register Reference File` |
| `rtl9310-developer-guide-v1.0.pdf` | RTL9310 Developer Guide Rev 1.00. §11.1 NIC: `DMA_IF_CTRL`/`DMA_IF_PKT_CTRL` match the RTL9300 SDK bit for bit | `JW` `RTL9310_Developer_Guide_V1.0.pdf` | 316, 4,562,944, `Developer Guide` |
| `rtl9310-architecture-overview-v1.0.pdf` | RTL9310 Architecture Overview v1.0 | `JW` `RTL9310_Architecture_Overview_V1.0.pdf` | 453, 6,299,648, `Architecture` |
| `rtl9310-cpu-memctrl-peripherals-v1.0.pdf` | RTL9310 CPU / memory controller / peripherals v1.0 (closest analogue to the RTL9300 SoC block) | https://raw.githubusercontent.com/VerifyL/realtek-doc/main/RTL9310-CPU-MemoryController-Peripherals-Datasheet_v1.0.pdf | 78, 5,899,264, `Peripherals` |

Searched, not found (2026-10-11):
- No RTL9300 (Longan) register file, developer guide or SDK API guide.
- No RTL9302A/B/C datasheet.
- No RTL9303 revision other than 1.1-1.
- No errata.
- No full RTL9303 reference/demo schematic.
- No product-brief PDF on realtek.com.

Where we looked:
- jameywine/youngfunchina/VerifyL repos;
- svanheule media;
- tomocha;
- `gh search code|repos`;
- alldatasheet, datasheet4u, eeworld;
- OpenWrt wiki;
- CSDN/gitcode (the 9310 zip is login-gated);
- anoatech (RTL9302B/C URLs 404).

The register substitute is the GPL SDK table `rtk_longan_reg_list.c` (`scripts/sdk_regdump.py`) and the svanheule.net/realtek/longan register browser built from it.

Exist, not downloaded:
- jameywine: RTL9311R draft 0.1, RTL9311/RTL9311BM design guides 0.3, RTL9310 GPIO/I2C/LED/SPI app notes;
- PHY datasheets: RTL8261N, RTL8221B, RTL8238B;
- RTL838x/839x datasheets and developer guides;
- anoatech RTL9313 excerpt;
- mensi.ch `rtl93xx_patching.html` (SerDes patch sequence).

## zentel-a3t4gf40bbf-ddr3-4gb-v06.pdf
- URL: http://zentel-japan.com/BeDownloadFiles/DSA3T4GF340BBFF.06.pdf
- Revision: Zentel Japan Doc. No. DSA3T4GF340BBFF.06, "4Gb DDR3/DDR3L SDRAM Specification", A3T4GF30BBF/A3T4GF40BBF, Rev. 06, 2021-09-02. Covers the board's DRAM, A3T4GF40BBF-HP (DDR3-1866 13-13-13, 1.35 V, 1.5 V backward compatible).
- Good copy: 49 pages, 1,223,759 bytes; contains "4.25 Standard Speed Bins" (p.15) with "CL=13 CWL= 9" and the 1333/1600 AC table (p.17) with "tFAW (x16)" 45 / 40 ns.

## W25Q256JV_revG.pdf
- URL: https://www.winbond.com/resource-files/w25q256jv%20spi%20revg%2008032017.pdf
- Revision: W25Q256JV, Publication Release Date August 03, 2017 (Rev G).
- Good copy: 92 pages; contains "Clock frequency for Read Data instruction (03h)" (50 MHz) and "133MHz Standard/Dual/Quad SPI clocks". The board's flash is JEDEC EF4019 (JV/FV class); die variant not confirmed.

## Web references (live pages, not downloaded)

Carried over from the retired `awto-st1008f` notes repo (2026-08-18).

| Topic | URL | Notes |
|---|---|---|
| Review + teardown (v1) | https://www.servethehome.com/cheapest-10gbe-8-port-switch-tp-link-tl-st1008f-review/ | 2022-06-26; internal photos, RTL9303 ID, power draw. v1 unit |
| Hardware wiki (v2) | https://techinfodepot.shoutwiki.com/wiki/TP-LINK_TL-ST1008F_v2 | component inventory, serial/JTAG, U-Boot flash walkthrough |
| OpenWrt device page | https://openwrt.org/inbox/toh/tp-link/tl-st1008f_1.0 | ToH entry |
| RTL93xx SoC notes | https://www.svanheule.net/switches/rtl93xx | clock/bus/memory map, register layout |
| Installation manual | https://www.manualslib.com/manual/3622336/Tp-Link-Tl-St1008f.html | not downloaded |

## busybox/busybox-mips
- URL: https://busybox.net/downloads/binaries/1.31.0-defconfig-multiarch-musl/busybox-mips
- Revision: BusyBox 1.31.0 defconfig, static musl, ELF32 MSB MIPS-I o32 (busybox.net multiarch build, 2019-06-10). Used by `scripts/mainline_initramfs.py`.
- Good copy: 1,629,084 bytes, sha256 `c3fed048a70d5529f95820c5abb77553efc276a89a8608414ca03e53d6bedd1d` (checked by the script). Gitignored; fetch with playwrong's download tool.

## openwrt-24.10.7-ipk/
- URL base: https://downloads.openwrt.org/releases/24.10.7/ (`packages/mips_24kc/{base,packages}/`, `targets/realtek/rtl930x/packages/`).
- Revision: OpenWrt 24.10.7 (2026-05-31), arch `mips_24kc` (the 24.10 realtek/rtl930x arch), musl 1.2.5. Packages: libc, libgcc1, libatomic1, libmnl0, libnftnl11, nftables-nojson 1.1.1, zlib, libelf1, libbpf1, libnl-tiny1, tc-tiny 6.11.0, ip-full 6.11.0, ethtool 6.11, libiperf3 + iperf3 3.17.1, dropbear 2024.86-r2 (`targets/realtek/rtl930x/packages/`).
- `Packages-base`, `Packages-target`: feed indexes (`packages/mips_24kc/base/Packages`, `targets/realtek/rtl930x/packages/Packages`), fetched 2026-10-12 to pin versions/sha256. Good copy: plain text starting `Package: `.
- Good copy: sha256 per file pinned in `scripts/initramfs_tools.py` (from the feed `Packages` index; libc/libgcc1 also match `targets/realtek/rtl930x/sha256sums`). Each `.ipk` is a gzip tar holding `data.tar.gz`. Gitignored; the script fetches missing files with `playwrong --pdf`.
