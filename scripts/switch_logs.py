#!/usr/bin/env python3
"""switch_logs — full dmesg + logread of a running OpenWrt over SSH, classified. Read-only.

- Pulls `dmesg` and `logread` (whole ring buffers), saves both to tmp/switch-logs/<host>-<ts>/.
- dmesg lines: boot_log_allowlist.txt sections [linux] + [openwrt] (OpenWrt 6.18) decide
  ok / known (#NN) / ERROR (DENY word, not known) / UNKNOWN.
- logread: non-kernel lines at warn/err/crit/alert/emerg, plus DENY words at any level.
- Groups by message with digits folded; prints count, first/last kernel time, a sample.
- Also lists pending uci-defaults, fw_env/fw_sys.config and `fw_printenv -n ethaddr` (#86).
- No writes on the switch: only `cat`, `ls`, `dmesg`, `logread`, `uname`, `fw_printenv`. Log: tmp/logs/switch_logs.log
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boot_log_check import DEFAULT_ALLOW, DENY, KERNEL_TS, load_allow  # noqa: E402
from boards import SW1_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/switch_logs.log"
OUT = ROOT / "tmp/switch-logs"
SSH_S = 5   # dropbear connect ~1 s on the LAN; x5
PULL_S = 20  # 2 x ~200 KB ring buffers over 1G LAN + MIPS cat: ~2 s; generous for first keygen
REMOTE = ("cat /proc/uptime; uname -r; echo ===DMESG; dmesg; echo ===LOGREAD; logread; echo ===ENV; "
          "ls /etc/uci-defaults; cat /etc/fw_env.config /etc/fw_sys.config; fw_printenv -n ethaddr 2>&1")
SYSLOG = re.compile(r"^\w{3} \w{3} +\d+ [\d:]+ \d{4} (?P<fac>\w+)\.(?P<pri>\w+) (?P<prog>[^:]+): (?P<msg>.*)$")
BAD_PRI = {"warn", "err", "crit", "alert", "emerg"}


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(msg + "\n")


def fold(s: str) -> str:
    s = re.sub(r"\b[0-9a-f]{2}(:[0-9a-f]{2}){5}\b", "<mac>", s, flags=re.I)
    return re.sub(r"\d+", "N", s)


def classify(text: str, rules) -> tuple[str, str]:
    for pat, reason, known in rules:
        if pat.fullmatch(text):
            if DENY.search(text):
                return {"known": ("known", reason), "benign": ("ok", reason)}.get(known, ("ERROR", reason))
            return "ok", reason
    return ("ERROR" if DENY.search(text) else "UNKNOWN"), ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=SW1_IP)
    ap.add_argument("--show-ok", action="store_true")
    a = ap.parse_args()
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes",
                        "-o", "StrictHostKeyChecking=accept-new", f"root@{a.ip}", REMOTE],
                       capture_output=True, text=True, timeout=PULL_S)
    if r.returncode:
        log(f"FAIL ssh root@{a.ip}: rc {r.returncode} {r.stderr.strip()}")
        return 1
    head, _, rest = r.stdout.partition("===DMESG\n")
    dmesg, _, logread = rest.partition("===LOGREAD\n")
    logread, _, env = logread.partition("===ENV\n")
    out = OUT / f"{a.ip}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "dmesg.txt").write_text(dmesg)
    (out / "logread.txt").write_text(logread)
    up, kver = head.split()[0], head.split()[-1]
    log(f"{a.ip}: kernel {kver}, uptime {float(up):.0f} s; dmesg {dmesg.count(chr(10))} lines, "
        f"logread {logread.count(chr(10))} lines -> {out.relative_to(ROOT)}")
    for ln in env.splitlines():  # fw_env.config + pending uci-defaults (#86)
        log(f"env: {ln}")
    allow = load_allow(DEFAULT_ALLOW)
    rules = allow.get("linux", []) + allow.get("openwrt", [])
    groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for raw in dmesg.splitlines():
        m = KERNEL_TS.match(raw)
        t = raw[:m.end()].strip() if m else ""
        text = KERNEL_TS.sub("", raw).rstrip()
        if not text:
            continue
        cls, reason = classify(text, rules)
        groups[("dmesg", cls, fold(text))].append(f"{t} {text}  {reason}".rstrip())
    for raw in logread.splitlines():
        m = SYSLOG.match(raw)
        if not m or m["prog"].startswith("kernel"):
            continue  # kernel lines duplicate dmesg
        if m["pri"] in BAD_PRI or DENY.search(m["msg"]):
            groups[("logread", m["pri"], fold(f"{m['prog']}: {m['msg']}"))].append(raw)
    order = {"ERROR": 0, "UNKNOWN": 1, "known": 2}
    bad = 0
    for (src, cls, key), lines in sorted(groups.items(), key=lambda kv: (kv[0][0], order.get(kv[0][1], 3))):
        if cls == "ok" and not a.show_ok:
            continue
        bad += cls in ("ERROR", "UNKNOWN") or src == "logread" and cls in ("err", "crit", "alert", "emerg")
        log(f"{src} {cls:7s} x{len(lines):<4d} first: {lines[0][:200]}")
        if len(lines) > 1:
            log(f"{'':16s}last:  {lines[-1][:200]}")
    log(f"{'FAIL' if bad else 'PASS'}: {bad} unreviewed/err groups ({a.ip})")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
