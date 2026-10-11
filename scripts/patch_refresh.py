#!/usr/bin/env python3
"""Refresh the new-file hunks of a patch from the patched kernel tree.

- For each `--- /dev/null` / `+++ b/<path>` section in the patch, replace its body with the
  current content of <tree>/<path>. Other sections (edits to existing files) are kept as is.
- Use after editing a file the patch creates (e.g. 300-06 mode-switch driver) in tmp/linux-v7.3.

    python3 scripts/patch_refresh.py openwrt/patches/300-06-*.patch [--tree tmp/linux-v7.3]
"""
import argparse
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/patch_refresh.log"


def refresh(patch: Path, tree: Path) -> list[str]:
    lines = patch.read_text().splitlines(keepends=True)
    out, done, i = [], [], 0
    while i < len(lines):
        ln = lines[i]
        out.append(ln)
        if ln.startswith("--- /dev/null") and i + 2 < len(lines) and lines[i + 1].startswith("+++ b/"):
            rel = lines[i + 1][6:].split("\t")[0].strip()
            body = (tree / rel).read_text().splitlines(keepends=True)
            out.append(lines[i + 1])
            out.append(f"@@ -0,0 +1,{len(body)} @@\n")
            out.extend("+" + b if b.endswith("\n") else "+" + b + "\n\\ No newline at end of file\n"
                       for b in body)
            i += 3  # ---, +++, @@
            while i < len(lines) and (lines[i].startswith("+") or lines[i].startswith("\\")) \
                    and not lines[i].startswith("+++ "):
                i += 1
            done.append(f"{rel}: {len(body)} lines")
            continue
        i += 1
    patch.write_text("".join(out))  # `index` hashes go stale; patch(1) ignores them
    return done


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("patch", type=Path)
    ap.add_argument("--tree", type=Path, default=ROOT / "tmp/linux-v7.3")
    a = ap.parse_args()
    done = refresh(a.patch, a.tree)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    msg = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {a.patch.name}: " + ("; ".join(done) or "no new-file hunks")
    with LOG.open("a") as f:
        f.write(msg + "\n")
    print(msg)


if __name__ == "__main__":
    main()
