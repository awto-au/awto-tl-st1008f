#!/usr/bin/env python3
"""Extract board/chip values from the TL-ST5008F v2 1.2.0 managed firmware vs stock ST1008F (#79).

Static only: parses XML and ELF data, never runs vendor code. Run with `python3 -I`.
- boardInfo.xml: GPIO list, pinmux writes, LED register writes (decoded per field from the SDK
  `swcore_rtl9300.h`), SFP TX-disable / ABS / EEPROM wiring, per-cage SerDes TX eye params.
- `core` + both `rtcore.ko` + stock `rtk.ko`: rxCaliConf myParam, rtl9303_80G txParam tables,
  RTL9303_8XGE hw-profile LED set (relocations resolved for the .ko files).
Out: tmp/st5008f/board_values.json. Log: tmp/logs/st5008f_board_values.log.
Usage: python3 -I scripts/st5008f_board_values.py
"""
import json
import re
import struct
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from elftools.elf.elffile import ELFFile
from elftools.elf.relocation import RelocationSection

ROOT = Path(__file__).resolve().parent.parent
X = ROOT / "private/china/st5008f-v2-extracted"
CORE = X / "rootfs/usrImage/app/sbin/core"
BOARD_XML = X / "rootfs/usrImage/data/boardInfo.xml"
KO_5008 = X / "initramfs/lib/modules/3.18.24/kernel/drivers/net/switch/rtcore/rtcore.ko"
STOCK = ROOT / "private/mtd-backup-20261008-145913/stock-extract/initramfs-1/lib/modules/3.18.24/kernel/drivers/net/switch"
KO_1008 = STOCK / "rtcore/rtcore.ko"
RTK_1008 = STOCK / "rtk/rtk.ko"
SWCORE_H = ROOT / "private/reyalo-Realtek/sources/rtk-xgs1210/system/include/private/drv/swcore/swcore_rtl9300.h"
OUT = ROOT / "tmp/st5008f/board_values.json"
LOG = ROOT / "tmp/logs/st5008f_board_values.log"

TXPARAM = [f"rtl9303_80G_txParam_s{i}" for i in range(2, 10)] + [f"rtl9303_80G_dac_txParam_s{i}" for i in range(2, 10)]
RXCALI = ["rtl9300_rxCaliConf_serdes_myParam", "rtl9300_rxCaliConf_phy_myParam"]
EYE = ["impedance", "pre_amp", "main_amp", "post_amp", "post2_amp", "pre_en", "post_en", "post2_en", "main_en"]


def log(msg, fh):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    fh.write(line + "\n")


def swcore_fields():
    """addr -> (reg name, [(field, offset, width)]) for non-array registers of swcore_rtl9300.h."""
    regs, cur = {}, None
    for line in SWCORE_H.read_text(errors="replace").splitlines():
        m = re.match(r"#define RTL9300_(\w+)_ADDR(\(port\))?\s+\((0x[0-9A-Fa-f]+)", line)
        if m:
            cur = m.group(1)
            regs[int(m.group(3), 16)] = (cur, [])
            continue
        m = re.match(r"\s+#define RTL9300_(\w+)_OFFSET(\(port\))?\s+(\(.*\))\s*$", line)
        if m and cur and m.group(1).startswith(cur + "_"):
            # per-port arrays: decode the port-0 field (offset expression evaluated with port = 0)
            off = eval(m.group(3), {"__builtins__": {}}, {"port": 0}) if m.group(2) else int(m.group(3).strip("()"))
            regs[max(a for a, v in regs.items() if v[0] == cur)][1].append([m.group(1)[len(cur) + 1:], off, None])
            continue
        m = re.match(r"\s+#define RTL9300_(\w+)_MASK(\(port\))?\s+\((0x[0-9A-Fa-f]+) <<", line)
        if m and cur and m.group(1).startswith(cur + "_"):
            flds = regs[max(a for a, v in regs.items() if v[0] == cur)][1]
            if flds and flds[-1][0] == m.group(1)[len(cur) + 1:]:
                flds[-1][2] = int(m.group(3), 16)
    return regs


def decode_write(regs, addr, mask, value):
    """Fields of a masked register write (port-0 layout for per-port arrays)."""
    name, flds = regs.get(addr & 0xffff, ("?", []))
    out = {}
    for f, off, w in flds:
        fm = (w or 0) << off
        if fm & mask:
            out[f] = (value & fm) >> off
    return name, out


