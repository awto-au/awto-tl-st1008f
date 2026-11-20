#!/usr/bin/env python3
"""iperf_hwloop — line-rate iperf3 from selwyn through sw2, hardware-switched out lan3 -> cable -> lan6 and back (owner OK 2026-11-21, #182).

Path (all L2, no sw2 CPU forwarding): selwyn enp8s0.991 (netns hl, 10.98.0.1) -> sw1 lan5 -> sw1 lan4 -> DAC -> sw2 lan1
  -> VLAN 991 access on lan3 -> fibre -> lan6 VLAN 992 access -> sw2 lan1 -> sw1 -> enp8s0.992 (netns hr, 10.98.0.2).
- Uses the existing bench VLANs 991/992 (tagged on sw1 lan4/lan5/lan6, docs/NAT-OPS.md); sw1 VLANs unchanged.
- Kernel loop detect (#111) is switched OFF on BOTH switches for the run: sw1 sees its own probe come back on lan4 through the
  cable (991 -> 992) and shuts lan4, the DAC to sw2 (the cause of the mgmt loss in #182). Restored with `loop on` + `unshut`.
- sw2 runtime changes: lan1 tagged 991,992; lan3 access 991; lan6 access 992 (VLAN 1 removed); bridge STP off.
  VLANs are set AFTER both ports are up and settled: netifd re-adds lan6 (uci port) to the bridge on link-up and resets its VLANs.
- Watchdogs on both switches revert everything at +WATCHDOG_S unless disarmed (flag file), so a lost ssh self-heals; the sw2
  restore also falls back to the console (short lines: the console drops input past ~240 chars).
- Host netns hl/hr need sudo; vlan ifaces get distinct MACs (the bridge must not hairpin to the same MAC).
- Aborts if enp8s0.991 or netns hl/hr exist (nat_bench in use).
- Log: tmp/logs/iperf_hwloop.log. Caps: iperf run DUR + 15 s; link wait 15 s; WATCHDOG_S 150 (4 runs x (DUR+~3) + setup).

Usage: python3 scripts/iperf_hwloop.py [--dur 10] [--udp-mbit 1000] [--sw2 IP] [--sw1 IP] [--host-nic enp8s0]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/iperf_hwloop.log"
SSH = ["ssh", "-o", "ConnectTimeout=3", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
       "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR"]
WATCHDOG_S = 150
DBG = "/sys/kernel/debug/rtl838x/storm"
UNDO_SW2 = ["ip link set lan3 down; ip link set lan6 down",
            "bridge vlan del dev lan3 vid 991; bridge vlan del dev lan6 vid 992",
            "bridge vlan del dev lan1 vid 991; bridge vlan del dev lan1 vid 992",
            "bridge vlan add dev lan3 vid 1 pvid untagged; bridge vlan add dev lan6 vid 1 pvid untagged",
            "ip link set switch type bridge stp_state 1",
            f"echo 'loop on' > {DBG}; echo unshut > {DBG}",
            "ip link set lan3 up; ip link set lan6 up"]
UNDO_SW1 = [f"echo 'loop on' > {DBG}; echo unshut > {DBG}"]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh(ip: str, cmd: str, cap: float = 30) -> str:
    try:
        r = subprocess.run([*SSH, f"root@{ip}", cmd], capture_output=True, text=True, timeout=cap)
    except subprocess.TimeoutExpired:
        return "ssh: timed out"
    return (r.stdout + r.stderr).strip()


def host(cmd: str, cap: float = 60) -> str:
    try:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=cap)
    except subprocess.TimeoutExpired:
        return "host cmd timed out"
    return (r.stdout + r.stderr).strip()


def cpu_stat(text: str) -> dict[str, tuple[int, int]]:
    """{cpuN: (busy, total)} from /proc/stat text."""
    out = {}
    for ln in text.splitlines():
        f = ln.split()
        if f and f[0].startswith("cpu") and f[0] != "cpu" and len(f) > 8:
            v = [int(x) for x in f[1:9]]
            out[f[0]] = (sum(v) - v[3] - v[4], sum(v))
    return out


def cpu_pct(a: dict, b: dict) -> str:
    return " ".join(f"{k}={100 * (b[k][0] - a[k][0]) / max(1, b[k][1] - a[k][1]):.0f}%" for k in sorted(a) if k in b)


def snap(a) -> dict:
    sw2 = ssh(a.sw2, "cat /proc/stat; echo ==; grep -E 'eth0' /proc/interrupts; echo ==; "
                     "for n in lan1 lan3 lan6; do ethtool -S $n | sed \"s/^ */$n /\"; done", 15)
    cnt = {}
    for ln in sw2.split("==")[-1].splitlines():
        f = ln.split(":")
        if len(f) == 2 and any(k in f[0] for k in ("iscard", "rop", "ause", "rror", "verflow")):
            try:
                cnt[f[0].strip()] = int(f[1])
            except ValueError:
                pass
    irq = sw2.split("==")[1].split()[1:3] if "==" in sw2 else []
    return {"t": time.monotonic(), "host": cpu_stat(open("/proc/stat").read()), "sw2": cpu_stat(sw2.split("==")[0]), "cnt": cnt,
            "irq": [int(x) for x in irq if x.isdigit()]}


def report(name: str, x: dict, y: dict) -> None:
    d = {k: y["cnt"][k] - x["cnt"].get(k, 0) for k in y["cnt"] if y["cnt"][k] != x["cnt"].get(k, 0)}
    irq = [b - a for a, b in zip(x["irq"], y["irq"])]
    log(f"{name} load: host {cpu_pct(x['host'], y['host'])} | sw2 {cpu_pct(x['sw2'], y['sw2'])} eth0-irq/CPU {irq} | counter deltas {d}")


def watchdog(ip: str, lines: list[str], tag: str) -> str:
    """Arm an on-box revert: runs at +WATCHDOG_S unless /tmp/wd_<tag> was removed (disarm)."""
    script = "\\n".join(lines)
    return ssh(ip, f"mkfifo /tmp/wf 2>/dev/null; printf '{script}\\n' > /tmp/revert_{tag}.sh; touch /tmp/wd_{tag}; d=$(( $(cut -d. -f1 /proc/uptime) + {WATCHDOG_S} )); "
                   f"( while [ -e /tmp/wd_{tag} ] && [ $(cut -d. -f1 /proc/uptime) -lt $d ]; do read -t 2 z <>/tmp/wf; done; "
                   f"[ -e /tmp/wd_{tag} ] && sh /tmp/revert_{tag}.sh ) </dev/null >/dev/null 2>&1 & echo armed-until-uptime=$d")


def restore(ip: str, lines: list[str], name: str, console: bool) -> None:
    out = ssh(ip, "; ".join(lines), 25)
    log(f"{name} restore: {out}")
    if console and (out.startswith("ssh:") or "timed out" in out):
        log(f"{name} ssh lost; restoring over the console")
        for ln in lines:
            subprocess.run([sys.executable, str(ROOT / "scripts/switch_console.py"), "send", ln], capture_output=True, timeout=30)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dur", type=int, default=10)
    ap.add_argument("--udp-mbit", type=int, default=1000)
    ap.add_argument("--sw2", default="192.168.25.56")
    ap.add_argument("--sw1", default="192.168.25.48")
    ap.add_argument("--host-nic", default="enp8s0")
    ap.add_argument("--only", default="", help="comma list of run names to execute (default: all)")
    a = ap.parse_args()
    nic = a.host_nic
    if subprocess.run(["ip", "link", "show", f"{nic}.991"], capture_output=True).returncode == 0:
        log(f"ABORT: {nic}.991 exists (nat_bench in use?)")
        return 1
    if {"hl", "hr"} & set(host("ip netns list").split()):
        log("ABORT: netns hl/hr already exist")
        return 1
    subprocess.run([sys.executable, str(ROOT / "dev.py"), "switch-check"], capture_output=True, timeout=90)  # starts the storm guard
    try:
        log("watchdog sw2: " + watchdog(a.sw2, UNDO_SW2, "sw2"))
        log("watchdog sw1: " + watchdog(a.sw1, UNDO_SW1, "sw1"))
        log("loop detect off: sw1 " + ssh(a.sw1, f"echo 'loop off' > {DBG}; grep -o 'loop: [a-z]*' {DBG}") +
            ", sw2 " + ssh(a.sw2, f"echo 'loop off' > {DBG}; ip link set switch type bridge stp_state 0; grep -o 'loop: [a-z]*' {DBG}"))
        log("ports up: " + ssh(a.sw2,
            "ip link set lan3 up; ip link set lan6 up; ethtool -s lan3 autoneg on; ethtool -s lan6 autoneg on; "
            "i=0; while [ $i -lt 150 ]; do [ \"$(cat /sys/class/net/lan3/carrier)\" = 1 ] && [ \"$(cat /sys/class/net/lan6/carrier)\" = 1 ] && break; i=$((i+1)); read -t 0.1 z <>/tmp/wf; done; "
            "read -t 3 z <>/tmp/wf; echo iters=$i lan3=$(cat /sys/class/net/lan3/carrier) lan6=$(cat /sys/class/net/lan6/carrier)"))
        log("vlans: " + ssh(a.sw2,
            "bridge vlan add dev lan1 vid 991; bridge vlan add dev lan1 vid 992; bridge vlan del dev lan3 vid 1; bridge vlan del dev lan6 vid 1; "
            "bridge vlan add dev lan3 vid 991 pvid untagged; bridge vlan add dev lan6 vid 992 pvid untagged; "
            "bridge vlan show | grep -A2 -E '^(lan1|lan3|lan6)' | tr -s ' ' | tr '\\n' ';'"))
        log("host setup: " + host(
            f"sudo ip netns add hl && sudo ip netns add hr && "
            f"sudo ip link add link {nic} name {nic}.991 type vlan id 991 && sudo ip link add link {nic} name {nic}.992 type vlan id 992 && "
            f"sudo ip link set {nic}.991 address 02:00:00:99:01:01 && sudo ip link set {nic}.992 address 02:00:00:99:02:02 && "
            f"sudo ip link set {nic}.991 netns hl && sudo ip link set {nic}.992 netns hr && "
            f"sudo ip -n hl addr add 10.98.0.1/24 dev {nic}.991 && sudo ip -n hr addr add 10.98.0.2/24 dev {nic}.992 && "
            f"sudo ip -n hl link set {nic}.991 up && sudo ip -n hr link set {nic}.992 up && echo ok"))
        log("ping: " + host("sudo ip netns exec hl ping -c 3 -W 1 10.98.0.2 | tail -2"))
        host("sudo ip netns exec hr iperf3 -s -D; sudo ip netns exec hl iperf3 -s -p 5202 -D")
        grep = "grep -E 'sender|receiver|SUM|error|refused' | tail -6"
        runs = {
            "tcp-fwd": f"sudo ip netns exec hl iperf3 -c 10.98.0.2 -t {a.dur} -f m 2>&1 | {grep}",
            "tcp-rev": f"sudo ip netns exec hl iperf3 -c 10.98.0.2 -R -t {a.dur} -f m 2>&1 | {grep}",
            "tcp-bidir": f"sudo ip netns exec hl iperf3 -c 10.98.0.2 --bidir -t {a.dur} -f m 2>&1 | {grep}",
            "tcp-bidir-P2": f"sudo ip netns exec hl iperf3 -c 10.98.0.2 --bidir -P 2 -t {a.dur} -f m 2>&1 | {grep}",
            # two single-direction iperf3 processes at once (no --bidir): separates iperf3 from the network
            "tcp-bidir-paced": f"sudo ip netns exec hl iperf3 -c 10.98.0.2 --bidir -b 900M -t {a.dur} -f m 2>&1 | {grep}",
            "tcp-dual": (f"(sudo ip netns exec hl iperf3 -c 10.98.0.2 -t {a.dur} -f m 2>&1 | {grep} | sed 's/^/A /') & "
                         f"(sudo ip netns exec hr iperf3 -c 10.98.0.1 -p 5202 -t {a.dur} -f m 2>&1 | {grep} | sed 's/^/B /') & wait"),
            "udp-fwd": f"sudo ip netns exec hl iperf3 -c 10.98.0.2 -u -b {a.udp_mbit}M -t {a.dur} -f m 2>&1 | {grep}",
        }
        want = [w for w in a.only.split(",") if w] or list(runs)
        for name in want:
            x = snap(a)
            out = host(runs[name], a.dur + 20)
            y = snap(a)
            log(f"{name}: {out}")
            report(name, x, y)
        log("sw2 lan3/lan6: " + ssh(a.sw2, "for n in lan3 lan6; do echo $n $(ip -s link show $n | tail -4 | tr -s ' ' | tr '\\n' ';'); done"))
    finally:
        host("sudo killall iperf3 2>/dev/null; true")
        log("host restore: " + host(f"sudo ip netns del hl 2>/dev/null; sudo ip netns del hr 2>/dev/null; sudo ip link del {nic}.991 2>/dev/null; sudo ip link del {nic}.992 2>/dev/null; true"))
        restore(a.sw2, UNDO_SW2, "sw2", True)
        restore(a.sw1, UNDO_SW1, "sw1", False)
        for ip, tag in ((a.sw2, "sw2"), (a.sw1, "sw1")):
            ssh(ip, f"rm -f /tmp/wd_{tag}", 10)  # disarm the watchdog
    return 0


if __name__ == "__main__":
    sys.exit(main())
