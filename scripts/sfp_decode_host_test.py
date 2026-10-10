#!/usr/bin/env python3
"""sfp_decode_host_test — build the U-Boot SFP decoder (uboot-port/board/tplink/tl-st1008f/sfp/) on the host.

- Host shim headers stand in for U-Boot's; the decoder sources are compiled unmodified.
- `dump A0 [A2]`: print the decode of raw EEPROM dumps (A0 >= 96 B, A2 >= 120 B).
- `selftest`: external-calibration vectors (random constants) vs double math; fixed-point log/format checks.
Log: tmp/logs/sfp_decode_host_test.log
Usage: sfp_decode_host_test.py dump <a0.bin> [<a2.bin>] | selftest
"""

import math
import random
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "uboot-port/board/tplink/tl-st1008f/sfp"
WORK = ROOT / "tmp/sfp-host"
LOG = ROOT / "tmp/logs/sfp_decode_host_test.log"
CC_TIMEOUT_S = 10   # one gcc run of 3 small files: ~0.5 s, x20 for a loaded host

SHIM = {
    "linux/types.h": "#include <stdint.h>\n#include <stdbool.h>\n#include <string.h>\n"
                     "typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32; typedef uint64_t u64;\n"
                     "typedef int16_t s16; typedef int32_t s32; typedef int64_t s64;\n",
    "linux/string.h": "",
    "vsprintf.h": "#define putc(c) putchar(c)\n",
    "linux/bitops.h": "static inline int fls(unsigned int x) { return x ? 32 - __builtin_clz(x) : 0; }\n",
    "linux/kernel.h": "#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))\n",
}

DRIVER = r'''
#include "sff-common.c"
#include "sfpid.c"
#include "sfpdiag.c"
#include <stdlib.h>
int main(int argc, char **argv)
{
	static u8 a0[256], a2[256];
	FILE *f = fopen(argv[1], "rb");
	if (!f || !fread(a0, 1, 256, f)) return 2;
	fclose(f);
	if (argc > 2 && (f = fopen(argv[2], "rb"))) { fread(a2, 1, 256, f); fclose(f); }
	sff8079_show_all(a0);
	if (a0[92] & 0x40) sff8472_show_all(a0, a2);
	return 0;
}
'''


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(msg + "\n")
    print(msg, flush=True)


def build() -> Path:
    WORK.mkdir(parents=True, exist_ok=True)
    for rel, txt in SHIM.items():
        p = WORK / "shim" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt)
    drv = WORK / "driver.c"
    drv.write_text(DRIVER)
    exe = WORK / "sfp_host"
    cmd = ["gcc", "-Wall", "-Wextra", "-Wno-unused-parameter", "-O1", "-I", str(WORK / "shim"),
           "-I", str(SRC), str(drv), "-o", str(exe)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=CC_TIMEOUT_S)
    log(f"gcc rc={r.returncode}\n{r.stderr}")
    if r.returncode:
        sys.exit(1)
    return exe


def decode(exe: Path, a0: bytes, a2: bytes | None = None) -> str:
    (WORK / "a0.bin").write_bytes(a0)
    args = [str(exe), str(WORK / "a0.bin")]
    if a2 is not None:
        (WORK / "a2.bin").write_bytes(a2)
        args.append(str(WORK / "a2.bin"))
    return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout


def field(out: str, name: str) -> str | None:
    for ln in out.splitlines():
        k, _, v = ln.partition(":")
        if k.strip() == name:
            return v.strip()
    return None


def f32(x: float) -> bytes:
    return struct.pack(">f", x)


