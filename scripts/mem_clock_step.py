#!/usr/bin/env python3
"""mem_clock_step — DDR3 clock change at the mainline U-Boot prompt, DRAM kept (#39, docs/CLOCKS.md (b)).

- Before: copy 16 MiB to uncached 0xa2000000, `crc32` + `md` it (contents reference).
- Per MHz in the ladder: `clocks set mem <MHz> [nosr] force`, then `clocks` must decode that MEM rate,
  `crc32` + `md` of the 16 MiB must match (contents survived), `highmem test` (256 MiB) must pass.
- Bins 675..800 issue MRS (MR2, MR0 + DLL reset) in the routine; `--nosr` only (C refuses otherwise).
- Ladder stops at the first fail. A hang = power cycle (`./dev.py ramload uboot-mainline`); no flash writes.
- Log: tmp/logs/mem_clock_step.log.
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/mem_clock_step.log"
PROMPT = r"\r?\nst1008f-mainline # "
REF = 0xa2000000          # uncached DRAM bus 0x02000000: clear of U-Boot (0x81000000 load, top-of-256M reloc)
REF_LEN = 0x1000000       # 16 MiB
SRC = 0x81000000

# Caps: (expected, source) x 1.25, rounded up to the 50 ms console poll; expiry -> SystemExit naming the step.
CAP_CMD = 1               # short commands: < 0.2 s of output at 115200
CAP_SET = 1               # routine 0.4 ms (2 x 200 us PLL waits) + canary 1024 reads + ~1.8 KB output 0.16 s
CAP_16M = 1               # 16 MiB uncached at 75 MB/s (highmem 1 GiB/14.3 s, 2026-10-10) = 0.22 s + crc32 0.3 s
CAP_HIGHMEM = 18          # highmem test 14.3 s at CPU 800 (CLOCKS.md, 2026-10-10) x 1.25


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def crc(con: Console) -> str:
    _, out = con.run(f"crc32 0x{REF:08x} 0x{REF_LEN:x}", r"==> ([0-9a-f]{8})" + PROMPT, CAP_16M, "crc32 16 MiB")
    return re.search(r"==> ([0-9a-f]{8})", out).group(1)


def md(con: Console) -> list[str]:
    _, out = con.run(f"md.l 0x{REF:08x} 8", r"a2000010:.*" + PROMPT, CAP_CMD, "md 8 words")
    return re.findall(r"a20000[01]0:[ 0-9a-f]+", out)


def step(con: Console, mhz: int, nosr: bool, ref_crc: str, ref_md: list[str]) -> bool:
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, CAP_CMD, "prompt present")
    cmd = f"clocks set mem {mhz}{' nosr' if nosr else ''} force"
    _, out = con.run(cmd, r"clocks: mem set (OK|FAIL)[^\r\n]*" + PROMPT, CAP_SET, f"mem set {mhz}")
    for line in re.findall(r"clocks: (?:routine|canary|mem now|mem set)[^\r\n]*", out):
        log(f"  {line}")
    marks = re.search(r"\n(M[SPRXDCF]*)\r?\n", out)  # written by the SRAM routine itself (R = MRS done)
    log(f"  routine UART marks: {marks.group(1) if marks else '(none)'}")
    ok = "mem set OK" in out
    _, out = con.run("clocks", r"(?s)mem pll:[^\r\n]*" + PROMPT, CAP_CMD, "clocks")
    m = re.search(r"\nmem ([\d.]+) MHz", out)
    dec = float(m.group(1)) if m else 0.0
    log(f"  clocks: mem {dec} MHz; " + " | ".join(re.findall(r"(?:ddr3 clk|ddr3 dram|ddr3 ctl|mem pll):[^\r\n]*", out)))
    ok &= abs(dec - mhz) < 0.5
    c = crc(con)
    words = md(con)
    log(f"  crc32 {c} (ref {ref_crc}), md {'same' if words == ref_md else 'DIFFERENT: ' + str(words)}")
    ok &= c == ref_crc and words == ref_md
    _, out = con.run("highmem test", r"(pattern test \d+ MiB: \d+ errors|alias check: FAIL)[^\r\n]*" + PROMPT,
                     CAP_HIGHMEM, "highmem test 256 MiB")
    hm = re.search(r"pattern test \d+ MiB: \d+ errors|alias check: FAIL", out).group(0)
    log(f"  highmem: {hm}")
    ok &= hm.endswith(": 0 errors")
    c2 = crc(con)
    ok &= c2 == ref_crc
    log(f"{'PASS' if ok else 'FAIL'} mem {mhz} MHz{' nosr' if nosr else ''}: decoded {dec}, crc after highmem {c2}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mhz", type=int, nargs="+",
                    help="bins in order, e.g. 600 650 675 700 ... 800 (600 = re-apply stock: proves the sequence; "
                         "675+ = CL 11 / CWL 8 via MRS, needs --nosr and CPU above the target)")
    ap.add_argument("--nosr", action="store_true", help="refresh-off method instead of self-refresh")
    a = ap.parse_args()
    con = Console()
    log(f"=== mem_clock_step {' '.join(sys.argv[1:])} ===")
    try:
        con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, CAP_CMD, "prompt present")
        _, out = con.run("clocks", r"(?s)mem pll:[^\r\n]*" + PROMPT, CAP_CMD, "clocks before")
        log("  before: " + " | ".join(re.findall(r"(?:mem [\d.]+ MHz|ddr3 clk|ddr3 dram|ddr3 ctl|ddr3 phy|mem pll)[^\r\n]*", out)))
        con.run(f"cp.l 0x{SRC:08x} 0x{REF:08x} 0x{REF_LEN // 4:x}", PROMPT, CAP_16M, "copy 16 MiB reference")
        ref_crc, ref_md = crc(con), md(con)
        log(f"  reference crc32 {ref_crc}")
        for mhz in a.mhz:
            if not step(con, mhz, a.nosr, ref_crc, ref_md):
                return 1
    except SystemExit as e:  # no prompt: hang after the change -> power cycle needed
        log(f"FAIL: {str(e)[:300]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
