#!/usr/bin/env python3
"""cabling_map — read-only map of what is plugged into each ST1008F cage and what is on the other end (#135, #126, #127).

- Per switch over ssh (read-only commands only): link/speed, SFP module PN/SN, DDM tx/rx power, LLDP neighbour,
  bridge FDB MACs per port, own MACs, `sfp sfp-pN: module ...` kernel lines (cage N = lanN; plain kernels have no DDM).
- MACs are labelled with the Omada client list (awto-omada/scripts/omada.py clients, read-only API); one switch's own MACs
  identify the other switch. Duplicate IPs (Omada list, ARP answers) are flagged.
- `--probe` (default on): arping -b from the host NIC for the edge devices; reply ratio per MAC proves both directions.
- Output: stdout + tmp/logs/cabling_map.log, the map in tmp/cabling/map-latest.md, a snapshot per switch and a diff
  against the previous snapshot (what was moved). sw1 is in service: network reads only.
- `cabling_map.py [--switches sw1,sw2] [--no-omada] [--no-probe] [--no-diff]`   (`./dev.py cabling-map`)
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP, SW1_IP, bench_nic  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/cabling_map.log"
SNAP = ROOT / "tmp/cabling"
REGISTRY = Path(os.environ.get("AWTO_IP_REGISTRY", "/mnt/2tb/git/awto-dan/docs/network/ip-registry.toml"))
OMADA_PY = Path(os.environ.get("OMADA_PY", "/mnt/2tb/git/awto-omada/scripts/omada.py"))
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "BatchMode=yes", "-o", "LogLevel=ERROR"]
SWITCHES = {"sw1": SW1_IP, "sw2": BENCH_IP}
PROBES = 8  # arping -b per IP: 8 probes ~ 8 s, enough for a reply ratio; edge devices only

# One read-only snippet per switch: sysfs, ethtool -m, lldpctl, bridge fdb, dmesg.
REMOTE = r"""
echo "HOST $(uname -r) up $(cut -d' ' -f1 /proc/uptime)"
for i in /sys/class/net/*; do n=$(basename $i); echo "OWN $n $(cat $i/address 2>/dev/null)"; done
for n in 1 2 3 4 5 6 7 8; do p=lan$n
  [ -d /sys/class/net/$p ] || continue
  echo "PORT $p carrier=$(cat /sys/class/net/$p/carrier 2>/dev/null) speed=$(cat /sys/class/net/$p/speed 2>/dev/null)"
  ethtool -m $p 2>/dev/null | grep -E "Vendor (name|PN|SN)|Laser output power  |Receiver signal average" | sed "s/^[ \t]*/MOD $p /"
