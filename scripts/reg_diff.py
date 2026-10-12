#!/usr/bin/env python3
"""reg_diff — dump register ranges at the current U-Boot prompt (stock or ours), diff two captures (#51).

- `capture <label>`: `md.l` each range in RANGES at the live prompt; saves tmp/reg_diff-<label>.json.
  Read-only; ranges are pinmux / GPIO / I2C blocks with no read side effects known.
- `compare <a> <b>`: per-word diff with field hints. Log: tmp/logs/reg_diff.log.
- Stock side: `./dev.py stock` (network on) first. Ours: `./dev.py ramload uboot-mainline --from-flash`.
- `--window`: the whole switch-core window 0xbb000000-0xbb00ffff (#80: stock network on vs ours, cold boot),
  in WINDOW_CHUNK-word `md.l` reads; `--skip A-B` leaves out a range (hex offsets) if a read misbehaves.
- `compare --sdk`: name each differing word and field from the SDK register list (sw_defaults_gen.load).
- `--serdes`: also MAC/SMI ranges (SERDES_RANGES) and `rtk sdsdump all` (ours prompt only: SerDes
  2-9, pages 0-7 + 0x1f-0x2f via the indirect path). Stock SerDes state = ours ramloaded after stock
  `rtk network on` (default ramload; ours does not reset the switch core). Latched/counter regs
  (page 1 errors, page 5 link) differ between reads: compare by eye.
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
    (0xBB00CC00, 4, "LED GLB 0xcc00, PORT_NUM 0xcc04/08, SET3_1 0xcc0c"),
    (0xB8003300, 7, "GPIO 0x3300: dir/data/int (otto-gpio)"),
    (0xB8003338, 2, "GPIO 0x3338: int status"),
]
# MAC side of the SerDes bring-up; read after `rtk network on` only (0xbb.. reads hung before, hardware.md)
SERDES_RANGES = [
    (0xBB000194, 2, "SDS_MODE_SEL_0/3 0x194/0x198"),
    (0xBB0002A0, 2, "SDS_MODE_SEL_1/2 0x2a0/0x2a4"),
    (0xBB00CA00, 5, "SMI GLB / MAC_TYPE 0xca04 / poll sel / private polling 0xca10"),
    (0xBB00CA1C, 29, "MAC_FORCE_MODE_CTRL ports 0-28"),
    (0xBB00CA90, 1, "SMI_POLL_CTRL 0xca90"),
    (0xBB00CB10, 4, "MAC link / speed status 0xcb10-0xcb1c"),
    # LED block written by stock mac_led_config (#9); 0xcc00-0xcc0c are in RANGES
    (0xBB00CC10, 7, "LED SET3_0..SET0_0 0xcc10-0xcc28"),
    (0xBB00CC2C, 4, "LED COPR/FIB_SET_SEL 0xcc2c-0xcc38"),
    (0xBB00CC3C, 4, "LED COPR/FIB/COMBO mask 0xcc3c-44, SW_LED_LOAD 0xcc48"),
    (0xBB00CC4C, 4, "LED_PORT_SW_EN 0xcc4c-0xcc58"),
    (0xBB00CC5C, 28, "LED_PORT_SW_CTRL ports 0-27 0xcc5c-0xccc8"),
]
WINDOW = (0xBB000000, 0x4000)  # switch core, 64 KiB = 16384 words
WINDOW_CHUNK = 0x100  # words per md.l: 64 lines (~3.5 KB) = 0.3 s at 115200; cap below
WINDOW_CAP = 1  # s per chunk: 3x the line time at 115200; a stuck read names its chunk
# 8 SerDes x 25 pages x ~170 chars = 34 KB at 115200 (11.5 KB/s) = 3 s; x1.25 + echo -> 5 s
SDSDUMP_CAP = 5


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def window_ranges(skip: list[str]) -> list[tuple[int, int, str]]:
    """WINDOW in WINDOW_CHUNK pieces minus the --skip ranges (switch-core offsets, hex)."""
    holes = [tuple(int(x, 16) for x in s.split("-")) for s in skip]
    out = []
    for off in range(0, WINDOW[1] * 4, WINDOW_CHUNK * 4):
        if any(lo <= off <= hi for lo, hi in holes):
            log(f"skip window chunk +0x{off:04x}")
            continue
        out.append((WINDOW[0] + off, WINDOW_CHUNK, f"window +0x{off:04x}"))
    return out


def capture(label: str, serdes: bool, window: bool = False, skip: list[str] | None = None) -> int:
    con, out = Console(), {}
    for start, words, name in (window_ranges(skip or []) if window else RANGES + (SERDES_RANGES if serdes else [])):
        # <= 29 words = 8 lines of md output (~550 chars): < 60 ms at 115200; 1 s names a hang
        _, txt = con.run(f"md.l {start:x} {words:x}", PROMPT, WINDOW_CAP, name)
        for m in re.finditer(r"([0-9a-f]{8}):((?: [0-9a-f]{8})+)", txt):
            base = int(m.group(1), 16)
            for i, w in enumerate(m.group(2).split()):
                out[f"{base + 4 * i:08x}"] = w
    if serdes:
        _, txt = con.run("rtk sdsdump all", r"\r?\nst1008f-mainline # ", SDSDUMP_CAP, "sdsdump")
        for m in re.finditer(r"sds (\d+) page 0x([0-9a-f]{2}):((?: (?:[0-9a-f]{4}|----)){32})", txt):
            for r, w in enumerate(m.group(3).split()):
                out[f"sds{int(m.group(1)):02d}.{m.group(2)}.{r:02x}"] = w
    path = ROOT / f"tmp/reg_diff-{label}.json"
    path.write_text(json.dumps(out, indent=1))
    log(f"captured {len(out)} words -> {path.name}")
    return 0


def sdk_names() -> dict[int, list[tuple[str, str, int]]]:
    """switch-core offset -> [(register[index], field, mask)] for every SDK register element."""
    import sw_defaults_gen as g
    regs, out = g.load(), {}
    for name, r in regs.items():
        i1s = range(r["p0"], r["p1"] + 1) if r["p1"] > r["p0"] or r["p0"] else [None]
        i2s = range(r["a0"], r["a1"] + 1) if r["a1"] > r["a0"] or r["a0"] else [None]
        for i1 in i1s:
            for i2 in i2s:
                for f in r["fields"]:
                    if f == "RESERVED":
                        continue
                    try:
                        addr, mask, _ = g.resolve(regs, name, f, i1, i2)
                    except (SystemExit, KeyError, ZeroDivisionError):
                        continue
                    idx = "".join(f"[{i}]" for i in (i1, i2) if i is not None)
                    out.setdefault(addr, []).append((name + idx, f, mask))
    return out


def compare(a: str, b: str, sdk: bool = False) -> int:
    ra, rb = (json.loads((ROOT / f"tmp/reg_diff-{x}.json").read_text()) for x in (a, b))
    names = {f"{s:08x}": n for s, _, n in RANGES}
    sdkmap = sdk_names() if sdk else {}
    diffs = 0
    for addr in sorted(set(ra) | set(rb)):
        va, vb = ra.get(addr, "-"), rb.get(addr, "-")
        if va != vb:
            diffs += 1
            x = f"{int(va, 16) ^ int(vb, 16):08x}" if "-" not in va + vb else "-"
            note = names.get(addr, "")
            if sdkmap and x != "-" and addr.startswith("bb"):
                hit = [f"{r}.{f}" for r, f, m in sdkmap.get(int(addr, 16) & 0xFFFF, []) if m & int(x, 16)]
                note = " ".join(hit) or "(no SDK field)"
            log(f"DIFF {addr}: {a} {va}  {b} {vb}  xor {x}  {note}")
    log(f"{diffs} differing words of {len(set(ra) | set(rb))}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    cap = sub.add_parser("capture")
    cap.add_argument("label")
    cap.add_argument("--serdes", action="store_true", help="MAC/SMI ranges + `rtk sdsdump all` (ours)")
    cap.add_argument("--window", action="store_true", help="whole switch-core window 0xbb000000-0xbb00ffff")
    cap.add_argument("--skip", action="append", default=[], help="window offsets to leave out, hex A-B")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--sdk", action="store_true", help="name differing fields from the SDK register list")
    a = ap.parse_args()
    if a.cmd == "capture":
        return capture(a.label, a.serdes, a.window, a.skip)
    return compare(a.a, a.b, a.sdk)


if __name__ == "__main__":
    sys.exit(main())
