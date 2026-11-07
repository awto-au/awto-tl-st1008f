#!/usr/bin/env python3
"""canary — one-command regression run of the existing sw2 checks in a fixed order (#138; docs/CANARY.md).

- Bench unit sw2 only: refuses 192.168.25.48 and any IP other than boards.BENCH_IP. Never touches sw1, relay or daemon directly.
- A) flash image: boot-link-check x3, hang-test, switch-check. B) plain kernel (ramload picks): selftest, vlanproto, gdma, dss, zc, boot log.
- Each check: own stall timeout (no output / console-log growth) + total cap; whole run has a backstop. Caps and basis in CHECKS.
- Verdicts PASS / WARN / FAIL / NOTRUN (not run is never a pass or a fail). Exit 0 = no FAIL, 1 = a FAIL, 2 = refused/usage.
- Baseline: scripts/canary_baseline.json (docs/CANARY.md). `--update-baseline` writes only after a full all-PASS run.
- `canary.py [--only a,b|ids] [--list] [--dry-run] [--update-baseline] [--no-ramload] [--selftest]`
- Output: tmp/logs/canary.log, one CSV row per run in tmp/logs/canary.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP, SW1_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/canary.log"
CSV_PATH = ROOT / "tmp/logs/canary.csv"
LOCK = ROOT / "tmp/canary.lock"
BASELINE = ROOT / "scripts/canary_baseline.json"
CONSOLE = ROOT / "private/serial/st1008-console.log"
UBOOT_LOG = ROOT / "tmp/logs/uboot_chain_env.log"
PY = sys.executable
DEVPY = str(ROOT / "dev.py")
CAMPAIGN = str(ROOT / "scripts/plain_campaign.py")
# whole run: sum of the typical times is ~12 min; sum of all caps ~34 min; backstop = 30 min
BACKSTOP_S = 1800
# final plain profile (owner 2026-11-07): CPU 1325, DDR 662, SRAM 500, switch core 608 via raw regs (LX ~304); --plain-turbo/--plain-raw override
PLAIN_TURBO = "turbo cpu=1325,ddr=662,lx=306,sram=500"
PLAIN_RAW = ("mw.l 0xbb00e220 0x36826; mw.l 0xbb00e214 0x478; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff")
BAD_CONSOLE = re.compile(rb"Oops|\bBUG\b|Kernel panic|gro_list_prepare")
FORBIDDEN = ["could not sync clock", "clock not ready, retry", "board silent", "board alive, console silent"]
V_ORDER = {"PASS": 0, "WARN": 1, "NOTRUN": 2, "FAIL": 3}

# id: (group, summary, stall s, total s, basis). Unmeasured caps are marked; secs in canary.csv tighten them.
CHECKS = {
    "boot_link": ("a", "boot-link-check x3: every cage up, no sync-clock/silent-console strings (#137 #138 #116)", 60, 540,
                  "60 s/round measured (CAMPAIGN-PLAIN-7.4 2026-11-07, 10 rounds in 10 min) x3 rounds x3; stall = console-log silence"),
    "hang_test": ("a", "SoC watchdog resets a board stuck in /bin/sh (#138)", 170, 400,
                  "silent window <= open_timeout 92 + 30 HW + 10 boot x1.25 = HANG_RESET_S 165; total = prompt ~35 + 165 + normal boot 60 + margin"),
    "switch": ("a", "switch-check on sw2: ping, ssh, bridge/STP, ports (read-only)", 45, 45,
               "ping wait 20 s + ssh connect 15 s bound in switch_check.py + commands <1 s"),
    "plain_boot": ("b", "ramload uboot-mainline -> mainline-kernel, picks clocks, cage 1, --mgmt", 60, 240,
                   "unmeasured: boot to shell 35-40 s (PLAIN-KERNEL-TESTS) + stock banner + kernel TFTP; stall = console-log silence"),
    "pre": ("b", "plain kernel up: uname, tools, debugfs/sysfs nodes present", 20, 30, "campaign pre cap 12 s + python start"),
    "prep": ("b", "perf push + NAT bench setup (needed by zc)", 40, 200, "unmeasured: campaign perf 25/90 + natsetup 30/90 (2 calls)"),
    "selftest": ("b", "boot self-test: memory, CPU, SRAM, clocks, registers, ASIC, SFP, flash (#108)", 45, 100,
                 "20-26 s measured (docs/SELFTEST.md; CAMPAIGN 21 s/20 s); campaign cap 35/80 + margin"),
    "vlanproto": ("b", "bridge vlan_protocol hook refuses 802.1ad with switch ports (patch 644)", 20, 30, "5 ip commands + ssh 5 s; campaign cap 10 s"),
    "gdma": ("b", "GDMA bench: 8 sizes bad 0 fails 0, 4096 B latency under ceiling (#62)", 25, 60, "ssh cat + insmod bench ~1 s; campaign cap 15/30"),
    "dss": ("b", "DSS probe: all 10 combos ready on poll 1 (die-speed sensors out of reset)", 40, 40,
            "ready-at-once = ssh + 10 combos < 5 s x8; a never-ready run is FAIL anyway (script bound 120 s)"),
    "zc": ("b", "zero-copy UDP 1400 B rate within tolerance of baseline; no panic under perf (#149)", 45, 330,
           "campaign zc cap 35/135 per run (UDP 10-12 s x2 + perf 15 s ~45 s) x --zc-n 2 + margin"),
    "bootlog": ("b", "boot log of the plain boot passes the allowlist (check-log)", 20, 40, "local scan <2 s; campaign cap 15/30"),
    "consolescan": ("b", "console log delta since phase B start has no Oops/BUG/Kernel panic/gro_list_prepare", 5, 10, "host-only file scan"),
}
ORDER = list(CHECKS)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


# ---------------------------------------------------------------- pure verdict logic (tested by --selftest)
def count_forbidden(*texts: str) -> dict[str, int]:
    return {s: sum(t.count(s) for t in texts) for s in FORBIDDEN}


def judge_boot_link(rc: int, out: str, extra: str, rounds: int) -> tuple[str, str, dict]:
    cnt = count_forbidden(out, extra)
    bad = {k: v for k, v in cnt.items() if v}
    ok_rounds = len(re.findall(r"round \d+: up .*missing none", out))
    bounces = sum(int(x) for x in re.findall(r"linkwatch bounces (\d+)", out))
    d = f"rounds ok {ok_rounds}/{rounds}, forbidden {bad or 0}, linkwatch bounces {bounces}"
    if rc in (124, 125):
        return "FAIL", f"killed ({'stall' if rc == 124 else 'total'}); " + d, {}
    if rc != 0 or ok_rounds != rounds or bad:
        return "FAIL", f"rc {rc}; " + d, {}
    return ("WARN" if bounces else "PASS"), d, {}


def judge_hang(rc: int, out: str, base: dict) -> tuple[str, str, dict]:
    m = re.search(r"reset (\d+) s after /bin/sh started", out)
    secs = int(m[1]) if m else None
    if rc in (124, 125):
        return "FAIL", f"killed ({'stall' if rc == 124 else 'total'}): no watchdog reset in time (#138)", {}
    if rc != 0 or "PASS hang-test" not in out or secs is None:
        return "FAIL", f"rc {rc}, no reset/normal boot confirmed: " + " ".join(out.split()[-14:]), {}
    warn = base.get("warn_above_s", 130)
    exp = base.get("reset_s")
    d = f"reset {secs} s after /bin/sh (baseline {exp if exp is not None else 'none'} s, warn above {warn} s)"
    return ("WARN" if secs > warn else "PASS"), d, {"hang_reset_s": secs}


def judge_gdma(verdict: str, detail: str, base: dict) -> tuple[str, str, dict]:
    m = re.search(r"4k gdma (\d+) ns", detail)
    ns = int(m[1]) if m else None
    if verdict != "PASS" or ns is None:
        return "FAIL", detail or verdict, {}
    mx = base["max_ns_4096"]
    if ns > mx:
        return "FAIL", f"4096 B {ns} ns > ceiling {mx} ns (baseline {base['ns_4096']}); {detail}", {"gdma_ns_4096": ns}
    return "PASS", f"4096 B {ns} ns <= {mx} ns, bad+fails 0", {"gdma_ns_4096": ns}


def judge_zc(runs: list[tuple[str, str]], base: dict) -> tuple[str, str, dict]:
    rates = []
    for v, d in runs:
        m = re.search(r"zc ([\d.]+) kpps", d)
        if v != "PASS" or not m:
            return "FAIL", f"zc run {v}: {d}", {}
        rates.append(float(m[1]))
    if not rates:
        return "FAIL", "no zc run reported", {}
    med = statistics.median(rates)
    b, tol = base["kpps_1400"], base["tol_pct"]
    dev = (med - b) / b * 100
    d = f"{med:.1f} kpps (runs {', '.join(f'{r:.1f}' for r in rates)}) vs baseline {b} kpps: {dev:+.1f} % (tol +-{tol} %)"
    met = {"zc_kpps": round(med, 1)}
    if dev < -tol:
        return "FAIL", d, met
    if dev > tol:
        return "WARN", d + " (faster: baseline stale?)", met
    return "PASS", d, met


def judge_dss(rc: int, out: str, base: dict) -> tuple[str, str, dict]:
    rows = re.findall(r"ws=\d rs=\d ctrl=\S+ polls=(\d+) ", out)
    slow = [p for p in rows if int(p) != base["polls"]]
    d = f"rows {len(rows)}, not on poll {base['polls']}: {len(slow)}"
    return ("PASS" if rc == 0 and len(rows) == 10 and not slow else "FAIL"), d, {}


def judge_scan(data: bytes) -> tuple[str, str, dict]:
    hits = BAD_CONSOLE.findall(data)
    if hits:
        return "FAIL", f"{len(hits)} hit(s): {sorted({h.decode()[:30] for h in hits})}", {}
    return "PASS", f"{len(data)} bytes scanned, 0 hits", {}


def campaign_step(out: str, step: str) -> list[tuple[str, int, str, str]]:
    """VERDICT lines of one plain_campaign step: (verdict, iter, secs, detail)."""
    return [(m[2], int(m[1]), m[4], m[5].strip())
            for m in re.finditer(rf"VERDICT canary {step}#(\d+): (\w+) rc=(-?\d+) (\d+)s (.*)", out)]


def worst(vs: list[str]) -> str:
    return max(vs, key=lambda v: V_ORDER[v]) if vs else "FAIL"


def judge_campaign(out: str, rc: int, step: str) -> tuple[str, str]:
    """One campaign step -> (verdict, detail of the last line); SKIP -> NOTRUN, STALL/TOTAL/ERRORS -> FAIL."""
    rows = campaign_step(out, step)
    if rc in (124, 125) and not rows:
        return "FAIL", f"killed ({'stall' if rc == 124 else 'total'}) before a verdict"
    if not rows:
        return "FAIL", "no VERDICT line: " + " ".join(out.split()[-12:])
    if any(r[0] == "SKIP" for r in rows):
        return "NOTRUN", rows[-1][3]
    vs = ["PASS" if r[0] == "PASS" else "FAIL" for r in rows]
    return worst(vs), rows[-1][3]


def ensure_ssh(ip: str) -> bool:
    """Plain kernel has no dropbear at boot: start it via the console, up to 4 tries (ssh <= 8 s connect + console send 4 s each)."""
    import subprocess
    ssh = ["ssh", "-o", "ConnectTimeout=8", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", f"root@{ip}", "true"]
    for _ in range(4):
        if subprocess.run(ssh, capture_output=True, timeout=12).returncode == 0:
            return True
        subprocess.run([PY, str(ROOT / "scripts/switch_console.py"), "send", "dropbear -R -B", "--secs", "4"], capture_output=True, timeout=20)
    return False


def row_cols() -> list[str]:
    return ["ts", "overall", *ORDER, "zc_kpps", "gdma_ns_4096", "hang_reset_s", "secs"]


# ---------------------------------------------------------------- running
def refuse(ip: str) -> None:
    if ip == SW1_IP:
        print(f"refused: {ip} is sw1 (in-service house switch)", file=sys.stderr)
        sys.exit(2)
    if ip != BENCH_IP:
        print(f"refused: {ip} is not the bench unit sw2 ({BENCH_IP})", file=sys.stderr)
        sys.exit(2)


def plan_cmds(a: argparse.Namespace, cid: str) -> list[list[str]]:
    c = lambda step: [PY, CAMPAIGN, "--tag", "canary", "--ip", a.ip, "--n", "1", "--steps", step]  # noqa: E731
    return {
        "boot_link": [[PY, DEVPY, "boot-link-check", "--rounds", str(a.rounds)]],
        "hang_test": [[PY, DEVPY, "uboot-chain-env", "hang-test", "--slot", "b"]],
        "switch": [[PY, str(ROOT / "scripts/switch_check.py"), "--ip", a.ip, "--wait", "20"]],
        "plain_boot": [[PY, DEVPY, "ramload", "uboot-mainline", *(["--stock-clocks"] if a.plain_raw else []), "--then", "mainline-kernel",
                       "--cage", "1", "--mgmt", "--pre", a.plain_turbo, *(["--pre", a.plain_raw] if a.plain_raw else [])]],
        "pre": [c("pre")],
        "prep": [c("perf"), c("natsetup")],
        "selftest": [c("selftest")],
        "vlanproto": [c("vlanproto")],
        "gdma": [c("gdma")],
        "dss": [[PY, str(ROOT / "scripts/dss_probe.py"), "--ip", a.ip, "--tag", "canary"]],
        "zc": [[PY, CAMPAIGN, "--tag", "canary", "--ip", a.ip, "--n", str(a.zc_n), "--steps", "zc"]],
        "bootlog": [c("checklog")],
        "consolescan": [],
    }[cid]


def select(only: str | None, no_ramload: bool) -> list[str]:
    ids = ORDER[:]
    if only:
        toks = [t.strip().lower() for t in only.split(",") if t.strip()]
        bad = [t for t in toks if t not in ("a", "b") and t not in CHECKS]
        if bad:
            sys.exit(f"unknown --only token(s): {bad}; groups a b, ids: {' '.join(ORDER)}")
        ids = [i for i in ORDER if CHECKS[i][0] in toks or i in toks]
    if no_ramload and "plain_boot" in ids:
        ids.remove("plain_boot")
    return ids


class Run:
    def __init__(self, a: argparse.Namespace, base: dict) -> None:
        self.a, self.base = a, base
        self.res: dict[str, tuple[str, str, float]] = {}
        self.met: dict[str, float] = {}
        self.dead = ""
        self.t0 = time.monotonic()
        self.mark_b = CONSOLE.stat().st_size if CONSOLE.exists() else 0

    def exec(self, cid: str, argv: list[str], watch: Path | None = None, total: int | None = None) -> tuple[int, str, float]:
        from plain_campaign import run_capped  # same stall/total killer as the campaign
        _, _, stall, cap, _ = CHECKS[cid]
        left = int(BACKSTOP_S - (time.monotonic() - self.t0))
        return run_capped(cid, argv, stall, min(total or cap, max(left, 1)), watch)

    def alive(self) -> bool:
        import subprocess
        return subprocess.run(["ping", "-c2", "-W1", self.a.ip], capture_output=True, timeout=5).returncode == 0  # 2 x 1 s

    def put(self, cid: str, v: str, d: str, secs: float) -> None:
        self.res[cid] = (v, d, secs)
        log(f"CHECK {cid}: {v} {secs:.0f}s {d}")
        if v == "FAIL" and not self.alive():
            self.dead = cid
            log(f"DEAD: {self.a.ip} does not answer ping after {cid}; remaining checks NOT RUN (no power action here)")

    def run_check(self, cid: str) -> None:
        a, b = self.a, self.base
        t = time.monotonic()
        if cid == "consolescan":
            data = CONSOLE.read_bytes()[self.mark_b:][:32 << 20] if CONSOLE.exists() else b""
            v, d, m = judge_scan(data)
            return self.put(cid, v, d, 0.0)
        cmds = plan_cmds(a, cid)
        if cid == "boot_link":
            m0 = CONSOLE.stat().st_size if CONSOLE.exists() else 0
            u0 = UBOOT_LOG.stat().st_size if UBOOT_LOG.exists() else 0
            rc, out, s = self.exec(cid, cmds[0], CONSOLE)
            extra = (CONSOLE.read_bytes()[m0:].decode("latin-1") if CONSOLE.exists() else "") + \
                    (UBOOT_LOG.read_bytes()[u0:].decode("latin-1") if UBOOT_LOG.exists() else "")
            v, d, m = judge_boot_link(rc, out, extra, a.rounds)
        elif cid == "hang_test":
            rc, out, s = self.exec(cid, cmds[0], CONSOLE)
            v, d, m = judge_hang(rc, out, b["hang_test"])
        elif cid == "switch":
            rc, out, s = self.exec(cid, cmds[0])
            v, d, m = ("PASS" if rc == 0 else "FAIL"), (out.strip().splitlines() or [""])[-1][-160:], {}
        elif cid == "plain_boot":
            rc, out, s = self.exec(cid, cmds[0], CONSOLE)
            v, d, m = ("PASS" if rc == 0 else "FAIL"), (out.strip().splitlines() or [""])[-1][-160:], {}
            if v == "PASS" and not ensure_ssh(a.ip):
                v, d = "FAIL", "booted, but ssh did not come up after dropbear via console"
        elif cid == "dss":
            rc, out, s = self.exec(cid, cmds[0])
            v, d, m = judge_dss(rc, out, b["dss"])
        elif cid == "prep":
            outs, vs, d = [], [], ""
            for step, argv in zip(("perf", "natsetup"), cmds):
                rc, out, s = self.exec(cid, argv, total=CHECKS[cid][3] // 2)
                sv, sd = judge_campaign(out, rc, step)
                vs.append(sv)
                d += f"{step} {sv}; "
                if sv != "PASS":
                    break
            v, m, s = worst(vs), {}, time.monotonic() - t
        elif cid == "zc":
            rc, out, s = self.exec(cid, cmds[0], total=135 * a.zc_n + 60)  # campaign total per run x n + margin
            rows = campaign_step(out, "zc")
            if not rows:
                v, d, m = "FAIL", "no VERDICT line: " + " ".join(out.split()[-12:]), {}
            else:
                v, d, m = judge_zc([(r[0], r[3]) for r in rows], b["zc"])
        else:  # single campaign step
            step = {"bootlog": "checklog"}.get(cid, cid)
            rc, out, s = self.exec(cid, cmds[0])
            if cid == "gdma":
                v0, d0 = judge_campaign(out, rc, "gdma")
                if v0 == "NOTRUN":
                    v, d, m = v0, d0, {}
                else:
                    v, d, m = judge_gdma("PASS" if v0 == "PASS" else "FAIL", d0, b["gdma"])
            else:
                v, d = judge_campaign(out, rc, step)
                m = {}
        self.met.update(m)
        self.put(cid, v, d, time.monotonic() - t)


def lock() -> None:
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    if LOCK.exists():
        try:
            pid = int(LOCK.read_text())
            os.kill(pid, 0)
            print(f"refused: canary already running (pid {pid}, {LOCK})", file=sys.stderr)
            sys.exit(2)
        except (ValueError, ProcessLookupError):
            pass
    LOCK.write_text(str(os.getpid()))


def summary(res: dict, ids: list[str]) -> tuple[str, str]:
    allv = {i: res.get(i, ("NOTRUN", "", 0))[0] for i in ORDER}
    ran = [allv[i] for i in ids]
    overall = "FAIL" if "FAIL" in ran else ("NOTRUN" if "NOTRUN" in ran else ("WARN" if "WARN" in ran else "PASS"))
    n = lambda v: sum(1 for i in ids if allv[i] == v)  # noqa: E731
    line = f"canary {overall}: {n('PASS')} pass, {n('WARN')} warn, {n('FAIL')} fail, {n('NOTRUN')} not run of {len(ids)}"
    bad = [f"{i}={allv[i]}" for i in ids if allv[i] in ("FAIL", "WARN", "NOTRUN")]
    return overall, line + (" [" + ", ".join(bad) + "]" if bad else "")


def update_baseline(base: dict, met: dict, res: dict, ids: list[str], full: bool) -> tuple[dict | None, str]:
    """(new baseline or None, message). Only after a full run with every check PASS."""
    if not full or any(res.get(i, ("NOTRUN",))[0] != "PASS" for i in ORDER):
        return None, "baseline NOT updated: needs a full run (no --only) with every check PASS"
    new = json.loads(json.dumps(base))
    new["recorded"] = time.strftime("%Y-%m-%d")
    if "hang_reset_s" in met:
        new["hang_test"]["reset_s"] = met["hang_reset_s"]
    if "gdma_ns_4096" in met:
        new["gdma"]["ns_4096"] = met["gdma_ns_4096"]
        new["gdma"]["max_ns_4096"] = int(met["gdma_ns_4096"] * 1.25)
    if "zc_kpps" in met:
        new["zc"]["kpps_1400"] = met["zc_kpps"]
    diff = [f"  {k}.{kk}: {base[k].get(kk)} -> {new[k].get(kk)}" for k in ("hang_test", "gdma", "zc") for kk in new[k]
            if base[k].get(kk) != new[k].get(kk)]
    return new, "baseline diff:\n" + ("\n".join(diff) if diff else "  (no value changed)") + f"\n  recorded: {base['recorded']} -> {new['recorded']}"


def write_csv(res: dict, met: dict, overall: str, secs: float) -> None:
    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    new = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(row_cols())
        w.writerow([time.strftime("%Y-%m-%dT%H:%M:%S%z"), overall, *[res.get(i, ("NOTRUN",))[0] for i in ORDER],
                    met.get("zc_kpps", ""), met.get("gdma_ns_4096", ""), met.get("hang_reset_s", ""), f"{secs:.0f}"])


# ---------------------------------------------------------------- selftest
def selftest() -> int:
    n = 0

    def eq(got, want, what):
        nonlocal n
        n += 1
        if got != want:
            sys.exit(f"selftest FAIL {what}: got {got!r} want {want!r}")
    rnd = "".join(f"round {i}: up ['lan1']; missing none; linkwatch bounces 0\n" for i in (1, 2, 3))
    eq(judge_boot_link(0, rnd, "", 3)[0], "PASS", "boot_link ok")
    eq(judge_boot_link(0, rnd, "x could not sync clock y", 3)[0], "FAIL", "boot_link forbidden string")
    eq(judge_boot_link(0, rnd + "board silent (hang", "", 3)[0], "FAIL", "boot_link board silent in out")
    eq(judge_boot_link(0, rnd.replace("none", "['lan1']", 1), "", 3)[0], "FAIL", "boot_link missing cage")
    eq(judge_boot_link(0, rnd.replace("bounces 0", "bounces 1", 1), "", 3)[0], "WARN", "boot_link bounce")
    eq(judge_boot_link(124, rnd, "", 3)[0], "FAIL", "boot_link killed")
    hb = {"warn_above_s": 130, "reset_s": 6}
    eq(judge_hang(0, "  reset 6 s after /bin/sh started (x)\nPASS hang-test: a", hb)[0], "PASS", "hang pass")
    eq(judge_hang(0, "  reset 140 s after /bin/sh started\nPASS hang-test: a", hb)[0], "WARN", "hang slow")
    eq(judge_hang(1, "FAIL no reset", hb)[0], "FAIL", "hang fail")
    eq(judge_hang(124, "", hb)[0], "FAIL", "hang stall")
    eq(judge_hang(0, "  reset 6 s after /bin/sh started\nPASS hang-test: a", hb)[2], {"hang_reset_s": 6}, "hang metric")
    gb = {"ns_4096": 97800, "max_ns_4096": 122000}
    eq(judge_gdma("PASS", "reg True rows 8 bad+fails 0 4k gdma 97800 ns 41 MB/s cpu 1815 MB/s", gb)[0], "PASS", "gdma ok")
    eq(judge_gdma("PASS", "reg True rows 8 bad+fails 0 4k gdma 130000 ns 31 MB/s", gb)[0], "FAIL", "gdma slow")
    eq(judge_gdma("FAIL", "reg False rows 0", gb)[0], "FAIL", "gdma bad")
    zb = {"kpps_1400": 143.3, "tol_pct": 10}
    ok = ("PASS", "stack 62 kpps zc 142.5 kpps ratio 2.3x perf")
    eq(judge_zc([ok, ("PASS", "stack 62 kpps zc 143.8 kpps ratio 2x perf")], zb)[0], "PASS", "zc ok")
    eq(judge_zc([("PASS", "zc 120.0 kpps")], zb)[0], "FAIL", "zc low")
    eq(judge_zc([("PASS", "zc 160.0 kpps")], zb)[0], "WARN", "zc high")
    eq(judge_zc([("FAIL", "zc ? kpps")], zb)[0], "FAIL", "zc run fail")
    eq(judge_zc([], zb)[0], "FAIL", "zc none")
    rows = "".join(f"ws={i} rs=0 ctrl=0x1 polls=1 dss0=1 dss1=1 count0=5 count1=6\n" for i in range(10))
    eq(judge_dss(0, rows, {"polls": 1})[0], "PASS", "dss ok")
    eq(judge_dss(0, rows.replace("polls=1", "polls=4096", 1), {"polls": 1})[0], "FAIL", "dss notready")
    eq(judge_dss(0, rows[:-80], {"polls": 1})[0], "FAIL", "dss short")
    eq(judge_scan(b"all fine zc miss: 00")[0], "PASS", "scan clean")
    eq(judge_scan(b"x Kernel panic - not syncing")[0], "FAIL", "scan panic")
    eq(judge_scan(b"CPU 0 Unable to handle\nOops[#1]")[0], "FAIL", "scan oops")
    eq(judge_scan(b"DEBUG line")[0], "PASS", "scan DEBUG is not BUG")
    v = "2026-11-07T10:00:00+1100 VERDICT canary {s}#{i}: {v} rc=0 3s {d}\n"
    eq(judge_campaign(v.format(s="selftest", i=0, v="PASS", d="ok"), 0, "selftest"), ("PASS", "ok"), "campaign pass")
    eq(judge_campaign(v.format(s="gdma", i=0, v="SKIP", d="no .ko"), 0, "gdma")[0], "NOTRUN", "campaign skip")
    eq(judge_campaign(v.format(s="vlanproto", i=0, v="STALL", d="x"), 124, "vlanproto")[0], "FAIL", "campaign stall")
    eq(judge_campaign("nothing", 3, "pre")[0], "FAIL", "campaign no verdict")
    eq(judge_campaign("", 124, "pre")[1].startswith("killed"), True, "campaign killed")
    res = {i: ("PASS", "", 0) for i in ORDER}
    eq(summary(res, ORDER)[0], "PASS", "summary pass")
    res["zc"] = ("FAIL", "", 0)
    res["bootlog"] = ("NOTRUN", "", 0)
    eq(summary(res, ORDER)[0], "FAIL", "summary fail beats notrun")
    eq(summary({"gdma": ("PASS", "", 0)}, ["gdma"])[0], "PASS", "summary subset ignores unselected")
    eq(summary({}, ["gdma"])[0], "NOTRUN", "summary not run")
    base = json.loads(BASELINE.read_text())
    full = {i: ("PASS", "", 0) for i in ORDER}
    eq(update_baseline(base, {"zc_kpps": 1}, full, ORDER, False)[0], None, "update needs full run")
    eq(update_baseline(base, {"zc_kpps": 1}, {**full, "zc": ("WARN", "", 0)}, ORDER, True)[0], None, "update needs all PASS")
    nb, msg = update_baseline(base, {"zc_kpps": 140.0, "gdma_ns_4096": 100000, "hang_reset_s": 7}, full, ORDER, True)
    eq((nb is not None, "zc.kpps_1400: 143.3 -> 140.0" in msg, "hang_test.reset_s: None -> 7" in msg), (True, True, True), "update diff")
    eq(base["zc"]["kpps_1400"], 143.3, "update does not mutate input")
    ids = select("a", False)
    eq(ids, ["boot_link", "hang_test", "switch"], "select a")
    eq("plain_boot" in select("b", True), False, "select no-ramload")
    eq(select("zc,gdma", False), ["gdma", "zc"], "select ids")
    for ip in (SW1_IP, "192.168.25.1"):
        try:
            refuse(ip)
        except SystemExit:
            n += 1
        else:
            sys.exit(f"selftest FAIL refuse {ip}")
    refuse(BENCH_IP)
    print(f"canary selftest: {n} checks OK")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP, help="must be the bench unit")
    ap.add_argument("--only", help="groups a,b and/or check ids (see --list)")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print every command and cap, touch nothing")
    ap.add_argument("--update-baseline", action="store_true", help="after a full all-PASS run: write new values, print the diff")
    ap.add_argument("--no-ramload", action="store_true", help="plain kernel already booted (picks): skip plain_boot")
    ap.add_argument("--plain-turbo", default=PLAIN_TURBO, help="plain kernel: U-Boot turbo --pre line (default: final profile)")
    ap.add_argument("--plain-raw", default=PLAIN_RAW, help="plain kernel: raw switch-core --pre line, '' = none (default: core 608)")
    ap.add_argument("--rounds", type=int, default=3, help="boot-link-check rounds")
    ap.add_argument("--zc-n", type=int, default=2, help="zc runs (each under perf, the #149 trigger)")
    ap.add_argument("--selftest", action="store_true", help="unit tests of the verdict logic")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    refuse(a.ip)
    base = json.loads(BASELINE.read_text())
    ids = select(a.only, a.no_ramload)
    if a.list:
        print(f"{'id':12s} grp stall total  what")
        for i in ORDER:
            g, s, st, tt, why = CHECKS[i]
            print(f"{i:12s} {g:3s} {st:5d} {tt:5d}  {s}{'' if i in ids else '  [not selected]'}\n{'':27s}basis: {why}")
        print(f"backstop {BACKSTOP_S} s; sum of total caps {sum(CHECKS[i][3] for i in ORDER)} s; baseline {BASELINE.relative_to(ROOT)} ({base['recorded']})")
        return 0
    if a.dry_run:
        for i in ids:
            g, s, st, tt, why = CHECKS[i]
            print(f"[dry-run] {i}: stall {st} s, total {tt} s ({why})")
            for argv in plan_cmds(a, i) or [["(host-only) scan console log delta for " + BAD_CONSOLE.pattern.decode()]]:
                print("    $ " + " ".join(argv))
        print(f"[dry-run] backstop {BACKSTOP_S} s; baseline {base['recorded']}; board {a.ip} (sw2); no hardware touched")
        return 0
    lock()
    try:
        r = Run(a, base)
        log(f"=== canary on {a.ip}: {' '.join(ids)}")
        for i in ids:
            if r.dead:
                r.res[i] = ("NOTRUN", f"board dead after {r.dead}", 0)
            elif time.monotonic() - r.t0 > BACKSTOP_S:
                r.res[i] = ("NOTRUN", "run backstop reached", 0)
            elif i in CHECKS and CHECKS[i][0] == "b" and i != "plain_boot" and r.res.get("plain_boot", ("PASS",))[0] != "PASS":
                r.res[i] = ("NOTRUN", "plain_boot did not pass", 0)
            else:
                if i == "plain_boot":
                    r.mark_b = CONSOLE.stat().st_size if CONSOLE.exists() else 0
                r.run_check(i)
                continue
            log(f"CHECK {i}: NOTRUN {r.res[i][1]}")
        secs = time.monotonic() - r.t0
        overall, line = summary(r.res, ids)
        write_csv(r.res, r.met, overall, secs)
        log(line + f" in {secs:.0f} s; csv {CSV_PATH.relative_to(ROOT)}")
        if a.update_baseline:
            new, msg = update_baseline(base, r.met, r.res, ids, a.only is None and not a.no_ramload)
            print(msg)
            if new:
                BASELINE.write_text(json.dumps(new, indent=2) + "\n")
                log("baseline written; update docs/CANARY.md#baseline and commit both")
        return 1 if overall == "FAIL" else 0
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
