#!/usr/bin/env python3
"""sync_sfp_core — vendor awto-sfp-core's src/sfp_core.[ch] into shared/sfp-core/ and check it for drift (#181).

- `stage`: copy the two files from the awto-sfp-core checkout (default /mnt/2tb/git/awto-sfp-core, or $SFP_CORE_REPO)
  and write shared/sfp-core/MANIFEST.txt (source commit, sha256 of each file). The copy is never edited here.
- `check`: fails if a vendored file differs from MANIFEST.txt (local edit) or, when the source checkout is present,
  from the source files (source moved on: run `stage`). Run from dev.py gate; works without the checkout.
- Built into U-Boot through SHARED_FILES in build_uboot_mainline.py (copied, never edited).
- Log: tmp/logs/sync_sfp_core.log
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DST = ROOT / "shared/sfp-core"
SRC = Path(os.environ.get("SFP_CORE_REPO", "/mnt/2tb/git/awto-sfp-core"))
FILES = ("sfp_core.c", "sfp_core.h")
LOG = ROOT / "tmp/logs/sync_sfp_core.log"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def manifest() -> dict[str, str]:
    out = {}
    m = DST / "MANIFEST.txt"
    if m.exists():
        for ln in m.read_text().splitlines():
            if ln.startswith("sha256 "):
                _, h, name = ln.split()
                out[name] = h
    return out


def stage() -> int:
    if not (SRC / "src/sfp_core.c").exists():
        sys.exit(f"FAIL: no awto-sfp-core checkout at {SRC} (set SFP_CORE_REPO)")
    commit = subprocess.run(["git", "-C", str(SRC), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "-C", str(SRC), "status", "--porcelain", "src"], capture_output=True, text=True).stdout.strip()
    if dirty:
        sys.exit("FAIL: awto-sfp-core src/ has uncommitted changes: commit and push it first")
    DST.mkdir(parents=True, exist_ok=True)
    lines = [f"source awto-au/awto-sfp-core {commit}"]
    for f in FILES:
        (DST / f).write_bytes((SRC / "src" / f).read_bytes())
        lines.append(f"sha256 {sha(DST / f)} {f}")
    (DST / "MANIFEST.txt").write_text("\n".join(lines) + "\n")
    log(f"staged {', '.join(FILES)} from {commit[:12]}")
    return 0


def check() -> int:
    man = manifest()
    bad = []
    for f in FILES:
        p = DST / f
        if not p.exists():
            bad.append(f"{f}: missing")
            continue
        if man.get(f) != sha(p):
            bad.append(f"{f}: differs from MANIFEST.txt (edited here?)")
        s = SRC / "src" / f
        if s.exists() and sha(s) != sha(p):
            bad.append(f"{f}: differs from {SRC} (source moved on: run stage)")
    log("OK: shared/sfp-core matches" if not bad else "DRIFT: " + "; ".join(bad))
    return 1 if bad else 0


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "check"
    if mode not in ("stage", "check"):
        sys.exit(__doc__)
    sys.exit(stage() if mode == "stage" else check())
