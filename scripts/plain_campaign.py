#!/usr/bin/env python3
"""plain_campaign — board test campaign on a booted PLAIN mainline kernel (owner 2026-11-07; docs/PLAIN-KERNEL-TESTS.md).

- Precondition: `./dev.py ramload ... mainline-kernel --mgmt` done (bench initramfs + bench kernel for gdma), board reachable by ssh.
- Steps (--steps, default all but memstress): pre perf natsetup zc gdma dss selftest link checklog memstress.
- Each step is a host subprocess under a STALL timeout (no output line / CSV growth for `stall` s = hung: kill, log last line,
  silence, loadavg) plus a total backstop (3x the measured worst case where one exists). Caps are in STEPS with their source.
- After a failed step the board is pinged; no answer = campaign stops (DEAD). No power action is ever taken here.
- Refuses sw1 (192.168.25.48) in every mode. `--dry-run` prints commands and caps, touches nothing.
- Output: tmp/logs/plain_campaign.csv (ts,tag,step,iter,rc,secs,verdict,detail), one-line verdicts in tmp/logs/plain_campaign.log
- `plain_campaign.py --tag stock|picks [--ip A.B.C.D] [--n 3] [--steps a,b] [--dry-run]`
"""
from __future__ import annotations

import argparse
import csv
import os
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP, SW1_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/plain_campaign.log"
CSV = ROOT / "tmp/logs/plain_campaign.csv"
SOAK_CSV = ROOT / "tmp/logs/dss_soak.csv"
SSH = ["ssh", "-o", "ConnectTimeout=5", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
       "-o", "LogLevel=ERROR", "-o", "BatchMode=yes"]
PY = sys.executable
KO = [ROOT / "kmod/gdma_bench/gdma_bench.ko"]  # driver is in-tree (patch 300-41)
ALL = "pre perf natsetup zc gdma dss selftest link vlanproto checklog memstress".split()
DEFAULT = [s for s in ALL if s != "memstress"]

# step: (stall s, total s, source of the caps). "unmeasured" caps are first-run guesses: secs in the CSV tighten them.
CAPS = {
    "pre": (12, 12, "ssh ConnectTimeout 5 + a few cat/which, <1 s; x2 of 5+1"),
    "perf": (25, 90, "unmeasured: ~6 MB through dropbear on a 1 GHz MIPS (cipher-bound); script bound 60 s per file"),
    "natsetup": (30, 90, "unmeasured: ~20 ssh round trips + host netns; 3 x ~10 s"),
    "zc": (35, 135, "UDP bench 10-12 s x2 runs + perf start + 15 s report + params = ~45 s; total 3x; stall = 12 s run + 15 s report + margin"),
    "gdma": (15, 30, "insmod x2 + bench ~1 s (127 kB x 200 iters at ~300 MB/s + memcpy) + ssh 5 s; hang = bus lock (ssh silent)"),
    "dss_probe": (130, 130, "dss_probe.py bound 120 s (10 combos x 4096 polls if the sensors never ready, HIDDEN-FEATURES); output only at the end"),
    "dss_soak": (30, 90, "1 min at 10 s interval = 6 samples; sample <3 s; stall = 3 intervals; total = 60 s + ramp-down x1.5"),
    "selftest": (35, 80, "selftest 20-26 s measured (docs/SELFTEST.md); stall 26 x 1.35, total 3x"),
    "link": (12, 12, "ssh + 8 sysfs reads, <1 s"),
    "vlanproto": (10, 10, "5 ip commands, ms each, + ssh connect 5 s; x2 of 5+1"),
    "checklog": (15, 30, "local console-log scan <2 s (st1008_ramload uses 30 s)"),
    "memstress": (25, 105, "mem_stress.py ~35 s measured (fill 3.5 s, verify 2 x 11 s, #27); total 3x"),
}


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def ssh_cmd(ip: str, remote: str) -> list[str]:
    return [*SSH, f"root@{ip}", remote]


