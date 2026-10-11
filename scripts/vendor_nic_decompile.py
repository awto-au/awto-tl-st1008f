#!/usr/bin/env python3
"""Decompile the CPU-NIC / CPU-port code of vendor RTL9303 firmware (Ghidra headless).

- Targets: TL-ST5008F v2 1.2.0 userspace `core` (user-mode SDK NIC driver + TP-Link CPU-port code),
  its rtcore.ko / ethdriver.ko / mgntPort.ko. Stock ST1008F rtcore/rtnic are already in private/ghidra.
- Output: private/ghidra/vendor-nic/<name>.c (vendor code, never published). Log: tmp/logs/vendor_nic_decompile.log.
- Usage: ./scripts/vendor_nic_decompile.py [name ...]   (default: all targets)
"""
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/vendor_nic_decompile.log"
OUT = ROOT / "private/ghidra/vendor-nic"
SCRIPTS = ROOT / "scripts/ghidra"
X = ROOT / "private/china/st5008f-v2-extracted"
KO = X / "initramfs/lib/modules"

NIC_RE = ("(?i).*(nic|cpuport|cpu_port|cputag|rxthread|pktctl|pkt_rx|pktrx|tpeth|tp_eth|ethdrv|ethdriver"
          "|rsn2cpu|cpuqid|cpuque|cpuQ|trap|rxring|txring|ring|intr|isr|irq|affinity|napi|rtcoreu|rtk_uk|ccm"
          "|egressrate|ingressrate|ratelimit|bandwidth|macforce|forcemode|jumbo|maxlen).*")
# second pass: CPU-port speed table, CPU-code (trap) rate limits, RX threads and their priority
EXTRA_RE = "(?i).*(transspeed|speed|cpucode|reason2cpu|rtnic|thread|nice|sched|rxcb|pktrecv|recvpkt|dispatch).*"

# name ->(binary, ghidra script + args, timeout s)
# timeouts: unmeasured on this host; 19 MB -O0 MIPS `core` est. <=40 min analysis -> 50 min (1.25x);
# kernel modules analyse in <1 min -> 5 min bound. On expiry: logged, target marked failed.
TARGETS = {
    "st5008f-core": (X / "rootfs/usrImage/app/sbin/core", ["DecompileMatching.java", None, NIC_RE], 3000),
    "st5008f-core-extra": (X / "rootfs/usrImage/app/sbin/core", ["DecompileMatching.java", None, EXTRA_RE], 3000),
    "st5008f-rtcore":(KO / "3.18.24/kernel/drivers/net/switch/rtcore/rtcore.ko", ["DecompileAll.java", None], 300),
    "st5008f-ethdriver": (KO / "ethdriver.ko", ["DecompileAll.java", None], 300),
    "st5008f-mgntport": (KO / "3.18.24/kernel/drivers/netfilter/mgntPort.ko", ["DecompileAll.java", None], 300),
}


def log(msg, fh):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    fh.write(line + "\n")
    fh.flush()


def run(name, fh):
    binary, script, tmo = TARGETS[name]
    out_c = OUT / f"{name}.c"
    args = [str(out_c) if a is None else a for a in script[1:]]
    cmd = ["nice", "-n", "19", "analyzeHeadless", str(OUT), f"proj-{name}", "-import", str(binary),
           "-overwrite", "-scriptPath", str(SCRIPTS), "-postScript", script[0], *args, "-deleteProject"]
    log(f"{name}: start {binary.name} ({binary.stat().st_size} B), limit {tmo} s", fh)
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=tmo)
    except subprocess.TimeoutExpired:
        log(f"{name}: TIMEOUT after {time.monotonic() - t0:.0f} s (limit {tmo} s)", fh)
        return False
    ok = r.returncode == 0 and out_c.exists()
    log(f"{name}: rc={r.returncode} {time.monotonic() - t0:.0f} s -> {out_c if ok else 'FAILED'}", fh)
    return ok


def main():
    names = sys.argv[1:] or list(TARGETS)
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        results = {n: run(n, fh) for n in names}
        log(f"summary: {results}", fh)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