def board_xml(regs):
    text = BOARD_XML.read_text(encoding="utf-8")
    board = ET.fromstring("<r>" + text.split("?>", 1)[1] + "</r>").find("TL_ST5008F_V2")
    res = {"gpio": [g.attrib for g in board.find("gpio/gpio_list")],
           "pinmux": [], "led_regs": [], "sfp_txdis": [], "sfp_abs": [], "sfp_eeprom": [], "sfp_param": [],
           "i2c": [i.attrib for i in board.find("i2c/i2cList")],
           "ports": [p.attrib for p in board.find("port/portInfo_list")],
           "pattern_groups": [g.attrib for g in board.find("sfp/sfpp_pattern_group")],
           "sysled": board.find("led/sysLed_good").attrib,
           "usb_micro": {c.tag: c.attrib for c in board.find("usb/usb_micro")},
           "phy_rxcali_en": board.find("chip/phy_rxcali_en").attrib["value"],
           "portLed_select": board.find("chip/portLed_ctrl/portLed_select").attrib}
    for r in board.find("gpio/mutiplex_mode_reg_list"):
        a, m, v = (int(r.attrib[k], 16) for k in ("reg", "mask", "value"))
        res["pinmux"].append({"reg": hex(a), "mask": hex(m), "value": hex(v), "decoded": decode_write(regs, a, m, v)})
    for r in board.find("chip/portLed_ctrl/led_reg_list"):
        a, m, v = (int(r.attrib[k], 16) for k in ("reg", "mask", "value"))
        res["led_regs"].append({"reg": hex(a), "mask": hex(m), "value": hex(v), "decoded": decode_write(regs, a, m, v)})
    for tag, key in (("sfp/sfp_txDis_list", "sfp_txdis"), ("sfp/sfp_abs_list", "sfp_abs"), ("sfp/sfp_eeprom", "sfp_eeprom")):
        res[key] = [e.attrib for e in board.find(tag)]
    for p in board.find("sfp/sfp_param_list"):
        for lane in p:
            res["sfp_param"].append({
                "cage": int(p.tag.split("_")[-1]) + 1, "speed": lane.attrib["speed"],
                "fiber": dict(zip(EYE, map(int, lane.attrib["param_fiber"].split(",")))),
                "copper": dict(zip(EYE, map(int, lane.attrib["param_copper"].split(","))))})
    return res


class Elf:
    def __init__(self, path):
        self.f = open(path, "rb")
        self.e = ELFFile(self.f)
        st = self.e.get_section_by_name(".symtab") or self.e.get_section_by_name(".dynsym")
        self.syms = list(st.iter_symbols())
        self.rel = {}
        for s in self.e.iter_sections():
            if isinstance(s, RelocationSection) and self.e.get_section(s["sh_info"]).name == ".data":
                for r in s.iter_relocations():
                    self.rel[r["r_offset"]] = self.syms[r["r_info_sym"]]

    def sym_bytes(self, name, size=None):
        for s in self.syms:
            if s.name == name and s["st_shndx"] not in ("SHN_UNDEF", "SHN_ABS", "SHN_COMMON"):
                sec = self.e.get_section(s["st_shndx"])
                if self.e["e_type"] == "ET_REL":
                    off = sec["sh_offset"] + s["st_value"]
                else:
                    off = sec["sh_offset"] + s["st_value"] - sec["sh_addr"]
                self.f.seek(off)
                return self.f.read(size or s["st_size"])
        return None

    def ko_profile_leds(self, name=b"RTL9303_8XGE"):
        """.ko only: profile list -> named profile -> swDescp; LED words around +0x600."""
        data = self.e.get_section_by_name(".data")
        self.f.seek(data["sh_offset"])
        d = self.f.read(data["sh_size"])
        lst = [s for s in self.syms if s.name == "hwp_hwProfile_list"][0]["st_value"]

        def deref(off):
            sy = self.rel[off]
            return sy["st_value"] + struct.unpack_from(">I", d, off)[0]
        o = lst
        while o in self.rel:
            po = deref(o)
            if d[po + 4:po + 4 + len(name) + 1] == name + b"\0":
                sw = deref(po + 0x3c)
                words = struct.unpack_from(">48I", d, sw + 0x600)
                return {"swDescp_off": hex(sw), "words_0x600": [hex(w) for w in words]}
            o += 4
        return None


def eye(b):
    v = struct.unpack(">7I", b[:28])
    return {"valid": v[0], "impedance": v[1], "pre_amp": v[2], "main_amp": v[3], "post_amp": v[4], "pre_en": v[5], "post_en": v[6]}


def rxcali(b):
    v = struct.unpack(">I4H", b[:12])
    return dict(zip(["dacLongCableOffset", "tap0_init_val", "vth_min", "eqHoldEnable", "dfeTap1_4Enable"], v))


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("w") as fh:
        regs = swcore_fields()
        res = {"boardInfo": board_xml(regs)}
        bins = {"st5008f_core": CORE, "st1008f_rtk_ko": RTK_1008}
        for k, p in bins.items():
            el = Elf(p)
            res[k] = {n: rxcali(b) for n in RXCALI if (b := el.sym_bytes(n, 12))}
            res[k].update({n: eye(b) for n in TXPARAM if (b := el.sym_bytes(n, 0x2c))})
            log(f"{k}: {len(res[k])} symbols", fh)
        for k, p in {"st5008f_rtcore_ko": KO_5008, "st1008f_rtcore_ko": KO_1008}.items():
            res[k] = Elf(p).ko_profile_leds()
        OUT.write_text(json.dumps(res, indent=1, default=str))
        b = res["boardInfo"]
        for w in b["pinmux"] + b["led_regs"]:
            log(f"write {w['reg']} mask {w['mask']} val {w['value']} -> {w['decoded']}", fh)
        for p in b["sfp_param"]:
            log(f"cage {p['cage']} fiber {p['fiber']} copper {p['copper']}", fh)
        for k in bins:
            for n, v in res[k].items():
                log(f"{k} {n} {v}", fh)
        for k in ("st5008f_rtcore_ko", "st1008f_rtcore_ko"):
            log(f"{k} 8XGE swDescp LED words @+0x600: {res[k]}", fh)
        log(f"wrote {OUT}", fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
