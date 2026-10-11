#!/usr/bin/env python3
"""Fetch OpenWrt's realtek rtl83xx DSA driver dir at a ref via `gh api` (no clone; disk is tight).

Out: tmp/upstream/rtl83xx-<sha10>/ (one file per driver file). Log: tmp/logs/upstream_rtl83xx_fetch.log
Use: diff against tmp/openwrt (pinned) to see what upstream changed since the pin (#59).
"""
import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/upstream_rtl83xx_fetch.log"
DIR = "target/linux/realtek/files-6.18/drivers/net/dsa/rtl83xx"


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    with LOG.open("a") as f:
        f.write(line + "\n")


def gh(path):
    r = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"gh api {path} failed: {r.stderr.strip()}")
    return json.loads(r.stdout)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="openwrt/openwrt")
    ap.add_argument("--ref", default="main")
    ap.add_argument("--dir", default=DIR)
    ap.add_argument("--match", default="", help="only files whose name contains this")
    ap.add_argument("--name", default="rtl83xx", help="out dir prefix")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    sha = gh(f"repos/{a.repo}/commits/{a.ref}")["sha"]
    out = ROOT / "tmp/upstream" / f"{a.name}-{sha[:10]}"
    out.mkdir(parents=True, exist_ok=True)
    log(f"{a.repo} ref {a.ref} = {sha} -> {out}")
    for ent in gh(f"repos/{a.repo}/contents/{a.dir}?ref={sha}"):
        if ent["type"] != "file" or a.match not in ent["name"]:
            continue
        blob = gh(f"repos/{a.repo}/git/blobs/{ent['sha']}")
        (out / ent["name"]).write_bytes(base64.b64decode(blob["content"]))
        log(f"  {ent['name']} {ent['size']} B")
    print(out)


if __name__ == "__main__":
    main()
