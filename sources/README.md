# sources

Downloaded vendor documents. `*.pdf` is gitignored; this manifest is tracked.

## rtl9303-cg-brief.pdf
- URL: https://www.svanheule.net/switches/_media/software/rtl9303-cg-layer-3-managed-8-10g-port-switch-controller.pdf
- Revision: RTL9303-CG datasheet Rev. 1.1-1, 2018-09-05, Track ID JATR-8275-15 (marked confidential, mirrored by svanheule.net).
- Good copy: 55 pages; contains "6.10. USB Interface" with `DM F4` and `DP G4`.

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
