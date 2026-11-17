#!/usr/bin/env python3
"""uboot_netboot — stop our U-Boot's power-up network window over UDP and boot an image from RAM, no UART (#80).

Needs the stock env `st1008f_netwin=CAGE,IP,HOST` (`./dev.py uboot-chain-env netwin set CAGE,IP,HOST --ssh --ip IP`)
and the U-Boot chain slot with bootsel.c `netwin`. Flow:
  reboot (ssh | relay | you) -> ESC datagrams to UDP :6666 every 0.1 s -> prompt seen on the wire
  -> [turbo PROFILE] -> setenv bootargs -> TFTP (tftpd.py --once) -> bootm.
No flash write, no trial/attempt state: a power cycle returns to the normal boot (window skipped if netwin is unset).
Log: tmp/logs/uboot_netboot.log
"""

import argparse
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import st1008_ramload as rl  # noqa: E402  (TFTP_ROOT, SERVER_IP, ensure_server_ip)
from boards import BENCH_IP  # noqa: E402

LOG = ROOT / "tmp/logs/uboot_netboot.log"
NC_PORT = 6666                 # U-Boot netconsole in/out port
PROMPT = "st1008f-mainline # "
ESC_PERIOD_S = 0.1             # a datagram before U-Boot's stack is up is lost; 10/s lands one within 0.1 s of it
# reboot -> prompt: ssh shutdown ~6 s + stock U-Boot ~8 s + ours ~2 s + netwin <= 17 s + window 2 s = 35 s, x1.25 + 15
PROMPT_CAP_S = 60
CMD_CAP_S = 5                  # one U-Boot command echo over UDP: ms; 5 s names a lost datagram
LOAD_ADDR = 0x84F00000         # TFTP area (docs/UBOOT-MAINLINE.md)
BOOT_CAP_S = 90                # kernel up on the LAN after bootm: ramload caps OpenWrt at 40 s, plain ~3 s + port-up


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


