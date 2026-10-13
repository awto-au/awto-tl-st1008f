#!/usr/bin/env python3
"""boot_timeline — stage table of the last Linux boot of a running OpenWrt, gaps flagged (#114).

- `run [--ip A.B.C.D] [--gap S] [--label L]`: pulls /proc/uptime, date, dmesg, logread over SSH
  (read-only); stage = first line matching each STAGES regex; kernel lines carry their own
  timestamp, logread lines are placed by wall time anchored at logd start (1 s resolution;
  lines after an NTP step are dropped). Prints the table, flags gaps >= --gap (default 3 s),
  saves tmp/boot-timeline/<label>.json. Log: tmp/logs/boot_timeline.log
- `compare A B`: delta per stage between two saved runs (labels or json paths).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/boot_timeline.log"
OUT = ROOT / "tmp/boot-timeline"
SSH_S = 5    # dropbear connect ~1 s on the LAN; x5
PULL_S = 20  # two ~200 KB ring buffers + MIPS cat ~2 s; x10 for a loaded first boot
REMOTE = "cat /proc/uptime; date +%s; echo ===DMESG; dmesg; echo ===LOGREAD; logread; echo ===STAMPS; cat /tmp/st1008f-boot.log 2>/dev/null; true"
KERNEL_TS = re.compile(r"^\[\s*(\d+\.\d+)\] (.*)$")
SYSLOG = re.compile(r"^(?P<wall>\w{3} \w{3} +\d+ [\d:]+ \d{4}) (?P<fac>\w+)\.(?P<pri>\w+) (?P<prog>[^:]+): (?P<msg>.*)$")
NTP_STEP_S = 60  # wall clock jump larger than this = NTP step (board has no RTC)

# (stage, source, regex); first match wins; kernel = dmesg, user = logread non-kernel lines
STAGES = [
    ("kernel start", "kernel", r"Linux version "),
    ("smp up", "kernel", r"smp: Brought up"),
    ("switch probed", "kernel", r"rtl83xx-switch .*led_set0|rtl83xx-switch .*: Link is Up"),
    ("sfp modules read", "kernel", r"sfp sfp-p\d: module "),
    ("init", "kernel", r"Run /sbin/init|Run /init"),
    ("preinit", "kernel", r"init: - preinit -"),
    ("failsafe wait", "kernel", r"preinit: \S+ failsafe_wait start "),
    ("failsafe done", "kernel", r"preinit: \S+ failsafe_wait end "),
    ("overlay mounted", "kernel", r"preinit: \S+ do_mount_root end "),
    ("preinit end", "kernel", r"preinit: \S+ run_init start "),
    ("crng ready", "kernel", r"random: crng init done"),
    ("eth0 up", "kernel", r"eth0: Link is Up"),
    ("first lan up", "kernel", r"lan\d: Link is Up"),
    ("procd early", "kernel", r"procd: - early -"),
    ("procd init", "kernel", r"procd: - init -"),
    ("dropbear", "user", r"^dropbear.*Not backgrounding"),
    ("linkcheck", "user", r"^st1008f-linkcheck.*verdict|^st1008f-linkcheck: live"),
    ("netifd lan up", "user", r"^netifd: Interface 'lan' is now up"),
    ("bridge up", "user", r"^netifd: bridge 'switch' link is up"),
    ("init complete", "user", r"^procd: - init complete -"),
    ("selftest", "user", r"^st1008f-selftest: "),
]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def pull(ip: str) -> tuple[float, float, str, str, str]:
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes",
                        # bench unit: a new dropbear key on every RAM boot / install (as nat_bench, mtd_backup)
                        "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                        "-o", "LogLevel=ERROR", f"root@{ip}", REMOTE],
                       capture_output=True, text=True, timeout=PULL_S)
    if r.returncode:
        raise SystemExit(f"FAIL ssh root@{ip}: rc {r.returncode} {r.stderr.strip()}")
    head, _, rest = r.stdout.partition("===DMESG\n")
    dmesg, _, logread = rest.partition("===LOGREAD\n")
    logread, _, stamps = logread.partition("===STAMPS\n")
    up, now = float(head.split()[0]), float(head.split()[2])
    return up, now - up, dmesg, logread, stamps


def wall(s: str) -> float:
    return datetime.strptime(s, "%a %b %d %H:%M:%S %Y").timestamp()


# "rc: S19dropbear boot start 17.31" (rc.common) / "preinit: preinit_main failsafe_wait end 12.03" (hook wrapper)
STAMP = re.compile(r"^(rc|preinit): (\S+) (\S+) (start|end) ([\d.]+)$")


def events(dmesg: str, logread: str, stamps: str = "", boot_epoch: float | None = None) -> list[tuple[float, str, str]]:
    """(uptime_s, source, text) for every line: dmesg by kernel ts, /tmp/st1008f-boot.log stamps by their
    own uptime (source "kernel": same clock), logread by wall time minus the boot epoch (now - uptime).
    The board has no RTC: before an NTP step its clock runs from 1970 (or sysfixtime's guess), so lines
    before the step are placed with the epoch logd started at (newest replayed kernel ts at its start)."""
    ev = []
    for raw in dmesg.splitlines():
        m = KERNEL_TS.match(raw)
        if m:
            ev.append((float(m[1]), "kernel", m[2].rstrip()))
    for raw in stamps.splitlines():
        m = STAMP.match(raw.strip())
        if m:
            ev.append((float(m[5]), "kernel", raw.strip()))
    rows = []
    for raw in logread.splitlines():
        m = SYSLOG.match(raw)
        if m:
            rows.append((wall(m["wall"]), m["prog"], m["msg"]))
    w0 = anchor = None  # logd start: replayed kernel lines all carry W0; newest kernel ts among them
    for w, prog, msg in rows:
        if not prog.startswith("kernel"):
            continue
        k = KERNEL_TS.match(msg)
        if w0 is None:
            w0 = w
        if k and w == w0:
            anchor = float(k[1])
    epoch_pre = (w0 - anchor) if w0 is not None and anchor is not None else None
    step_at = None  # first wall time after the NTP step (consecutive lines jump > NTP_STEP_S)
    for (w1, _, _), (w2, _, _) in zip(rows, rows[1:]):
        if w2 - w1 > NTP_STEP_S:
            step_at = w2
            break
    for w, prog, msg in rows:
        if prog.startswith("kernel"):
            continue  # kernel lines duplicate dmesg
        epoch = epoch_pre if step_at is None or w < step_at else boot_epoch
        if epoch is None:
            continue
        ev.append((w - epoch, "user", f"{prog}: {msg}"))
    ev.sort(key=lambda e: e[0])
    return ev


def stages(ev: list[tuple[float, str, str]]) -> list[tuple[str, float, str]]:
    out = []
    for name, src, rx in STAGES:
        pat = re.compile(rx)
        for t, s, text in ev:
            if s == src and pat.search(text):
                out.append((name, t, text[:90]))
                break
    return sorted(out, key=lambda r: r[1])


RC_STAMP = re.compile(r"^rc: (\S+) (\S+) (start|end) ([\d.]+)$")


def rc_scripts(ev: list[tuple[float, str, str]]) -> list[tuple[str, float, float]]:
    """(item, start, duration) from the stamps: init scripts "S19dropbear boot" and preinit hook
    functions "preinit_main failsafe_wait", in start order."""
    start: dict[str, float] = {}
    out = []
    for _, src, text in ev:
        m = STAMP.match(text) if src == "kernel" else None
        if not m:
            continue
        key, t = f"{m[2]} {m[3]}", float(m[5])
        if m[4] == "start":
            start[key] = t
        elif key in start:
            t0 = start.pop(key)
            out.append((key, t0, t - t0))
    return sorted(out, key=lambda r: r[1])


def run(a) -> int:
    up, boot_epoch, dmesg, logread, stamps = pull(a.ip)
    ev = events(dmesg, logread, stamps, boot_epoch)
    st = stages(ev)
    label = a.label or f"{a.ip}-{time.strftime('%Y%m%d-%H%M%S')}"
    log(f"{a.ip}: uptime {up:.0f} s, {len(st)} stages, gaps >= {a.gap:.0f} s flagged")
    prev = 0.0
    rows = []
    for name, t, text in st:
        gap = t - prev
        flag = " <-- gap" if gap >= a.gap else ""
        log(f"  {t:7.2f}  +{gap:6.2f}  {name:18s} {text}{flag}")
        rows.append({"stage": name, "t": round(t, 2), "gap": round(gap, 2), "line": text})
        prev = t
    scripts = rc_scripts(ev)
    if scripts:
        log(f"  stamped steps (preinit hooks + init scripts), {len(scripts)}; >= 1 s flagged:")
        for key, t0, dur in scripts:
            log(f"  {t0:7.2f}  {dur:6.2f}  {key}{'  <-- slow' if dur >= 1 else ''}")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{label}.json"
    path.write_text(json.dumps({"ip": a.ip, "label": label, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                "uptime_s": up, "stages": rows,
                                "scripts": [{"script": k, "t": round(t0, 2), "s": round(d, 2)} for k, t0, d in scripts]},
                               indent=1))
    log(f"saved {path.relative_to(ROOT)}")
    return 0


def load(ref: str) -> dict:
    p = Path(ref) if ref.endswith(".json") else OUT / f"{ref}.json"
    return json.loads(p.read_text())


def compare(a) -> int:
    x, y = load(a.a), load(a.b)
    tx = {r["stage"]: r["t"] for r in x["stages"]}
    ty = {r["stage"]: r["t"] for r in y["stages"]}
    log(f"compare {x['label']} -> {y['label']} (s at stage, delta)")
    for name, _, _ in STAGES:
        if name in tx or name in ty:
            sa, sb = tx.get(name), ty.get(name)
            d = f"{sb - sa:+7.2f}" if sa is not None and sb is not None else "      -"
            log(f"  {name:18s} {sa if sa is not None else '-':>8} {sb if sb is not None else '-':>8} {d}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--ip", default=BENCH_IP)
    r.add_argument("--gap", type=float, default=3.0)
    r.add_argument("--label")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    a = ap.parse_args()
    return run(a) if a.cmd == "run" else compare(a)


if __name__ == "__main__":
    sys.exit(main())