def run_capped(name: str, argv: list[str], stall: int, total: int, watch: Path | None = None,
               stdin_path: Path | None = None) -> tuple[int, str, float]:
    """(rc, output, secs); rc 124 = killed on stall, 125 = killed on the total backstop."""
    t0 = time.monotonic()
    fh = stdin_path.open("rb") if stdin_path else None
    p = subprocess.Popen(argv, stdin=fh or subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    q: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: ([q.put(ln) for ln in p.stdout], q.put(None)), daemon=True).start()  # sentinel after EOF
    out, last, wsize = [], t0, (watch.stat().st_size if watch and watch.exists() else 0)
    rc = None
    while rc is None:
        try:
            ln = q.get(timeout=1.0)  # 1 s poll of the reader queue; the stall/total checks below carry the bounds
            if ln is None:
                rc = p.wait()
                break
            out.append(ln)
            last = time.monotonic()
        except queue.Empty:
            pass
        if watch and watch.exists() and watch.stat().st_size != wsize:
            wsize, last = watch.stat().st_size, time.monotonic()
        now = time.monotonic()
        why = "stall" if now - last > stall else "total" if now - t0 > total else ""
        if why:
            p.kill()
            p.wait()
            log(f"  {name}: KILLED on {why} (stall {stall} s, total {total} s); silent {now - last:.0f} s, "
                f"elapsed {now - t0:.0f} s, loadavg {os.getloadavg()[0]:.2f}, last line: {(out[-1].strip() if out else '-')[:160]}")
            rc = 124 if why == "stall" else 125
    if fh:
        fh.close()
    return rc, "".join(out), time.monotonic() - t0


