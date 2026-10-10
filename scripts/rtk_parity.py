#!/usr/bin/env python3
"""rtk_parity — run the same `rtk` command list on the stock loader and on our U-Boot, diff the output.

- Command list: scripts/rtk_parity_cmds.json (kinds: read, state, slow, key, ours; see its _doc).
- Sides are separate boots: `capture --side stock` (fresh boot at RTL9300#, no network yet; runs
  `rtk network on` + one-cage laser mask between the pre and post phases), `capture --side ours` (at st1008f-mainline #), then `compare`.
  `both` = stock capture, chainload our U-Boot (st1008_ramload --no-cycle --no-network), ours capture, compare.
- Table: PASS (same after normalising) | DIFF | ONLY-OURS (no stock command) | NO-STOCK / NO-OURS (not captured).
- Hard denylist (never sent, on either side): flash writers, upgrades, boot/reset, `*force`, boardid/boardmodel set.
- Captures: tmp/logs/rtk_parity-<side>.json. Log: tmp/logs/rtk_parity.log.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console, laser, network_on  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CMDS = ROOT / "scripts/rtk_parity_cmds.json"
LOG = ROOT / "tmp/logs/rtk_parity.log"
PROMPTS = {"stock": r"\r?\nRTL9300# ", "ours": r"\r?\nst1008f-mainline # "}
DEFAULT_CAP = 2  # replies are <1 KB (~90 ms at 115200); 2 s names a hang without waiting long

# Flash writers (docs/UBOOT-REFERENCE.md, issue #24) plus anything that boots, resets or forces.
DENY = re.compile(
    r"\b(saveenv|savesys|setsys|upgrade|flerase|erase|protect|boota|bootm|bootp|tftpboot|reset|go)\b"
    r"|\bsf\s+(write|erase|update)\b"
    r"|\brtk\s+(boardid|boardmodel)\s+\S"
    r"|\brtk\s+(init|rtcore-init|network|port-isolation|send|macsds\s+set\s+\d+\s+(?!bogus\b)\w+)"
    r"|\S*force\b", re.I)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def denied(cmd: str) -> bool:
    return any(DENY.search(part) for part in cmd.split(";"))


def clean(cmd: str, raw: str) -> str:
    """Drop the echoed command line and the trailing prompt; normalise line ends."""
    lines = raw.replace("\r", "").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and cmd[:12] in lines[0]:
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and re.match(r"^(RTL9300|st1008f-mainline) ?#", lines[-1]):
        lines.pop()
    return "\n".join(ln.rstrip() for ln in lines).strip("\n")


def run_one(con: Console, side: str, c: dict) -> str:
    cap = c.get("cap", DEFAULT_CAP)
    prompt = PROMPTS[side]
    if c.get("kind") == "key":
        mark = con.size()
        con.send(c["cmd"])
        try:
            con.expect(c["key_after"], cap, mark, c["cmd"] + " (wait for key prompt)")
            con.send("")  # one CR = "press any"
            _, out = con.expect(prompt, cap, mark, c["cmd"] + " (after key)")
        except SystemExit as e:
            return f"<<TIMEOUT: {e}>>"
        return out
    try:
        _, out = con.run(c["cmd"], prompt, cap, c["cmd"])
    except SystemExit as e:
        return f"<<TIMEOUT: {e}>>"
    return out


def capture(side: str, with_state: bool, with_slow: bool) -> Path:
    con = Console()
    cmds = json.loads(CMDS.read_text())["commands"]
    res = {}
    # stock has no `echo`; printenv exists on both
    con.run("printenv baudrate", r"\r?\nbaudrate=\d+" + PROMPTS[side], 1, f"{side} prompt present")
    phases = ["pre", "post"] if side == "stock" else ["any"]
    for phase in phases:
        if side == "stock" and phase == "post":
            log("stock: rtk network on (once per boot)")
            network_on(con)
            laser(con, 1)  # all lasers come up on: one cage only (cage loop)
        for c in cmds:
            if side == "stock" and c.get("phase", "post") != phase:
                continue
            kind = c.get("kind", "read")
            if kind == "ours" and side == "stock":
                continue
            if (kind == "state" and not with_state) or (kind in ("slow", "key") and not with_slow):
                log(f"skip ({kind}, flag not given): {c['cmd']}")
                continue
            if denied(c["cmd"]):
                log(f"DENIED (flash/boot/force denylist), not sent: {c['cmd']}")
                continue
            raw = run_one(con, side, c)
            if raw.startswith("<<TIMEOUT"):
                res[c["cmd"]] = "<<TIMEOUT>>"
                log(f"{side}: {c['cmd']!r} TIMEOUT: console dead, stopping this side ({raw[:200]})")
                break
            res[c["cmd"]] = clean(c["cmd"], raw)
            log(f"{side}: {c['cmd']!r} -> {len(res[c['cmd']])} chars")
        else:
            continue
        break
    out = ROOT / f"tmp/logs/rtk_parity-{side}.json"
    out.write_text(json.dumps(res, indent=1))
    log(f"wrote {out.relative_to(ROOT)}")
    return out


def norm(text: str, masks: list[str]) -> str:
    for m in masks:
        text = re.sub(m, "<X>", text)
    return text


def compare() -> int:
    cmds = json.loads(CMDS.read_text())["commands"]
    sides = {}
    for s in ("stock", "ours"):
        p = ROOT / f"tmp/logs/rtk_parity-{s}.json"
        sides[s] = json.loads(p.read_text()) if p.exists() else {}
    counts: dict[str, int] = {}
    rows = []
    for c in cmds:
        cmd = c["cmd"]
        st, ou = sides["stock"].get(cmd), sides["ours"].get(cmd)
        if c.get("kind") == "ours":
            verdict = "ONLY-OURS" if ou is not None else "NO-OURS"
        elif st is None or ou is None:
            verdict = "NO-STOCK" if st is None else "NO-OURS"
        else:
            m = c.get("mask", [])
            verdict = "PASS" if norm(st, m) == norm(ou, m) else "DIFF"
        counts[verdict] = counts.get(verdict, 0) + 1
        rows.append((verdict, cmd, st, ou))
    for verdict, cmd, st, ou in rows:
        log(f"{verdict:<9} {cmd}")
        if verdict == "DIFF":
            log("    stock: " + repr(st))
            log("    ours : " + repr(ou))
    log("=== " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return 1 if counts.get("DIFF") else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["capture", "compare", "both"])
    ap.add_argument("--side", choices=["stock", "ours"], help="for capture")
    ap.add_argument("--state", action="store_true", help="include kind=state (sdsreg set, port disable/enable)")
    ap.add_argument("--slow", action="store_true", help="include kind=slow/key (ledtest)")
    a = ap.parse_args()
    if a.action == "compare":
        return compare()
    if a.action == "capture":
        if not a.side:
            ap.error("capture needs --side")
        capture(a.side, a.state, a.slow)
        return 0
    import subprocess
    # fresh boot, stock prompt, NO network on: the stock "pre" phase must run before it
    r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "stock", "--no-network"],
                       timeout=30)  # relay + daemon restart + banner ~6 s; 30 s names a hang
    if r.returncode:
        log(f"stock boot failed rc={r.returncode}")
        return r.returncode
    capture("stock", a.state, a.slow)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "uboot-mainline",
                        "--no-cycle", "--no-network"], timeout=90)  # TFTP ~10 s + go; 90 s names a hang
    if r.returncode:
        log(f"ramload failed rc={r.returncode}")
        return r.returncode
    capture("ours", a.state, a.slow)
    return compare()


if __name__ == "__main__":
    sys.exit(main())
