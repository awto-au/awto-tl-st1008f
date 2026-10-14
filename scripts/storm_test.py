#!/usr/bin/env python3
"""storm_test — #111 steps L2-L6 on sw2 (docs/STORM-PROTECTION-OPS.md).

- L2-L5: mainline initramfs shell (`./dev.py ramload mainline-kernel`). L6: OpenWrt 6.18 + 300-26
  (`./dev.py ramload openwrt-ours-6.18`). sw2 only: board_guard via dev.py.
- Test bridge `br-t` = one looped cage pair, default lan7 + lan8 (fibre). The 3 <-> 4 DAC does not
  link under the mainline kernel yet (#112 fix is OpenWrt-tree only): `--pair 3 4` to try it.
  The mgmt cage (lan1) is never in br-t, so a loop cannot reach the house LAN. Torn down after each step.
- L2 STP on: one port blocks, no `loop:` shut. L3 STP off: `loop:` shut <= 2 s. L4 (after L3):
  back up at +60 s and shut again. L5 `loop off` + one broadcast: meters cap it (`storm_s`
  rising, `storm:` line), then `loop on` shuts it <= 2 s. L6: the pair in OpenWrt's `switch` bridge
  with STP off: `loop:` shut <= 2 s; lan1 (uplink) is taken out of `switch` first and put back after.
- Log: tmp/logs/storm_test.log; results go in docs/STORM-PROTECTION.md.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/storm_test.log"
PROMPT = r"st1008f-linux # "
OW_PROMPT = r"root@[^:\s]*:[^#\n]*# "
BR = "br-t"
DBG = "/sys/kernel/debug/rtl838x/storm"
SHUT_S = 2      # loop period 1 s (300-26): probe out + back + shut = 1 period; x2 (one period may be missed)
RECOVER_S = 60  # loop_recover_s default (300-26)
LINK_S = 4      # link up after `ip link set up`: SerDes config + RX calibration ~1 s per port (dmesg); x2
A = B = ""      # the pair, set in main()


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(con: Console, cmd: str, cap: float = 3) -> str:
    """One shell command; its output. Local commands answer < 0.5 s; `cap` covers board-side sleeps."""
    _, out = con.run(cmd, PROMPT, cap, cmd[:40])
    return out


def state_cmd() -> str:
    return (f"grep -E '^(loop|{A}|{B})' {DBG}; for p in {A} {B}; do "
            f"echo \"$p stp $(cat /sys/class/net/{BR}/brif/$p/state 2>/dev/null) oper $(cat /sys/class/net/$p/operstate)\"; done")


def bridge_up(con: Console, stp: int) -> None:
    sh(con, "ip link del br-t 2>/dev/null; ip link add br-t type bridge")
    sh(con, f"echo {stp} > /sys/class/net/br-t/bridge/stp_state; echo 200 > /sys/class/net/br-t/bridge/forward_delay")
    sh(con, f"ip link set {A} master br-t; ip link set {B} master br-t")
    sh(con, f"ip link set {A} up; ip link set {B} up; ip link set br-t up")
    # both links up before any timing; polled on the board once a second (BusyBox: no sub-second sleep)
    out = sh(con, f"i=0; while [ $i -lt {LINK_S} ]; do [ $(cat /sys/class/net/{A}/operstate) = up ] && "
                  f"[ $(cat /sys/class/net/{B}/operstate) = up ] && break; sleep 1; i=$((i+1)); done; "
                  f"echo LINKS $(cat /sys/class/net/{A}/operstate) $(cat /sys/class/net/{B}/operstate)", LINK_S + 2)
    m = re.search(r"LINKS (\S+) (\S+)", out)
    log(f"  links {A} {m[1] if m else '?'}, {B} {m[2] if m else '?'}")


def teardown(con: Console) -> None:
    sh(con, f"echo 'loop on' > {DBG}; echo unshut > {DBG}")
    sh(con, f"ip link set br-t down; ip link set {A} nomaster; ip link set {B} nomaster; ip link del br-t")
    sh(con, f"ip link set {A} down; ip link set {B} down")


def dmesg_lines(con: Console) -> int:
    return int(re.search(r"\n(\d+)\s*\r?\n", sh(con, "dmesg | wc -l"))[1])


def dmesg_since(con: Console, n: int) -> str:
    out = sh(con, f"dmesg | tail -n +{n + 1} | grep -E 'loop:|storm:'")
    return "\n".join(ln for ln in out.splitlines() if re.search(r"^\[ *\d", ln))


def l2(con: Console) -> bool:
    n = dmesg_lines(con)
    bridge_up(con, 1)
    # STP: listening 2 s + learning 2 s; the blocking decision comes first; 6 s = 4 s x 1.5
    st = sh(con, "sleep 6; " + state_cmd(), 6 + 3)
    ev = dmesg_since(con, n)
    log(f"L2 state:\n{st}\nL2 dmesg: {ev or '(none)'}")
    ok = re.search(r" stp 4 ", st) is not None and "loop:" not in ev and "SHUT" not in st
    teardown(con)
    return ok


def l3(con: Console, keep: bool = False) -> bool:
    n = dmesg_lines(con)
    bridge_up(con, 0)
    st = sh(con, f"sleep {SHUT_S + 1}; " + state_cmd(), SHUT_S + 4)
    ev = dmesg_since(con, n)
    log(f"L3 state:\n{st}\nL3 dmesg: {ev or '(none)'}")
    ok = "shut down" in ev and "SHUT" in st
    if not keep:
        teardown(con)
    return ok


def l4(con: Console) -> bool:
    if not l3(con, keep=True):
        log("L4: L3 did not shut; skipped")
        teardown(con)
        return False
    n = dmesg_lines(con)
    st = sh(con, f"sleep {RECOVER_S + SHUT_S + 2}; " + state_cmd(), RECOVER_S + SHUT_S + 5)
    ev = dmesg_since(con, n)
    log(f"L4 state:\n{st}\nL4 dmesg: {ev or '(none)'}")
    ok = "back up" in ev and "shut down" in ev and re.search(r"loops [2-9]", st) is not None
    teardown(con)
    return ok


def l5(con: Console) -> bool:
    n = dmesg_lines(con)
    sh(con, f"echo 'loop off' > {DBG}")
    bridge_up(con, 0)
    sh(con, "ip addr add 10.99.0.1/24 dev br-t")
    # one broadcast seeds the loop; the meters must cap it; 5 s of storm, then read
    st = sh(con, f"ping -b -c 1 -W 1 10.99.0.255 >/dev/null 2>&1; sleep 5; {state_cmd()}; cat /proc/loadavg", 5 + 4)
    ev = dmesg_since(con, n)
    log(f"L5 storm state:\n{st}\nL5 dmesg: {ev or '(none)'}")
    capped = re.search(r"(broadcast|multicast|unknown-unicast) \d+/\d+ storm_s [1-9]", st) is not None and "storm:" in ev
    n2 = dmesg_lines(con)
    st2 = sh(con, f"echo 'loop on' > {DBG}; sleep {SHUT_S + 1}; " + state_cmd(), SHUT_S + 4)
    ev2 = dmesg_since(con, n2)
    log(f"L5 after loop on:\n{st2}\nL5 dmesg: {ev2 or '(none)'}")
    shut = "shut down" in ev2
    teardown(con)
    return capped and shut


def l6(con: Console) -> bool:
    """OpenWrt `switch` bridge, STP off, pair added: loop detect must shut one port; lan1 isolated.
    OpenWrt's BusyBox echo check breaks on long lines: short commands only."""
    sb = "/sys/class/net/switch/bridge"
    n = dmesg_lines(con)
    sh(con, "ip link set lan1 nomaster")  # uplink out first: the loop can never reach sw1 / the house LAN
    try:
        sh(con, f"echo 0 > {sb}/stp_state")
        sh(con, f"ip link set {A} master switch")
        sh(con, f"ip link set {B} master switch")
        sh(con, f"ip link set {A} up; ip link set {B} up")
        sh(con, f"sleep {LINK_S + SHUT_S}", LINK_S + SHUT_S + 2)
        sh(con, f"D={DBG}")
        st = sh(con, f"grep -E '^(loop|{A}|{B})' $D") + sh(con, "cat /proc/loadavg")
        ev = dmesg_since(con, n)
        log(f"L6 state:\n{st}\nL6 dmesg: {ev or '(none)'}")
        return "shut down" in ev and "SHUT" in st
    finally:
        sh(con, f"ip link set {A} nomaster; ip link set {B} nomaster")
        sh(con, f"ip link set {A} down; ip link set {B} down")
        sh(con, f"echo 1 > {sb}/stp_state")
        sh(con, "ip link set lan1 master switch")
        sh(con, f"echo unshut > {DBG}")

def main() -> int:
    global A, B
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("steps", nargs="*", default=["l2", "l3", "l4", "l5"], choices=["l2", "l3", "l4", "l5", "l6"])
    ap.add_argument("--pair", nargs=2, type=int, default=[7, 8], metavar="CAGE")
    a = ap.parse_args()
    A, B = f"lan{a.pair[0]}", f"lan{a.pair[1]}"
    con = Console()
    global PROMPT
    if a.steps == ["l6"]:
        PROMPT = OW_PROMPT
    elif "l6" in a.steps:
        raise SystemExit("l6 runs alone (OpenWrt shell); l2-l5 need the mainline initramfs shell")
    sh(con, "dmesg -n 1")
    res = {}
    for s in a.steps:
        log(f"=== {s.upper()} ({A} + {B})")
        res[s] = {"l2": l2, "l3": l3, "l4": l4, "l5": l5, "l6": l6}[s](con)
        log(f"{s.upper()} {'PASS' if res[s] else 'FAIL'}")
    log("result: " + " ".join(f"{k.upper()} {'PASS' if v else 'FAIL'}" for k, v in res.items()))
    return 0 if all(res.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
