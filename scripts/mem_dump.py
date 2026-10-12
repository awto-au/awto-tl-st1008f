#!/usr/bin/env python3
"""mem_dump — copy the bench unit's on-chip SRAM and the RAM-resident stock U-Boot to the host over Ethernet.

- `ramload uboot-mainline --stock-clocks` (stock prompt, stock `rtk network on`, TFTP ours, go): no `clocks`
  command runs, so SRAM still holds what stock's preloader/U-Boot left (ours only uses SRAM for clock changes).
- At our prompt: `tftpput` each region to the host TFTP server (tmp/tftp/), then move to private/mem-dump-<ts>/
  with sha256. Read-only on the board. Log: tmp/logs/mem_dump.log
"""

import argparse
import hashlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import ROOT, SERVER_IP, TFTP_ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/mem_dump.log"
PROMPT = r"st1008f-mainline # "
# (name, KSEG0 address, bytes): SRAM = 64 KiB SP-SRAM (DS §1); stock U-Boot text linked at 0x83f00000,
# loader image 0xe0000 B incl. SPL, so 1 MiB covers text+data+bss (docs/UBOOT-REFERENCE.md)
REGIONS = [("sram", 0x9F000000, 0x10000), ("stock-uboot-ram", 0x83F00000, 0x100000)]
# 1 MiB over 10G TFTP measured ~0.1 s; host disk + U-Boot lock-step ~1 MiB/s worst case; 1 MiB x5 -> 5 s
PUT_S = 5


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-boot", action="store_true", help="already at our U-Boot prompt (booted with --stock-clocks)")
    a = ap.parse_args()
    if not a.no_boot:
        r = subprocess.run([sys.executable, str(ROOT / "dev.py"), "ramload", "uboot-mainline", "--stock-clocks"])
        if r.returncode:
            log("FAIL: ramload uboot-mainline --stock-clocks")
            return 1
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = ROOT / "private" / f"mem-dump-{stamp}"
    out.mkdir(parents=True)
    con = Console()
    con.run(f"setenv serverip {SERVER_IP}; setenv tftpdstp", PROMPT, 1, "serverip")
    for name, addr, size in REGIONS:
        fname = f"memdump-{stamp}-{name}.bin"
        srv = subprocess.Popen(["sudo", "-n", sys.executable, str(ROOT / "scripts/tftpd.py"), "--once"],
                               cwd=ROOT)  # one-shot receiver on :69, as ramload's RRQ path (firewall allows it)
        con.run(f"tftpput {addr:x} {size:x} {fname}", r"Bytes transferred = \d+[\s\S]*" + PROMPT, PUT_S, f"tftpput {name}")
        try:
            srv.wait(timeout=PUT_S)  # receiver exits right after the last block
        except subprocess.TimeoutExpired:
            subprocess.run(["sudo", "-n", "pkill", "-f", "scripts/tftpd.py"], check=False)
        src = TFTP_ROOT / fname
        if not src.exists() or src.stat().st_size != size:
            log(f"FAIL {name}: {src.name} missing or wrong size ({src.stat().st_size if src.exists() else 0} != {size})")
            return 1
        dst = out / f"{name}-{addr:08x}.bin"
        shutil.move(src, dst)
        log(f"{name} 0x{addr:08x} +0x{size:x}: {dst.relative_to(ROOT)} sha256 {hashlib.sha256(dst.read_bytes()).hexdigest()}")
    log(f"DONE: {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
