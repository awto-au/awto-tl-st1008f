#!/usr/bin/env python3
"""sds_tools_test — hardware tests of `rtk sds` (SerDes test tools, #74) at our U-Boot prompt.

- Run after `./dev.py ramload uboot-mainline`; does `rtk network on` + `rtk laser 1` itself if needed.
- Tests: status (all cages), errcnt, prbs-near (PRBS31 + near loopback on dark cages, 0 errors
  expected), prbs-dark (no loopback: checker must count, proves it works), eye1 (cage 1 link up),
  eye-dark (other cages), txeye (read-back).
- `run "<cmd>"`: one ad-hoc command at the prompt, reply printed.
- Output: tmp/sds_tools/<label>.json (+ raw eye text); log tmp/logs/sds_tools_test.log.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sds_tools_test.log"
OUT = ROOT / "tmp/sds_tools"
PROMPT = r"\r?\nst1008f-mainline # "
NET_CAP_S = 12  # `rtk network on` measured ~9 s (#28); x1.25
# eye: 4096 points x ~8 SerDes ops; raw dump 64 rows x ~260 chars = 17 KB = 1.5 s at 115200.
EYE_CAP_S = 15
STATUS_CAP_S = 2  # 8 lines, ~100 SerDes reads: < 0.2 s


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(con: Console, cmd: str, cap: float) -> str:
    _, out = con.run(cmd, PROMPT, cap, cmd)
    out = re.sub(r"\[(?:TX|daemon)[^\n]*\n", "", out).lstrip("\r\n")  # daemon annotations
    body = out.split("\n", 1)[1] if "\n" in out else out
    return re.sub(PROMPT + r"$", "", body).replace("\r", "")


def net_on(con: Console) -> None:
    if "run `rtk network on` first" in run(con, "rtk sds status 1", STATUS_CAP_S):
        con.run("rtk network on", r"Err:0xf030:FAIL \(0xf030\)" + PROMPT, NET_CAP_S, "rtk network on")
    con.run("rtk laser 1", r"OK \(out 0xfe\)" + PROMPT, 1, "laser cage 1 only")


DARK10G = [2, 6, 8]  # 10G SR modules, no fibre (docs/hardware.md cage table, 2026-10-12)
LB_REGS = [(5, 0xA), (6, 0x0), (6, 0x1), (6, 0xE), (6, 0xF)]  # pattern + loopback state
PRBS_MS = 1000  # 10.3 Gbit per run; 0 errors -> BER < 3e-10 (95 %)
PRBS_CAP_S = 3  # 1 s run + restore/print ~50 ms; x~2.5 for the 10 ms poll loop + console


def regs(con: Console, cage: int) -> dict:
    out = {}
    for page, reg in LB_REGS:
        txt = run(con, f"rtk sdsreg get 0 {cage + 1} {page} {reg}", 1)
        out[f"{page}/{reg:#x}"] = re.search(r"val: (0x[0-9A-F]{4})", txt).group(1)
    return out


def t_status(con: Console, res: dict) -> bool:
    st = run(con, "rtk sds status", STATUS_CAP_S)
    e1 = run(con, "rtk sds errcnt", STATUS_CAP_S)
    e2 = run(con, "rtk sds errcnt", STATUS_CAP_S)
    res["status"], res["errcnt"] = st.splitlines(), [e1.splitlines(), e2.splitlines()]
    ok = len(re.findall(r"^cage \d sds \d: mode", st, re.M)) == 8 and "cage 1 sds 2: mode 10GBASE-R" in st \
        and re.search(r"cage 1 sds 2:.*pcs up.*mac up", st) is not None
    ok &= len(re.findall(r"^errcnt cage \d", e2, re.M)) == 8
    log(f"{'PASS' if ok else 'FAIL'} status: 8 cages, cage 1 up\n" + st + e2)
    return ok


def prbs(con: Console, cage: int, args: str) -> dict:
    txt = run(con, f"rtk sds prbs {cage} {args}", PRBS_CAP_S)
    m = re.search(r"(\d+) errors in (\d+) ms \((\d+) Mbit\), (\d+)/(\d+) samples nonzero, (\d+) saturated", txt)
    if not m:
        return {"text": txt, "ok": False}
    return {"text": txt.strip(), "errors": int(m[1]), "ms": int(m[2]), "mbit": int(m[3]),
            "nonzero": int(m[4]), "samples": int(m[5]), "saturated": int(m[6])}


def t_prbs(con: Console, res: dict) -> bool:
    ok = True
    for c in DARK10G:
        before = regs(con, c)
        r = {"self_test": prbs(con, c, "mismatch 300 near"),
             "prbs31_near": prbs(con, c, f"31 {PRBS_MS} near"),
             "prbs9_near": prbs(con, c, f"9 {PRBS_MS} near"),
             "prbs31_dark": prbs(con, c, "31 300")}
        after = regs(con, c)
        good = r["self_test"].get("saturated", 0) > 0 and r["prbs31_near"].get("errors") == 0 \
            and r["prbs9_near"].get("errors") == 0 and before == after
        r.update(regs_before=before, regs_after=after, ok=good)
        res.setdefault("prbs", {})[c] = r
        ok &= good
        log(f"{'PASS' if good else 'FAIL'} prbs cage {c}: self-test sat {r['self_test'].get('saturated')}, "
            f"31 near {r['prbs31_near'].get('errors')} err / {r['prbs31_near'].get('mbit')} Mbit, "
            f"9 near {r['prbs9_near'].get('errors')} err, dark {r['prbs31_dark'].get('errors')} err, "
            f"regs restored {before == after}")
    return ok


def t_guards(con: Console, res: dict) -> bool:
    a = run(con, "rtk sds prbs 1 31 100", PRBS_CAP_S)
    b = run(con, "rtk sds loopback 1 near", 1)
    c = run(con, "rtk sds loopback 2 far", 1)
    st = run(con, "rtk sds status 1", STATUS_CAP_S)
    ok = "refused: cage 1 link is up" in a and "refused: cage 1 link is up" in b and "refused: no far-end" in c \
        and "pcs up" in st
    res["guards"] = [a, b, c, st]
    log(f"{'PASS' if ok else 'FAIL'} guards: live-link refusal, far refused, cage 1 still up")
    return ok


def t_ctrlc(con: Console, res: dict) -> bool:
    before = regs(con, 2)
    mark = con.size()
    con.send("rtk sds prbs 2 31 5000 near")
    time.sleep(0.5)  # into the 5 s run; Ctrl-C is polled every 10 ms
    con.send("\x03", cr=False)
    _, out = con.expect(r"ABORTED \(Ctrl-C\)[^\n]*" + PROMPT, 2, mark, "prbs abort on Ctrl-C")
    after = regs(con, 2)
    ok = before == after
    res["ctrlc"] = {"text": out.strip().splitlines()[-2:], "regs_before": before, "regs_after": after}
    log(f"{'PASS' if ok else 'FAIL'} ctrl-c: prbs aborted, registers restored {before == after}")
    return ok


def eye(con: Console, cage: int, frames: int) -> dict:
    txt = run(con, f"rtk sds eye {cage} {frames}", EYE_CAP_S + frames)
    h = re.search(r"pcs (\w+) -> (\w+), (\d+) invalid", txt)
    m = re.search(r"height (\d+)/128 rows \(at x (\d+)\), width (\d+)/64 .*centre width (\d+)", txt)
    return {"text": txt, "pcs": h and (h[1], h[2]), "invalid": h and int(h[3]),
            "height": m and int(m[1]), "height_x": m and int(m[2]), "width": m and int(m[3]),
            "centre_width": m and int(m[4])}


def t_eye(con: Console, res: dict, label: str) -> bool:
    run(con, "rtk sds errcnt 1 clear", 1)
    run(con, "rtk sds status 1", STATUS_CAP_S)  # clears the latched-low link bit (4/1.2)
    e = eye(con, 1, 16)
    err = run(con, "rtk sds errcnt 1", 1)
    st = run(con, "rtk sds status 1", STATUS_CAP_S)
    (OUT / f"{label}-eye-cage1.txt").write_text(e["text"])
    ok = e["pcs"] == ("up", "up") and "blk_err 0 ber 0" in err and "pcs up (latched 1)" in st and \
        e["centre_width"] is not None
    res["eye1"] = {**e, "errcnt_after": err.strip(), "status_after": st.strip()}
    log(f"{'PASS' if ok else 'FAIL'} eye cage 1 (16 frames, link up): height {e['height']}/128 at x "
        f"{e['height_x']}, SDK width {e['width']}/64, centre width {e['centre_width']}, pcs {e['pcs']}, "
        f"after: {err.strip()}; {st.strip()}\n{e['text']}")
    for c in DARK10G:
        d = eye(con, c, 1)
        (OUT / f"{label}-eye-cage{c}.txt").write_text(d["text"])
        d["rx_idle"] = "RX idle (no signal)" in d["text"]
        res.setdefault("eye_dark", {})[c] = {k: v for k, v in d.items() if k != "text"}
        ok &= d["rx_idle"]
        log(f"  eye cage {c} (dark, rx idle flagged {d['rx_idle']}): height {d['height']}, width {d['width']}, centre width {d['centre_width']}")
    return ok


def t_txeye(con: Console, res: dict) -> bool:
    rd = {c: run(con, f"rtk sds txeye {c}", 1).strip() for c in range(1, 9)}
    a = run(con, "rtk sds txeye 2 1 10 3", 1)
    b = run(con, "rtk sds txeye 2 restore", 1)
    ok = "pre 1 (en 1) main 10 post 3 (en 1)" in a and b.strip() == rd[2]
    res["txeye"] = {"read": rd, "set": a.strip(), "restore": b.strip()}
    log(f"{'PASS' if ok else 'FAIL'} txeye: set/restore on cage 2\n" + "\n".join(rd.values()))
    return ok


TESTS = {"status": t_status, "guards": t_guards, "prbs": t_prbs, "ctrlc": t_ctrlc, "txeye": t_txeye}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", nargs="*", default=["all"])
    ap.add_argument("--cap", type=float, default=5, help="run: reply cap in s")
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    a = ap.parse_args()
    con = Console()
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "mainline prompt present")
    if a.what[0] == "run":
        con.note("interactive-begin")
        try:
            print(run(con, " ".join(a.what[1:]), a.cap))
        finally:
            con.note("interactive-end")
        return 0
    names = list(TESTS) + ["eye"] if a.what == ["all"] else a.what
    OUT.mkdir(parents=True, exist_ok=True)
    con.note("interactive-begin")
    res, ok = {"label": a.label}, {}
    try:
        net_on(con)
        for n in names:
            ok[n] = t_eye(con, res, a.label) if n == "eye" else TESTS[n](con, res)
    finally:
        con.note("interactive-end")
        res["ok"] = ok
        (OUT / f"{a.label}.json").write_text(json.dumps(res, indent=1))
    bad = [n for n, v in ok.items() if not v]
    log(f"=== {len(ok) - len(bad)}/{len(ok)} pass" + (f"; FAIL: {', '.join(bad)}" if bad else "") +
        f"; results tmp/sds_tools/{a.label}.json")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
