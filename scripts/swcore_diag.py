#!/usr/bin/env python3
"""swcore_diag — read-only state dump of sw2 (NIC IRQ/DMA, PLL, CPU-port regs, link, temperature) for the switch-core clock study (#148).

- Reads only (devmem reads, /proc, debugfs). Registers: phys = 0x1b000000 + offset. Queue peak counters are clear-on-read.
- `swcore_diag.py --tag NAME [--ip A.B.C.D] [--peer]` -> stdout + tmp/logs/swcore_diag_NAME.log
- --peer also reads sw1 lan4 (ethtool, ip -s) READ-ONLY.
"""
import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SSH = ["ssh", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes"]
SSH_S = 40  # ~80 devmem forks + debugfs reads at 1 GHz: <5 s; 40 s names a dead link
BASE = 0x1B000000
REGS = [  # name, offset, count
    ("PLL_GLB_CTRL0 e200", 0xE200, 1), ("PLL_SW_CTRL0 e214", 0xE214, 1), ("PLL_SW_DIV e220", 0xE220, 1),
    ("PLL_CPU e208/e210", 0xE208, 1), ("PLL_CPU_MISC e210", 0xE210, 1),
    ("MAC_FORCE_MODE_CTRL(28) 0xCA8C", 0xCA8C, 1), ("MAC_L2_CPU_PORT_CTRL 0xC70C", 0xC70C, 1),
    ("MAC_FORCE_MODE_CTRL(0..3)", 0xCA1C, 4),
    ("FC_CPU_Q_THR[0..3] 0x7DC0", 0x7DC0, 4), ("QM_CPUQID2QID[0..3]", 0xA324, 4), ("QM_CPUQID2XGQID[0..3]", 0xA334, 4),
    ("DMA_IF_INTR_RX_RUNOUT_MSK", 0xE010, 1), ("DMA_IF_INTR_RX_DONE_MSK", 0xE014, 1), ("DMA_IF_INTR_TX_DONE_MSK", 0xE018, 1),
    ("DMA_IF_INTR_RX_RUNOUT_STS", 0xE01C, 1), ("DMA_IF_INTR_RX_DONE_STS", 0xE020, 1), ("DMA_IF_INTR_TX_DONE_STS", 0xE024, 1),
    ("DMA_IF_CTRL", 0xE028, 1), ("DMA_IF_PKT_CTRL 0xCE00", 0xCE00, 1),
    ("RX_BASE_DESC[0..7]", 0xDF00, 8), ("RX_CUR_DESC[0..7]", 0xDF80, 8), ("TX_BASE/CUR", 0xE000, 4),
    ("RX_RING_SIZE[0..2]", 0x7C60, 3), ("RX_RING_CNTR[0..2]", 0x7C8C, 3),
    ("CPU_Q_EGR_PAGE_CNT[0..3] (clr)", 0x7E40, 4), ("CPU_Q_EGR_PKT_CNT[0..3] (clr)", 0x7EC0, 4),
]


def ssh(ip, cmd):
    try:
        r = subprocess.run(SSH + [f"root@{ip}", cmd], capture_output=True, text=True, timeout=SSH_S)
    except subprocess.TimeoutExpired:
        return f"[ssh timeout {SSH_S}s]"
    return r.stdout + (f"[stderr] {r.stderr.strip()}" if r.stderr.strip() else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--ip", default="192.168.25.56")
    ap.add_argument("--peer", action="store_true")
    a = ap.parse_args()
    cmds = []
    for name, off, n in REGS:
        for i in range(n):
            cmds.append(f"echo '{name}[{i}]' 0x{off + 4 * i:04X} $(devmem 0x{BASE + off + 4 * i:08X} 32)")
    out = [f"=== {time.strftime('%Y-%m-%dT%H:%M:%S%z')} tag {a.tag}"]
    out.append("--- temp\n" + ssh(a.ip, "for z in /sys/class/thermal/thermal_zone*; do echo $z $(cat $z/type) $(cat $z/temp); done"))
    out.append("--- regs\n" + ssh(a.ip, "; ".join(cmds)))
    out.append("--- interrupts #1\n" + ssh(a.ip, "grep -i 'eth\\|rteth\\|nic' /proc/interrupts; uptime"))
    out.append("--- interrupts #2\n" + ssh(a.ip, "grep -i 'eth\\|rteth\\|nic' /proc/interrupts; uptime"))
    out.append("--- rteth debugfs\n" + ssh(a.ip, "ls /sys/kernel/debug/rteth 2>&1; cat /sys/kernel/debug/rteth/rxq 2>&1 | head -60"))
    out.append("--- link\n" + ssh(a.ip, "ip -s link show lan1; ethtool lan1 2>&1 | head -30"))
    if a.peer:
        out.append("--- sw1 lan4 (read-only)\n" + ssh("192.168.25.48", "ethtool lan4 2>&1 | head -30; ip -s link show lan4"))
    text = "\n".join(out)
    print(text)
    log = ROOT / f"tmp/logs/swcore_diag_{a.tag}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as fh:
        fh.write(text + "\n")


if __name__ == "__main__":
    main()
