#!/usr/bin/env python3
"""clocks_cycle — repeat-rate of one clock step over N power cycles on the bench unit (#101).

- Per cycle: `ramload uboot-mainline --stock-clocks` (power cycle; `--from-flash` = ours copied from
  jffs2-log, no `rtk network on`, as the power-up chain), then ONE step at our prompt:
  cpu = `clocks set cpu 0x3a8 0x6b439e13 0 force` (1 GHz); mem = `clocks set mem <--mhz> nosr force`;
  fast = `clocks fast` (both + tREFI + prefetch). Then `echo ALIVE`.
- Result per cycle: pass / fail (command reported FAIL) / hang (no prompt; last console lines kept)
  / boot (ramload failed). JSON lines -> tmp/logs/clocks_cycle.jsonl; summary at the end.
- `--session DOMAIN` (cpu|ddr|lx|sram; CLAUDE.md "Speed sweeps"): binary search over the points `turbo`
  accepts in --lo (stock) .. --hi (max) [on the --step grid], starting at the midpoint; pass -> higher,
  fail/hang -> lower; ONE quick test per point, in one powered session. Each point: `bootsel wdt` armed,
  `turbo <domain>=<v>` (applied from the current clocks), ALIVE + 16 MiB crc32 + temp, wdt off.
  Power-cycle only after a fail or hang. Logs every point and the final edge.
- RAM U-Boot only: no flash or env writes. Log: tmp/logs/clocks_cycle.log
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/clocks_cycle.log"
JSONL = ROOT / "tmp/logs/clocks_cycle.jsonl"
PROMPT = r"\r?\nst1008f-mainline # "
STEPS = {
    "cpu": ("clocks set cpu {e208} {e210} 0 force", r"clocks: (locked after \d+ us[^\n]*|CPU PLL not locked[^\n]*)"),
    "mem": ("clocks set mem {mhz} nosr {extra}force", r"clocks: (mem set (OK|FAIL[^\n]*)|no bin[^\n]*)"),
    # same set with all 32 trained DQ read taps rewritten unchanged while clk_oe = 0 (#101 test)
    "memdq0": ("clocks set mem {mhz} nosr dqshift 0 force", r"clocks: (mem set (OK|FAIL[^\n]*)|no bin[^\n]*)"),
    "sram500": ("clocks set sram 500 force", r"clocks: (locked after \d+ us[^\n]*|CPU PLL not locked[^\n]*)"),
    "membench": ("clocks membench", r"membench dram c read \(fill\): \d+ ps/access"),
    "lx": ("clocks set lx {lx} force", r"clocks: (lx now \d+ kHz[^\n]*|lx code[^\n]*)"),
    "turbo": ("turbo {profile}", r"clocks: turbo (OK|reverted|FAIL)[^\n]*|clocks: turbo refused[^\n]*"),
    "fast": ("clocks fast", r"clocks: (fast = [^\n]*|mem set FAIL[^\n]*|DTR latch[^\n]*)"),
}
# step from SRAM: PLL relock (250 us bound) + DDR change + 1024-word canary, ~ms; the console
# prints ~20 lines (~2 KB at 115200 = 0.2 s). 3 s names a hang.
STEP_S = 3
CPU = ["0x3a8", "0x6b439e13"]  # 1000 MHz; --cpu
PROFILE = ""  # --profile: turbo step, e.g. cpu=1400,ddr=662,sram=500
EXTRA = ""  # --extra: mem step options, e.g. 'dqshift -8'
LX = 4  # --lx: code 2..5 (306 / 245 / 204 / 175 MHz)
BOOT_S = 120  # ramload uboot-mainline: power cycle + network on + TFTP ~25 s; x1.25 + relay retries


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def cycle(step: str, flash: bool, mhz: int) -> dict:
    cmd = [sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "uboot-mainline", "--stock-clocks"]
    r = subprocess.run(cmd + (["--from-flash"] if flash else []), capture_output=True, text=True,
                       timeout=BOOT_S)
    if r.returncode not in (0, 1):  # 1 = boot log UNKNOWN only: prompt usable
        return {"result": "boot", "detail": (r.stdout + r.stderr).strip().splitlines()[-1:]}
    con = Console()
    try:
        con.run("", PROMPT, 2, "our prompt")
    except SystemExit:
        return {"result": "boot", "detail": ["no st1008f-mainline prompt after ramload"]}
    res, detail = "pass", []
    for part in step.split("+"):  # e.g. cpu+mem: separate commands, in order
        text, want = STEPS[part]
        text = text.format(mhz=mhz, e208=CPU[0], e210=CPU[1], lx=LX, extra=EXTRA + " " if EXTRA else "",
                           profile=PROFILE)
        mark = con.size()
        try:
            _, out = con.run(text, rf"(?s){want}.*?{PROMPT}", STEP_S, f"step {part}")
        except SystemExit as e:
            log_tail = Path(ROOT / "private/serial/st1008-console.log").read_bytes()[mark:].decode("latin-1")
            lines = [ln.strip() for ln in log_tail.splitlines() if ln.strip() and not ln.startswith("[TX")]
            return {"result": "hang" if str(e).startswith("TIMEOUT") else "fail", "detail": [part] + lines[-3:]}
        m = re.search(want, out)
        detail.append(m.group(0))
        if part == "membench":  # keep the per-access table
            detail.extend(re.findall(r"membench (?:sram|dram) [^\r\n]*", out))
        if "FAIL" in m.group(0) or "latch" in m.group(0) or "no bin" in m.group(0) or "not locked" in m.group(0):
            res = "fail"
            break
    try:
        con.run("echo ALIVE", r"\r?\nALIVE" + PROMPT, 2, "alive")
        # 16 MiB CRC: CPU + DRAM work at the new clocks; ~0.3 s at 1 GHz (bench), cap x5 for slow settings
        con.run("crc32 0x81000000 0x1000000", r"==> [0-9a-f]{8}" + PROMPT, 2, "crc32 16 MiB")
        _, t = con.run("rtk temp", r"(?s)rtk temp.*?" + PROMPT, 2, "temp")  # meter enable + 1 sample, ~ms
        detail.append(" ".join(re.findall(r"(\d+) ?C\b", t))[:20] + " C")
    except SystemExit:
        return {"result": "hang", "detail": detail + ["after step: no ALIVE / crc32 / temp"]}
    return {"result": res, "detail": detail}


# `turbo` points per domain (uboot-port clocks.c cpu_code / mem_bins / lx_pts, bootsel sram); [0] = stock
POINTS = {"cpu": [800, 1000, 1050] + list(range(1100, 1426, 25)),
          "ddr": [600, 625, 650, 662, 675, 700, 725, 750, 775, 800],
          "lx": [175, 204, 245, 306], "sram": [250, 500]}
# bootsel wdt per point: turbo (PLL/DDR change ~ms) + ~25 console lines (0.2 s) + crc32 (<= 2 s cap) +
# temp: expected <= 4 s, x1.25 = 5 s; ticks follow LX, so 306 MHz shortens it to ~2.9 s -> 9 s armed
WDT_MS = 9000
TURBO_OK = r"clocks: turbo (OK|reverted) = [^\n]*|turbo: [^\n]*nothing changed|clocks: turbo refused[^\n]*"


def boot(flash: bool) -> bool:
    cmd = [sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "uboot-mainline", "--stock-clocks"]
    r = subprocess.run(cmd + (["--from-flash"] if flash else []), capture_output=True, text=True, timeout=BOOT_S)
    return r.returncode in (0, 1)  # 1 = boot log UNKNOWN only: prompt usable


def point(con, domain: str, v: int) -> dict:
    mark = con.size()
    try:
        con.run(f"bootsel wdt {WDT_MS}", PROMPT, 1, "wdt on")
        _, out = con.run(f"turbo {domain}={v}", rf"(?s)({TURBO_OK}).*?{PROMPT}", STEP_S, f"turbo {domain}={v}")
        m = re.search(TURBO_OK, out)
        if not m.group(0).startswith("clocks: turbo OK"):
            return {"result": "fail", "detail": [m.group(0)]}
        con.run("echo ALIVE", r"\r?\nALIVE" + PROMPT, 2, "alive")
        con.run("crc32 0x81000000 0x1000000", r"==> [0-9a-f]{8}" + PROMPT, 2, "crc32 16 MiB")
        _, t = con.run("rtk temp", r"(?s)rtk temp.*?" + PROMPT, 2, "temp")
        con.run("bootsel wdt off", PROMPT, 1, "wdt off")
        return {"result": "pass", "detail": [m.group(0), " ".join(re.findall(r"(\d+) ?C\b", t))[:20] + " C"]}
    except SystemExit as e:
        tail = Path(ROOT / "private/serial/st1008-console.log").read_bytes()[mark:].decode("latin-1")
        lines = [ln.strip() for ln in tail.splitlines() if ln.strip() and not ln.startswith("[TX")]
        return {"result": "hang" if str(e).startswith("TIMEOUT") else "fail", "detail": lines[-3:]}


def session(domain: str, lo: int | None, hi: int | None, step: int | None, flash: bool) -> int:
    pts = POINTS[domain]
    lo = pts[0] if lo is None else lo
    hi = pts[-1] if hi is None else hi
    pts = [p for p in pts if lo <= p <= hi and (not step or (p - lo) % step == 0)]
    if len(pts) < 2 or pts[0] != lo:
        log(f"FAIL session: no points in {lo}..{hi} step {step} ({POINTS[domain]})")
        return 2
    good, bad = 0, len(pts)  # index: pts[0] = stock = known good; bad = first failing index
    fresh = False
    tag = f"session-{domain}"
    while good + 1 < bad:
        # MHz midpoint of the open interval (stock..max at the start), snapped to a point strictly inside
        mid = (pts[good] + (pts[bad] if bad < len(pts) else pts[-1])) / 2
        i = min(range(good + 1, bad), key=lambda k: abs(pts[k] - mid))
        if not fresh and not boot(flash):
            log(f"[{tag}] FAIL: no prompt after the power cycle")
            return 2
        fresh = True
        res = point(Console(), domain, pts[i])
        res.update({"tag": tag, "point": pts[i], "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        log(f"[{tag}] {domain}={pts[i]}: {res['result']}: {' | '.join(res['detail'])}")
        with JSONL.open("a") as fh:
            fh.write(json.dumps(res) + "\n")
        if res["result"] == "pass":
            good = i  # clocks stay up; the next point is higher and applies from here
        else:
            bad = i
            fresh = False  # fail or hang: power-cycle before the next point
    edge = pts[bad] if bad < len(pts) else "none (max passed)"
    log(f"EDGE {domain}: fastest viable {pts[good]}, first failing {edge} (one quick test per point)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("step", nargs="?", help="cpu | mem | fast, or a sequence like cpu+mem / mem+cpu")
    ap.add_argument("--session", choices=sorted(POINTS), help="binary-search sweep in one powered session")
    ap.add_argument("--lo", type=int, help="session: stock end (default: stock)")
    ap.add_argument("--hi", type=int, help="session: max end (default: highest point `turbo` accepts)")
    ap.add_argument("--step", dest="grid", type=int, help="session: resolution in MHz from --lo")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--mhz", type=int, default=650, help="mem step: DDR bin (662 = 662.5 MHz)")
    ap.add_argument("--stop-on-hang", action="store_true")
    ap.add_argument("--profile", default="", help="turbo step profile, e.g. cpu=1400,ddr=662,sram=500")
    ap.add_argument("--extra", default="", help="mem step options before force, e.g. 'dqshift -8'")
    ap.add_argument("--lx", type=int, default=4, help="lx step: code 2..5")
    ap.add_argument("--cpu", default="0x3a8:0x6b439e13", help="cpu step: E208:E210 (scripts/clock_calc.py cpu <MHz>)")
    ap.add_argument("--from-flash", action="store_true", help="ours from jffs2-log, no network on")
    a = ap.parse_args()
    if a.session:
        return session(a.session, a.lo, a.hi, a.grid, a.from_flash)
    if not a.step:
        ap.error("step or --session DOMAIN")
    global CPU, LX, EXTRA, PROFILE
    CPU = a.cpu.split(":")
    LX = a.lx
    EXTRA = a.extra
    PROFILE = a.profile
    if any(p not in STEPS for p in a.step.split("+")):
        ap.error(f"step parts must be in {list(STEPS)}")
    tag = f"{a.step}{a.mhz if 'mem' in a.step else ''}{'@' + CPU[0] if 'cpu' in a.step else ''}{'-flash' if a.from_flash else ''}"
    counts: dict[str, int] = {}
    for i in range(1, a.n + 1):
        res = cycle(a.step, a.from_flash, a.mhz)
        res.update({"tag": tag, "cycle": i, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")})
        counts[res["result"]] = counts.get(res["result"], 0) + 1
        log(f"[{tag} {i}/{a.n}] {res['result']}: {' | '.join(res['detail'])}")
        with JSONL.open("a") as fh:
            fh.write(json.dumps(res) + "\n")
        if a.stop_on_hang and res["result"] == "hang":
            break
    log(f"SUMMARY {tag}: {counts} of {a.n}")
    return 0 if counts.get("pass", 0) == a.n else 1


if __name__ == "__main__":
    sys.exit(main())
