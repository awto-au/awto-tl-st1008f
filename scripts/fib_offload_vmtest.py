#!/usr/bin/env python3
"""fib_offload library tests in a VM (#85): x86_64 kernel of the kernel_base tree, netdevsim
on the library (fib_offload_lib=1), kernel selftests under virtme-ng.

- config: virtme-configkernel --defconfig + FRAGMENT, O=tmp/build-x86-fol (tree stays clean).
- build:  bzImage (nice 19, -j8 max) + W=1 rebuild of the library and its netdevsim user.
- run [TEST ...]: `vng -r bzImage --exec` per test; default TESTS. Kernel log + test output
  -> tmp/logs/fib_offload_vmtest.log; one line per test (ok / FAIL) on stdout.
- all: config, build, run. `--no-apply`: keep the tree as is (default: apply our patch series).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import kernel_base  # noqa: E402

LOG = ROOT / "tmp/logs/fib_offload_vmtest.log"
OUT = ROOT / "tmp/build-x86-fol"
FRAG = ROOT / "tmp/fib_offload_x86.config"
FRAGMENT = """CONFIG_NETDEVSIM=y
CONFIG_FIB_OFFLOAD=y
CONFIG_IPV6=y
CONFIG_IP_MULTIPLE_TABLES=y
CONFIG_IPV6_MULTIPLE_TABLES=y
CONFIG_IPV6_SUBTREES=y
CONFIG_DUMMY=y
CONFIG_VETH=y
CONFIG_DEBUG_FS=y
CONFIG_NET_NS=y
CONFIG_PSAMPLE=y
CONFIG_PROVE_LOCKING=y
CONFIG_DEBUG_ATOMIC_SLEEP=y
CONFIG_DEBUG_LIST=y
CONFIG_DEBUG_OBJECTS=y
CONFIG_DEBUG_OBJECTS_WORK=y
"""
SELFTESTS = "tools/testing/selftests/drivers/net/netdevsim"
# fib.sh subset the library model covers: no devlink FIB resources, no delete veto, no nexthop objects
FIB_SH = ("ipv4_identical_routes ipv4_tos ipv4_metric ipv4_replace ipv4_delete ipv4_plen ipv4_replay "
          "ipv4_flush ipv6_add ipv6_metric ipv6_append_single ipv6_replace_single ipv6_metric_multipath "
          "ipv6_append_multipath ipv6_replace_multipath ipv6_append_multipath_to_single ipv6_delete_single "
          "ipv6_delete_multipath ipv6_replay_single ipv6_replay_multipath")
TESTS = {
    "fib_offload_lib": "./fib_offload_lib.sh",
    "fib_lib_mode": f"echo 1 > /sys/module/netdevsim/parameters/fib_offload_lib && ALL_TESTS='{FIB_SH}' ./fib.sh",
    "fib_notifications_lib_mode": "echo 1 > /sys/module/netdevsim/parameters/fib_offload_lib && ./fib_notifications.sh",
    "fib_legacy": "./fib.sh",  # netdevsim's own fib.c: the patch must not change it
}
# Measured run lengths (VM boot ~5 s + test): fib.sh legacy ~150 s, the others < 120 s; x1.25 of 480 s
RUN_TIMEOUT = 600
BUILD_TIMEOUT = 3600  # cold x86 defconfig build at -j8 ~25 min; x1.25 rounded up
NICE = ["nice", "-n", "19"]


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}"
    print(line, flush=True)
    with LOG.open("a") as f:
        f.write(line + "\n")


def run(cmd: list[str], cwd: Path, timeout: int) -> tuple[int, str]:
    log("$ " + " ".join(map(str, cmd)))
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        with LOG.open("a") as f:
            f.write(out)
        log(f"TIMEOUT after {time.monotonic() - t0:.0f} s (limit {timeout} s): {cmd[0]}")
        return 124, out
    with LOG.open("a") as f:
        f.write(r.stdout + r.stderr)
    log(f"exit {r.returncode} after {time.monotonic() - t0:.0f} s")
    return r.returncode, r.stdout + r.stderr


def config(tree: Path) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    FRAG.write_text(FRAGMENT)
    rc, _ = run(["virtme-configkernel", "--defconfig", "--custom", str(FRAG), f"O={OUT}"], tree, 300)
    if rc:
        return rc
    have = set((OUT / ".config").read_text().splitlines())
    missing = [ln for ln in FRAGMENT.splitlines() if ln not in have]
    if missing:
        log(f"config lost fragment lines: {missing}")
        return 1
    return 0


def build(tree: Path) -> int:
    base = [*NICE, "make", "-C", str(tree), f"O={OUT}", "-j8"]
    rc, _ = run([*base, "bzImage"], tree, BUILD_TIMEOUT)
    if rc:
        return rc
    objs = ["net/core/fib_offload.o", "drivers/net/netdevsim/fib_lib.o"]
    for o in objs:
        (OUT / o).unlink(missing_ok=True)
    rc, out = run([*base, "W=1", *objs], tree, 600)
    warn = [ln for ln in out.splitlines() if "warning:" in ln]
    log(f"W=1 {' '.join(objs)}: {len(warn)} warnings, rc {rc}")
    for ln in warn:
        log("  " + ln)
    return rc or (1 if warn else 0)


def run_tests(tree: Path, names: list[str]) -> int:
    img = OUT / "arch/x86/boot/bzImage"
    bad = 0
    for name in names or list(TESTS):
        cmd = TESTS.get(name, name)  # not a test name: a shell command (debugging)
        # boot messages cleared first: only what the test triggers counts
        sh = (f"dmesg -C; cd {tree / SELFTESTS} && {cmd}; echo VMTEST_RC=$?; "
              "dmesg | grep -iE -A30 'BUG|WARNING|lockdep|circular' || true")
        rc, out = run(["vng", "-r", str(img), "--user", "root", "--memory", "2G", "--cpus", "2",
                       "--exec", sh], tree, RUN_TIMEOUT)
        res = [ln for ln in out.splitlines() if ln.startswith(("TEST:", "VMTEST_RC=")) or "FAIL" in ln]
        ok = rc == 0 and "VMTEST_RC=0" in out and not any(k in out for k in ("BUG:", "WARNING:", "circular"))
        bad += not ok
        log(f"{name}: {'ok' if ok else 'FAIL'} ({sum('[ OK ]' in ln for ln in res)} OK, "
            f"{sum('[FAIL]' in ln for ln in res)} FAIL)")
        for ln in res:
            if "[FAIL]" in ln or "VMTEST_RC" in ln:
                log("  " + ln.strip())
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["config", "build", "run", "all"])
    ap.add_argument("tests", nargs="*", help=f"run: subset of {list(TESTS)}")
    ap.add_argument("--no-apply", action="store_true", help="tree as is, do not re-apply the series")
    a = ap.parse_args()
    os.nice(19)
    tree = kernel_base.checkout()
    log(f"kernel base {kernel_base.selected()}: {tree}")
    if a.step in ("config", "all") and not a.no_apply:
        rc, _ = run([sys.executable, str(ROOT / "scripts/mainline_build_check.py"), "--apply-only"], ROOT, 600)
        if rc:
            return rc
    if a.step in ("config", "all") and (rc := config(tree)):
        return rc
    if a.step in ("build", "all") and (rc := build(tree)):
        return rc
    if a.step in ("run", "all"):
        return run_tests(tree, a.tests)
    return 0


if __name__ == "__main__":
    sys.exit(main())
