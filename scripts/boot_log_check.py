#!/usr/bin/env python3
"""boot_log_check — strict allowlist check of ST1008F U-Boot and Linux console boots.

- Splits the console log into boots (`U-Boot 20…` banner) and stages: `uboot`, then the Linux
  flavour from its banner: `openwrt`, `mainline`, `stock`.
- Every line must match an allowlist regex for its stage (scripts/boot_log_allowlist.txt;
  section `[linux]` applies to openwrt, mainline and stock);
  anything else is UNKNOWN and fails the check.
- DENY patterns (panic, Oops, WARNING, Call Trace, failed, timed out, -Exxx, …) are ERROR even if
  allowlisted, unless that allowlist entry carries `known #NN` (a tracking issue).
- Daemon markers (`[TX …]`, `[daemon] …`), U-Boot prompt lines and our own echoed commands are skipped.
- U-Boot md/i2c reply shapes (`xxxxxxxx: …`, `data 0x..`, `done`) are skipped.
- Exit 0 = clean, 1 = UNKNOWN only, 2 = ERROR. Log: tmp/logs/boot_log_check.log
"""

import argparse
import re
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/boot_log_check.log"
DEFAULT_CONSOLE = ROOT / "private/serial/st1008-console.log"
DEFAULT_ALLOW = ROOT / "scripts/boot_log_allowlist.txt"

DENY = re.compile(
    r"panic|\bOops\b|\bBUG\b|WARNING|Call Trace|cut here|Unable to handle|segfault|"
    r"\bfail(ed|ure)?\b|\berror\b|\bErr:0x|timed out|timeout|invalid|unknown|not found|"
    r"(?-i:-E[A-Z]{2,}\b)|error -\d+|Ring contention|\bhung\b|\bstall(ed)?\b|corrupt|\bbad\b|cannot|can't|"
    r"not (yet )?(fully )?implemented|deprecated|taints kernel|\bFAIL\b|could not|"
    r"own address as source",  # bridge loop signature (#19): never allowlist
    re.IGNORECASE)
# Stack/register dump lines: part of the preceding WARNING/Oops/panic, which is already ERROR.
TRACE = re.compile(r"\s*\[<[0-9a-f]{8}>\] .*|Stack : .*|\s+([0-9a-f]{8} )+[0-9a-f]{8}|\s+\.\.\.|"
                   r"CPU: \d+ UID: \d+ PID: .*|Hardware name: .*")
DAEMON_TS = re.compile(r"^\[\d\d:\d\d:\d\d\.\d{3}\] ?")
KERNEL_TS = re.compile(r"^\[\s*\d+\.\d+\]\s?")
SHELL_PROMPT = re.compile(r"Please press Enter to activate this console|^root@[\w()-]+:.*# ?|^/ # |"
                          r"^st1008f-mainline # |^st1008f-linux # ?")  # lines are rstripped: bare linux prompt has no space
SKIP = re.compile(r"^\[TX \d\d:\d\d:\d\d\]|^\[daemon\]|^\s*$|^RTL9300#|^st1008f-(mainline|linux) #")
# U-Boot replies to our own md/rtk i2c commands (dump rows, `data 0x..`, `done`).
UBOOT_REPLY = re.compile(r"[0-9a-f]{8}: [0-9a-f]{8}.*|data 0x[0-9a-f]+|done")


def apply_bs(s: str) -> str:
    """Resolve backspaces (U-Boot countdown / TFTP progress overwrite)."""
    out: list[str] = []
    for c in s:
        if c == "\x08":
            if out:
                out.pop()
        else:
            out.append(c)
    return "".join(out)


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(msg + "\n")


def load_allow(path: Path) -> dict[str, list[tuple[re.Pattern, str, bool]]]:
    """Sections `[stage]`; lines `regex  # reason [known #NN]`. Regex is fullmatch on the
    normalised line (timestamps stripped)."""
    allow: dict[str, list] = {}
    stage = None
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        if m := re.fullmatch(r"\[([\w-]+)\]", line.strip()):
            stage = m.group(1)
            allow.setdefault(stage, [])
            continue
        pat, _, reason = line.partition("  # ")
        if not reason:
            raise SystemExit(f"{path}:{n}: entry needs '  # reason'")
        allow[stage].append((re.compile(pat.strip()), reason, bool(re.search(r"known #\d+", reason))))
    return allow


