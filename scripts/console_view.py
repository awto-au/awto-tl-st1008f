#!/usr/bin/env python3
"""console_view — follow the stamped serial console log in colour.

Run:  scripts/console_view.py [-n LINES] [--once] [FILE]
- FILE default `logs/serial/st1008-console.ts.log` (console daemon, `[ ms]` per line); `-` reads stdin.
- Starts with the last LINES lines (default 40), then follows (tail -F). `--once` prints them and exits.
- Colour is off when NO_COLOR is set or with `--no-color`. The raw log is never touched.
Colours: link up green / down red, FAIL/error red, WARN yellow, U-Boot milestones and prompts bold,
         `[ ms]` stamps and kernel `[ s]` stamps dim, `[TX]` markers (what was typed) yellow.
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT = ROOT / "logs/serial/st1008-console.ts.log"
POLL_S = 0.05  # follow loop: a UART line at 115200 takes ~1 ms/char; 50 ms keeps the view live and the CPU idle

R, G, Y, B, M, C = "31", "32", "33", "34", "35", "36"
DIM, BOLD = "2", "1"

# (pattern, SGR codes); applied in order, first match per span wins via the stamp/body split below
RULES = [
    (re.compile(r"Link is Up[^\n]*"), f"{BOLD};{G}"),
    (re.compile(r"Link is Down"), f"{BOLD};{R}"),
    (re.compile(r"(?i)\b(fail(ed|ure)?|error|panic|oops|BUG:|timed? ?out|refused|not found|unknown connector)\b|Err:0x|errno=\d+"), f"{BOLD};{R}"),
    (re.compile(r"(?i)\b(warn(ing)?|deprecated|checksum error|NON-COMPLIANT)\b"), Y),
    (re.compile(r"(?<![-\w])(PASS|OK|done|passed|ready)(?![-\w])"), G),
    (re.compile(r"^(U-Boot 20\d\d|Mode:|netwin:|bootsel:|Autoboot|Boot:|## Booting|   Uncompressing|Starting kernel|rtk: network on done|Net:)"), f"{BOLD};{C}"),
    (re.compile(r"(st1008f-mainline|RTL9300|st1008f-linux|root@[\w.-]+:[^#]*)\s?#"), f"{BOLD};{B}"),
    (re.compile(r"^\[TX [\d:]+\][^\n]*"), f"{BOLD};{Y}"),
    (re.compile(r"^\[daemon\][^\n]*"), M),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d+)?\b"), C),
    (re.compile(r"\blan[1-8]\b|\bsw[12]-lan[1-8]\b|\bcage [1-8]\b"), f"{BOLD}"),
]
STAMP = re.compile(r"^(\[\s*\d+ ms\] )")
KSTAMP = re.compile(r"^(\[\s*\d+\.\d{3,6}\] )")


def sgr(codes: str, text: str) -> str:
    return f"\x1b[{codes}m{text}\x1b[0m"


def colour(line: str) -> str:
    stamp = ""
    m = STAMP.match(line)
    if m:
        stamp, line = sgr(DIM, m.group(1)), line[m.end():]
    k = KSTAMP.match(line)
    if k:
        stamp += sgr(DIM, k.group(1))
        line = line[k.end():]
    spans: list[tuple[int, int, str]] = []
    for rx, codes in RULES:
        for hit in rx.finditer(line):
            s, e = hit.span()
            if e > s and not any(s < pe and e > ps for ps, pe, _ in spans):
                spans.append((s, e, codes))
    out, pos = [], 0
    for s, e, codes in sorted(spans):
        out += [line[pos:s], sgr(codes, line[s:e])]
        pos = e
    out.append(line[pos:])
    return stamp + "".join(out)


def last_lines(path: Path, n: int) -> list[str]:
    """Last n lines of a large file without reading all of it (the raw log is hundreds of MB)."""
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        block, data = 1 << 16, b""
        while size > 0 and data.count(b"\n") <= n:
            step = min(block, size)
            size -= step
            fh.seek(size)
            data = fh.read(step) + data
    return data.decode("utf-8", "replace").splitlines()[-n:]


def emit(line: str, use_colour: bool) -> None:
    sys.stdout.write((colour(line) if use_colour else line) + "\n")
    sys.stdout.flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", nargs="?", default=str(DEFAULT))
    ap.add_argument("-n", type=int, default=40, help="lines of history first (default 40)")
    ap.add_argument("--once", action="store_true", help="print the history and exit")
    ap.add_argument("--no-color", "--no-colour", dest="plain", action="store_true")
    a = ap.parse_args()
    use_colour = not (a.plain or os.environ.get("NO_COLOR"))

    if a.file == "-":
        for ln in sys.stdin:
            emit(ln.rstrip("\n"), use_colour)
        return 0
    path = Path(a.file)
    if not path.exists():
        print(f"console_view: {path} not found (is the console daemon running?)", file=sys.stderr)
        return 2
    for ln in last_lines(path, a.n):
        emit(ln, use_colour)
    if a.once:
        return 0
    with path.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        buf = b""
        while True:
            chunk = fh.read(65536)
            if chunk:
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for ln in lines:
                    emit(ln.decode("utf-8", "replace").rstrip("\r"), use_colour)
                continue
            if path.stat().st_size < fh.tell():  # truncated or replaced: start over
                fh.seek(0)
            time.sleep(POLL_S)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
