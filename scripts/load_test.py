#!/usr/bin/env python3
"""load_test — short functional load test of one settings string on sw2, plus the 'old options' re-test matrix (docs/FASTEST-SETTINGS.md).

- sw2 only (refuses sw1 / any IP but boards.BENCH_IP); `./dev.py load-test`. NO soaks: every stage is one short run with a stall cap.
- ONE NAT interface only (nat-bench setup: one WAN, one LAN); no multi-WAN / multi-interface case.
- Settings = the `--pre` list of fastest_search (`"turbo cpu=...|mw.l ..."`, items split by ` | `); `--picks`; `--no-boot` = test the running board.
- Stages: boot, sanity (ping/ssh/ARP/ICMP through the switch), NAT TCP P4 fwd + rev, zc UDP 1400 B + 64 B, integrity, ASIC drops, temperature,
  link flaps, console scan (Oops/BUG/panic/gro_list_prepare, #149), canary subset. Verdict PASS/WARN/FAIL per stage -> tmp/logs/load_test.csv.
- `--options all|retest|name,...`: each option (kernel knob / boot arg + its earlier bench) vs a baseline of the SAME session at the same core clock
  (--core LABEL); rows -> tmp/logs/load_test_options.csv; VPE0/VPE1 busy and the saturated VPE recorded. `retest` = options that did not win at 408.
    load_test.py --list | --picks|--settings S [--no-boot] [--options all] [--core 408] [--dry-run] | --options-table
"""
from __future__ import annotations

import argparse
import csv
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fastest_search as fs  # noqa: E402
from retest_options import parse_zc  # noqa: E402  (one zc_bench parser; the manual boot/meas flow lives there)
from boards import BENCH_IP, SW1_IP  # noqa: E402

ROOT = fs.ROOT
CSV_PATH = ROOT / "tmp/logs/load_test.csv"
OPT_CSV = ROOT / "tmp/logs/load_test_options.csv"
LOG = ROOT / "tmp/logs/load_test.log"
fs.LOG = LOG
PY = sys.executable
Z = str(ROOT / "scripts/zc_bench.py")
P = "/sys/module/rtl838x_eth/parameters"
# Baselines: docs/CAMPAIGN-PLAIN-7.4.md (zc forwarding 1400 B, #147 rx-only, stack rate). None = no number in the docs: first run seeds it.
BASE = {"picks": {"zc1400": 143.0, "rx1400": 143.3, "rx64": 228.3, "stack1400": 62.1, "tcp_fwd": None, "tcp_rev": None},
        "stock": {"zc1400": 119.4, "rx1400": 143.5, "rx64": None, "stack1400": 44.4, "tcp_fwd": None, "tcp_rev": None}}
ZC_ARGS = ["--nat", "--zc-only", "--napi", "irq1", "--secs", "6"]
# stage: (stall s, total s, basis). zc_bench run cap = secs*3+30 inside; ceiling/integrity caps from fastest_search (measured in swcore_step logs).
CAPS = {"sanity": (40, 90, "nat-bench setup ~8 s + 3 pings + ssh <10 s, x3"),
        "tcp": (60, 120, "10 s iperf + ramp + counter dumps ~25 s measured by zc_bench cap secs*6+60"),
        "udp": (60, 100, "6 s flood + setup + dumps ~20 s, x3"),
        "integrity": fs.CAPS["integrity"] + ("3 lengths x ~7 s, x4",),
        "canary": (60, 300, "selftest 21 s + gdma 1 s + dss + pre + bootlog (canary CHECKS caps)")}
STAGE_COLS = ["when", "tag", "stage", "verdict", "value", "baseline", "vpe0", "vpe1", "temp_before_mC", "temp_after_mC", "flaps", "drops", "settings", "detail"]
OPT_COLS = ["when", "option", "variant", "core", "base_kpps", "kpps", "verdict", "base_vpe0", "base_vpe1", "vpe0", "vpe1", "saturated", "settings", "detail"]


