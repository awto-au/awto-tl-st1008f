#!/usr/bin/env python3
"""Decompile the CPU-NIC / CPU-port code of vendor RTL9303 firmware (Ghidra headless).

- Targets: TL-ST5008F v2 1.2.0 userspace `core` (user-mode SDK NIC driver + TP-Link CPU-port code),
  its rtcore.ko / ethdriver.ko / mgntPort.ko. Stock ST1008F rtcore/rtnic are already in private/ghidra.
- Output: private/ghidra/vendor-nic/<name>.c (vendor code, never published). Log: tmp/logs/vendor_nic_decompile.log.
- Usage: ./scripts/vendor_nic_decompile.py [name ...]   (default: all targets)
- `addr <hex> ...`: decompile `core` functions at addresses (unnamed FUN_ callees) -> st5008f-core-addr.c.
- `str <needle> ...`: decompile `core` functions referencing strings containing a needle -> st5008f-core-str.c.
- `ref <symbol|0xaddr> ...`: decompile `core` functions referencing a global -> st5008f-core-ref.c.
- `name <regex>`: decompile `core` functions whose name matches -> st5008f-core-name.c.
- These four keep the analysed project proj-st5008f-core for repeat runs.
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
# board pass (#79): TP-Link board XML drivers (SFP, TX-disable, LEDs, temp, watchdog, GPIO, flash/upgrade)
# + the SDK init that consumes board values (SerDes TX/RX params, LED config, hwp, flow control)
BOARD_RE = ("(?!cparser).*(adBoard|adBorad|adSfp|adDDM|adPortSfp|adPortStateSet|adPortFlowCtrl|adMmuFlowCtrl"
            "|adChipSdk|drvchipSdk|drvChipSdk|drvPhyPort|drvPortInitRealtek|drvPortSetPhyFlowCtrl"
            "|subDrvPortFlowctrlInit|drvPortSfp|drvSfp|drvPortLed|drvMgntPortLed|drvPortSpdDpx|drvQosSetPortCpuInit"
            "|drvRxQueueInit|drvTpstkRpcServerPort|drv_watchdog|drv_gpio|drv_generalCtrlGPIO|drv_i2c_dev_init"
            "|dal_longan_sds_(txParam|rxCaliConf|10gEyeParam|eyeParam_set|init)|dal_longan_led|rtl9300_led_config"
            "|dal_longan_switch_(thermal|watchdog)|dal_longan_flowctrl_init|_hwp_led_parse|hwp_init"
            "|Wtd|Watchdog|Thermal|Temperature|SysMac|sysMac|BaseMac|flashUidGet|UpgradeState|DualFlash).*")

# name ->(binary, ghidra script + args, timeout s)
# timeouts: unmeasured on this host; 19 MB -O0 MIPS `core` est. <=40 min analysis -> 50 min (1.25x);
# kernel modules analyse in <1 min -> 5 min bound. On expiry: logged, target marked failed.
TARGETS = {
    "st5008f-core": (X / "rootfs/usrImage/app/sbin/core", ["DecompileMatching.java", None, NIC_RE], 3000),
    "st5008f-core-extra": (X / "rootfs/usrImage/app/sbin/core", ["DecompileMatching.java", None, EXTRA_RE], 3000),
    "st5008f-board": (X / "rootfs/usrImage/app/sbin/core", ["DecompileMatching.java", None, BOARD_RE], 3000),
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


def run_addr(mode, addrs, fh):
    """Decompile `core` by address or string needle; project analysed once, then reused (-process)."""
    core = X / "rootfs/usrImage/app/sbin/core"
    out_c = OUT / f"st5008f-core-{mode}.c"
    script = {"addr": "TraceLoader.java", "str": "DecompileStringUsers.java",
              "name": "DecompileMatching.java", "ref": "DecompileRefsTo.java"}[mode]
    proj = "proj-st5008f-core"
    src = (["-process", core.name, "-noanalysis"] if (OUT / f"{proj}.gpr").exists()
           else ["-import", str(core)])
    cmd = ["nice", "-n", "19", "analyzeHeadless", str(OUT), proj, *src, "-scriptPath", str(SCRIPTS),
           "-postScript", script, str(out_c), *addrs]
    # bound: first run = full `core` analysis -> same 3000 s limit as the core targets above (expiry logged)
    log(f"{mode}: {len(addrs)} args, limit 3000 s", fh)
    t0 = time.monotonic()
    try:
        r = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=3000)
    except subprocess.TimeoutExpired:
        log(f"{mode}: TIMEOUT after {time.monotonic() - t0:.0f} s (limit 3000 s)", fh)
        return False
    log(f"{mode}: rc={r.returncode} {time.monotonic() - t0:.0f} s -> {out_c}", fh)
    return r.returncode == 0


def main():
    if sys.argv[1:2] in (["addr"], ["str"], ["name"], ["ref"]):
        OUT.mkdir(parents=True, exist_ok=True)
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            return 0 if run_addr(sys.argv[1], sys.argv[2:], fh) else 1
    names = sys.argv[1:] or list(TARGETS)
    OUT.mkdir(parents=True, exist_ok=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        results = {n: run(n, fh) for n in names}
        log(f"summary: {results}", fh)
    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
