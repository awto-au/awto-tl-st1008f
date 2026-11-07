#!/usr/bin/env python3
"""cabling_map — read-only map of what is plugged into each ST1008F cage and what is on the other end (#135, #126, #127).

- Per switch over ssh (read-only commands only): link/speed, SFP module PN/SN, DDM tx/rx power, LLDP neighbour,
  bridge FDB MACs per port, recent `sfp ... module` kernel lines (hot-plug times). sw1 is in service: network reads only.
- MACs are labelled with the Omada controller's client list (../awto-omada/scripts/omada.py clients, read-only API).
- Each run saves tmp/cabling/<switch>-<ts>.json and prints what changed since the previous snapshot.
- `cabling_map.py [--switches sw1,sw2] [--no-omada] [--no-diff]`  Log tmp/logs/cabling_map.log
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP, SW1_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/cabling_map.log"
SNAP = ROOT / "tmp/cabling"
OMADA_PY = Path(os.environ.get("OMADA_PY", "/mnt/2tb/git/awto-omada/scripts/omada.py"))
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "BatchMode=yes", "-o", "LogLevel=ERROR"]
SWITCHES = {"sw1": SW1_IP, "sw2": BENCH_IP}

# One read-only snippet per switch; every command only reads sysfs, ethtool -m, lldpctl, bridge fdb, dmesg.
REMOTE = r"""
echo "HOST $(uname -r) up $(cut -d' ' -f1 /proc/uptime)"
for n in 1 2 3 4 5 6 7 8; do p=lan$n
  [ -d /sys/class/net/$p ] || continue
  echo "PORT $p carrier=$(cat /sys/class/net/$p/carrier 2>/dev/null) speed=$(cat /sys/class/net/$p/speed 2>/dev/null)"
  ethtool -m $p 2>/dev/null | grep -E "Vendor (name|PN|SN)|Laser output power  |Receiver signal average" | sed "s/^[ \t]*/MOD $p /"
