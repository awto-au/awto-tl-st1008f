#!/usr/bin/env python3
"""stack_compare — identical NAT bench on three stacks (A upstream OpenWrt, B ours OpenWrt, C plain kernel); DRY-RUN ONLY.

- Plan: docs/NAT-STACK-TESTS.md. Prints every command per stack x clock set; `--run` is refused until the owner releases it.
- Stacks: A = `openwrt-upstream` (snapshot as shipped), B = `openwrt-ours-clean` (profile runs: `openwrt-ours-l3fix2`), C = `mainline-kernel --kernel mainline-7.4-rc1-clean3.bin`. A7 (upstream + 7.4) cannot be built: NAT-STACK-TESTS.md.
- Clock sets: common = core 508 / CPU 1350 / DDR 662 / LX 306 / SRAM 500; final = core 608 / CPU 1325 (LX 304-306).
- Profile `clean`: tracing off (numbers). Profile `profile`: perf (+ ftrace on C) on, one diagnosis run per stack.
- Per boot: `stack_normalize.py` runs BEFORE the cells (pinned tools, services, ruleset, sysctls, RPS/XPS, qdisc, offloads, IRQ), a
  `--snapshot-only --tag post` after them (drift). GATE: the three snapshots are diffed; every difference is printed and written into
  the result header (tmp/logs/stack_compare_result-<ts>.txt); a difference not in stack_normalize.KNOWN = NOT CONTROLLED.
- Log: tmp/logs/stack_compare.log. Reuses nat_bench.py / zc_bench.py / l3_offload_ab.py commands unchanged.
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stack_normalize as sn  # noqa: E402

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
    "B": ("ours: OpenWrt main r38178 + 7.4-rc1 + series, clean profile", "openwrt-ours-clean", ["--no-linkcheck"], True, True, "none (no PERF, PROFILING, DYNAMIC_DEBUG, FTRACE)"),
    "C": ("plain Linux 7.4-rc1 + series, bench initramfs", "mainline-kernel", ["--kernel", "mainline-7.4-rc1-clean3.bin", "--mgmt"], True, True, "clean image (C-clean3: B's BusyBox/musl/dropbear/nft/ip/tc/ethtool + fw4 ruleset): none"),
}
PROFILE_IMG = {"C": ["--kernel", "mainline-7.4-rc1.bin", "--mgmt"]}  # existing image: PERF + FTRACE + function_graph compiled in
PROFILE_THEN = {"B": "openwrt-ours-l3fix2"}  # perf-enabled image (PERF_EVENTS + PROFILING + DYNAMIC_DEBUG)
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
        then = PROFILE_THEN.get(stack, then) if profile == "profile" else then
        boot = f"{PY} dev.py ramload uboot-mainline --stock-clocks --then {then} {' '.join(extra)} --cage 1 --pre \"{TURBO[clk]}\" --pre \"{RAW[clk]}\""
    cmds = [(95, boot), (60, f"{PY} scripts/stack_normalize.py --stack {stack} --napi irq1  # BEFORE every bench: pins tools, settings; writes tmp/logs/stack_snapshot-{stack}.json")]
    if profile == "clean":
        cmds += matrix(stack, zc, l3)
        cmds.append((5, f"{PY} scripts/stack_normalize.py --stack {stack} --snapshot-only --tag post  # drift check after the cells"))
    else:  # one diagnosis run per stack: perf on the stack path (nat-ft P4) and, on C, function_graph of rteth
        cmds += [(20, nb("setup")), (5, nb("mode", "nat-ft")),
                 (60, f"{PY} scripts/nat_perf.py --tag stack-{stack} --test udp64-100 --callgraph  # perf record -a -e cpu-clock; needs perf_push.py first"),
                 (60, f"{PY} scripts/zc_bench.py --nat --len 1400 --perf --napi irq1" if zc else "# no zc")]
        if stack == "C":
            cmds.append((90, f"{PY} scripts/rteth_ftrace.py --depth 2  # function_graph, numbers inflated: never in a table with clean rows"))
    return sum(t for t, _ in cmds), [c for _, c in cmds]



# ---- GATE: snapshots of the stacks diffed after normalisation -----------------------------------------------------------
# Intrinsic to the stacks under test (never aligned); listed in every result header.
BY_DESIGN = [
    "kernel generation: A Linux 6.18.60 (upstream main has no 7.4: A7 not buildable) vs B/C 7.4-rc1",
    "PREEMPT: A NONE (6.18), B/C VOLUNTARY (7.x MIPS has no NONE choice)",
    "patch set: A has none of 300-xx (rteth TX ring / BQL xmit_more / SRAM rings / DRAM prefetch / L3 offload / zc / CP0 timer from PLL)",
    "A CP0 timer rate from DT (no 300-05): host-timed Mbit/s valid, switch-side CPU % not comparable",
    "compiler: A OpenWrt toolchain, B GCC 14.4.0, C kernel by host GCC 16.2.1 (mips64-linux-gnu); userland all OpenWrt GCC 14.4.0",
    "OpenWrt base system (procd/ubusd/netifd/logd/urngd/hotplug/st1008f-linkwatch) on A and B, not C; A's kernel config is derived, not read",
    "free memory (initramfs size, kernel size)",
]


def load_snaps(stacks, d, tag=""):
    out = {}
    for s_ in stacks:
        p = d / f"stack_snapshot-{s_}{'-' + tag if tag else ''}.json"
        if p.exists():
            out[s_] = json.loads(p.read_text())
    return out


def trace_state(stacks, snaps):
    """Debug/perf/trace state per stack: build-time (STACKS table) and run-time probes of the snapshot."""
    lines = []
    for s_ in stacks:
        sn_ = snaps.get(s_, {})
        rt = {k[3:]: sn_.get(k, "?") for k in ("rt_perf", "rt_ftrace", "rt_dyndbg", "rt_kprobes", "rt_lockdep", "rt_schedstat", "rt_debugfs_mounted")}
        cfg = "config.gz present" if sn_.get("config_gz_sha256", "absent") not in ("absent", "") else "no config.gz"
        lines.append(f"  {s_}: build-time: {STACKS[s_][5]}; run-time: " + (" ".join(f"{k}={v}" for k, v in rt.items()) +
                     f"; current_tracer={sn_.get('rt_current_tracer', '?') or 'n/a'}; perf/trace-cmd running={sn_.get('rt_perf_processes', '?')}; {cfg}"
                     if sn_ else "no snapshot yet (run stack_normalize.py on the booted stack)"))
    return lines


def gate(stacks, snapdir, write=True):
    """Diff the stacks' snapshots; returns (controlled: bool|None, header lines). None = not evaluable (snapshots missing)."""
    snaps = load_snaps(stacks, snapdir)
    hdr = []
    missing = [s_ for s_ in stacks if s_ not in snaps]
    if missing:
        verdict, controlled = f"NOT CONTROLLED (not evaluated: no snapshot for {','.join(missing)})", None
        diffs = []
    else:
        diffs = sn.diff_snapshots(snaps)
        unlisted = [d for d in diffs if d[2] is None]
        controlled = not unlisted
        verdict = "CONTROLLED (all remaining differences listed)" if controlled else f"NOT CONTROLLED ({len(unlisted)} unlisted difference(s))"
    hdr.append(f"# GATE {time.strftime('%Y-%m-%dT%H:%M:%S%z')} stacks {','.join(stacks)}: {verdict}")
    hdr.append("# by design (never aligned):")
    hdr += [f"#   - {t}" for t in BY_DESIGN]
    hdr.append("# debug / perf / trace state per stack:")
    hdr += ["# " + ln for ln in trace_state(stacks, snaps)]
    hdr.append("# pinned (identical bytes pushed to every stack): " + ("; ".join(
        f"{s_}: {snaps[s_].get('sha_pinned', '?').replace(chr(10), ' ')[:400]}" for s_ in stacks[:1] if s_ in snaps) or "tmp/stack-tools/MANIFEST.txt"))
    hdr.append("# snapshot differences after normalisation:")
    for k, vals, why in diffs:
        short = {lab: (v if len(v) < 90 else v[:87] + "...").replace("\n", " | ") for lab, v in vals.items()}
        hdr.append(f"#   [{'listed: ' + why if why else 'UNLISTED'}] {k}: {short}")
    if not diffs and not missing:
        hdr.append("#   none")
    for s_, sn_ in snaps.items():
        if sn_.get("normalise_failures"):
            hdr.append(f"# normalise failures on {s_}: {sn_['normalise_failures'].replace(chr(10), '; ')}")
    # drift: pre vs post snapshot of the same stack
    for s_ in stacks:
        post = load_snaps([s_], snapdir, "post")
        if s_ in snaps and s_ in post:
            dr = sn.diff_snapshots({"pre": snaps[s_], "post": post[s_]})
            hdr.append(f"# drift {s_} (pre vs post): " + ("none" if not dr else "; ".join(f"{k}" for k, _, _ in dr)))
    if write:
        p = ROOT / f"tmp/logs/stack_compare_result-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        p.write_text("\n".join(hdr) + "\n# (dry-run: no result rows)\n")
        log(f"result header -> {p.relative_to(ROOT)}")
    for ln in hdr:
        log(ln)
    return controlled, hdr


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stacks", default="A,B,C", help="subset of A,B,C")
    ap.add_argument("--clocks", default="common,final", help="common (core 508 / CPU 1350) and/or final (core 608 / CPU 1325)")
    ap.add_argument("--profile", default="clean", choices=["clean", "profile", "both"])
    ap.add_argument("--dry-run", action="store_true", default=True, help="always on: this script prints the plan only")
    ap.add_argument("--snapshot-dir", default=str(ROOT / "tmp/logs"), help="where stack_snapshot-<S>[-post].json live (gate input)")
    ap.add_argument("--gate-only", action="store_true", help="evaluate the gate from existing snapshots, print no plan")
    ap.add_argument("--run", action="store_true", help="refused: hardware runs need the owner's release")
    a = ap.parse_args()
    if a.run:
        sys.exit("refused: dry-run only (NAT-STACK-TESTS.md); the owner releases hardware runs")
    if a.gate_only:
        ok, _ = gate(a.stacks.split(","), Path(a.snapshot_dir))
        sys.exit(0 if ok else 3)
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
    gate(a.stacks.split(","), Path(a.snapshot_dir))
    log(f"TOTAL {boots} boots, est {total / 3600:.1f} h (1 run per cell, no repeats; add 2 repeats of the P4 cells: +~25 min per clean boot)")


if __name__ == "__main__":
    main()
