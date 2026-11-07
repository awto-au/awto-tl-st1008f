#!/usr/bin/env python3
"""zc_prefetch_ab — A/B of the RX-loop prefetch variants (300-44, #147) on a booted plain kernel.

- Precondition: `./dev.py ramload ... mainline-kernel --mgmt` done, `nat-bench setup` + `mode route` (done here unless --no-setup).
- Variants are runtime module parameters (zc_prefetch_desc, zc_prefetch_hdr); rounds interleave the variants to spread drift.
- Per run: `zc_bench.py --nat --napi irq1 --zc-only --secs S --len L`; kpps and VPE busy parsed from its log line.
- `--integrity` runs the payload pattern check per variant. Output: tmp/logs/zc_prefetch_ab.log, tmp/logs/zc_prefetch_ab.jsonl.
    python3 scripts/zc_prefetch_ab.py --tag pf1 [--n 3] [--dry-run]   (kernel: mainline-7.4-rc1-pf.bin, booted by retest_options.py boot)
"""
import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import nat_bench as nb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/zc_prefetch_ab.log"
JSONL = ROOT / "tmp/logs/zc_prefetch_ab.jsonl"
P = "/sys/module/rtl838x_eth/parameters"
VARIANTS = {  # name: (zc_prefetch_desc, zc_prefetch_hdr)
    "base": (0, 0),
    "desc": (1, 0),
    "hdr": (0, 1),
    "both": (1, 1),
}


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def setv(v):
    d, h = VARIANTS[v]
    nb.sw(f"echo {d} > {P}/zc_prefetch_desc; echo {h} > {P}/zc_prefetch_hdr; cat {P}/zc_prefetch_desc {P}/zc_prefetch_hdr")


def zc_run(ln, secs, extra=()):
    cmd = [sys.executable, str(ROOT / "scripts/zc_bench.py"), "--nat", "--napi", "irq1", "--secs", str(secs), "--len", str(ln), *extra]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=secs * 3 + 90)  # 12 s run + param writes + ssh; x3 + 90
    return r.stdout + r.stderr


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--secs", type=int, default=12)
    ap.add_argument("--variants", default="base,desc,hdr,both")
    ap.add_argument("--lens", default="1400,64")
    ap.add_argument("--integrity", action="store_true", default=True)
    ap.add_argument("--no-integrity", dest="integrity", action="store_false")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, touch nothing")
    ap.add_argument("--no-setup", action="store_true")
    a = ap.parse_args()
    if a.dry_run:
        for rnd in range(1, a.n + 1):
            for v in a.variants.split(","):
                log(f"DRY round {rnd} {v} {VARIANTS[v]}: set params, then zc_bench --nat --napi irq1 --zc-only --secs {a.secs} --len " + ",".join(a.lens.split(",")))
            if a.integrity:
                log(f"DRY round {rnd} integrity per variant (zc_bench --integrity, 1400 B)")
        return
    if nb.SW_IP == "192.168.25.48":
        sys.exit("refusing sw1")
    variants, lens = a.variants.split(","), [int(x) for x in a.lens.split(",")]
    if not a.no_setup:
        for sub in (["setup"], ["mode", "route"]):
            subprocess.run([str(ROOT / "dev.py"), "nat-bench", *sub], capture_output=True, text=True, timeout=240)  # ~20 ssh round trips
    res = {}
    for rnd in range(1, a.n + 1):
        for v in variants:
            setv(v)
            for ln in lens:
                out = zc_run(ln, a.secs, ["--zc-only"])
                m = re.search(r"zc\+nat: natwan rx \d+ pkts = ([\d.]+) kpps.*?zc_fwd (\d+) miss (\d+) busy (\d+).*?busy VPE0/VPE1 (\d+)/(\d+)%", out)
                if not m:
                    log(f"round {rnd} {v} {ln}: NO RESULT: {out[-300:]!r}")
                    continue
                k = float(m[1])
                res.setdefault((v, ln), []).append((k, int(m[6])))
                rec = dict(tag=a.tag, round=rnd, variant=v, len=ln, kpps=k, zc_fwd=int(m[2]), miss=int(m[3]), busy=int(m[4]), vpe0=int(m[5]), vpe1=int(m[6]))
                with JSONL.open("a") as fh:
                    fh.write(json.dumps(rec) + "\n")
                log(f"round {rnd} {v} {ln}: {k:.1f} kpps VPE0/1 {m[5]}/{m[6]}% zc_busy {m[4]}")
        if a.integrity:
            for v in variants:
                setv(v)
                out = zc_run(1400, 2, ["--integrity"])
                log(f"round {rnd} {v} integrity: " + " | ".join(re.findall(r"INTEGRITY.*", out)))
    log(f"SUMMARY {a.tag}")
    base = {ln: statistics.mean(x[0] for x in res.get(("base", ln), [(0, 0)])) for ln in lens}
    for v in variants:
        for ln in lens:
            r = res.get((v, ln))
            if not r:
                continue
            ks = [x[0] for x in r]
            mean = statistics.mean(ks)
            log(f"  {v:7s} {ln:5d} B: mean {mean:6.1f} kpps min {min(ks):6.1f} max {max(ks):6.1f} spread {(max(ks) - min(ks)) / mean * 100:4.1f}% "
                f"vs base {(mean / base[ln] - 1) * 100 if base[ln] else 0:+5.1f}% VPE1 {statistics.mean(x[1] for x in r):.0f}%")


if __name__ == "__main__":
    main()