done
lldpctl -f keyvalue 2>/dev/null | grep -E "^lldp\.lan[0-9]\.(chassis\.(name|mac)|port\.(id|descr))" | sed 's/^/LLDP /'
bridge fdb show 2>/dev/null | grep -v -E "permanent|self" | sed 's/^/FDB /'
dmesg 2>/dev/null | grep -E "sfp sfp-p[0-9]+: module" | tail -n 24 | sed 's/^/SFP /'
"""


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def omada_clients():
    """MAC (lower, colon) -> 'name ip @switchport' from the controller; {} if unavailable."""
    if not OMADA_PY.exists():
        log(f"omada: {OMADA_PY} not found, MACs stay unlabelled")
        return {}
    r = subprocess.run([sys.executable, str(OMADA_PY), "clients"], capture_output=True, text=True,
                       timeout=60)  # one controller API call, ~2 s on the LAN
    out = {}
    for ln in r.stdout.splitlines():
        m = re.match(r"^(\S+)\s+([0-9A-F]{2}(?:-[0-9A-F]{2}){5})\s+(R\s+)?(.*?)\s*(Switch \S+ \S+|EAP\S*.*)?$", ln)
        if not m:
            continue
        ip, mac, _, rest, where = m.groups()
        out.setdefault(mac.lower().replace("-", ":"), []).append(f"{ip} {rest.strip()[:24]} {(where or '').strip()[:34]}".strip())
    return out


def read_switch(name, ip):
    try:
        r = subprocess.run(SSH + [f"root@{ip}", REMOTE], capture_output=True, text=True,
                           timeout=40)  # 8 x ethtool -m + lldpctl + fdb + dmesg: ~5 s; 40 s names a hung ssh
    except subprocess.TimeoutExpired:
        return {"error": "ssh timed out (40 s)"}
    if r.returncode and not r.stdout:
        return {"error": f"ssh rc={r.returncode}: {r.stderr.strip()[:120]}"}
    d = {"ports": {}, "fdb": {}, "sfp_events": [], "host": ""}
    for ln in r.stdout.splitlines():
        tag, _, rest = ln.partition(" ")
        if tag == "HOST":
            d["host"] = rest
        elif tag == "PORT":
            m = re.match(r"(lan\d) carrier=(\S*) speed=(\S*)", rest)
            if m:
                d["ports"].setdefault(m[1], {}).update(carrier=m[2], speed=m[3])
        elif tag == "MOD":
            m = re.match(r"(lan\d) (.*?)\s*:\s*(.*)$", rest)
            if m:
                key = {"Vendor name": "vendor", "Vendor PN": "pn", "Vendor SN": "sn",
                       "Laser output power": "tx_power", "Receiver signal average optical power": "rx_power"}.get(m[2].strip())
                if key:
                    d["ports"].setdefault(m[1], {})[key] = m[3].strip()
        elif tag == "LLDP":
            m = re.match(r"lldp\.(lan\d)\.(\S+?)=(.*)$", rest)
            if m:
                d["ports"].setdefault(m[1], {}).setdefault("lldp", {})[m[2]] = m[3]
        elif tag == "FDB":
            m = re.match(r"(\S+) dev (lan\d)", rest)
            if m:
                d["fdb"].setdefault(m[2], [])
                if m[1] not in d["fdb"][m[2]]:
                    d["fdb"][m[2]].append(m[1])
        elif tag == "SFP":
            d["sfp_events"].append(rest.strip()[:150])
    return d


def label(mac, omada):
    return "; ".join(omada.get(mac.lower(), [])) or "?"


def show(name, ip, d, omada):
    log(f"=== {name} {ip}: {d.get('host', d.get('error'))}")
    if "error" in d:
        return
    for p in sorted(d["ports"]):
        v = d["ports"][p]
        mod = f"{v.get('pn', '-')} {v.get('sn', '-')}" if v.get("sn") else "(no module read)"
        pw = f" tx {v['tx_power'].split('/')[0].strip()} rx {v['rx_power'].split('/')[0].strip()}" if v.get("tx_power") else ""
        ll = v.get("lldp", {})
        lldp = f" LLDP {ll.get('chassis.name', ll.get('chassis.mac', ''))} {ll.get('port.descr', ll.get('port.id', ''))}".rstrip() if ll else ""
        log(f"{p}: carrier={v.get('carrier') or '-'} speed={v.get('speed') or '-'} {mod}{pw}{lldp}")
        for mac in d["fdb"].get(p, [])[:6]:
            log(f"      learned {mac} = {label(mac, omada)}")
        if len(d["fdb"].get(p, [])) > 6:
            log(f"      ... {len(d['fdb'][p])} MACs on {p}")
    for e in d["sfp_events"][-6:]:
        log(f"   sfp: {e}")


def key_state(d):
    s = {}
    for p, v in d.get("ports", {}).items():
        s[p] = {"sn": v.get("sn"), "carrier": v.get("carrier"), "speed": v.get("speed"),
                "lldp": (v.get("lldp") or {}).get("chassis.mac"), "fdb": sorted(d["fdb"].get(p, []))}
    return s


def diff(name, new):
    files = sorted(SNAP.glob(f"{name}-*.json")) if SNAP.exists() else []
    if not files:
        log(f"{name}: first snapshot, nothing to compare")
        return
    old = json.loads(files[-1].read_text())
    changes = []
    for p in sorted(set(old) | set(new)):
        o, n = old.get(p, {}), new.get(p, {})
        for k in ("sn", "carrier", "speed", "lldp", "fdb"):
            if o.get(k) != n.get(k):
                changes.append(f"{p}.{k}: {o.get(k)} -> {n.get(k)}")
    log(f"{name}: changes since {files[-1].name}: " + ("none" if not changes else ""))
    for c in changes:
        log(f"   CHANGED {c}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--switches", default="sw1,sw2")
    ap.add_argument("--no-omada", action="store_true")
    ap.add_argument("--no-diff", action="store_true")
    a = ap.parse_args()
    omada = {} if a.no_omada else omada_clients()
    SNAP.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    for name in a.switches.split(","):
        ip = SWITCHES[name]
        d = read_switch(name, ip)
        show(name, ip, d, omada)
        if "error" in d:
            continue
        st = key_state(d)
        if not a.no_diff:
            diff(name, st)
        (SNAP / f"{name}-{ts}.json").write_text(json.dumps(st, indent=1))


if __name__ == "__main__":
    main()