class Wire:
    """U-Boot's netconsole output, read off the wire: the host firewall drops UDP :6666 before a socket sees it."""

    def __init__(self, nic: str, unit_ip: str):
        self.buf = ""
        self.lock = threading.Lock()
        self.proc = subprocess.Popen(
            ["sudo", "-n", "tcpdump", "-l", "-U", "-nn", "-i", nic, "-A", "udp", "and", "src", "host", unit_ip,
             "and", "src", "port", str(NC_PORT)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, errors="replace")
        self.t = threading.Thread(target=self._read, daemon=True)
        self.t.start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            with self.lock:
                self.buf += line

    def mark(self) -> int:
        with self.lock:
            return len(self.buf)

    def wait(self, pattern: str, cap: float, since: int = 0, on_poll=None):
        end = time.monotonic() + cap
        while time.monotonic() < end:
            with self.lock:
                m = re.search(pattern, self.buf[since:])
            if m:
                return m
            if on_poll:
                on_poll()
            threading.Event().wait(0.02)
        return None

    def text(self, since: int = 0) -> str:
        with self.lock:
            return self.buf[since:]

    def close(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def reboot(how: str, ip: str) -> None:
    if how == "ssh":
        log(f"reboot: ssh root@{ip} reboot")
        subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", f"root@{ip}", "reboot"],
                       timeout=15, check=False)
    elif how == "relay":
        log("reboot: relay power cycle")
        rc = subprocess.call([sys.executable, str(ROOT / "scripts/switch_power.py"), "cycle"], timeout=60)
        if rc:
            raise SystemExit(f"relay cycle failed rc {rc}")
    else:
        log("reboot: power-cycle the unit now (waiting)")


def send(sock: socket.socket, ip: str, text: str) -> None:
    sock.sendto(text.encode(), (ip, NC_PORT))


def run_cmd(sock, wire: Wire, ip: str, cmd: str, expect: str, cap: float, what: str):
    since = wire.mark()
    send(sock, ip, cmd + "\n")
    m = wire.wait(expect, cap, since)
    if not m:
        raise SystemExit(f"{what}: no {expect!r} in {cap:.0f} s after {cmd!r}; wire: {wire.text(since)[-400:]!r}")
    return m


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", help="file in tmp/tftp (Realtek or std magic; our bootm takes both)")
    ap.add_argument("--ip", default=BENCH_IP, help="unit IP = the IP in st1008f_netwin")
    ap.add_argument("--reboot", choices=["ssh", "relay", "none"], default="ssh")
    ap.add_argument("--turbo", help="U-Boot `turbo` args at the prompt, e.g. cpu=1325,ddr=662,sram=500,swcore=608")
    ap.add_argument("--bootargs", default="st1008f.boot=net", help="kernel args (st1008f.boot= triggers the plain init's port-up)")
    ap.add_argument("--no-check", action="store_true", help="skip the st1008f_netwin read-back over ssh")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; no network or board access")
    a = ap.parse_args()

    fname = a.image
    src = rl.TFTP_ROOT / fname
    plan = [f"reboot via {a.reboot}", f"ESC -> UDP {a.ip}:{NC_PORT} every {ESC_PERIOD_S} s until {PROMPT!r} (cap {PROMPT_CAP_S} s)"]
    if a.turbo:
        plan.append(f"turbo {a.turbo}")
    plan += [f"setenv bootargs {a.bootargs}", f"tftpboot 0x{LOAD_ADDR:08x} {fname}", f"bootm 0x{LOAD_ADDR:08x}",
             f"wait for {a.ip} ping (cap {BOOT_CAP_S} s)"]
    if a.dry_run:
        print("\n".join(plan))
        return 0
    if not src.is_file():
        raise SystemExit(f"{src} missing")
    size = src.stat().st_size
    log(f"=== netboot {fname} ({size} B) -> {a.ip}")
    if a.reboot == "ssh" and not a.no_check:
        out = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", f"root@{a.ip}",
                              "fw_printenv st1008f_netwin"], capture_output=True, text=True, timeout=15).stdout
        if "st1008f_netwin=" not in out:
            raise SystemExit("st1008f_netwin is not set on the unit: ./dev.py uboot-chain-env netwin set CAGE,IP,HOST --ssh --ip IP")
        log(f"unit env: {out.strip()}")
    rl.ensure_server_ip()
    wire = Wire(rl.SERVER_NIC, a.ip)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        reboot(a.reboot, a.ip)
        t0 = time.monotonic()
        last = [0.0]

        def esc():
            now = time.monotonic()
            if now - last[0] >= ESC_PERIOD_S:
                send(sock, a.ip, "\x1b")
                last[0] = now
        if not wire.wait(re.escape(PROMPT), PROMPT_CAP_S, 0, on_poll=esc):
            seen = wire.text()
            raise SystemExit(f"no U-Boot prompt in {PROMPT_CAP_S} s; netconsole output seen: {len(seen)} B "
                             f"({'window up, ESC not accepted: stdin nc?' if seen.strip() else 'nothing: netwin not running / no link'})")
        log(f"prompt after {time.monotonic() - t0:.1f} s")
        if a.turbo:
            run_cmd(sock, wire, a.ip, f"turbo {a.turbo}", r"clocks: turbo (OK|reverted)[^\n]*", 30, "turbo")
        run_cmd(sock, wire, a.ip, f"setenv bootargs {a.bootargs}", re.escape(PROMPT), CMD_CAP_S, "bootargs")
        srv = subprocess.Popen(["sudo", "-n", sys.executable, str(ROOT / "scripts/tftpd.py"), "--once"], cwd=ROOT,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # first block times out once after link-up (stock TFTP retransmit 5 s), then ~1.2 MB/s (ramload tftp())
            cap = 5 + size / 1.2e6 * 1.25 + 3
            m = run_cmd(sock, wire, a.ip, f"setenv ipaddr {a.ip}; setenv serverip {rl.SERVER_IP}; "
                        f"tftpboot 0x{LOAD_ADDR:08x} {fname}", r"Bytes transferred = (\d+) \(", cap, "tftp")
            if int(m.group(1)) != size:
                raise SystemExit(f"tftp size {m.group(1)} != file {size}")
        finally:
            try:
                srv.wait(timeout=3)
            except subprocess.TimeoutExpired:
                subprocess.run(["sudo", "-n", "kill", "-TERM", str(srv.pid)], check=False, timeout=5)
        log(f"tftp ok {size} B; bootm")
        send(sock, a.ip, f"bootm 0x{LOAD_ADDR:08x}\n")
        end = time.monotonic() + BOOT_CAP_S
        while time.monotonic() < end:
            if subprocess.run(["ping", "-c1", "-W1", a.ip], capture_output=True).returncode == 0:
                log(f"{a.ip} answers ping {time.monotonic() - t0:.0f} s after the reboot")
                return 0
        raise SystemExit(f"{a.ip} did not answer ping in {BOOT_CAP_S} s after bootm")
    finally:
        sock.close()
        wire.close()


if __name__ == "__main__":
    sys.exit(main())
