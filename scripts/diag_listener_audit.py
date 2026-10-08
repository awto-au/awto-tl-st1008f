#!/usr/bin/env python3
"""diag_listener_audit — decide whether the stock `diag` binary is a network
*agent* (listens on a socket) or a console-only REPL.

Background: in the stock initramfs `/etc/rc` runs `/bin/diag` in the foreground
and it never returns, so diag is a continuously-running resident process by
design. "Running forever" is necessary but not sufficient for the agent theory
-- a REPL stuck on the fake /dev/console also runs forever. The ELF dynamic
import table separates the two: a listener MUST import bind/listen/accept; a
console REPL imports only read/write on fd 0/1.

Static only. Does NOT execute the target (it is MIPS32 BE, foreign-arch and
untrusted); it is read solely by readelf/nm/strings.

Usage:
    diag_listener_audit.py [path/to/diag]     # or set DIAG_BIN
Default path: $DIAG_BIN, else private/stock-initramfs/bin/diag.
Needs binutils (readelf, nm, strings). Log: tmp/logs/diag_listener_audit.log
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/diag_listener_audit.log"
TIMEOUT = 60  # binutils on a ~MB image is sub-second; fail fast if wedged.

# Dynamic-symbol imports that classify the binary.
LISTENER_API = ["bind", "listen", "accept", "accept4"]
SOCKET_API = ["socket", "setsockopt", "getsockname", "recv", "recvfrom",
              "send", "sendto", "connect"]
SHELL_API = ["dup2", "dup", "execve", "execv", "execvp", "execl", "execlp",
             "fork", "vfork", "forkpty", "openpty", "posix_spawn", "system",
             "grantpt", "unlockpt", "ptsname"]
CONSOLE_API = ["read", "write", "fgets", "fgetc", "getchar", "fputs"]

STRING_HINTS = [
    "telnet", "dropbear", "inetd", "listen", "0.0.0.0", "INADDR",
    "access_telnet", "/bin/sh", "/bin/cli", "login", "password",
    "shell", "port", "AF_INET", "SO_REUSEADDR",
]


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def run(cmd: list[str]) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True,
                             timeout=TIMEOUT, check=False)
    except FileNotFoundError:
        log(f"  (missing tool: {cmd[0]})")
        return ""
    except subprocess.TimeoutExpired:
        log(f"  (timeout: {' '.join(cmd)})")
        return ""
    return out.stdout + out.stderr


def dyn_symbols(path: Path) -> set[str]:
    """Imported dynamic symbol names, from readelf --dyn-syms (nm -D fallback)."""
    names: set[str] = set()
    text = run(["readelf", "-W", "--dyn-syms", str(path)])
    # columns: Num: Value Size Type Bind Vis Ndx Name[@ver]
    for line in text.splitlines():
        m = re.search(r"\s(\S+?)(?:@+\S+)?\s*$", line)
        if m and re.match(r"^\s*\d+:", line):
            names.add(m.group(1))
    if not names:
        for line in run(["nm", "-D", str(path)]).splitlines():
            parts = line.split()
            if parts:
                names.add(parts[-1])
    return {n for n in names if n and not n.startswith("_")} | names


def hits(names: set[str], api: list[str]) -> list[str]:
    return [a for a in api if a in names]


def main() -> int:
    arg = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("DIAG_BIN")
    path = Path(arg) if arg else ROOT / "private/stock-initramfs/bin/diag"
    log(f"=== diag_listener_audit {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ===")
    log(f"target: {path}")
    if not path.is_file():
        log(f"ERROR: not found. Pass the path or set DIAG_BIN "
            f"(unpack the stock initramfs first; it lives under private/).")
        return 2

    header = run(["readelf", "-h", str(path)])
    arch = re.search(r"Machine:\s*(.+)", header)
    endian = re.search(r"Data:\s*(.+)", header)
    etype = re.search(r"Type:\s*(.+)", header)
    log(f"ELF: type={etype.group(1).strip() if etype else '?'} "
        f"machine={arch.group(1).strip() if arch else '?'} "
        f"data={endian.group(1).strip() if endian else '?'}")
    if "DYN" not in header and "EXEC" not in header:
        log("WARNING: not an ELF executable/shared object; results may be empty.")

    names = dyn_symbols(path)
    log(f"dynamic symbols resolved: {len(names)}")

    listener = hits(names, LISTENER_API)
    socket_ = hits(names, SOCKET_API)
    shell = hits(names, SHELL_API)
    console = hits(names, CONSOLE_API)

    log(f"  listener API : {listener or '-'}")
    log(f"  socket  API : {socket_ or '-'}")
    log(f"  shell   API : {shell or '-'}")
    log(f"  console API : {console or '-'}")

    log("string hints:")
    strings_out = run(["strings", "-a", str(path)])
    for hint in STRING_HINTS:
        found = sorted({ln.strip() for ln in strings_out.splitlines()
                        if hint.lower() in ln.lower()})[:8]
        if found:
            log(f"  [{hint}] " + " | ".join(found))

    # Verdict.
    if listener:
        verdict = (f"LISTENER (network agent): imports {listener}. "
                   f"diag accepts socket connections -- the dead serial console "
                   f"is irrelevant. Next: Ghidra DiagSocketAudit for port + the "
                   f"config gate + the dup2/exec shell handoff.")
    elif "socket" in names or "connect" in names:
        verdict = ("SOCKET CLIENT only (no bind/listen/accept): diag talks out "
                   "but does not accept connections. Not an inbound console.")
    else:
        verdict = ("NO socket API: diag is console-only. The agent theory is out; "
                   "fall back to overlay-init / busybox telnetd.")
    log("VERDICT: " + verdict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
