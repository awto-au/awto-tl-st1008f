#!/usr/bin/env python3
"""gh_issue_from_draft — create a GitHub issue from a Markdown draft.

- Title = the draft's first `# ` line; body = the rest.
- Relative links (`../docs/x.md`, `./y`) are rewritten to absolute blob URLs on --repo/--branch,
  since GitHub does not resolve relative links inside issues.

Usage:
    scripts/gh_issue_from_draft.py tmp/issue-draft-foo.md [--repo awto-au/awto-tl-st1008f] [--close] [--dry-run]

Log: tmp/logs/gh_issue_from_draft.log
"""

from __future__ import annotations

import argparse
import posixpath
import re
import subprocess
import sys
import time
from pathlib import Path

LOG = Path("tmp/logs/gh_issue_from_draft.log")
LINK = re.compile(r"\]\((?!https?://|#|mailto:)([^)\s]+)\)")


def log(msg: str):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def absolutise(body: str, draft: Path, repo: str, branch: str) -> str:
    base = draft.parent.as_posix()

    def sub(m: re.Match) -> str:
        target, _, frag = m.group(1).partition("#")
        path = posixpath.normpath(posixpath.join(base, target))
        url = f"https://github.com/{repo}/blob/{branch}/{path}"
        return f"]({url}{'#' + frag if frag else ''})"

    return LINK.sub(sub, body)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("draft", type=Path)
    ap.add_argument("--repo", default="awto-au/awto-tl-st1008f")
    ap.add_argument("--branch", default="main")
    ap.add_argument("--close", action="store_true", help="close right after creating")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    text = args.draft.read_text()
    first, _, rest = text.partition("\n")
    if not first.startswith("# "):
        log(f"{args.draft}: first line is not a '# ' title")
        return 1
    title = first[2:].strip()
    body = absolutise(rest.lstrip("\n"), args.draft, args.repo, args.branch)

    if args.dry_run:
        print(f"TITLE: {title}\n\n{body}")
        return 0

    r = subprocess.run(["gh", "issue", "create", "--repo", args.repo, "--title", title,
                        "--body-file", "-"], input=body, text=True, capture_output=True)
    if r.returncode:
        log(f"{args.draft}: create failed: {r.stderr.strip()}")
        return r.returncode
    url = r.stdout.strip().splitlines()[-1]
    log(f"{args.draft} -> {url} ({title})")

    if args.close:
        r = subprocess.run(["gh", "issue", "close", url, "--reason", "completed"],
                           text=True, capture_output=True)
        log(f"close {url}: rc={r.returncode} {r.stderr.strip()}")
        return r.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
