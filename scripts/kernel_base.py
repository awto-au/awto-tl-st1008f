#!/usr/bin/env python3
"""kernel_base — the Linux tree the mainline build and the OpenWrt-on-mainline kernel use (#16).

- PIN = default base: a linux-next tag (owner 2026-10-12, docs/DECISIONS.md). FALLBACK = v7.3-rc6.
- Select: env `KERNEL_BASE=v7.3-rc6` (or another fetched next tag) for any build command.
- Git: one repo `tmp/linux-v7.3` (shallow; origin = torvalds tag v7.3-rc6, remote `linux-next`, depth-1
  tag fetches). A next tag is checked out as its git worktree `tmp/linux-next`.
- Per-base patches: `openwrt/patches/` is the series for next; `openwrt/patches-v7.3-rc6/` holds the
  7.3 copy of every patch refreshed or dropped for next (same name = replaces; status: MAINLINE-PORT §8).
- `./dev.py kernel-base [show | update [--tag next-YYYYMMDD] | checkout]`; update rewrites PIN below.
- Log: tmp/logs/kernel_base.log
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/kernel_base.log"
PIN = "next-20261009"  # rewritten by `kernel-base update`
FALLBACK = "v7.3-rc6"
NEXT_URL = "https://git.kernel.org/pub/scm/linux/kernel/git/next/linux-next.git"
REPO = ROOT / "tmp/linux-v7.3"
NEXT_TREE = ROOT / "tmp/linux-next"
OURS = ROOT / "openwrt/patches"
# git.kernel.org ls-remote ~2 s, depth-1 fetch of a next tag ~300 MB at >=5 MB/s ~60 s; x1.25 rounded up
LS_TIMEOUT, FETCH_TIMEOUT, CHECKOUT_TIMEOUT = 15, 600, 300


def log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}"
    print(line)
    with LOG.open("a") as f:
        f.write(line + "\n")


def git(*args: str, cwd: Path = REPO, timeout: int = 60, check: bool = True) -> str:
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        sys.exit(f"git {' '.join(args)}: no result after {timeout} s (limit), see {LOG}")
    if check and r.returncode:
        log(f"git {' '.join(args)} -> {r.returncode}: {r.stderr.strip()}")
        sys.exit(f"git {args[0]} failed, see {LOG}")
    return r.stdout.strip()


def selected() -> str:
    return os.environ.get("KERNEL_BASE") or PIN


def is_next(base: str) -> bool:
    return base.startswith("next-")


def tree(base: str | None = None) -> Path:
    return NEXT_TREE if is_next(base or selected()) else REPO


def patches(base: str | None = None) -> list[Path]:
    """Our openwrt/patches series for this base (fallback: 7.3 copies replace/add by name)."""
    base = base or selected()
    series = {p.name: p for p in OURS.glob("*.patch")}
    if not is_next(base):
        series.update({p.name: p for p in (ROOT / f"openwrt/patches-{base}").glob("*.patch")})
    return [series[n] for n in sorted(series)]


def kernel_version(base: str | None = None) -> tuple[str, str]:
    """(patchver, full) from the tree's Makefile, e.g. ("7.3", "7.3-rc7")."""
    mk = (tree(base) / "Makefile").read_text()
    v = {k: re.search(rf"^{k} = (.*)$", mk, re.M)[1].strip() for k in ("VERSION", "PATCHLEVEL", "EXTRAVERSION")}
    pv = f"{v['VERSION']}.{v['PATCHLEVEL']}"
    return pv, pv + v["EXTRAVERSION"]


def fetch(tag: str) -> None:
    if git("tag", "-l", tag):
        return
    if "linux-next" not in git("remote").split():
        git("remote", "add", "--no-tags", "linux-next", NEXT_URL)
        git("config", "--unset-all", "remote.linux-next.fetch", check=False)
    log(f"fetch {tag} (depth 1) into {REPO.relative_to(ROOT)}")
    git("fetch", "--depth", "1", "--no-tags", "linux-next", f"refs/tags/{tag}:refs/tags/{tag}",
        timeout=FETCH_TIMEOUT)


def checkout(base: str | None = None) -> Path:
    """Tree at `base`, fetched/created if needed. Patched files are reset by the build scripts."""
    base = base or selected()
    if not is_next(base):
        return REPO
    fetch(base)
    want = git("rev-parse", f"{base}^{{commit}}")
    if not (NEXT_TREE / ".git").exists():
        git("worktree", "prune")
        log(f"worktree add {NEXT_TREE.relative_to(ROOT)} @ {base}")
        git("worktree", "add", "--detach", str(NEXT_TREE), base, timeout=CHECKOUT_TIMEOUT)
    elif git("rev-parse", "HEAD", cwd=NEXT_TREE) != want:
        log(f"checkout {base} in {NEXT_TREE.relative_to(ROOT)}")
        git("checkout", "-f", "--detach", base, cwd=NEXT_TREE, timeout=CHECKOUT_TIMEOUT)
        git("clean", "-fdq", cwd=NEXT_TREE, timeout=CHECKOUT_TIMEOUT)
    return NEXT_TREE


def newest_next() -> str:
    out = git("ls-remote", "--tags", NEXT_URL, "refs/tags/next-*", timeout=LS_TIMEOUT)
    tags = sorted({m[1] for m in re.finditer(r"refs/tags/(next-\d{8})$", out, re.M)})
    if not tags:
        sys.exit("no next-YYYYMMDD tags on linux-next")
    return tags[-1]


def set_pin(tag: str) -> None:
    me = Path(__file__)
    me.write_text(re.sub(r'^PIN = "[^"]*"', f'PIN = "{tag}"', me.read_text(), count=1, flags=re.M))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", default="show", choices=["show", "update", "checkout"])
    ap.add_argument("--tag", help="update: this next-YYYYMMDD instead of the newest")
    a = ap.parse_args()
    if a.action == "update":
        tag = a.tag or newest_next()
        checkout(tag)
        if tag != PIN:
            set_pin(tag)
            log(f"PIN {PIN} -> {tag} (scripts/kernel_base.py); record it in docs/MAINLINE-PORT.md Baselines")
        else:
            log(f"PIN already {tag}")
        base = tag
    else:
        base = selected()
        if a.action == "checkout":
            checkout(base)
    t = tree(base)
    ver = kernel_version(base)[1] if (t / "Makefile").exists() else "not checked out"
    log(f"base {base} ({'env KERNEL_BASE' if os.environ.get('KERNEL_BASE') else 'PIN'}), "
        f"tree {t.relative_to(ROOT)}, Makefile {ver}, {len(patches(base))} patches in our series")
    return 0


if __name__ == "__main__":
    sys.exit(main())