def selftest(exe: Path) -> int:
    rng = random.Random(1)
    bad = 0
    for n in range(200):
        a0 = bytearray(128)
        a0[0], a0[1], a0[2], a0[12] = 3, 4, 7, 0x67
        a0[92], a0[93] = 0x58, 0x00   # DDM, external cal, average rx power
        a2 = bytearray(128)
        c4, c3, c2, c1, c0 = (rng.uniform(-1, 1) * s for s in (1e-17, 1e-12, 1e-7, 0.6, 20))
        rx = rng.randrange(1, 65535)
        for off, v in ((56, c4), (60, c3), (64, c2), (68, c1), (72, c0)):
            a2[off:off + 4] = f32(v)
        slp = [rng.randrange(0x80, 0x300) for _ in range(4)]
        off = [rng.randrange(-200, 200) for _ in range(4)]
        for i, o in zip(range(4), (76, 80, 84, 88)):
            a2[o:o + 2] = struct.pack(">H", slp[i])
            a2[o + 2:o + 4] = struct.pack(">h", off[i])
        txi, txp, vcc, tmp = (rng.randrange(1, 60000), rng.randrange(1, 60000),
                              rng.randrange(1, 60000), rng.randrange(-20000, 20000))
        a2[96:98] = struct.pack(">h", tmp)
        a2[98:100] = struct.pack(">H", vcc)
        a2[100:102] = struct.pack(">H", txi)
        a2[102:104] = struct.pack(">H", txp)
        a2[104:106] = struct.pack(">H", rx)
        out = decode(exe, bytes(a0), bytes(a2))
        # reference: SFF-8472 formulas in double; coefficients rounded to binary32 as stored
        c = [struct.unpack(">f", f32(v))[0] for v in (c0, c1, c2, c3, c4)]
        rx_ref = max(0.0, sum(ci * rx ** k for k, ci in enumerate(c)))
        want = {
            "Receiver signal average optical power": rx_ref / 10000,
            "Laser output power": (txp * slp[1] // 256 + off[1]) / 10000,
            "Module voltage": (vcc * slp[3] // 256 + off[3]) / 10000,
            "Laser bias current": (txi * slp[0] // 256 + off[0]) * 2 / 1000,
        }
        for name, ref in want.items():
            v = field(out, name)
            val = float(v.split()[0]) if v else None
            # tolerance: 1 LSB of the printed value plus 1e-6 relative (binary32 summation order)
            tol = 1.5e-4 if "power" in name or name == "Module voltage" else 1.5e-3
            if val is None or abs(val - max(ref, 0)) > tol + 1e-6 * abs(ref):
                bad += 1
                log(f"MISMATCH {name}: got {val} want {ref:.6f} (rx={rx} c={c})")
        t_ref = (tmp * slp[2] // 256 if tmp >= 0 else -(-tmp * slp[2] // 256)) + off[2]
        val = float(field(out, "Module temperature").split()[0])
        if abs(val - t_ref / 256) > 0.006:
            bad += 1
            log(f"MISMATCH temperature: got {val} want {t_ref / 256:.4f}")
    # dBm: fixed-point log vs math.log10 over the full range
    for mw_raw in (1, 7, 100, 1000, 5000, 10000, 12345, 65535):
        a0 = bytearray(128)
        a0[0], a0[1], a0[92], a0[93] = 3, 4, 0x68, 0
        a2 = bytearray(128)
        a2[102:104] = struct.pack(">H", mw_raw)
        out = decode(exe, bytes(a0), bytes(a2))
        got = float(field(out, "Laser output power").split("/")[1].split()[0])
        want = 10 * math.log10(mw_raw / 10000)
        if abs(got - want) > 0.02:
            bad += 1
            log(f"MISMATCH dBm raw {mw_raw}: got {got} want {want:.3f}")
    log("PASS selftest" if not bad else f"FAIL selftest: {bad} mismatches")
    return 1 if bad else 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("dump", "selftest"):
        print(__doc__)
        return 2
    exe = build()
    if sys.argv[1] == "selftest":
        return selftest(exe)
    a0 = Path(sys.argv[2]).read_bytes()
    a2 = Path(sys.argv[3]).read_bytes() if len(sys.argv) > 3 else None
    log(decode(exe, a0, a2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
