#!/usr/bin/env python3
"""st1008_ramload — one command: power-cycle → stock U-Boot → TFTP an image → run it → check the boot log.

- Sequence: relay off → restart console daemon (a power cut stalls the PL2303 RX) → relay on →
  wait for the daemon's autoboot catch → `rtk network on` (waits for its end marker) → light one
  cage → TFTP (verifies byte count) → `go`/`bootm` → capture until a done marker → boot_log_check.
- Every wait expects a console marker with a stated cap; expiry logs what was waited for.
- Images: `uboot-mainline` (go 0x81000000), `openwrt` (bootm 0x84f00000), `mainline-kernel` (bootm).
- Log: tmp/logs/st1008_ramload.log. Read-only on flash: no saveenv/sf/upgrade ever sent.
"""

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/st1008_ramload.log"
CONSOLE = ROOT / "private/serial/st1008-console.log"
SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "tio-st1008.daemon.sock"
DEV = "/dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller-if00-port0"
TFTP_ROOT = ROOT / "tmp/tftp"
SWITCH_IP, SERVER_IP = "192.168.25.148", "192.168.25.147"

IMAGES = {
    # name: (file, load addr, start cmd, done marker, cap s)
    # caps: uboot-mainline reaches its prompt <1 s after go; OpenWrt shell ~25 s, ports ~75 s;
    # mainline kernel panics/prompts <3 s. Each cap ≈ 1.25x measured + margin for print time.
    "uboot-mainline": ("uboot-mainline.bin", 0x81000000, "go", r"st1008f-mainline #", 5),
    "openwrt": ("openwrt-initramfs.bin", 0x84f00000, "bootm", r"Please press Enter to activate", 40),
    "mainline-kernel": ("mainline.bin", 0x84f00000, "bootm",
                        r"end Kernel panic|Please press Enter|login:|/ # ", 10),
}
FAIL_MARKERS = r"U-Boot 2011\.12|Kernel panic - not syncing(?!: VFS)|Oops|Unhandled exception|\$ra  "


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


class Console:
    """Send through the daemon socket; read replies straight from the console log it writes."""

    def size(self) -> int:
        return CONSOLE.stat().st_size

    def send(self, text: str, cr: bool = True) -> None:
        s = __import__("socket").socket(__import__("socket").AF_UNIX)
        s.settimeout(5)  # local unix socket; 5 s names a dead daemon
        s.connect(str(SOCK))
        data = base64.b64encode(text.encode() + (b"\r" if cr else b"")).decode()
        s.sendall((json.dumps({"op": "send", "data": data, "secs": 0.05}) + "\n").encode())
        s.recv(65536)
        s.close()

    def echo_since(self, mark: int) -> str:
        """Board output after `mark`, minus the daemon's own [TX]/[daemon] annotation lines."""
        with CONSOLE.open("rb") as fh:
            fh.seek(mark)
            raw = fh.read().decode(errors="replace")
        return re.sub(r"\n\[(?:TX|daemon)[^\n]*\n", "", raw)

    def send_checked(self, text: str, chunk: int = 16, tries: int = 3) -> int:
        """Type `text` in chunks, wait for each chunk's echo, Enter only on an exact echo.
        Long lines lose characters on the way in (#31); a lost CR leaves U-Boot waiting.
        On a bad echo: Ctrl-C (U-Boot drops the line) and retry. Returns the mark before Enter."""
        for attempt in range(1, tries + 1):
            mark = self.size()
            for i in range(0, len(text), chunk):
                self.send(text[i:i + chunk], cr=False)
                want = text[:i + chunk]
                t0 = time.monotonic()
                # chunk echo at 115200 = 1.4 ms; daemon send pause 50 ms; 0.5 s names a lost char
                while not self.echo_since(mark).endswith(want[-chunk:]) and time.monotonic() - t0 < 0.5:
                    time.sleep(0.01)
            got = self.echo_since(mark)
            if got == text:
                enter = self.size()
                self.send("", cr=True)
                return enter
            log(f"  echo mismatch (try {attempt}/{tries}): {len(got)}/{len(text)} chars; Ctrl-C")
            m = self.size()
            self.send("\x03", cr=False)
            self.expect(r"st1008f-mainline # |RTL9300# ", 1, m, "prompt after Ctrl-C")
        raise SystemExit(f"FAIL: line echo wrong {tries}x: {text[:60]!r}...")

    def expect(self, pattern: str, cap: float, mark: int, what: str,
               boot_ok: bool = False) -> tuple[re.Match, str]:
        """Wait for `pattern` in log bytes after `mark`. Polls 50 ms (console line time ~5 ms).
        A stock banner fails every wait except the power-on one (`boot_ok`): it means a reset."""
        rx = re.compile(pattern)
        bad = re.compile(FAIL_MARKERS.replace(r"U-Boot 2011\.12|", "") if boot_ok else FAIL_MARKERS)
        t0 = time.monotonic()
        while True:
            with CONSOLE.open("rb") as fh:
                fh.seek(mark)
                new = fh.read().decode(errors="replace")
            if m := rx.search(new):
                log(f"  ok: {what} ({time.monotonic() - t0:.1f}s)")
                return m, new
            if b := bad.search(new):
                raise SystemExit(f"FAIL during {what}: '{b.group(0)}' seen; see {CONSOLE.name}")
            if time.monotonic() - t0 > cap:
                tail = new[-300:].replace("\n", " | ")
                raise SystemExit(f"TIMEOUT {cap}s waiting for {what} /{pattern}/; last: {tail}")
            time.sleep(0.05)

    def run(self, cmd: str, pattern: str, cap: float, what: str) -> tuple[re.Match, str]:
        mark = self.size()
        self.send(cmd)
        return self.expect(pattern, cap, mark, what)


