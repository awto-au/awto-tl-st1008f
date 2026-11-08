#!/usr/bin/env python3
"""stack_compare — identical NAT bench on three stacks (A upstream OpenWrt, B ours OpenWrt, C plain kernel); DRY-RUN ONLY.

- Plan: docs/NAT-STACK-TESTS.md. Prints every command per stack x clock set; `--run` is refused until the owner releases it.
- Stacks: A = `openwrt-upstream` (r38178 built from upstream, zero patches), B = `openwrt-ours-clean` (profile runs: `openwrt-ours-l3fix2`), C = `mainline-kernel --kernel mainline-7.4-rc1-clean3.bin`. A7 (upstream + 7.4) cannot be built: NAT-STACK-TESTS.md.
- Clock sets: common = core 508 / CPU 1350 / DDR 662 / LX 306 / SRAM 500; final = core 608 / CPU 1325 (LX 304-306).
- Profile `clean`: tracing off (numbers). Profile `profile`: perf (+ ftrace on C) on, one diagnosis run per stack.
- Per boot: `stack_normalize.py` runs BEFORE the cells (pinned tools, services, ruleset, sysctls, RPS/XPS, qdisc, offloads, IRQ), a
  `--snapshot-only --tag post` after them (drift). GATE: the three snapshots are diffed; every difference is printed and written into
  the result header (tmp/logs/stack_compare_result-<ts>.txt); a difference not in stack_normalize.KNOWN = NOT CONTROLLED.
- Log: tmp/logs/stack_compare.log. Reuses nat_bench.py / zc_bench.py / l3_offload_ab.py commands unchanged.
"""
import argparse
import json
import os
import re
import select
import shlex
import signal
import statistics
import subprocess
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
    "final": "mw.l 0xbb00e220 0x36826; mw.l 0xbb00e214 0x478; mw.l 0xbb00e200 0x0001c0ff; mw.l 0xbb00e200 0x4001c0ff",
}
# key: (label, ramload --then, extra ramload args, zc fast path present, L3 offload (300-17) present, tracing in the image)
STACKS = {
    "A": ("OpenWrt r38178 (upstream, zero patches) + Linux 6.18.x", "openwrt-upstream", ["--no-linkcheck"], False, False, "none (no PERF, no FTRACE)"),
    "B": ("ours: OpenWrt main r38178 + 7.4-rc1 + series, clean profile", "openwrt-ours-clean", ["--no-linkcheck"], True, True, "none (no PERF, PROFILING, DYNAMIC_DEBUG, FTRACE)"),
    "C": ("plain Linux 7.4-rc1 + series, bench initramfs", "mainline-kernel", ["--kernel", "mainline-7.4-rc1-clean3.bin", "--mgmt"], True, True, "clean image (C-clean3: B's BusyBox/musl/dropbear/nft/ip/tc/ethtool + fw4 ruleset): none"),
}
PROFILE_IMG = {"C": ["--kernel", "mainline-7.4-rc1.bin", "--mgmt"]}  # existing image: PERF + FTRACE + function_graph compiled in
PROFILE_THEN = {"B": "openwrt-ours-l3fix2"}  # perf-enabled image (PERF_EVENTS + PROFILING + DYNAMIC_DEBUG)
SECS = 15


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
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


def boot_argv(stack, clk, profile, stock=False):
    label, then, extra, zc, l3, tracing = STACKS[stack]
    if profile == "profile":
        extra = PROFILE_IMG.get(stack, extra)
        then = PROFILE_THEN.get(stack, then)
    argv = [PY, "dev.py", "ramload", "uboot-mainline", "--stock-clocks", "--then", then, *extra, "--cage", "1"]
    return argv if stock else argv + ["--pre", TURBO[clk], "--pre", RAW[clk]]


def plan(stack, clk, profile):
    label, then, extra, zc, l3, tracing = STACKS[stack]
    if profile == "profile" and stack == "A":
        return 0, [f"# A has no PERF/FTRACE compiled in: no profile run"]
    img = extra if not (profile == "profile" and stack in PROFILE_IMG) else PROFILE_IMG[stack]
    boot = shlex.join(boot_argv(stack, clk, profile))
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
    "compiler: A = B (OpenWrt GCC 14.4.0); C kernel by host GCC 16.2.1 (mips64-linux-gnu); userland all OpenWrt GCC 14.4.0",
    "OpenWrt base system (procd/ubusd/netifd/logd/urngd/hotplug/st1008f-linkwatch) on A and B, not C; OpenWrt base r38178 on A and B",
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


