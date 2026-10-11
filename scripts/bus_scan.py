#!/usr/bin/env python3
"""bus_scan — read-only I2C/SPI scan for undocumented devices at our U-Boot prompt (#77, docs/BUS-SCAN.md).

- I2C MST1 SDA0-7 (cages 1-8): `busscan i2c N` at 100 kHz, then again at 50 kHz (MCU modules clock-stretch).
- i2c8 (GPIO22/23 bit-bang, TCA9534A @0x38): `busscan i2c 8`.
- Probe = 0x08-0x77 only; first read = 16 B from reg 0 per responder (pointer write + read, no data writes).
- SPI flash controller: `busscan spi 0` (baseline: boot flash RDID) and `busscan spi 1` (RDID + RDSR only).
- Registers (`md.l`, no writes): switch-core SPI master + pinmux, I2C MST2 (never driven: SCL1 = GPIO17 = mode
  switch), MAC EEPROM autoload, I2C/SPI slave, EXT_GPIO (RTL8231), SPI-NOR SFCR/SFCSR, GPIO (MOD-DEF0).
- Only write: `rtk laser none` (all TX-disable = safe direction) unless --keep-lasers.
- Without the `busscan` command (flash copy of ours older than the build): I2C via `i2c probe`/`i2c md`, SPI skipped.
- Output: tmp/bus_scan-<label>.json; log tmp/logs/bus_scan.log.
- Run: `./dev.py bus-scan [--label L] [--network-on] [--keep-lasers]` at the `st1008f-mainline #` prompt.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_probe  # noqa: E402  (md(), log())
from st1008_ramload import Console, network_on  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
hw_probe.LOG = ROOT / "tmp/logs/bus_scan.log"
log = hw_probe.log
PROMPT_TXT = "st1008f-mainline #"
PROMPT = r"\r?\nst1008f-mainline # "
# `busscan i2c`: 112 probes; worst case every probe hits the driver busy cap (1.6 ms at 50 kHz) = 0.18 s,
# + 16 B reads + ~1.5 KB of output at 115200 (0.13 s) + daemon/poll latency 0.2 s = 0.5 s; x1.25 -> 0.65 s,
# rounded to 1 s (console poll is 50 ms; hw_probe uses the same cap). Expiry = SystemExit naming the command.
CAP_SCAN_S = 1
CAP_CMD_S = 1  # one short command (md.l, i2c probe <addr>, busscan spi): < 0.1 s on the wire
NBUS_SFP, BUS_EXP = 8, 8

KNOWN = {0x50: "SFF-8472 A0 ID EEPROM", 0x51: "SFF-8472 A2 DDM", 0x56: "copper-module PHY (88E1111-style)"}
KNOWN_EXP = {0x38: "TCA9534A laser TX-disable expander"}

# (name, addr, words); SPI-NOR SFDR (0xb800120c) not read: a read clocks the bus
REGS = [
    ("GPIO_SEL_CTRL/+4 (slave SPI CS/SDO GPIO, LED sync)", 0xBB000200, 2),
    ("MAC_IF_CTRL/MAC_SLV_I2C_CTRL/MAC_SLV_TIMEOUT", 0xBB000360, 3),
    ("I2C_MST1 CTRL1/2 DATA0-3, I2C_MST_GLB_CTRL", 0xBB00036C, 7),
    ("I2C_MST2 CTRL1/2 DATA0-3", 0xBB000388, 6),
    ("SPI_CTRL1/SPI_CTRL2/SPI_ADDR (switch-core SPI master)", 0xBB0003A0, 3),
    ("EXT_GPIO_GLB_CTRL (RTL8231 over MDIO)", 0xBB00C600, 1),
    ("MAC_EEPROM_DOWN_LOAD CNTRL/STS/MAC/SERDES/PHY/GROUP_MAC_POS", 0xBB00C6E4, 6),
    ("SPI-NOR SFCR/SFCR2/SFCSR", 0xB8001200, 3),
    ("GPIO en/dir/dat/isr/imr", 0xB8003300, 7),
]


def f(v: int, hi: int, lo: int) -> int:
    return v >> lo & ((1 << (hi - lo + 1)) - 1)


def decode(regs: dict[int, list[int]]) -> dict[str, str]:
    d = {}
    gs = regs[0xBB000200][0]
    d["GPIO_SEL_CTRL"] = (f"SLV_SPI_CS_SEL_GPIO={f(gs, 9, 5)} SLV_SPI_SDO_SEL_GPIO={f(gs, 4, 0)} "
                          f"GPIO18_USBLED={f(gs, 10, 10)} GPIO19_LEDSYNC={f(gs, 11, 11)}")
    ifc, slv, to = regs[0xBB000360]
    d["slave if"] = (f"MAC_IF_CTRL REG_IF_SEL={f(ifc, 0, 0)} SPI_SO_REF={f(ifc, 1, 1)}; "
                     f"SLV_I2C CFG_SDA_DLY={f(slv, 13, 8)} ENDIAN={f(slv, 0, 0)}; "
                     f"SLV_TIMEOUT SPI_SET={f(to, 29, 16)} SPI_FLAG={f(to, 15, 15)} "
                     f"I2C_SET={f(to, 14, 1)} I2C_FLAG={f(to, 0, 0)}")
    glb = regs[0xBB00036C][6]
    d["I2C_MST_GLB_CTRL"] = (f"SDA_SEL[7:0]=0x{f(glb, 7, 0):02x} OPEN_DRN_SDA=0x{f(glb, 15, 8):02x} "
                             f"OPEN_DRN_SCL_MST1={f(glb, 16, 16)} MST2={f(glb, 17, 17)}")
    m2 = regs[0xBB000388]
    d["I2C_MST2"] = (f"CTRL1=0x{m2[0]:08x} (SCL_SEL bit3={f(m2[0], 3, 3)}, TRIG={f(m2[0], 0, 0)}) "
                     f"CTRL2=0x{m2[1]:08x} DEV_ADDR=0x{f(m2[1], 14, 8):02x}")
    s1, s2, _ = regs[0xBB0003A0]
    d["SPI_CTRL1"] = (f"GPIO_SPI_SEL(GPIO3-5)={f(s1, 13, 13)} GPIO7_CSB0_SEL={f(s1, 10, 10)} "
                      f"GPIO6_CSB1_SEL={f(s1, 11, 11)} CSB_OUT_SEL={f(s1, 12, 12)} CLK_DIV={f(s1, 16, 14)} "
                      f"TRIG={f(s1, 0, 0)}; SPI_CTRL2=0x{s2:08x}")
    eg = regs[0xBB00C600][0]
    d["EXT_GPIO"] = f"EXT_GPIO_EN={f(eg, 8, 8)} MDX2_EN={f(eg, 1, 1)} MDX3_EN={f(eg, 0, 0)}"
    ee = regs[0xBB00C6E4]
    d["MAC_EEPROM"] = (f"CNTRL SCK_FREQ_SEL={f(ee[0], 9, 8)} EEPROM_VALID=0x{f(ee[0], 7, 0):02x}; "
                       f"STS NOEEPROM={f(ee[1], 0, 0)} EEPROM_COMPL={f(ee[1], 1, 1)} "
                       f"VALID_FAIL={f(ee[1], 2, 2)}; POS MAC/SDS/PHY/GMAC=" +
                       " ".join(f"{w >> 16:04x}-{w & 0xFFFF:04x}" for w in ee[2:]))
    sfcsr = regs[0xB8001200][2]
    d["SFCSR"] = f"CSB0={f(sfcsr, 31, 31)} CSB1={f(sfcsr, 30, 30)} (1 = deasserted)"
    dat = regs[0xB8003300][3]
    d["MOD-DEF0"] = " ".join(f"c{c + 1}={'present' if not dat >> c & 1 else 'empty'}" for c in range(8))
    return d


def i2c_busscan(con: Console, bus: int, hz: int) -> dict:
    _, out = con.run(f"busscan i2c {bus} {hz}", rf"i2c{bus} done: \d+ found{PROMPT}", CAP_SCAN_S,
                     f"busscan i2c{bus} {hz or 'default'} Hz")
    found = {}
    for m in re.finditer(rf"i2c{bus} 0x([0-9a-f]{{2}}) (ack|data((?: [0-9a-f]{{2}})+)|read FAIL (-?\d+))", out):
        a = int(m.group(1), 16)
        e = found.setdefault(a, {"data": None, "err": None})
        if m.group(3):
            e["data"] = m.group(3).split()
        elif m.group(4):
            e["err"] = int(m.group(4))
    hzm = re.search(rf"i2c{bus} scan 0x08-0x77 at (\d+) Hz", out)
    return {"hz": int(hzm.group(1)) if hzm else hz, "found": found}


def i2c_fallback(con: Console, bus: int) -> dict:
    """Stock-command path: per-address `i2c probe` (bit-bang bus must not see 0x00-0x07/0x78+)."""
    con.run(f"i2c dev {bus}", rf"Setting bus to {bus}{PROMPT}", CAP_CMD_S, f"i2c dev {bus}")
    found = {}
    for a in range(0x08, 0x78):
        _, out = con.run(f"i2c probe {a:x}", PROMPT, CAP_CMD_S, f"i2c{bus} probe 0x{a:02x}")
        if re.search(rf"Valid chip addresses:\s*{a:02X}\b", out, re.I):
            found[a] = {"data": None, "err": None}
    for a, e in found.items():
        _, out = con.run(f"i2c md {a:x} 0.1 10", PROMPT, CAP_CMD_S, f"i2c{bus} md 0x{a:02x}")
        m = re.search(r"0000:((?: [0-9a-f]{2}){16})", out)
        e["data"] = m.group(1).split() if m else None
        e["err"] = None if m else "md failed"
    return {"hz": None, "found": found}


def spi_scan(con: Console, cs: int) -> dict:
    _, out = con.run(f"busscan spi {cs}", rf"spi cs{cs} rdsr[^\n]*{PROMPT}", CAP_CMD_S, f"busscan spi {cs}")
    rid = re.search(rf"spi cs{cs} rdid((?: [0-9a-f]{{2}})+)", out)
    rsr = re.search(rf"spi cs{cs} rdsr ([0-9a-f]{{2}})", out)
    return {"rdid": rid.group(1).split() if rid else None, "rdsr": rsr.group(1) if rsr else None,
            "raw": out.strip()[-300:]}


def ident(bus: int, a: int) -> str:
    return (KNOWN_EXP if bus == BUS_EXP else KNOWN).get(a, "UNKNOWN: new device")


def spi_verdict(r: dict) -> str:
    if not r["rdid"]:
        return "no answer"
    b = {x.lower() for x in r["rdid"][:3]}
    return "nothing attached (bus floats/pulled)" if b in ({"ff"}, {"00"}) else f"DEVICE: JEDEC {' '.join(r['rdid'][:3])}"


def run(a: argparse.Namespace) -> int:
    con, res = Console(), {"label": a.label, "time": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    path = ROOT / f"tmp/bus_scan-{a.label}.json"
    save = lambda: path.write_text(json.dumps(res, indent=1))  # noqa: E731  per step: a hang keeps the rest
    log(f"=== bus_scan {a.label}")
    con.run("", PROMPT, CAP_CMD_S, "our prompt")
    _, out = con.run("help busscan", PROMPT, CAP_CMD_S, "busscan present?")
    have = "Unknown command" not in out
    log(f"busscan command: {'present' if have else 'ABSENT (flash copy of ours predates it): fallback'}")
    if a.network_on:
        network_on(con, PROMPT_TXT)
    res["regs"] = {}
    for name, addr, n in REGS:
        r = hw_probe.md(con, addr, n, name)
        if isinstance(r, str):
            log(f"STOP at {name}: {r}")
            save()
            return 1
        res["regs"][addr] = r
        log(f"  {addr:08x} {name}: " + " ".join(f"{w:08x}" for w in r))
    res["decode"] = decode(res["regs"])
    res["regs"] = {f"{k:08x}": [f"{w:08x}" for w in v] for k, v in res["regs"].items()}
    for k, v in res["decode"].items():
        log(f"  {k}: {v}")
    save()
    _, out = con.run("rtk laser", rf"cage 8: \w+{PROMPT}", CAP_CMD_S, "laser status")
    res["lasers_before"] = re.findall(r"cage (\d): (ON|off)", out)
    if not a.keep_lasers:
        con.run("rtk laser none", rf"OK \(out 0xff\){PROMPT}", CAP_CMD_S, "all lasers off")
    res["i2c"] = {}
    for bus in range(NBUS_SFP + 1):
        speeds = [0, 50000] if bus < NBUS_SFP else [0]
        res["i2c"][bus] = [i2c_busscan(con, bus, hz) if have else i2c_fallback(con, bus)
                           for hz in (speeds if have else [0])]
        save()
    res["spi"] = {cs: spi_scan(con, cs) for cs in (0, 1)} if have else "skipped: busscan absent"
    save()
    return report(res)


def report(res: dict) -> int:
    log("| bus | addr | first 16 B | identity |")
    log("|---|---|---|---|")
    unknown = 0
    for bus, passes in res["i2c"].items():
        addrs = sorted({x for p in passes for x in p["found"]})
        if not addrs:
            log(f"| i2c{bus} | none | - | " + ", ".join(f"{p['hz']} Hz" for p in passes) + " |")
        for x in addrs:
            hits = [p for p in passes if x in p["found"]]
            e = next((p["found"][x] for p in hits if p["found"][x]["data"]), hits[0]["found"][x])
            data = " ".join(e["data"]) if e["data"] else f"read FAIL {e['err']}"
            hz = "/".join(str(p["hz"]) for p in hits)
            unknown += ident(bus, x).startswith("UNKNOWN")
            log(f"| i2c{bus} @{hz} Hz | 0x{x:02x} | {data} | {ident(bus, x)} |")
    if isinstance(res["spi"], dict):
        for cs, r in res["spi"].items():
            log(f"| spi cs{cs} | RDID {' '.join(r['rdid'] or ['-'])} | RDSR {r['rdsr']} | {spi_verdict(r)} |")
    log(f"unknown I2C devices: {unknown}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--network-on", action="store_true", help="run `rtk network on` in ours first (once per boot)")
    ap.add_argument("--keep-lasers", action="store_true", help="do not send `rtk laser none`")
    return run(ap.parse_args())


if __name__ == "__main__":
    sys.exit(main())
