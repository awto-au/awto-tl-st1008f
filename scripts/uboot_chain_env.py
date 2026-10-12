#!/usr/bin/env python3
"""uboot_chain_env — stock U-Boot env for chainloading our U-Boot from flash jffs2-log (#47 A).

- test:   power cycle -> stock prompt -> set the chain vars WITHOUT saving -> `run bootcmd` -> our banner,
          autoboot, flash OpenWrt. Nothing written.
- test-bad: as test, but one RAM word of the copy is changed before the check -> `cmp.l` fails ->
          `run` stops before `go` -> stock `boota` boots flash OpenWrt (#105). Nothing written.
- apply:  stock prompt: chain vars in RAM, check the jffs2-log slot with them (refuse unless it
          verifies; --allow-fallback = save anyway, boots stock `boota` until uboot-chain-install),
          then saveenv; printenv check.
- revert: stock prompt: setenv bootcmd boota; clear the chain vars; saveenv.
- prompt: power cycle with the saved chain, ESC in our 2 s window -> our prompt (#46).
- set-mac [MAC]: stock prompt: setenv ethaddr; saveenv; verify (#91). Default: random locally
  administered unicast; refuses the Realtek placeholder and sw1's MAC.
- boot:   power cycle with the daemon policy `run bootcmd` (= the saved autoboot) and follow it to
          flash OpenWrt; daemon back to `hold` after.
- Chain (#105): ub_ld copies the 512 KiB slot from flash 0x200000 (cached window 0x94200000) to
  0x81000000; ub_ck = slot CRC32 check (scripts/uboot_chain_image.py); ub_go = marker 0xa5a51008 @
  0xa0f80000 (ours autoboots on it) + go. bootcmd = `run ub_ld ub_ck ub_go; run bootcmd_stock`:
  stock (no hush) `run` stops at the first failing var, `;` goes on to boota.
- Log: tmp/logs/uboot_chain_env.log
"""

import argparse
import random
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_guard  # noqa: E402
from boards import SW1_MAC  # noqa: E402
from st1008_ramload import OW_READY, ROOT, SOCK, Console, openwrt_stp, power, restart_daemon  # noqa: E402
from uboot_chain_image import LOAD, SLOT, stock_check_cmd  # noqa: E402

LOG = ROOT / "tmp/logs/uboot_chain_env.log"
VARS = {  # saved in this order; bootcmd last
    "bootcmd_stock": "boota",
    "ub_ld": f"cp.b 0x94200000 0x{LOAD:08x} 0x{SLOT:x}",
    "ub_ck": stock_check_cmd(),
    "ub_go": f"mw.l 0xa0f80000 0xa5a51008; go 0x{LOAD:08x}",
    "bootcmd": "run ub_ld ub_ck ub_go; run bootcmd_stock",
}
CHECK_OK = r"Total of 1 word"   # stock cmp.l: equal
CHECK_BAD = r"word at 0x"        # stock cmp.l: differ
STOCK = r"\r?\nRTL9300# "
OURS_PROMPT = r"\r?\nst1008f-mainline # "
ESC_WINDOW = r"Autoboot in \d s, ESC for the prompt"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def to_stock() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "stock", "--no-network"],
                       timeout=30)  # relay + daemon restart + banner ~6 s; 30 s names a hang
    if r.returncode:
        raise SystemExit(f"FAIL: no stock prompt (rc {r.returncode})")


def set_policy(policy: str) -> None:
    import json
    import socket
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)  # local unix socket; 5 s names a dead daemon
    s.connect(str(SOCK))
    s.sendall((json.dumps({"op": "policy", "policy": policy}) + "\n").encode())
    s.recv(65536)
    s.close()


def set_vars(con) -> None:
    """Chain vars into the stock RAM env (not saved). <= 14 words each (stock MAXARGS 16)."""
    for k, v in VARS.items():
        con.run(f"setenv {k} '{v}'" if ";" in v else f"setenv {k} {v}", STOCK, 1, f"setenv {k}")


