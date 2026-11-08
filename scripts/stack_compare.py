#!/usr/bin/env python3
"""stack_compare — identical NAT bench on three stacks (A upstream OpenWrt, B ours OpenWrt, C plain kernel); DRY-RUN ONLY.

- Plan: docs/NAT-STACK-TESTS.md. Prints every command per stack x clock set; `--run` is refused until the owner releases it.
- Stacks: A = `openwrt-upstream` (snapshot as shipped), B = `openwrt-ours-l3fix2`, C = `mainline-kernel --kernel <clean image>`.
- Clock sets: common = core 508 / CPU 1350 / DDR 662 / LX 306 / SRAM 500; final = core 608 / CPU 1325 (LX 304-306).
- Profile `clean`: tracing off (numbers). Profile `profile`: perf (+ ftrace on C) on, one diagnosis run per stack.
- Log: tmp/logs/stack_compare.log. Reuses nat_bench.py / zc_bench.py / l3_offload_ab.py commands unchanged.
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/stack_compare.log"
PY = "python3"
TURBO = {"common": "turbo cpu=1350,ddr=662,lx=306,sram=500", "final": "turbo cpu=1325,ddr=662,lx=306,sram=500"}
RAW = {  # core 508 (nat161_compare.py RAW) and core 608 (openwrt_core_stability.py c608_cpu1325: e220 0x36826)
    "common": "mw.l 0xbb00e220 0x30626; mw.l 0xbb00e214 0x3b8; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff",
    "final": "mw.l 0xbb00e220 0x36826; mw.l 0xbb00e214 0x3b8; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff",
}
# key: (label, ramload --then, extra ramload args, zc fast path present, L3 offload (300-17) present, tracing in the image)
STACKS = {
    "A": ("upstream OpenWrt snapshot r38188, Linux 6.18.60, no patches", "openwrt-upstream", ["--no-linkcheck"], False, False, "none (no PERF, no FTRACE)"),
    "B": ("ours: OpenWrt main r38178 + 7.4-rc1 + series (l3fix2)", "openwrt-ours-l3fix2", ["--no-linkcheck"], True, True, "PERF_EVENTS + PROFILING compiled in, no FTRACE"),
    "C": ("plain Linux 7.4-rc1 + series, bench initramfs", "mainline-kernel", ["--kernel", "mainline-7.4-rc1-clean.bin", "--mgmt"], True, True, "clean image: none"),
}
PROFILE_IMG = {"C": ["--kernel", "mainline-7.4-rc1.bin", "--mgmt"]}  # existing image: PERF + FTRACE + function_graph compiled in
SECS = 15


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def nb(*a):
    return f"{PY} scripts/nat_bench.py " + " ".join(map(str, a))


def matrix(stack, with_zc, with_l3):
    """(est_seconds, command) per cell; the same cell list for every stack, cells a stack lacks are skipped and logged."""
    cells = [(20, nb("setup"))]
    for mode in ("nat", "nat-ft"):
        cells.append((5, nb("mode", mode)))
        for p in (1, 2, 4):
            for rev in (False, True):
                cells.append((27, nb("run", "--secs", SECS, "-P", p, *(["--reverse"] if rev else []), "--label", f"{stack}-{mode}-P{p}")))
    cells.append((5, nb("mode", "route")))
    for ln, mbit in ((1400, 900), (64, 100)):
        cells.append((27, nb("run", "--secs", 10, "--udp", mbit, "--len", ln, "--label", f"{stack}-stack-udp{ln}")))
    for ln in (500,):  # 64 and 1400 are the two UDP cells above
        cells.append((27, nb("run", "--secs", 10, "--udp", 900, "--len", ln, "--label", f"{stack}-stack-udp{ln}")))
    if with_l3:
        cells.append((300, f"{PY} scripts/l3_offload_ab.py -n 1 --only v4-onlink,v4-default --secs 10 --clocks \"<clock line>\"  # off then on; l3.c module params"))
    else:
        cells.append((0, f"# {stack}: no L3 offload module (not in this build): routed L3 off only, covered by the route cells above"))
    if with_zc:
        cells.append((5, nb("mode", "nat-ft")))
        cells.append((150, f"{PY} scripts/zc_bench.py --tcp --nat --napi irq1 --secs {SECS}  # zc+nat TCP P4 fwd/rev"))
        for ln in (64, 500, 1400):
            cells.append((40, f"{PY} scripts/zc_bench.py --nat --len {ln} --napi irq1 --secs 10  # zc UDP, frame-size sweep"))
    else:
        cells.append((0, f"# {stack}: no zc fast path (300-39) in this build: zc cells skipped"))
    return cells


def plan(stack, clk, profile):
    label, then, extra, zc, l3, tracing = STACKS[stack]
    if profile == "profile" and stack == "A":
        return 0, [f"# A has no PERF/FTRACE compiled in: no profile run"]
    img = extra if not (profile == "profile" and stack in PROFILE_IMG) else PROFILE_IMG[stack]
    if stack == "C":
        boot = f"{PY} dev.py ramload uboot-mainline --stock-clocks --then mainline-kernel {' '.join(img)} --cage 1 --pre \"{TURBO[clk]}\" --pre \"{RAW[clk]}\""
    else:
        boot = f"{PY} dev.py ramload uboot-mainline --stock-clocks --then {then} {' '.join(extra)} --cage 1 --pre \"{TURBO[clk]}\" --pre \"{RAW[clk]}\""
    cmds = [(95, boot)]
    if profile == "clean":
        cmds += matrix(stack, zc, l3)
    else:  # one diagnosis run per stack: perf on the stack path (nat-ft P4) and, on C, function_graph of rteth
        cmds += [(20, nb("setup")), (5, nb("mode", "nat-ft")),
                 (60, f"{PY} scripts/nat_perf.py --tag stack-{stack} --test udp64-100 --callgraph  # perf record -a -e cpu-clock; needs perf_push.py first"),
                 (60, f"{PY} scripts/zc_bench.py --nat --len 1400 --perf --napi irq1" if zc else "# no zc")]
        if stack == "C":
            cmds.append((90, f"{PY} scripts/rteth_ftrace.py --depth 2  # function_graph, numbers inflated: never in a table with clean rows"))
    return sum(t for t, _ in cmds), [c for _, c in cmds]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stacks", default="A,B,C", help="subset of A,B,C")
    ap.add_argument("--clocks", default="common,final", help="common (core 508 / CPU 1350) and/or final (core 608 / CPU 1325)")
    ap.add_argument("--profile", default="clean", choices=["clean", "profile", "both"])
    ap.add_argument("--dry-run", action="store_true", default=True, help="always on: this script prints the plan only")
    ap.add_argument("--run", action="store_true", help="refused: hardware runs need the owner's release")
    a = ap.parse_args()
    if a.run:
        sys.exit("refused: dry-run only (NAT-STACK-TESTS.md); the owner releases hardware runs")
    total, boots = 0, 0
    for prof in (["clean", "profile"] if a.profile == "both" else [a.profile]):
        for clk in a.clocks.split(","):
            for s in a.stacks.split(","):
                if prof == "profile" and clk == "final":
                    continue  # profile runs at the common clocks only
                sec, cmds = plan(s, clk, prof)
                log(f"=== stack {s} ({STACKS[s][0]}) clocks {clk} profile {prof}; tracing in image: {STACKS[s][5]}; est {sec / 60:.0f} min")
                for c in cmds:
                    log("  " + c)
                total += sec
                boots += 1 if sec else 0
    log(f"TOTAL {boots} boots, est {total / 3600:.1f} h (1 run per cell, no repeats; add 2 repeats of the P4 cells: +~25 min per clean boot)")


if __name__ == "__main__":
    main()
