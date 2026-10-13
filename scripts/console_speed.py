#!/usr/bin/env python3
"""console_speed — switch the sw2 console UART (board + host) on demand, verify, revert on failure (#46).

- Detects the prompt (st1008_ramload.PROMPTS). Rate N (default 921600): board divisor = round(UART clock /
  16 / N); UART clock = LX (175 MHz stock, 306.25 MHz turbo: div 12 / 21 give the same 911458 Bd).
- Our U-Boot: `setenv baudrate N` (N in CFG_SYS_BAUDRATE_TABLE, e.g. 921600; host request from
  tmp/serial-cal.json for the divisor, then the exact rate). Linux/OpenWrt: `stty -F /dev/ttyS0 N` (8250 picks the divisor).
- Host request = calibrated value for that divisor; verify = `echo` round trip at speed. On failure: type
  the revert (`setenv baudrate 115200` / `stty ... 115200`) at each candidate host rate, host back to 115200.
- State: tmp/console-speed.json {"host": request, "rate": board rate}; restart_board reads it so a
  software reboot still reaches the prompt, then drops the host to 115200 before the stock banner.
- `console-speed 115200` goes back. Log: tmp/logs/console_speed.log
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import PROMPTS, ROOT, Console  # noqa: E402
from serial_speed_test import CAL, host_baud  # noqa: E402

LOG = ROOT / "tmp/logs/console_speed.log"
STATE = ROOT / "tmp/console-speed.json"
UART_175 = 175_000_000 // 16
VERIFY_S = 0.5  # echo round trip at >= 115200: ms; 0.5 s = poll slack, names a wrong host rate
PROBE_S = 1     # prompt redraw at the current rate: ms; 1 s names a dead or mismatched console


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {"host": 115200, "rate": 115200}


def save(host: int, rate: int) -> None:
    STATE.write_text(json.dumps({"host": host, "rate": rate}))


def prompt(con: Console) -> tuple[str, str] | None:
    """(prompt pattern, reboot cmd) of what answers a CR at the current host rate."""
    mark = con.size()
    con.send("", cr=True)
    t0 = time.monotonic()
    while time.monotonic() - t0 < PROBE_S:
        tail = con.echo_since(mark).rstrip("\r\n").split("\n")[-1].rstrip() + " "
        for pat, cmd in PROMPTS:
            if re.search(pat, tail):
                return pat, cmd
        time.sleep(0.05)  # log poll; a prompt line arrives in ms
    return None


def verify(con: Console) -> bool:
    mark = con.size()
    con.send("", cr=True)
    try:  # let the prompt line land first: it would otherwise mix into the echo check
        con.expect(r"st1008f-\w+ # |RTL9300# |root@[^#\n]*# ", VERIFY_S, mark, "prompt at speed")
    except SystemExit:
        return False
    try:  # chunked typing with echo check (#31): a burst overruns the 1-byte UART FIFO at high rates
        mark = con.send_checked("echo SPEED_OK", chunk=4, tries=1)
        con.expect(r"\nSPEED_OK\r?\n", VERIFY_S, mark, "echo at speed")
        return True
    except SystemExit:
        return False


def candidates(div: int, rate: int) -> list[int]:
    cal = json.loads(CAL.read_text()) if CAL.exists() else {}
    # the PL2303 rounds a request to its own grid: calibrated value first, then +-6 % around the rate
    sweep = [round(rate * (1 + k / 100)) for k in (0, -2, 2, -4, 4, -6, 6)]
    return list(dict.fromkeys(([cal[str(div)]] if str(div) in cal else []) + sweep))


def set_rate(rate: int = 921600) -> bool:
    """Library entry for long-output flows (memtest, selftest): True = board + host at `rate`."""
    return switch(Console(), rate) == 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rate", nargs="?", type=int, default=921600)
    return switch(Console(), ap.parse_args().rate)


def switch(con: Console, rate: int) -> int:
    a = argparse.Namespace(rate=rate)
    st = state()
    host_baud(st["host"])
    p = prompt(con)
    if not p:
        log(f"FAIL: no prompt at host {st['host']} (state {st}); reboot the board (restart_board)")
        return 1
    pat, _ = p
    linux = "linux" in pat or "root@" in pat
    if not linux and "mainline" not in pat:
        log("FAIL: stock U-Boot console is not switched (its env/table differ); use our U-Boot or Linux")
        return 1
    div = max(1, round(UART_175 / a.rate))
    rate = 115200 if a.rate == 115200 else UART_175 // div
    if linux:
        cmd = f"stty -F /dev/ttyS0 {a.rate}"
        con.send_checked(cmd, chunk=4)
        time.sleep(0.2)  # command echo + execute at the old rate (~ms); output after it is at the new rate
        tries = [115200] if a.rate == 115200 else candidates(div, rate)
        for req in tries:
            host_baud(req)
            if verify(con):
                save(req, rate)
                log(f"Linux console at {a.rate} (board ~{rate} Bd, host request {req})")
                return 0
    else:
        # U-Boot accepts only CFG_SYS_BAUDRATE_TABLE rates (921600 or the exact divisor rates); the ns16550
        # driver rounds to its divisor, so the board runs UART clock / 16 / div
        tries = [115200] if a.rate == 115200 else candidates(div, rate)
        if a.rate == 115200 and st["host"] == 115200:
            return 0 if verify(con) else 1
        mark = con.send_checked(f"setenv baudrate {a.rate}", chunk=4)  # 1-byte FIFO at fast rates
        try:
            con.expect(r"press ENTER", 1, mark, "baudrate switch prompt")  # printed at the old rate
        except SystemExit as e:
            log(f"FAIL: U-Boot refused {a.rate}: {e}")
            return 1
        for req in tries:
            host_baud(req)
            con.send("", cr=True)  # U-Boot waits for a CR at the new rate
            if verify(con):
                save(req, rate)
                log(f"U-Boot console at {rate} Bd (host request {req})")
                return 0
    # revert: type the 115200 command at every candidate host rate, then check at 115200
    back = "stty -F /dev/ttyS0 115200" if linux else "setenv baudrate 115200"
    for req in tries:
        host_baud(req)
        con.send(back)
        con.send("", cr=True)
    host_baud(115200)
    con.send("", cr=True)
    ok = verify(con)
    save(115200, 115200) if ok else None
    log(f"FAIL at {a.rate}: reverted to 115200 {'OK' if ok else 'NOT confirmed (board needs a reboot)'}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