def gate(stacks, snapdir, write=True, out_dir=None):
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
        p = (out_dir or ROOT / "tmp/logs") / f"stack_compare_result-{time.strftime('%Y%m%d-%H%M%S')}.txt"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(hdr) + ("\n" if out_dir else "\n# (dry-run: no result rows)\n"))
        log(f"result header -> {p.relative_to(ROOT)}")
    for ln in hdr:
        log(ln)
    return controlled, hdr


# ---- RUN ENGINE (owner released hardware runs 2026-11-08; sw2 only) -----------------------------------------------------
CTRL = ROOT / "tmp/controlled"
ROWS, BOOTS = CTRL / "rows.jsonl", CTRL / "boots.jsonl"
NB_JSONL = ROOT / "tmp/logs/nat_bench.jsonl"
CONSOLE = ROOT / "private/serial/st1008-console.log"
BAD = re.compile(rb"Oops|\bBUG\b|Kernel panic|gro_list_prepare|Unhandled|rcu.*stall|Call Trace")
SSHB = ["ssh", "-q", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes"]
NREP = 3
EXPECT_E220 = {"common": 0x30626, "final": 0x36826}


class Hang(Exception):
    pass


def sh(argv, stall, total, tag=""):
    """Run argv in its own process group; kill it after `stall` s without output or `total` s. Returns (rc, text)."""
    t0 = last = time.time()
    p = subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True)
    buf = b""
    while True:
        r, _, _ = select.select([p.stdout], [], [], 5)  # poll the pipe; no sleeping
        now = time.time()
        if r:
            chunk = os.read(p.stdout.fileno(), 65536)
            if not chunk:
                break
            buf += chunk
            last = now
        if now - last > stall or now - t0 > total:
            os.killpg(p.pid, signal.SIGKILL)  # our own child group
            p.wait()
            tail = buf.decode(errors="replace").strip().splitlines()[-1:] or [""]
            why = f"STALL {now - last:.0f} s silent (limit {stall})" if now - last > stall else f"TOTAL {now - t0:.0f} s (limit {total})"
            log(f"KILLED {tag}: {why}; last line '{tail[0][:120]}'; load {os.getloadavg()[0]:.1f}")
            return 124, buf.decode(errors="replace") + f"\n[killed: {why}]\n"
    p.wait()
    return p.returncode, buf.decode(errors="replace")


def ssh(cmd, tmo=20):
    try:
        return subprocess.run(SSHB + [f"root@{sn.BENCH_IP}", cmd], capture_output=True, text=True, timeout=tmo).stdout
    except subprocess.TimeoutExpired:
        return ""


def alive():
    ping = subprocess.run(["ping", "-c", "2", "-W", "2", sn.BENCH_IP], capture_output=True).returncode == 0
    return ping and "root" in ssh("echo root", 10)


def hold(secs):
    """Pace by pinging the (live) board once a second: a real wait on the device, no sleep."""
    subprocess.run(["ping", "-c", str(int(secs) + 1), "-i", "1", "-W", "1", sn.BENCH_IP], capture_output=True)


