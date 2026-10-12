#!/usr/bin/env python3
"""patch_rebase — refresh one patch of the mainline series onto the current kernel base (#16).

- `prepare 300-09`: apply the series (mainline_build_check.apply_patches) up to 300-09, snapshot the
  tree into a private git index (tmp/patch_rebase.index, the tree's own index is untouched), then
  apply 300-09 with rejects kept. Fix the `.rej` hunks by hand in the tree.
- `write 300-09`: body of openwrt/patches/300-09-*.patch = `git diff` of its files vs the snapshot
  (header kept, new files included); `.rej`/`.orig` deleted. Copy the old patch to
  openwrt/patches-v7.3-rc6/ first when 7.3 still needs it (kernel_base.py).
- Log: tmp/logs/patch_rebase.log
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

import kernel_base
import mainline_build_check as mbc

ROOT = kernel_base.ROOT
LOG = ROOT / "tmp/logs/patch_rebase.log"
INDEX = ROOT / "tmp/patch_rebase.index"


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}\n")
    print(msg)


def git(tree: Path, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_INDEX_FILE": str(INDEX)}
    return subprocess.run(["git", *args], cwd=tree, env=env, capture_output=True, text=True,
                          timeout=120)  # add -A over a 1.8 GB tree ~20 s


def find(prefix: str) -> Path:
    hits = [p for p in mbc.PATCHES if p.name.startswith(prefix)]
    if len(hits) != 1:
        sys.exit(f"{prefix}: {len(hits)} patches match")
    return hits[0]


def files_of(patch: Path) -> tuple[list[str], list[str]]:
    lines = patch.read_text().splitlines()
    mod, new = [], []
    for prev, ln in zip(lines, lines[1:]):
        if ln.startswith("+++ b/"):
            (new if prev.startswith("--- /dev/null") else mod).append(ln[6:].split("\t")[0].strip())
    return mod, new


def prepare(tree: Path, prefix: str) -> int:
    patch = find(prefix)
    mbc.apply_patches(tree, upto=patch.name)
    git_index = Path(subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-path", "index"],
                                    cwd=tree, capture_output=True, text=True, check=True).stdout.strip())
    shutil.copy2(git_index, INDEX)
    if (r := git(tree, "add", "-A", ".")).returncode:
        sys.exit(f"snapshot failed: {r.stderr}")
    r = subprocess.run(["patch", "-p1", "--forward", "--batch", "-i", str(patch)], cwd=tree,
                       capture_output=True, text=True, timeout=30)
    log(f"prepare {patch.name}:\n{r.stdout}")
    rej = sorted(str(p.relative_to(tree)) for p in tree.rglob("*.rej"))
    log("rejects: " + (" ".join(rej) or "none"))
    return 0


def write(tree: Path, prefix: str) -> int:
    patch = find(prefix)
    mod, new = files_of(patch)
    if new:
        git(tree, "add", "-N", "--", *new)
    r = git(tree, "diff", "--no-color", "--no-ext-diff", "--", *mod, *new)
    if r.returncode:
        sys.exit(f"git diff failed: {r.stderr}")
    text = patch.read_text()
    m = re.search(r"^(diff |--- (a/|/dev/null))", text, re.M)
    patch.write_text((text[:m.start()] if m else text) + r.stdout)
    for f in mod + new:
        for suf in (".rej", ".orig"):
            (tree / (f + suf)).unlink(missing_ok=True)
    log(f"write {patch.relative_to(ROOT)}: {len(r.stdout.splitlines())} diff lines, {len(mod)} modified, {len(new)} new")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["prepare", "write"])
    ap.add_argument("patch", help="name prefix, e.g. 300-09")
    a = ap.parse_args()
    tree = kernel_base.checkout()
    mbc.LOG.parent.mkdir(parents=True, exist_ok=True)
    return prepare(tree, a.patch) if a.action == "prepare" else write(tree, a.patch)


if __name__ == "__main__":
    sys.exit(main())
