#!/usr/bin/env python3
"""power_rule_host_test — SFP declared-power rule on the host, kernel and U-Boot copies, against real EEPROM dumps (#30).

- Kernel: st_fixups[] / st_field_is() / st_power_mw() cut from openwrt/patches/300-06 (the '+' lines), built with gcc.
- U-Boot: shared/sfp-core sfp_fixup() + sfp_power_mw(), the calls rtk_sfp_power_mw() makes.
- Each EEPROM file (`ethtool -m <port> raw on` output) prints both results; they must agree, and --expect FILE=MW must hold.
Usage: power_rule_host_test.py [--expect tmp/eeprom-lan3.bin=3000 ...] EEPROM...
Log: tmp/logs/power_rule_host_test.log
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATCH = ROOT / "openwrt/patches/300-06-realtek-rtl930x-tplink-mode-switch.patch"
WORK = ROOT / "tmp/power_rule_host_test"

SHIM = """#include <stdio.h>
#include <string.h>
#include <stdbool.h>
typedef unsigned char u8;
#define BIT(n) (1u << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
"""

MAIN = r"""
#include "sfp_core.h"
int main(int argc, char **argv)
{
	for (int a = 1; a < argc; a++) {
		u8 buf[ST_EEPROM_LEN] = {0}, fx[96];
		const char *wk, *wu;
		FILE *f = fopen(argv[a], "rb");
		size_t n = f ? fread(buf, 1, sizeof(buf), f) : 0;

		if (f)
			fclose(f);
		if (n < 96) {
			printf("%s ERR short read %zu\n", argv[a], n);
			continue;
		}
		unsigned int k = st_power_mw(buf, &wk);
		memcpy(fx, buf, 96);
		int fixed = sfp_fixup(fx, 96);
		int u = sfp_power_mw(fx, 96, &wu);
		printf("%s kernel=%u(%s) uboot=%d(%s%s) pn=%.16s\n", argv[a], k, wk, u, wu, fixed ? ", quirk" : "", buf + 40);
	}
	return 0;
}
"""


def kernel_src() -> str:
    lines = [l[1:] for l in PATCH.read_text().splitlines() if l.startswith("+") and not l.startswith("+++")]
    src = "\n".join(lines)
    want = []
    for pat in (r"#define ST_EEPROM_LEN[^\n]*", r"#define ST_CU_\w+_MW[^\n]*"):
        want += re.findall(pat, src)
    start = src.index("/* Linux sfp_quirks[] fixups that rewrite the ID")
    end = src.index("static unsigned int st_power_total")
    return "\n".join(want) + "\n" + src[start:end]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("eeprom", nargs="+")
    ap.add_argument("--expect", action="append", default=[], help="FILE=MW")
    a = ap.parse_args()
    WORK.mkdir(parents=True, exist_ok=True)
    (WORK / "t.c").write_text(SHIM + kernel_src() + MAIN)
    exe = WORK / "t"
    cc = subprocess.run(["gcc", "-O1", "-Wall", "-Wno-unused-function", "-I", str(ROOT / "shared/sfp-core"),
                         "-o", str(exe), str(WORK / "t.c"), str(ROOT / "shared/sfp-core/sfp_core.c")],
                        capture_output=True, text=True)
    log = (ROOT / "tmp/logs/power_rule_host_test.log").open("a")
    if cc.returncode:
        print(cc.stderr)
        log.write(cc.stderr)
        return 2
    out = subprocess.run([str(exe), *a.eeprom], capture_output=True, text=True).stdout
    print(out, end="")
    log.write(out)
    bad = 0
    exp = dict(e.split("=", 1) for e in a.expect)
    for line in out.splitlines():
        m = re.match(r"(\S+) kernel=(\d+)\(.*?\) uboot=(\d+)", line)
        if not m:
            bad += 1
            continue
        if m.group(2) != m.group(3):
            print(f"MISMATCH kernel vs uboot: {line}")
            bad += 1
        if m.group(1) in exp and m.group(2) != exp[m.group(1)]:
            print(f"FAIL {m.group(1)}: {m.group(2)} mW, expected {exp[m.group(1)]}")
            bad += 1
    print("PASS" if not bad else f"FAIL ({bad})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
