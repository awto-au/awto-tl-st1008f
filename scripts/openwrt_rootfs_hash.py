#!/usr/bin/env python3
"""openwrt_rootfs_hash — read every file of the running flash OpenWrt's squashfs root, hash it (#50, #52).

- One aggregate md5 over `md5sum` of every file under /bin /sbin /lib /usr (sorted), plus the
  SQUASHFS error count from dmesg. Stored as tmp/rootfs-hash/<label>.json.
- Compare runs taken under different clock/controller settings: any setting that corrupts flash
  or DRAM reads changes the hash or raises errors. Log: tmp/logs/openwrt_rootfs_hash.log
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import OW_PROMPT, ROOT, Console  # noqa: E402

LOG = ROOT / "tmp/logs/openwrt_rootfs_hash.log"
OUT = ROOT / "tmp/rootfs-hash"
HASH = "find $D -type f | sort | xargs md5sum | md5sum"  # < 60 chars (BusyBox echo)


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("label")
    ap.add_argument("--against", help="label of a previous run that must match")
    a = ap.parse_args()
    con = Console()
    con.run("dmesg -n 1", OW_PROMPT, 1, "quiet")
    con.run("D='/bin /sbin /lib /usr'", OW_PROMPT, 1, "dirs")
    # ~310 files, few MB from squashfs: measured 1.8 s at stock SPI; x1.25 + slack for slower settings
    _, out = con.run(HASH, r"\n([0-9a-f]{32})\s+-\r?\n" + OW_PROMPT, 10, "rootfs hash")
    h = re.search(r"\n([0-9a-f]{32})\s+-\r?\n", out).group(1)
    _, out = con.run("dmesg | grep -c SQUASHFS", r"\n(\d+)\r?\n" + OW_PROMPT, 2, "squashfs errors")
    errs = int(re.search(r"\n(\d+)\r?\n", out).group(1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{a.label}.json").write_text(json.dumps({"label": a.label, "hash": h, "squashfs_errors": errs}))
    ok = errs == 0
    msg = f"{a.label}: rootfs hash {h}, SQUASHFS errors {errs}"
    if a.against:
        ref = json.loads((OUT / f"{a.against}.json").read_text())
        ok = ok and ref["hash"] == h
        msg += f"; vs {a.against} {ref['hash']}: {'same' if ref['hash'] == h else 'DIFFERENT'}"
    log(f"{'PASS' if ok else 'FAIL'} {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
