#!/usr/bin/env python3
"""mem_tap_sweep — DDR3 probe sweep at the mainline U-Boot prompt (#48 #49 #56, docs/CLOCKS.md (b)).

- Each setting = `clocks set mem <MHz> nosr probe [--extra] <setting> force`: change, canary at the new
  clock, always revert to the current bin (MRS and PHY values included). Logs canary bad / 1024 + XOR.
- Modes:
  - `field --reg A --fields H:L[,H:L] --values LO-HI`: those fields of PHY register A (live value read
    first) = each value; e.g. DIDER b8001050 fields 28:24,20:16 (DQS0/1 read enable taps).
  - `dqshift --values -8-8`: all 32 trained DQ read taps + n.
  - `mpcr`: MPCR0-2 rows of the SDK MEM PLL table (cg_mem.c) with the bin's NCODE.
  - `once`: one probe with `--extra` only (e.g. `--mhz 650 --extra cl11`).
- Stops on `probe FAIL` (not back cleanly) or no prompt (hang: power cycle). No flash writes.
- Log: tmp/logs/mem_tap_sweep.log; table: tmp/mem_tap_sweep-<YYYYMMDD-HHMMSS>.csv.
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/mem_tap_sweep.log"
PROMPT = r"\r?\nst1008f-mainline # "
# Caps (expected x 1.25, rounded up to the 50 ms console poll); expiry -> SystemExit naming the step.
CAP_CMD = 1    # md.l / echo: < 0.1 s of output at 115200
CAP_PROBE = 1  # 2 x 1.9 ms routine + <= 4.5 KB output (32 dqshift lines) at 11.5 KB/s = 0.4 s x 1.25
# SDK cg_mem.c MPCR0-2 rows (250-600) + the #if 0 650 row (boot0412/memctl.c); label = source row
MPCR_ROWS = {
    "600": (0x0000007F, 0x400001EF, 0x26A33860), "575/650if0": (0x000C807F, 0x4000018F, 0x26A33860),
    "550": (0x000C607F, 0x4000018F, 0x26A33840), "500": (0x000C607F, 0x4000018F, 0x26A23740),
    "450": (0x0008407F, 0x4000018F, 0x26A23720), "400": (0x0000007F, 0x400001EF, 0x26622520),
    "375": (0x0008407F, 0x4000018F, 0x26622520), "350": (0x0008407F, 0x4000018F, 0x26222520),
}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def span(s: str) -> list[int]:
    m = re.fullmatch(r"(-?\d+)-(-?\d+)", s)
    if not m:
        return [int(x) for x in s.split(",")]
    lo, hi = int(m.group(1)), int(m.group(2))
    return list(range(lo, hi + 1))


def read_reg(con: Console, addr: int) -> int:
    _, out = con.run(f"md.l {addr:x} 1", rf"{addr:08x}: ([0-9a-f]{{8}})[^\n]*" + PROMPT, CAP_CMD, f"md {addr:x}")
    return int(re.search(rf"{addr:08x}: ([0-9a-f]{{8}})", out).group(1), 16)


def probe(con: Console, mhz: int, extra: str, setting: str) -> dict:
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, CAP_CMD, "prompt present")
    cmd = f"clocks set mem {mhz} nosr probe {extra} {setting} force".replace("  ", " ")
    if len(cmd) > 240:
        raise SystemExit(f"command {len(cmd)} chars > 240 (console drops input): {cmd}")
    _, out = con.run(cmd, r"clocks: (?:probe (?:OK|FAIL)|mem set FAIL|no bin|mem option|reg |DTR0 |MEM would)"
                     r"[^\r\n]*" + PROMPT, CAP_PROBE, f"probe {setting}")
    m = re.search(r"canary (\d+) bad at the new clock(?: \(\d+ in the burst pass\))?, xor ([0-9a-f]{8}), first \+0x([0-9a-f]+) = "
                  r"([0-9a-f]{8}) want ([0-9a-f]{8})", out)
    marks = re.search(r"\n(M[SPRXDCF]*)\r?\n", out)
    r = {"setting": setting, "ok": "probe OK" in out, "bad": int(m.group(1)) if m else -1,
         "xor": m.group(2) if m else "", "first": f"+0x{m.group(3)} {m.group(4)}/{m.group(5)}" if m else "",
         "marks": marks.group(1) if marks else ""}
    if not m:
        r["error"] = (re.findall(r"clocks: [^\r\n]*", out) or ["(no output)"])[-1]
    log(f"  {setting or '(base)'}: canary bad {r['bad']}/1024 xor {r['xor']} first {r['first']} "
        f"marks {r['marks']} {'OK' if r['ok'] else 'FAIL ' + r.get('error', '')}")
    return r


def settings(a: argparse.Namespace, con: Console) -> list[str]:
    if a.mode == "once":
        return [""]
    if a.mode == "dqshift":
        return [f"dqshift {n}" for n in span(a.values)]
    if a.mode == "mpcr":
        return [f"mpcr {m0:08x} {m1:08x} {m2:08x}" for m0, m1, m2 in MPCR_ROWS.values()]
    addr = int(a.reg, 16)
    live = read_reg(con, addr)
    fields = [tuple(int(x) for x in f.split(":")) for f in a.fields.split(",")]
    log(f"  reg {addr:08x} live {live:08x}, fields {a.fields}")
    out = []
    for v in span(a.values):
        val = live
        for hi, lo in fields:
            mask = ((1 << (hi - lo + 1)) - 1) << lo
            val = (val & ~mask) | ((v << lo) & mask)
        out.append(f"reg {addr:08x} {val:08x}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["field", "dqshift", "mpcr", "once"])
    ap.add_argument("--mhz", type=int, required=True, help="target bin, e.g. 675 (probe reverts to the current)")
    ap.add_argument("--reg", help="field mode: PHY register, hex (b8001050..58, b8001500..15c4)")
    ap.add_argument("--fields", default="", help="field mode: H:L[,H:L] all set to each value")
    ap.add_argument("--values", default="0-31", help="LO-HI or comma list (dqshift: e.g. -8-8)")
    ap.add_argument("--extra", default="", help="options added to every probe, e.g. 'cl11' or 'mpcr a b c'")
    a = ap.parse_args()
    if a.mode == "field" and not (a.reg and a.fields):
        ap.error("field mode needs --reg and --fields")
    con = Console()
    log(f"=== mem_tap_sweep {' '.join(sys.argv[1:])} ===")
    rows = []
    try:
        for s in settings(a, con):
            rows.append(probe(con, a.mhz, a.extra, s))
            if not rows[-1]["ok"]:
                log("STOP: probe did not come back cleanly (see the error); state unknown")
                break
    except SystemExit as e:  # no prompt: hang -> power cycle
        log(f"FAIL (hang?): {str(e)[:300]}")
    csv = ROOT / f"tmp/mem_tap_sweep-{time.strftime('%Y%m%d-%H%M%S')}.csv"
    csv.write_text("setting,canary_bad,xor,first,marks,ok\n" + "".join(
        f"{r['setting']},{r['bad']},{r['xor']},{r['first']},{r['marks']},{r['ok']}\n" for r in rows))
    good = [r for r in rows if r["bad"] >= 0]
    if good:
        best = min(good, key=lambda r: r["bad"])
        log(f"best: {best['setting'] or '(base)'} canary bad {best['bad']}/1024; table {csv.name}")
    return 0 if rows and all(r["ok"] for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