def split_boots(lines: list[str]) -> list[list[tuple[int, str]]]:
    boots, cur = [], []
    for n, line in enumerate(lines, 1):
        if "U-Boot 2011.12" in line and cur:  # stock power-on banner; chainloaded U-Boot is a stage
            boots.append(cur)
            cur = []
        cur.append((n, line))
    if cur:
        boots.append(cur)
    return boots


def stage_of(text: str, current: str) -> str:
    if "U-Boot 2011.12" in text:
        return "uboot"
    if "U-Boot 20" in text:
        return "uboot-mainline"
    if "Linux version" in text:
        if "openwrt" in text.lower():
            return "openwrt"
        if re.search(r"Linux version [7-9]\.|Linux version 6\.(1[3-9]|[2-9]\d)", text):
            return "mainline"
        return "stock"
    return current


def check_boot(boot, allow, show_ok: bool):
    """After a Linux shell prompt, only kernel-timestamped lines are checked: the rest is our
    own interactive command output, not boot output."""
    stage, unknown, errors, ok = "uboot", Counter(), Counter(), 0
    echoed: set[str] = set()
    typed, last_typed = "", ""  # send_checked types in chunks: one [TX] line per chunk, Enter alone
    interactive = False
    skipping = False  # between [daemon] note interactive-begin/-end (script command output)
    for n, raw in boot:
        if raw.startswith("[daemon] note interactive-"):
            skipping = raw.rstrip().endswith("begin")
            continue
        if skipping:
            continue
        if raw.startswith("[TX "):
            m = re.search(r"'(.*)'", raw)
            if m:
                p = m.group(1)
                if p.endswith("\\\\r"):
                    typed += p[:-3]
                    echoed.add(typed.strip())
                    last_typed, typed = typed, ""
                else:
                    typed += p
            continue
        stripped = DAEMON_TS.sub("", raw)
        is_kmsg = bool(KERNEL_TS.match(stripped))
        text = apply_bs(KERNEL_TS.sub("", stripped)).rstrip()
        if SHELL_PROMPT.search(text):
            interactive = True
        if interactive and stage != "uboot" and not is_kmsg:
            continue
        t = text.strip()
        if SKIP.match(text) or t in echoed or (t and (t in typed or t in last_typed)):
            continue
        stage = stage_of(text, stage)
        is_uboot = stage.startswith("uboot")
        if is_uboot and UBOOT_REPLY.fullmatch(text):
            continue
        if not is_uboot and TRACE.fullmatch(text):
            continue
        rules = allow.get(stage, []) + (allow.get("linux", []) if not is_uboot else [])
        hit = next(((r, k) for p, r, k in rules if p.fullmatch(text)), None)
        denied = bool(DENY.search(text))
        if hit is None:
            (errors if denied else unknown)[(stage, text)] += 1
            continue
        if denied and not hit[1]:
            errors[(stage, text)] += 1
            continue
        ok += 1
        if show_ok:
            log(f"  ok   {stage:8} {text}  <- {hit[0]}")
    return ok, unknown, errors


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", type=Path, default=DEFAULT_CONSOLE)
    ap.add_argument("--allow", type=Path, default=DEFAULT_ALLOW)
    ap.add_argument("--boot", type=int, default=-1, help="boot index (python style); default last")
    ap.add_argument("--all", action="store_true", help="check every boot in the log")
    ap.add_argument("--from-line", type=int, default=1, help="ignore console-log lines before this")
    ap.add_argument("--show-ok", action="store_true")
    a = ap.parse_args()

    allow = load_allow(a.allow)
    lines = a.log.read_text(errors="replace").splitlines()[a.from_line - 1:]
    boots = split_boots(lines)
    pick = boots if a.all else [boots[a.boot]]
    log(f"=== {time.strftime('%Y-%m-%dT%H:%M:%S%z')} {a.log.name}: {len(boots)} boots, checking {len(pick)}")
    worst = 0
    for b in pick:
        ok, unknown, errors = check_boot(b, allow, a.show_ok)
        first = b[0][0] + a.from_line - 1
        log(f"--- boot at log line {first}: ok {ok}, UNKNOWN {sum(unknown.values())}, "
            f"ERROR {sum(errors.values())}")
        for (st, t), c in sorted(errors.items()):
            log(f"  ERROR   {st:8} x{c:<3} {t}")
        for (st, t), c in sorted(unknown.items()):
            log(f"  UNKNOWN {st:8} x{c:<3} {t}")
        worst = max(worst, 2 if errors else 1 if unknown else 0)
    log(f"=== result: {['CLEAN', 'UNKNOWN lines', 'ERRORS'][worst]}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
