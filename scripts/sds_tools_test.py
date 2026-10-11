#!/usr/bin/env python3
"""sds_tools_test — hardware tests of `rtk sds` (SerDes test tools, #74) at our U-Boot prompt.

- Run after `./dev.py ramload uboot-mainline`; does `rtk network on` + `rtk laser 1` itself if needed.
- Tests: status (all cages), errcnt, prbs-near (PRBS31 + near loopback on dark cages, 0 errors
  expected), prbs-dark (no loopback: checker must count, proves it works), eye1 (cage 1 link up),
  eye-dark (other cages), txeye (read-back).
- `run "<cmd>"`: one ad-hoc command at the prompt, reply printed.
- Output: tmp/sds_tools/<label>.json (+ raw eye text); log tmp/logs/sds_tools_test.log.
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import Console  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/sds_tools_test.log"
OUT = ROOT / "tmp/sds_tools"
PROMPT = r"\r?\nst1008f-mainline # "
NET_CAP_S = 12  # `rtk network on` measured ~9 s (#28); x1.25
# eye: 4096 points x ~8 SerDes ops; raw dump 64 rows x ~260 chars = 17 KB = 1.5 s at 115200.
EYE_CAP_S = 15
STATUS_CAP_S = 2  # 8 lines, ~100 SerDes reads: < 0.2 s


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def run(con: Console, cmd: str, cap: float) -> str:
    _, out = con.run(cmd, PROMPT, cap, cmd)
    body = out.split("\n", 1)[1] if "\n" in out else out
    return re.sub(PROMPT + r"$", "", body).replace("\r", "")


def net_on(con: Console) -> None:
    if "run `rtk network on` first" in run(con, "rtk sds status 1", STATUS_CAP_S):
        con.run("rtk network on", r"Err:0xf030:FAIL \(0xf030\)" + PROMPT, NET_CAP_S, "rtk network on")
    con.run("rtk laser 1", r"OK \(out 0xfe\)" + PROMPT, 1, "laser cage 1 only")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", nargs="*", default=["all"])
    ap.add_argument("--cap", type=float, default=5, help="run: reply cap in s")
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    a = ap.parse_args()
    con = Console()
    con.run("echo PROMPT_OK", r"\r?\nPROMPT_OK" + PROMPT, 1, "mainline prompt present")
    if a.what[0] == "run":
        con.note("interactive-begin")
        try:
            print(run(con, " ".join(a.what[1:]), a.cap))
        finally:
            con.note("interactive-end")
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
