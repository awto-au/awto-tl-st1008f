#!/usr/bin/env python3
"""drop_counters — RTL9300 ASIC drop-reason counters over SSH from Linux (#74).

- `0xBB00B5B8 + 4n` (phys `0x1B00B5B8`), n = 0..84, 16 bit each; names from the GPL SDK `mac_debug.c`
  (`hal_getDbgCntr`, parsed by scripts/sdk_leftovers_scan.py); n = 9-11 unnamed.
- Read with BusyBox `devmem` in one SSH call. `snap` logs nonzero counters; `diff -- CMD` snapshots,
  runs CMD on the host, snapshots again and logs the nonzero deltas (16-bit wrap handled).
- Library: `snap()` / `delta()` (nic_path_bench logs deltas per test). Log: tmp/logs/drop_counters.log
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/drop_counters.log"
sys.path.insert(0, str(ROOT / "scripts"))
BASE = 0x1B00B5B8
N = 85
READ_S = 10  # 85 devmem forks over SSH: < 1 s at 1 GHz + SSH setup; 10 s names a stuck link
NAMES = {
    0: "OAM_PARSER", 1: "UC_RPF", 2: "DEI_CFI", 3: "MAC_IP_SUBNET_BASED_VLAN", 4: "VLAN_IGR_FILTER",
    5: "L2_UC_MC_BRIDGE", 6: "IP4_IP6_MC_BRIDGE", 7: "PTP", 8: "USER_DEF_0_3", 12: "BPDU_RMA", 13: "LACP",
    14: "LLDP", 15: "EAPOL", 16: "XX_RMA", 17: "L3_IPUC_NON_IP", 18: "IP4_IP6_HEADER_ERROR", 19: "L3_BAD_IP",
    20: "L3_DIP_DMAC_MISMATCH", 21: "IP4_IP_OPTION", 22: "IP_UC_MC_ROUTING_LOOK_UP_MISS",
    23: "L3_DST_NULL_INTF", 24: "L3_PBR_NULL_INTF", 25: "HOST_NULL_INTF", 26: "ROUTE_NULL_INTF",
    27: "BRIDGING_ACTION", 28: "ROUTING_ACTION", 29: "IPMC_RPF", 30: "L2_NEXTHOP_AGE_OUT",
    31: "L3_UC_TTL_FAIL", 32: "L3_MC_TTL_FAIL", 33: "L3_UC_MTU_FAIL", 34: "L3_MC_MTU_FAIL",
    35: "L3_UC_ICMP_REDIR", 36: "IP6_MLD_OTHER_ACT", 37: "ND", 38: "IP_MC_RESERVED", 39: "IP6_HBH",
    40: "INVALID_SA", 41: "L2_HASH_FULL", 42: "NEW_SA", 43: "PORT_MOVE_FORBID", 44: "STATIC_PORT_MOVING",
    45: "DYNMIC_PORT_MOVING", 46: "L3_CRC", 47: "MAC_LIMIT", 48: "ATTACK_PREVENT", 49: "ACL_FWD_ACTION",
    50: "OAMPDU", 51: "OAM_MUX", 52: "TRUNK_FILTER", 53: "ACL_DROP", 54: "IGR_BW", 55: "ACL_METER",
    56: "VLAN_ACCEPT_FRAME_TYPE", 57: "MSTP_SRC_DROP_DISABLED_BLOCKING", 58: "SA_BLOCK", 59: "DA_BLOCK",
    60: "STORM_CONTROL", 61: "VLAN_EGR_FILTER", 62: "MSTP_DESTINATION_DROP", 63: "SRC_PORT_FILTER",
    64: "PORT_ISOLATION", 65: "TX_MAX_FRAME_SIZE", 66: "EGR_LINK_STATUS", 67: "MAC_TX_DISABLE",
    68: "MAC_PAUSE_FRAME", 69: "MAC_RX_DROP", 70: "MIRROR_ISOLATE", 71: "RX_FC", 72: "EGR_QUEUE",
    73: "HSM_RUNOUT", 74: "ROUTING_DISABLE", 75: "INVALID_L2_NEXTHOP_ENTRY", 76: "L3_MC_SRC_FLT",
    77: "CPUTAG_FLT", 78: "FWD_PMSK_NULL", 79: "IPUC_ROUTING_LOOKUP_MISS", 80: "MY_DEV_DROP",
    81: "STACK_NONUC_BLOCKING_PMSK", 82: "STACK_PORT_NOT_FOUND", 83: "ACL_LOOPBACK_DROP",
    84: "IP6_ROUTING_EXT_HEADER",
}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def snap() -> list[int]:
    import nat_bench
    cmd = f"i=0; while [ $i -lt {N} ]; do devmem $(({BASE} + 4 * i)) 32; i=$((i + 1)); done"
    out = nat_bench.sw(cmd, tmo=READ_S).split()
    if len(out) != N:
        raise SystemExit(f"drop counters: {len(out)} values, want {N}")
    return [int(v, 16) & 0xFFFF for v in out]


def name(i: int) -> str:
    return NAMES.get(i, f"#{i}")


def delta(a: list[int], b: list[int]) -> dict[str, int]:
    return {name(i): (y - x) & 0xFFFF for i, (x, y) in enumerate(zip(a, b)) if y != x}


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("snap", "diff"):
        print(__doc__)
        return 2
    a = snap()
    if sys.argv[1] == "snap":
        log("nonzero: " + (", ".join(f"{name(i)} {v}" for i, v in enumerate(a) if v) or "none"))
        return 0
    cmd = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if cmd:
        subprocess.run(cmd, timeout=600)  # caller's workload; 600 s names a stuck one
    d = delta(a, snap())
    log("delta: " + (", ".join(f"{k} {v}" for k, v in d.items()) or "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
