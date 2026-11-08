#!/usr/bin/env python3
"""l3_offload_h: check h (docs/ROUTING-OFFLOAD-OPS.md, #59): martian DIPs must not be forwarded by the ASIC default rows.

- Needs the bench set up as by l3_offload_ab.py (netns natlan/natwan, offload params applied here: all 1).
- natlan sends raw UDP frames to the switch SVI MAC with DIP 127.0.0.2, 0.0.0.1, ::1; natwan sniffs. Control: DIP 10.99.2.2.
- PASS = control seen, no martian seen. Raw AF_PACKET (no scapy). sw2 only. Log tmp/logs/l3_offload_h.log.
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
sys.path.insert(0, str(ROOT / "scripts"))
from boards import BENCH_IP, SW1_IP  # noqa: E402
import nat_bench as nb  # noqa: E402

LOG = ROOT / "tmp/logs/l3_offload_h.log"
RX_WAIT_S = 4  # frames cross the ASIC in < 1 ms; 4 s covers rx start + 3 sends + margin
V4_DIPS = ["127.0.0.2", "0.0.0.1", nb.H_WAN]  # last = control
V6_DIPS = ["::1"]
SPORT, DPORT = 40000, 40001


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def csum(b: bytes) -> int:
    if len(b) % 2:
        b += b"\0"
    s = sum(struct.unpack(f"!{len(b) // 2}H", b))
    while s >> 16:
        s = (s & 0xFFFF) + (s >> 16)
    return ~s & 0xFFFF


def udp(payload: bytes) -> bytes:
    return struct.pack("!HHHH", SPORT, DPORT, 8 + len(payload), 0) + payload


def frame4(dmac: bytes, smac: bytes, src: str, dst: str) -> bytes:
    u = udp(b"l3h")
    ip = struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + len(u), 1, 0, 64, 17, 0, socket.inet_aton(src), socket.inet_aton(dst))
    ip = ip[:10] + struct.pack("!H", csum(ip)) + ip[12:]
    return dmac + smac + b"\x08\x00" + ip + u


def frame6(dmac: bytes, smac: bytes, src: str, dst: str) -> bytes:
    u = udp(b"l3h")
    s, d = socket.inet_pton(socket.AF_INET6, src), socket.inet_pton(socket.AF_INET6, dst)
    ck = csum(s + d + struct.pack("!IBBBB", len(u), 0, 0, 0, 17) + u) or 0xFFFF
    u = u[:6] + struct.pack("!H", ck) + u[8:]
    ip = struct.pack("!IHBB", 6 << 28, len(u), 17, 64) + s + d
    return dmac + smac + b"\x86\xdd" + ip + u


def inner_tx(nic: str, dmac: str) -> None:
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW)
    s.bind((nic, 0))
    smac = s.getsockname()[4]
    dm = bytes.fromhex(dmac.replace(":", ""))
    for d in V4_DIPS:
        s.send(frame4(dm, smac, nb.H_LAN, d))
    for d in V6_DIPS:
        s.send(frame6(dm, smac, nb.V6[nb.LAN_VID][1], d))
    print("tx done", flush=True)


def inner_rx(nic: str) -> None:
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(3))
    s.bind((nic, 0))
    s.settimeout(RX_WAIT_S)
    want4 = {socket.inet_aton(d): d for d in V4_DIPS}
    want6 = {socket.inet_pton(socket.AF_INET6, d): d for d in V6_DIPS}
    print("ready", flush=True)
    end = time.monotonic() + RX_WAIT_S
    while time.monotonic() < end:
        try:
            f = s.recv(2000)
        except socket.timeout:
            break
        et = f[12:14]
        if et == b"\x08\x00" and f[23] == 17 and f[30:34] in want4:
            print(f"seen {want4[f[30:34]]}", flush=True)
        elif et == b"\x86\xdd" and f[20] == 17 and f[38:54] in want6:
            print(f"seen {want6[f[38:54]]}", flush=True)
    print("rx done", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP)
    ap.add_argument("--inner", choices=["tx", "rx"], help=argparse.SUPPRESS)
    ap.add_argument("--nic", help=argparse.SUPPRESS)
    ap.add_argument("--dmac", help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.inner == "tx":
        inner_tx(a.nic, a.dmac)
        return 0
    if a.inner == "rx":
        inner_rx(a.nic)
        return 0
    if a.ip == SW1_IP or a.ip != BENCH_IP:
        print(f"refused: {a.ip} is not the bench unit sw2", file=sys.stderr)
        return 2
    nic_l, nic_w = f"{nb.HOST_NIC}.{nb.LAN_VID}", f"{nb.HOST_NIC}.{nb.WAN_VID}"
    nb.offload(1, 1, 1)
    me = [sys.executable, str(Path(__file__).resolve())]
    ns = lambda n, *c: ["sudo", "-n", "ip", "netns", "exec", n, *c]  # noqa: E731
    subprocess.run(ns(nb.NS_LAN, "ping", "-c", "1", "-W", "1", nb.H_WAN), capture_output=True, timeout=10)
    nei = subprocess.run(ns(nb.NS_LAN, "ip", "neigh", "show", nb.SW_LAN), capture_output=True, text=True, timeout=10).stdout.split()
    if "lladdr" not in nei:
        log(f"FAIL: no neighbour MAC for {nb.SW_LAN} in {nb.NS_LAN}: {nei}")
        return 1
    dmac = nei[nei.index("lladdr") + 1]
    log(f"h: switch SVI MAC {dmac}; DIPs {V4_DIPS + V6_DIPS} (last v4 is the control); offload params all 1")
    rx = subprocess.Popen(ns(nb.NS_WAN, *me, "--inner", "rx", "--nic", nic_w), stdout=subprocess.PIPE, text=True)
    if rx.stdout.readline().strip() != "ready":
        log("FAIL: sniffer did not start")
        return 1
    tx = subprocess.run(ns(nb.NS_LAN, *me, "--inner", "tx", "--nic", nic_l, "--dmac", dmac), capture_output=True, text=True, timeout=10)
    log(f"tx rc {tx.returncode} {tx.stdout.strip()} {tx.stderr.strip()[-200:]}")
    out, _ = rx.communicate(timeout=RX_WAIT_S + 3)
    seen = [ln.split()[1] for ln in out.splitlines() if ln.startswith("seen")]
    martians = [d for d in seen if d != nb.H_WAN]
    ok = nb.H_WAN in seen and not martians
    log(f"check h: {'PASS' if ok else 'FAIL'} (seen at natwan: {seen}; control seen={nb.H_WAN in seen}, martians seen={martians})")
    nb.offload(0, 0, 0)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
