#!/usr/bin/env python3
"""gdma_probe — read-only dump of the RTL9303 GDMA / bus-traffic-generator blocks on a running sw2 (#62, #148).

- Instances (phys = 0x18000000 + SoC offset): LX1 0x1800a000, LX2 0x18018000, LX0 0x18144000.
- Offsets: CTRL 0x00, IM 0x04, IS 0x08, ICVL 0x0c, ICVR 0x10 (old layout), SBP/SBL 0x20-0x5c, DBP/DBL 0x60-0x9c,
  BTG write block 0x100.., read block 0x200.. (SDK register_map.h:2630-2718, rtl9300_soc_reg.h:3165-3481).
- One ssh per instance: a bus hang shows as the ssh timing out, naming the instance (board needs the relay then).
- `--write-test`: per word write 0xa5a5a5a5 and 0x5a5a5a5a, read back, restore 0 (never CTRL bit 31 = enable: CTRL is
  tested with 0x0fffffff only). Shows which words are real flops and which bits stick.
- `gdma_probe.py [--ip A.B.C.D] [--only lx1|lx2|lx0] [--write-test]`  Log tmp/logs/gdma_probe.log
"""
import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/gdma_probe.log"
INST = {"lx1": 0x1800A000, "lx2": 0x18018000, "lx0": 0x18144000}
RANGES = [(0x00, 0x14), (0x20, 0xA0), (0x100, 0x140), (0x200, 0x240)]
SSH = ["-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null"]


def log(msg):
    print(msg, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("--only", choices=list(INST))
    ap.add_argument("--write-test", action="store_true")
    a = ap.parse_args()
    for name, base in INST.items():
        if a.only and a.only != name:
            continue
        if a.write_test:
            offs = [o for lo, hi in RANGES for o in range(lo, hi, 4)]
            lines = []
            for i in range(0, len(offs), 10):  # dropbear rejects very long command lines: 10 words per ssh
                cmd = "; ".join(
                    f"A=0x{base + o:08x}; "
                    + ("devmem $A 32 0x0fffffff; x=$(devmem $A 32); devmem $A 32 0; echo " + f"{name}+0x{o:03x} one=$x"
                       if o == 0 else
                       "devmem $A 32 0xa5a5a5a5; x=$(devmem $A 32); devmem $A 32 0x5a5a5a5a; y=$(devmem $A 32); devmem $A 32 0; "
                       + f"echo {name}+0x{o:03x} a5=$x 5a=$y")
                    for o in offs[i:i + 10])
                try:
                    r = subprocess.run(["ssh", *SSH, f"root@{a.ip}", cmd], capture_output=True, text=True,
                                       timeout=15)  # 10 words x 4-5 mapped accesses, ms each; a hang never returns
                except subprocess.TimeoutExpired:
                    log(f"{name}: write test ssh timed out after 15 s = BUS HANG; relay power-cycle needed")
                    return 1
                lines += [ln for ln in r.stdout.splitlines() if ln.startswith(name)]
                if r.stderr.strip() and "Warning" not in r.stderr:
                    log(f"  stderr: {r.stderr.strip()[:300]}")
            for ln in lines:
                if "a5=0x00000000 5a=0x00000000" not in ln:
                    log("  " + ln)
            log(f"{name} write test done ({len(lines)} words)")
            continue
        cmd = "; ".join(f"echo {name}+0x{o:03x} $(devmem 0x{base + o:08x} 32)"
                        for lo, hi in RANGES for o in range(lo, hi, 4))
        try:
            r = subprocess.run(["ssh", *SSH, f"root@{a.ip}", cmd], capture_output=True, text=True,
                               timeout=20)  # ~60 mapped reads, ms each; a bus hang never returns
        except subprocess.TimeoutExpired:
            log(f"{name} 0x{base:08x}: ssh timed out after 20 s = BUS HANG on a read; stopping (relay power-cycle needed)")
            return 1
        words = [ln.split() for ln in r.stdout.splitlines() if ln.startswith(name)]
        nz = [(w[0], w[1]) for w in words if len(w) > 1 and w[1] not in ("0x00000000",)]
        log(f"{name} 0x{base:08x}: {len(words)} words read, {len(nz)} non-zero: " + " ".join(f"{k}={v}" for k, v in nz))
        if r.stderr.strip() and "Warning" not in r.stderr:
            log(f"  stderr: {r.stderr.strip()[:200]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