def csv_add(path: Path, cols: list[str], row: dict) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="") as fh:
        w = csv.DictWriter(fh, cols, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerow(row)


def temp() -> int:
    t = fs.ssh("cat /sys/class/thermal/thermal_zone0/temp")
    return int(t.strip()) if t and t.strip() else 0


def carrier() -> dict:
    out = fs.ssh("for f in /sys/class/net/*/carrier_changes; do echo $f $(cat $f); done") or ""
    return {ln.split()[0].split("/")[4]: int(ln.split()[1]) for ln in out.splitlines() if len(ln.split()) == 2}


def vs_base(v: float | None, base: float | None) -> str:
    if v is None or v < 5:
        return "FAIL"
    if base is None:
        return "PASS"
    return "FAIL" if v < 0.9 * base else "WARN" if v < 0.97 * base else "PASS"


def saturated(v0, v1) -> str:
    if v0 is None:
        return "?"
    s = [n for n, v in (("VPE0", v0), ("VPE1", v1)) if v >= 95]
    return "+".join(s) if s else "neither (door-limited)"


def dry_cmds(a, st: str) -> None:
    pres = [p.strip() for p in st.split("|")]
    fs.run(fs.ramload_cmd(pres, a.kernel), *fs.CAPS["boot"], dry=True)
    for name, cmd in [("sanity", [PY, str(ROOT / "dev.py"), "nat-bench", "setup"]),
                      ("tcp fwd", [PY, str(ROOT / "dev.py"), "nat-bench", "run", "--secs", "10", "-P", "4", "--label", "lt-fwd"]),
                      ("tcp rev", [PY, str(ROOT / "dev.py"), "nat-bench", "run", "--secs", "10", "-P", "4", "--label", "lt-rev", "--reverse"]),
                      ("udp 1400", [PY, Z, *ZC_ARGS, "--len", "1400"]), ("udp 64", [PY, Z, *ZC_ARGS, "--len", "64"]),
                      ("integrity", [PY, Z, "--integrity"]),
                      ("canary", [PY, str(ROOT / "scripts/canary.py"), "--only", "pre,selftest,gdma,dss,bootlog", "--no-ramload"])]:
        c = CAPS["tcp" if name.startswith("tcp") else "udp" if name.startswith("udp") else name if name in CAPS else "sanity"]
        log(f"stage {name}: stall {c[0]} s total {c[1]} s ({c[2]})")
        fs.run(cmd, c[0], c[1], dry=True)


def log(msg: str) -> None:
    fs.log(msg)


def stage_row(a, st, stage, verdict, value="", base="", v0="", v1="", tb="", ta="", flaps="", drops="", detail="") -> None:
    csv_add(CSV_PATH, STAGE_COLS, dict(when=time.strftime("%Y-%m-%dT%H:%M:%S%z"), tag=a.tag, stage=stage, verdict=verdict, value=value, baseline=base,
                                       vpe0=v0, vpe1=v1, temp_before_mC=tb, temp_after_mC=ta, flaps=flaps, drops=drops, settings=st, detail=detail))
    log(f"STAGE {stage}: {verdict} value {value} baseline {base} VPE0/1 {v0}/{v1} temp {tb}->{ta} flaps {flaps} drops {drops} {detail}")


def load(a, st: str) -> int:
    import drop_counters as dc   # noqa: PLC0415
    pres = [p.strip() for p in st.split("|")]
    base = BASE["stock" if a.stock else "picks"]
    verdicts: list[str] = []
    mark = fs.conlen()
    if not a.no_boot:
        rc, out = fs.run(fs.ramload_cmd(pres, a.kernel), *fs.CAPS["boot"])
        if rc not in (0, 1):
            stage_row(a, st, "boot", "FAIL", detail=f"ramload rc {rc}: " + " ".join(out.strip().splitlines()[-2:]))
            return 1
    bogo = (fs.ssh("grep -i bogomips /proc/cpuinfo | head -1") or "").split(":")[-1].strip()
    stage_row(a, st, "boot", "PASS", detail=f"bogomips {bogo} (531 = 800 MHz, 664 = 1000, ~897 = 1350)")
    car0 = carrier()
    # sanity
    rc, out = fs.run([PY, str(ROOT / "dev.py"), "nat-bench", "setup"], *CAPS["sanity"][:2])
    ping = subprocess.run(["ping", "-c", "5", "-W", "1", BENCH_IP], capture_output=True, text=True)
    icmp = subprocess.run(["sudo", "-n", "ip", "netns", "exec", "natlan", "ping", "-c", "5", "-W", "1", "10.99.2.2"], capture_output=True, text=True)
    stage_row(a, st, "sanity", "PASS" if rc == 0 and ping.returncode == 0 and icmp.returncode == 0 else "FAIL",
              detail=f"setup rc {rc}; mgmt ping rc {ping.returncode}; ARP+ICMP natlan->natwan rc {icmp.returncode}")
    # tcp
    for rev in (False, True):
        key = "tcp_rev" if rev else "tcp_fwd"
        tb = temp()
        dc.snap()
        rc, out = fs.run([PY, str(ROOT / "dev.py"), "nat-bench", "run", "--secs", "10", "-P", "4", "--label", f"lt-{key}", *(["--reverse"] if rev else [])],
                         *CAPS["tcp"][:2])
        m = re.search(r"RESULT \S+: ([\d.]+) Mbit/s", out)
        v = float(m.group(1)) if m else None
        d = dc.delta([0] * dc.N, dc.snap())
        verdicts.append(vs_base(v, base[key]))
        stage_row(a, st, key, verdicts[-1], v, base[key], tb=tb, ta=temp(), drops=str(d)[:200], detail="Mbit/s, NAT TCP P4, one NAT interface")
    # udp
    for ln in (1400, 64):
        tb = temp()
        dc.snap()
        rc, out = fs.run([PY, Z, *ZC_ARGS, "--len", str(ln)], *CAPS["udp"][:2])
        k, v0, v1 = parse_zc(out)
        d = dc.delta([0] * dc.N, dc.snap())
        verdicts.append(vs_base(k, base.get(f"zc{ln}")))
        stage_row(a, st, f"udp{ln}", verdicts[-1], k, base.get(f"zc{ln}"), v0, v1, tb, temp(), drops=str(d)[:200], detail=f"zc+nat kpps; saturated {saturated(v0, v1)}")
    rc, out = fs.run([PY, Z, "--integrity"], *CAPS["integrity"][:2])
    verdicts.append("PASS" if "INTEGRITY PASS" in out else "FAIL")
    stage_row(a, st, "integrity", verdicts[-1], detail=" ".join(re.findall(r"INTEGRITY.*", out))[:150])
    # canary subset
    rc, out = fs.run([PY, str(ROOT / "scripts/canary.py"), "--only", "pre,selftest,gdma,dss,bootlog", "--no-ramload"], *CAPS["canary"][:2])
    verdicts.append("PASS" if rc == 0 else "FAIL")
    stage_row(a, st, "canary", verdicts[-1], detail=f"canary rc {rc}")
    # cross-cutting: flaps, temperature, console
    car1 = carrier()
    flaps = {k: car1[k] - car0.get(k, 0) for k in car1 if car1[k] != car0.get(k, 0)}
    stage_row(a, st, "flaps", "WARN" if flaps else "PASS", detail=str(flaps))
    t = temp()
    stage_row(a, st, "temperature", "FAIL" if t > fs.TEMP_MAX_MC else "WARN" if t > 80000 else "PASS", t / 1000, "85 C abort", ta=t)
    with fs.CONSOLE.open("rb") as fh:
        fh.seek(mark)
        bad = fs.BAD_CONSOLE.findall(fh.read())
    stage_row(a, st, "console", "FAIL" if bad else "PASS", detail=str(bad[:3]))
    allv = verdicts + (["FAIL"] if bad else []) + (["FAIL"] if t > fs.TEMP_MAX_MC else [])
    final = "FAIL" if "FAIL" in allv else "WARN" if "WARN" in allv or flaps else "PASS"
    log(f"LOAD TEST {final} for {st}")
    if a.options:
        return options(a, st) or (1 if final == "FAIL" else 0)
    return 1 if final == "FAIL" else 0


# ---- old options re-test matrix ----------------------------------------------------------------
RING = "mainline-7.4-rc1-ring.bin"
OPTIONS = {
    "ring_split": {"kind": "image", "kernel": RING, "args": "rtl838x_eth.cpuq0_drop_pages=1024", "bench": "ring",
                   "variants": ["rt0", "rt1", "par", "par_acl1"], "what": "300-43 two-ring split (ring_split_ab.py)"},
    "napi": {"kind": "runtime", "bench": "zc", "variants": [("irq1", "--napi irq1"), ("split", "--napi split")],
             "what": "NAPI placement: default irq vs softirq on VPE1 vs one threaded ring per VPE"},
    "tx_by_cpu": {"kind": "runtime", "bench": "zc", "variants": [("1", f"echo 1 > {P}/tx_by_cpu"), ("0", f"echo 0 > {P}/tx_by_cpu")],
                  "what": "TX ring + reclaim follow the forwarding CPU (300-38)", "default": f"echo 0 > {P}/tx_by_cpu"},
    "noqueue": {"kind": "runtime", "bench": "zc", "variants": [("noqueue", "tc qdisc replace dev eth0 root noqueue")],
                "what": "eth0 root qdisc noqueue", "default": "tc qdisc replace dev eth0 root mq 2>/dev/null; true"},
    "sram_rings": {"kind": "boot", "args": "rtl838x_eth.sram_rings=3", "bench": "zc", "variants": ["sram_rings=3"], "what": "NIC rings in SRAM (300-25)"},
    "zc_sync": {"kind": "runtime", "bench": "sync", "variants": ["base", "txfull", "rxpart"], "needs": f"{P}/zc_sync_bytes",
                "build": "parked 300-42 (zc_sync_bytes, zc_rx_part): rebuild with scripts/head_bench_build.py + 300-42", "what": "cache variants"},
    "cpuq": {"kind": "boot", "bench": "zc", "variants": ["rtl838x_eth.cpuq_drop_pages=0", "rtl838x_eth.cpuq_drop_pages=512"],
             "what": "CPU queue drop thresholds (300-40; read at open)"},
    "cpuq0": {"kind": "image", "kernel": RING, "bench": "zc", "variants": ["rtl838x_eth.cpuq0_drop_pages=1024"],
              "what": "queue-0 drop threshold; param exists only in the ring image (300-43)"},
    "zc_vs_stack": {"kind": "runtime", "bench": "zcstack", "variants": ["zc/stack"], "what": "zc fast path vs stack path"},
    "gro_list": {"kind": "runtime", "bench": "tcp", "variants": [("off", "for d in eth0 lan1; do ethtool -K $d rx-gro-list off; done")],
                 "default": "for d in eth0 lan1; do ethtool -K $d rx-gro-list on; done", "what": "GRO fraglist off (stack TCP path)"},
    "gdma": {"kind": "na", "what": "GDMA copy offload: n/a unless a copy exists in the NAT path (kmod/gdma_bench is a copy test)"},
}


def bench(kind: str, extra: str = "") -> tuple[float | None, float | None, float | None, str]:
    if kind == "tcp":
        rc, out = fs.run([PY, str(ROOT / "dev.py"), "nat-bench", "run", "--secs", "10", "-P", "4", "--label", "lt-opt"], *CAPS["tcp"][:2])
        m = re.search(r"RESULT \S+: ([\d.]+) Mbit/s", out)
        return (float(m.group(1)) if m else None), None, None, "Mbit/s"
    args = [x for x in ZC_ARGS if x not in ("--zc-only",)] if kind == "zcstack" else list(ZC_ARGS)
    if extra.startswith("--napi"):
        args[args.index("--napi") + 1] = extra.split()[1]
    rc, out = fs.run([PY, Z, *args, "--len", "1400"], *CAPS["udp"][:2])
    return (*parse_zc(out), "kpps")


def options(a, st: str) -> int:
    names = list(OPTIONS) if a.options == "all" else retest_names() if a.options == "retest" else a.options.split(",")
    pres = [p.strip() for p in st.split("|")]
    log(f"OPTIONS at core {a.core}: {names}")
    fs.run([PY, str(ROOT / "dev.py"), "nat-bench", "setup"], *CAPS["sanity"][:2])
    b0 = bench("zc")
    log(f"session baseline (default state, core {a.core}): {b0}")
    for n in names:
        o = OPTIONS[n]
        if o["kind"] == "na":
            csv_add(OPT_CSV, OPT_COLS, dict(when=time.strftime("%Y-%m-%dT%H:%M:%S%z"), option=n, core=a.core, verdict="n/a", detail=o["what"]))
            log(f"option {n}: n/a - {o['what']}")
            continue
        if o.get("needs") and "y" not in (fs.ssh(f"[ -e {o['needs']} ] && echo y; true") or ""):
            log(f"option {n}: SKIPPED, image lacks {o['needs']}; build needed: {o['build']}")
            csv_add(OPT_CSV, OPT_COLS, dict(when=time.strftime("%Y-%m-%dT%H:%M:%S%z"), option=n, core=a.core, verdict="needs build", detail=o["build"]))
            continue
        for v in o["variants"]:
            label, arg = (v if isinstance(v, tuple) else (v, v))
            if o["kind"] in ("image", "boot"):
                args = " ".join(x for x in (o.get("args"), arg if arg.startswith("rtl838x_eth.") else None) if x)
                rc, _ = fs.run(fs.ramload_cmd(pres, o.get("kernel") or a.kernel, args), *fs.CAPS["boot"])
                if rc not in (0, 1):
                    csv_add(OPT_CSV, OPT_COLS, dict(when=time.strftime("%Y-%m-%dT%H:%M:%S%z"), option=n, variant=label, core=a.core, verdict="FAIL", detail=f"boot rc {rc}"))
                    continue
                fs.run([PY, str(ROOT / "dev.py"), "nat-bench", "setup"], *CAPS["sanity"][:2])
                b0 = bench("zc")   # no baseline carry-over across a reboot: new default-state baseline with this image/args is the option's own run
            elif not arg.startswith("--napi") and o["bench"] not in ("ring", "sync") and o["kind"] == "runtime" and not arg.startswith("zc/"):
                fs.ssh(arg)
            if o["bench"] == "ring":
                rc, out = fs.run([PY, str(ROOT / "scripts/ring_split_ab.py"), "--tag", f"lt-{a.core}", "--n", "1", "--variants", label], 90, 180)
                m = re.findall(rf"^\S*\s*{re.escape(label)}\s+mean\s+([\d.]+) kpps", out, re.M)   # SUMMARY line of ring_split_ab
                k, v0, v1 = (float(m[-1]) if m else None), None, None
                unit = "kpps (ring_split_ab, VPE busy in its log)"
            elif o["bench"] == "sync":
                rc, out = fs.run([PY, str(ROOT / "scripts/zc_sync_ab.py"), "--tag", f"lt-{a.core}", "--n", "1", "--variants", label, "--lens", "1400"], 90, 180)
                m = re.findall(rf"{re.escape(label)}\s+1400 B: mean\s+([\d.]+) kpps", out)   # SUMMARY line of zc_sync_ab
                k, v0, v1 = (float(m[-1]) if m else None), None, None
            else:
                k, v0, v1, unit = bench(o["bench"], arg)
            if o.get("default"):
                fs.ssh(o["default"])
            bk = b0[0]
            verdict = "FAIL" if k is None else "wins" if bk and k >= bk * 1.03 else "loses" if bk and k <= bk * 0.97 else "ties"
            csv_add(OPT_CSV, OPT_COLS, dict(when=time.strftime("%Y-%m-%dT%H:%M:%S%z"), option=n, variant=label, core=a.core, base_kpps=bk, kpps=k, verdict=verdict,
                                            base_vpe0=b0[1], base_vpe1=b0[2], vpe0=v0, vpe1=v1, saturated=saturated(v0, v1), settings=st, detail=o["what"]))
            log(f"option {n}/{label}: {verdict} {k} vs {bk}; VPE0/1 {v0}/{v1}; saturated {saturated(v0, v1)}")
    return 0


def retest_names() -> list[str]:
    last: dict[str, str] = {}
    if OPT_CSV.exists():
        with OPT_CSV.open() as fh:
            for r in csv.DictReader(fh):
                if r["core"] == "408":
                    last[r["option"]] = r["verdict"] if last.get(r["option"]) != "wins" else "wins"
    return [n for n in OPTIONS if OPTIONS[n]["kind"] != "na" and last.get(n) != "wins"]


def table() -> None:
    rows = list(csv.DictReader(OPT_CSV.open())) if OPT_CSV.exists() else []
    print("| option | 408 result | best-core result | verdict | VPE0/VPE1 busy |\n|---|---|---|---|---|")
    for n, o in OPTIONS.items():
        mine = [r for r in rows if r["option"] == n]
        a = next((r for r in mine if r["core"] == "408"), None)
        b = [r for r in mine if r["core"] != "408"]
        b = b[-1] if b else None
        f = lambda r: "-" if not r else f"{r['variant']}: {r['kpps']} vs {r['base_kpps']}"   # noqa: E731
        last = b or a
        print(f"| {n} | {f(a)} | {f(b)} | {last['verdict'] if last else ('n/a' if o['kind'] == 'na' else '-')} | "
              f"{(last['vpe0'] + '/' + last['vpe1']) if last and last['vpe0'] else '-'} |")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settings", help="`--pre` items joined by ' | ' (fastest_search output)")
    ap.add_argument("--picks", action="store_true")
    ap.add_argument("--stock", action="store_true", help="compare with the stock baseline row (default: picks)")
    ap.add_argument("--no-boot", action="store_true")
    ap.add_argument("--options", help="all | retest | name,... (see --list)")
    ap.add_argument("--core", default="408", help="switch-core clock label of this session (options rows)")
    ap.add_argument("--kernel")
    ap.add_argument("--tag", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--ip", default=BENCH_IP)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--options-table", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.ip == SW1_IP or a.ip != BENCH_IP:
        print(f"refused: {a.ip} is not the bench unit sw2 ({BENCH_IP})", file=sys.stderr)
        return 2
    if a.list:
        for s, c in CAPS.items():
            print(f"stage {s:10} stall {c[0]} s, total {c[1]} s: {c[2]}")
        for n, o in OPTIONS.items():
            print(f"option {n:12} {o['kind']:8} {o['what']}")
        print("baselines:", BASE)
        return 0
    if a.options_table:
        table()
        return 0
    if a.picks:
        a.settings = fs.settings_string(dict(fs.PICKS))
    if not a.settings:
        ap.error("--settings S or --picks")
    if a.dry_run:
        dry_cmds(a, a.settings)
        if a.options:
            log(f"options {a.options}: " + str(list(OPTIONS) if a.options == 'all' else retest_names() if a.options == 'retest' else a.options.split(',')))
            for n, o in OPTIONS.items():
                log(f"  {n}: {o['kind']} {o['what']} variants {o.get('variants', '-')} kernel {o.get('kernel', '-')} args {o.get('args', '-')}")
        return 0
    return load(a, a.settings)


if __name__ == "__main__":
    sys.exit(main())
