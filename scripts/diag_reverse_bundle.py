#!/usr/bin/env python3
"""diag_reverse_bundle — build a grepable static-analysis bundle for an ELF
(default: stock `diag`) so the network/shell question can be settled by grep +
Ghidra instead of guesswork.

Emits into an output dir (default private/diag-analysis/<name>/):
  elf-header.txt     readelf -h -d
  dynsyms.txt        readelf -W --dyn-syms   (the import table)
  relocs.txt         readelf -W -r           (PLT targets = who gets called)
  strings.txt        strings -a -t x         (offset-tagged, grepable)
  net-shell.txt      grep of dynsyms+relocs for socket/bind/listen/accept/
                     connect/setsockopt/dup2/exec*/fork/system/popen + a
                     raw-MIPS-syscall note (o32 numbers) for the Ghidra pass
Static only; never executes the target. Output is under private/ (gitignored).

Usage: diag_reverse_bundle.py [elf] [out_dir]
Log: tmp/logs/diag_reverse_bundle.log
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/diag_reverse_bundle.log"
DEFAULT_ELF = (ROOT / "private/mtd-backup-20261008-145913/stock-extract/"
               "initramfs-1/bin/diag")
TIMEOUT = 120  # binutils on a 2.4 MB ELF is ~1 s; 120 s = ample, fails loud.

NET_SHELL = ["socket", "bind", "listen", "accept", "accept4", "connect",
             "setsockopt", "getsockname", "recv", "recvfrom", "send", "sendto",
             "dup", "dup2", "execve", "execv", "execl", "execlp", "execvp",
             "fork", "vfork", "system", "popen", "openpty", "forkpty"]
# MIPS o32 direct syscall numbers — for a Ghidra raw-syscall scan (li v0,<n>).
MIPS_O32 = {"socket": 4183, "bind": 4169, "connect": 4170, "listen": 4174,
            "accept": 4168, "setsockopt": 4181, "execve": 4011, "fork": 4002}


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def run(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=TIMEOUT, check=False)
    except FileNotFoundError:
        log(f"  missing tool: {cmd[0]}")
        return ""
    except subprocess.TimeoutExpired:
        log(f"  TIMEOUT ({TIMEOUT}s): {' '.join(cmd)}")
        return ""
    return r.stdout + r.stderr


def main() -> int:
    elf = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ELF
    out = (Path(sys.argv[2]) if len(sys.argv) > 2
           else ROOT / "private/diag-analysis" / elf.name)
    log(f"=== diag_reverse_bundle {time.strftime('%Y-%m-%dT%H:%M:%S%z')} ===")
    log(f"elf: {elf}")
    if not elf.is_file():
        log("ERROR: ELF not found; pass a path.")
        return 2
    out.mkdir(parents=True, exist_ok=True)
    log(f"out: {out}")

    dumps = {
        "elf-header.txt": ["readelf", "-h", "-d", str(elf)],
        "dynsyms.txt": ["readelf", "-W", "--dyn-syms", str(elf)],
        "relocs.txt": ["readelf", "-W", "-r", str(elf)],
        "strings.txt": ["strings", "-a", "-t", "x", str(elf)],
    }
    text = {}
    for name, cmd in dumps.items():
        t = run(cmd)
        (out / name).write_text(t)
        text[name] = t
        log(f"  wrote {name} ({len(t.splitlines())} lines)")

    syms = text["dynsyms.txt"] + text["relocs.txt"]
    present = [a for a in NET_SHELL
               if any(a == ln.split("@")[0].split()[-1]
                      for ln in syms.splitlines() if ln.split())]
    ns = [f"net/shell libc imports present: {present or '-'}", "",
          "MIPS o32 raw-syscall numbers to scan for in Ghidra (li v0,<n> then",
          "`syscall`) — a hit would mean networking bypassing the libc PLT:"]
    ns += [f"  {k:12} __NR_{k} = {v}" for k, v in MIPS_O32.items()]
    verdict = ("LISTENER" if {"bind", "listen", "accept", "accept4"} & set(present)
               else "CLIENT/connect" if "connect" in present
               else "no inbound socket API via libc")
    ns += ["", f"verdict (libc imports): {verdict}"]
    (out / "net-shell.txt").write_text("\n".join(ns) + "\n")
    log("  wrote net-shell.txt")
    log(f"VERDICT (libc imports): {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
