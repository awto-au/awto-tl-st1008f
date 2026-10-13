#!/usr/bin/env python3
"""st1008_ramload — one command: power-cycle → stock U-Boot → TFTP an image → run it → check the boot log.

- Sequence: restart console daemon → software reboot from the current prompt (`restart_board`; relay power
  cycle only if the board does not answer) → wait for the daemon's autoboot catch → `rtk network on` (waits for its end marker) → light one
  cage → TFTP (verifies byte count) → `go`/`bootm` → capture until a done marker → boot_log_check.
- Every wait expects a console marker with a stated cap; expiry logs what was waited for.
- Images: `uboot-mainline` (go 0x81000000), `openwrt` / `openwrt-ours[-6.18]` (bootm 0x84f00000, bridge STP
  forced on), `mainline-kernel` (bootm;
  done = initramfs BusyBox prompt `st1008f-linux # `, scripts/mainline_initramfs.py).
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_guard  # noqa: E402  (#81)

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/st1008_ramload.log"
CONSOLE = ROOT / "private/serial/st1008-console.log"
SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "tio-st1008.daemon.sock"
from boards import BENCH_CONSOLE  # noqa: E402
DEV = BENCH_CONSOLE
TFTP_ROOT = ROOT / "tmp/tftp"
# awto-dan docs/network/ip-registry.toml: st1008f-1-mgmt .48, selwyn-enp7s0 .30 (was .148/.147)
from boards import BENCH_IP  # noqa: E402  sw2 = bench unit
SWITCH_IP, SERVER_IP, SERVER_NIC = BENCH_IP, "192.168.25.30", "enp7s0"


def ensure_server_ip() -> None:
    """TFTP server address as a secondary on the host NIC; a host reboot drops it (2026-10-11)."""
    have = subprocess.run(["ip", "-br", "-4", "addr", "show", SERVER_NIC], capture_output=True,
                          text=True, timeout=2).stdout  # local netlink query, instant
    if f"{SERVER_IP}/" not in have:
        subprocess.run(["sudo", "-n", "ip", "addr", "add", f"{SERVER_IP}/24", "dev", SERVER_NIC],
                       check=True, timeout=5)  # local netlink; 5 s names a sudo prompt hang
        log(f"host {SERVER_NIC}: added {SERVER_IP}/24")

# OpenWrt console-ready line; a kernel printk can land anywhere inside it ("Please press Ent[ 12.6] procd: ...\n")
OW_READY = r"(?:\[[^\n]*\n)?".join(re.escape(c) for c in "Please press Enter to activate")

IMAGES = {
    # name: (file, load addr, start cmd, done marker, cap s)
    # caps: uboot-mainline reaches its prompt <1 s after go; OpenWrt shell ~25 s, ports ~75 s;
    # mainline kernel reached its VFS panic <3 s (pre-initramfs). Each cap ≈ 1.25x measured + margin.
    "uboot-mainline": ("uboot-mainline.bin", 0x81000000, "go", r"st1008f-mainline #", 5),
    "openwrt": ("openwrt-initramfs.bin", 0x84f00000, "bootm", OW_READY, 40),
    # local OpenWrt main builds (scripts/build_openwrt.py, #73): ours = 7.3 kernel, -6.18 = OpenWrt kernel
    # + backports. Same STP enforcement as `openwrt`.
    "openwrt-ours": ("openwrt-ours-initramfs.bin", 0x84f00000, "bootm", OW_READY, 40),
    "openwrt-ours-6.18": ("openwrt-ours-6.18-initramfs.bin", 0x84f00000, "bootm",
                          OW_READY, 40),
    "mainline-kernel": ("mainline.bin", 0x84f00000, "bootm",
                        r"st1008f-linux # ", 10),
}
FAIL_MARKERS = r"U-Boot 2011\.12|Kernel panic - not syncing|Oops|Unhandled exception|\$ra  "


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
        if cr:
            flash_guard.check_cmd(text)  # #81; the daemon re-checks whole lines (chunked typing)
        s = __import__("socket").socket(__import__("socket").AF_UNIX)
        s.settimeout(5)  # local unix socket; 5 s names a dead daemon
        s.connect(str(SOCK))
        data = base64.b64encode(text.encode() + (b"\r" if cr else b"")).decode()
        s.sendall((json.dumps({"op": "send", "data": data, "secs": 0.05}) + "\n").encode())
        s.recv(65536)
        s.close()

    def note(self, text: str) -> None:
        """Daemon log marker; `interactive-begin`/`-end` make boot_log_check skip the section."""
        s = __import__("socket").socket(__import__("socket").AF_UNIX)
        s.settimeout(5)  # local unix socket; 5 s names a dead daemon
        s.connect(str(SOCK))
        s.sendall((json.dumps({"op": "note", "text": text}) + "\n").encode())
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
        flash_guard.check_cmd(text)  # #81
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
            self.expect(r"st1008f-(mainline|linux) # |RTL9300# |root@[^:\s]*:[^#]*# ", 1, m,
                        "prompt after Ctrl-C")
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

    def run(self, cmd: str, pattern: str, cap: float, what: str, checked: bool = False) -> tuple[re.Match, str]:
        mark = self.size()
        if checked or len(cmd) > 60:  # long lines lose chars (#31): a lost digit once sent crc32 to kuseg -> trap
            self.send_checked(cmd)
        else:
            self.send(cmd)
        return self.expect(pattern, cap, mark, what)


def power(op: str) -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/switch_power.py"), op],
                       capture_output=True, text=True, timeout=30)  # 2 POSTs + 3 GETs 5 s each + 2 sw1 pings 0.7 s
    log(f"relay {op}: {r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr.strip()}")
    if r.returncode:
        raise SystemExit(f"relay {op} failed rc={r.returncode} (4 = relay powers sw1, #91): {r.stdout.strip()}")


def relay_check() -> int:
    """Relay rebooted since our power-on (comes up OFF, #84)? Power on once and say so."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts/switch_power.py"), "check", "--fix"],
                       capture_output=True, text=True, timeout=17)  # 2 GETs + 1 POST, 5 s cap each
    for ln in r.stdout.strip().splitlines():
        log(f"  {ln}")
    return r.returncode