class Campaign:
    def __init__(self, a: argparse.Namespace) -> None:
        self.a, self.ip = a, a.ip
        self.rows: list[list] = []
        self.dead = False
        if not a.dry_run:
            CSV.parent.mkdir(parents=True, exist_ok=True)
            if not CSV.exists():
                CSV.write_text("ts,tag,step,iter,rc,secs,verdict,detail\n")

    def record(self, step: str, it: int, rc: int, secs: float, verdict: str, detail: str) -> None:
        detail = " ".join(detail.split())[:300]
        log(f"VERDICT {self.a.tag} {step}#{it}: {verdict} rc={rc} {secs:.0f}s {detail}")
        with CSV.open("a", newline="") as fh:
            csv.writer(fh).writerow([time.strftime("%Y-%m-%dT%H:%M:%S%z"), self.a.tag, step, it, rc, f"{secs:.1f}", verdict, detail])

    def do(self, step: str, argv: list[str], capkey: str | None = None, it: int = 0, watch: Path | None = None,
           stdin_path: Path | None = None, judge=None) -> tuple[int, str]:
        stall, total, why = CAPS[capkey or step]
        if self.a.dry_run:
            print(f"[dry-run] {step}#{it} stall {stall}s total {total}s ({why})\n    $ "
                  + " ".join(map(str, argv)) + (f" < {stdin_path}" if stdin_path else ""))
            return 0, ""
        rc, out, secs = run_capped(step, argv, stall, total, watch, stdin_path)
        verdict, detail = judge(rc, out) if judge else (("PASS" if rc == 0 else "FAIL"), out.strip().splitlines()[-1] if out.strip() else "")
        if rc in (124, 125):
            verdict = "STALL" if rc == 124 else "TOTAL"
        self.record(step, it, rc, secs, verdict, detail)
        if verdict not in ("PASS", "SKIP") and not self.alive():
            self.dead = True
        return rc, out

    def alive(self) -> bool:
        r = subprocess.run(["ping", "-c2", "-W1", self.ip], capture_output=True, timeout=5)  # 2 pings x 1 s wait
        if r.returncode:
            log(f"DEAD: {self.ip} does not answer ping after a failed step; campaign stops (check console log; no power action here)")
        return r.returncode == 0

    # ---- steps
    def pre(self) -> None:
        remote = ("uname -r; [ -f /etc/openwrt_release ] && echo OPENWRT; grep -m1 BogoMIPS /proc/cpuinfo; "
                  "echo temp $(cat /sys/class/thermal/thermal_zone0/temp); for t in devmem taskset ethtool nft dropbear iperf3; "
                  "do which $t >/dev/null || echo MISSING $t; done; "
                  "for f in /sys/kernel/debug/rteth/rxq /sys/module/rtl838x_eth/parameters /proc/kallsyms /dev/mem; "
                  "do [ -e $f ] || echo MISSING $f; done")

        def judge(rc, out):
            bad = re.findall(r"MISSING \S+|OPENWRT", out)
            bogo = re.search(r"BogoMIPS\s*:\s*([\d.]+)", out)
            return ("PASS" if rc == 0 and not bad else "FAIL"), f"bogo {bogo.group(1) if bogo else '?'} " + " ".join(bad) + " " + " ".join(out.split()[:1])
        self.do("pre", ssh_cmd(self.ip, remote), judge=judge)

    def perf(self) -> None:
        self.do("perf", [PY, str(ROOT / "scripts/perf_push.py"), "--ip", self.ip])

    def natsetup(self) -> None:
        for sub in (["setup"], ["mode", "route"]):
            self.do("natsetup", [str(ROOT / "dev.py"), "nat-bench", *sub])

    def zc(self) -> None:
        def judge(rc, out):
            k = {m[0]: float(m[1]) for m in re.findall(r"(stack|zc): natwan rx \d+ pkts = ([\d.]+) kpps", out)}
            ratio = re.search(r"zc / stack = ([\d.]+)x", out)
            perf = "perf" if "perf report ->" in out else "NOPERF"
            ok = rc == 0 and len(k) == 2 and perf == "perf"
            return ("PASS" if ok else "FAIL"), f"stack {k.get('stack', '?')} kpps zc {k.get('zc', '?')} kpps ratio {ratio.group(1) if ratio else '?'} {perf}"
        for i in range(1, self.a.n + 1):
            if self.dead:
                return
            self.do("zc", [PY, str(ROOT / "scripts/zc_bench.py"), "--secs", "10", "--perf"], it=i, judge=judge)

    def gdma(self) -> None:
        if not self.a.dry_run and not all(k.exists() for k in KO):
            self.record("gdma", 0, 0, 0, "SKIP", "no .ko: build against tmp/build-mips-bench (docs/PLAIN-KERNEL-TESTS.md)")
            return
        for k in KO:
            self.do("gdma", ssh_cmd(self.ip, f"cat > /tmp/{k.name}"), capkey="gdma", stdin_path=k)

        def judge(rc, out):
            reg = len(re.findall(r"memcpy channel", out)) >= 2
            rows = re.findall(r"gdma_bench: len +(\d+) iters \d+: gdma (\d+) ns/xfer \((\d+) MB/s\) cpu memcpy (\d+) ns \((\d+) MB/s\) bad (\d+) fails (\d+)", out)
            bad = sum(int(r[5]) + int(r[6]) for r in rows)
            r4k = next((r for r in rows if r[0] == "4096"), None)
            ok = reg and len(rows) == 8 and bad == 0
            return ("PASS" if ok else "FAIL"), (f"reg {reg} rows {len(rows)} bad+fails {bad} "
                                               + (f"4k gdma {r4k[2]} MB/s cpu {r4k[4]} MB/s" if r4k else "") + ("" if ok else " " + out.strip()[-120:]))
        self.do("gdma", ssh_cmd(self.ip, "ls /sys/class/dma; insmod /tmp/gdma_bench.ko iters=200 2>&1 | tail -n 1; dmesg | grep -i -E 'gdma|memcpy channel'"), judge=judge)

    def dss(self) -> None:
        def judge_probe(rc, out):
            rows = re.findall(r"ws=\d rs=\d ctrl=\S+ polls=(\d+) dss0=\S+ dss1=\S+ count0=(\d+) count1=(\d+)", out)
            notready = sum(1 for r in rows if int(r[0]) >= 4096)
            nonzero = sum(1 for r in rows if int(r[2]) > 0)
            return ("PASS" if rc == 0 and len(rows) == 10 and notready == 0 else "FAIL"), f"rows {len(rows)} not-ready {notready} nonzero-count1 {nonzero}"
        self.do("dss_probe", [PY, str(ROOT / "scripts/dss_probe.py"), "--ip", self.ip, "--tag", f"plain-{self.a.tag}"], judge=judge_probe)
        if self.dead:
            return
        mark = CSV_lines(SOAK_CSV)

        def judge_soak(rc, out):
            new = SOAK_CSV.read_text().splitlines()[mark:] if SOAK_CSV.exists() else []
            fails = sum(1 for ln in new if ",FAIL" in ln or ",STOP" in ln)
            last = new[-1].split(",") if new else []
            return ("PASS" if rc == 0 and len(new) >= 5 and not fails else "FAIL"), \
                f"samples {len(new)} fails {fails} last temp_mC {last[4] if len(last) > 4 else '?'} counts {','.join(last[5:]) if len(last) > 5 else '?'}"
        self.do("dss_soak", [PY, str(ROOT / "scripts/dss_soak.py"), "--ip", self.ip, "--minutes", "1", "--interval", "10",
                             "--load", "2", "--tag", f"plain-{self.a.tag}"], watch=SOAK_CSV, judge=judge_soak)

    def selftest(self) -> None:
        self.do("selftest", [PY, str(ROOT / "scripts/selftest.py"), "--ip", self.ip],
                judge=lambda rc, out: ({0: "PASS", 1: "FAIL"}.get(rc, "NORESULT"), (re.findall(r"st1008f-selftest: .*", out) or [""])[-1]))

    def link(self) -> None:
        remote = "for d in /sys/class/net/lan*; do echo ${d##*/} carrier=$(cat $d/carrier 2>/dev/null) $(cat $d/operstate); done"

        def judge(rc, out):
            up = re.findall(r"(lan\d) carrier=1", out)
            return ("PASS" if "lan1" in up else "FAIL"), "carrier up: " + ",".join(up)
        self.do("link", ssh_cmd(self.ip, remote), judge=judge)

    def vlanproto(self) -> None:
        # patch 644 hook check; port stays DOWN (hook only needs a switch port in the bridge): no laser, no loop, lan1 (mgmt) untouched
        p, br = "lan2", "brvp"
        remote = (f"ip -o addr show dev {p} | grep -q inet && {{ echo ABORT {p} has an address; exit 9; }}; "
                  f"ip link add {br} type bridge && ip link set {p} master {br}; "
                  f"ip link set {br} type bridge vlan_protocol 802.1ad 2>&1; echo RC=$?; "
                  f"ip link set {p} nomaster; ip link del {br}")

        def judge(rc, out):
            m = re.search(r"RC=(\d+)", out)
            if "ABORT" in out or not m:
                return "FAIL", "setup failed: " + out.strip()[-120:]
            if m.group(1) == "0":
                return "FAIL", "silent accept: hook missing or not enforcing"
            ok = "can't be changed on a bridge with switch ports" in out
            return ("PASS" if ok else "FAIL"), ("extack ok" if ok else "wrong error: " + out.strip()[-120:])
        self.do("vlanproto", ssh_cmd(self.ip, remote), judge=judge)

    def checklog(self) -> None:
        self.do("checklog", [PY, str(ROOT / "scripts/boot_log_check.py"), "--boot", "-1"],
                judge=lambda rc, out: ({0: "PASS", 1: "UNKNOWN"}.get(rc, "ERRORS"), (out.strip().splitlines() or [""])[-1]))

    def memstress(self) -> None:
        self.do("memstress", [PY, str(ROOT / "scripts/mem_stress.py")],
                judge=lambda rc, out: ("PASS" if rc == 0 else "FAIL", (re.findall(r"RESULT \w+", out) or [""])[-1]))


def CSV_lines(p: Path) -> int:
    return len(p.read_text().splitlines()) if p.exists() else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP)
    ap.add_argument("--tag", required=True, help="clock set label for the CSV, e.g. stock | picks")
    ap.add_argument("--n", type=int, default=3, help="#149 trigger repeats")
    ap.add_argument("--steps", default=",".join(DEFAULT), help="subset of: " + " ".join(ALL))
    ap.add_argument("--dry-run", action="store_true", help="print commands and caps, touch nothing")
    a = ap.parse_args()
    if a.ip == SW1_IP:
        sys.exit(f"refused: {a.ip} is sw1 (in-service house switch)")
    steps = a.steps.split(",")
    if bad := [s for s in steps if s not in ALL]:
        sys.exit(f"unknown step(s): {bad}")
    c = Campaign(a)
    log(f"=== plain_campaign {a.tag} on {a.ip}: {' '.join(steps)}{' (dry-run)' if a.dry_run else ''}")
    for s in steps:
        if c.dead:
            break
        getattr(c, s)()
    log(f"=== done{' (stopped: board DEAD)' if c.dead else ''}; csv {CSV.relative_to(ROOT)}")
    return 3 if c.dead else 0


if __name__ == "__main__":
    sys.exit(main())
