#!/usr/bin/env python3
"""Fetch the switches' syslog-ng files from TrueNAS (#115) into tmp/syslog/<ip>/.

Run with awto-terminal's venv (websocket-client):
  /mnt/2tb/git/awto-terminal/.venv/bin/python scripts/syslog_fetch.py [--ip A.B.C.D]
Read-only on TrueNAS: filesystem.listdir + core.download (filesystem.get).
"""
import argparse
import logging
import os
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path

HTTP_TIMEOUT = 30  # s; one day file is < 10 MB on a 1 Gbit LAN (~0.1 s), x300 backstop
TERMINAL_SCRIPTS = Path("/mnt/2tb/git/awto-terminal/scripts")
ROOT_ENV = "ST1008F_REPO"


def repo_root() -> Path:
    if os.environ.get(ROOT_ENV):
        return Path(os.environ[ROOT_ENV])
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, check=True, cwd=Path(__file__).parent)
        return Path(out.stdout.strip())
    except Exception:
        return Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", action="append", help="sender IP (default: every dir)")
    ap.add_argument("--host", default="192.168.25.64")
    args = ap.parse_args()

    root = repo_root()
    out_root = root / "tmp" / "syslog"
    (root / "tmp" / "logs").mkdir(parents=True, exist_ok=True)
    out_root.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=root / "tmp" / "logs" / "syslog_fetch.log", level=logging.INFO,
                        format="%(asctime)s %(message)s")
    logging.getLogger().addHandler(logging.StreamHandler(sys.stdout))

    sys.path.insert(0, str(TERMINAL_SCRIPTS))
    import truenas  # noqa: E402
    truenas._load_env()
    api = truenas.TrueNAS(args.host)
    base = "/mnt/p3/syslog"
    ips = args.ip or [e["name"] for e in api.call("filesystem.listdir", base)
                      if e["type"] == "DIRECTORY"]
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    for ip in ips:
        d = out_root / ip
        d.mkdir(exist_ok=True)
        for e in api.call("filesystem.listdir", f"{base}/{ip}"):
            if e["type"] != "FILE":
                continue
            _, url = api.call("core.download", "filesystem.get", [e["path"]], e["name"])
            data = urllib.request.urlopen(f"https://{args.host}{url}", context=ctx,
                                          timeout=HTTP_TIMEOUT).read()
            (d / e["name"]).write_bytes(data)
            logging.info("%s/%s %d bytes", ip, e["name"], len(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