def console_view() -> None:
    """Owner watches the console via the VS Code task 'ST1008 console' (.vscode/tasks.json)."""
    r = subprocess.run(["pgrep", "-a", "-f", "console_watch.py"], capture_output=True, text=True,
                       timeout=2)  # local process scan, instant
    log("console view: running" if "console_watch.py" in r.stdout else
        "console view NOT running: VS Code -> Run Task -> 'ST1008 console' (or reopen the folder)")


def restart_daemon(policy: str = "hold") -> None:
    subprocess.run(["pkill", "-f", "scripts/switch_console_daemon.py"], check=False)
    t0 = time.monotonic()
    while SOCK.exists() and time.monotonic() - t0 < 3:  # daemon unlinks its socket on SIGTERM
        time.sleep(0.05)
    out = open(ROOT / "tmp/logs/switch_console_daemon.out", "a")
    subprocess.Popen([sys.executable, str(ROOT / "scripts/switch_console_daemon.py"), "--dev", DEV,
                      "--baud", "115200", "--policy", policy], cwd=ROOT, stdout=out,
                     stderr=subprocess.STDOUT, start_new_session=True)
    t0 = time.monotonic()
    while not SOCK.exists():  # daemon binds within ~0.3 s
        if time.monotonic() - t0 > 3:
            raise SystemExit("TIMEOUT 3s: console daemon did not create its socket")
        time.sleep(0.05)
    log("console daemon restarted")


# owner rule 2026-10-13: reboot in software; the relay only when the board does not answer
PROMPTS = (  # (pattern of the prompt the board shows, reboot command)
    (r"st1008f-linux # $", "reboot -f"),          # mainline initramfs: /init is a shell, no init to signal
    (r"root@[^:\s]*:[^#\n]*# $", "reboot"),       # OpenWrt: clean shutdown (overlay)
    (r"st1008f-mainline # $", "reset"),            # our U-Boot
    (r"RTL9300#[ #]*$", "reset"),                  # stock U-Boot (its CR echo can add a "#")
)
PROBE_S = 1     # prompt redraw after a CR: one line at 115200, ms; 1 s names a hung / fast-baud console
SOFT_S = 12     # reboot -> stock banner: OpenWrt shutdown ~5 s (#105) + banner ~2.5 s; x1.25 + slack


