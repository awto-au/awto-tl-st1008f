#!/usr/bin/env python3
"""serial_speed_test — console UART baud ladder at the mainline U-Boot prompt (#32).

- UART clock: LX 175 MHz / 16 = 10.9375 MBd / divisor. Ladder = divisors 47 24 12 6 5 4 3 2 1.
- One self-restoring command line per step: `mw.b` the divisor (DLAB), sleep, `md.b` a RAM
  block, sleep, restore divisor 95 (115200). The board always comes back; no power cycle.
- Host follows via the daemon `baud` op. Pass = dump at rate == 115200 baseline, byte for byte.
- Log: tmp/logs/serial_speed_test.log. Exit 0 = every tested rate passed.
"""

import argparse
import json
import re
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import CONSOLE, SOCK, Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/serial_speed_test.log"
CAL = ROOT / "tmp/serial-cal.json"  # {divisor: host request that decodes}; written by the ladder
PROMPT = r"\r?\nst1008f-mainline # "
UART = 0xB8002000  # ns16550, one register per word, data in byte 0 (docs/UBOOT-MAINLINE.md)
LCR, DLL, DLM = UART + 0x0C, UART + 0x00, UART + 0x04
BASE_CLK = 175_000_000 // 16  # 10.9375 MBd at divisor 1
DIV_115200 = 95
LADDER = [47, 24, 12, 6, 5, 4, 3, 2, 1]
DUMP_ADDR, DUMP_LEN = 0x81000000, 0x4000  # our own image region; ~80 KB of md.b text
CHARS_PER_ROW = 79  # "81000000: " + 16x"xx " + 16 ascii + CRLF, approx
SETTLE_S = 1  # board sleeps after the switch: host daemon reopen is ~10-50 ms
HOLD_S = 2  # board sleeps before restoring 115200: host must revert inside this


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def host_baud(baud: int) -> None:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)  # local unix socket; 5 s names a dead daemon
    s.connect(str(SOCK))
    s.sendall((json.dumps({"op": "baud", "baud": baud}) + "\n").encode())
    s.recv(65536)
    s.close()


def parse_dump(text: str) -> bytes:
    rows = re.findall(r"^([0-9a-f]{8}): ((?:[0-9a-f]{2} ){16})", text, re.M)
    return bytes(int(h, 16) for _, row in rows for h in row.split())


def divisor_cmds(div: int) -> str:
    return (f"mw.b {LCR:x} 83; mw.b {DLL:x} {div & 0xff:x}; mw.b {DLM:x} {div >> 8:x}; "
            f"mw.b {LCR:x} 3")


# Clone PL2303HX runs faster than requested, more so at high rates (board 911k decodes at
# request 0.92x, 10.94M at 0.50x). Sweep request factors down from the last good one.
SWEEP_STEP, SWEEP_MIN = 0.04, 0.44
HOST_MAX = 6_000_000  # Linux pl2303.c clamps TYPE_HX requests here


def step(con: Console, div: int, base: bytes, host: int | None = None) -> dict:
    rate = BASE_CLK / div
    line = (f"{divisor_cmds(div)}; sleep {SETTLE_S}; echo SPD_GO; md.b {DUMP_ADDR:x} {DUMP_LEN:x}; "
            f"echo SPD_END; sleep {HOLD_S}; {divisor_cmds(DIV_115200)}; echo SPD_BACK")
    mark = con.send_checked(line)  # Enter only after an exact echo (#31 lost chars)
    host_baud(host or round(rate))
    t_go = None
    res = {"div": div, "rate": round(rate), "host": host or round(rate), "ok": False}
    chars = DUMP_LEN // 16 * CHARS_PER_ROW
    cap = SETTLE_S + chars * 10 / rate * 1.25 + 0.5  # settle + dump at line rate x1.25 + poll slack
    t0 = time.monotonic()
    out = ""
    while time.monotonic() - t0 < cap:
        with CONSOLE.open("rb") as fh:
            fh.seek(mark)
            out = fh.read().decode(errors="replace")
        if t_go is None and re.search(r"\nSPD_GO\r?\n", out):
            t_go = time.monotonic()
        if re.search(r"\nSPD_END\r?\n", out):
            break
        time.sleep(0.005)
    t_end = time.monotonic()
    host_baud(115200)
    seg = out.split("SPD_GO", 2)[-1] if "SPD_GO" in out else out
    got = parse_dump(seg)
    res["bytes"] = len(got)
    res["ok"] = got == base
    if t_go and "SPD_END" in out:
        res["cps"] = round(len(seg.split("SPD_END")[0]) / max(t_end - t_go, 1e-3))
    if not res["ok"]:
        bad = next((i for i, (a, b) in enumerate(zip(got, base)) if a != b), min(len(got), len(base)))
        res["first_bad"] = bad
    try:
        # board restores 115200 HOLD_S after SPD_END; +1 s
        con.expect(r"\nSPD_BACK\r?\n", HOLD_S + 1, mark, "back at 115200")
    except SystemExit:
        # SPD_END never seen at this rate: board is still dumping/holding; wait for the whole
        # line to finish (remaining dump at 115200-equivalent cannot exceed the baseline time)
        con.expect(r"\nSPD_BACK\r?\n", HOLD_S + chars * 10 / rate * 1.25 + 2, mark, "back (late)")
    return res


