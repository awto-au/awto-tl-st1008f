#!/usr/bin/env python3
"""Build the openwrt/openwrt-relative diff of our l3.c change and run checkpatch on it (#59).

- a/: upstream files as fetched (scripts/upstream_rtl83xx_fetch.py); b/: edited copies.
- Out: <out>/l3-upstream.diff, paths target/linux/realtek/files-6.18/drivers/net/dsa/rtl83xx/l3.[ch].
- checkpatch: tmp/linux-v7.3/scripts/checkpatch.pl --no-tree on that diff.
Log: tmp/logs/l3_upstream_diff.log
"""
import argparse
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/l3_upstream_diff.log"
DST = "target/linux/realtek/files-6.18/drivers/net/dsa/rtl83xx"


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    with LOG.open("a") as f:
        f.write(line + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", type=Path, default=ROOT / "tmp/l3work/a")
    ap.add_argument("--b", type=Path, default=ROOT / "tmp/l3work/b")
    ap.add_argument("--out", type=Path, default=ROOT / "tmp/upstream-pr")
    a = ap.parse_args()
    LOG.parent.mkdir(parents=True, exist_ok=True)
    a.out.mkdir(parents=True, exist_ok=True)
    body = ""
    for name in ("l3.c", "l3.h"):
        # local diff of two files, well under 1 s; 10 s names a hang
        r = subprocess.run(["diff", "-u", "--label", f"a/{DST}/{name}", "--label", f"b/{DST}/{name}",
                            str(a.a / name), str(a.b / name)], capture_output=True, text=True, timeout=10)
        if r.returncode > 1:
            raise SystemExit(f"diff failed: {r.stderr}")
        body += r.stdout
    out = a.out / "l3-upstream.diff"
    out.write_text(body)
    log(f"{out}: {len(body.splitlines())} lines")
    # checkpatch on ~1 k lines takes a few s; 60 s names a hang
    r = subprocess.run(["perl", str(ROOT / "tmp/linux-v7.3/scripts/checkpatch.pl"), "--no-tree",
                        "--no-signoff", "--strict", "--max-line-length=100", str(out)],
                       capture_output=True, text=True, timeout=60)
    log(r.stdout.strip()[-3000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
