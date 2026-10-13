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
REMOTE = "cat /proc/uptime; date +%s; echo ===DMESG; dmesg; echo ===LOGREAD; logread"
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


def pull(ip: str) -> tuple[float, str, str]:
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes",
                        "-o", "StrictHostKeyChecking=accept-new", f"root@{ip}", REMOTE],
                       capture_output=True, text=True, timeout=PULL_S)
    if r.returncode:
        raise SystemExit(f"FAIL ssh root@{ip}: rc {r.returncode} {r.stderr.strip()}")
    head, _, rest = r.stdout.partition("===DMESG\n")
    dmesg, _, logread = rest.partition("===LOGREAD\n")
    return float(head.split()[0]), dmesg, logread


def wall(s: str) -> float:
    return datetime.strptime(s, "%a %b %d %H:%M:%S %Y").timestamp()


def events(dmesg: str, logread: str) -> list[tuple[float, str, str]]:
    """(uptime_s, source, text) for every line, logread placed by wall time anchored at logd start."""
    ev = []
    for raw in dmesg.splitlines():
        m = KERNEL_TS.match(raw)
        if m:
            ev.append((float(m[1]), "kernel", m[2].rstrip()))
    # logd replays the kernel ring with its own start time W0: the newest kernel ts at W0 = uptime(W0)
    w0 = anchor = None
    last_wall = None
    for raw in logread.splitlines():
        m = SYSLOG.match(raw)
        if not m:
            continue
        w = wall(m["wall"])
        if m["prog"].startswith("kernel"):
            k = KERNEL_TS.match(m["msg"])
            if w0 is None:
                w0 = w
            if k and w == w0:
                anchor = float(k[1])
            continue
        if w0 is None or anchor is None:
            continue
        if last_wall is not None and w - last_wall > NTP_STEP_S:
            break  # clock stepped (NTP): later lines carry no boot time
        last_wall = w
        ev.append((anchor + (w - w0), "user", f"{m['prog']}: {m['msg']}"))
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


def run(a) -> int:
    up, dmesg, logread = pull(a.ip)
    st = stages(events(dmesg, logread))
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
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{label}.json"
    path.write_text(json.dumps({"ip": a.ip, "label": label, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                                "uptime_s": up, "stages": rows}, indent=1))
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
