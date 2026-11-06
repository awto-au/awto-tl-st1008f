#!/usr/bin/env python3
"""cpuport_regs — read-only dump of the RTL9303 CPU-port (port 28) registers from a running sw2 (#148).

- Physical address = 0x1b000000 + switch register offset (devmem takes physical addresses; 0xbb00xxxx is the KSEG1 alias).
- Offsets/names: svanheule.net longan map, docs/CPU-PORT.md. Reads only, never writes.
- `cpuport_regs.py [--ip A.B.C.D]`  -> table on stdout + tmp/logs/cpuport_regs.log
"""
import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/cpuport_regs.log"
BASE = 0x1B000000

# (name, offset, count, stride)
REGS = [
    ("MAC_FORCE_MODE_CTRL(28)", 0xCA1C + 28 * 4, 1, 4),
    ("MAC_L2_CPU_PORT_CTRL", 0xC70C, 1, 4),
    ("MAC_L2_PORT_MAX_LEN_CTRL(28)", 0x326C + (28 << 6), 1, 4),
    ("MAC_L2_CPU_MAX_LEN_CTRL", 0xA3A0, 1, 4),
    ("EGBW_PORT_CTRL(28)", 0x7820, 1, 4),
    ("IGBW_PORT_CTRL(28)", 0x80D8, 1, 4),
    ("EGBW_CTRL", 0x78E4, 1, 4),
    ("EGBW_CPU_PPS_LB_CTRL", 0x78E8, 1, 4),
    ("EGBW_CPU_Q_MAX_LB_CTRL[0..3]", 0x7CB8, 4, 4),
    ("SCHED_CPU_Q_CTRL[0..3]", 0x7F44, 4, 4),
    ("QM_CPUQID2QID_CTRL[0..3]", 0xA324, 4, 4),
    ("QM_CPUQID2XGQID_CTRL[0..3]", 0xA334, 4, 4),
    ("FC_CPU_Q_EGR_FORCE_DROP_CTRL[0..3]", 0xC4DC, 4, 4),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.25.56")
    a = ap.parse_args()
    cmds = []
    for name, off, n, st in REGS:
        for i in range(n):
            cmds.append(f"echo '{name.split('[')[0]}{'[%d]' % i if n > 1 else ''}' 0x{off + i * st:04X} $(devmem 0x{BASE + off + i * st:08X} 32)")
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                        f"root@{a.ip}", "; ".join(cmds)], capture_output=True, text=True,
                       timeout=60)  # ~35 devmem reads of mapped registers, ms each
    out = r.stdout + (("\n[stderr] " + r.stderr) if r.stderr.strip() else "")
    print(out)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a.ip}\n{out}\n")


if __name__ == "__main__":
    main()
