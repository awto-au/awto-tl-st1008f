#!/usr/bin/env python3
"""lock_probe — CPU PLL lock vs real limit, U-Boot only, on sw2 (docs/FASTEST-SETTINGS.md "lock or limit").

- Boot: ramload uboot-mainline --stock-clocks, `turbo cpu=800,ddr=662,lx=306,sram=500`, optional 608 core line (retest_options recipe).
- Per CPU point in order: `clocks set cpu` (lock line), e200/e208/e210 readout, N repeat e200 reads, quick memtest cached+uncached.
- A timeout or FAIL marker = HANG: logged, the ladder stops; the next boot reboots in software.
    lock_probe.py --tag T --core 408|608 --cpu 1350,1375,1400 [--reads 20] [--mib 32] [--settle 0]
- Log: tmp/logs/lock_probe.log (+ .jsonl)
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/lock_probe.log"
JSONL = ROOT / "tmp/logs/lock_probe.jsonl"
PROMPT = r"\r?\nst1008f-mainline # "
TAIL = r"st1008f-mainline # "
CORES = {"408": None, "608": ("0x36826", "0x478")}  # e220, e214: retest_options.py CORES
BOOT_S = 120   # ramload to prompt ~25 s measured (memtest.py), x1.25 + relay retries
MEMTEST_S = 40  # 12 units x 32 MiB, uncached stock ~1.75 s per unit, x1.9; hang names itself


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def e208_e210(mhz):
    out = subprocess.run([sys.executable, "scripts/clock_calc.py", "cpu", str(mhz)], capture_output=True, text=True, cwd=ROOT).stdout
    m = re.search(rf"cpu {mhz}\.000 MHz.*e208 = (0x[0-9a-f]+), 0xbb00e210 = (0x[0-9a-f]+)", out.replace("0xbb00e208", "e208"))
    return m[1], m[2]


def regs(con):
    _, out = con.run("md.l 0xbb00e200 1; md.l 0xbb00e208 1; md.l 0xbb00e210 1", r"(?s)bb00e210: [^\n]*\n.*?" + TAIL, 3, "regs")
    return {a: int(v, 16) for a, v in re.findall(r"bb00e(200|208|210): ([0-9a-f]{8})", out)}


def point(con, mhz, a, rec):
    e208, e210 = e208_e210(mhz)
    _, out = con.run(f"clocks set cpu {e208} {e210} 0 force",
                     r"clocks: (locked after \d+ us[^\r\n]*|CPU PLL not locked[^\r\n]*)\r?\n", 3, f"cpu {mhz}")
    rec["lock"] = re.search(r"clocks: (locked after (\d+) us|CPU PLL not locked)", out)[0]
    rec["lock_us"] = int(re.search(r"after (\d+) us", out)[1])
    log(f"  cpu {mhz} [{e208} {e210}]: {rec['lock']}")
    con.run("", PROMPT, 2, "prompt")
    r = regs(con)
    rec["e200"] = f"{r.get('200', 0):08x}"
    rec["e208"], rec["e210"] = f"{r.get('208', 0):08x}", f"{r.get('210', 0):08x}"
    rec["ready_bit15"] = (r.get("200", 0) >> 15) & 1
    log(f"  regs e200 {rec['e200']} (bit15 {rec['ready_bit15']}) e208 {rec['e208']} e210 {rec['e210']}")
    bits = []
    for _ in range(a.reads):  # one read per console round trip = spacing without sleep
        _, o = con.run("md.l 0xbb00e200 1", r"bb00e200: ([0-9a-f]{8})[^\n]*\r?\n" + TAIL, 2, "e200 re-read")
        bits.append((int(re.search(r"bb00e200: ([0-9a-f]{8})", o)[1], 16) >> 15) & 1)
    rec["reread_bit15"] = "".join(map(str, bits))
    log(f"  bit15 re-reads x{a.reads}: {rec['reread_bit15']}")
    mark = con.size()
    con.send(f"memtest log=3 mib={a.mib} low")
    _, out = con.expect(r"memtest: done[^\r\n]*", MEMTEST_S, mark, f"memtest {mhz}")
    units = re.findall(r"memtest: S (\w+) (\w+) (\w+) \d+ MiB \d+ ms errs (\d+)", out)
    rec["memtest_errs"] = {f"{u[1]}": 0 for u in units}
    for u in units:
        rec["memtest_errs"][u[1]] += int(u[3])
    rec["memtest_units"] = len(units)
    log(f"  memtest {len(units)} units, errs {rec['memtest_errs']}")
    con.run("", PROMPT, 3, "prompt")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--core", choices=list(CORES), default="408")
    ap.add_argument("--cpu", required=True, help="comma list of MHz, applied in order")
    ap.add_argument("--reads", type=int, default=20)
    ap.add_argument("--mib", type=int, default=32)
    ap.add_argument("--no-boot", action="store_true")
    a = ap.parse_args()
    t0 = time.time()
    if not a.no_boot:
        r = subprocess.run([sys.executable, "scripts/st1008_ramload.py", "uboot-mainline", "--stock-clocks"],
                           capture_output=True, text=True, cwd=ROOT, timeout=BOOT_S)
        log(f"[{a.tag}] boot rc {r.returncode} in {time.time() - t0:.0f} s")
        if r.returncode not in (0, 1):
            log(f"BOOT FAIL: {(r.stdout + r.stderr).strip().splitlines()[-1:]}")
            return 3
    con = Console()
    con.run("", PROMPT, 3, "prompt")
    con.note("interactive-begin")
    con.run("turbo cpu=800,ddr=662,lx=306,sram=500", r"clocks: turbo [^\r\n]*" + PROMPT, 6, "turbo base")
    if CORES[a.core]:
        e220, e214 = CORES[a.core]
        con.run(f"mw.l 0xbb00e220 {e220}; mw.l 0xbb00e214 {e214}; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff",
                TAIL, 5, "core 608")  # UART garbles at the re-code: no newline before the prompt
    _, out = con.run("md.l 0xbb00e220 1; md.l 0xbb00e214 1", r"(?s)bb00e214: [^\n]*\n.*?" + TAIL, 3, "core regs")
    log(f"[{a.tag}] core {a.core}: {re.findall(r'bb00e2(?:20|14): [0-9a-f]{8}', out)}")
    for mhz in (int(x) for x in a.cpu.split(",")):
        rec = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "tag": a.tag, "core": a.core, "cpu": mhz}
        try:
            point(con, mhz, a, rec)
            rec["result"] = "ok"
        except SystemExit as e:
            rec["result"] = f"HANG/FAIL: {str(e)[:200]}"
            log(f"  {rec['result']}")
        with JSONL.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        if rec["result"] != "ok":
            break
    con.note("interactive-end")
    return 0


if __name__ == "__main__":
    sys.exit(main())
