#!/usr/bin/env python3
"""Dump the LED part of a hw profile compiled into the stock loader (#9).

- Finds the profile by name string, follows hwp_hwProfile_t -> swDescp[0].
- swDescp layout from the stock decompile (hwp_led_cfg_validate 0x83f1b2ec,
  mac_led_config 0x83f6f768): ports at +0x14 stride 0x14 (mac_id +0, led_c +0xc,
  led_f +0xd, led_layout +0xe), led_if_sel +0x610, led_active +0x614,
  led_definition_set[4][5] at +0x618 (stride 0x14, 0xffffffff = end).

Usage: stock_led_profile.py <loader.bin> [PROFILE_NAME]   (default RTL9303_8XGE)
Log: tmp/logs/stock_led_profile.log
"""
import struct
import sys
from pathlib import Path

VA0, OFF0 = 0x83f00000, 0x5080  # loader.bin: VA 0x83f00000 at file offset 0x5080
PROFILE_LIST = 0x83f9348c
LOG = Path(__file__).resolve().parent.parent / "tmp/logs/stock_led_profile.log"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    blob = Path(sys.argv[1]).read_bytes()
    name = (sys.argv[2] if len(sys.argv) > 2 else "RTL9303_8XGE").encode() + b"\0"
    out: list[str] = []

    def va2off(va: int) -> int:
        return va - VA0 + OFF0

    def u32(va: int) -> int:
        return struct.unpack_from(">I", blob, va2off(va))[0]

    # Profile list (hw_profile_list_print 0x83f1bfa0): NULL-terminated pointers; profile
    # = {?, name[] @+4, id @+0x30, ..., sw_count @+0x38, swDescp[] @+0x3c}.
    ptr, prof = PROFILE_LIST, None
    while (pv := u32(ptr)) != 0:
        o = va2off(pv + 4)
        if blob[o:o + len(name)] == name:
            prof = pv
        ptr += 4
    if prof is None:
        print(f"profile {name[:-1].decode()} not in list @ {PROFILE_LIST:#x}")
        return 1
    out.append(f"profile {name[:-1].decode()} @ {prof:#x} id {u32(prof + 0x30):#x} "
               f"sw_count {u32(prof + 0x38)}")
    for sw in [u32(prof + 0x3c + 4 * i) for i in range(u32(prof + 0x38))]:
        out.append(f"swDescp @ {sw:#x}: chip_id {u32(sw):#010x}")
        for p in range(30):
            base = sw + 0x14 + p * 0x14
            mac = blob[va2off(base)]
            if mac == 0xff:
                break
            b = blob[va2off(base): va2off(base) + 0x14]
            out.append(f"  port {p}: mac {mac:2d} led_c {b[0xc]:#04x} led_f {b[0xd]:#04x} "
                       f"layout {b[0xe]:#04x} raw {b.hex()}")
        out.append(f"  led_if_sel {u32(sw + 0x610):#x} led_active {u32(sw + 0x614):#x}")
        for s in range(4):
            leds = [u32(sw + 0x618 + s * 0x14 + i * 4) for i in range(5)]
            out.append(f"  set{s}: " + " ".join(f"{v:#010x}" for v in leds))
    text = "\n".join(out)
    print(text)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    LOG.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
