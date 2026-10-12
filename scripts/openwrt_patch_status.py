#!/usr/bin/env python3
"""Classify every OpenWrt realtek patches-6.18 patch against the kernel_base.py tree (#16).

Per patch, in series order, on a clean tree:
  upstream = reverse-applies (content already in the base)
  applies  = applies forward (then kept applied so later patches in a series can stack);
             can be a false positive (705 lands in another function: already upstream there)
  fails    = neither (needs a forward-port, or partly upstream)
Tree is reset to git HEAD (checkout + clean) before and after. Log: tmp/logs/openwrt_patch_status.log
Output: tmp/openwrt_patch_status.tsv (name, status, files touched).
"""
import argparse
import subprocess
from pathlib import Path

import kernel_base

ROOT = Path(__file__).resolve().parent.parent
OWRT = ROOT / "tmp/openwrt/target/linux/realtek/patches-6.18"
LOG = ROOT / "tmp/logs/openwrt_patch_status.log"
OUT = ROOT / "tmp/openwrt_patch_status.tsv"


def sh(cmd, cwd, log):
    r = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log.write(f"$ {' '.join(map(str, cmd))}\n{r.stdout}[exit {r.returncode}]\n")
    return r.returncode


def files_of(p: Path):
    return sorted({ln[6:].split("\t")[0].strip() for ln in p.read_text(errors="replace").splitlines()
                   if ln.startswith("+++ b/")})


def reset(tree, log):
    sh(["git", "checkout", "-q", "--", "."], tree, log)
    sh(["git", "clean", "-fdq"], tree, log)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tree", default=str(kernel_base.tree()))
    ap.add_argument("--dir", default=str(OWRT), help="patch dir (e.g. generic/pending-6.18)")
    ap.add_argument("--glob", default="*.patch")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    tree = Path(a.tree)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with LOG.open("w") as log:
        reset(tree, log)
        for p in sorted(Path(a.dir).resolve().glob(a.glob)):
            base = ["patch", "-p1", "-s", "-f", "-i", str(p)]
            if sh(base + ["-R", "--dry-run"], tree, log) == 0:
                st = "upstream"
            elif sh(base + ["--dry-run"], tree, log) == 0:
                sh(base, tree, log)
                st = "applies"
            else:
                st = "fails"
            rows.append((p.name, st, " ".join(files_of(p))))
            print(f"{st:9} {p.name}")
        reset(tree, log)
    Path(a.out).write_text("".join("\t".join(r) + "\n" for r in rows))
    print("->", a.out)


if __name__ == "__main__":
    main()
