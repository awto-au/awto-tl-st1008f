#!/usr/bin/env python3
"""fastest_search — fastest stable setting per limiting domain on sw2: midpoint bisection, ONE quick test per point (docs/FASTEST-SETTINGS.md).

- sw2 only: refuses sw1 and any --ip but boards.BENCH_IP; run through `./dev.py fastest-search` (board_guard). Never the relay directly.
- Point = ramload uboot-mainline --then mainline-kernel (picks for the other domains + this domain's value via `--pre`), then the quick test:
  link alive, ceiling_rxtx rx 64 B + 1400 B 6 s, zc_bench --integrity, console free of Oops/BUG/panic/gro_list_prepare (temperature logged only).
- Domains in order of expected value: switch-core, lx-arb, cpu, ddr, sram. bisect = stock..max from the midpoint; scan = candidate list.
- ONE NAT interface only (the nat-bench setup: one WAN, one LAN). Hang: the next point's ramload reboots in software (relay only if no prompt).
- `--combine`: best of every domain together; a failing combination drops the least valuable domain first. `--discover`: read the registers
  the sram/lx-arb candidates are derived from (tmp/fastest_search_regs.json).
- Output: tmp/logs/fastest_search.log + .csv; resumes from the csv (`--fresh` ignores it). `--write-doc` fills the results table.
    fastest_search.py --list | --domain D [--dry-run] [--write-doc] | --combine | --discover
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import select
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP, SW1_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/fastest_search.log"
CSV_PATH = ROOT / "tmp/logs/fastest_search.csv"
REGS = ROOT / "tmp/fastest_search_regs.json"
DOC = ROOT / "docs/FASTEST-SETTINGS.md"
CONSOLE = ROOT / "private/serial/st1008-console.log"
PY = sys.executable
DEVPY = str(ROOT / "dev.py")
BAD_CONSOLE = re.compile(rb"Oops|\bBUG\b|Kernel panic|gro_list_prepare")
BASE = {"kpps_1400": 143.3}  # --base overrides (core 608 baseline); picks, rx-only 1400 B (CAMPAIGN-PLAIN-7.4.md, #147); a scan point must beat it by GAIN
GAIN = 1.03                  # 6x the 0.5 % spread measured at 408/306 MHz
PICKS = {"cpu": 1350, "ddr": 662, "lx": 306, "sram": 500}
CORE = {"sw": None}          # --core: fixed switch-core point added to every settings dict
KERNEL = "mainline-7.4-rc1.bin"   # plain bench kernel (not the 7.3 image: #149)
STOCK = {"cpu": 800, "ddr": 600, "lx": 175, "sram": 250}
ORDER = ["switch-core", "lx-arb", "cpu", "ddr", "sram"]   # expected value, high first; combine back-off drops from the end
SSH = ["ssh", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes"]
# stall = no output line and no console-log growth. boot: power cycle + TFTP 5.7 MB ~40 s measured (swcore_step), canary 60/240.
CAPS = {"boot": (60, 240), "ceiling": (60, 120), "integrity": (60, 90), "ssh": (20, 20)}
COLS = ["when", "domain", "point", "settings", "result", "kpps_1400", "kpps_64", "integrity", "temp_before_mC", "temp_after_mC",
        "drops", "bogomips", "kernel", "clocks", "gain", "detail"]
HOST_ARB = [f"0xb80000{o:02x}" for o in range(0x10, 0x40, 4)]   # LX0..2_ARB_CFG0-3


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def conlen() -> int:
    return CONSOLE.stat().st_size if CONSOLE.exists() else 0


def run(cmd: list[str], stall: int, total: int, dry: bool = False) -> tuple[int, str]:
    """rc 124 = stall or total cap hit (logged with elapsed + last line)."""
    log(("DRY " if dry else "RUN ") + " ".join(cmd) + f"   [stall {stall} s, total {total} s]")
    if dry:
        return 0, ""
    p = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    t0 = last = time.time()
    cl, buf = conlen(), b""
    while True:
        r, _, _ = select.select([p.stdout], [], [], 1.0)
        if r:
            d = os.read(p.stdout.fileno(), 65536)
            if not d:
                break
            buf += d
            last = time.time()
        elif p.poll() is not None:
            break
        if conlen() != cl:
            cl, last = conlen(), time.time()
        now = time.time()
        if now - last > stall or now - t0 > total:
            p.kill()
            tail = buf.decode(errors="replace").strip().splitlines()[-1:]
            log(f"CAP expired: {cmd[1:4]} stall limit {stall} s / total {total} s, elapsed {now - t0:.0f} s, silent {now - last:.0f} s, last {tail}")
            return 124, buf.decode(errors="replace")
    p.wait()
    return p.returncode, buf.decode(errors="replace")


def ssh(cmd: str, dry: bool = False) -> str | None:
    if dry:
        return ""
    try:
        r = subprocess.run(SSH + [f"root@{BENCH_IP}", cmd], capture_output=True, text=True, timeout=CAPS["ssh"][1])
    except subprocess.TimeoutExpired:
        return None
    return r.stdout if r.returncode == 0 else None


# ---- settings -> U-Boot commands -------------------------------------------------------------
def sw_line(e214: int, e220: int) -> str:
    """e220, e214, relock in one line (swcore_step: e214 garbles the UART until e220 re-codes LX). Words: docs/CLOCKS.md."""
    return f"mw.l 0xbb00e220 0x{e220:x}; mw.l 0xbb00e214 0x{e214:x}; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff"


# MHz -> (e214, e220), all code 1 (/6), passed 3/3 boots (#148). 612 (code 0) wedges forwarding: not offered.
SWC = {"508": (0x3b8, 0x30626), "575": (0x438, 0x34a26), "608": (0x478, 0x36826), "658": (0x4d8, 0x38c26)}
ARB = {"stock": None, "swap": 0x01010101, "m1": 0x11111111, "m0": 0x00000000}   # slot owners; master IDs unknown (DATASHEET-AUDIT.md:185)


def regs() -> dict:
    return json.loads(REGS.read_text()) if REGS.exists() else {}


def br_lines(name: str, dry: bool) -> list[str]:
    if name == "stock":
        return []
    r = regs()
    if "40f8" not in r or "0388" not in r:
        if dry:
            return [f"mw.l 0xb80040f8 <from --discover: {name}>"]
        raise SystemExit("run `fastest_search.py --discover` first (needs 0xb80040f8, 0xb8000388 at the picks)")
    a, c = int(r["40f8"], 16), int(r["0388"], 16)
    return {"pulse_dn": [f"mw.l 0xb80040f8 0x{(a & ~3) | max(0, (a & 3) - 1):x}"],
            "pulse_up": [f"mw.l 0xb80040f8 0x{(a & ~3) | min(2, (a & 3) + 1):x}"],
            "oc0_dram_flip": [f"mw.l 0xb8000388 0x{c ^ 0x200:x}"]}[name]


def pre_list(st: dict, dry: bool = False) -> list[str]:
    """Settings dict (cpu ddr lx sram + sw / arb / br) -> ordered `--pre` lines; turbo first, raw writes after."""
    pres = [f"turbo cpu={st['cpu']},ddr={st['ddr']},lx={st['lx']},sram={st['sram']}"]
    if st.get("sw") and st["sw"] != "408":
        pres.append(sw_line(*SWC[st["sw"]]))
    if st.get("arb") and ARB[st["arb"]] is not None:
        v = ARB[st["arb"]]
        pres += ["; ".join(f"mw.l {a} 0x{v:08x}" for a in HOST_ARB[i:i + 4]) for i in range(0, 12, 4)]
    if st.get("br") and st["br"] != "stock":
        pres += br_lines(st["br"], dry)
    return pres


def settings_string(st: dict, dry: bool = False) -> str:
    return " | ".join(pre_list(st, dry))


def ramload_cmd(pres: list[str], kernel: str | None = KERNEL, bootargs: str | None = None) -> list[str]:
    c = [PY, DEVPY, "ramload", "uboot-mainline", "--then", "mainline-kernel", "--cage", "1", "--mgmt"]
    if kernel:
        c += ["--kernel", kernel]
    if bootargs:
        c += ["--bootargs", bootargs]
    for p in pres:
        c += ["--pre", p]
    return c


def wait_up(dry: bool) -> bool:
    """Ping for up to 60 s, dropbear via console if ssh is missing, then uptime >= 25 s (nat-bench setup earlier lost lan1)."""
    if dry:
        return True
    t_up = time.time() + 60   # kernel at ramload end is 8-30 s old, lan1 10G link up ~4 s after port-up; a fixed 15 ping loop gave up at 25 s (false HANG at cpu 1100)
    while subprocess.run(["ping", "-c", "1", "-W", "2", BENCH_IP], capture_output=True).returncode != 0:
        if time.time() > t_up:
            log("wait_up: no ping reply within 60 s")
            return False
    if ssh("echo root") is None:
        run([PY, str(ROOT / "scripts/switch_console.py"), "send", "dropbear -R -B", "--secs", "4"], 30, 40)
    t_end = time.time() + 90   # boot to 25 s uptime ~50 s, x1.8
    while time.time() < t_end:
        up = (ssh("cut -d. -f1 /proc/uptime") or "").split()
        if up and up[-1].isdigit() and int(up[-1]) >= 25:
            return True
    return False


# ---- the quick test ---------------------------------------------------------------------------
def quick(st: dict, tag: str, dry: bool, kernel: str | None = None) -> dict:
    pres = pre_list(st, dry)
    res = {"settings": " | ".join(pres), "result": "PASS", "detail": []}
    mark = conlen()
    rc, out = run(ramload_cmd(pres, kernel), *CAPS["boot"], dry=dry)   # rc 1 = boot-log UNKNOWN lines only: shell reached
    if dry:
        run([PY, str(ROOT / "scripts/ceiling_rxtx.py"), "--tag", tag, "--n", "1", "--sizes", "64,1400", "--modes", "rx", "--secs", "6"], *CAPS["ceiling"], dry=True)
        run([PY, str(ROOT / "scripts/zc_bench.py"), "--integrity"], *CAPS["integrity"], dry=True)
        return res
    if rc not in (0, 1):
        return {**res, "result": "HANG" if rc == 124 else "FAIL", "detail": [f"ramload rc {rc}", *out.strip().splitlines()[-2:]]}
    with CONSOLE.open("rb") as fh:   # a rejected turbo leaves stock clocks and every test would pass: require the applied values
        fh.seek(mark)
        ok_t = re.findall(rb"clocks: turbo OK = cpu (\d+) MHz, mem (\d+) MHz", fh.read())
    if not ok_t or (int(ok_t[-1][0]), int(ok_t[-1][1])) != (st["cpu"], st["ddr"]):
        return {**res, "result": "FAIL", "detail": [f"turbo not applied as asked (cpu {st['cpu']} ddr {st['ddr']}): {ok_t[-1:]}"]}
    t0 = ssh("cat /sys/class/thermal/thermal_zone0/temp") if wait_up(dry) else None
    if t0 is None:
        return {**res, "result": "HANG", "detail": ["no ssh after ramload"]}
    res["temp_before_mC"] = int(t0.strip() or 0)
    res["bogomips"] = (ssh("grep -i bogomips /proc/cpuinfo | head -1") or "").split(":")[-1].strip()
    res["kernel"] = (ssh("uname -r") or "").strip()
    res["clocks"] = " ".join((ssh("dmesg | grep 'LX frequency' | tail -1") or "").split()[-6:])
    for attempt in (1, 2):   # one retry only for a stalled flood (harness artefact, CAMPAIGN-PLAIN-7.4.md #147), never for noise
        rc, out = run([PY, str(ROOT / "scripts/ceiling_rxtx.py"), "--tag", tag, "--n", "1", "--sizes", "64,1400", "--modes", "rx", "--secs", "6"],
                      *CAPS["ceiling"])
        k = {int(s): float(v) for s, v in re.findall(r"SUMMARY rx (\d+) B: ([\d.]+) kpps", out)}
        if rc == 0 and k.get(1400, 0) >= 5:
            break
        res["detail"].append(f"rx attempt {attempt}: rc {rc} kpps {k}")
    res["kpps_1400"], res["kpps_64"] = k.get(1400, 0), k.get(64, 0)
    m = re.findall(r'"drops": (\{[^}]*\}|\[[^\]]*\])', (ROOT / "tmp/logs/ceiling_rxtx.jsonl").read_text().splitlines()[-1]) if (ROOT / "tmp/logs/ceiling_rxtx.jsonl").exists() else []
    res["drops"] = m[0] if m else ""
    rc, out = run([PY, str(ROOT / "scripts/zc_bench.py"), "--integrity"], *CAPS["integrity"])
    res["integrity"] = "PASS" if "INTEGRITY PASS" in out else "FAIL"
    alive = ssh("echo ok") is not None and subprocess.run(["ping", "-c", "2", "-W", "1", BENCH_IP], capture_output=True).returncode == 0
    t1 = ssh("cat /sys/class/thermal/thermal_zone0/temp")
    res["temp_after_mC"] = int((t1 or "0").strip() or 0)
    with CONSOLE.open("rb") as fh:
        fh.seek(mark)
        bad = BAD_CONSOLE.findall(fh.read())
    why = [w for ok, w in [(alive, "link dead after test"), (k.get(1400, 0) >= 5, "rx 1400 B stalled"), (res["integrity"] == "PASS", "integrity"),
                           (not bad, f"console {bad[:2]}")] if not ok]
    if why:
        res["result"], res["detail"] = ("HANG" if not alive else "FAIL"), res["detail"] + why
    return res


def record(domain: str, point: str, res: dict, gain: str = "") -> None:
    row = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "domain": domain, "point": point, "gain": gain, **res}
    row["detail"] = " | ".join(map(str, res.get("detail", [])))
    new = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="") as fh:
        w = csv.DictWriter(fh, COLS, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)
    log(f"[{domain}] {point}: {row['result']} 1400B {res.get('kpps_1400', '-')} kpps 64B {res.get('kpps_64', '-')} integrity {res.get('integrity', '-')} "
        f"temp {res.get('temp_after_mC', '-')} mC {row['detail']}")


def known() -> dict:
    if not CSV_PATH.exists():
        return {}
    with CSV_PATH.open() as fh:
        return {(r["domain"], r["point"]): r for r in csv.DictReader(fh)}


# ---- domains ----------------------------------------------------------------------------------
DOMAINS = {
    "switch-core": {"mode": "bisect", "key": "sw", "knob": "SW VCO e214 NCODE (code 1) + e220 LX/NOR, relock e200 b30", "stock": "408",
                    "points": ["408", "508", "575", "608", "658"], "unit": "MHz"},
    "lx-arb": {"mode": "scan", "key": "arb", "knob": "LX0..2_ARB_CFG0-3 0xB8000010-3C (reset 0x10101010)", "stock": "stock",
               "points": ["stock", "swap", "m1", "m0"], "unit": ""},
    "cpu": {"mode": "bisect", "key": "cpu", "knob": "turbo cpu=", "stock": 800, "points": [800, 1000, 1050] + list(range(1100, 1426, 25)), "unit": "MHz"},
    "ddr": {"mode": "bisect", "key": "ddr", "knob": "turbo ddr=", "stock": 600, "points": [600, 625, 650, 662, 675, 700, 725, 750, 775, 800], "unit": "MHz"},
    "sram": {"mode": "scan", "key": "br", "knob": "CPU_SRAM_ASY_TIMING 0x40f8, CMUCR_OC0 0x388 b9 (turbo sram= already 500)", "stock": "stock",
             "points": ["stock", "pulse_dn", "pulse_up", "oc0_dram_flip"], "unit": ""},
}
EST_POINT_S = 150   # boot ~45 s + setup 8 s + rx 2 x ~12 s + integrity ~25 s + ssh/reads ~15 s (estimate; csv timings replace it)


def settings_for(domain: str, value) -> dict:
    d = DOMAINS[domain]
    st = dict(PICKS)
    if CORE["sw"] and d["key"] != "sw":
        st["sw"] = CORE["sw"]
    st[d["key"]] = value if d["key"] in PICKS else str(value)
    return st


def bisect_plan(pts: list, passing) -> list:
    """Order tested under `passing(i)`; pts[0] = stock, known good."""
    good, bad, seq = 0, len(pts), []
    while good + 1 < bad:
        mid = (pts[good] + (pts[bad] if bad < len(pts) else pts[-1])) / 2
        i = min(range(good + 1, bad), key=lambda k: abs(pts[k] - mid))
        seq.append(pts[i])
        good, bad = (i, bad) if passing(i) else (good, i)
    return seq


def search(domain: str, a) -> int:
    d = DOMAINS[domain]
    pts = d["points"]
    nums = [float(p) for p in pts] if d["mode"] == "bisect" else None
    done = {} if a.fresh else known()

    def test(i):
        key = (domain, str(pts[i]))
        if key in done:
            log(f"[{domain}] {pts[i]}: resumed {done[key]['result']}")
            return done[key]["result"] == "PASS"
        res = quick(settings_for(domain, pts[i]), f"fs-{domain}-{pts[i]}", False, a.kernel)
        gain = ""
        if d["mode"] == "scan":
            gain = "yes" if res["result"] == "PASS" and res.get("kpps_1400", 0) >= BASE["kpps_1400"] * GAIN else "no"
        record(domain, str(pts[i]), res, gain)
        done[key] = {"result": res["result"]}
        return res["result"] == "PASS"

    if d["mode"] == "scan":
        for i in range(len(pts)):
            test(i)
        return 0
    good, bad = 0, len(pts)
    while good + 1 < bad:
        mid = (nums[good] + (nums[bad] if bad < len(pts) else nums[-1])) / 2
        i = min(range(good + 1, bad), key=lambda k: abs(nums[k] - mid))
        good, bad = (i, bad) if test(i) else (good, i)
    log(f"EDGE {domain}: fastest viable {pts[good]}, first failing {pts[bad] if bad < len(pts) else 'none (max passed)'} (one quick test per point)")
    return 0


def dry_plan(domain: str, a) -> None:
    d = DOMAINS[domain]
    pts = d["points"]
    log(f"PLAN {domain}: {d['mode']} over {pts} (stock {d['stock']}), knob: {d['knob']}")
    if d["mode"] == "bisect":
        nums = [float(p) for p in pts]
        log(f"  all-pass path: {bisect_plan(nums, lambda i: True)}; all-fail path: {bisect_plan(nums, lambda i: False)}")
        first = bisect_plan(nums, lambda i: True)[0]
        k = next(p for p in pts if float(p) == first)
        quick(settings_for(domain, k), f"fs-{domain}-{k}", True, a.kernel)
    else:
        for p in pts:
            log(f"  candidate {p}: pre {pre_list(settings_for(domain, p), True)}")
        quick(settings_for(domain, pts[1]), f"fs-{domain}-{pts[1]}", True, a.kernel)
    n = len(bisect_plan([float(p) for p in pts], lambda i: True)) if d["mode"] == "bisect" else len(pts)
    log(f"  est. {n} points x {EST_POINT_S} s = {n * EST_POINT_S // 60} min (every point power-cycles: the kernel test needs a boot)")
    log(f"  caps: boot stall/total {CAPS['boot']}, ceiling {CAPS['ceiling']}, integrity {CAPS['integrity']}")
    log("  hang: next ramload restarts the board in software, relay only if no prompt (st1008_ramload.restart_board)")


def best(domain: str, rows: dict):
    d = DOMAINS[domain]
    ok = [p for p in d["points"] if (domain, str(p)) in rows and rows[(domain, str(p))]["result"] == "PASS"]
    if d["mode"] == "scan":
        ok = [p for p in ok if rows[(domain, str(p))]["gain"] == "yes"]
        return max(ok, key=lambda p: float(rows[(domain, str(p))]["kpps_1400"] or 0)) if ok else d["stock"]
    return ok[-1] if ok else d["stock"]


def combine(a) -> int:
    rows = known()
    chosen = {dm: best(dm, rows) for dm in ORDER}
    log(f"COMBINE best per domain: {chosen}")
    for drop in [None] + ORDER[::-1]:
        if drop:
            chosen[drop] = DOMAINS[drop]["stock"] if DOMAINS[drop]["key"] not in PICKS else PICKS[DOMAINS[drop]["key"]]
            log(f"COMBINE back-off: {drop} -> pick/stock")
        st = dict(PICKS)
        if CORE["sw"]:
            st["sw"] = CORE["sw"]
        for dm, v in chosen.items():
            st[DOMAINS[dm]["key"]] = v if DOMAINS[dm]["key"] in PICKS else str(v)
        res = quick(st, "fs-combo", a.dry_run, a.kernel)
        if a.dry_run:
            return 0
        record("combo", json.dumps(chosen), res)
        if res["result"] == "PASS":
            log(f"COMBINATION OK. load-test settings: ./dev.py load-test --settings \"{res['settings']}\"")
            return 0
    log("COMBINATION: nothing passed, even the picks")
    return 1


def discover(dry: bool) -> int:
    from st1008_ramload import Console   # noqa: PLC0415
    pre = [f"turbo cpu={PICKS['cpu']},ddr={PICKS['ddr']},lx={PICKS['lx']},sram={PICKS['sram']}"]
    rc, _ = run([PY, DEVPY, "ramload", "uboot-mainline", "--stock-clocks"], *CAPS["boot"], dry=dry)
    if dry or rc not in (0, 1):
        return rc
    con, out = Console(), {}
    prompt = r"\r?\nst1008f-mainline # "
    con.run(pre[0], prompt, 3, "turbo picks")
    for name, addr in (("40f8", "0xb80040f8"), ("0388", "0xb8000388"), ("000c", "0xb800000c")):
        _, t = con.run(f"md.l {addr} 1", rf"(?s){addr[2:]}: [0-9a-f]{{8}}.*?{prompt}", 2, f"md {addr}")
        out[name] = "0x" + re.search(rf"{addr[2:]}: ([0-9a-f]{{8}})", t).group(1)
    for a_ in HOST_ARB:
        _, t = con.run(f"md.l {a_} 1", rf"(?s){a_[2:]}: [0-9a-f]{{8}}.*?{prompt}", 2, f"md {a_}")
        out[a_[-2:]] = "0x" + re.search(rf"{a_[2:]}: ([0-9a-f]{{8}})", t).group(1)
    REGS.write_text(json.dumps(out, indent=1))
    log(f"DISCOVER at picks: {out}")
    return 0


def write_doc() -> None:
    rows = known()
    lines = ["| domain | knob | stock | pick | max tried | fastest viable | date/conditions |", "|---|---|---|---|---|---|---|"]
    for dm in ORDER:
        d = DOMAINS[dm]
        tried = [p for p in d["points"] if (dm, str(p)) in rows]
        when = max((rows[(dm, str(p))]["when"] for p in tried), default="not run")
        pick = PICKS.get(d["key"], "stock" if d["mode"] == "scan" else "408")
        lines.append(f"| {dm} | {d['knob'].split(',')[0][:40]} | {d['stock']} | {pick} | {tried[-1] if tried else '-'} | "
                     f"{best(dm, rows) if tried else '-'} | {when[:10]} picks, 1 quick test/point |")
    text = DOC.read_text()
    new = re.sub(r"(<!-- RESULTS-BEGIN -->\n).*?(<!-- RESULTS-END -->)", lambda m: m.group(1) + "\n".join(lines) + "\n" + m.group(2), text, flags=re.S)
    DOC.write_text(new)
    log(f"results table written to {DOC}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--domain", choices=ORDER, help="default: all in order")
    ap.add_argument("--ip", default=BENCH_IP, help="must be the bench unit")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print plan, commands and caps; touch nothing")
    ap.add_argument("--write-doc", action="store_true")
    ap.add_argument("--combine", action="store_true")
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--fresh", action="store_true", help="ignore the csv (no resume)")
    ap.add_argument("--kernel", default=KERNEL, help="TFTP-root kernel file")
    ap.add_argument("--core", choices=list(SWC), help="fixed switch-core point for every test (608 = recommended max)")
    ap.add_argument("--pick", help="override the other-domain values, e.g. cpu=1400,ddr=700,lx=306,sram=500")
    ap.add_argument("--once", action="store_true", help="one quick test at --core / --pick / --arb / --br, then exit")
    ap.add_argument("--base", type=float, help="scan gain baseline: rx-only 1400 B kpps of the unmodified picks at this core (default 143.3 = core 408)")
    ap.add_argument("--arb", default="stock")
    ap.add_argument("--br", default="stock")
    a = ap.parse_args()
    if a.ip == SW1_IP or a.ip != BENCH_IP:
        print(f"refused: {a.ip} is not the bench unit sw2 ({BENCH_IP})", file=sys.stderr)
        return 2
    global CSV_PATH
    CORE["sw"] = a.core
    if a.base:
        BASE["kpps_1400"] = a.base
    if a.core:
        CSV_PATH = ROOT / f"tmp/logs/fastest_search_core{a.core}.csv"   # rows are only comparable at the same core
    for kv in (a.pick.split(",") if a.pick else []):
        PICKS[kv.split("=")[0]] = int(kv.split("=")[1])
    if a.once:
        st = {**PICKS, "arb": a.arb, "br": a.br, **({"sw": a.core} if a.core else {})}
        res = quick(st, "fs-once", a.dry_run, a.kernel)
        if not a.dry_run:
            record("once", json.dumps(st), res)
        return 0 if res["result"] == "PASS" else 1
    if a.list:
        for dm in ORDER:
            d = DOMAINS[dm]
            n = len(bisect_plan([float(p) for p in d["points"]], lambda i: True)) if d["mode"] == "bisect" else len(d["points"])
            print(f"{dm:12} {d['mode']:6} {d['knob']}\n{'':12} points {d['points']}  ~{n} tests, ~{n * EST_POINT_S // 60} min")
        return 0
    if a.write_doc:
        write_doc()
        return 0
    if a.discover:
        return discover(a.dry_run)
    if a.combine:
        return combine(a)
    for dm in [a.domain] if a.domain else ORDER:
        if a.dry_run:
            dry_plan(dm, a)
        else:
            search(dm, a)
    return 0


if __name__ == "__main__":
    sys.exit(main())
