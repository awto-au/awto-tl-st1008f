#!/usr/bin/env python3
"""sdk_regdump — print RTL9300 (longan) register offsets + field layouts from the GPL SDK tables.

- Inputs: `rtk_longan_reg_list.c` + `rtk_longan_regField_list.c` (SDK `src/hal/chipdef/longan/`,
  GPL copy `reyalo/Realtek` `sources/rtk-dms1250/`); fetch with `--fetch` (gh api) into
  `tmp/datasheet-audit/sdk/longan/`.
- Select registers by regex on the name; `--decode NAME=0xVALUE` splits a read value into fields.
- Log: tmp/logs/sdk_regdump.log.
- Example: `scripts/sdk_regdump.py '^DMA_IF_|^NIC_|^L2_NTFY' --decode DMA_IF_CTRL=0x06400000`
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SDK = ROOT / "tmp/datasheet-audit/sdk/longan"
LOG = ROOT / "tmp/logs/sdk_regdump.log"
REPO = "reyalo/Realtek"
SRC = "sources/rtk-dms1250/src/hal/chipdef/longan"
FILES = ("rtk_longan_reg_list.c", "rtk_longan_regField_list.c")

REG_RE = re.compile(
    r'/\* register name  \*/\s+"(?P<name>\w+)".*?'
    r"/\* offset address \*/\s+(?P<off>0x[0-9A-Fa-f]+).*?"
    r"/\* array index \*/\s+(?P<a0>\d+),\s*(?P<a1>\d+).*?"
    r"/\* register fields \*/\s+(?P<fields>\w+)_FIELDS",
    re.S,
)
FIELDS_RE = re.compile(r"rtk_regField_t (\w+)_FIELDS\[\] =\s*\{(.*?)\n\};", re.S)
FIELD_RE = re.compile(
    r"/\* lsp \*/\s+(\d+),\s*/\* len \*/\s+(\d+),.*?/\* field name \*/\s+\"(\w+)\"", re.S
)


def log(msg: str) -> None:
    print(msg)
    with LOG.open("a") as f:
        f.write(msg + "\n")


def fetch() -> None:
    SDK.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        out = SDK / name
        with out.open("wb") as f:
            subprocess.run(
                ["gh", "api", "-H", "Accept: application/vnd.github.raw",
                 f"repos/{REPO}/contents/{SRC}/{name}"],
                stdout=f, check=True,
            )
        log(f"fetched {name}: {out.stat().st_size} bytes")


def load():
    regs = {}
    text = (SDK / FILES[0]).read_text(errors="replace")
    for m in REG_RE.finditer(text):
        regs.setdefault(m["name"], (int(m["off"], 16), int(m["a0"]), int(m["a1"]), m["fields"]))
    fields = {}
    ftext = (SDK / FILES[1]).read_text(errors="replace")
    for m in FIELDS_RE.finditer(ftext):
        name = m[1].removesuffix("_RTL9300")
        fields[name] = sorted(
            ((int(lsp), int(ln), fn) for lsp, ln, fn in FIELD_RE.findall(m[2])), reverse=True
        )
    return regs, fields


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pattern", nargs="?", default=".", help="regex on register name")
    ap.add_argument("--fetch", action="store_true", help="download the SDK tables via gh")
    ap.add_argument("--decode", action="append", default=[], help="NAME=0xVALUE")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if a.fetch or not all((SDK / n).exists() for n in FILES):
        fetch()
    regs, fields = load()
    pat = re.compile(a.pattern)
    for name, (off, a0, a1, fkey) in sorted(regs.items(), key=lambda kv: kv[1][0]):
        if not pat.search(name):
            continue
        arr = f" [{a0}..{a1}]" if a1 else ""
        fl = fields.get(fkey.removesuffix("_RTL9300"), [])
        desc = ", ".join(f"{fn}[{lsp + ln - 1}:{lsp}]" if ln > 1 else f"{fn}[{lsp}]"
                         for lsp, ln, fn in fl)
        log(f"0x{off:04X} (0xBB00{off:04X}) {name}{arr}: {desc}")
    for d in a.decode:
        name, val = d.split("=")
        v = int(val, 0)
        fl = fields.get(regs[name][3].removesuffix("_RTL9300"), [])
        log(f"decode {name} = 0x{v:08X}")
        for lsp, ln, fn in fl:
            fv = (v >> lsp) & ((1 << ln) - 1)
            log(f"  {fn:24s} [{lsp + ln - 1:2d}:{lsp:2d}] = 0x{fv:X} ({fv})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
