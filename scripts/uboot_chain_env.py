#!/usr/bin/env python3
"""uboot_chain_env — stock U-Boot env for chainloading our U-Boot from flash jffs2-log (#47 A).

- test:   power cycle -> stock prompt -> type the chain command WITHOUT saving -> expect our banner,
          autoboot, flash OpenWrt. Nothing written.
- apply:  stock prompt: setenv bootcmd_stock boota; setenv bootcmd <chain>; saveenv; printenv check.
- revert: stock prompt: setenv bootcmd boota; saveenv.
- boot:   power cycle with the daemon policy `run bootcmd` (= the saved autoboot) and follow it to
          flash OpenWrt; daemon back to `hold` after.
- Chain: marker 0xa5a51008 @ 0xa0f80000 (ours autoboots on it), copy 512 KiB from flash 0x200000
  (cached window 0x94200000) to 0x81000000, go. Log: tmp/logs/uboot_chain_env.log
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, SOCK, Console, openwrt_stp, power, restart_daemon  # noqa: E402

LOG = ROOT / "tmp/logs/uboot_chain_env.log"
CHAIN = "mw.l 0xa0f80000 0xa5a51008; cp.b 0x94200000 0x81000000 0x80000; go 0x81000000"
STOCK = r"\r?\nRTL9300# "


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
        con.expect(r"clocks: fast = cpu 1000 MHz", 4, mark, "our autoboot: clocks fast", boot_ok=True)
        # bootm from flash + kernel to console ~23 s after ours (measured 24 s incl. bootdelay); x1.25
        con.expect(r"Please press Enter to activate", 30, mark, "flash OpenWrt console", boot_ok=True)
        openwrt_stp(con)
    finally:
        set_policy("hold")
    log("PASS boot: power-on -> stock -> saved chain -> ours (1 GHz) -> flash OpenWrt, STP on")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["test", "apply", "revert", "boot"])
    a = ap.parse_args()
    if a.mode == "boot":
        return boot()
    to_stock()
    con = Console()
    if a.mode == "test":
        # cp 512 KiB from flash at stock SPI (~5 MB/s cached) ~0.1 s; our banner < 1 s after go
        mark = con.size()
        con.run(CHAIN, r"U-Boot 2026\.07", 3, "chain -> our U-Boot")
        # no keypress here: any byte stops our autoboot. 1 s bootdelay + clocks fast + bootm from
        # flash + kernel to console ~25 s (measured); x1.25 + slack
        con.expect(r"Please press Enter to activate", 40, mark, "autoboot -> flash OpenWrt")
        openwrt_stp(con)
        log("PASS test: stock -> chain (not saved) -> ours -> flash OpenWrt")
        return 0
    if a.mode == "apply":
        con.run("setenv bootcmd_stock boota", STOCK, 1, "keep stock bootcmd")
        con.run(f"setenv bootcmd '{CHAIN}'", STOCK, 2, "set chain bootcmd")
    else:
        con.run("setenv bootcmd boota", STOCK, 1, "stock bootcmd")
    # saveenv: one 64 KiB env sector erase + write (W25Q256 max 2 s erase) x1.25 + output
    con.run("saveenv", STOCK, 4, "saveenv")
    _, out = con.run("printenv bootcmd bootcmd_stock", STOCK, 1, "verify")
    want = CHAIN if a.mode == "apply" else "boota"
    ok = f"bootcmd={want}" in out
    log(f"{'PASS' if ok else 'FAIL'} {a.mode}: bootcmd={want!r}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
