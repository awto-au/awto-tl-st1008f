#!/usr/bin/env python3
"""extract_console_excerpts — cut redacted, per-session excerpts from the console log into artifacts/.

Input: the console daemon's raw log (default private/serial/st1008-console.log, local only).
Output: artifacts/<name> text files. Line ranges below refer to that log as captured 2026-10-08.

Redaction (applied to every excerpt, then checked):
- `[daemon]` bookkeeping lines dropped; CR, NUL and backspace stripped. `[TX hh:mm:ss]` markers kept.
- MAC addresses, `Using MAC <hex>` and SFP `sn <serial>` replaced.
- --map OLD=NEW rewrites host-specific IPs (e.g. the switch and TFTP server addresses).
- Refuses to write if a host path (/mnt, /home) or an unmapped 192.168.x.y outside the
  U-Boot/OpenWrt defaults remains.

Usage:
    scripts/extract_console_excerpts.py --map <switch-lan-ip>=<switch-ip> --map <host-ip>=<tftp-server-ip> ...
Log: tmp/logs/extract_console_excerpts.log
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/extract_console_excerpts.log"
DEFAULT_SRC = ROOT / "private/serial/st1008-console.log"
OUT = ROOT / "artifacts"

# Factory defaults that are not host-specific: U-Boot env ipaddr/serverip, OpenWrt LAN.
ALLOWED_IPS = {"192.168.0.100", "192.168.0.145", "192.168.1.1"}


# name -> list of (first_line, last_line) inclusive, 1-based; str entries are inserted verbatim.
EXCERPTS: dict[str, list] = {
    "stock-boot-20261008.log": [(1, 141)],
    "uboot-version.txt": [(1433, 1439)],
    "uboot-printenv.txt": [(1440, 1455)],
    "uboot-help.txt": [(1456, 1523)],
    "uboot-help-rtk.txt": [(2399, 2457)],
    "uboot-flshow.txt": [(4898, 4922)],
    "uboot-10g-tftp-bootm-20261008.log": [
        "# One power-on, 2026-10-08 (TX times are +11:00). Gaps marked [...].",
        (2466, 2483), (2487, 2494), (2498, 2551), (2568, 2581),
        "[... PCA9534 enabled by GPIO bit-bang (scripts/st1008_pca9534.py), cage 1 only; lines elided ...]",
        (3505, 3514), (3527, 3558),
        "[... lines elided ...]",
        (3946, 3972), (3974, 3981),
        "[... cage 2 laser via bit-bang; tftpboot repeated on cage 2 (5383940 bytes); lines elided ...]",
        (4529, 4579),
        "[... serial flash-dump experiments; lines elided ...]",
        (4961, 5013),
    ],
    "openwrt-25.12.4-ramboot-20261008.log": [(5014, 5281), (5310, 5317)],
    "openwrt-proc-mtd.txt": [(5310, 5316)],
    "stock-rdinit-sh-test-20261008.log": [(5762, 5960)],
}

MAC_RE = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
USING_MAC_RE = re.compile(r"(Using MAC )[0-9a-fA-F]{12,16}")
SFP_SN_RE = re.compile(r"(\bsn )\S+")
IP_RE = re.compile(r"\b192\.168\.\d{1,3}\.\d{1,3}\b")
CTRL_RE = re.compile(r"[\x00\x08\r]")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def clean(line: str, ip_map: dict[str, str]) -> str | None:
    if line.startswith("[daemon]"):
        return None
    line = CTRL_RE.sub("", line)
    line = MAC_RE.sub("xx:xx:xx:xx:xx:xx", line)
    line = USING_MAC_RE.sub(r"\1<redacted>", line)
    line = SFP_SN_RE.sub(r"\1<redacted>", line)
    for old, new in ip_map.items():
        line = line.replace(old, new)
    return line


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--src", type=Path, default=DEFAULT_SRC)
    ap.add_argument("--map", action="append", default=[], metavar="OLD=NEW")
    args = ap.parse_args()
    ip_map = dict(m.split("=", 1) for m in args.map)

    lines = args.src.read_bytes().decode("latin-1").split("\n")
    OUT.mkdir(exist_ok=True)
    bad = 0
    for name, parts in EXCERPTS.items():
        out: list[str] = []
        for part in parts:
            if isinstance(part, str):
                out.append(part)
                continue
            first, last = part
            for raw in lines[first - 1:last]:
                c = clean(raw, ip_map)
                if c is not None:
                    out.append(c)
        text = "\n".join(out).rstrip() + "\n"
        leaks = [ip for ip in IP_RE.findall(text) if ip not in ALLOWED_IPS]
        if "/mnt/" in text or "/home/" in text or leaks:
            log(f"REFUSED {name}: host path or unmapped IPs {sorted(set(leaks))}")
            bad += 1
            continue
        (OUT / name).write_text(text)
        log(f"wrote artifacts/{name}: {len(out)} lines")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
