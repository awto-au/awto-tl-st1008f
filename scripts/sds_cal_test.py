#!/usr/bin/env python3
"""sds_cal_test — does a SerDes calibrated with no input signal link once the partner lights? (#125)

- sw2 looped pairs (lan3<->lan4 DAC, lan7<->lan8 fibre), both ports out of the bridge (linkcheck keeps
  looped cages down), so no loop. Calibration runs once per boot, at a port's first `ip link set up`
  (pcs post_config on the mode change): the test needs both ports unconfigured since boot (`--reboot`).
- Sequence: FIRST up alone (its partner is down: no signal at its calibration), carrier read; SECOND up
  (calibrates against FIRST's signal); both carriers polled for WATCH_S; both down again.
- Log: tmp/logs/sds_cal_test.log; results in docs/SDS-TOOLS.md (#125).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sds_cal_test.log"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes"]
CMD_S = 10      # one SSH command, board-side sleeps excluded: < 1 s on a quiet LAN; x10 for SSH setup
ALONE_S = 3     # FIRST alone: SerDes config + calibration ~0.6 s (dmesg), link would be ~1 s; x3
WATCH_S = 10    # carrier watch after SECOND up: a calibrated pair links ~1.1 s after up; ~10x = "stuck"
BOOT_S = 240    # uboot_chain_env boot backstop (boot_link_check.py BOOT_S)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, extra_s: float = 0) -> str:
    r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=CMD_S + extra_s)
    if r.returncode:
        raise SystemExit(f"FAIL ssh {cmd[:50]!r}: rc {r.returncode} {r.stderr.strip()[:200]}")
    return r.stdout


def wait_ssh(ip: str) -> None:
    for _ in range(12):  # boot -> dropbear: flow returns at the console prompt, SSH within ~10 s; 12 x 5 s
        if subprocess.run([*SSH, f"root@{ip}", "true"], capture_output=True).returncode == 0:
            return
    raise SystemExit("FAIL: no SSH after the reboot")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--first", default="lan3")
    ap.add_argument("--second", default="lan4")
    ap.add_argument("--reboot", action="store_true", help="chain-boot sw2 first (fresh, unconfigured SerDes)")
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    f, s = a.first, a.second
    sds = {p: int(p[3:]) + 1 for p in (f, s)}  # cage N = lanN = SerDes N+1
    if a.reboot:
        r = subprocess.run([sys.executable, str(ROOT / "scripts/uboot_chain_env.py"), "boot"],
                           capture_output=True, text=True, timeout=BOOT_S)
        if r.returncode:
            raise SystemExit(f"FAIL chain boot: {(r.stderr.strip() or r.stdout.strip()).splitlines()[-1:]}")
        wait_ssh(a.ip)
    st = ssh(a.ip, f"for p in {f} {s}; do [ -e /sys/class/net/$p/master ] && echo BRIDGED $p; "
                   f"echo OPER $p $(cat /sys/class/net/$p/operstate); done; dmesg | grep 'SerDes [0-9]* configured'")
    if "BRIDGED" in st:
        raise SystemExit(f"FAIL: a port is in a bridge (loop risk): {st.strip()}")
    done = [n for n in sds.values() if re.search(rf"SerDes {n} configured", st)]
    if done:
        raise SystemExit(f"FAIL: SerDes {done} already configured this boot; use --reboot")
    log(f"=== {f} (SerDes {sds[f]}) up alone, then {s} (SerDes {sds[s]})")
    # PCS debug on (DYNAMIC_DEBUG, #125): "no RX signal within 10 ms" shows what each SerDes saw at calibration
    ssh(a.ip, "c=/sys/kernel/debug/dynamic_debug/control; [ -w $c ] && echo 'file pcs-rtl-otto.c +p' > $c || true")
    out = ssh(a.ip, f"ip link set {f} up; sleep {ALONE_S}; echo ALONE $(cat /sys/class/net/{f}/carrier)", ALONE_S)
    alone = re.search(r"ALONE (\d)", out)
    poll = (f"ip link set {s} up; i=0; while [ $i -lt {WATCH_S} ]; do sleep 1; i=$((i+1)); "
            f"echo T $i $(cat /sys/class/net/{f}/carrier) $(cat /sys/class/net/{s}/carrier); done")
    out = ssh(a.ip, poll, WATCH_S)
    rows = re.findall(r"T (\d+) (\d) (\d)", out)
    t_f = next((int(t) for t, cf, _ in rows if cf == "1"), None)
    t_s = next((int(t) for t, _, cs in rows if cs == "1"), None)
    dm = ssh(a.ip, f"dmesg | grep -E '{f}:|{s}:|SerDes ({sds[f]}|{sds[s]})[: ]' | tail -12")
    ssh(a.ip, f"ip link set {f} down; ip link set {s} down")
    log(f"  {f} alone {ALONE_S} s: carrier {alone[1] if alone else '?'}")
    log(f"  after {s} up: {f} carrier at {t_f if t_f else f'never ({WATCH_S} s)'} s, "
        f"{s} carrier at {t_s if t_s else f'never ({WATCH_S} s)'} s")
    log("  dmesg: " + " | ".join(ln.strip() for ln in dm.splitlines()))
    stuck = t_f is None and t_s is not None
    log(f"result: {'DARK-CALIBRATED PORT STUCK' if stuck else 'both linked' if t_f and t_s else 'other'} "
        f"({f} first)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
