#!/usr/bin/env python3
"""kernel_series_branch — our mainline patch series as a branch in the machine Linux store (awto-dan#50).

    python3 scripts/kernel_series_branch.py [--base next-20261009]   # default: kernel_base PIN

- Branch `awto/st1008f/<base>` = the base tag, then exactly what `mainline_build_check.py` lays down:
  one commit for the OpenWrt realtek files (OWRT_FILES at the pinned OpenWrt commit) + shared cores,
  then one commit per patch (OpenWrt verbatim set, then ours; `patch -p1` as the build). Rebuilt from
  scratch each run: the patch files stay the source, the branch is the shared git-native view.
- Built in a temporary worktree of the store (tmp/linux-series), removed afterwards. Local only: pushing
  to the public awto-au/linux remote is a separate, approved step.
- Log: tmp/logs/kernel_series_branch.log
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kernel_base  # noqa: E402
import mainline_build_check as mbc  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/kernel_series_branch.log"
WT = ROOT / "tmp/linux-series"
GIT_S = 300  # worktree add / one apply+commit on a kernel tree: seconds at most; 300 names a hang


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


ENV: dict[str, str] = {}  # commit dates pinned to the base commit: same series = same hashes (push without force)


def git(*args: str, cwd: Path, check: bool = True, data: str | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_S, input=data,
                       env={**os.environ, **ENV})
    if check and r.returncode:
        raise SystemExit(f"FAIL git {' '.join(args)[:80]}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def message(patch: Path) -> str:
    """Commit message from the patch header: Subject (without [PATCH]) + the text before '---'."""
    text = patch.read_text(errors="replace")
    m = re.search(r"^Subject: (?:\[PATCH[^\]]*\] )?(.+)$", text, re.M)
    subject = m[1].strip() if m else patch.stem
    body = text[m.end():].split("\n---\n", 1)[0].strip() if m else ""
    src = "openwrt/patches" if patch.parent == kernel_base.OURS else "OpenWrt target/linux/realtek/patches-6.18"
    return f"{subject}\n\n{body}\n\nPatch: {src}/{patch.name}\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default=kernel_base.selected())
    a = ap.parse_args()
    store = kernel_base.REPO
    kernel_base.fetch(a.base)
    branch = f"awto/st1008f/{a.base}"
    if a.base != kernel_base.selected():
        raise SystemExit("--base must match the build's base: run with KERNEL_BASE=<base> instead")
    series = mbc.PATCHES
    when = git("log", "-1", "--format=%cI", f"{a.base}^{{commit}}", cwd=store)
    ENV.update(GIT_AUTHOR_DATE=when, GIT_COMMITTER_DATE=when)
    git("worktree", "prune", cwd=store)
    if WT.exists():
        git("worktree", "remove", "--force", str(WT), cwd=store)
    git("worktree", "add", "--force", "-B", branch, str(WT), f"{a.base}^{{commit}}", cwd=store)
    try:
        for rel in mbc.OWRT_FILES:
            src, dst = mbc.OWRT_FILES_DIR / rel, WT / rel
            if src.is_dir():
                shutil.rmtree(dst, ignore_errors=True)
                shutil.copytree(src, dst)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        for rel, src in mbc.SHARED_FILES.items():
            shutil.copy2(src, WT / rel)
        git("add", "-A", cwd=WT)
        git("commit", "-q", "-F", "-", cwd=WT, data=f"realtek: OpenWrt realtek files-6.18 + awto shared cores\n\n"
            f"OpenWrt {mbc.owrt_commit()[:12]} target/linux/realtek/files-6.18 ({len(mbc.OWRT_FILES)} paths) and "
            f"{', '.join(mbc.SHARED_FILES)} (awto-tl-st1008f shared/).\n")
        for p in series:
            r = subprocess.run(["patch", "-p1", "--forward", "--batch", "-i", str(p.resolve())], cwd=WT,
                               capture_output=True, text=True, timeout=GIT_S)
            if r.returncode:
                raise SystemExit(f"FAIL {p.name} does not apply: {r.stdout.strip()[-300:]}")
            for f in WT.rglob("*.orig"):
                f.unlink()
            git("add", "-A", cwd=WT)
            git("commit", "-q", "-F", "-", cwd=WT, data=message(p))
        head = git("rev-parse", "--short", "HEAD", cwd=WT)
    finally:
        git("worktree", "remove", "--force", str(WT), cwd=store, check=False)
    log(f"PASS {branch} = {a.base} + {len(series)} patches -> {head} (local; push needs approval)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
