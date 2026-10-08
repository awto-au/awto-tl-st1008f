#!/usr/bin/env python3
"""st1008_thermal_stress — CPU-load the switch under RAM-booted OpenWrt while logging the on-die thermal meter.

- Meter is OFF at power-on (RESULT_0 holds a reset value, VALID clear). Enables it like OpenWrt's realtek-thermal
  driver: CTRL_1.SAMPLE_DLY = 0x0800, CTRL_2.TM_ENABLE (bit 16). Reads RESULT_0 (phys 0x1B00006C): VALID = bit 24,
  TEMP_OUT = bits 23:16, °C directly (OpenWrt DTS coefficients <1000 0>). Over SSH (`devmem`).
- Starts one `yes > /dev/null` per CPU, polls every --interval s, and runs `killall yes` on any abort:
  meter >= --abort-temp, --duration elapsed, SSH failure, or Ctrl-C.

Usage:
    scripts/st1008_thermal_stress.py --host <switch-ip> [--abort-temp 85] [--duration 600] [--interval 5] [--no-load]

Output: tmp/logs/st1008_thermal_stress.log and a CSV in private/thermal/<ts>.csv
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

LOG = Path("tmp/logs/st1008_thermal_stress.log")
METER_PHYS = 0x1B00006C
CTRL1_PHYS, CTRL2_PHYS = 0x1B000064, 0x1B000068
TEMP_VALID = 1 << 24
SSH_OPTS = ["-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "BatchMode=yes", "-o", "LogLevel=ERROR",
            # LAN host, sub-ms RTT; 5 s covers TCP + key exchange with margin.
            "-o", "ConnectTimeout=5"]
SSH_CMD_TIMEOUT = 8.0  # one-line remote command on an idle-ish 800 MHz MIPS; ×~1.5 over connect
_log_fh = None


def log(msg: str):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    _log_fh.write(line + "\n")
    _log_fh.flush()


def ssh(host: str, cmd: str) -> str:
    r = subprocess.run(["ssh", *SSH_OPTS, f"root@{host}", cmd], capture_output=True,
                       text=True, timeout=SSH_CMD_TIMEOUT)
    if r.returncode:
        raise RuntimeError(f"ssh rc={r.returncode}: {r.stderr.strip()}")
    return r.stdout.strip()


def enable_meter(host: str):
    """RMW CTRL_1 sample delay + CTRL_2 TM_ENABLE (same as OpenWrt rtl9300_thermal_init)."""
    c1 = int(ssh(host, f"devmem 0x{CTRL1_PHYS:08X} 32"), 16)
    c2 = int(ssh(host, f"devmem 0x{CTRL2_PHYS:08X} 32"), 16)
    ssh(host, f"devmem 0x{CTRL1_PHYS:08X} 32 0x{(c1 & 0xFFFF) | (0x0800 << 16):08X}")
    ssh(host, f"devmem 0x{CTRL2_PHYS:08X} 32 0x{c2 | (1 << 16):08X}")


def read_temp(host: str) -> tuple[int, int]:
    raw = int(ssh(host, f"devmem 0x{METER_PHYS:08X} 32"), 16)
    if not raw & TEMP_VALID:
        raise RuntimeError(f"meter not valid (raw 0x{raw:08x}); is TM_ENABLE set?")
    return (raw >> 16) & 0xFF, raw


def stop_load(host: str):
    try:
        ssh(host, "killall yes 2>/dev/null; true")
        log("load stopped (killall yes)")
    except Exception as exc:  # noqa: BLE001 — must report, never raise during abort
        log(f"WARNING: could not stop load: {exc} — power the switch off")


def main() -> int:
    global _log_fh
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--abort-temp", type=int, default=85,
                    help="meter value that stops the load (no datasheet limit in hand; see issue #13)")
    ap.add_argument("--duration", type=float, default=600, help="max seconds of load")
    ap.add_argument("--interval", type=float, default=5, help="seconds between meter reads")
    ap.add_argument("--no-load", action="store_true", help="log only, no stress")
    args = ap.parse_args()

    LOG.parent.mkdir(parents=True, exist_ok=True)
    _log_fh = LOG.open("a")
    out = Path("private/thermal") / f"{time.strftime('%Y%m%d-%H%M%S')}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)

    enable_meter(args.host)
    time.sleep(1)  # first samples after enable are unsettled; see issue #13
    t, raw = read_temp(args.host)
    ncpu = int(ssh(args.host, "grep -c ^processor /proc/cpuinfo"))
    log(f"host={args.host} cpus={ncpu} start meter={t} raw=0x{raw:08x} abort>={args.abort_temp} "
        f"duration={args.duration}s interval={args.interval}s csv={out}")

    if not args.no_load:
        ssh(args.host, " ".join(["(yes > /dev/null &);"] * ncpu))
        log(f"load started: {ncpu}x yes")

    t0 = time.monotonic()
    reason = "duration elapsed"
    peak = t
    with out.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["elapsed_s", "meter", "raw", "load1"])
        try:
            while time.monotonic() - t0 < args.duration:
                t, raw = read_temp(args.host)
                load1 = ssh(args.host, "cut -d' ' -f1 /proc/loadavg")
                el = time.monotonic() - t0
                peak = max(peak, t)
                w.writerow([f"{el:.1f}", t, f"0x{raw:08x}", load1])
                fh.flush()
                log(f"t={el:6.1f}s meter={t} load1={load1}")
                if t >= args.abort_temp:
                    reason = f"ABORT: meter {t} >= {args.abort_temp}"
                    break
                time.sleep(args.interval)  # paced poll, not a wait-for-condition
        except KeyboardInterrupt:
            reason = "interrupted"
        except Exception as exc:  # noqa: BLE001
            reason = f"ABORT: {exc}"
        finally:
            if not args.no_load:
                stop_load(args.host)
    log(f"done: {reason}; peak meter={peak}; elapsed={time.monotonic() - t0:.0f}s")
    return 0 if reason == "duration elapsed" else 1


if __name__ == "__main__":
    sys.exit(main())
