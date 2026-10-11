#!/usr/bin/env python3
"""mode_switch_map — map the M1/M2/M3 switch to GPIO 17/18/19 and check the boot policy (#8, #46).

- `live`: at our `st1008f-mainline #` prompt (after `./dev.py ramload uboot-mainline`). Prints
  "OWNER: slide the switch to Mx", polls `rtk mode` until the pins change and hold, records them.
  Order M1 (current) -> M2 -> M3 -> M1. PASS = 3 distinct patterns, decode == label, ends at M1.
- `boot --expect Mx`: owner sets the switch first. Power-cycle with the saved chain (`run bootcmd`
  policy): M1 must autoboot flash OpenWrt (STP set); M2/M3 must stop at our prompt with boot_mode=Mx.
- Read-only: GPIO DATA reads only; no flash writes. Log: tmp/logs/mode_switch_map.log.
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, Console, openwrt_stp, power, restart_daemon  # noqa: E402
from uboot_chain_env import set_policy  # noqa: E402

LOG = ROOT / "tmp/logs/mode_switch_map.log"
PROMPT = r"\r?\nst1008f-mainline # "
MODE_RX = (r"mode: pins 17/18/19 = ([01])/([01])/([01]) -> pattern \d[^\n]*\n"
           r"boot policy: (invalid -> )?M([123])")
# owner reads the request relayed through chat, walks to the switch: 180 s names "nobody came"
OWNER_WAIT_S = 180
POLL_S = 0.5    # `rtk mode` = 2 x 30 ms settle + ~150 B at 115200: well under 0.5 s
STABLE_N = 3    # same pins on 3 polls (1.5 s) = slide finished, not mid-travel


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def read_mode(con: Console) -> tuple[str, int]:
    """(pins '17/18/19', boot-policy mode; 0 = invalid)."""
    m, _ = con.run("rtk mode", MODE_RX + r"[^\n]*" + PROMPT, 1, "rtk mode")
    return "/".join(m.group(1, 2, 3)), 0 if m.group(4) else int(m.group(5))


def wait_change(con: Console, prev: str | None, label: str) -> tuple[str, int]:
    log(f"OWNER: slide the mode switch to {label} (waiting up to {OWNER_WAIT_S} s)")
    t0, seen, run = time.monotonic(), None, 0
    while time.monotonic() - t0 < OWNER_WAIT_S:
        pins, mode = read_mode(con)
        run = run + 1 if pins == seen else 1
        seen = pins
        if pins != prev and run >= STABLE_N:
            log(f"  {label}: pins 17/18/19 = {pins} -> boot policy {f'M{mode}' if mode else 'invalid'}")
            return pins, mode
        time.sleep(POLL_S)
    raise SystemExit(f"TIMEOUT {OWNER_WAIT_S}s: switch not moved to {label} (pins still {seen})")


def live() -> int:
    con = Console()
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "our U-Boot prompt")
    pins, mode = read_mode(con)
    log(f"start: pins 17/18/19 = {pins} -> M{mode}; assumed to be M1 (owner confirms)")
    got = {"M1": (pins, mode)}
    got["M2"] = wait_change(con, pins, "M2")
    got["M3"] = wait_change(con, got["M2"][0], "M3")
    back = wait_change(con, got["M3"][0], "M1 (back to normal: flash autoboot needs M1)")
    onehot = [got[k][0][0] for k in ("M1", "M2", "M3")] == ["0", "1", "1"]
    log(f"pin 17: {'one-hot (low at M1 only)' if onehot else 'NOT one-hot'} (#8 open question)")
    ok = (len({v[0] for v in got.values()}) == 3 and back[0] == got["M1"][0]
          and all(v[1] == int(k[1]) for k, v in got.items()))
    for k, (p, m) in got.items():
        log(f"  {k}: 17/18/19 = {p}, decode M{m}")
    log(f"{'PASS' if ok else 'FAIL'} live map: decode {'matches' if ok else 'does NOT match'} the labels")
    return 0 if ok else 1


def boot(expect: int) -> int:
    power("off")
    restart_daemon(policy="run bootcmd")
    time.sleep(2)  # relay off->on gap: rails discharge (same as ramload)
    con = Console()
    mark = con.size()
    power("on")
    try:
        # stock banner ~2 s after power-on; chain + our banner < 1 s more; x1.25 + relay latency
        con.expect(r"U-Boot 2026\.07", 6, mark, "stock -> saved bootcmd -> our U-Boot", boot_ok=True)
        m, _ = con.expect(r"Mode:  (M[123]|invalid)[^\n]*\n", 2, mark, "Mode line", boot_ok=True)
        log(f"  board: {m.group(0).strip()}")
        if expect == 1:
            con.expect(r"clocks: fast = cpu 1000 MHz", 4, mark, "M1 autoboot: clocks fast", boot_ok=True)
            # bootm from flash + kernel to console ~23 s after ours (uboot_chain_env); x1.25
            con.expect(r"Please press Enter to activate", 30, mark, "flash OpenWrt console", boot_ok=True)
            openwrt_stp(con)
        else:
            # M3 without a recovery image: `Boot:  prompt` (#73); with one it boots it (default-boot tests)
            con.expect(r"(needs Ethernet|Boot:  prompt)[^\n]*\n" + r"(?s:.*)" + PROMPT, 2, mark, f"M{expect}: prompt",
                       boot_ok=True)
            con.run("printenv boot_mode", rf"boot_mode=M{expect}\r?\n" + PROMPT, 1, "boot_mode")
    finally:
        set_policy("hold")
    log(f"PASS boot M{expect}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("live")
    b = sub.add_parser("boot")
    b.add_argument("--expect", required=True, choices=["M1", "M2", "M3"])
    a = ap.parse_args()
    return live() if a.cmd == "live" else boot(int(a.expect[1]))


if __name__ == "__main__":
    sys.exit(main())
