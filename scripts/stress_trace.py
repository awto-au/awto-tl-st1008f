#!/usr/bin/env python3
"""stress_trace — stress a switch over the network only and record exactly where it fails (#144).

- No console is used by this tool (sw1 has none). Host side: 1 Hz telemetry streamed over SSH from two
  on-board samplers (openwrt/selftest/st1008f-trace.c, one pinned to each VPE), ping at 0.2 s, the
  selftest running in a third SSH session. All lines carry the host time.
- On loss (no ping reply for LOSS_S): last sample per VPE with its age before the loss, selftest stage,
  temperature, busy %; then waits for the unit to return and collects a post-mortem over SSH (uptime,
  cmdline, kernel log head, pstore, clocks).
- `--inject panic|hang|bus --inject-at S`: deliberately kills the unit (validates the recorder). `hang` = panic
  with kernel.panic=0 (recorded as a panic, SoC watchdog resets it); `bus` = a bus-locking read: a true hang,
  no oops and no panic (the next boot must report `unclean`).
- sw1 (house switch) needs `--sw1-ok` (owner request 2026-11-06, #144). Each failing run = about 100 s outage.
- Output: tmp/logs/stress_trace-<ip>-<ts>.{trace,json}, log tmp/logs/stress_trace.log
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/stress_trace.log"
SRC = ROOT / "openwrt/selftest/st1008f-trace.c"
BIN = ROOT / "tmp/trace/st1008f-trace"
SW1 = "192.168.25.48"
NETCONSOLE_PORT = 6666  # kernel log over UDP from the unit (image: hotplug 60-st1008f-netconsole); panic text arrives even as it dies
LOSS_S = 3.0        # ping every 0.2 s: 3 s of silence = 15 lost probes in a row; a busy unit still answers within ~1 s
SHUTDOWN_CAP_S = 40  # OpenWrt shutdown up to ~26 s while the boot selftest runs (#139); x1.5
RETURN_CAP_S = 300  # boot to SSH ~45 s (sw1 2026-11-06); x6 covers a failed turbo boot falling back to stock + retry
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=2", "-o", "ServerAliveCountMax=2",
       "-o", "StrictHostKeyChecking=no"]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def build_and_push(ip: str) -> None:
    import build_selftest
    cc = build_selftest.toolchain(None)
    BIN.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(cc), "-O2", "-static", "-o", str(BIN), str(SRC)], check=True, timeout=60,  # one file < 2 s
                   capture_output=True)
    subprocess.run(["scp", "-O", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=5", str(BIN),
                    f"root@{ip}:/tmp/st1008f-trace"], check=True, timeout=30, capture_output=True)  # 30 KB on the LAN
    subprocess.run(SSH + [f"root@{ip}", "chmod +x /tmp/st1008f-trace"], check=True, timeout=15)


class Recorder:
    def __init__(self, ip: str, path: Path):
        self.ip, self.fh = ip, path.open("w")
        self.last: dict[str, tuple[float, str]] = {}
        self.last_reply = time.time()
        self.stop = False
        self.lock = threading.Lock()

    def line(self, src: str, text: str) -> None:
        t = time.time()
        with self.lock:
            self.fh.write(f"{t:.3f} {src} {text}\n")
            self.fh.flush()
        if src.startswith("trace"):
            m = re.search(r"cpu=(\S+)", text)
            if m:
                self.last[m.group(1)] = (t, text)
        elif src == "ping" and "bytes from" in text:
            self.last_reply = t

    def pump(self, src: str, proc: subprocess.Popen) -> threading.Thread:
        def run() -> None:
            for text in proc.stdout:  # type: ignore[union-attr]
                self.line(src, text.rstrip())
        th = threading.Thread(target=run, daemon=True)
        th.start()
        return th


def netconsole(rec: "Recorder", ip: str) -> subprocess.Popen | None:
    """The unit's netconsole stream, captured on the wire (the host firewall drops UDP :6666 before a socket sees it).
    Each datagram = kernel log text; recorded as `kmsg`."""
    route = subprocess.run(["ip", "-o", "route", "get", ip], capture_output=True, text=True, timeout=5).stdout
    m = re.search(r" dev (\S+)", route)
    if not m:
        log("netconsole: no route to the unit; kernel text not recorded")
        return None
    p = subprocess.Popen(["sudo", "-n", "tcpdump", "-l", "-n", "-i", m.group(1), "-s0", "-A", "-q", "udp", "and", "src", "host",
                          ip, "and", "dst", "port", str(NETCONSOLE_PORT)], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, errors="replace")

    def run() -> None:
        for ln in p.stdout:  # type: ignore[union-attr]
            if re.match(r"^\d\d:\d\d:\d\d\.\d+ IP ", ln) or not ln.strip():
                continue  # tcpdump packet header / blank separator
            rec.line("kmsg", ln.rstrip())
    threading.Thread(target=run, daemon=True).start()
    return p


def post_mortem(ip: str) -> dict:
    cmds = {"uptime_s": "cut -d' ' -f1 /proc/uptime", "cmdline": "cat /proc/cmdline",
            "bogomips": "grep -i bogomips /proc/cpuinfo | head -1",
            "temp_mC": "cat /sys/class/thermal/thermal_zone0/temp",
            "pstore": "ls /sys/fs/pstore 2>/dev/null | tr '\\n' ' '",
            "kernel_head": "dmesg | head -3 | cut -c1-120",
            "lastreset_cmdline": "tr ' ' '\\n' < /proc/cmdline | grep lastreset",
            "blackbox_last": "cat /sys/kernel/debug/st1008f-blackbox/last 2>&1",
            "blackbox_dmesg": "dmesg | grep -i blackbox | head -2 | cut -c1-200",
            "reset_hints": "dmesg | grep -i 'watchdog\\|reset\\|panic\\|oops\\|thermal' | head -5 | cut -c1-140"}
    out = {}
    for k, c in cmds.items():
        r = subprocess.run(SSH + [f"root@{ip}", c], capture_output=True, text=True, timeout=15)
        out[k] = r.stdout.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ip", default=BENCH_IP)
    ap.add_argument("--cpu-secs", type=int, default=60)
    ap.add_argument("--mem-secs", type=int, default=30)
    ap.add_argument("--full", action="store_true", help="selftest --full (all memory patterns)")
    ap.add_argument("--inject", choices=["panic", "hang", "bus", "reboot"])
    ap.add_argument("--inject-at", type=int, default=30, help="seconds after the selftest starts")
    ap.add_argument("--sw1-ok", action="store_true", help="allow sw1, the in-service house switch (owner request, #144)")
    a = ap.parse_args()
    if a.ip == SW1 and not a.sw1_ok:
        sys.exit("refused: 192.168.25.48 is sw1 (house switch); --sw1-ok = owner request, a failing run costs ~100 s outage")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    base = ROOT / f"tmp/logs/stress_trace-{a.ip}-{stamp}"
    build_and_push(a.ip)
    for _ in range(120):  # the unit's own boot selftest takes ~30 s after boot; a second run is refused (rc 2)
        busy = subprocess.run(SSH + [f"root@{a.ip}", "pidof st1008f-selftest"], capture_output=True, text=True, timeout=15)
        if not busy.stdout.strip():
            break
        time.sleep(1)  # poll once a second, bounded 120 s
    rec = Recorder(a.ip, Path(f"{base}.trace"))
    procs = []
    for cpu, mask in (("0", "1"), ("1", "2")):
        p = subprocess.Popen(SSH + [f"root@{a.ip}", f"taskset {mask} /tmp/st1008f-trace 1000 {cpu}"],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        procs.append(p)
        rec.pump(f"trace{cpu}", p)
    nsock = netconsole(rec, a.ip)
    ping = subprocess.Popen(["ping", "-i", "0.2", "-D", a.ip], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    rec.pump("ping", ping)
    t0 = time.time()
    args = f"--quiet --mem-secs {a.mem_secs} --cpu-secs {a.cpu_secs}" + (" --full" if a.full else "")
    test = subprocess.Popen(SSH + [f"root@{a.ip}", f"st1008f-selftest {args}"], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    rec.pump("selftest", test)
    log(f"started on {a.ip}: st1008f-selftest {args}; trace -> {base}.trace")
    injected = False
    lost_at = None
    while True:
        now = time.time()
        if a.inject and not injected and now - t0 >= a.inject_at:
            injected = True
            cmd = {"panic": "echo c > /proc/sysrq-trigger",
                   "hang": "sysctl -w kernel.panic=0 >/dev/null; echo c > /proc/sysrq-trigger",
                   "bus": "devmem 0xbb000010",
                   "reboot": "reboot"}[a.inject]  # bus lock: no oops, no panic, only the SoC watchdog resets it
            log(f"injecting {a.inject} at +{now - t0:.1f} s")
            subprocess.Popen(SSH + [f"root@{a.ip}", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if test.poll() is not None:
            break
        if now - rec.last_reply > LOSS_S:
            lost_at = rec.last_reply
            break
        if now - t0 > a.cpu_secs + a.mem_secs + 120:  # selftest fast steps + both loads + margin: a stuck run
            log("FAIL: run exceeded its budget without loss or end")
            break
        time.sleep(0.2)  # poll cadence of the loss check: 5 Hz is finer than the 0.2 s ping, cheap on the host
    if lost_at is None and test.returncode not in (0, None):  # SSH broke first (reboot, crash): does the ping stop too?
        t2 = time.time()
        while time.time() - t2 < SHUTDOWN_CAP_S:  # a clean shutdown keeps answering ping while services stop
            if time.time() - rec.last_reply > LOSS_S:
                lost_at = rec.last_reply
                break
            time.sleep(0.2)  # same 5 Hz cadence as the main loop
    report: dict = {"ip": a.ip, "started": stamp, "args": args, "inject": a.inject}
    if lost_at is None:
        report["result"] = "PASS" if test.returncode == 0 else f"selftest rc {test.returncode}"
        log(f"{report['result']}: selftest ended after {time.time() - t0:.1f} s, no loss")
    else:
        report["result"] = "LOST"
        report["lost_after_s"] = round(lost_at - t0, 1)
        per = {}
        for cpu, (t, text) in sorted(rec.last.items()):
            per[f"cpu{cpu}"] = {"age_before_loss_s": round(lost_at - t, 2), "line": text}
        report["last_samples"] = per
        kmsg = [ln for ln in Path(f"{base}.trace").read_text().splitlines() if " kmsg " in ln][-12:]
        report["kernel_last_lines"] = kmsg
        log(f"netconsole: {len(kmsg)} kernel lines recorded" + (" (last: " + kmsg[-1][:120] + ")" if kmsg else
                                                                " (none: no netconsole in the image, or a hang with no oops)"))
        log(f"LOST {report['lost_after_s']} s after the selftest started")
        for k, v in per.items():
            log(f"  last {k}: {v['age_before_loss_s']} s before the loss: {v['line']}")
        log(f"waiting for the unit (cap {RETURN_CAP_S} s) ...")
        back = None
        last_up = max((float(m.group(1)) for _, text in rec.last.values() if (m := re.search(r" up=([\d.]+)", text))),
                      default=0.0)
        t1 = time.time()
        while time.time() - t1 < RETURN_CAP_S:
            r = subprocess.run(SSH + [f"root@{a.ip}", "cut -d' ' -f1 /proc/uptime"], capture_output=True, text=True,
                               timeout=15)
            if r.returncode == 0 and r.stdout.strip() and float(r.stdout.strip()) < last_up - 1:  # a new boot
                back = time.time()
                break
            time.sleep(1)  # one SSH probe per second (a failed probe already waits up to its 5 s connect timeout)
        if back:
            report["outage_s"] = round(back - lost_at, 1)  # up to ~10 s after the ping returns: SSH comes up later
            log(f"back after {report['outage_s']} s; collecting post-mortem")
            for _ in range(60):  # SSH comes up ~10 s after the first ping (firewall start)
                try:
                    report["post_mortem"] = post_mortem(a.ip)
                    break
                except Exception:
                    time.sleep(1)  # one SSH retry per second, bounded 60 s
            log(f"post-mortem: {json.dumps(report.get('post_mortem', {}))}")
        else:
            report["outage_s"] = None
            log(f"FAIL: no ping reply within {RETURN_CAP_S} s: physical recovery needed")
    rec.stop = True
    if nsock and nsock.poll() is None:
        nsock.terminate()
    for p in procs + [ping, test]:
        if p.poll() is None:
            p.terminate()
    Path(f"{base}.json").write_text(json.dumps(report, indent=2))
    log(f"report: {base}.json")
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
