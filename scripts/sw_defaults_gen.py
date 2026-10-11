#!/usr/bin/env python3
"""sw_defaults_gen — RTL9303 switch defaults that stock `rtk network on` writes and ours did not (#80).

- Source of the sequence: Realtek SDK (GPL-2.0, reyalo/Realtek rtk-dms1250), bootloader build:
  - "Chip Construct" = dal_longan_construct_default_init (dal_longan_construct.c), model 8XG.
  - "Mgmt_dev init" = dal_longan_init under __BOOTLOADER__: port_init (CPU port id), l2_init (flood
    masks), eee_init (EEE off), stack_init (stack defaults). VLAN/STP init are NOT in the bootloader.
- Each op is written by SDK register/field name; addresses resolved with the SDK's own rules
  (reg.c _reg_addr_find / reg_array_field_write, chipdef.c rtl9300_macPpInfo per-port blocks).
- Output: shared/rtl930x-sw/rtl930x_sw_defaults.h (generated: offset, mask, value per RMW, in order).
- Inputs: tmp/datasheet-audit/sdk/longan/rtk_longan_reg_list.c + _regField_list.c (`sdk_regdump.py --fetch`).
- Log: tmp/logs/sw_defaults_gen.log (every op with its resolved address).
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SDK = ROOT / "tmp/datasheet-audit/sdk/longan"
OUT = ROOT / "shared/rtl930x-sw/rtl930x_sw_defaults.h"
LOG = ROOT / "tmp/logs/sw_defaults_gen.log"

# RTL9303_8XGE hardware profile: cage ports (XGE on SerDes) and the CPU port
CAGES = [0, 8, 16, 20, 24, 25, 26, 27]
CPU = 28
ALL = CAGES + [CPU]
ALL_MASK = sum(1 << p for p in ALL)
# chipdef.c rtl9300 capacity: queues 8, stack queues 12, CPU queues 32, trunks 64, devices 16
NQ, NSQ, NCPUQ, NTRK, NDEV = 8, 12, 32, 64, 16
# chipdef.c rtl9300_macPpInfo: (low, high, interval) of the per-port register blocks
PP = [(0x3260, 0x3A5C, 0x40), (0x3C60, 0x67DC, 0x180), (0x67E0, 0x765C, 0x60), (0x7660, 0x785C, 0x10),
      (0xE300, 0xEAFC, 0x60)]

REG_RE = re.compile(
    r'/\* register name  \*/\s+"(?P<name>\w+)".*?'
    r"/\* offset address \*/\s+(?P<off>0x[0-9A-Fa-f]+).*?"
    r"/\* port index \*/\s+(?P<p0>\d+),\s*(?P<p1>\d+).*?"
    r"/\* array index \*/\s+(?P<a0>\d+),\s*(?P<a1>\d+).*?"
    r"/\* bit offset \*/\s+(?P<bo>\d+).*?"
    r"/\* register fields \*/\s+(?P<fields>\w+)_FIELDS",
    re.S)
FIELDS_RE = re.compile(r"rtk_regField_t (\w+)_FIELDS\[\] =\s*\{(.*?)\n\};", re.S)
FIELD_RE = re.compile(r"/\* lsp \*/\s+(\d+),\s*/\* len \*/\s+(\d+),.*?/\* field name \*/\s+\"(\w+)\"", re.S)


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(msg + "\n")


def load():
    fields = {m.group(1): {f[2]: (int(f[0]), int(f[1])) for f in FIELD_RE.findall(m.group(2))}
              for m in FIELDS_RE.finditer((SDK / "rtk_longan_regField_list.c").read_text(errors="replace"))}
    regs = {}
    for m in REG_RE.finditer((SDK / "rtk_longan_reg_list.c").read_text(errors="replace")):
        regs[m.group("name")] = dict(off=int(m.group("off"), 16), p0=int(m.group("p0")), p1=int(m.group("p1")),
                                     a0=int(m.group("a0")), a1=int(m.group("a1")), bo=int(m.group("bo")),
                                     fields=fields[m.group("fields")])
    return regs


def resolve(regs, reg, field, i1=None, i2=None):
    """(addr, mask) of REG.FIELD[i1][i2], as SDK reg_array_field_write computes them."""
    r = regs[reg]
    lsp, ln = r["fields"][field]
    bo, addr = r["bo"], r["off"]
    if i1 is not None and not r["p0"] <= i1 <= r["p1"]:
        raise SystemExit(f"{reg}: index_1 {i1} outside {r['p0']}..{r['p1']}")
    if i2 is not None and not r["a0"] <= i2 <= r["a1"]:
        raise SystemExit(f"{reg}: index_2 {i2} outside {r['a0']}..{r['a1']}")

    def step(i, lo):  # offset of element i within one dimension
        return (i - lo) // (32 // bo) * 4 if bo % 32 else (i - lo) * (bo // 8)

    pp = next((b for b in PP if b[0] <= addr <= b[1]), None)
    if pp:
        if i1 is not None:
            addr += i1 * pp[2]
        if i2 is not None:
            addr += step(i2, r["a0"])
    elif i1 is not None and i2 is not None:
        dim1 = ((r["a1"] - r["a0"]) // (32 // bo) + 1) * 4 if bo % 32 else (r["a1"] - r["a0"] + 1) * (bo // 8)
        addr += (i1 - r["p0"]) * dim1 + step(i2, r["a0"])
    elif i1 is not None:
        addr += step(i1, r["p0"])
    elif i2 is not None:
        addr += step(i2, r["a0"])
    if bo % 32 == 0:
        pos = lsp
    elif i2 is not None:
        pos = (i2 - r["a0"]) % (32 // bo) * bo
    elif i1 is not None:
        pos = (i1 - r["p0"]) % (32 // bo) * bo
    else:
        pos = 0
    words = (bo + 31) >> 5 if bo > 32 else 1
    addr += (words - 1 - (pos >> 5)) * 4
    pos &= 31
    mask = ((1 << ln) - 1) << pos if ln < 32 else 0xFFFFFFFF
    return addr, mask & 0xFFFFFFFF, pos


# --- the sequence, SDK names; (reg, field, value, index_1, index_2) ---------------------------
def construct_default():
    """dal_longan_construct_default_init, RTL9303 8XG (fcModelIdx 1). Skipped: SMI FREQ_SEL (chip rev 2 only)."""
    ops = []
    w = lambda reg, f, v, i1=None, i2=None: ops.append((reg, f, v, i1, i2))  # noqa: E731
    # smi
    for f, v in (("SMI0_POLL_SEL", 0), ("SMI1_POLL_SEL", 0), ("SMI2_POLL_SEL", 0), ("SMI3_POLL_SEL", 1)):
        w("SMI_GLB_CTRL", f, v)
    # port: ASIC auto queue-reset triggers off; SS-501 dummy
    for f in ("EN_SYS_DSC_ERR_TRIG", "EN_RXPORT_DSC_ERR_TRIG", "EN_TOKEN_ERR_TRIG"):
        w("TRIG_AUTO_RECOVER_CTRL_INGRESS", f, 0)
    for f in ("EN_LD_TX_DSC_ERR_TRIG", "EN_PINGPONG_ERR_TRIG"):
        w("TRIG_AUTO_RECOVER_CTRL_EGRESS", f, 0)
    w("TRIG_AUTO_RECOVER_CTRL_MAC", "EN_FIFO_ERR_TRIG", 0)
    w("DMY_REG0_CHIP_MISC_R", "DUMMY", 0xFFFFFFF)
    # rate: CPU port packet mode, bursts
    w("EGBW_CTRL", "RATE_MODE_CPU", 0)
    w("EGBW_PORT_CTRL", "BURST", 5, CPU)
    for q in range(NCPUQ):
        w("EGBW_CPU_Q_MAX_LB_CTRL", "BURST", 5, None, q)
    for p in CAGES:
        w("EGBW_PORT_CTRL", "BURST", 0x4000, p)
        s, nq = ("SET0", NQ) if p < 24 else ("SET1", NSQ)
        for q in range(nq):
            w(f"EGBW_PORT_Q_MAX_LB_CTRL_{s}", "BURST", 0x4000, p, q)
            w(f"EGBW_PORT_Q_ASSURED_FIX_BURST_CTRL_{s}", "BURST", 0x4000, p, q)
            w(f"EGBW_PORT_Q_ASSURED_LB_CTRL_{s}", "RATE", 0, p, q)
            w(f"EGBW_PORT_Q_FIX_LB_CTRL_{s}", "RATE", 0, p, q)
    # qos
    w("SCHED_PORT_ALGO_CTRL", "SCHED_TYPE", 1, CPU)  # WRR
    for f in ("PORT_PRI_REMAP_EN", "PROTO_VLAN_PRI_REMAP_EN", "MAC_IP_VLAN_PRI_REMAP_EN"):
        w("PRI_SEL_CTRL", f, 0)
    for q in range(NQ):
        w("QM_CPUQID2QID_CTRL", "QID", q, None, q)
    for q in range(NSQ):
        w("QM_CPUQID2XGQID_CTRL", "QID", q, None, q)
    # flow control, 8XG column
    for p in CAGES:  # all 10G
        w("FC_PORT_THR_SET_SEL", "IDX", 1, p)
        w("FC_PORT_EGR_DROP_THR_SET_SEL", "IDX", 1, p)
        w("ETE_FC_REMOTE_PORT_THR_SET_SEL", "IDX", 1, p)
    w("FC_PORT_EGR_DROP_CTRL", "REF_RXCNGST", 0, CPU)
    w("FC_PORT_THR_SET_SEL", "IDX", 0, CPU)
    for reg, f, v in (("FC_GLB_DROP_THR", "DROP_ALL", 0xff8), ("FC_GLB_SYS_UTIL_THR", "THR", 0x958),
                      ("FC_GLB_HI_THR", "ON", 0xa20), ("FC_GLB_HI_THR", "OFF", 0x9d0),
                      ("FC_GLB_LO_THR", "ON", 0x958), ("FC_GLB_LO_THR", "OFF", 0x908),
                      ("FC_GLB_FCOFF_HI_THR", "ON", 0xa20), ("FC_GLB_FCOFF_HI_THR", "OFF", 0x9d0),
                      ("FC_GLB_FCOFF_LO_THR", "ON", 0x958), ("FC_GLB_FCOFF_LO_THR", "OFF", 0x908),
                      ("FC_JUMBO_HI_THR", "ON", 0xd30), ("FC_JUMBO_HI_THR", "OFF", 0xce0),
                      ("FC_JUMBO_LO_THR", "ON", 0xc68), ("FC_JUMBO_LO_THR", "OFF", 0xc18),
                      ("FC_JUMBO_FCOFF_HI_THR", "ON", 0xd30), ("FC_JUMBO_FCOFF_HI_THR", "OFF", 0xce0),
                      ("FC_JUMBO_FCOFF_LO_THR", "ON", 0xc68), ("FC_JUMBO_FCOFF_LO_THR", "OFF", 0xc18),
                      ("FC_JUMBO_THR_ADJUST", "SYS_USED_PAGE_THR", 0xdc8),
                      ("FC_LB_PORT_Q_EGR_DROP_THR", "ON", 0x4e), ("FC_LB_PORT_Q_EGR_DROP_THR", "OFF", 0x44),
                      ("SC_P_CTRL", "DRAIN_OUT_THR_H", 0x140), ("SC_P_CTRL", "DRAIN_OUT_THR", 0x140),
                      ("ETE_FC_CASCADE_PORT_DROP_THR", "ON", 0x507), ("ETE_FC_CASCADE_PORT_DROP_THR", "OFF", 0x485)):
        w(reg, f, v)
    for p in CAGES:
        w("FC_PORT_ACT_CTRL", "ALLOW_PAGE_CNT", 0x32, p)
    port_sets = {0: (0x11b, 0x111, 0xa0, 0x78), 1: (0x11b, 0x111, 0xa0, 0x78), 2: (0x11b, 0x111, 0xa0, 0x78),
                 3: (0x17d, 0x173, 0x23, 0x19)}
    for idx, (hon, hoff, lon, loff) in port_sets.items():
        for reg in ("FC_PORT_HI_THR", "FC_PORT_FCOFF_HI_THR"):
            w(reg, "ON", hon, None, idx)
            w(reg, "OFF", hoff, None, idx)
        for reg in ("FC_PORT_LO_THR", "FC_PORT_FCOFF_LO_THR"):
            w(reg, "ON", lon, None, idx)
            w(reg, "OFF", loff, None, idx)
        w("FC_PORT_GUAR_THR", "THR", 0x10, None, idx)
    for idx in (0, 1):
        for reg in ("ETE_FC_ON_REMOTE_PORT_THR", "ETE_FC_OFF_REMOTE_PORT_THR"):
            w(reg, "ON", 0x17, None, idx)
            w(reg, "OFF", 0x0d, None, idx)
        w("ETE_FC_REMOTE_PORT_GUAR_THR", "THR", 0x10, None, idx)
    q_drop = {0: (0x4e, 0x44), 1: (0x118, 0xf0), 2: (0x4e, 0x44), 3: (0x64, 0x44)}
    red = {0: (0x7f, 0x71, 0x67), 1: (0x7f, 0x4e, 0x44), 2: (0x7f, 0x2b, 0x21)}
    for q in range(NSQ):
        for idx, (on, off) in q_drop.items():
            w("FC_Q_EGR_DROP_THR", "ON", on, q, idx)
            w("FC_Q_EGR_DROP_THR", "OFF", off, q, idx)
        for idx, (rate, mx, mn) in red.items():
            w("SWRED_QUEUE_DROP_CTRL", "RATE", rate, q, idx)
            w("SWRED_QUEUE_DROP_CTRL", "MAX", mx, q, idx)
            w("SWRED_QUEUE_DROP_CTRL", "MIN", mn, q, idx)
    for q in range(NCPUQ):
        w("FC_CPU_Q_EGR_DROP_THR", "ON", 0x4e, None, q)
        w("FC_CPU_Q_EGR_DROP_THR", "OFF", 0x44, None, q)
        w("FC_CPU_Q_EGR_FORCE_DROP_CTRL", "EN", 1, None, q)
    w("FC_GLB_SYS_UTIL_THR", "THR", 1)
    # ipmcast: exceptions bridged
    for f, v in (("DMAC_MISMATCH_ACT", 3), ("ZERO_SIP_ACT", 3), ("BAD_SIP_ACT", 3), ("HDR_OPT_ACT", 6)):
        w("L3_IPMC_ROUTE_CTRL", f, v)
    for f, v in (("DMAC_MISMATCH_ACT", 3), ("ZERO_SIP_ACT", 3), ("BAD_SIP_ACT", 3), ("HBH_ERR_ACT", 6),
                 ("HBH_ACT", 6), ("HDR_ROUTE_ACT", 6)):
        w("L3_IP6MC_ROUTE_CTRL", f, v)
    # acl, trunk, vlan, l2, l3, parser, misc
    for p in ALL:
        w("ACL_PORT_LOOKUP_CTRL", "LOOKUP_EN", 1, p)
    w("TRK_CTRL", "LINK_DOWN_AVOID", 1)
    w("TRK_CTRL", "LOCAL_FIRST", 1)
    w("TRK_HASH_CTRL", "L3_HASH_MSK", 0x3FF)
    w("VLAN_CTRL", "STP_LEAK_EN", 0)
    w("VLAN_PORT_IGR_FLTR", "IGR_FLTR_ACT", 0, CPU)
    w("VLAN_PORT_PB_VLAN", "OPVID_FMT", 0, CPU)
    w("VLAN_PORT_PB_VLAN", "IPVID_FMT", 0, CPU)
    w("L2_CTRL", "LINK_DOWN_P_INVLD", 0)
    w("L2_GLB_STT_PORT_MV_LRN", "LRN", 0)
    for p in ALL:
        w("L2_STT_PORT_MV_LRN", "LRN", 0, p)
    for t in range(NTRK):
        w("L2_STT_TRK_MV_LRN", "LRN", 0, None, t)
    w("L2_NTFY_CTRL", "LD_FLUSH_NTFY_EN", 1)
    w("L2_NTFY_CTRL", "DYN_NTFY_EN", 1)
    w("L2_PORT_DABLK_CTRL", "EN", 0, CPU)
    w("L2_PORT_SABLK_CTRL", "EN", 0, CPU)
    w("L3_IP6UC_ROUTE_CTRL", "DMAC_MISMATCH_ACT", 0)
    w("L3_IP_ROUTE_CTRL", "IP_HDR_ERR_ACT", 3)
    w("L3_IP_ROUTE_CTRL", "IP6_HDR_ERR_ACT", 3)
    w("PARSER_CTRL", "PPPOE_PARSE_EN", 1)
    # enables only: arm no timer (SoC WDT 0xb8003260 is outside this table), no trigger bit, no GPIO21
    w("RST_GLB_CTRL_0", "CHIP_RST_EN", 1)  # SW_CHIP_RST (bit 0) takes effect; never written as 1 here
    w("RST_GLB_CTRL_0", "WD_RST_EN", 1)  # a WDT expiry resets the chip: what bootsel `wdt on` relies on
    return ops


def dal_bootloader():
    """dal_longan_init (bootloader): port, l2, eee, stack. Port isolation (all ports) is replaced by ours."""
    ops = []
    w = lambda reg, f, v, i1=None, i2=None: ops.append((reg, f, v, i1, i2))  # noqa: E731
    w("MAC_L2_CPU_PORT_CTRL", "CPU_PORT", 0)  # CPU MAC id 28
    w("L2_UNKN_UC_FLD_PMSK", "PORTMASK", ALL_MASK)
    w("L2_BC_FLD_PMSK", "PORTMASK", ALL_MASK)
    for p in CAGES:
        for f in ("EEE_EN_100M", "EEE_EN_500M", "EEE_EN_1000M", "EEE_EN_2P5G", "EEE_EN_5G", "EEE_EN_10G"):
            w("MAC_FORCE_MODE_CTRL", f, 0, p)
        w("EEE_CTRL", "EEE_TX_EN", 0, p)
        w("EEE_CTRL", "EEE_RX_EN", 0, p)
    w("STK_GLB_CTRL", "STK_PORT_SEL", 0)
    w("DMY_REG0_QUEUE", "FORCE_ALL_PORT_SECOND_EGR_DROP", 0)
    w("STK_GLB_CTRL", "MY_DEV_ID", 0)
    w("STK_GLB_CTRL", "MASTER_DEV_ID", 0)
    w("STK_GLB_CTRL", "DROP_MY_DEV", 0)  # loop guard DISABLED
    for d in range(NDEV):
        w("STK_NON_UNICAST_BLOCK_CTRL", "NON_UNICAST_BLOCK_PM", 0, None, d)
    return ops


def emit(regs, name, doc, ops):
    rows, prev = [], None
    for reg, f, v, i1, i2 in ops:
        addr, mask, pos = resolve(regs, reg, f, i1, i2)
        val = (v << pos) & mask
        if val != v << pos:
            raise SystemExit(f"{reg}.{f} = {v:#x} does not fit the field")
        idx = "".join(f"[{i}]" for i in (i1, i2) if i is not None)
        if addr == 0x000C and mask & 0x7F:  # RST_GLB_CTRL_0 [6:0] = reset triggers incl. SW_CHIP_RST
            raise SystemExit(f"{reg}.{f}: refusing a write to a reset trigger bit")
        log(f"{name}: {reg}{idx}.{f} = {v:#x} -> {addr:#06x} mask {mask:#010x} val {val:#010x}")
        if prev and prev[0] == addr:  # consecutive RMWs of one word: same result as one
            prev[1] |= mask
            prev[2] = (prev[2] & ~mask) | val
            prev[3].append(f"{reg}{idx}.{f}")
        else:
            prev = [addr, mask, val, [f"{reg}{idx}.{f}"]]
            rows.append(prev)
    body = "\n".join(f"\t{{ 0x{a:04x}, 0x{m:08x}, 0x{v:08x} }},\t/* {', '.join(n)[:80]} */" for a, m, v, n in rows)
    return f"/* {doc} ({len(ops)} SDK field writes) */\nstatic const struct rtl930x_sw_rmw {name}[] = {{\n{body}\n}};\n"


def main() -> int:
    regs = load()
    if not regs:
        sys.exit(f"no SDK register tables in {SDK}: run scripts/sdk_regdump.py --fetch")
    LOG.write_text("")
    text = ("/* SPDX-License-Identifier: GPL-2.0-only */\n"
            "/* Generated by scripts/sw_defaults_gen.py from the Realtek SDK (GPL-2.0); do not edit.\n"
            " * RTL9303_8XGE switch defaults of stock `rtk network on` (#80). Apply in order: RMW. */\n"
            "#ifndef _RTL930X_SW_DEFAULTS_H\n#define _RTL930X_SW_DEFAULTS_H\n\n"
            "struct rtl930x_sw_rmw { u16 off; u32 mask; u32 val; };\n\n"
            + emit(regs, "rtl930x_sw_construct", "\"Chip Construct\": dal_longan_construct_default_init",
                   construct_default())
            + "\n" + emit(regs, "rtl930x_sw_dal", "\"Mgmt_dev init\": dal_longan_init, bootloader build",
                          dal_bootloader())
            + "\n#endif\n")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    log(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
