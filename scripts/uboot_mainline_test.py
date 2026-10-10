#!/usr/bin/env python3
"""uboot_mainline_test — on-board checks for mainline U-Boot at the `st1008f-mainline #` prompt.

- Each check: send a command, expect a regex before the prompt returns, within a stated cap.
- `timer`: `sleep N; echo` timed host-side against the console log; must be within ±3 %.
- Read-only: flash writes are refused by the driver (checked), no env-save or GPIO21 commands. Add a check per new driver stage.
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
    # 115200, or a CFG_SYS_BAUDRATE_TABLE rate after `ramload --fast`
    "env": ("printenv baudrate", r"baudrate=(115200|1822916|2187500|2734375|3645833|5468750|10937500)\r?\n", 1),
}
# mode switch via gpio-keys: all three probe (a state, not "not found"); M1 = pin 17 low = on
CHECKS["buttons"] = ("button M1; button M2; button M3",
                     r"button M3\r?\n(on|off)\r?\n(on|off)\r?\n(on|off)\r?\n", 1)
CHECKS["rtk_i2c"] = ("rtk i2c read 0 0", r"\r?\ndata 0x3\r?\n", 1)  # stock format; SFP id 0x03
CHECKS["rtk_pin"] = ("rtk pinGet 7", r"\r?\npin7:\t[01]\r?\n\r?\n", 1)  # stock format
# stock-named verbs (docs/RTK-COMMANDS.md); expected text = stock output
CHECKS["rtk_i2c_nodev"] = ("rtk i2c read 9 1", r"\r?\nFAIL \(61455\)\r?\n", 1)
CHECKS["rtk_unit"] = ("rtk unit get", r"\r?\nunit: 0\r?\n", 1)
CHECKS["rtk_boardmodel"] = ("rtk boardmodel", r"\r?\nBoard Model: RTL9303_8XGE\r?\n", 1)
CHECKS["rtk_boardid"] = ("rtk boardid", r"\r?\nBoard Model ID: <NULL>\r?\n", 1)
CHECKS["rtk_profiles"] = ("rtk show hw_profile_list",
                          r"(?s)Available profiles are:.*RTL9303_8XGE \(9300015\)", 1)
CHECKS["rtk_sdsreg"] = ("rtk sdsreg get 0 2 0x1f 2",
                        r"Get unit 0 sds 02 page 31 reg 02  val: 0x[0-9A-F]{4} \r?\n", 1)
CHECKS["rtk_ext"] = ("rtk ext-pinGet 3", r"The pinNum \(3\) is invalid\.", 1)  # no RTL8231
CHECKS["rtk_usage"] = ("rtk bogus", r"Usage:\r?\nrtk     - Realtek commands\r?\n", 1)
# new commands (no stock equivalent)
CHECKS["rtk_mode"] = ("rtk mode", r"mode: pins 17/18/19 = [01]/[01]/[01] -> pattern [123] \(M[123]", 1)
CHECKS["rtk_temp"] = ("rtk temp", r"temp: \d+ C \(since enable: min \d+, max \d+\)", 1)
CHECKS["rtk_port"] = ("rtk port", r"(?s)cage 1 \(port 0, sds 2\): .*cage 8 \(port 27, sds 9\): ", 3)
CHECKS["refuse_boardid"] = ("rtk boardid 5", r"refused: stock does setenv", 1)
CHECKS["refuse_boardmodel"] = ("rtk boardmodel X", r"refused: stock does setenv", 1)
CHECKS["rtk_help"] = ("help rtk", r"--- TL-ST1008F additions.*\r?\nrtk laser", 1)
CHECKS["highmem_info"] = ("highmem info", r"-> 512 MiB \(high bank 256 MiB at bus 0x20000000\)", 1)
# zone-3 remap + TLB window + alias check + 2-pass pattern over 256 MiB; 14.3 s measured x1.25
CHECKS["highmem"] = ("highmem test", r"alias check: ok\r?\n\.+\r?\npattern test 256 MiB: 0 errors", 18)
CHECKS["rtk_nophy"] = ("rtk phyreg get 0 0 0 0", r"val: 0x0000 \r?\nnote: no PHY on TL-ST1008F", 1)
CHECKS["rtk_phymmd_short"] = ("rtk phymmd set 0 0 4 0xc441", r"phymmd parameter error", 1)  # was argv[7] NULL
# safety rails: module EEPROM write, GPIO21 low (board reset), all lasers on: all refused
CHECKS["refuse_eeprom"] = ("rtk i2c write 0 0 0", r"refused: module EEPROM", 1)
CHECKS["refuse_reset"] = ("rtk pinSet 21 0", r"refused: GPIO21 low", 1)
CHECKS["refuse_all"] = ("rtk laser all", r"refused: all lasers", 1)
# SPI-NOR (stage 3, #32). Caps: bytes x 8 / assumed 1 MHz floor SPI clock x 1.25 (driver RDY limit
# basis; divider not decoded): 64 KiB -> 0.66 s, plus console echo ~30 ms; cap 2 s.
SF_RAM, SF_RAM2, SF_LEN, SF_LAST = 0x86000000, 0x86100000, 0x10000, 0x1FF0000  # SF_LAST = bank 1 (>16 MiB)
SF_CAP_S = 2
CHECKS["sf_probe"] = ("sf probe 0", r"SF: Detected w25q256 with page size 256 Bytes, erase size 4 KiB, total 32 MiB", 1)
CHECKS["refuse_sf_write"] = (f"sf probe 0; mw.b 0x{SF_RAM2:x} 0x5a 0x100; sf write 0x{SF_RAM2:x} 0x1ff0000 0x100",
                             r"refused: no flash writes", 1)
CHECKS["refuse_sf_erase"] = ("sf erase 0x1ff0000 0x1000", r"refused: no flash writes", 1)
CHECKS["refuse_sf_update"] = (f"sf update 0x{SF_RAM2:x} 0x1ff0000 0x100", r"refused: no flash writes", 1)
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
    _, out = con.run(f"rtk sfp {cage} brief", PROMPT, 1, f"ddm cage {cage}")
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


def crc(con: Console, cmd: str, label: str, cap: int) -> int | None:
    _, out = con.run(cmd, PROMPT, cap, label)
    m = re.search(r"==> ([0-9a-f]{8})", out)
    return int(m.group(1), 16) if m else None


def sf_read(con: Console) -> bool:
    """`sf read` (offset 0 = LOADER, and SF_LAST = second 16 MiB bank) vs the same bytes via the
    memory-mapped window; the window must still work after `sf` use (driver restores SFCR/SFCSR)."""
    ok = True
    try:
        con.run("sf probe 0", PROMPT, 1, "sf probe")
        con.run("md.l 0xb8001200 4", PROMPT, 1, "SFCR before")  # logged in the console log for the divider
        for off in (0, SF_LAST):
            con.run(f"mw.l 0x{SF_RAM:x} 0 0x{SF_LEN // 4:x}", PROMPT, 1, "clear RAM")
            con.run(f"sf read 0x{SF_RAM:x} 0x{off:x} 0x{SF_LEN:x}", PROMPT, SF_CAP_S, f"sf read @0x{off:x}")
            a = crc(con, f"crc32 0x{SF_RAM:x} 0x{SF_LEN:x}", "crc RAM", 1)
            b = crc(con, f"crc32 0x{0xB4000000 + off:x} 0x{SF_LEN:x}", "crc mmio", SF_CAP_S)
            good = a is not None and a == b
            ok &= good
            log(f"{'PASS' if good else 'FAIL'} sf_read @0x{off:x}: sf read crc {a and f'{a:08x}'} vs mmio {b and f'{b:08x}'}")
        con.run("md.l 0xb8001200 4", PROMPT, 1, "SFCR after")
    except SystemExit as e:
        log(f"FAIL sf_read: {e}")
        return False
    return ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("checks", nargs="*", default=[*CHECKS, "gpio", "sfp_a0", "sfp_all", "ddm", "laser", "sf_read", "timer"])
    a = ap.parse_args()
    con = Console()
    # presence probe: a command with a known reply (a bare CR once got no reply at all)
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "mainline prompt present")
    special = {"timer": timer, "gpio": gpio, "sfp_a0": sfp_a0, "sfp_all": sfp_all, "ddm": ddm_sane, "laser": laser,
               "sf_read": sf_read, "reset": reset}
    results = {n: (special[n](con) if n in special else check(con, n)) for n in a.checks}
    bad = [n for n, ok in results.items() if not ok]
    log(f"=== {len(results) - len(bad)}/{len(results)} pass" + (f"; FAIL: {', '.join(bad)}" if bad else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
