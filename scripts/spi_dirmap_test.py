#!/usr/bin/env python3
"""spi_dirmap_test — A/B the SPI-NOR read path under the mainline kernel (#61): PIO vs mmio window.

- Needs the initramfs shell (`./dev.py ramload mainline-kernel`); read-only (dd from /dev/mtdN).
- Per mode of /sys/module/spi_realtek_rtl/parameters/dirmap (0 PIO, 2 cached window, 1 uncached):
  time `dd` of the partition to /dev/null, then md5sum it.
- PASS: dirmap active at probe (driver dev_info line), equal md5 in every mode, cached faster than PIO.
- Log: tmp/logs/spi_dirmap_test.log
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import st1008_ramload as rl  # noqa: E402

rl.LOG = Path(__file__).resolve().parent.parent / "tmp/logs/spi_dirmap_test.log"
P = r"st1008f-linux # "
PARAM = "/sys/module/spi_realtek_rtl/parameters/dirmap"
# Read-time cap per pass: slowest expected path = PIO at stock SCK 25.5 MHz; U-Boot's PIO
# `sf read` measured ~1.5 MB/s (docs/UBOOT-MAINLINE.md). md5sum adds CPU time (floor 10 MB/s).
FLOOR_READ, FLOOR_MD5 = 1.5e6, 10e6


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--part", default="firmware", help="MTD partition name (default firmware)")
    ap.add_argument("--modes", default="0,2,1", help="dirmap modes in order (default 0,2,1)")
    a = ap.parse_args()
    con = rl.Console()
    con.note("interactive-begin")
    try:
        con.run("", P, 2, "shell prompt")
        con.run("dmesg -n 1", P, 1, "console loglevel 1")  # keep kernel lines out of the replies
        con.run(f"D={PARAM}", P, 1, "param path")  # short lines: ash wraps past 80 cols, breaks echo checks
        _, out = con.run(f"grep '\"{a.part}\"' /proc/mtd", rf"(mtd\d+): ([0-9a-f]+) .*\r?\n{P}", 2,
                         f"/proc/mtd {a.part}")
        m = re.search(r"(mtd\d+): ([0-9a-f]+) ", out)
        dev, size = f"/dev/{m.group(1)}", int(m.group(2), 16)
        rl.log(f"{a.part} = {dev}, {size} B")
        _, out = con.run("dmesg | grep dirmap", P, 2, "driver dirmap line")
        active = "via window" in out
        rl.log("dirmap at probe: " + ("ACTIVE" if active else "NOT active") + " | " +
               " / ".join(l.strip() for l in out.splitlines() if "dirmap" in l and "grep" not in l))
        cap_read = 1.25 * size / FLOOR_READ + 2
        cap_md5 = 1.25 * size * (1 / FLOOR_READ + 1 / FLOOR_MD5) + 2
        res = {}
        for mode in (int(x) for x in a.modes.split(",")):
            con.run(f"echo {mode} >$D; cat $D", rf"\n{mode}\r?\n{P}", 1, f"dirmap={mode}")
            _, out = con.run(f"dd if={dev} of=/dev/null bs=64k", rf"(?s)seconds.*{P}", cap_read,
                             f"dd mode {mode}")
            t = re.search(r"(\d+) bytes .*copied, ([\d.]+) seconds", out)
            if not t or int(t.group(1)) != size:
                raise SystemExit(f"FAIL: dd mode {mode}: no/short byte count: {out[-200:]!r}")
            secs = float(t.group(2))
            _, out = con.run(f"dd if={dev} bs=64k 2>/dev/null | md5sum", rf"([0-9a-f]{{32}})  -\r?\n{P}",
                             cap_md5, f"md5 mode {mode}")
            md5 = re.search(r"([0-9a-f]{32})  -", out).group(1)
            res[mode] = (secs, md5)
            rl.log(f"mode {mode}: {size} B in {secs:.3f} s = {size / secs / 1e6:.2f} MB/s, md5 {md5}")
        con.run("echo 2 >$D", P, 1, "dirmap back to default 2")
    finally:
        con.note("interactive-end")
    same = len({md5 for _, md5 in res.values()}) == 1
    faster = 0 in res and 2 in res and res[2][0] < res[0][0]
    ok = active and same and faster
    rl.log(f"{'PASS' if ok else 'FAIL'}: dirmap active {active}, md5 equal {same}, cached faster than PIO {faster}"
           + (f" ({res[0][0] / res[2][0]:.1f}x)" if faster else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
