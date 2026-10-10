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
GPIO_DAT = 0xB800330C  # gpio0 DATA (docs/hardware.md)
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
    ap.add_argument("checks", nargs="*", default=[*CHECKS, "gpio", "timer"])
    a = ap.parse_args()
    con = Console()
    # presence probe: a command with a known reply (a bare CR once got no reply at all)
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "mainline prompt present")
    special = {"timer": timer, "gpio": gpio}
    results = {n: (special[n](con) if n in special else check(con, n)) for n in a.checks}
    bad = [n for n, ok in results.items() if not ok]
    log(f"=== {len(results) - len(bad)}/{len(results)} pass" + (f"; FAIL: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
