#!/usr/bin/env python3
"""gdma_test — build kmod/gdma_test against the 7.3 build tree, load it on sw2, print the GDMA result (#62, #151).

- Needs: tmp/openwrt-build 7.3 tree built (`./dev.py build-openwrt --kernel mainline`), sw2 on that image (ramload).
- The module runs one GDMA transfer at init and refuses to stay loaded (insmod fails by design); result is in dmesg.
- `gdma_test.py [--func 0] [--len 4096] [--burst 1] [--iters 1] [--base 0x1800a000] [--no-build]`  Log tmp/logs/gdma_test.log
"""
import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/gdma_test.log"
KDIR = ROOT / "tmp/openwrt-build/build_dir/target-mips_24kc_musl/linux-realtek_rtl930x/linux-7.3-next-20261009"
TC = ROOT / "tmp/openwrt-build/staging_dir/toolchain-mips_24kc_gcc-14.4.0_musl/bin"
MOD = ROOT / "kmod/gdma_test"
SSH = ["-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("--func", type=int, default=0)
    ap.add_argument("--len", type=int, default=4096)
    ap.add_argument("--burst", type=int, default=1)
    ap.add_argument("--iters", type=int, default=1)
    ap.add_argument("--base", default="0x1800a000")
    ap.add_argument("--no-build", action="store_true")
    a = ap.parse_args()
    if not a.no_build:
        env = {"PATH": f"{TC}:/usr/bin:/bin", "STAGING_DIR": str(ROOT / "tmp/openwrt-build/staging_dir")}
        r = subprocess.run(["make", "-C", str(KDIR), f"M={MOD}", "ARCH=mips", "CROSS_COMPILE=mips-openwrt-linux-musl-", "modules"],
                           capture_output=True, text=True, env=env, timeout=300)  # one-file module: ~10 s
        if r.returncode:
            log("build failed: " + r.stdout[-600:] + r.stderr[-600:])
            return 1
    r = subprocess.run(["scp", "-O", *SSH, str(MOD / "gdma_test.ko"), f"root@{a.ip}:/tmp/"], capture_output=True, text=True, timeout=30)
    if r.returncode:
        log("scp failed: " + r.stderr.strip())
        return 1
    cmd = (f"dmesg -c >/dev/null; insmod /tmp/gdma_test.ko base={a.base} func={a.func} len={a.len} burst={a.burst} "
           f"iters={a.iters} 2>&1 | tail -n 2; dmesg | grep gdma_test")
    try:
        r = subprocess.run(["ssh", *SSH, f"root@{a.ip}", cmd], capture_output=True, text=True,
                           timeout=30)  # transfer bound 2 ms x iters in-kernel; 30 s names a hung ssh/bus
    except subprocess.TimeoutExpired:
        log("ssh timed out: GDMA transfer may have hung the bus (relay power-cycle)")
        return 2
    log(f"func {a.func} len {a.len} burst {a.burst} iters {a.iters}: " + (r.stdout + r.stderr).replace("\n", " | ")[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
