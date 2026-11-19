#!/usr/bin/env python3
"""uboot_netboot — stop our U-Boot's power-up network window over UDP and boot an image from RAM, no UART (#80).

Needs the unit's mode slider in M2 and the U-Boot chain slot with bootsel.c `netwin` (no setting): U-Boot lights the
cage 1 on 192.168.1.1; the host answers from a 192.168.1.2/24 alias. Flow:
  reboot (ssh | relay | you) -> ESC datagrams to UDP :6666 every 0.1 s -> prompt seen on the wire
  -> [turbo PROFILE] -> setenv bootargs -> TFTP (tftpd.py --once) -> bootm.
No flash write, no trial/attempt state: a power cycle returns to the normal boot (the window runs only in M2).
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
UBOOT_IP = "192.168.1.1"       # bootsel.c NETWIN_IP
HOST_IP = "192.168.1.2"        # host alias on the server NIC, same /24
PROMPT = "st1008f-mainline # "
ESC_PERIOD_S = 0.1             # a datagram before U-Boot's stack is up is lost; 10/s lands one within 0.1 s of it
# reboot -> prompt (#178): peer link up +65 s after an ssh reboot + STP 4 s = ~70 s, x1.25 = 90 s. Expiry: exit 1, bytes seen
PROMPT_CAP_S = 90
CMD_CAP_S = 5                  # one U-Boot command echo over UDP: ms; 5 s names a lost datagram
SSH_REBOOT_WAIT_S = 6          # ssh ConnectTimeout 5 s + 1: a connect failure shows within this; a live reboot hangs the session
TFTPD_READY_CAP_S = 3          # sudo + python start ~0.5 s measured 2026-11-19, x6; expiry: exit, log path named
LOAD_ADDR = 0x84F00000         # TFTP area (docs/UBOOT-MAINLINE.md)
BOOT_CAP_S = 90                # kernel up on the LAN after bootm: ramload caps OpenWrt at 40 s, plain ~3 s + port-up
PLAIN_UP_CAP_S = 40            # bootm -> plain kernel prompt: 22 s measured 2026-11-19 (console log), x1.25 + 12


def ensure_host_ip() -> None:
    """192.168.1.2/24 on the server NIC for U-Boot's fixed 192.168.1.1; a host reboot drops it."""
    have = subprocess.run(["ip", "-br", "-4", "addr", "show", rl.SERVER_NIC], capture_output=True,
                          text=True, timeout=2).stdout  # local netlink query, instant
    if f"{HOST_IP}/" not in have:
        subprocess.run(["sudo", "-n", "ip", "addr", "add", f"{HOST_IP}/24", "dev", rl.SERVER_NIC],
                       check=True, timeout=5)  # local netlink; 5 s names a sudo prompt hang
        log(f"host {rl.SERVER_NIC}: added {HOST_IP}/24")
    # enp8s0 is in no zone: default zone drops TFTP :69 from 192.168.1.1; runtime only, gone at firewall reload (owner OK 2026-11-19)
    net = f"{HOST_IP.rsplit('.', 1)[0]}.0/24"
    q = subprocess.run(["sudo", "-n", "firewall-cmd", "--zone=trusted", f"--query-source={net}"],
                       capture_output=True, text=True, timeout=5)  # local dbus call: ms; 5 s names a hang
    if q.stdout.strip() != "yes":
        subprocess.run(["sudo", "-n", "firewall-cmd", "--zone=trusted", f"--add-source={net}"],
                       check=True, timeout=5)
        log(f"host firewall: {net} added to zone trusted (runtime)")


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
        # OpenWrt and the plain kernel have different dropbear keys on the same IP: no host-key check (bench LAN, as the other bench scripts)
        p = subprocess.Popen(["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
                              "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR", f"root@{ip}",
                              "sync; reboot -f"],  # the plain kernel ignores a bare `reboot` (no init); sync = flush an OpenWrt overlay first
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        try:
            _, err = p.communicate(timeout=SSH_REBOOT_WAIT_S)
        except subprocess.TimeoutExpired:
            return  # connected and the session hangs while the box goes down: rebooting; ESC spam starts now
        if any(s in err for s in ("timed out", "No route", "refused", "Permission denied")):
            raise SystemExit(f"ssh reboot of {ip} failed, nothing rebooted: {err.strip()[-200:]}")
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
    ap.add_argument("--ip", default=BENCH_IP, help="unit IP once Linux is up (reboot over ssh, final ping); U-Boot itself is on " + UBOOT_IP)
    ap.add_argument("--reboot", choices=["ssh", "relay", "none"], default="ssh")
    ap.add_argument("--turbo", help="U-Boot `turbo` args at the prompt, e.g. cpu=1325,ddr=662,sram=500,swcore=608")
    ap.add_argument("--bootargs", default="st1008f.boot=net", help="kernel args")
    ap.add_argument("--port-up", type=int, metavar="CAGE", help="plain kernel only: after bootm wait for its console prompt and `port-up CAGE IP/24` (needs the console daemon); an OpenWrt image brings its own network up")
    ap.add_argument("--dry-run", action="store_true", help="print the plan; no network or board access")
    a = ap.parse_args()

    fname = a.image
    src = rl.TFTP_ROOT / fname
    plan = [f"reboot via {a.reboot}", f"ESC -> UDP {UBOOT_IP}:{NC_PORT} every {ESC_PERIOD_S} s until {PROMPT!r} (cap {PROMPT_CAP_S} s)"]
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
    rl.ensure_server_ip()
    ensure_host_ip()
    wire = Wire(rl.SERVER_NIC, UBOOT_IP)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        reboot(a.reboot, a.ip)
        t0 = time.monotonic()
        last = [0.0]

        def esc():
            now = time.monotonic()
            if now - last[0] >= ESC_PERIOD_S:
                send(sock, UBOOT_IP, "\x1b")
                last[0] = now
        if not wire.wait(re.escape(PROMPT), PROMPT_CAP_S, 0, on_poll=esc):
            seen = wire.text()
            raise SystemExit(f"no U-Boot prompt in {PROMPT_CAP_S} s; netconsole output seen: {len(seen)} B "
                             f"({'window up, ESC not accepted: stdin nc?' if seen.strip() else 'nothing: slider not in M2, or no link on cage 1'})")
        log(f"prompt after {time.monotonic() - t0:.1f} s")
        if a.turbo:
            run_cmd(sock, wire, UBOOT_IP, f"turbo {a.turbo}", r"clocks: turbo (OK|reverted)[^\n]*", 30, "turbo")
        run_cmd(sock, wire, UBOOT_IP, f"setenv bootargs {a.bootargs}", re.escape(PROMPT), CMD_CAP_S, "bootargs")
        tlog = ROOT / "tmp/logs/tftpd.log"
        before = tlog.stat().st_size if tlog.exists() else 0
        srv = subprocess.Popen(["sudo", "-n", sys.executable, str(ROOT / "scripts/tftpd.py"), "--once", "--bind", HOST_IP],
                               cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # sudo + python start ~0.5 s; until bound, the system tftp.socket (wildcard :69, other root) answers "File not found"
            ready = time.monotonic() + TFTPD_READY_CAP_S
            while not (tlog.exists() and tlog.stat().st_size > before and "tftpd on port" in tlog.read_text()[before:]):
                if time.monotonic() > ready:
                    raise SystemExit(f"tftpd.py not listening on {HOST_IP} in {TFTPD_READY_CAP_S} s; see {tlog}")
                time.sleep(0.02)  # poll the log: ~25 polls for the 0.5 s start
            # (the loop below sends the tftpboot only now)
            # first block times out once after link-up (stock TFTP retransmit 5 s), then ~1.2 MB/s (ramload tftp())
            cap = 5 + size / 1.2e6 * 1.25 + 3
            m = run_cmd(sock, wire, UBOOT_IP, f"setenv serverip {HOST_IP}; "
                        f"tftpboot 0x{LOAD_ADDR:08x} {fname}", r"Bytes transferred = (\d+) \(", cap, "tftp")
            if int(m.group(1)) != size:
                raise SystemExit(f"tftp size {m.group(1)} != file {size}")
        finally:
            try:
                srv.wait(timeout=3)
            except subprocess.TimeoutExpired:
                subprocess.run(["sudo", "-n", "kill", "-TERM", str(srv.pid)], check=False, timeout=5)
        log(f"tftp ok {size} B; bootm")
        con = mark = None
        if a.port_up:
            con = rl.Console()  # the daemon owns the UART; no daemon: this raises, nothing to fall back to
            mark = con.size()
        send(sock, UBOOT_IP, f"bootm 0x{LOAD_ADDR:08x}\n")
        if con:
            con.expect(rl.PLAIN_PROMPT, PLAIN_UP_CAP_S, mark, "plain kernel console prompt")
            rl.plain_mgmt(con, a.ip, a.port_up)
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