def restart_board(con: Console, policy: str = "hold") -> int:
    """Software reboot from whatever prompt the board shows; relay power cycle only if it does not answer
    or no stock banner follows within SOFT_S. Returns the log mark before the reboot (callers expect from it,
    boot_ok=True). The daemon restarts first (policy; a power cut stalls the PL2303 RX)."""
    restart_daemon(policy)
    mark = con.size()
    con.send("", cr=True)
    t0, cmd, tail = time.monotonic(), None, ""
    while cmd is None and time.monotonic() - t0 < PROBE_S:
        tail = con.echo_since(mark).rstrip("\r\n").split("\n")[-1] + " "
        cmd = next((c for pat, c in PROMPTS if re.search(pat, tail.rstrip() + " ")), None)
        time.sleep(0.05)  # poll the log; a prompt line arrives in ~ms
    if cmd:
        mark = con.size()
        con.send(cmd)
        try:
            con.expect(r"U-Boot 2011\.12", SOFT_S, mark, f"software reboot ({cmd})", boot_ok=True)
            return mark
        except SystemExit as e:
            log(f"  software reboot gave no stock banner in {SOFT_S} s ({e}); relay power cycle")
    else:
        log(f"  no known prompt within {PROBE_S} s (last: {tail.strip()[-60:]!r}); relay power cycle")
    power("off")
    restart_daemon(policy)
    time.sleep(2.0)  # rail discharge before power-on (relay off->on in <1 s left a half-reset)
    mark = con.size()
    power("on")
    return mark


def to_stock_uboot(con: Console) -> None:
    mark = restart_board(con)
    # banner ~2.5 s after power-on, daemon catches autoboot within its 1 s countdown: cap 8 s
    con.expect(r"\[daemon\] at RTL9300#", 8, mark, "stock U-Boot prompt (autoboot caught)", boot_ok=True)


def network_on(con: Console, prompt: str = "RTL9300#") -> str:
    # measured ~9 s (PHY init); ends with the benign Err:0xf030 (#28) then the prompt. Cap 15 s.
    # Ours (same sequence) prints the same end line; any extra line (SerDes errors) fails the match.
    _, out = con.run("rtk network on", rf"Err:0xf030:FAIL \(0xf030\)\s*\r?\n{prompt}", 15, "rtk network on")
    return out


def laser(con: Console, cage: int, prompt: str = "RTL9300#") -> None:
    mask = 0xFF & ~(1 << (cage - 1))
    m, _ = con.run(f"rtk i2c write 8 1 0x{mask:02x}; rtk i2c write 8 3 0; rtk i2c read 8 1",
                   rf"data 0x([0-9a-f]+)\s*\r?\n{prompt}", 2, f"laser cage {cage} only")
    if int(m.group(1), 16) != mask:
        raise SystemExit(f"laser readback 0x{m.group(1)} != 0x{mask:02x}")


CAGE_PORT = (0, 8, 16, 20, 24, 25, 26, 27)  # cage 1-8 -> SDK port (docs/hardware.md)


def ports_only(con: Console, cage: int) -> None:
    """Stock `rtk network on` forwards front<->front; copper modules (GLC-T, AQR113C) ignore laser
    TX-disable, so one lit cage is not enough (storms 2026-10-12, #100). Admin-disable every other cage
    port; ours re-enables them behind its CPU-only isolation (board_late_init)."""
    cmd = "; ".join(f"rtk port disable {p}" for c, p in enumerate(CAGE_PORT, 1) if c != cage)
    con.run(cmd, r"(?s)(Disable port \(0,\d+\).*){7}RTL9300#", 3, f"ports: cage {cage} only")