def slot_check(con) -> bool:
    """Copy + CRC-check the jffs2-log slot with the stock commands, as the saved bootcmd does."""
    # 512 KiB copy from the cached flash window + crc32 at stock clocks: well under 0.2 s; cap 2 s
    _, out = con.run("run ub_ld ub_ck", rf"({CHECK_OK}|{CHECK_BAD})[\s\S]*?{STOCK}", 2, "slot check")
    ok = re.search(CHECK_OK, out) is not None
    log(f"slot check (stock crc32 + cmp.l): {'OK' if ok else 'MISMATCH'}")
    return ok


def boot() -> int:
    power("off")
    restart_daemon(policy="run bootcmd")
    time.sleep(2)  # relay off->on gap: rails discharge (same as ramload)
    con = Console()
    mark = con.size()
    power("on")
    try:
        # stock banner ~2 s after power-on; chain + our banner < 1 s more; x1.25 + relay latency
        con.expect(r"U-Boot 2026\.07", 6, mark, "stock -> saved bootcmd -> our U-Boot", boot_ok=True)
        m, _ = con.expect(r"bootsel: M\d: [^\n]*", 4, mark, "our autoboot: clock policy (#46)", boot_ok=True)
        log(f"  {m.group(0).strip()}")
        # 2 s ESC window + bootm from flash + kernel to console ~24 s after ours (measured 24 s with a
        # 1 s window); x1.25
        con.expect(OW_READY, 31, mark, "flash OpenWrt console", boot_ok=True)
        openwrt_stp(con)
    finally:
        set_policy("hold")
    log("PASS boot: power-on -> stock -> saved chain -> ours -> flash OpenWrt, STP on")
    return 0


def prompt() -> int:
    """Power cycle with the saved chain; ESC in our 2 s window (#46) -> our prompt."""
    power("off")
    restart_daemon(policy="pass")
    time.sleep(2)  # relay off->on gap: rails discharge (same as ramload)
    con = Console()
    mark = con.size()
    power("on")
    # stock banner ~2.5 s after power-on + 1 s stock window + chain < 1 s + our banner: ~5 s; x1.25 + relay
    con.expect(ESC_WINDOW, 8, mark, "our 2 s ESC window", boot_ok=True)
    con.send("\x1b", cr=False)
    con.expect(OURS_PROMPT, 3, mark, "our prompt after ESC", boot_ok=True)  # window 2 s; x1.25 + echo
    log("PASS prompt: ESC stopped our autoboot")
    return 0


PLACEHOLDER = "00:e0:4c:00:00:00"


def pick_mac(mac: str | None) -> str:
    if mac is None:
        b = [random.randrange(256) for _ in range(6)]
        b[0] = (b[0] & 0xFC) | 0x02  # unicast, locally administered
        mac = ":".join(f"{x:02x}" for x in b)
    mac = mac.lower()
    if not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac) or int(mac[:2], 16) & 1:
        raise SystemExit(f"FAIL set-mac: {mac!r} is not a unicast MAC")
    if mac in (PLACEHOLDER, SW1_MAC.lower()):
        raise SystemExit(f"FAIL set-mac: {mac} is the placeholder or sw1's MAC")
    return mac