def jrow(path, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def bad_console(mark):
    with CONSOLE.open("rb") as fh:
        fh.seek(mark)
        return [b.decode() for b in BAD.findall(fh.read())][:5]


def console_tail(mark, n=60):
    with CONSOLE.open("rb") as fh:
        fh.seek(mark)
        return "\n".join(fh.read().decode(errors="replace").splitlines()[-n:])


def boot(stack, clk, profile, stock=False):
    """One ramload attempt; success = ssh answers (ramload rc is 1 on any UNKNOWN boot-log line, also for good boots)."""
    mark = CONSOLE.stat().st_size
    t0 = time.time()
    for sock in ("tmp/nat_bench.ssh", "tmp/stack_normalize.ssh"):
        (ROOT / sock).unlink(missing_ok=True)  # stale ssh mux of the previous boot hangs scripts
    argv = boot_argv(stack, clk, profile, stock)
    log(f"BOOT {stack} {clk} {profile}{' stock' if stock else ''}: {shlex.join(argv)}")
    rc, out = sh(argv, 90, 420, "ramload")  # stall 90 s: ramload logs each step; total ~3x its ~100 s
    up = any(subprocess.run(["ping", "-c", "3", "-i", "1", "-W", "1", sn.BENCH_IP], capture_output=True).returncode == 0 for _ in range(10))
    if up and "root" not in ssh("echo root", 10):
        sh([PY, "scripts/switch_console.py", "send", "dropbear -R -B", "--secs", "4"], 30, 40, "dropbear")
    ok = up and any(alive() for _ in range(5))
    info = {}
    if ok:
        while True:  # uptime >= 25 s: ports and daemons settled
            u = ssh("cut -d. -f1 /proc/uptime").split()
            if u and u[-1].isdigit() and int(u[-1]) < 25:
                hold(25 - int(u[-1]))
            else:
                break
        raw = ssh("uname -r; grep -i bogomips /proc/cpuinfo | head -1; for a in 0x1b00e200 0x1b00e214 0x1b00e220 0x18001200; do devmem $a 32 2>&1; done; cat /sys/class/thermal/thermal_zone0/temp").splitlines()
        info = {"uname_r": raw[0] if raw else "", "regs": raw[2:6], "bogomips": raw[1] if len(raw) > 1 else "", "temp_mC": raw[-1] if raw else ""}
        try:
            info["e220_ok"] = (not stock) and int(raw[4], 16) == EXPECT_E220[clk]
        except (IndexError, ValueError):
            info["e220_ok"] = None
    row = {"when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "stack": stack, "clk": clk, "profile": profile, "stock": stock, "ok": ok,
           "ramload_rc": rc, "secs": round(time.time() - t0), "bad_console": bad_console(mark), **info}
    if not ok:
        fp = CTRL / "logs" / f"bootfail-{stack}-{clk}-{time.strftime('%H%M%S')}.txt"
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text("== ramload output tail ==\n" + "\n".join(out.splitlines()[-40:]) + "\n== console tail ==\n" + console_tail(mark))
        row["fail_log"] = str(fp.relative_to(ROOT))
    jrow(BOOTS, row)
    log(f"BOOT result: {json.dumps(row)}")
    return ok


def done_cells(stack, clk, profile):
    cnt = {}
    if ROWS.exists():
        for ln in ROWS.read_text().splitlines():
            r = json.loads(ln)
            if (r["stack"], r["clk"], r["profile"]) == (stack, clk, profile):
                cnt[r["cell"]] = cnt.get(r["cell"], 0) + 1
    return cnt


def nbcmd(*args, tmo=90):
    rc, out = sh([PY, "scripts/nat_bench.py", *map(str, args)], 60, tmo, "nat_bench " + " ".join(map(str, args)))
    log(f"nat_bench {' '.join(map(str, args))} rc {rc}")
    return rc, out


class Session:
    def __init__(self, stack, clk, profile):
        self.stack, self.clk, self.profile = stack, clk, profile
        self.done = done_cells(stack, clk, profile)

    def finish_row(self, cell, rep, row, mark, ok):
        row.update({"stack": self.stack, "clk": self.clk, "profile": self.profile, "cell": cell, "rep": rep, "ok": ok,
                    "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "bad_console": bad_console(mark)})
        t = ssh("cat /sys/class/thermal/thermal_zone0/temp", 10).split()
        row["temp_mC"] = int(t[0]) if t and t[0].isdigit() else None
        jrow(ROWS, row)
        log(f"ROW {json.dumps(row)}")
        if not ok and not alive():
            fp = CTRL / "logs" / f"hang-{self.stack}-{self.clk}-{cell}-{time.strftime('%H%M%S')}.txt"
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(console_tail(mark, 80))
            raise Hang(f"{cell} rep {rep}: board not answering; console tail {fp.relative_to(ROOT)}")

    def cell(self, name, fn):
        for rep in range(self.done.get(name, 0), NREP):
            mark = CONSOLE.stat().st_size
            try:
                row = fn(rep)
                ok = row.pop("_ok", True)
            except (SystemExit, Exception) as e:  # nat_bench style failure or a timeout
                row, ok = {"error": repr(e)[:300]}, False
            self.finish_row(name, rep, row, mark, ok)

    def tcp(self, mode, p, rev, secs=15):
        def fn(rep):
            label = f"{self.stack}-{self.clk}-{mode}-P{p}{'-R' if rev else ''}-r{rep}"
            n0 = NB_JSONL.stat().st_size if NB_JSONL.exists() else 0
            rc, out = sh([PY, "scripts/nat_bench.py", "run", "--secs", str(secs), "-P", str(p), *(["--reverse"] if rev else []), "--label", label],
                         60, int((secs + 2) * 1.25) + 60, "nat_bench run")  # iperf3 own limit + ssh dumps
            rows = [json.loads(x) for x in NB_JSONL.open("rb").read()[n0:].decode().splitlines() if x]
            r = next((x for x in rows if x.get("label") == label), None)
            if rc or not r:
                return {"_ok": False, "error": out[-300:]}
            return {"mbps": r["mbps"], "retrans": r.get("retrans"), "irq_per_s": r["irq_per_s"], "eth0_rx_pps": r["eth0_rx_pps"],
                    "eth0_tx_pps": r["eth0_tx_pps"], "rx_drop": r["eth0_rx_dropped"], "tx_drop": r["eth0_tx_dropped"],
                    "cpu0": r["cpu"].get("cpu0"), "cpu1": r["cpu"].get("cpu1"), "conntrack": r["conntrack"]}
        return fn

    def udp(self, ln, secs=10, flows=4, zc_on=False):
        import nat_bench as nb  # noqa: E402  (lazy: dry-run needs no host access)
        import zc_bench as zb

        def fn(rep):
            dev = f"{nb.HOST_NIC}.992"
            if zc_on:
                nb.sw(f"echo 1 > {zb.P}/zc")
            try:
                a, c0 = zb.rx(dev), zb.cpu_stat()
                z0 = zb.zc() if zc_on else {}
                r = subprocess.run(["sudo", "-n", "ip", "netns", "exec", "natlan", str(ROOT / "tmp/udpblast"), "10.99.1.2", "10.99.2.2", "5201", str(ln), str(secs), str(flows)],
                                   capture_output=True, text=True, timeout=secs * 3 + 30)  # sender stops itself at secs
                b, c1 = zb.rx(dev), zb.cpu_stat()
                z1 = zb.zc() if zc_on else {}
            finally:
                if zc_on:
                    nb.sw(f"echo 0 > {zb.P}/zc", check=False)
            sent = re.search(r"sent (\d+)", r.stdout)
            row = {"kpps": round((b - a) / secs / 1000, 2), "busy": zb.busy(c0, c1), "sent": int(sent.group(1)) if sent else None}
            if zc_on:
                row["zc"] = {k: z1[k] - z0[k] for k in z1 if k in z0}
            return row
        return fn

    def zc_params(self, tcp):
        import nat_bench as nb
        import zc_bench as zb
        P = zb.P
        nb.sw(f"echo {zb.NATWAN_MAC} > {P}/zc_dmac; echo 992 > {P}/zc_vid; echo 5201 > {P}/zc_dport; echo 1 > {P}/zc_ring; echo 'l3_net_route 1' > /sys/kernel/debug/rteth/rxq")
        nb.sw(f"echo 0 > {P}/zc; echo 10,99,2,1 > {P}/zc_sip; echo 1000 > {P}/zc_sport_add")
        if tcp:
            nb.sw(f"echo 2,153,0,0,9,145 > {P}/zc_rmac; echo 991 > {P}/zc_rvid; echo 10,99,1,2 > {P}/zc_rip")

    def zc_reset(self):
        import nat_bench as nb
        import zc_bench as zb
        nb.sw(f"echo 0 > {zb.P}/zc; echo 0 > {zb.P}/zc_sport_add", check=False)

    def zc_tcp(self, rev, secs=15):
        import nat_bench as nb
        import zc_bench as zb
        inner = self.tcp("nat-ft", 4, rev, secs)

        def fn(rep):
            nb.sw(f"echo 1 > {zb.P}/zc")
            z0 = zb.zc()
            try:
                row = inner(rep)
            finally:
                z1 = zb.zc()
                nb.sw(f"echo 0 > {zb.P}/zc", check=False)
            row["zc"] = {k: z1[k] - z0[k] for k in z1 if k in z0}
            return row
        return fn

    def matrix(self):
        S = self.stack
        zc, l3 = STACKS[S][3], S == "B"  # routed L3 off/on: B only (C n/m, owner)
        rc, _ = nbcmd("setup", tmo=120)
        if rc:
            rc, _ = nbcmd("setup", tmo=120)  # one retry: first ping can race the SVI
        if rc:
            raise Hang("nat_bench setup failed twice")
        for mode in ("nat", "nat-ft"):
            nbcmd("mode", mode)
            for p in (1, 2, 4):
                for rev in (False, True):
                    self.cell(f"{mode}-P{p}-{'rev' if rev else 'fwd'}", self.tcp(mode, p, rev))
        nbcmd("mode", "route")
        if zc:
            nbcmd("offload", "--onlink", 0, "--default-v4", 0, "--default-v6", 0)
        for ln in (1400, 500, 64):
            self.cell(f"stack-udp{ln}", self.udp(ln))
        if l3:
            nbcmd("offload", "--onlink", 1)
            self.cell("l3on-udp1400", self.udp(1400))
            self.cell("l3on-tcp-P4-fwd", self.tcp("route", 4, False))
            nbcmd("offload", "--onlink", 0)
            self.cell("l3off-tcp-P4-fwd", self.tcp("route", 4, False))
        if zc:
            nbcmd("mode", "nat-ft")
            self.zc_params(tcp=False)
            for ln in (1400, 500, 64):
                self.cell(f"zcnat-udp{ln}", self.udp(ln, zc_on=True))
            self.zc_params(tcp=True)
            self.cell("zcnat-P4-fwd", self.zc_tcp(False))
            self.cell("zcnat-P4-rev", self.zc_tcp(True))
            self.zc_reset()


def normalise(stack, snapdir, tag=""):
    argv = [PY, "scripts/stack_normalize.py", "--stack", stack, "--napi", "irq1", "--snap-dir", str(snapdir)]
    if tag:
        argv += ["--snapshot-only", "--tag", tag]
    rc, out = sh(argv, 60, 400, "stack_normalize")  # push of ~1.4 MB + 90 s remote script, 3x measured later
    (CTRL / "logs").mkdir(parents=True, exist_ok=True)
    (CTRL / "logs" / f"normalize-{stack}-{snapdir.name}{'-' + tag if tag else ''}.txt").write_text(out)
    log(f"normalise {stack} {tag} rc {rc}: {out.strip().splitlines()[-1] if out.strip() else ''}")
    return rc


def run_stack(stack, clk, profile, a):
    snapdir = CTRL / f"snap-{clk}{'-' + profile if profile != 'clean' else ''}"
    tries = 2 if stack == "A" else 2  # A: 2 tries then move on; B, C: one retry
    if not a.no_boot:
        ok = False
        for n in range(tries):
            ok = boot(stack, clk, profile)
            if ok:
                break
        if not ok:
            log(f"STACK {stack} {clk}: no boot in {tries} tries: recorded, moving on")
            return False
    rc = normalise(stack, snapdir)
    if rc and rc != 1:  # 1 = normalise FAIL lines (listed by the gate); other = tool failure
        log(f"STACK {stack} {clk}: normalise tool failure rc {rc}")
        return False
    if profile == "clean":
        try:
            Session(stack, clk, profile).matrix()
        except Hang as e:
            log(f"HANG {stack} {clk}: {e}")
            return False
    normalise(stack, snapdir, "post")
    return True


def run_all(a):
    if sn.BENCH_IP != "192.168.25.56" or sn.BENCH_IP == "192.168.25.48":
        sys.exit("refused: sw2 (192.168.25.56) only")
    CTRL.mkdir(parents=True, exist_ok=True)
    for prof in (["clean", "profile"] if a.profile == "both" else [a.profile]):
        for clk in a.clocks.split(","):
            for s in a.stacks.split(","):
                if prof == "profile" and clk == "final":
                    continue
                log(f"=== RUN stack {s} clocks {clk} profile {prof}")
                run_stack(s, clk, prof, a)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--stacks", default="A,B,C", help="subset of A,B,C")
    ap.add_argument("--clocks", default="common,final", help="common (core 508 / CPU 1350) and/or final (core 608 / CPU 1325)")
    ap.add_argument("--profile", default="clean", choices=["clean", "profile", "both"])
    ap.add_argument("--dry-run", action="store_true", default=True, help="always on: this script prints the plan only")
    ap.add_argument("--snapshot-dir", default=str(ROOT / "tmp/logs"), help="where stack_snapshot-<S>[-post].json live (gate input)")
    ap.add_argument("--gate-only", action="store_true", help="evaluate the gate from existing snapshots, print no plan")
    ap.add_argument("--run", action="store_true", help="execute on sw2 (owner release 2026-11-08); rows -> tmp/controlled/")
    ap.add_argument("--no-boot", action="store_true", help="--run: the stack is already booted (resume after a script fix)")
    a = ap.parse_args()
    if a.run:
        return run_all(a)
    if a.gate_only:
        ok, _ = gate(a.stacks.split(","), Path(a.snapshot_dir), out_dir=CTRL if a.snapshot_dir.startswith(str(CTRL)) else None)
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
