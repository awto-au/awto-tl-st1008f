#!/usr/bin/env python3
"""st1008_cpu_punt_probe — find the process that answers CPU-punted frames.

Hypothesis: on stock firmware the switch traps control/exception frames to the
CPU; whatever reads+REPLIES to them on the CPU port (eth0 @ 192.168.1.1) is a
usable interface. This sends trapped-class frames and logs every reply:
  - ARP who-has / ICMP echo  -> reply = the Linux kernel stack (expected).
  - LLDP / STP-BPDU / RLDP / Realtek 0x8899 -> any reply or unsolicited emit =
    a protocol RESPONDER/announcer on the CPU (the interface we want).
Also passively listens first for anything the switch emits unprompted.

Non-destructive: adds a SECONDARY ip (ip addr add, keeps existing), removes it
on exit. Raw AF_PACKET, so needs root (run with sudo). ONE switch port cabled
to <iface> (cage-loop hazard). Switch must be booted into STOCK firmware (rc
up, eth0 configured) or nothing is punted.

Usage: sudo scripts/st1008_cpu_punt_probe.py <iface> [--target 192.168.1.1] [--ip 192.168.1.2/24] [--listen 5]
Log: tmp/logs/st1008_cpu_punt_probe.log   Pcap: tmp/logs/cpu_punt_<iface>_<ts>.pcap
"""

from __future__ import annotations

import argparse
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/st1008_cpu_punt_probe.log"
ETH_P_ALL = 0x0003
# recv timeout per probe: LAN RTT is sub-ms; SDK slow-path (trap->CPU->reply)
# is still <100 ms. 2 s = ~20x worst case; on expiry => "no reply" (logged).
RECV_TMO = 2.0


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def mac_bytes(s: str) -> bytes:
    return bytes(int(x, 16) for x in s.split(":"))


def if_mac(iface: str) -> bytes:
    return mac_bytes(Path(f"/sys/class/net/{iface}/address").read_text().strip())


def cksum(data: bytes) -> int:
    if len(data) % 2:
        data += b"\0"
    s = sum(struct.unpack(f">{len(data)//2}H", data))
    s = (s >> 16) + (s & 0xFFFF)
    s += s >> 16
    return (~s) & 0xFFFF


def eth(dst: bytes, src: bytes, etype: int, payload: bytes) -> bytes:
    return dst + src + struct.pack(">H", etype) + payload


def summarize(frame: bytes) -> str:
    if len(frame) < 14:
        return f"runt {len(frame)}B"
    dst, src = frame[:6].hex(":"), frame[6:12].hex(":")
    et = int.from_bytes(frame[12:14], "big")
    names = {0x0806: "ARP", 0x0800: "IPv4", 0x86DD: "IPv6", 0x88CC: "LLDP",
             0x8899: "RTK/CPUTAG", 0x8809: "SlowProto/LACP", 0x88F7: "PTP",
             0x8100: "VLAN"}
    kind = names.get(et, f"0x{et:04x}")
    extra = ""
    if et == 0x0806 and len(frame) >= 42:
        op = int.from_bytes(frame[20:22], "big")
        extra = f" op={'reply' if op == 2 else 'req' if op == 1 else op}"
    if et == 0x0800 and len(frame) >= 34:
        proto = frame[23]
        extra = f" ipproto={proto}{' ICMP' if proto == 1 else ''}"
        if proto == 1 and len(frame) >= 35:
            extra += f" type={frame[34]}"
    return f"{src} -> {dst} {kind}{extra} ({len(frame)}B)"


