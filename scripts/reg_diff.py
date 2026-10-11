#!/usr/bin/env python3
"""reg_diff — dump register ranges at the current U-Boot prompt (stock or ours), diff two captures (#51).

- `capture <label>`: `md.l` each range in RANGES at the live prompt; saves tmp/reg_diff-<label>.json.
  Read-only; ranges are pinmux / GPIO / I2C blocks with no read side effects known.
- `compare <a> <b>`: per-word diff with field hints. Log: tmp/logs/reg_diff.log.
- Stock side: `./dev.py stock` (network on) first. Ours: `./dev.py ramload uboot-mainline --from-flash`.
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
LOG = ROOT / "tmp/logs/reg_diff.log"
PROMPT = r"\r?\n(?:RTL9300# |st1008f-mainline # )"
# (start, words, name): pinmux per OpenWrt rtl930x.dtsi; I2C MST1/2 + GLB per i2c-rtl9300; GPIO block
RANGES = [
    (0xBB000200, 4, "pinmux 200/204 (led sync, usb led, slv spi, uart1)"),
    (0xBB00036C, 8, "I2C MST1 0x36c, MST2 0x378, GLB 0x384"),
    (0xBB0003A0, 4, "pinmux 3a0 (spi0, spi cs0 = GPIO7, cs1 = GPIO6)"),
    (0xBB00C600, 4, "pinmux c600 (gpio mdio)"),
    (0xBB00CC00, 4, "pinmux cc00 (sys led, led stack)"),
    (0xB8003300, 7, "GPIO 0x3300: dir/data/int (otto-gpio)"),
    (0xB8003338, 2, "GPIO 0x3338: int status"),
]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def capture(label: str) -> int:
    con, out = Console(), {}
    for start, words, name in RANGES:
        # <= 16 words = 4 lines of md output: < 30 ms at 115200; 1 s names a hang
        _, txt = con.run(f"md.l {start:x} {words:x}", PROMPT, 1, name)
        for m in re.finditer(r"([0-9a-f]{8}):((?: [0-9a-f]{8})+)", txt):
            base = int(m.group(1), 16)
            for i, w in enumerate(m.group(2).split()):
                out[f"{base + 4 * i:08x}"] = w
    path = ROOT / f"tmp/reg_diff-{label}.json"
    path.write_text(json.dumps(out, indent=1))
    log(f"captured {len(out)} words -> {path.name}")
    return 0


def compare(a: str, b: str) -> int:
    ra, rb = (json.loads((ROOT / f"tmp/reg_diff-{x}.json").read_text()) for x in (a, b))
    names = {f"{s:08x}": n for s, _, n in RANGES}
    diffs = 0
    for addr in sorted(set(ra) | set(rb)):
        va, vb = ra.get(addr, "-"), rb.get(addr, "-")
        if va != vb:
            diffs += 1
            x = f"{int(va, 16) ^ int(vb, 16):08x}" if "-" not in (va, vb) else "-"
            log(f"DIFF {addr}: {a} {va}  {b} {vb}  xor {x}  {names.get(addr, '')}")
    log(f"{diffs} differing words of {len(set(ra) | set(rb))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("capture").add_argument("label")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    a = ap.parse_args()
    return capture(a.label) if a.cmd == "capture" else compare(a.a, a.b)


if __name__ == "__main__":
    sys.exit(main())
