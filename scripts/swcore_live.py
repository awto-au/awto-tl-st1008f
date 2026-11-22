#!/usr/bin/env python3
"""swcore_live — one live switch-core clock step on sw2 running OpenWrt (no ramload, no reboot), then zc forwarding + checksums (#148).

- Core = SW VCO / (2 x (code + 2)); VCO = 50 x (e214 NCODE + 2); LX = VCO / (2 x (LX code + 2)); NOR = VCO / (2 x (NOR code + 2)).
- Needs sw2 booted with the 608 profile (e220 0x36826, e214 0x478); aborts otherwise. Words per docs/CLOCKS.md: e214 = live & ~0xff0 | NCODE << 4;
  e220 = live & ~0x1ffe0 | NOR << 13 | LX << 9 | code << 5. Order e220 -> e214 when the VCO rises (dividers first), e214 -> e220 when it falls; relock e200 last.
- Always restores the 608 words in `finally` (ssh, then console fallback + `ip link set eth0 down/up`). A hard hang is caught by the board watchdog (kept running, ~28 s).
- NOR clock must stay <= 153.1 MHz (SPI 25.5 MHz, #50): refused above. Linux must not read flash during a step (nothing here does).
- `swcore_live.py --tag 708 --vco 4250 --lx 5 --nor 12 [--code 1] [--secs 8]`; log tmp/logs/swcore_live_TAG.log
"""
import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IP = "192.168.25.56"
SSH = ["ssh", "-o", "ConnectTimeout=4", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes", "-q", f"root@{IP}"]
BASE = {"e214": 0x478, "e220": 0x36826}  # 608 profile = known good
LOG = None


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(cmd, tmo):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=tmo, cwd=ROOT)
        return r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return 124, f"[timeout {tmo}s] {' '.join(cmd)[:100]}"


def ssh(cmd, tmo=12):
    rc, out = run(SSH + [cmd], tmo)
    return out.strip() if rc == 0 else ""


def words(e214, e220, vco_old, vco_new):
    seq = [("e220", e220), ("e214", e214)] if vco_new >= vco_old else [("e214", e214), ("e220", e220)]
    addr = {"e214": "0x1b00e214", "e220": "0x1b00e220"}
    cmd = "; ".join(f"devmem {addr[n]} 32 0x{v:x}" for n, v in seq)
    return cmd + "; devmem 0x1b00e200 32 0x0001c0ff; devmem 0x1b00e200 32 0x4001c0ff"


def alive(tries=8):
    for _ in range(tries):  # 8 x (1 ping + 2 s wait) bounds the wait at ~25 s; the relock drops the link ~1 s
        if run(["ping", "-c", "1", "-W", "2", IP], 5)[0] == 0 and ssh("echo ok", 8) == "ok":
            return True
    return False


def restore(vco_now, lx_mhz=304.17):
    cmd = words(BASE["e214"], BASE["e220"], vco_now, 3650)
    if alive(2):
        ssh(cmd, 15)
    else:
        # UART divisor was fixed at boot for LX 304.17: the real baud scales with LX; the host follows for the restore line
        baud = round(115200 * lx_mhz / 304.17)
        log(f"restore: no ssh, console fallback at {baud} baud")
        run([sys.executable, "scripts/switch_console.py", "baud", str(baud)], 10)
        run([sys.executable, "scripts/switch_console.py", "send", cmd, "--secs", "6"], 30)
        run([sys.executable, "scripts/switch_console.py", "baud", "115200"], 10)
        run([sys.executable, "scripts/switch_console.py", "send", "ip link set eth0 down; ip link set eth0 up; ip link set lan1 up", "--secs", "6"], 30)
    ok = alive(8)
    got = ssh("devmem 0x1b00e214 32; devmem 0x1b00e220 32").split() if ok else []
    log(f"restore to 608: {'OK' if ok else 'FAILED'} e214/e220 {got}")
    return ok


