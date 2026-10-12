#!/usr/bin/env python3
"""switch_snmp — poll a switch's IF-MIB over SNMP, log every sample, flag interface errors/discards.

- Per interface: ifName, oper status, speed, HC in/out octets + unicast packets, in/out errors, in/out discards.
- Appends one JSON row per interface per sample to tmp/logs/switch_snmp-<ip>.jsonl; compares with the previous
  sample in that file and prints ERRORS when any error/discard counter grew. Rates in Mbit/s from octet deltas.
- `--every S --count N` samples N times; default one sample. Community/version from ~/.snmp/snmp.conf.
- Exit 0 = no error growth, 1 = errors/discards grew, 2 = SNMP failed. Log: tmp/logs/switch_snmp.log
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/switch_snmp.log"
COLS = {"name": "IF-MIB::ifName", "oper": "IF-MIB::ifOperStatus", "mbps": "IF-MIB::ifHighSpeed",
        "in_oct": "IF-MIB::ifHCInOctets", "out_oct": "IF-MIB::ifHCOutOctets",
        "in_ucast": "IF-MIB::ifHCInUcastPkts", "out_ucast": "IF-MIB::ifHCOutUcastPkts",
        "in_err": "IF-MIB::ifInErrors", "out_err": "IF-MIB::ifOutErrors",
        "in_disc": "IF-MIB::ifInDiscards", "out_disc": "IF-MIB::ifOutDiscards"}
BAD = ("in_err", "out_err", "in_disc", "out_disc")
WALK_S = 5  # one column walk of ~12 rows on the LAN answers in <0.1 s; 1 s per request x 2 tries, 5 s cap


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def walk(ip: str, oid: str) -> dict[int, str]:
    r = subprocess.run(["snmpbulkwalk", "-t", "1", "-r", "1", "-Oqe", ip, oid],
                       capture_output=True, text=True, timeout=WALK_S)
    if r.returncode:
        raise RuntimeError(f"snmpbulkwalk {oid}: {r.stderr.strip()}")
    out = {}
    for ln in r.stdout.splitlines():
        k, _, v = ln.partition(" ")
        out[int(k.rsplit(".", 1)[1])] = v.strip().strip('"')
    return out


def sample(ip: str) -> dict[int, dict]:
    cols = {k: walk(ip, o) for k, o in COLS.items()}
    rows = {}
    for idx, name in cols["name"].items():
        r = {"idx": idx, "name": name}
        for k in COLS:
            if k != "name":
                v = cols[k].get(idx)
                r[k] = int(v) if v is not None and v.lstrip("-").isdigit() else v
        rows[idx] = r
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default="192.168.25.48")
    ap.add_argument("--every", type=float, default=10.0)
    ap.add_argument("--count", type=int, default=1)
    a = ap.parse_args()
    jl = ROOT / f"tmp/logs/switch_snmp-{a.ip}.jsonl"
    prev: dict[str, dict] = {}
    if jl.exists():
        for ln in jl.read_text().splitlines()[-64:]:
            r = json.loads(ln)
            prev[r["name"]] = r
    worst = 0
    for n in range(a.count):
        try:
            rows = sample(a.ip)
        except (RuntimeError, subprocess.TimeoutExpired) as e:
            log(f"FAIL {a.ip}: {e}")
            return 2
        ts = time.time()
        with jl.open("a") as fh:
            for r in rows.values():
                r["ts"] = ts
                fh.write(json.dumps(r) + "\n")
        for r in sorted(rows.values(), key=lambda r: r["name"]):
            p = prev.get(r["name"])
            line = f"{r['name']:<10} {r['oper']:<5} {r['mbps']:>6} Mb/s  err in/out {r['in_err']}/{r['out_err']}  disc in/out {r['in_disc']}/{r['out_disc']}"
            if p and isinstance(r["in_oct"], int) and isinstance(p.get("in_oct"), int) and ts > p["ts"]:
                dt = ts - p["ts"]
                line += f"  rate in/out {(r['in_oct'] - p['in_oct']) * 8 / dt / 1e6:.1f}/{(r['out_oct'] - p['out_oct']) * 8 / dt / 1e6:.1f} Mbit/s"
                grew = {k: r[k] - p[k] for k in BAD if isinstance(r[k], int) and isinstance(p.get(k), int) and r[k] > p[k]}
                if grew:
                    line += f"  ERRORS +{grew}"
                    worst = 1
            log(line)
        prev = {r["name"]: r for r in rows.values()}
        if n + 1 < a.count:
            time.sleep(a.every)  # sampling interval chosen by the caller (--every)
    return worst


if __name__ == "__main__":
    sys.exit(main())
