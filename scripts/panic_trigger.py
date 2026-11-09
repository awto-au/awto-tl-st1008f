#!/usr/bin/env python3
"""panic_trigger — #149 trigger search on sw2: N boots of stack B per variant, one fixed load, panic count per variant.

- Load per boot: nat-ft P1 fwd + rev, then zc+nat P4 fwd, 3 reps each (stack_compare.Session cells). A panic ends the boot.
- Variants V0..V8: one factor each against V0 (B-clean, common clocks, normaliser as-is). Usage: `./dev.py panic-trigger V1 --boots 4`.
- Out: tmp/controlled/149/{variants,rows,boots}.jsonl, <variant>-b<n>.console.txt per panic. Log: tmp/logs/stack_compare.log.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stack_compare as sc  # noqa: E402

D = sc.ROOT / "tmp/controlled/149"
VARIANTS = {  # name: (boot clock key, profile, extra normaliser args, one-line description)
    "V0": ("common", "clean", [], "baseline: B-clean, common clocks, normaliser as-is"),
    "V1": ("common", "clean", ["--offload", "gro=off"], "GRO off"),
    "V2": ("common", "clean", ["--offload", "rx-gro-list=off"], "rx-gro-list off"),
    "V3": ("common", "clean", ["--rps", "keep"], "RPS/XPS as the stack sets it (no pin)"),
    "V4": ("common", "clean", ["--napi", "irq0"], "NIC irq on VPE0"),
    "V5": ("common", "clean", ["--qdisc", "fq_codel"], "eth0 qdisc fq_codel"),
    "V6": ("common", "profile", [], "B-profile image (perf-enabled l3fix2)"),
    "V7": ("v7", "clean", [], "core 508, CPU 1325 (CPU only lowered)"),
    "V8": ("v8", "clean", [], "core 408 stock, CPU 1350, LX stock"),
}
OOPS = re.compile(r"Oops|Unable to handle|\bBUG:|Kernel panic|gro_list_prepare|Call Trace")


def relay_ok():
    return subprocess.run(["ping", "-c", "1", "-W", "2", "192.168.25.49"], capture_output=True).returncode == 0


def panic_info(mark):
    """First oops line, epc/ra, task, uptime from the console slice since mark; excerpt text."""
    with sc.CONSOLE.open("rb") as fh:
        fh.seek(mark)
        lines = fh.read().decode(errors="replace").splitlines()
    idx = next((i for i, ln in enumerate(lines) if OOPS.search(ln)), None)
    if idx is None:
        return {"kind": "hang-no-oops"}, ""
    ex = lines[max(0, idx - 5): idx + 90]
    txt = "\n".join(ex)
    pick = lambda rx: next((ln.strip() for ln in ex if re.search(rx, ln)), "")
    ts = re.search(r"\[\s*(\d+\.\d+)\]", lines[idx])
    return {"kind": "oops", "first_line": lines[idx].strip()[:200], "epc": pick(r"\bepc\b"), "ra": pick(r"\bra\b\s*:"),
            "task": pick(r"Process|comm:|CPU: \d"), "regs": [ln.strip() for ln in ex if re.match(r"\s*(\$ ?\d+\s*:|Stack :|Hi\s*:|BadVA)", ln)][:12],
            "uptime_s": float(ts.group(1)) if ts else None}, txt


def load(sess):
    """Fixed load; raises sc.Hang when the board dies."""
    for attempt in range(10):  # orphan TCP sockets of a panicked board pin the old natlan netns 1-3 min
        if attempt:
            sc.hold(15)
        sc.nbcmd("setup", tmo=120)
        sc.nbcmd("mode", "nat")
        rc, _ = sc.nbcmd("status")
        if rc == 0:
            break
    else:
        raise sc.Hang("nat_bench: natlan cannot reach natwan after 10 tries")
    sc.nbcmd("mode", "nat-ft")
    for rev in (False, True):
        sess.cur = f"nat-ft-P1-{'rev' if rev else 'fwd'}"
        sess.cell(sess.cur, sess.tcp("nat-ft", 1, rev))
    sess.cur = "zcnat-P4-fwd"
    sess.zc_params(tcp=True)
    try:
        sess.cell("zcnat-P4-fwd", sess.zc_tcp(False))
    finally:
        try:
            sess.zc_reset()
        except (SystemExit, Exception):  # dead board: nb.sw exits on an ssh timeout
            pass


def one_boot(var, n):
    clk, prof, nargs, desc = VARIANTS[var]
    if not relay_ok():
        sc.log(f"STOP: relay 192.168.25.49 unreachable before {var} boot {n}")
        sys.exit(3)
    tag = f"{var}-b{n}"
    rec = {"variant": var, "boot": n, "desc": desc, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    mark0 = sc.CONSOLE.stat().st_size
    if not any(sc.boot("B", clk, prof) for _ in range(2)):
        rec.update(result="no-boot")
        sc.jrow(D / "variants.jsonl", rec)
        return rec
    snapdir = D / f"snap-{tag}"
    argv = [sc.PY, "scripts/stack_normalize.py", "--stack", "B", "--snap-dir", str(snapdir)]
    argv += nargs + ([] if "--napi" in nargs else ["--napi", "irq1"])
    for _ in range(2):  # first ssh login after boot failed once (push rc 255)
        rc, out = sc.sh(argv, 60, 400, "stack_normalize")
        if "snapshot ->" in out:
            break
    (D / "logs").mkdir(parents=True, exist_ok=True)
    (D / "logs" / f"normalize-{tag}.txt").write_text(out)
    rec["normalise_rc"] = rc
    rec["normalise_fail"] = [ln for ln in out.splitlines() if ln.startswith(("FAIL", "MISSING"))]
    if "snapshot ->" not in out:
        rec.update(result="normalise-failed")
        sc.jrow(D / "variants.jsonl", rec)
        return rec
    mark = sc.CONSOLE.stat().st_size
    sess = sc.Session("B", tag, "clean")
    try:
        load(sess)
        rec.update(result="clean", bad_console=sc.bad_console(mark))
    except (sc.Hang, SystemExit, Exception) as e:
        if not isinstance(e, sc.Hang) and sc.alive():
            rec.update(result="load-error", error=repr(e)[:200])
            sc.jrow(D / "variants.jsonl", rec)
            return rec
        if not isinstance(e, sc.Hang):
            e = sc.Hang(f"{getattr(sess, "cur", "setup")} rep ?: {e!r}"[:200])
        info, txt = panic_info(mark)
        cell = re.match(r"([\w-]+) rep (\d+)", str(e))
        rec.update(result="panic", cell=cell.group(1) if cell else str(e)[:80], rep=int(cell.group(2)) if cell else None, **info)
        (D / f"{tag}.console.txt").write_text(txt + "\n")
    rows = [json.loads(x) for x in sc.ROWS.read_text().splitlines() if f'"clk": "{tag}"' in x] if sc.ROWS.exists() else []
    rec["cells_ok"] = sum(1 for r in rows if r.get("ok"))
    sc.jrow(D / "variants.jsonl", rec)
    sc.log(f"VARIANT {json.dumps(rec)}")
    return rec


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("variant", choices=sorted(VARIANTS))
    ap.add_argument("--boots", type=int, default=4)
    ap.add_argument("--first", type=int, default=0, help="first boot index (resume)")
    a = ap.parse_args()
    if sc.sn.BENCH_IP != "192.168.25.56":
        sys.exit("refused: sw2 (192.168.25.56) only")
    D.mkdir(parents=True, exist_ok=True)
    sc.CTRL, sc.ROWS, sc.BOOTS = D, D / "rows.jsonl", D / "boots.jsonl"
    panics = 0
    for n in range(a.first, a.first + a.boots):
        r = one_boot(a.variant, n)
        panics += r.get("result") == "panic"
    sc.log(f"=== {a.variant}: {panics} panics in {a.boots} boots")
    print(f"{a.variant}: {panics}/{a.boots}")


if __name__ == "__main__":
    main()