def kpps(out, key):
    m = re.search(key + r".*?= ([0-9.]+) kpps", out)
    return m.group(1) if m else "?"


def main():
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--vco", type=int, required=True, help="MHz, multiple of 50")
    ap.add_argument("--lx", type=int, required=True, help="DIVN2_LXB code")
    ap.add_argument("--nor", type=int, required=True, help="DIVN2_SPI_NOR code")
    ap.add_argument("--code", type=int, default=1, help="DIVN2_SWCORE code (0 wedges, #148)")
    ap.add_argument("--secs", type=int, default=8)
    a = ap.parse_args()
    LOG = ROOT / f"tmp/logs/swcore_live_{a.tag}.log"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    if a.vco % 50 or a.code == 0:
        sys.exit("vco must be a multiple of 50, code 0 is the known wedge")
    core, lx, nor = a.vco / (2 * (a.code + 2)), a.vco / (2 * (a.lx + 2)), a.vco / (2 * (a.nor + 2))
    log(f"step {a.tag}: VCO {a.vco}, core {core:.1f} (code {a.code}), LX {lx:.1f} (code {a.lx}), NOR {nor:.1f} (code {a.nor}) SPI {nor / 6:.1f}")
    if nor > 153.2:
        sys.exit(f"NOR {nor:.1f} MHz above the stock 153.1: SPI would exceed 25.5 MHz (#50)")
    live = ssh("devmem 0x1b00e214 32; devmem 0x1b00e220 32").split()
    if len(live) != 2 or int(live[0], 16) != BASE["e214"] or int(live[1], 16) != BASE["e220"]:
        sys.exit(f"sw2 is not on the 608 profile: e214/e220 {live}")
    e214 = (BASE["e214"] & ~0xff0) | ((a.vco // 50 - 2) << 4)
    e220 = (BASE["e220"] & ~0x1ffe0) | a.nor << 13 | a.lx << 9 | a.code << 5
    log(f"words e214 0x{e214:x} e220 0x{e220:x}; temp {int(ssh('cat /sys/class/thermal/thermal_zone0/temp') or -1) / 1000:.1f} C")
    run(["./dev.py", "irq-check", "pin", "eth0", "2"], 30)
    run([sys.executable, "scripts/nat_bench.py", "setup"], 60)
    run([sys.executable, "scripts/nat_bench.py", "mode", "nat"], 30)
    status, vco_now = "PASS", 3650
    lx_now = 304.17
    try:
        ssh(words(e214, e220, 3650, a.vco), 15)
        vco_now, lx_now = a.vco, lx
        if not alive():
            status = "HANG@apply"
        else:
            log(f"applied: e214/e220 {ssh('devmem 0x1b00e214 32; devmem 0x1b00e220 32').split()}")
            # fwd run = stack baseline + zc+nat + payload checksum check ("checksums: ok"); 8 s runs ~30 s, cap 100 s
            for name, cmd, tmo in (("fwd", [sys.executable, "scripts/zc_bench.py", "--nat", "--secs", str(a.secs), "--len", "1400"], 100),):
                rc, out = run(cmd, tmo)
                keep = [ln[-150:] for ln in out.splitlines() if any(k in ln for k in ("zc+nat", "checksums", "zc /", "ntegrity", "timed out"))]
                log(f"stage {name} rc {rc}: " + " | ".join(keep[-4:]))
                log(f"temp after {name}: {int(ssh('cat /sys/class/thermal/thermal_zone0/temp') or -1) / 1000:.1f} C")
                if rc or "checksums: ok" not in out or not alive():
                    status = f"FAIL@{name}"
                    break
    finally:
        ok = restore(vco_now, lx_now)
    log(f"RESULT {a.tag}: {status}; restore {'OK' if ok else 'FAILED'}")
    return 0 if status == "PASS" and ok else 1


if __name__ == "__main__":
    sys.exit(main())