def recv_until(sock: socket.socket, want_from: bytes | None, deadline: float,
               my_mac: bytes) -> list[bytes]:
    got = []
    while time.monotonic() < deadline:
        try:
            frame = sock.recv(65535)
        except socket.timeout:
            break
        if frame[6:12] == my_mac:   # ignore our own TX echoed back
            continue
        got.append(frame)
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("iface")
    ap.add_argument("--target", default="192.168.1.1")
    ap.add_argument("--ip", default="192.168.1.2/24")
    ap.add_argument("--listen", type=float, default=5.0,
                    help="passive listen seconds before active probes")
    a = ap.parse_args()
    log(f"=== cpu_punt_probe iface={a.iface} target={a.target} ===")

    my_mac = if_mac(a.iface)
    src_ip = a.ip.split("/")[0]
    tgt_ip = a.target
    added = False
    try:
        # secondary IP (keeps the existing house-LAN addr)
        r = subprocess.run(["ip", "addr", "add", a.ip, "dev", a.iface],
                           capture_output=True, text=True)
        if r.returncode == 0:
            added = True
            log(f"added {a.ip} on {a.iface} (secondary)")
        else:
            log(f"ip addr add note: {r.stderr.strip()} (continuing)")

        s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETH_P_ALL))
        s.bind((a.iface, 0))
        s.settimeout(RECV_TMO)

        # 1) passive: what does the switch emit unprompted?
        log(f"-- passive listen {a.listen}s (unsolicited emissions) --")
        for f in recv_until(s, None, time.monotonic() + a.listen, my_mac):
            log(f"  RX {summarize(f)}")

        bcast = b"\xff" * 6
        probes = []
        # 2) ARP who-has target  (expect kernel ARP reply -> reveals CPU MAC)
        arp = struct.pack(">HHBBH", 1, 0x0800, 6, 4, 1) + my_mac + \
            socket.inet_aton(src_ip) + b"\0" * 6 + socket.inet_aton(tgt_ip)
        probes.append(("ARP who-has " + tgt_ip, eth(bcast, my_mac, 0x0806, arp)))
        # 3) ICMP echo to target (expect kernel echo reply)
        icmp = struct.pack(">BBHHH", 8, 0, 0, 0x4242, 1) + b"punt-probe"
        icmp = icmp[:2] + struct.pack(">H", cksum(icmp)) + icmp[4:]
        ihl = struct.pack(">BBHHHBBH", 0x45, 0, 20 + len(icmp), 0, 0, 64, 1, 0) + \
            socket.inet_aton(src_ip) + socket.inet_aton(tgt_ip)
        ihl = ihl[:10] + struct.pack(">H", cksum(ihl)) + ihl[12:]
        # ICMP to the CPU needs its MAC; resolve from the ARP reply if we get one.
        probes.append(("ICMP echo " + tgt_ip, ("ARP_THEN_ICMP", ihl + icmp)))
        # 4) LLDP, 5) STP BPDU, 6) Realtek 0x8899 — listen for a responder
        probes.append(("LLDP multicast",
                       eth(mac_bytes("01:80:c2:00:00:0e"), my_mac, 0x88CC,
                           b"\x02\x07\x04" + my_mac + b"\x00\x00")))
        probes.append(("STP BPDU",
                       eth(mac_bytes("01:80:c2:00:00:00"), my_mac, 0x0026,
                           b"\x42\x42\x03" + b"\x00" * 32)))
        probes.append(("Realtek 0x8899 probe",
                       eth(bcast, my_mac, 0x8899, b"\x00" * 46)))

        cpu_mac = None
        for name, payload in probes:
            if isinstance(payload, tuple):  # ICMP needs resolved dst MAC
                if cpu_mac is None:
                    log(f"-- skip {name}: no CPU MAC (ARP unanswered) --")
                    continue
                payload = eth(cpu_mac, my_mac, 0x0800, payload[1])
            log(f"-- probe: {name} --")
            s.send(payload)
            replies = recv_until(s, None, time.monotonic() + RECV_TMO, my_mac)
            if not replies:
                log("   (no reply)")
            for f in replies:
                log(f"   REPLY {summarize(f)}")
                if f[12:14] == b"\x08\x06" and len(f) >= 42 and \
                   int.from_bytes(f[20:22], "big") == 2:
                    cpu_mac = f[6:12]
                    log(f"   => CPU MAC = {cpu_mac.hex(':')}")
        log("=== done ===")
        return 0
    finally:
        if added:
            subprocess.run(["ip", "addr", "del", a.ip, "dev", a.iface],
                          capture_output=True, text=True)
            log(f"removed {a.ip} from {a.iface}")


if __name__ == "__main__":
    sys.exit(main())