def set_mac(con, mac: str) -> int:
    _, out = con.run(f"setenv ethaddr {mac}", STOCK, 1, "setenv ethaddr")
    if "overwrite" in out.lower():
        log(f"FAIL set-mac: stock U-Boot refuses: {out.strip()!r}")
        return 1
    con.run("saveenv", STOCK, 4, "saveenv")  # 64 KiB sector erase + write, W25Q256 max 2 s; x1.25 + output
    _, out = con.run("printenv ethaddr", STOCK, 1, "verify")
    ok = f"ethaddr={mac}" in out.lower()
    log(f"{'PASS' if ok else 'FAIL'} set-mac: {out.strip()!r}")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["test", "test-bad", "apply", "revert", "boot", "prompt", "set-mac"])
    ap.add_argument("--allow-fallback", action="store_true",
                    help="apply: save even if the slot does not verify (boots stock boota until reinstalled)")
    ap.add_argument("mac", nargs="?", help="set-mac: aa:bb:cc:dd:ee:ff (default: random, locally administered)")
    a = ap.parse_args()
    if a.mode == "boot":
        return boot()
    if a.mode == "prompt":
        return prompt()
    if a.mode == "set-mac":
        mac = pick_mac(a.mac)
        flash_guard.check_range(0xE0000, 0x20000, "uboot-chain-env set-mac")
        log(f"set-mac: {mac}")
        to_stock()
        return set_mac(Console(), mac)
    if a.mode in ("apply", "revert"):  # stock saveenv: env 0xE0000 + env2 0xF0000 (#81)
        flash_guard.check_range(0xE0000, 0x20000, f"uboot-chain-env {a.mode}")
    for v in VARS.values():
        flash_guard.check_cmd(v)
    to_stock()
    con = Console()
    if a.mode in ("test", "test-bad"):
        set_vars(con)
        mark = con.size()
        if a.mode == "test":
            # slot copy + CRC < 0.2 s; our banner < 1 s after go
            m, _ = con.run("run bootcmd", rf"U-Boot 2026\.07|{CHECK_BAD}", 3, "chain (not saved) -> check")
            fell_back = m.group(0) != "U-Boot 2026.07"
            what = ("slot check FAILED -> stock boota -> flash OpenWrt (install the slot first)" if fell_back
                    else "check OK -> ours -> flash OpenWrt")
        else:
            con.run("run ub_ld", STOCK, 2, "slot copy")
            con.run(f"mw.l 0x{LOAD + 0x100:08x} 0x5a5aa5a5", STOCK, 1, "corrupt one RAM word of the copy")
            con.run("run ub_ck ub_go; run bootcmd_stock", CHECK_BAD, 2, "check must fail")
            what = "check failed -> stock boota -> flash OpenWrt"
        # no keypress here (ESC stops ours). 2 s window + bootm from flash + kernel ~25 s; x1.25 + slack
        _, out = con.expect(OW_READY, 40, mark, what)
        if a.mode == "test-bad" and re.search(r"U-Boot 2026\.07", out):
            log("FAIL test-bad: our U-Boot ran from a corrupt copy (`run` did not stop on cmp.l)")
            return 1
        openwrt_stp(con)
        if a.mode == "test" and fell_back:
            log(f"FAIL test: {what} (nothing saved; the fallback itself worked)")
            return 1
        log(f"PASS {a.mode}: {what} (nothing saved)")
        return 0
    if a.mode == "apply":
        set_vars(con)
        if not slot_check(con) and not a.allow_fallback:
            log("FAIL apply: jffs2-log slot does not verify; nothing saved. Install first "
                "(./dev.py uboot-chain-install) or --allow-fallback (boots stock boota until then)")
            return 1
    else:
        con.run("setenv bootcmd boota", STOCK, 1, "stock bootcmd")
        for k in ("ub_ld", "ub_ck", "ub_go"):
            con.run(f"setenv {k}", STOCK, 1, f"clear {k}")
    # saveenv: one 64 KiB env sector erase + write (W25Q256 max 2 s erase) x1.25 + output
    con.run("saveenv", STOCK, 4, "saveenv")
    names = ["bootcmd"] + (list(VARS)[:-1] if a.mode == "apply" else [])
    _, out = con.run("printenv " + " ".join(names), STOCK, 1, "verify")
    want = VARS if a.mode == "apply" else {"bootcmd": "boota"}
    bad = [k for k, v in want.items() if f"{k}={v}" not in out]
    log(f"{'PASS' if not bad else 'FAIL'} {a.mode}: {'all vars as set' if not bad else 'differ: ' + ', '.join(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
