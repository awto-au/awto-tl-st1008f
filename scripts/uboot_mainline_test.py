#!/usr/bin/env python3
"""uboot_mainline_test — on-board checks for mainline U-Boot at the `st1008f-mainline #` prompt.

- Each check: send a command, expect a regex before the prompt returns, within a stated cap.
- `timer`: `sleep N; echo` timed host-side against the console log; must be within ±3 %.
- Read-only: no flash, env-save or GPIO21 commands. Add a check per new driver stage.
- Log: tmp/logs/uboot_mainline_test.log. Exit 0 = all pass.
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402  same socket/log console driver

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/uboot_mainline_test.log"
PROMPT = r"\r?\nst1008f-mainline # "

# name: (command, regex that must appear before the prompt, cap s). Caps: replies are a few
# hundred bytes at 115200 (~30 ms); 1 s names a hang without waiting long.
CHECKS = {
    "version": ("version", r"U-Boot 2026\.07", 1),
    "bdinfo": ("bdinfo", r"-> start\s*= 0x80000000\r?\n-> size\s*= 0x10000000", 1),  # 256 MiB @ KSEG0
    "dm": ("dm tree", r"root_driver.*\r?\n.*simple_bus.*\r?\n.*ns16550_serial", 1),
    "env": ("printenv baudrate", r"baudrate=115200", 1),
}
# mode switch via gpio-keys: all three probe (a state, not "not found"); M1 = pin 17 low = on
CHECKS["buttons"] = ("button M1; button M2; button M3",
                     r"button M3\r?\n(on|off)\r?\n(on|off)\r?\n(on|off)\r?\n", 1)
CHECKS["rtk_i2c"] = ("rtk i2c read 0 0", r"\r?\ndata 0x3\r?\n", 1)  # stock format; SFP id 0x03
CHECKS["rtk_pin"] = ("rtk pinGet 18", r"\r?\ndata 0x[01]\r?\n", 1)
# safety rails: module EEPROM write, GPIO21 low (board reset), all lasers on: all refused
CHECKS["refuse_eeprom"] = ("rtk i2c write 0 0 0", r"refused: module EEPROM", 1)
CHECKS["refuse_reset"] = ("rtk pinSet 21 0", r"refused: GPIO21 low", 1)
CHECKS["refuse_all"] = ("rtk laser all", r"refused: all lasers", 1)
GPIO_DAT = 0xB800330C  # gpio0 DATA (docs/hardware.md)
SFP_DUMPS = ROOT / "private/sfp"  # stock-loader A0 dumps (scripts/st1008_sfp_ddm.py)
# DDM sanity: SFF-8472 Vcc 3.3 V +-5 %; room-temp module 10-70 C; laser on = bias > 1 mA.
VCC_RANGE, TEMP_RANGE, BIAS_ON_MA = (3.135, 3.465), (10, 70), 1.0
TIMER_SECS = 5
TIMER_TOL = 0.03  # CP0 count rate guess (CPU/2 = 400 MHz): a wrong guess is off by ~2x, not 3 %


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def check(con: Console, name: str) -> bool:
    cmd, rx, cap = CHECKS[name]
    try:
        _, out = con.run(cmd, PROMPT, cap, name)
    except SystemExit as e:
        log(f"FAIL {name}: {e}")
        return False
    ok = re.search(rx, out) is not None
    log(f"{'PASS' if ok else 'FAIL'} {name}" + ("" if ok else f": /{rx}/ not in {out[-200:]!r}"))
    return ok


def gpio(con: Console) -> bool:
    """Driver vs raw register: every `gpio status -a` value must equal the DATA bit."""
    try:
        _, raw = con.run(f"md.l 0x{GPIO_DAT:08x} 1", PROMPT, 1, "raw gpio DATA")
        _, st = con.run("gpio status -a", PROMPT, 1, "gpio status")
    except SystemExit as e:
        log(f"FAIL gpio: {e}")
        return False
    word = int(re.search(rf"{GPIO_DAT:08x}: ([0-9a-f]{{8}})", raw).group(1), 16)
    lines = {int(n): int(v) for n, v in re.findall(r"gpio(\d+): \w+: ([01])", st)}
    bad = [n for n, v in lines.items() if v != (word >> n) & 1]
    ok = len(lines) == 24 and not bad
    log(f"{'PASS' if ok else 'FAIL'} gpio: {len(lines)} lines vs DATA 0x{word:08x}"
        + (f"; mismatch {bad}" if bad else "")
        + f"; mode pins 17/18/19 = {(word >> 17) & 1}/{(word >> 18) & 1}/{(word >> 19) & 1}")
    return ok


def sfp_a0(con: Console) -> bool:
    """Our I2C master vs the stock loader: first 96 A0 bytes must match the stock dump."""
    ok = True
    for dump in sorted(SFP_DUMPS.glob("*/cage*-a0.bin")):
        cage = int(re.search(r"cage(\d)", dump.name).group(1))
        try:
            _, out = con.run(f"i2c dev {cage - 1}; i2c md 0x50 0 0x60", PROMPT, 1, f"A0 cage {cage}")
        except SystemExit as e:
            log(f"FAIL sfp_a0 cage {cage}: {e}")
            return False
        got = bytes(int(h, 16) for row in re.findall(r"^[0-9a-f]{4}: ((?:[0-9a-f]{2} ){1,16})", out, re.M)
                    for h in row.split())
        same = got == dump.read_bytes()[:0x60]
        ok &= same
        log(f"{'PASS' if same else 'FAIL'} sfp_a0 cage {cage}: {len(got)} B vs stock {dump.parent.name}")
    return ok


def sfp_all(con: Console) -> bool:
    """Every cage: either an EEPROM with both checksums ok and MOD-DEF0 present, or no
    EEPROM and MOD-DEF0 absent. Anything else (bad checksum, presence mismatch) fails."""
    try:
        # 8 cages; worst case a slow module: 100 kHz fail + 20 ms + 50 kHz block (~25 ms) each
        _, out = con.run("rtk sfp", PROMPT, 3, "rtk sfp (all cages)")
    except SystemExit as e:
        log(f"FAIL sfp_all: {e}")
        return False
    blocks = re.split(r"\r?\ncage (?=\d:)", "\n" + out.split("rtk sfp", 1)[1])[1:]
    ok = len(blocks) == 8
    for b in blocks:
        cage = b[0]
        if "no EEPROM answer" in b:
            good = "absent" in b and "mismatch" not in b
            what = "empty"
        else:
            good = "CC_BASE ok, CC_EXT ok" in b and "mismatch" not in b
            what = re.search(r"pn\s+(\S+)", b).group(1) if re.search(r"pn\s+(\S+)", b) else "?"
        ok &= good
        log(f"  {'ok ' if good else 'BAD'} cage {cage}: {what}")
    log(f"{'PASS' if ok else 'FAIL'} sfp_all: {len(blocks)} cages")
    return ok


def ddm(con: Console, cage: int) -> dict | None:
    _, out = con.run(f"rtk sfp {cage}", PROMPT, 1, f"ddm cage {cage}")
    m = re.search(r"temp (-?[\d.]+) C, vcc ([\d.]+) V, bias ([\d.]+) mA, tx ([\d.]+) mW, rx ([\d.]+) mW", out)
    return dict(zip(("temp", "vcc", "bias", "tx", "rx"), map(float, m.groups()))) if m else None


def laser(con: Console) -> bool:
    """End to end: move the laser to cage 2, see the expander AND cage 2's bias current
    follow, then restore cage 1. One laser on at any time (cage loop, #19)."""
    try:
        con.run("rtk laser 2", PROMPT, 1, "laser -> cage 2")
        _, rb = con.run("rtk i2c read 8 1", PROMPT, 1, "expander readback")
        time.sleep(0.2)  # SFF-8431 TX_DISABLE deassert (t_on) max 2 ms; module DDM refresh ~100 ms
        d2 = ddm(con, 2)
        con.run("rtk laser 1", PROMPT, 1, "laser -> cage 1")
        time.sleep(0.2)
        d1, d2_off = ddm(con, 1), ddm(con, 2)
    except SystemExit as e:
        log(f"FAIL laser: {e}")
        return False
    ok = ("data 0xfd" in rb and d2 and d2["bias"] > BIAS_ON_MA and d1 and d1["bias"] > BIAS_ON_MA
          and d2_off and d2_off["bias"] < BIAS_ON_MA)
    log(f"{'PASS' if ok else 'FAIL'} laser: cage2 on bias {d2 and d2['bias']} mA, then cage1 "
        f"{d1 and d1['bias']} mA / cage2 {d2_off and d2_off['bias']} mA")
    return ok


def ddm_sane(con: Console) -> bool:
    try:
        d = ddm(con, 1)
    except SystemExit as e:
        log(f"FAIL ddm: {e}")
        return False
    ok = bool(d) and VCC_RANGE[0] <= d["vcc"] <= VCC_RANGE[1] and TEMP_RANGE[0] <= d["temp"] <= TEMP_RANGE[1]
    log(f"{'PASS' if ok else 'FAIL'} ddm cage 1: {d}")
    return ok


def reset(con: Console) -> bool:
    """`reset` must bring back the stock loader (caught by the daemon). Ends the session:
    not in the default list; run `./dev.py uboot-test reset` explicitly."""
    mark = con.size()
    con.send("reset")
    try:
        # stock banner ~2.5 s after a cold start; warm reset is faster. Cap 6 s.
        con.expect(r"\[daemon\] at RTL9300#", 6, mark, "stock prompt after reset", boot_ok=True)
    except SystemExit as e:
        log(f"FAIL reset: {e}")
        return False
    log("PASS reset: chip reset -> stock U-Boot caught")
    return True


def timer(con: Console) -> bool:
    mark = con.size()
    t0 = time.monotonic()
    con.send(f"sleep {TIMER_SECS}; echo TIMER_DONE")
    try:
        # cap: TIMER_SECS x2 covers a CP0 rate off by 2x (CPU vs CPU/2) and names it
        con.expect(r"\r?\nTIMER_DONE", TIMER_SECS * 2 + 1, mark, f"sleep {TIMER_SECS}")
    except SystemExit as e:
        log(f"FAIL timer: {e}")
        return False
    dt = time.monotonic() - t0
    err = dt / TIMER_SECS - 1
    ok = abs(err) <= TIMER_TOL
    log(f"{'PASS' if ok else 'FAIL'} timer: sleep {TIMER_SECS} took {dt:.3f}s host ({err:+.1%})")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("checks", nargs="*", default=[*CHECKS, "gpio", "sfp_a0", "sfp_all", "ddm", "laser", "timer"])
    a = ap.parse_args()
    con = Console()
    # presence probe: a command with a known reply (a bare CR once got no reply at all)
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "mainline prompt present")
    special = {"timer": timer, "gpio": gpio, "sfp_a0": sfp_a0, "sfp_all": sfp_all, "ddm": ddm_sane, "laser": laser,
               "reset": reset}
    results = {n: (special[n](con) if n in special else check(con, n)) for n in a.checks}
    bad = [n for n, ok in results.items() if not ok]
    log(f"=== {len(results) - len(bad)}/{len(results)} pass" + (f"; FAIL: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
