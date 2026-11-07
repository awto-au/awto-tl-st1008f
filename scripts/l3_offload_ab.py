#!/usr/bin/env python3
"""l3_offload_ab: 300-17 L3 offload A/B matrix on a booted OpenWrt-ours image (docs/ROUTING-OFFLOAD.md, #59).

- Cases: v4 on-link, v4 default, v6 on-link, v6 default. Each: params 0 (baseline) vs offload on.
- Per state: iperf3 TCP -P 4, fwd and reverse, n runs each; Mbit/s, CPU0/CPU1 busy, eth0 pps, ASIC rows.
- Then checks a b c d e f i (g optional, h not scripted). Bench unit sw2 only (refuses sw1 and any other IP).
- Outputs: tmp/logs/l3_offload_ab.log, tmp/logs/l3_offload_ab-<ts>.csv / .txt.  `--dry-run` prints every step.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import json
import re
import signal
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from boards import BENCH_IP, SW1_IP  # noqa: E402
import nat_bench as nb  # noqa: E402  (import has no side effects beyond a sysfs read)

LOG = ROOT / "tmp/logs/l3_offload_ab.log"
TS = time.strftime("%Y%m%d-%H%M%S")
CSV_PATH = ROOT / f"tmp/logs/l3_offload_ab-{TS}.csv"
TXT_PATH = ROOT / f"tmp/logs/l3_offload_ab-{TS}.txt"
PARAMS = ("l3_onlink", "l3_default_v4", "l3_default_v6")
POLL_S = nb.L3_POLL_S              # l3.c poll (DELAY_PROBE_TIME)
SETTLE_S = 2 * nb.L3_SETTLE_S      # 2 polls x 1.25: parameter applied at one poll, gateway refreshed at the next (check a: > 6.25 s, ok at 20 s)
RUN_MEASURED_S = 14                # 10 s + 2 s omit + ~2 s snapshots (nat_bench.log 2026-11-06: 13-14 s)
CHECK_CAP_S = 70                   # a check = up to 3 settle waits (12.5 s) + ssh + pings (~20 s); x1.25
SETUP_CAP_S = 90                   # setup+mode+v6-setup+dflt-setup ~20 s observed; x3 + ssh mux start
OFFLOAD_CAP_S = 40                 # settle 12.5 s + a few ssh (0.3 s idle, 20 s cap each)
DRY = False
T_START = time.monotonic()
BACKSTOP_S = 2700                  # 48 runs x 14 s + params/checks ~ 900 s measured-estimate; x3

# case: (name, family, params for offload, run kind, targets that must read fwd when on)
CASES = [
    ("v4-onlink", 4, {"l3_onlink": 1, "l3_default_v4": 0, "l3_default_v6": 0}, nb.H_WAN,
     [("host", f"{nb.H_LAN}/32"), ("host", f"{nb.H_WAN}/32")]),
    ("v4-default", 4, {"l3_onlink": 1, "l3_default_v4": 1, "l3_default_v6": 0}, nb.FAR4,
     [("host", f"{nb.H_LAN}/32"), ("host", f"{nb.H_WAN}/32"), ("dflt", "4")]),
    ("v6-onlink", 6, {"l3_onlink": 1, "l3_default_v4": 0, "l3_default_v6": 0}, None,
     [("host", f"{nb.V6[nb.LAN_VID][1]}/128"), ("host", f"{nb.V6[nb.WAN_VID][1]}/128")]),
    ("v6-default", 6, {"l3_onlink": 0, "l3_default_v4": 0, "l3_default_v6": 1}, nb.FAR6,
     [("dflt", "6")]),
]
ALL_ON = {"l3_onlink": 1, "l3_default_v4": 1, "l3_default_v6": 1}
ALL_OFF = {"l3_onlink": 0, "l3_default_v4": 0, "l3_default_v6": 0}


class StepTimeout(Exception):
    pass


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {'[dry-run] ' if DRY else ''}{msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


@contextlib.contextmanager
def cap(seconds: float, what: str):
    """Hard cap per step (SIGALRM); expiry names the step. Dry run: print only."""
    if DRY:
        log(f"cap {seconds:.0f} s: {what}")
        yield
        return
    if time.monotonic() - T_START > BACKSTOP_S:
        raise StepTimeout(f"run backstop {BACKSTOP_S} s exceeded before: {what}")

    def _h(*_):
        raise StepTimeout(f"{what}: no completion in {seconds:.0f} s")
    old = signal.signal(signal.SIGALRM, _h)
    signal.alarm(int(seconds + 0.999))
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def sw(cmd: str, check: bool = False) -> str:
    if DRY:
        log(f"ssh root@{BENCH_IP} {cmd!r}")
        return ""
    return nb.sw(cmd, check=check)


def host(cmd: list[str], check: bool = False) -> str:
    if DRY:
        log("sudo " + " ".join(cmd))
        return ""
    return nb.host(cmd, check=check)


def svi(vid: int) -> str:
    return f"switch.{vid}" if DRY else nb.svi(vid)


def alive() -> bool:
    return subprocess.run(["ping", "-c1", "-W1", BENCH_IP], capture_output=True).returncode == 0


def link_ready() -> bool:
    """Setup pings right after the VLAN add; the bridge port forwards ~4 s later (STP, fd 2 s). Poll 1 ping/s, 8 s."""
    for _ in range(8):  # STP forward ~4 s measured (CLAUDE.md), x2
        if ping_ns(nb.NS_LAN, nb.H_WAN):  # via the switch; fw4 input rejects pings to the SVI itself
            return True
    return False


# ---- ASIC table ---------------------------------------------------------------
def get_routes() -> str:
    return sw(f"grep -E 'TABLE|10\\.99|198\\.51|fd99|2001:db8|/0 ' {nb.L3_DBG}/routes; true")


def parse_rows(text: str) -> list[dict]:
    rows = []
    for ln in text.splitlines():
        f = ln.split()
        if len(f) >= 12 and f[0] in ("host", "prefix") and f[1].isdigit():
            rows.append({"kind": f[0], "idx": int(f[1]), "width": f[5], "hit": f[8], "dest": f[9],
                         "action": f[10], "nh": int(f[11]), "flags": " ".join(f[13:])})
    return rows


def row_state(rows: list[dict], tgt: tuple[str, str]) -> str:
    """fwd | trap | absent. dflt = lowest-IDX /0 row of the family (the catch-all is last, NH 0 trap)."""
    kind, sel = tgt
    if kind == "host":
        m = [r for r in rows if r["kind"] == "host" and r["dest"] == sel]
        return m[0]["action"] if m else "absent"
    z = "0.0.0.0/0" if sel == "4" else "::/0"
    d = sorted((r for r in rows if r["kind"] == "prefix" and r["dest"] == z), key=lambda r: r["idx"])
    return d[0]["action"] if len(d) >= 2 else ("single" if d else "absent")


def compact(rows: list[dict]) -> str:
    keep = [r for r in rows if r["dest"] != "::1/128"]
    return ";".join(f"{r['kind']} {r['dest']} {r['action']} NH{r['nh']} hit{r['hit']}{' ' + r['flags'] if r['flags'] else ''}"
                    for r in keep)


def wait_state(targets: list, want_fwd: bool, what: str) -> bool:
    """Poll the table once a second until targets read fwd (or are absent / not fwd); limit SETTLE_S."""
    if DRY:
        log(f"wait <= {SETTLE_S} s: {what}")
        return True
    t0 = time.time()
    while True:
        rows = parse_rows(get_routes())
        st = [row_state(rows, t) for t in targets]
        ok = all(s == "fwd" for s in st) if want_fwd else all(s != "fwd" for s in st)
        if ok:
            log(f"wait ok {what}: {time.time() - t0:.1f} s")
            return True
        if time.time() - t0 > SETTLE_S:
            log(f"WAIT EXPIRED {what}: states {st} after {time.time() - t0:.1f} s (limit {SETTLE_S} s)")
            return False
        time.sleep(1)  # l3.c applies changes at its next 5 s poll; 1 s sampling is plenty


def set_params(p: dict) -> bool:
    if DRY:
        log("./dev.py nat-bench offload " + " ".join(f"--{k[3:].replace('_', '-')} {v}" for k, v in p.items()))
        return True
    with cap(OFFLOAD_CAP_S, f"offload {p}"):
        return nb.offload(p["l3_onlink"], p["l3_default_v4"], p["l3_default_v6"]) == 0


# ---- one iperf cell -----------------------------------------------------------
def jsonl_since(off: int) -> list[dict]:
    if not nb.JSONL.exists():
        return []
    data = nb.JSONL.read_bytes()[off:].decode(errors="replace")
    return [json.loads(x) for x in data.splitlines() if x.strip()]


def one_run(case: str, fam: int, dst: str | None, state: str, rev: bool, i: int, secs: int, streams: int) -> dict:
    label = f"l3ab-{case}-{state}-{'rev' if rev else 'fwd'}{i}"
    cli = (f"nat_bench run --secs {secs} -P {streams} --dst {dst}{' --reverse' if rev else ''}" if fam == 4 else
           f"nat_bench v6-run --secs {secs} -P {streams}{' --onlink' if dst is None else f' --dst {dst}'}"
           f"{' --reverse' if rev else ''}")
    out = {"case": case, "state": state, "dir": "rev" if rev else "fwd", "run": i, "label": label}
    if DRY:
        log(f"cap {3 * (secs + 4)} s: ./dev.py {cli.replace('nat_bench', 'nat-bench')}")
        return out
    off = nb.JSONL.stat().st_size if nb.JSONL.exists() else 0
    try:
        with cap(3 * (secs + 4), cli):
            if fam == 4:
                ns = argparse.Namespace(label=label, reverse=rev, P=streams, udp=None, len=1460, secs=secs, dst=dst)
                rc = nb.run(ns, False)
            else:
                rc = nb.v6_run(secs, streams, dst is None, dst, rev)
    except (StepTimeout, SystemExit, json.JSONDecodeError, subprocess.TimeoutExpired) as e:
        out["error"] = f"{type(e).__name__}: {e}"[:200]
        log(f"RUN FAILED {label}: {out['error']}")
        return out
    rows = jsonl_since(off)
    if rc or not rows:
        out["error"] = f"rc {rc}, no result row"
        return out
    r = rows[-1]
    cpu = r.get("cpu", {})
    out.update(mbps=r["mbps"], retrans=r.get("retrans"),
               cpu0_busy=cpu.get("cpu0", {}).get("busy"), cpu1_busy=cpu.get("cpu1", {}).get("busy"),
               cpu0_softirq=cpu.get("cpu0", {}).get("softirq"),
               eth0_rx_pps=r["eth0_rx_pps"], eth0_tx_pps=r["eth0_tx_pps"], irq_per_s=r["irq_per_s"],
               asic=compact(parse_rows(get_routes())))  # HIT bits as left by this run
    return out


def run_case(c: tuple, n: int, secs: int, streams: int, results: list) -> None:
    name, fam, on, dst, targets = c
    log(f"=== case {name}: baseline params 0 vs {on}")
    for state, params in (("base", ALL_OFF), ("offload", on)):
        applied = set_params(params)
        rows_ok = wait_state(targets, state == "offload", f"{name} {state} rows")
        if state == "offload" and not DRY:
            # warm both neighbours: natwan -> natlan (the 2nd host row needs a neighbour event)
            host(["ip", "netns", "exec", nb.NS_WAN, "ping", "-c", "1", "-W", "1", nb.H_LAN])
            rows_ok = wait_state(targets, True, f"{name} {state} rows after ping") and rows_ok
        for rev in (False, True):
            for i in range(1, n + 1):
                r = one_run(name, fam, dst, state, rev, i, secs, streams)
                r.update(applied=applied, rows_ok=rows_ok, temp=temp_c(), when=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
                results.append(r)
                log(f"  {r['label']}: {r.get('mbps', r.get('error'))} Mbit/s cpu0 {r.get('cpu0_busy')} "
                    f"cpu1 {r.get('cpu1_busy')} eth0 {r.get('eth0_rx_pps')}/{r.get('eth0_tx_pps')} pps")


# ---- checks -------------------------------------------------------------------
def tgt_state(tgt: tuple) -> str:
    return row_state(parse_rows(get_routes()), tgt)


def ping_ns(ns: str, dst: str) -> bool:
    if DRY:
        host(["ip", "netns", "exec", ns, "ping", "-c", "1", "-W", "1", dst])
        return True
    r = subprocess.run(["sudo", "-n", "ip", "netns", "exec", ns, "ping", "-c", "1", "-W", "1", dst],
                       capture_output=True, text=True, timeout=10)  # 1 ping, 1 s wait + margin
    return r.returncode == 0


def chk_a():
    t = ("host", f"{nb.H_WAN}/32")
    sw(f"ip neigh del {nb.H_WAN} dev {svi(nb.WAN_VID)}")
    s1, d1 = tgt_state(t), tgt_state(("dflt", "4"))
    ping_ns(nb.NS_LAN, nb.H_WAN)
    back = wait_state([t, ("dflt", "4")], True, "a rows back")
    return (s1 != "fwd" and d1 != "fwd" and back), f"after del: /32 {s1}, dflt4 {d1}; after ping back={back}"


def chk_b():
    nic = f"{nb.HOST_NIC}.{nb.WAN_VID}"
    new, old = "02:99:00:00:09:93", f"02:99:00:00:{nb.WAN_VID // 100:02d}:{nb.WAN_VID % 100:02d}"
    host(["ip", "-n", nb.NS_WAN, "link", "set", nic, "address", new])
    try:
        ping_ns(nb.NS_WAN, nb.SW_WAN)  # natwan ARPs the switch with its new MAC: neighbour update
        t0, seen = time.time(), False
        while not DRY and time.time() - t0 <= SETTLE_S and not seen:
            seen = new in sw(f"cat {nb.L3_DBG}/nexthops")
            if not seen:
                time.sleep(1)  # poll nexthops 1 s apart inside the settle limit
        flows = ping_ns(nb.NS_LAN, nb.H_WAN)
    finally:
        host(["ip", "-n", nb.NS_WAN, "link", "set", nic, "address", old])
        ping_ns(nb.NS_WAN, nb.SW_WAN)
        wait_state([("host", f"{nb.H_WAN}/32")], True, "b rows after MAC restore")
    return (seen and flows), f"new MAC in nexthops={seen}, ping natlan->natwan={flows}"


def chk_c():
    t = ("host", f"{nb.H_WAN}/32")
    sw(f"ip route add 10.99.2.0/25 via {nb.H_LAN} dev {svi(nb.LAN_VID)}")
    gone = wait_state([t], False, "c row torn down")
    sw("ip route del 10.99.2.0/25")
    ping_ns(nb.NS_LAN, nb.H_WAN)
    back = wait_state([t], True, "c row back")
    return (gone and back), f"torn down={gone}, back after del+ping={back}"


def chk_d():
    t = ("host", f"{nb.H_WAN}/32")
    sw(f"ip addr add {nb.H_WAN}/32 dev {svi(nb.WAN_VID)}")
    gone = wait_state([t], False, "d neighbour row gone")
    rows = parse_rows(get_routes())
    local = [r for r in rows if r["kind"] == "host" and r["dest"] == f"{nb.H_WAN}/32"]
    local_trap = bool(local) and local[0]["action"] == "trap"
    sw(f"ip addr del {nb.H_WAN}/32 dev {svi(nb.WAN_VID)}")
    ping_ns(nb.NS_LAN, nb.H_WAN)
    back = wait_state([t], True, "d row back")
    return (gone and local_trap and back), f"neighbour row gone={gone}, local /32 trap={local_trap}, back={back}"


def chk_e():
    ts = [("host", f"{nb.H_LAN}/32"), ("host", f"{nb.H_WAN}/32"), ("dflt", "4")]
    n0 = sw("dmesg | grep -c 'forwarding offload suspended'").strip()
    sw(f"ip rule add from {nb.H_LAN} table 100")
    trapped = wait_state(ts, False, "e v4 rows trap")
    n1 = sw("dmesg | grep -c 'forwarding offload suspended'").strip()
    sw(f"ip rule del from {nb.H_LAN} table 100")
    resumed = wait_state(ts, True, "e v4 rows resume")
    return (trapped and resumed and n1 != n0), f"rows trap={trapped}, dmesg 'suspended' {n0}->{n1}, resumed={resumed}"


def chk_f():
    t = ("dflt", "6")
    gw = nb.V6[nb.WAN_VID][1]
    out = sw(f"ip -6 route add ::/0 from fd99:11::/64 via {gw} dev {svi(nb.WAN_VID)} 2>&1; echo rc=$?")
    if "rc=0" not in out and not DRY:
        return None, f"route add refused ({out.strip()[-80:]}): kernel without IPV6_SUBTREES?"
    trapped = wait_state([t], False, "f v6 default trap")
    sw(f"ip -6 route del ::/0 from fd99:11::/64 via {gw} dev {svi(nb.WAN_VID)}")
    set_params({**ALL_ON, "l3_default_v6": 0})
    set_params(ALL_ON)
    back = wait_state([t], True, "f v6 default back")
    return (trapped and back), f"source-specific default: trap={trapped}, back after 0->1={back}"


def chk_g():
    """120 s HW-forwarded run, neighbour state sampled every 10 s: never FAILED (--with-g only)."""
    if DRY:
        log("g: nat_bench run --secs 120 in background, ip neigh sampled every 10 s")
        return True, "dry"
    p = subprocess.Popen([sys.executable, str(ROOT / "scripts/nat_bench.py"), "run", "--secs", "120", "-P", "4",
                          "--label", "l3ab-g"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    seen = []
    t0 = time.time()
    while p.poll() is None and time.time() - t0 < 160:  # 120 s + 2 omit + ssh; x1.25 = 160
        seen.append(sw(f"ip neigh show dev {svi(nb.WAN_VID)} | grep -o '{nb.H_WAN}.*'").strip().split()[-1:] or ["?"])
        time.sleep(10)  # the spec asks for a sample every 10 s
    p.kill()
    states = [s[0] for s in seen]
    bad = "FAILED" in states
    nov = sw("dmesg | grep -c 'no valid neighbour'").strip()
    return (not bad and nov == "0"), f"states {sorted(set(states))}, 'no valid neighbour' dmesg={nov}"


def chk_i():
    ts = [("host", f"{nb.H_LAN}/32"), ("host", f"{nb.H_WAN}/32"), ("dflt", "4"), ("dflt", "6")]
    set_params(ALL_OFF)
    ok = wait_state(ts, False, "i all rows non-fwd")
    return ok, f"neighbour rows gone and default rows trap={ok}"


def run_checks(with_g: bool) -> list[tuple[str, str, str]]:
    res = []
    log("=== checks (ROUTING-OFFLOAD.md a..i), all three params on")
    set_params(ALL_ON)
    ping_ns(nb.NS_LAN, nb.H_WAN)
    wait_state([("host", f"{nb.H_LAN}/32"), ("host", f"{nb.H_WAN}/32"), ("dflt", "4"), ("dflt", "6")], True, "checks precondition")
    plan = [("a", chk_a), ("b", chk_b), ("c", chk_c), ("d", chk_d), ("e", chk_e), ("f", chk_f)]
    if with_g:
        plan.append(("g", chk_g))
    for cid, fn in plan:
        try:
            with cap(CHECK_CAP_S if cid != "g" else 220, f"check {cid}"):
                ok, why = fn()
            v = "DRY" if DRY else "NOTRUN" if ok is None else ("PASS" if ok else "FAIL")
        except (StepTimeout, SystemExit, subprocess.TimeoutExpired) as e:
            v, why = "FAIL", f"{type(e).__name__}: {e}"[:200]
        log(f"check {cid}: {v} ({why})")
        res.append((cid, v, why))
        if v == "FAIL":  # leave no stray state for the next check
            sw(f"ip route del 10.99.2.0/25 2>/dev/null; ip addr del {nb.H_WAN}/32 dev {svi(nb.WAN_VID)} 2>/dev/null; "
               f"ip rule del from {nb.H_LAN} table 100 2>/dev/null; true")
            ping_ns(nb.NS_LAN, nb.H_WAN)
            wait_state([("host", f"{nb.H_WAN}/32")], True, "post-fail re-arm")
    if not with_g:
        res.append(("g", "NOTRUN", "120 s run; use --with-g"))
    res.append(("h", "NOTRUN", "martian DIPs need scapy raw frames; not scripted"))
    try:
        with cap(CHECK_CAP_S, "check i"):
            ok, why = chk_i()
        v = "DRY" if DRY else "PASS" if ok else "FAIL"
    except (StepTimeout, SystemExit) as e:
        v, why = "FAIL", str(e)[:200]
    log(f"check i: {v} ({why})")
    res.append(("i", v, why))
    return sorted(res)


# ---- context ------------------------------------------------------------------
def temp_c() -> str:
    """Thermal zone (deg C) if the image has one, else the SoC meter byte (uncalibrated, #13)."""
    if DRY:
        return ""
    out = sw("cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -1; echo ==; "
             "grep -i '^006c' /sys/kernel/debug/regmap/dummy-ethernet-switch@0x1b000000/registers 2>/dev/null; true")
    z, _, m = out.partition("==")
    if z.strip().isdigit():
        return f"{int(z.strip()) / 1000:.1f}C"
    mm = re.search(r"006c:?\s+([0-9a-fA-F]{8})", m)
    if mm and int(mm[1], 16) & (1 << 24):
        return f"meter{(int(mm[1], 16) >> 16) & 0xFF}"
    return ""


def local(cmd: list[str]) -> str:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)  # local query, ms
        return (r.stdout or r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"? {e}"


def context(clocks: str, image: Path) -> dict:
    c = {"date": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "bench_ip": BENCH_IP, "clocks_ramload": clocks,
         "repo_head": local(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"]),
         "repo_dirty": bool(local(["git", "-C", str(ROOT), "status", "--porcelain", "openwrt/", "scripts/"])),
         "host_kernel": local(["uname", "-r"]), "host_iperf3": local(["iperf3", "--version"]).splitlines()[0:1],
         "host_nic": nb.HOST_NIC, "host_nic_driver": local(["ethtool", "-i", nb.HOST_NIC]).replace("\n", "; ")[:160]}
    p = sorted((ROOT / "openwrt/patches").glob("300-17*"))
    c["patch_300_17"] = f"{p[0].name} sha256 {hashlib.sha256(p[0].read_bytes()).hexdigest()[:12]}" if p else "missing"
    c["image_file"] = (f"{image.name} {image.stat().st_size} B mtime "
                       f"{time.strftime('%Y-%m-%dT%H:%M:%S%z', time.localtime(image.stat().st_mtime))} "
                       f"sha256 {hashlib.sha256(image.read_bytes()).hexdigest()[:16]}") if image.exists() else "missing"
    if DRY:
        log("context: git/uname/ethtool local; switch: uname -r, /etc/openwrt_release, /proc/cmdline, BogoMIPS, "
            "ethtool lan1, params")
        return c
    s = sw("uname -r; echo ==; cat /etc/openwrt_release; echo ==; cat /proc/cmdline; echo ==; "
           "grep -i bogomips /proc/cpuinfo; echo ==; ethtool lan1 2>/dev/null | grep -E 'Speed|Link detected'; "
           "ethtool -m lan1 2>/dev/null | grep -E 'Vendor name|Vendor PN|Vendor SN'; echo ==; "
           f"grep . {nb.L3_PARAMS}/l3_* 2>/dev/null; echo ==; cat /sys/kernel/debug/clk/clk_summary 2>/dev/null | head -12")
    k, rel, cmd, bogo, eth, par, clk = (x.strip() for x in (s.split("==\n") + [""] * 7)[:7])
    c.update(switch_kernel=k, openwrt_release=rel.replace("\n", "; "), cmdline=cmd, bogomips=bogo.replace("\n", "; "),
             lan1=eth.replace("\n", "; "), params=par.replace("\n", "; "), clk_summary=clk[:300], temp_start=temp_c())
    return c


# ---- results ------------------------------------------------------------------
def med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def fmt(x, nd=0):
    return "-" if x is None else f"{x:.{nd}f}"


def results_block(results: list, checks: list, ctx: dict, n: int, secs: int, streams: int) -> str:
    L = [f"## L3 offload A/B {ctx['date']}  (TCP -P {streams}, {secs} s, n={n} per cell; median [min-max] Mbit/s)", ""]
    L.append("| Path | Dir | Base | Offload | CPU0 busy base/off % | CPU1 busy base/off % | eth0 pps base/off |")
    L.append("|---|---|---|---|---|---|---|")
    for c in CASES:
        for d in ("fwd", "rev"):
            cell = {}
            for st in ("base", "offload"):
                rs = [r for r in results if r["case"] == c[0] and r["state"] == st and r["dir"] == d and "mbps" in r]
                m = [r["mbps"] for r in rs]
                cell[st] = (f"{fmt(med(m))} [{fmt(min(m)) if m else '-'}..{fmt(max(m)) if m else '-'}]",
                            fmt(med([r["cpu0_busy"] for r in rs]), 1), fmt(med([r["cpu1_busy"] for r in rs]), 1),
                            fmt(med([r["eth0_rx_pps"] + r["eth0_tx_pps"] for r in rs])))
            b, o = cell["base"], cell["offload"]
            L.append(f"| {c[0]} | {d} | {b[0]} | {o[0]} | {b[1]}/{o[1]} | {b[2]}/{o[2]} | {b[3]}/{o[3]} |")
    L.append("")
    bad = [r["label"] for r in results if "error" in r]
    nrow = [r["label"] for r in results if r.get("rows_ok") is False]
    L.append(f"- Failed runs: {bad or 'none'}. Cells whose expected ASIC rows were not seen in the settle window: {sorted(set(nrow)) or 'none'}.")
    for c in CASES:
        rs = [r for r in results if r["case"] == c[0] and r["state"] == "offload" and r.get("asic")]
        if rs:
            L.append(f"- ASIC rows after {c[0]} offload run: {rs[-1]['asic']}")
    L.append("- Checks: " + "; ".join(f"{cid} {v}" for cid, v, _ in checks))
    for cid, v, why in checks:
        if v != "PASS":
            L.append(f"  - {cid} {v}: {why}")
    L.append("- Context: " + "; ".join(f"{k}={v}" for k, v in ctx.items() if k not in ("date", "clk_summary")))
    return "\n".join(L)


def write_csv(results: list) -> None:
    cols = ["when", "case", "state", "dir", "run", "mbps", "retrans", "cpu0_busy", "cpu1_busy", "cpu0_softirq",
            "eth0_rx_pps", "eth0_tx_pps", "irq_per_s", "applied", "rows_ok", "temp", "asic", "error", "label"]
    with CSV_PATH.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in results:
            w.writerow({"when": r.get("when", ""), **r})


def main() -> int:
    global DRY
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--settle", type=float, default=0, help="override the settle limit (s); default 1.25 x l3.c poll")
    ap.add_argument("--ip", default=BENCH_IP, help="must be the bench unit sw2")
    ap.add_argument("--dry-run", action="store_true", help="print every step and cap, touch nothing")
    ap.add_argument("--secs", type=int, default=10)
    ap.add_argument("-n", type=int, default=3, help="runs per cell and direction")
    ap.add_argument("-P", type=int, default=4)
    ap.add_argument("--only", default="", help="comma list of cases: " + ",".join(c[0] for c in CASES))
    ap.add_argument("--no-setup", action="store_true", help="nat_bench setup/mode/v6-setup/dflt-setup already done")
    ap.add_argument("--no-checks", action="store_true")
    ap.add_argument("--with-g", action="store_true", help="also check g (120 s run)")
    ap.add_argument("--teardown", action="store_true", help="nat_bench teardown at the end")
    ap.add_argument("--clocks", default="unknown", help="ramload clock line used, recorded (e.g. 'turbo cpu=1350,ddr=662,lx=306,sram=500' or 'stock')")
    ap.add_argument("--image", default=str(ROOT / "tmp/tftp/openwrt-ours-initramfs.bin"))
    a = ap.parse_args()
    DRY = a.dry_run
    if a.settle:
        global SETTLE_S
        SETTLE_S = a.settle
    if a.ip == SW1_IP or a.ip != BENCH_IP or nb.SW_IP != BENCH_IP:
        print(f"refused: {a.ip} is not the bench unit sw2 ({BENCH_IP}); sw1 {SW1_IP} is the house switch", file=sys.stderr)
        return 2
    cases = [c for c in CASES if not a.only or c[0] in a.only.split(",")]
    log(f"=== l3_offload_ab {' '.join(sys.argv[1:])} (board {a.ip})")
    if not DRY and not alive():
        log(f"FAIL: {a.ip} does not answer ping; boot first (see docs/ROUTING-OFFLOAD.md phase-2 recipe)")
        return 1
    results: list = []
    checks: list = []
    ctx: dict = {}
    rc = 0
    try:
        ctx = context(a.clocks, Path(a.image))
        log("context: " + json.dumps(ctx, default=str))
        if not DRY:
            if nb.mainline():
                log("FAIL: switch runs the mainline initramfs, not OpenWrt-ours (ssh bench flow differs)")
                return 1
            if not sw(f"ls {nb.L3_PARAMS}/l3_onlink 2>/dev/null; true").strip():
                log("FAIL: no l3_onlink parameter: image without 300-17")
                return 1
        if not a.no_setup:
            with cap(SETUP_CAP_S, "setup + mode route + v6-setup + dflt-setup"):
                steps = [("setup", nb.setup), ("mode route", lambda: nb.set_mode("route")),
                         ("v6-setup", nb.v6_setup), ("dflt-setup", nb.dflt_setup)]
                for name, fn in steps:
                    if DRY:
                        log(f"./dev.py nat-bench {name}")
                    elif fn() and name != "setup":  # setup's SVI ping needs the fw4 accept that `mode` adds
                        raise SystemExit(f"setup step failed: {name}")
                    if name == "mode route" and not DRY and not link_ready():
                        raise SystemExit("natlan cannot reach natwan through the switch after mode route")
        for c in cases:
            run_case(c, a.n, a.secs, a.P, results)
        if not a.no_checks:
            checks = run_checks(a.with_g)
        else:
            set_params(ALL_OFF)
    except StepTimeout as e:
        rc = 1
        log(f"TIMEOUT: {e}; board {'answers' if alive() else 'DOES NOT answer'} ping (no power action taken)")
    except SystemExit as e:
        rc = 1
        log(f"ABORT: {e}")
    finally:
        if not DRY:
            with contextlib.suppress(Exception):
                if alive():
                    with cap(OFFLOAD_CAP_S, "final params 0"):
                        set_params(ALL_OFF)
                    if a.teardown:
                        with cap(SETUP_CAP_S, "teardown"):
                            nb.teardown()
    if DRY:
        log("dry run done: nothing written")
        return 0
    write_csv(results)
    block = results_block(results, checks, ctx, a.n, a.secs, a.P)
    TXT_PATH.write_text(block + "\n")
    for ln in block.splitlines():
        log(ln)
    log(f"csv {CSV_PATH}  txt {TXT_PATH}")
    if rc == 0 and (any("error" in r for r in results) or any(v == "FAIL" for _, v, _ in checks)):
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
