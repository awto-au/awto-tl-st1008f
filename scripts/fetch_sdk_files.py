#!/usr/bin/env python3
"""Fetch single files/dirs from the Realtek GPL SDK (github.com/reyalo/Realtek) via `gh api`.

- For files the sparse local clone lacks. Output: tmp/sdk/<repo path>; log tmp/logs/fetch_sdk_files.log.
- Usage: scripts/fetch_sdk_files.py sources/<path> [...]   (a dir fetches its files, not subdirs)
"""
import base64, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tmp/sdk"
LOG = ROOT / "tmp/logs/fetch_sdk_files.log"
REPO = "reyalo/Realtek"


def log(msg):
    print(msg)
    with LOG.open("a") as f:
        f.write(msg + "\n")


def gh(path):
    # 60 s: one GitHub API call is ~1 s; contents API caps files at 100 MB anyway.
    r = subprocess.run(["gh", "api", f"repos/{REPO}/contents/{path}"], capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(f"gh api {path}: {r.stderr.strip()}")
    return json.loads(r.stdout)


def fetch(path):
    j = gh(path)
    if isinstance(j, list):
        for e in j:
            if e["type"] == "file":
                fetch(e["path"])
        return
    dst = OUT / path
    dst.parent.mkdir(parents=True, exist_ok=True)
    if j.get("encoding") == "base64" and j.get("content"):
        data = base64.b64decode(j["content"])
    else:  # >1 MB: contents API omits content; use the blob API
        b = json.loads(subprocess.run(["gh", "api", f"repos/{REPO}/git/blobs/{j['sha']}"],
                                      capture_output=True, text=True, timeout=120, check=True).stdout)
        data = base64.b64decode(b["content"])
    dst.write_bytes(data)
    log(f"{len(data):8d} {path}")


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    for p in sys.argv[1:]:
        fetch(p)


if __name__ == "__main__":
    main()
