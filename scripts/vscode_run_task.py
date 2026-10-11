#!/usr/bin/env python3
"""vscode_run_task — run a VS Code workspace task by name from the shell (agents included).

- install: pack tools/vscode-run-task/ into tmp/run-task.vsix (zip, no npm) and
  `code-insiders --install-extension` it.
- run <name>: `code-insiders --open-url vscode-insiders://awto.run-task/run?name=<name>`. The
  extension runs that task from the open workspace's tasks.json (no-op if already running).
- console: run "ST1008 console", then check a real `tail -F ...st1008-console.log` appeared.
- Log: tmp/logs/vscode_run_task.log
"""

import argparse
import json
import urllib.parse
import subprocess
import sys
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "tools/vscode-run-task"
VSIX = ROOT / "tmp/run-task.vsix"
LOG = ROOT / "tmp/logs/vscode_run_task.log"
URI = "vscode-insiders://awto.run-task/run?name="
CONSOLE_TASK = "ST1008 console"

TYPES = ('<?xml version="1.0" encoding="utf-8"?><Types xmlns="http://schemas.openxmlformats.org/package/'
         '2006/content-types"><Default Extension=".json" ContentType="application/json"/>'
         '<Default Extension=".js" ContentType="application/javascript"/>'
         '<Default Extension=".vsixmanifest" ContentType="text/xml"/></Types>')


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def manifest(pkg: dict) -> str:
    return f'''<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
 <Metadata>
  <Identity Language="en-US" Id="{pkg["name"]}" Version="{pkg["version"]}" Publisher="{pkg["publisher"]}"/>
  <DisplayName>{pkg["displayName"]}</DisplayName>
  <Description xml:space="preserve">{pkg["description"]}</Description>
  <Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="{pkg["engines"]["vscode"]}"/></Properties>
 </Metadata>
 <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
 <Dependencies/>
 <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true"/></Assets>
</PackageManifest>
'''


def tail_running() -> bool:
    r = subprocess.run(["pgrep", "-a", "-x", "tail"], capture_output=True, text=True, timeout=2)
    return "st1008-console.log" in r.stdout


def install() -> int:
    pkg = json.loads((SRC / "package.json").read_text())
    VSIX.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(VSIX, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", TYPES)
        z.writestr("extension.vsixmanifest", manifest(pkg))
        for f in ("package.json", "extension.js"):
            z.write(SRC / f, f"extension/{f}")
    # local install, no network: a few seconds; 60 s names a stuck editor
    r = subprocess.run(["code-insiders", "--install-extension", str(VSIX), "--force"],
                       capture_output=True, text=True, timeout=60)
    log(f"install {VSIX.name} v{pkg['version']}: rc {r.returncode} {r.stdout.strip()} {r.stderr.strip()}")
    return r.returncode


def run(name: str) -> int:
    # hands the URI to the running editor; returns at once
    r = subprocess.run(["code-insiders", "--open-url", URI + urllib.parse.quote(name)], timeout=10)
    log(f"run task {name!r}: rc {r.returncode}")
    return r.returncode


def open_view() -> int:
    if tail_running():
        log("console view already running")
        return 0
    run(CONSOLE_TASK)
    t0 = time.monotonic()
    while time.monotonic() - t0 < 5:  # task start = spawn a shell + tail: < 1 s; 5 s names a refusal
        if tail_running():
            log(f"console view started ({time.monotonic() - t0:.1f}s)")
            return 0
        time.sleep(0.2)
    log("console view NOT started: accept VS Code's 'open this URI' prompt, or Run Task -> 'ST1008 console'")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=["install", "run", "console"])
    ap.add_argument("name", nargs="?", help="task label for `run`")
    a = ap.parse_args()
    if a.action == "install":
        return install()
    if a.action == "run":
        return run(a.name) if a.name else ap.error("run needs a task name")
    return open_view()


if __name__ == "__main__":
    sys.exit(main())