def tftp(con: Console, fname: str, addr: int, retransmits: int = 1) -> None:
    ensure_server_ip()
    size = (TFTP_ROOT / fname).stat().st_size
    srv = subprocess.Popen(["sudo", "-n", sys.executable, str(ROOT / "scripts/tftpd.py"), "--once"],
                           cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # first block always times out once after link-up (`*T`, stock TFTP retransmit = 5 s), then
        # ~1.2 MB/s. Cap = 5 s retransmit + 1.25x transfer + 3 s setup.
        cap = 5 * retransmits + size / 1.2e6 * 1.25 + 3
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


OW_PROMPT = r"root@[^:\s]*:[^#]*# "  # hostname is "(none)" early in boot


def openwrt_stp(con: Console) -> None:
    """Bridge STP on as soon as the shell is up: the initramfs bridges every port with every
    laser lit, no STP (#19). A loop ramps slowly (~13k pps at +80 s), so this is in time."""
    con.run("", OW_PROMPT, 3, "OpenWrt shell")  # 'Please press Enter'; prompt within ~1 s
    # kernel lines (SerDes calibration) interleave with replies and broke the check 2026-10-10
    # checked: right after the login banner the first char was dropped ('mesg: not found', 2026-10-11)
    con.run("dmesg -n 1", OW_PROMPT, 1, "console loglevel 1", checked=True)
    # bridge appears when netifd runs (~27 s uptime; shell is up at ~14 s): wait ON the board,
    # set STP within 1 s of it existing. First-boot dropbear keygen delays rc S19/S20 (network): bridge seen
    # 14-35 s after the shell (2026-10-12, #73); cap 45 s = 35 s x 1.25. No bridge = no loop while waiting.
    con.run("B=/sys/class/net/switch/bridge", OW_PROMPT, 1, "bridge path")
    try:
        con.run("until [ -d $B ];do sleep 1;done;echo 1 >$B/stp_state", OW_PROMPT, 45, "stp on")
        con.run("cat $B/stp_state", r"\n1\r?\n" + OW_PROMPT, 1, "stp_state = 1")
        # 2 s (sysfs unit 1/100 s) = bridge minimum: ports forward ~4 s after STP on, not 2 x 8 s
        con.run("echo 200 >$B/forward_delay", OW_PROMPT, 1, "forward_delay 2 s", checked=True)
    except SystemExit:
        con.send("\x03")
        con.send("for p in /sys/class/net/lan*; do ip link set ${p##*/} down; done")
        # lasers' ports are down: record why there is no bridge (console log), then cut power
        for cmd in ("uptime", "ls /sys/class/net", "pgrep -l netifd", "uci -q show network | head -40",
                    "logread | grep -v kern | tail -25"):
            try:
                con.run(cmd, OW_PROMPT, 3, f"diag: {cmd[:24]}")  # local shell output <1 s; 3 s names a hang
            except SystemExit:
                break
        power("off")
        raise SystemExit("FAIL: bridge STP not enabled in 45 s: lan* down + relay off (#19)")
    # BusyBox wraps lines > 60 chars and breaks the echo check: short commands
    con.run("S=network.switch", OW_PROMPT, 1, "uci section", checked=True)
    con.run("uci set $S.stp='1'; uci set $S.forward_delay='2'", OW_PROMPT, 1, "stp uci", checked=True)
    con.run("uci commit network; sync", OW_PROMPT, 2, "stp persistent", checked=True)
    log("  OpenWrt bridge STP on")


FAST_CPU_E208 = "0x3a8"  # 1000 MHz with DIVN2 /3: uboot-test 40/40 + 15 min Linux load (#38)
SFCR, SFCR_D_FAST = 0xB8001200, 0  # SPI = NOR clock / 2
E220, NOR_CODE_FAST = 0xBB00E220, 3  # NOR 245 MHz -> SPI 122.5 MHz (rated 133); 153 MHz corrupts (#32)


def set_spi(con: Console, d: int, code: int) -> None:
    """SFCR[31:29] = D (SPI = NOR / 2(D+1)), e220[16:13] = NOR code (NOR = 2450 / 2(code+2) MHz)."""
    p = r"st1008f-mainline # "
    _, out = con.run(f"md.l {SFCR:x} 1", r"b8001200: ([0-9a-f]{8})[^\n]*\r?\n" + p, 1, "SFCR")
    v = int(re.search(r"b8001200: ([0-9a-f]{8})", out).group(1), 16)
    con.run(f"mw.l {SFCR:x} {(v & 0x1fffffff) | (d << 29):08x}", p, 1, f"SFCR D={d}")
    _, out = con.run(f"md.l {E220:x} 1", r"bb00e220: ([0-9a-f]{8})[^\n]*\r?\n" + p, 1, "e220")
    v = int(re.search(r"bb00e220: ([0-9a-f]{8})", out).group(1), 16)
    con.run(f"mw.l {E220:x} {(v & ~(0xF << 13)) | (code << 13):08x}", p, 1, f"NOR code {code}")
    log(f"  spi {2450 / (2 * (code + 2)) / (2 * (d + 1)):.1f} MHz (D={d}, NOR code {code})")


def fast_clocks(con: Console, e208: str, spi: bool = True) -> None:
    con.note("interactive-begin")  # command output, not boot output (boot_log_check skips it)
    con.run(f"clocks set cpu {e208} 0x6b439e13 0 force",
            r"clocks: locked after \d+ us[^\r\n]*\r?\nst1008f-mainline # ", 2, f"cpu pll {e208}")
    if not spi:
        _, out = con.run("clocks", r"(?s)mem \d+ MHz.*st1008f-mainline # ", 1, "clocks")
        con.note("interactive-end")
        log("  " + ", ".join(re.findall(r"^(?:cpu|spi) [\d.]+ MHz", out, re.M)))
        return
    _, out = con.run(f"md.l {SFCR:x} 1", r"b8001200: ([0-9a-f]{8})[^\n]*\r?\nst1008f-mainline # ", 1,
                     "SFCR")
    v = int(re.search(r"b8001200: ([0-9a-f]{8})", out).group(1), 16)
    con.run(f"mw.l {SFCR:x} {(v & 0x1fffffff) | (SFCR_D_FAST << 29):08x}", r"st1008f-mainline # ", 1,
            "SPI /2")
    _, out = con.run(f"md.l {E220:x} 1", r"bb00e220: ([0-9a-f]{8})[^\n]*\r?\nst1008f-mainline # ", 1,
                     "e220")
    v = int(re.search(r"bb00e220: ([0-9a-f]{8})", out).group(1), 16)
    con.run(f"mw.l {E220:x} {(v & ~(0xF << 13)) | (NOR_CODE_FAST << 13):08x}", r"st1008f-mainline # ",
            1, "NOR 245 MHz")
    _, out = con.run("clocks", r"(?s)mem \d+ MHz.*st1008f-mainline # ", 1, "clocks")
    con.note("interactive-end")
    log("  " + ", ".join(re.findall(r"^(?:cpu|spi) [\d.]+ MHz", out, re.M)))


def linkcheck_gate(ours: bool) -> None:
    """`linkcheck.py --boot` (power cycle into ours, `rtk linkcheck`); refuse LOOP always, MULTI unless
    the image is ours (`openwrt-ours*`: st1008f-linkcheck turns STP on before netifd) (#97)."""
    r = subprocess.run([sys.executable, str(ROOT / "scripts/linkcheck.py"), "--boot"],
                       timeout=150)  # ramload ours ~25 s + check 14 s cap; x1.25 + relay latency
    if r.returncode == 3 and ours:
        log("linkcheck MULTI: allowed, image enforces STP before bridging (st1008f-linkcheck)")
        return
    if r.returncode:
        raise SystemExit(f"linkcheck rc {r.returncode} (3 MULTI, 4 LOOP): OpenWrt boot refused (#97)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("image", choices=sorted(IMAGES) + ["stock"],
                    help="`stock` = stop at the caught stock prompt (+ rtk network on)")
    ap.add_argument("--cage", type=int, default=1, help="the ONE cage to light for TFTP (cage-loop hazard)")
    ap.add_argument("--no-cycle", action="store_true", help="already at the stock RTL9300# prompt")
    ap.add_argument("--fast", type=int, nargs="?", const=1, metavar="DIV",
                    help="uboot-mainline: switch console to 10.9375 MBd/DIV after boot (default 1)")
    ap.add_argument("--from-flash", action="store_true",
                    help="uboot-mainline: copy ours from flash jffs2-log instead of TFTP; no `rtk network on` "
                         "(switch DMA idle, lasers dark; needed for mem-clock, #39)")
    ap.add_argument("--chain-test", action="store_true",
                    help="uboot-mainline: write the chainload marker before go (as stock bootcmd will, #47): "
                         "ours must autoboot flash OpenWrt")
    ap.add_argument("--stock-clocks", action="store_true",
                    help="uboot-mainline: keep stock CPU 800 MHz + SPI 25.5 MHz (default: 1 GHz + SPI 122.5 MHz)")
    ap.add_argument("--spi", metavar="D:CODE",
                    help="with --then: SPI before bootm, SFCR D (0 = /2) and NOR code e220[16:13] (6 = stock)")
    ap.add_argument("--then", choices=["openwrt", "openwrt-ours", "openwrt-ours-6.18", "mainline-kernel"],
                    help="uboot-mainline: also TFTP that image (std magic) to 0x84f00000, bootm it from ours "
                         "(after `clocks fast`)")
    ap.add_argument("--cpu", metavar="E208",
                    help="uboot-mainline: CPU e208 for /3 (default 0x3a8 = 1000 MHz; docs/CLOCKS.md)")
    ap.add_argument("--no-network", action="store_true", help="rtk network on already done this boot")
    ap.add_argument("--pre", action="append", default=[], metavar="CMD",
                    help="with --then: our U-Boot command(s) run before bootm, in order (e.g. clock picks, #103)")
    ap.add_argument("--no-linkcheck", action="store_true",
                    help="skip the pre-OpenWrt live-link/loop check (`rtk linkcheck`, #97)")
    ap.add_argument("--bootargs", metavar="ARGS",
                    help="with --then: U-Boot bootargs before bootm, e.g. 'st1008f.mode=m2 st1008f.boot=primary'")
    a = ap.parse_args()

    log(f"=== ramload {a.image}, cage {a.cage}")
    console_view()
    ow_boot = a.image.startswith("openwrt") or (a.then or "").startswith("openwrt") or a.chain_test
    if ow_boot and a.image != "uboot-mainline" and not a.no_linkcheck:
        linkcheck_gate(a.image.startswith("openwrt-ours"))  # own boot of ours; OpenWrt bridges (#97)
    con = Console()
    if not a.no_cycle:
        to_stock_uboot(con)
    if a.from_flash:
        if a.image != "uboot-mainline":
            raise SystemExit("--from-flash is for uboot-mainline only")
        # slot copy + stock CRC check (#105) at stock clocks < 0.2 s; cap 2 s
        from uboot_chain_image import stock_check_cmd  # late: keeps this module's imports light
        _, out = con.run(f"cp.b 0x94200000 0x81000000 0x80000; {stock_check_cmd()}",
                         r"(Total of 1 word|word at 0x)[\s\S]*?RTL9300# ", 2, "jffs2-log slot check")
        if "Total of 1 word" not in out:
            raise SystemExit("FAIL: jffs2-log slot CRC mismatch (old raw image or corrupt): "
                             "./dev.py uboot-chain-install --overwrite")
        con.run("go 0x81000000", IMAGES[a.image][3], 3, "uboot-mainline from flash (no network)")  # banner < 1 s
        if not a.stock_clocks:
            fast_clocks(con, a.cpu or FAST_CPU_E208)
        return 0
    if not a.no_network:
        network_on(con)
    if a.no_network and a.image == "stock":
        return 0  # rtk i2c before `rtk network on` hangs the console: no laser mask yet
    laser(con, a.cage)
    ports_only(con, a.cage)
    if a.image == "stock":
        return 0
    fname, addr, start, done, cap = IMAGES[a.image]
    if a.then:
        src = TFTP_ROOT / IMAGES[a.then][0]
        std = src.with_name(src.stem + "-std.bin")
        subprocess.run([sys.executable, str(ROOT / "scripts/uimage_std_magic.py"), str(src), str(std)],
                       check=True, timeout=10)  # local 5 MB rewrite, <1 s
        tftp(con, std.name, IMAGES[a.then][1])
    tftp(con, fname, addr)
    if a.chain_test:
        con.run("mw.l 0xa0f80000 0xa5a51008", r"RTL9300# ", 1, "chainload marker")
        con.run(f"go 0x{addr:08x}", OW_READY, 60, "autoboot -> flash OpenWrt")
        openwrt_stp(con)
        return 0
    con.run(f"{start} 0x{addr:08x}", done, cap, f"{a.image} running")
    if a.image.startswith("openwrt"):
        openwrt_stp(con)
    r = subprocess.run([sys.executable, str(ROOT / "scripts/boot_log_check.py"), "--boot", "-1"],
                       capture_output=True, text=True, timeout=30)  # local file scan, <2 s
    sys.stdout.write(r.stdout)
    log(f"boot_log_check exit {r.returncode} ({['CLEAN', 'UNKNOWN', 'ERRORS'][min(r.returncode, 2)]})")
    if a.image == "uboot-mainline" and not a.stock_clocks:
        # fast SPI only when Linux will not run: under Linux it corrupted squashfs reads (#50)
        fast_clocks(con, a.cpu or FAST_CPU_E208, spi=not (a.then or a.chain_test))
    if a.then and a.spi:
        d, code = (int(x) for x in a.spi.split(":"))
        set_spi(con, d, code)
    for cmd in a.pre if a.then else []:
        # a clock change: SRAM routine < 1 ms + ~4 KB of log at 115200 (0.4 s); x5 for LX/UART changes
        con.run(cmd, r"st1008f-mainline # ", 3, f"pre: {cmd[:40]}")
    if (a.then or "").startswith("openwrt") and not a.no_linkcheck:
        from linkcheck import run as linkcheck_run  # late: linkcheck imports this module
        verdict, live, _ = linkcheck_run(con)
        if verdict == "LOOP" or (verdict == "MULTI" and not a.then.startswith("openwrt-ours")):
            raise SystemExit(f"linkcheck {verdict}: {live} live link(s) or a loop; RAM OpenWrt bridges "
                             "without STP until openwrt_stp -> refused (#97)")
    if a.then:
        ow = IMAGES[a.then]
        if a.bootargs:  # appended to the DT bootargs by DTB_EXTEND kernels (OpenWrt-on-7.3, #73)
            con.run(f"setenv bootargs {a.bootargs}", r"st1008f-mainline # ", 1, "bootargs")
        # memtest=N: kernel early pattern test of lowmem, ~2.2 s per pattern at stock (#103); x1.25 + boot cap
        mt = re.search(r"\bmemtest=(\d+)", a.bootargs or "")
        cap = ow[4] + (3 * int(mt[1]) if mt else 0)
        con.run(f"bootm 0x{ow[1]:08x}", ow[3], cap, f"{a.then} via mainline bootm")
        if a.then.startswith("openwrt"):
            openwrt_stp(con)
        r = subprocess.run([sys.executable, str(ROOT / "scripts/boot_log_check.py"), "--boot", "-1"],
                           capture_output=True, text=True, timeout=30)  # local file scan, <2 s
        sys.stdout.write(r.stdout)
        log(f"boot_log_check exit {r.returncode}")
        return r.returncode
    if a.fast and a.image == "uboot-mainline":
        from serial_speed_test import go_fast  # imports this module; late import avoids a cycle
        go_fast(con, a.fast)
    return r.returncode


if __name__ == "__main__":
    try:
        rc = main()
    except SystemExit as e:  # FAIL paths raise: a relay reboot (#84) is the first thing to rule out
        rc = e.code
    relay_check()  # flow end, >= 60 s after power-on for kernel/OpenWrt flows: a relay reboot shows here
    sys.exit(rc)
