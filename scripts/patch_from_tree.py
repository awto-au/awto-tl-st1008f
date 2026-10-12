#!/usr/bin/env python3
"""Regenerate the diff body of a patch on existing files from an edited kernel tree.

- Keeps the patch's header (everything before the first `diff `/`--- a/` line).
- Body = `diff -u` of <orig-dir>/<path> (or <orig-dir>/<basename>) vs <tree>/<path> for each path,
  labelled a/<path> b/<path>; no original = new file (`--- /dev/null`).
- <orig-dir> holds the files as the earlier patches leave them (copy them before editing).

    python3 scripts/patch_from_tree.py openwrt/patches/300-12-*.patch --orig-dir tmp/rteth-orig \\
        drivers/net/ethernet/realtek/rtl838x_eth.c drivers/net/ethernet/realtek/rtl838x_eth.h
Log: tmp/logs/patch_from_tree.log
"""
import argparse
import re
import subprocess
import time
from pathlib import Path

import kernel_base

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/patch_from_tree.log"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("patch", type=Path)
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--orig-dir", type=Path, required=True)
    ap.add_argument("--tree", type=Path, default=kernel_base.tree())
    a = ap.parse_args()
    text = a.patch.read_text() if a.patch.exists() else "Subject: \n\n---\n"
    m = re.search(r"^(diff |--- a/|--- /dev/null)", text, re.M)
    out = text[:m.start()] if m else text
    for rel in a.paths:
        # original: <orig-dir>/<rel>, else <orig-dir>/<basename>, else none (new file)
        orig = next((p for p in (a.orig_dir / rel, a.orig_dir / Path(rel).name) if p.is_file()), None)
        old = ["--label", f"a/{rel}", str(orig)] if orig else ["--label", "/dev/null", "/dev/null"]
        # diff exit 1 = files differ (expected); 2 = trouble
        r = subprocess.run(["diff", "-u", *old[:2], "--label", f"b/{rel}", old[2], str(a.tree / rel)],
                           capture_output=True, text=True, timeout=10)  # local diff of 2 files, <1 s
        if r.returncode > 1:
            raise SystemExit(f"diff failed for {rel}: {r.stderr}")
        out += r.stdout
    a.patch.write_text(out)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a.patch.name}: {len(out.splitlines())} lines\n")
    print(f"{a.patch}: {len(out.splitlines())} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
