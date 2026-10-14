#!/usr/bin/env python3
"""kernel_base — the Linux tree the mainline build and the OpenWrt-on-mainline kernel use (#16).

- PIN = default base: a linux-next tag (owner 2026-10-12, docs/DECISIONS.md). FALLBACK = v7.3-rc6.
- Select: env `KERNEL_BASE=v7.3-rc6` (or another fetched next tag) for any build command.
- Git: the machine-wide Linux store (awto-dan#50: all upstreams as remotes, awto series as branches),
  reached through the gitignored symlink `tmp/linux-store` (`./dev.py kernel-base setup --store PATH`).
  Worktrees of it: `tmp/linux-next` (PIN, a next tag) and `tmp/linux-v7.3` (FALLBACK). Next tags are
  fetched in full from remote `next` (never --depth: the store is shared and full).
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
REPO = ROOT / "tmp/linux-store"  # symlink -> the machine store (awto-dan#50); no host path in this repo
NEXT_TREE = ROOT / "tmp/linux-next"
FALLBACK_TREE = ROOT / "tmp/linux-v7.3"
OURS = ROOT / "openwrt/patches"
# 6.18-image only: they patch OpenWrt generic code a mainline tree lacks (build_openwrt.py lists them)
OPENWRT_ONLY = {
    "300-32-jffs2-skip-erase-of-blank-blocks.patch",  # on top of OpenWrt 532-jffs2_eofdetect
    "300-33-mtdsplit-uimage-cmdline-match.patch",  # OpenWrt generic drivers/mtd/mtdsplit
}
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
    return NEXT_TREE if is_next(base or selected()) else FALLBACK_TREE


def patches(base: str | None = None) -> list[Path]:
    """Our openwrt/patches series for this base (fallback: 7.3 copies replace/add by name)."""
    base = base or selected()
    series = {p.name: p for p in OURS.glob("*.patch") if p.name not in OPENWRT_ONLY}
    if not is_next(base):
        series.update({p.name: p for p in (ROOT / f"openwrt/patches-{base}").glob("*.patch")})
    return [series[n] for n in sorted(series)]


def kernel_version(base: str | None = None) -> tuple[str, str]:
    """(patchver, full) from the tree's Makefile, e.g. ("7.3", "7.3-rc7")."""
    mk = (tree(base) / "Makefile").read_text()
    v = {k: re.search(rf"^{k} = (.*)$", mk, re.M)[1].strip() for k in ("VERSION", "PATCHLEVEL", "EXTRAVERSION")}
    pv = f"{v['VERSION']}.{v['PATCHLEVEL']}"
    return pv, pv + v["EXTRAVERSION"]


def store_ok() -> None:
    if not (REPO / ".git").exists() and not (REPO / "objects").exists():
        sys.exit(f"{REPO.relative_to(ROOT)}: no Linux store; ./dev.py kernel-base setup --store PATH (awto-dan#50)")


def fetch(tag: str) -> None:
    store_ok()
    if git("tag", "-l", tag):
        return
    if is_next(tag) and "next" not in git("remote").split():
        git("remote", "add", "--no-tags", "next", NEXT_URL)
    log(f"fetch {tag} into the store")
    git("fetch", "--no-tags", "next" if is_next(tag) else "torvalds", f"refs/tags/{tag}:refs/tags/{tag}",
        timeout=FETCH_TIMEOUT)


def checkout(base: str | None = None) -> Path:
    """Worktree of the store at `base`, fetched/created if needed. Patched files are reset by the build scripts."""
    base = base or selected()
    wt = tree(base)
    fetch(base)
    want = git("rev-parse", f"{base}^{{commit}}")
    if not (wt / ".git").exists():
        git("worktree", "prune")
        log(f"worktree add {wt.relative_to(ROOT)} @ {base}")
        git("worktree", "add", "--detach", str(wt), base, timeout=CHECKOUT_TIMEOUT)
    elif git("rev-parse", "HEAD", cwd=wt) != want:
        log(f"checkout {base} in {wt.relative_to(ROOT)}")
        git("checkout", "-f", "--detach", base, cwd=wt, timeout=CHECKOUT_TIMEOUT)
        git("clean", "-fdq", cwd=wt, timeout=CHECKOUT_TIMEOUT)
    return wt


def setup(store: str) -> None:
    """tmp/linux-store -> the machine store; fails closed if it is not a full Linux repo."""
    st = Path(store).expanduser().resolve()
    if subprocess.run(["git", "-C", str(st), "rev-parse", "--is-shallow-repository"], capture_output=True,
                      text=True).stdout.strip() != "false" or not (st / "MAINTAINERS").exists():
        sys.exit(f"{st}: not a full (non-shallow) Linux checkout")
    if REPO.is_symlink() or not REPO.exists():
        REPO.unlink(missing_ok=True)
        REPO.symlink_to(st)
    log(f"{REPO.relative_to(ROOT)} -> {st}")


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
    ap.add_argument("action", nargs="?", default="show", choices=["show", "update", "checkout", "setup"])
    ap.add_argument("--tag", help="update: this next-YYYYMMDD instead of the newest")
    ap.add_argument("--store", help="setup: path of the machine Linux store (awto-dan#50)")
    a = ap.parse_args()
    if a.action == "setup":
        if not a.store:
            sys.exit("setup needs --store PATH")
        setup(a.store)
        return 0
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
