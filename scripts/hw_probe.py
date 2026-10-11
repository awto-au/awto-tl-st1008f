#!/usr/bin/env python3
"""hw_probe — read-only presence probes of RTL9303 SoC blocks at the U-Boot prompt (#62).

- `md.l` of each block's ID/ctrl registers; no writes. Inventory: docs/HARDWARE-INVENTORY.md.
- Order: SoC core first, switch core next, gated IP blocks last (a hang there costs nothing earlier).
- Gated blocks (GDMA, crypto, SPI-NAND/ECC) are read only when their IP enable bit is set,
  or with `--gated` (a read of a clock-gated LX slave may hang the bus: SPEC).
- Skipped addresses (read side effects or not needed): SKIPPED below, printed at the end.
- Output: table on stdout, tmp/hw_probe-<label>.json, log tmp/logs/hw_probe.log.
- Run: `./dev.py hw-probe [--label L] [--gated]` at our prompt (stock `RTL9300#` also accepted).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/hw_probe.log"
PROMPT = r"\r?\n(?:RTL9300# |st1008f-mainline # )"
# md.l of <= 24 words = 6 lines (~420 chars) = 37 ms at 115200 + echo; 1 s names a hang/bus error
CAP_S = 1

# (group, block, addr, words, present-reads-as, absent-reads-as)
CORE = [
    ("sys", "SYS_REG CHIPID/RMR", 0xB8000000, 2, "nonzero id; RMR VERID [11:8]", "n/a (core)"),
    ("sys", "SSR soc_init_rdy", 0xB8000044, 1, "bit0 = 1; bit2 ckse_ocp0 = 1 (CPU on PLL)", "n/a"),
    ("sys", "BDSEL", 0xB800004C, 1, "strap/debug bits", "n/a"),
    ("bus", "OCP timeout monitor TO_CTRL/INTR/ADDR", 0xB8005100, 3, "bit31 TO_CTRL_EN", "0 = monitor off"),
    ("bus", "LX timeout monitor LBPSTCR/IR/MAR", 0xB8005200, 3, "bit31 LX_TCEN", "0 = monitor off"),
    ("ip", "IP_EN_CTRL", 0xB8000600, 1, "enable bits (decoded)", "-"),
    ("ip", "SYS_MISC_CTRL", 0xB800060C, 1, "bit31 HWRSTO_N", "-"),
    ("ip", "NEW_IP_EN_CTRL", 0xB800063C, 1, "enable bits (decoded)", "-"),
    ("ana", "USB_H_PHY/PCIE/USB3 ctrl", 0xB8000500, 3, "PHY ctrl bits", "0 (superset regs)"),
    ("ana", "SATA_CTRL", 0xB8000510, 1, "PHY ctrl bits", "0 (superset reg)"),
    ("sens", "SPD_SENSOR0-8 (speed/RO sensors)", 0xB8000618, 9, "reset values; counts need a start write", "0"),
    ("ddr", "MCR/DCR", 0xB8001000, 2, "MCR DRAM_TYPE [31:28] = 2 (DDR3); DCR 0x21421003", "n/a"),
    ("ddr", "UMSAR0-3 (unmapped segments)", 0xB8001300, 8, "bit0 enable per segment", "0"),
    ("ddr", "MEM_CACHE MCCCR..MCDDR1", 0xB8001600, 6, "ctrl values", "0"),
    ("spi", "SPI-NOR SFCR/SFCR2/SFCSR", 0xB8001200, 3, "SFCR2 [31:24] read cmd (0xbb = dual I/O)", "n/a"),
    ("uart", "UART0 IER", 0xB8002004, 1, "byte in [31:24]", "-"),
    ("uart", "UART0 LCR/MCR", 0xB800200C, 2, "LCR 0x03 = 8N1 (console)", "-"),
    ("uart", "UART1 IER", 0xB8002104, 1, "reset value", "bus error"),
    ("uart", "UART1 LCR/MCR", 0xB800210C, 2, "reset value (unused)", "bus error"),
    ("intc", "VPE0 GIMR", 0xB8003000, 1, "mask (0 at U-Boot: polled)", "-"),
    ("intc", "VPE0 IRR0-3", 0xB8003008, 4, "routing nibbles", "-"),
    ("intc", "VPE1 GIMR", 0xB8003018, 1, "mask", "-"),
    ("intc", "VPE1 IRR0-3", 0xB8003020, 4, "routing nibbles", "-"),
    ("timer", "TC0-TC5 DATA/CNT/CTRL/INTR", 0xB8003200, 24, "CTRL bit28 EN; TC5 = 6th set (DS says 5)", "TC5 0"),
    ("wdt", "WDTCNTRR/WDTINTRR/WDT_CTRL", 0xB8003260, 3, "WDT_CTRL bit31 WDT_E", "-"),
    ("gpio", "GPIO 0x3300 en/dir/dat/isr/imr", 0xB8003300, 7, "en 0x00ffffff", "-"),
    ("gpio", "GPIO 0x3338 IER", 0xB8003338, 2, "-", "-"),
    ("sram", "CPU_SRAM_SEG0-3 ADDR/SIZE/BASE", 0xB8004000, 16, "SEG0 0x1f000001 (stock map)", "0 = unmapped"),
    ("sram", "DSP_SRAM_SEG0-3 regs", 0xB8004040, 16, "superset (VoIP DSP)", "0"),
    ("rom", "ROMSAR/ROMSSR/ROMCR", 0xB8004080, 3, "bit0 ENROM", "0"),
    ("sram", "DORS0/DORS2/SCATS", 0xB8004090, 3, "-", "-"),
    ("usb", "EHCI CAPLENGTH+HCIVERSION, HCSPARAMS", 0xB8021000, 2, "LE 0x01000010 (md shows 10000001)", "bus error"),
    ("usb", "EHCI CONFIGFLAG/PORTSC1", 0xB8021050, 2, "PORTSC1 0x2000 seen (#5)", "bus error"),
]
SWITCH = [
    ("sw", "MODEL_NAME_INFO/CHIP_INFO", 0xBB000004, 2, "0x93030001; CHIP_INFO RL_ID needs an EN write (0 here)", "n/a"),
    ("rst", "RST_GLB_CTRL_0, STS_0 chip, STS_1 wdog, STS_2/3", 0xBB00000C, 5, "STS = reset-cause words", "-"),
    ("therm", "TM CTRL_0-2/RESULT_0-1", 0xBB000060, 5, "CTRL_2 bit16 TM_ENABLE; RESULT_0 bit24 valid", "-"),
    ("sds", "SDS_MODE_SEL_0/3", 0xBB000194, 2, "5-bit mode per SerDes", "-"),
    ("sds", "SDS_MODE_SEL_1/2", 0xBB0002A0, 2, "5-bit mode per SerDes", "-"),
    ("pinmux", "pinmux 0x200/0x204 (led sync, usb led, slv spi, uart1)", 0xBB000200, 2, "-", "-"),
    ("i2c", "I2C MST1 CTRL1/2, DATA0-3, GLB", 0xBB00036C, 7, "CTRL2 dev addr of last xfer", "-"),
    ("i2c", "I2C MST2 CTRL1/2, DATA0-3", 0xBB000388, 6, "reset values (MST2 unused)", "-"),
    ("spim", "SPI_CTRL1/2 (switch-core SPI master + pinmux)", 0xBB0003A0, 2, "-", "-"),
    ("smi", "SMI_GLB_CTRL/MAC_TYPE_CTRL", 0xBB00CA00, 2, "-", "-"),
    ("smi", "SMI_POLL_CTRL", 0xBB00CA90, 1, "poll mask", "-"),
    ("led", "LED_GLB_CTRL", 0xBB00CC00, 1, "[1:0] mode 1 = serial", "-"),
    ("nic", "DMA_IF_INTR_MSK", 0xBB00E010, 1, "-", "-"),
    ("nic", "DMA_IF_CTRL", 0xBB00E028, 1, "RX/TX enable bits", "-"),
    ("intr", "IMR_GLB", 0xBB00C628, 1, "-", "-"),
    ("mac", "MAC_L2_GLOBAL_CTRL0/1", 0xBB00C700, 2, "-", "-"),
    ("eee", "EEE_TX_CTRL", 0xBB00C72C, 1, "-", "-"),
    ("eee", "EEE_CTRL port 0", 0xBB003274, 1, "per-port EEE enables", "-"),
    ("oam", "OAM_CTRL", 0xBB00A120, 1, "-", "-"),
    ("oam", "OAM_GLB_DYING_GASP_CTRL/POLARITY", 0xBB00C7BC, 2, "-", "-"),
    ("efuse", "EFUSE_ACCESS_EN/CTRL", 0xBB00C698, 2, "access idle", "-"),
    ("l2", "L2_CTRL/L2_AGE_CTRL", 0xBB008FD8, 2, "-", "-"),
    ("l3", "L3_IP_ROUTE_CTRL/HOST_TBL_CTRL", 0xBB00AB44, 2, "-", "-"),
    ("acl", "ACL_CTRL", 0xBB00A494, 1, "-", "-"),
    ("meter", "METER_GLB_CTRL", 0xBB00A0A0, 1, "-", "-"),
    ("mirror", "MIR_CTRL", 0xBB00A2A0, 1, "-", "-"),
    ("sflow", "SFLOW_CTRL", 0xBB00BEA0, 1, "-", "-"),
    ("parser", "PARSER_CTRL", 0xBB00D724, 1, "-", "-"),
    ("ptp", "RMA_PORT_PTP_CTRL port 0 (trap only, no MAC PTP)", 0xBB009E88, 1, "-", "-"),
]
# (block, addr, words, gate); least certain last (LX0 0x144000: SDK only, no driver or DTS uses it)
GATED = [
    ("GDMA LX1 CTRL/IM/IS/ICVL", 0xB800A000, 4, "any GDMA enable bit"),
    ("GDMA LX2 CTRL/IM/IS/ICVL", 0xB8018000, 4, "any GDMA enable bit"),
    ("IPSEC/crypto SRC/DST desc, CMD_STS, CTRL", 0xB800C000, 4, "IP_EN_CTRL bit10 EN_IPSEC"),
    ("SPI-NAND SNFCFR/SNFCCR", 0xB801A400, 2, "NEW_IP_EN_CTRL bit4 EN_SPI_NAND"),
    ("ECC ECCFR", 0xB801A600, 1, "NEW_IP_EN_CTRL bit4 EN_SPI_NAND"),
    ("GDMA LX0 CTRL/IM/IS/ICVL", 0xB8144000, 4, "any GDMA enable bit"),
]
SKIPPED = [
    ("0xb8002000 / 0xb8002100", "UART0/1 RBR: read pops the RX FIFO"),
    ("0xb8002008 / 0xb8002108", "UART IIR: read clears a pending THRE interrupt"),
    ("0xb8002014 / 0xb8002114", "UART LSR: read clears overrun/parity/framing/break bits"),
    ("0xb8002018 / 0xb8002118", "UART MSR: read clears the delta bits"),
    ("0xb800120c", "SPI-NOR SFDR: read clocks the next data word"),
    ("0xb8003004 / 0xb800301c", "INTC GISR: pending status, not needed for presence"),
    ("0xbb00c658 / 0xbb00e01c", "switch ISR_GLB / NIC DMA_IF_INTR_STS: W1C status, not needed"),
    ("0xbb00c6a4", "EFUSE_RDATA: valid only after an access-trigger write"),
    ("0xbb000664 + 0x100*port", "MIB counters: clear-on-read depends on STAT_CTRL; not needed"),
    ("0xbb00cb10..", "MAC link status: latched bits"),
    ("0xbb0003b0..", "SerDes indirect access: needs a command write"),
    ("PCIe / SATA controllers", "no balls on RTL9303 (datasheet pin table); register base unknown"),
]
IP_EN_BITS = {31: "USBPHY1", 30: "USBPHY0", 15: "NANDFSH", 14: "NFBI", 13: "SATA", 12: "VOIPFFT",
              11: "VOIPACC", 10: "IPSEC", 9: "GDMA1", 8: "GDMA0", 7: "PCIE0", 6: "PCIE1",
              4: "P0USBHOST", 3: "P1USBHOST", 2: "PCM", 1: "GMAC", 0: "PREI_VOIP"}
NEW_IP_EN_BITS = {10: "GDMA6", 9: "GDMA5", 8: "GDMA4", 7: "GDMA3", 6: "GDMA2", 5: "WRAP_PBUF", 4: "SPI_NAND"}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def bits(v: int, names: dict[int, str]) -> str:
    return ",".join(n for b, n in sorted(names.items(), reverse=True) if v >> b & 1) or "none"


def verdict(words: list[int]) -> str:
    if all(w == 0xFFFFFFFF for w in words):
        return "all-ones (absent?)"
    if all(w == 0 for w in words):
        return "zero (reset value or absent)"
    return "nonzero (present)"


def md(con: Console, addr: int, n: int, name: str) -> list[int] | str:
    """Words read, or an error string (timeout / exception). An error ends the run: console state unknown."""
    try:
        _, txt = con.run(f"md.l {addr:x} {n:x}", PROMPT, CAP_S, name)
    except SystemExit as e:  # expect() raises on timeout and on an exception banner
        return f"ERROR: {e}"
    out = []
    for m in re.finditer(r"([0-9a-f]{8}):((?: [0-9a-f]{8})+)", txt):
        out += [int(w, 16) for w in m.group(2).split()]
    return out[:n] if len(out) >= n else f"ERROR: parsed {len(out)}/{n} words"


def run(label: str, gated: bool) -> int:
    con, res, rows = Console(), {}, []
    path = ROOT / f"tmp/hw_probe-{label}.json"

    def probe(group, block, addr, n, present, absent) -> bool:
        r = md(con, addr, n, block)
        ok = not isinstance(r, str)
        v = verdict(r) if ok else r
        res[f"{addr:08x}"] = {"block": block, "words": [f"{w:08x}" for w in r] if ok else [], "verdict": v}
        rows.append((group, block, f"{addr:08x}", " ".join(f"{w:08x}" for w in r[:4]) + (" .." if ok and n > 4 else "")
                     if ok else "-", v, present, absent))
        path.write_text(json.dumps(res, indent=1))  # saved per probe: a hang keeps what came before
        if not ok:
            log(f"STOP at {block} 0x{addr:08x}: {r}; recover with ./dev.py stock (power cycle)")
        return ok

    log(f"hw_probe {label}: {len(CORE) + len(SWITCH)} safe probes, {len(GATED)} gated ({'forced' if gated else 'if enabled'})")
    for p in CORE + SWITCH:
        if not probe(*p):
            return report(rows, 1)
    w = lambda a: int(res.get(f"{a:08x}", {}).get("words", ["0"])[0], 16)  # noqa: E731
    ip, new_ip, sram0 = w(0xB8000600), w(0xB800063C), w(0xB8004000)
    log(f"IP_EN_CTRL {ip:08x}: {bits(ip, IP_EN_BITS)}; NEW_IP_EN_CTRL {new_ip:08x}: {bits(new_ip, NEW_IP_EN_BITS)}")
    if sram0 & 1 and (sram0 & ~0xFF) == 0x1F000000:  # stock window: bus 0x1f000000 -> KSEG1 0xbf000000
        if not probe("sram", "SRAM data (stock window)", 0xBF000000, 4, "SPL code/data", "-"):
            return report(rows, 1)
    else:
        log(f"SRAM data not read: SEG0 {sram0:08x} is not the stock window (unmapped reads may bus-error)")
    enabled = {"any GDMA enable bit": bool(ip & 0x300 or new_ip & 0x7C0),
               "IP_EN_CTRL bit10 EN_IPSEC": bool(ip >> 10 & 1),
               "NEW_IP_EN_CTRL bit4 EN_SPI_NAND": bool(new_ip >> 4 & 1)}
    for block, addr, n, gate in GATED:
        if not (gated or enabled[gate]):
            rows.append(("gated", block, f"{addr:08x}", "-", f"not read: {gate} = 0", "-", "-"))
            continue
        if not probe("gated", block, addr, n, "nonzero ctrl or idle 0", "bus error / hang"):
            return report(rows, 1)
    return report(rows, 0)


def report(rows: list[tuple], rc: int) -> int:
    log("| group | block | addr | words | verdict | present reads as | absent reads as |")
    log("|---|---|---|---|---|---|---|")
    for r in rows:
        log("| " + " | ".join(r) + " |")
    log("Skipped (side effects / not needed):")
    for a, why in SKIPPED:
        log(f"  {a}: {why}")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--gated", action="store_true", help="also read gated blocks whose enable bit is 0 (may hang)")
    a = ap.parse_args()
    return run(a.label, a.gated)


if __name__ == "__main__":
    sys.exit(main())