done
lldpctl -f keyvalue 2>/dev/null | grep -E "^lldp\.lan[0-9]\.(chassis\.(name|mac)|port\.(id|descr))" | sed 's/^/LLDP /'
bridge fdb show 2>/dev/null | grep -v -E "permanent|self" | sed 's/^/FDB /'
dmesg 2>/dev/null | grep -E "sfp sfp-p[0-9]+: module" | tail -n 40 | sed 's/^/SFP /'
"""


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def omada_clients():
    """MAC (lower, colon) -> list of 'ip name @port'; {} if unavailable."""
    if not OMADA_PY.exists():
        log(f"omada: {OMADA_PY} not found, MACs stay unlabelled")
        return {}
    r = subprocess.run([sys.executable, str(OMADA_PY), "clients"], capture_output=True, text=True,
                       timeout=60)  # one controller API call, ~2 s on the LAN
    out = {}
    for ln in r.stdout.splitlines():
        m = re.match(r"^(\S+)\s+([0-9A-F]{2}(?:-[0-9A-F]{2}){5})\s+(R\s+)?(.*?)\s*(Switch \S+ \S+|EAP\S*.*)?$", ln)
        if m:
            ip, mac, res, rest, where = m.groups()
            out.setdefault(mac.lower().replace("-", ":"), []).append(
                {"ip": ip, "text": f"{ip} {rest.strip()[:24]} {(where or '').strip()[:30]}".strip(), "reserved": bool(res)})
    return out


def registry_hosts():
    """MAC (lower, colon) -> {ip, name, box, iface} from the house IP registry; {} if missing."""
    if not REGISTRY.exists():
        log(f"registry: {REGISTRY} not found, no box grouping")
        return {}
    out = {}
    for h in tomllib.loads(REGISTRY.read_text()).get("host", []):
        if h.get("mac"):
            out[h["mac"].lower().replace("-", ":")] = {k: h.get(k, "") for k in ("ip", "name", "box", "iface", "speed")}
    return out


def classify_dup(ip, macs, reg):
    """ARP flux (one box, several NICs on one subnet) vs a real duplicate IP."""
    boxes = {reg[m]["box"] for m in macs if m in reg and reg[m]["box"]}
    if len(boxes) == 1 and all(m in reg for m in macs):
        b = next(iter(boxes))
        regip = {reg[m]["ip"] + " " + reg[m]["iface"] for m in macs}
        return (f"ARP FLUX {ip}: {len(macs)} NICs of one box '{b}' answer ({', '.join(sorted(regip))}); not a second device. "
                f"Fix on that host: net.ipv4.conf.all.arp_ignore=1 and arp_announce=2")
    return f"DUPLICATE IP {ip}: " + ", ".join(f"{m} ({reg[m]['name']})" if m in reg else m for m in sorted(macs))


def read_switch(ip):
    try:
        r = subprocess.run(SSH + [f"root@{ip}", REMOTE], capture_output=True, text=True,
                           timeout=40)  # 8 x ethtool -m + lldpctl + fdb + dmesg: ~5 s; 40 s names a hung ssh
    except subprocess.TimeoutExpired:
        return {"error": "ssh timed out (40 s)"}
    if r.returncode and not r.stdout:
        return {"error": f"ssh rc={r.returncode}: {r.stderr.strip()[:120]}"}
    d = {"ports": {}, "fdb": {}, "sfp": {}, "own": {}, "host": ""}
    for ln in r.stdout.splitlines():
        tag, _, rest = ln.partition(" ")
        if tag == "HOST":
            d["host"] = rest
        elif tag == "OWN":
            m = re.match(r"(\S+) ((?:[0-9a-f]{2}:){5}[0-9a-f]{2})", rest)
            if m and m[2] != "00:00:00:00:00:00":
                d["own"][m[2]] = m[1]
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
            if m and m[1] not in d["fdb"].setdefault(m[2], []):
                d["fdb"][m[2]].append(m[1])
        elif tag == "SFP":  # dmesg order: the last line per cage wins
            m = re.search(r"sfp sfp-p(\d): module (removed|\S.*)", rest)
            if m:
                d["sfp"][f"lan{m[1]}"] = None if m[2] == "removed" else re.sub(r"\s+", " ", m[2]).strip()[:70]
    return d


def partner_of(name, port, v, d, omada, others, reg):
    """One-line label for what is behind a port."""
    ll = v.get("lldp", {})
    parts = []
    if ll:
        parts.append(f"LLDP {ll.get('chassis.name', ll.get('chassis.mac', ''))} {ll.get('port.descr', ll.get('port.id', ''))}".strip())
    macs = d["fdb"].get(port, [])
    for mac in macs[:3]:
        hit = [(o, i) for o, od in others.items() for m, i in od.items() if m == mac]
        sw = (f"{hit[0][0]} (switch)" if len({o for o, _ in hit}) == 1 and len(hit) > 1 else f"{hit[0][0]} {hit[0][1]}") if hit else None
        if not sw and mac.startswith("02:99:00:00:09:"):
            sw = "nat-bench netns on the host (VLAN 991/992)"
        if not sw and mac in reg:
            r = reg[mac]
            sw = f"{r['name']} {r['iface']} {r['speed']} (registry {r['ip']})"
        parts.append(f"{mac} = {sw or ('; '.join(c['text'] for c in omada.get(mac, [])[:1]) or '?')}")
    if len(macs) > 3:
        parts.append(f"... {len(macs)} MACs (trunk)")
    return " | ".join(parts) or "(nothing learned)"


def probe(ip_by_mac, nic):
    """arping -b each edge IP; returns {ip: {mac: replies}} and the probe count."""
    res = {}
    mine = set(re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", subprocess.run(["ip", "-4", "addr"], capture_output=True, text=True).stdout))
    for ip in sorted(set(ip_by_mac.values()) - mine):
        r = subprocess.run(["sudo", "-n", "arping", "-b", "-I", nic, "-c", str(PROBES), "-w", str(PROBES + 4), ip],
                           capture_output=True, text=True, timeout=PROBES + 20)  # paced by arping: 1 probe/s
        cnt = {}
        for m in re.finditer(r"reply from \S+ \[([0-9A-F:]{17})\]", r.stdout):
            mac = m[1].lower()
            cnt[mac] = cnt.get(mac, 0) + 1
        res[ip] = cnt
    return res


def snapshot_state(d):
    return {p: {"sn": v.get("sn"), "carrier": v.get("carrier"), "speed": v.get("speed"),
                "lldp": (v.get("lldp") or {}).get("chassis.mac"), "fdb": sorted(d["fdb"].get(p, [])),
                "sfp": d["sfp"].get(p)} for p, v in d.get("ports", {}).items()}


def diff(name, new):
    files = sorted(SNAP.glob(f"{name}-*.json")) if SNAP.exists() else []
    if not files:
        return [f"{name}: first snapshot, nothing to compare"]
    old = json.loads(files[-1].read_text())
    out = []
    for p in sorted(set(old) | set(new)):
        for k in ("sn", "carrier", "speed", "lldp", "fdb", "sfp"):
            if k == "fdb" and max(len(old.get(p, {}).get(k) or []), len(new.get(p, {}).get(k) or [])) > 6:
                continue  # trunk port: its learned MACs change every run
            if old.get(p, {}).get(k) != new.get(p, {}).get(k):
                out.append(f"CHANGED {name} {p}.{k}: {old.get(p, {}).get(k)} -> {new.get(p, {}).get(k)}")
    return [f"{name}: changes since {files[-1].name}: " + ("none" if not out else "")] + out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--switches", default="sw1,sw2")
    ap.add_argument("--no-omada", action="store_true")
    ap.add_argument("--no-probe", action="store_true")
    ap.add_argument("--no-diff", action="store_true")
    a = ap.parse_args()
    omada = {} if a.no_omada else omada_clients()
    reg = registry_hosts()
    data = {n: read_switch(SWITCHES[n]) for n in a.switches.split(",")}
    own = {n: d["own"] for n, d in data.items() if "own" in d}
    md = [f"# Cabling map {time.strftime('%Y-%m-%dT%H:%M:%S%z')}", ""]
    ip_by_mac = {}
    for name, d in data.items():
        md += [f"## {name} {SWITCHES[name]}: {d.get('host', d.get('error'))}", "", "| port | link | module | DDM tx/rx | partner |", "|---|---|---|---|---|"]
        if "error" in d:
            continue
        others = {o: od for o, od in own.items() if o != name}
        for p in sorted(set(d["ports"]) | set(d["sfp"])):
            v = d["ports"].get(p, {})
            link = f"{'up' if v.get('carrier') == '1' else 'down' if v.get('carrier') == '0' else '-'} {v.get('speed') if v.get('speed') not in (None, '', '-1') else ''}".strip()
            mod = f"{v.get('pn', '')} {v.get('sn', '')}".strip() or (d["sfp"].get(p) or "(none seen)")
            pw = f"{v['tx_power'].split('/')[0].strip()} / {v['rx_power'].split('/')[0].strip()}" if v.get("tx_power") else "-"
            md.append(f"| {p} | {link or '-'} | {mod} | {pw} | {partner_of(name, p, v, d, omada, others, reg)} |")
            if v.get("carrier") == "1" and len(d["fdb"].get(p, [])) <= 3:  # edge port (not the 20-MAC trunk)
                for mac in d["fdb"].get(p, []):
                    for c in omada.get(mac, [])[:1]:
                        ip_by_mac[mac] = c["ip"]
        md.append("")
    findings = []
    ips = {}
    for mac, cl in omada.items():
        for c in cl:
            if c["ip"] != "-":
                ips.setdefault(c["ip"], set()).add(mac)
    for ip, macs in sorted(ips.items()):
        if len(macs) > 1:
            findings.append("(Omada list) " + classify_dup(ip, macs, reg))
    if not a.no_probe and ip_by_mac:
        nic = bench_nic()
        pr = probe(ip_by_mac, nic)
        findings.append(f"two-way probe via {nic}: arping -b x{PROBES} per edge IP, replies per MAC:")
        for ip, cnt in pr.items():
            findings.append(f"  {ip}: " + (", ".join(f"{m}={n}/{PROBES}" for m, n in sorted(cnt.items())) or "no reply"))
            if len(cnt) > 1:
                findings.append("  (ARP) " + classify_dup(ip, set(cnt), reg))
    SNAP.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    for name, d in data.items():
        if "error" in d:
            continue
        if not a.no_diff:
            findings += diff(name, snapshot_state(d))
        (SNAP / f"{name}-{ts}.json").write_text(json.dumps(snapshot_state(d), indent=1))
    md += ["## Findings", ""] + [f"- {f}" for f in findings] + [""]
    (SNAP / "map-latest.md").write_text("\n".join(md))
    for ln in md + ["map saved: tmp/cabling/map-latest.md"]:
        log(ln)


if __name__ == "__main__":
    main()