def power(op: str) -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/switch_power.py"), op],
                       capture_output=True, text=True, timeout=12)  # 2 LAN POSTs, 5 s cap each
    log(f"relay {op}: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()}")


def restart_daemon() -> None:
    subprocess.run(["pkill", "-f", "scripts/switch_console_daemon.py"], check=False)
    t0 = time.monotonic()
    while SOCK.exists() and time.monotonic() - t0 < 3:  # daemon unlinks its socket on SIGTERM
        time.sleep(0.05)
    out = open(ROOT / "tmp/logs/switch_console_daemon.out", "a")
    subprocess.Popen([sys.executable, str(ROOT / "scripts/switch_console_daemon.py"), "--dev", DEV,
                      "--baud", "115200", "--policy", "hold"], cwd=ROOT, stdout=out,
                     stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.monotonic()
    while not SOCK.exists():  # daemon binds within ~0.3 s
        if time.monotonic() - t0 > 3:
            raise SystemExit("TIMEOUT 3s: console daemon did not create its socket")
        time.sleep(0.05)
    log("console daemon restarted")


def to_stock_uboot(con: Console) -> None:
    power("off")
    restart_daemon()
    time.sleep(2.0)  # rail discharge before power-on (relay off->on in <1 s left a half-reset)
    mark = con.size()
    power("on")
    # banner ~2.5 s after power-on, daemon catches autoboot within its 1 s countdown: cap 8 s
    con.expect(r"\[daemon\] at RTL9300#", 8, mark, "stock U-Boot prompt (autoboot caught)", boot_ok=True)


def network_on(con: Console) -> None:
    # measured ~9 s (PHY init); ends with the benign Err:0xf030 (#28) then the prompt. Cap 15 s.
    con.run("rtk network on", r"Err:0xf030:FAIL \(0xf030\)\s*\r?\nRTL9300#", 15, "rtk network on")


def laser(con: Console, cage: int) -> None:
    mask = 0xFF & ~(1 << (cage - 1))
    m, _ = con.run(f"rtk i2c write 8 1 0x{mask:02x}; rtk i2c write 8 3 0; rtk i2c read 8 1",
                   r"data 0x([0-9a-f]+)\s*\r?\nRTL9300#", 2, f"laser cage {cage} only")
    if int(m.group(1), 16) != mask:
        raise SystemExit(f"laser readback 0x{m.group(1)} != 0x{mask:02x}")


def tftp(con: Console, fname: str, addr: int) -> None:
    size = (TFTP_ROOT / fname).stat().st_size
    srv = subprocess.Popen(["sudo", "-n", sys.executable, str(ROOT / "scripts/tftpd.py"), "--once"],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # first block always times out once after link-up (`*T`, stock TFTP retransmit = 5 s), then
        # ~1.2 MB/s. Cap = 5 s retransmit + 1.25x transfer + 3 s setup.
        cap = 5 + size / 1.2e6 * 1.25 + 3
        m, _ = con.run(f"setenv ipaddr {SWITCH_IP}; setenv serverip {SERVER_IP}; "
                       f"tftpboot 0x{addr:08x} {fname}",
                       r"Bytes transferred = (\d+)", cap, f"tftp {fname} ({size} B)")
        if int(m.group(1)) != size:
            raise SystemExit(f"tftp size {m.group(1)} != file {size}")
    finally:
        try:
            srv.wait(timeout=3)  # --once exits after the transfer
        except subprocess.TimeoutExpired:  # killing sudo would orphan the root tftpd on :69
            subprocess.run(["sudo", "-n", "pkill", "-f", "scripts/tftpd.py"], check=False)
            srv.wait(timeout=3)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", choices=sorted(IMAGES) + ["stock"],
                    help="`stock` = stop at the caught stock prompt (+ rtk network on)")
    ap.add_argument("--cage", type=int, default=1, help="the ONE cage to light for TFTP (cage-loop hazard)")
    ap.add_argument("--no-cycle", action="store_true", help="already at the stock RTL9300# prompt")
    ap.add_argument("--fast", type=int, nargs="?", const=1, metavar="DIV",
                    help="uboot-mainline: switch console to 10.9375 MBd/DIV after boot (default 1)")
    ap.add_argument("--no-network", action="store_true", help="rtk network on already done this boot")
    a = ap.parse_args()

    log(f"=== ramload {a.image}, cage {a.cage}")
    con = Console()
    if not a.no_cycle:
        to_stock_uboot(con)
    if not a.no_network:
        network_on(con)
    laser(con, a.cage)
    if a.image == "stock":
        return 0
    fname, addr, start, done, cap = IMAGES[a.image]
    tftp(con, fname, addr)
    con.run(f"{start} 0x{addr:08x}", done, cap, f"{a.image} running")
    r = subprocess.run([sys.executable, str(ROOT / "scripts/boot_log_check.py"), "--boot", "-1"],
                       capture_output=True, text=True, timeout=30)  # local file scan, <2 s
    sys.stdout.write(r.stdout)
    log(f"boot_log_check exit {r.returncode} ({['CLEAN', 'UNKNOWN', 'ERRORS'][min(r.returncode, 2)]})")
    if a.fast and a.image == "uboot-mainline":
        from serial_speed_test import go_fast  # imports this module; late import avoids a cycle
        go_fast(con, a.fast)
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
