#!/usr/bin/env python3
"""dac_rxcal_test — TFTP frame loss over the 10G DAC (sw2 cage 1 <-> sw1 lan4) in our U-Boot, RX calibration off vs on (#114).

- RAM-boots the current tmp/tftp/uboot-mainline.bin (`ramload uboot-mainline`), then per mode (env rtk_rxcal=0 / 1):
  ROUNDS x (`rtk network off`, `rtk network on quick`, one TFTP of IMAGE with tftptimeout 500).
- Loss = `T` marks in the TFTP progress line (one per timed-out block) / blocks of 1468 B. Log: tmp/logs/dac_rxcal_test.log.
- Caps: TFTP = 5 s first-block retransmit + 1.25x size at 1.2 MB/s + 3 s + 1.5 % loss x 0.5 s per block x 1.25 (as uboot_netboot.py).
- No flash writes. sw2 only.

Usage: python3 scripts/dac_rxcal_test.py [--rounds 3] [--image mainline-7.4-rc3-clean3.bin] [--no-boot]
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import st1008_ramload as rl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/dac_rxcal_test.log"
PROMPT = r"st1008f-mainline # "
BLOCK = 1468
TMO_MS = 500
LOAD = 0x82000000


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def one_tftp(con: rl.Console, image: str) -> tuple[int, float, str]:
    size = (rl.TFTP_ROOT / image).stat().st_size
    cap = 5 + size / 1.2e6 * 1.25 + 3 + size / BLOCK * 0.015 * TMO_MS / 1000 * 1.25
    srv = subprocess.Popen(["sudo", "-n", sys.executable, str(ROOT / "scripts/tftpd.py"), "--once"],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t0 = time.monotonic()
    try:
        _, out = con.run(f"setenv ipaddr {rl.SWITCH_IP}; setenv serverip {rl.SERVER_IP}; setenv tftptimeout {TMO_MS}; "
                         f"tftpboot 0x{LOAD:08x} {image}", r"Bytes transferred = (\d+) \(", cap, f"tftp {image}")
    finally:
        try:
            srv.wait(timeout=3)  # --once exits after the transfer
        except subprocess.TimeoutExpired:
            subprocess.run(["sudo", "-n", "kill", "-TERM", str(srv.pid)], check=False, timeout=5)
    el = time.monotonic() - t0
    seg = out.split("Loading: ", 1)[-1].split("done", 1)[0]
    return seg.count("T"), el, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--image", default="mainline-7.4-rc3-clean3.bin")
    ap.add_argument("--no-boot", action="store_true", help="already at our prompt")
    a = ap.parse_args()
    if not a.no_boot:
        rc = subprocess.run(["./dev.py", "ramload", "uboot-mainline"], cwd=ROOT).returncode
        if rc:
            log(f"FAIL ramload uboot-mainline rc {rc}")
            return rc
    rl.ensure_server_ip()
    con = rl.Console()
    blocks = (rl.TFTP_ROOT / a.image).stat().st_size // BLOCK + 1
    res: dict[int, list[int]] = {0: [], 1: []}
    for mode in (0, 1):
        con.run(f"setenv rtk_rxcal {mode}", re.escape(PROMPT), 2, f"rtk_rxcal={mode}")
        for r in range(1, a.rounds + 1):
            con.run("rtk network off", re.escape(PROMPT), 5, "network off")
            _, out = con.run("rtk network on quick", r"network on done \((\d+) ms\)", 10, "network on quick")
            cal = re.findall(r"rtk: sds \d+ rx cal [^\n]*", out)
            lost, el, _ = one_tftp(con, a.image)
            res[mode].append(lost)
            log(f"rxcal={mode} round {r}: {lost} timeouts / {blocks} blocks ({100 * lost / blocks:.2f} %), {el:.1f} s; {cal}")
    for mode, v in res.items():
        log(f"rxcal={mode}: timeouts per run {v}, total {sum(v)} / {blocks * len(v)} blocks ({100 * sum(v) / (blocks * len(v)):.2f} %)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