def go_fast(con: Console, div: int = 1) -> int:
    """`setenv baudrate` to BASE_CLK/div (an exact CFG_SYS_BAUDRATE_TABLE entry), then find the
    host request that sees the prompt: calibrated value first, then the sweep. Returns it."""
    rate = BASE_CLK // div  # truncated, as listed in the U-Boot table
    cal = json.loads(CAL.read_text()) if CAL.exists() else {}
    f0 = min(1.0, HOST_MAX / rate)
    tries = ([cal[str(div)]] if str(div) in cal else []) + \
        [round(rate * (f0 - SWEEP_STEP * i)) for i in range(int((f0 - SWEEP_MIN) / SWEEP_STEP) + 1)]
    mark = con.send_checked(f"setenv baudrate {rate}")
    con.expect(r"press ENTER", 1, mark, "baudrate switch prompt")  # printed at 115200 before switch
    for req in tries:
        host_baud(req)
        mark = con.size()
        con.send("", cr=True)  # U-Boot discards input until a CR decodes at the new rate
        try:
            # prompt line at >=1 MBd arrives in <1 ms; 0.3 s = poll slack, names a wrong request
            con.expect(PROMPT, 0.3, mark, f"prompt at {rate} (host {req})")
            con.send_checked("echo FAST_OK")
            con.expect(r"\nFAST_OK\r?\n", 0.3, con.size() - 40, "typed command at speed")
            log(f"console at {rate:,} Bd (host request {req:,})")
            return req
        except SystemExit:
            continue
    raise SystemExit(f"FAIL: no host request decodes {rate} Bd; board needs a power cycle")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("divisors", nargs="*", type=int, default=LADDER)
    a = ap.parse_args()
    con = Console()
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "mainline prompt present")
    chars = DUMP_LEN // 16 * CHARS_PER_ROW
    t0 = time.monotonic()
    _, out = con.run(f"md.b {DUMP_ADDR:x} {DUMP_LEN:x}", PROMPT, chars * 10 / 115200 * 1.25 + 1, "baseline")
    base = parse_dump(out)
    log(f"baseline 115200: {len(base)} B in {time.monotonic() - t0:.2f}s")
    if len(base) != DUMP_LEN:
        log(f"FAIL baseline: {len(base)} != {DUMP_LEN}")
        return 1
    results, last_f = [], 0.96
    for div in a.divisors:
        r = step(con, div, base)
        f = min(last_f, HOST_MAX / r["rate"])
        while not r["ok"] and f >= SWEEP_MIN:
            r = step(con, div, base, round(r["rate"] * f))
            if r["ok"]:
                last_f = f
            f = round(f - SWEEP_STEP, 3)
        results.append(r)
        log(f"{'PASS' if r['ok'] else 'FAIL'} div {div:3d} = {r['rate']:>9,d} Bd (host {r['host']:,}): {r['bytes']} B"
            + (f", {r['cps']:,} char/s" if "cps" in r else "")
            + (f", first bad byte {r['first_bad']:#x}" if "first_bad" in r else ""))
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "prompt after ladder")
    for r in results:
        if r["ok"] and r["host"] != r["rate"]:
            log(f"  div {r['div']}: board {r['rate']:,} decoded with host request {r['host']:,}")
    cal = json.loads(CAL.read_text()) if CAL.exists() else {}
    cal.update({str(r["div"]): r["host"] for r in results if r["ok"]})
    CAL.write_text(json.dumps(cal, indent=1))
    good = [r["rate"] for r in results if r["ok"]]
    log(f"=== {len(good)}/{len(results)} rates pass; fastest {max(good) if good else '-'} Bd")
    return 0 if len(good) == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
