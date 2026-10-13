#!/usr/bin/env python3
"""spg_test — staged checks of the RTL9303 Smart Packet Generator through `rtk spg` (#70, docs/SPG.md).

- Prereq: our U-Boot at `st1008f-mainline # ` (`./dev.py ramload uboot-mainline`). Runs `rtk network on`
  if `rtk spg` says it is off (lasers parked off, loop guard on).
- stage1: read-only. `rtk spg status` + md.l of every SPG register (global, PB access, page index,
  per-cage-port block, IPG); cross-checks the two views.
- stage2: one DARK cage (status says `dark`: module with laser off and no RX light preferred, else an
  empty cage; none -> FAIL "no dark cage"). Burst --count frames; pass = `result DONE|COUNT` and the
  port-MIB sent count == count (SPG's own counter reads 0). TIMEOUT with link down -> one retry with `force-link`.
  Then an informational run with --ipg-probe to time the IPG_LEN unit.
- stage3: cage 1 (laser on, fibre to the house switch) -> host --nic. storm_watch armed first; host
  capture = AF_PACKET as root (sudo -n), ethertype 0x88b5 + our SA; pass = host frames == count == sent,
  no socket drops, storm_watch rc 0. Without root: host rx_packets delta only = UNVERIFIED (rc 3).
- Log: tmp/logs/spg_test.log; results appended to tmp/logs/spg_test.jsonl.
"""

import argparse
import json
import re
import select
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # the _capture child runs as root: no root-owned __pycache__
sys.path.insert(0, str(Path(__file__).resolve().parent))
import hw_probe  # noqa: E402
from st1008_ramload import Console, network_on  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/spg_test.log"
JSONL = ROOT / "tmp/logs/spg_test.jsonl"
hw_probe.LOG = LOG
PROMPT = r"\r?\nst1008f-mainline # "
SW = 0xBB000000
CAGE_PORT = [0, 8, 16, 20, 24, 25, 26, 27]
ETYPE = 0x88B5
SA = "02:00:00:00:70:01"           # locally administered, unicast
DA_DARK = "02:00:00:00:70:02"      # stage2: nothing listens
# `rtk spg status`: 8 cages x (A0 96 B + A2 128 B at 100 kHz ~ 25 ms, 50 kHz fallback +45 ms)
# + ~3 KB of text at 115200 (~0.3 s) ~ 0.9 s worst; cap 1.25x.
STATUS_CAP_S = 1.2
# load: <= 391 PB writes + 391 reads (switch bus, us each) + 3 lines; md.l rule of thumb (hw_probe.CAP_S)
LOAD_CAP_S = 1.0
# start: the plan line follows the lit check (I2C <= 70 ms) and a 400 B print (~35 ms); cap 1.25x + poll
PLAN_CAP_S = 0.5
# after the plan: the board's own limit + result print (~20 ms) + 50 ms expect poll
RESULT_OVERHEAD_S = 0.1
CAPTURE_CAP_S = 10  # root capture child: whole stage3 burst window; expiry = parent never sent stop

STATUS_RE = re.compile(r"cage (\d) port\s+(\d+): sent (\d+), cnt (\d+):(\d+), ipg (\d+), index 0x([0-9a-f]+), "
                       r"link (up|down), (LIT|dark) \(([^)]*)\)")
GLB_RE = re.compile(r"SPG_GLB 0x([0-9a-f]{8}) \(mode (\w+), tx_cmd (\w+)\), TX_GRP 0x([0-9a-f]+), "
                    r"TX_DONE 0x([0-9a-f]+)")
PLAN_RE = r"(auto-stop at TX_DONE or (\d+) us[^\n]*|spg: [^\n]*(?:refused|first|unknown)[^\n]*)\n"
RES_RE = re.compile(r"spg: result (\w+) sent (\d+) of (\d+)(?: \(port MIB\))?, tx_done 0x([0-9a-f]+) \(before 0x([0-9a-f]+)\), "
                    r"elapsed (\d+) us \(expected (\d+), limit (\d+)\)")


def log(msg: str) -> None:
    hw_probe.log(msg)


def record(row: dict) -> None:
    row["when"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    with JSONL.open("a") as fh:
        fh.write(json.dumps(row) + "\n")


def rtk(con: Console, cmd: str, cap: float, what: str) -> str:
    _, out = con.run(cmd, PROMPT, cap, what)
    return out


def status(con: Console) -> str:
    out = rtk(con, "rtk spg status", STATUS_CAP_S, "rtk spg status")
    if "rtk network on` first" in out:
        log("network is off: running `rtk network on` (lasers parked, loop guard)")
        network_on(con, "st1008f-mainline #")
        out = rtk(con, "rtk spg status", STATUS_CAP_S, "rtk spg status")
    if not GLB_RE.search(out):
        raise SystemExit(f"FAIL: no SPG_GLB line in status: {out[-300:]!r}")
    return out


def cages(out: str) -> dict[int, dict]:
    res = {}
    for m in STATUS_RE.finditer(out):
        res[int(m[1])] = {"port": int(m[2]), "sent": int(m[3]), "cnt": (int(m[4]) << 32) | int(m[5]),
                          "ipg": int(m[6]), "index": int(m[7], 16), "link": m[8], "lit": m[9] == "LIT",
                          "why": m[10]}
    return res


def load(con: Console, port: int, length: int, da: str, extra: str = "") -> None:
    out = rtk(con, f"rtk spg load {port} 0 {length} {length} {da} {SA} incr {extra}".strip(), LOAD_CAP_S,
              f"spg load port {port}")
    if "verify ok" not in out:
        raise SystemExit(f"FAIL: load port {port}: {out.strip()[-300:]}")
    log("  " + next(ln for ln in out.splitlines() if "spg: loaded" in ln).strip())


def start(con: Console, port: int, count: int, opts: str = "") -> dict:
    """Plan line first (or a refusal), then the result with the board's own limit as the cap."""
    mark = con.size()
    con.send_checked(f"rtk spg start {port} 0 {count} {opts}".strip())
    m, txt = con.expect(PLAN_RE, PLAN_CAP_S, mark, f"spg start port {port} plan")
    if not m[2]:
        con.expect(PROMPT, PLAN_CAP_S, mark, "prompt after refusal")
        return {"result": "REFUSED", "line": m[1].strip()}
    log("  " + m[1].strip())
    limit_s = int(m[2]) / 1e6
    m2, txt = con.expect(RES_RE.pattern + r"[\s\S]*?" + PROMPT, limit_s * 1.25 + RESULT_OVERHEAD_S, mark,
                         f"spg result (board limit {limit_s * 1e3:.1f} ms)")
    r = RES_RE.search(txt)
    row = {"result": r[1], "sent": int(r[2]), "count": int(r[3]), "tx_done": r[4], "tx_done_before": r[5],
           "elapsed_us": int(r[6]), "expected_us": int(r[7]), "limit_us": int(r[8]),
           "notes": [ln.strip() for ln in txt.splitlines() if ln.startswith("spg: ") and "result" not in ln
                     and "plan" not in ln]}
    log(f"  result {row['result']}: sent {row['sent']}/{row['count']}, elapsed {row['elapsed_us']} us "
        f"(expected {row['expected_us']}), tx_done 0x{row['tx_done']} (before 0x{row['tx_done_before']})")
    for n in row["notes"]:
        log("  " + n)
    return row


# ---- stage 1 ---------------------------------------------------------------------------
def stage1(con: Console) -> int:
    out = status(con)
    for ln in out.splitlines():
        if ln.startswith(("spg:", "cage ", "  s")):
            log("  " + ln.rstrip())
    g = GLB_RE.search(out)
    md = {}
    for name, off, n in [("SPG_GLB/TX_GRP/GLOBAL_STS", 0x7AB0, 3), ("PKB_ACC_DEBUG/PB_ACCESS_CTRL0-2", 0xDCEC, 4),
                         ("SPG_GLOBAL_INDEX_CTRL0[0..27]", 0xDCFC, 28), ("MAC_L2_GLOBAL_CTRL0", 0xC700, 1)]:
        md[name] = hw_probe.md(con, SW + off, n, name)
    for p in CAGE_PORT:
        md[f"port {p} block"] = hw_probe.md(con, SW + 0x67E4 + 0x60 * p, 15, f"SPG port {p} 0x67e4 block")
        md[f"port {p} ipg"] = hw_probe.md(con, SW + 0x328C + 0x40 * p, 1, f"SPG_PORT_IPG_CTRL {p}")
    bad = [k for k, v in md.items() if isinstance(v, str)]
    if bad:
        log(f"FAIL: md.l errors: {bad}")
        return 1
    mism = []
    glb = md["SPG_GLB/TX_GRP/GLOBAL_STS"]
    if glb[0] != int(g[1], 16) or glb[1] & 0x0FFFFFFF != int(g[4], 16) or glb[2] & 0x0FFFFFFF != int(g[5], 16):
        mism.append(f"global: md {[hex(x) for x in glb]} vs status {g[0]}")
    for c, d in cages(out).items():
        blk, ipg = md[f"port {d['port']} block"], md[f"port {d['port']} ipg"][0] & 0xFFFFF
        want = {"cnt": (blk[0] << 32) | blk[1], "sent": (blk[2] << 32) | blk[3], "index": blk[14], "ipg": ipg}
        for k, v in want.items():
            if d[k] != v:
                mism.append(f"cage {c} {k}: status {d[k]} vs md {v}")
    for k, v in md.items():
        log(f"  md {k}: " + " ".join(f"{x:08x}" for x in v))
    mac0 = md["MAC_L2_GLOBAL_CTRL0"][0]
    log(f"  MAC_L2_GLOBAL_CTRL0 IPG comp: 10G {mac0 >> 18 & 1}, 2.5G {mac0 >> 20 & 1}, 1G {mac0 >> 22 & 1}")
    idle = glb[1] & 0x0FFFFFFF == 0 and (glb[0] >> 1 & 3) in (0, 2, 3)
    record({"stage": 1, "glb": f"{glb[0]:08x}", "grp": f"{glb[1]:08x}", "sts": f"{glb[2]:08x}", "idle": idle,
            "mismatch": mism, "ipg": {p: md[f"port {p} ipg"][0] & 0xFFFFF for p in CAGE_PORT}})
    for x in mism:
        log("  MISMATCH " + x)
    log(f"stage1 {'PASS' if not mism and idle else 'FAIL'}: generator {'idle' if idle else 'NOT idle'}, "
        f"{len(mism)} status/md mismatches")
    return 0 if not mism and idle else 1


# ---- stage 2 ---------------------------------------------------------------------------
def pick_dark(cs: dict[int, dict]) -> int | None:
    dark = [c for c, d in sorted(cs.items()) if not d["lit"]]
    with_module = [c for c in dark if cs[c]["why"].startswith("laser off")]
    return (with_module or dark or [None])[0]


def stage2(con: Console, count: int, ipg_probe: int) -> int:
    cs = cages(status(con))
    for c, d in sorted(cs.items()):
        log(f"  cage {c} port {d['port']}: {'LIT' if d['lit'] else 'dark'} ({d['why']}), link {d['link']}")
    cage = pick_dark(cs)
    if cage is None:
        log("stage2 FAIL: no dark cage (every cage lit, copper/DAC, or unreadable)")
        record({"stage": 2, "result": "no dark cage"})
        return 1
    port = cs[cage]["port"]
    log(f"stage2: cage {cage} port {port} ({cs[cage]['why']})")
    load(con, port, 64, DA_DARK)
    row = start(con, port, count)
    opts = ""
    if row["result"] == "TIMEOUT" and cs[cage]["link"] == "down":
        log("  TIMEOUT on a down link: retry with force-link")
        opts = "force-link"
        row = start(con, port, count, opts)
    held = cages(status(con))[cage]["sent"]
    # sent = port MIB ifOutUcastPkts delta (rtk spg); `held` = SPG PKT_CNT_DBG, reads 0 on this chip (#70)
    ok = row["result"] in ("DONE", "COUNT") and row["sent"] == count
    log(f"stage2 {'PASS' if ok else 'FAIL'}: {row['result']}, sent {row['sent']}, held counter {held}, count {count}")
    record({"stage": 2, "cage": cage, "port": port, "opts": opts, "held": held, **row})
    if ok and ipg_probe:
        p = start(con, port, count, f"{ipg_probe} {opts}".strip())
        if p["sent"]:
            ns = p["elapsed_us"] * 1000 / p["sent"]
            log(f"  ipg-probe {ipg_probe}: {ns:.0f} ns/frame measured vs {p['expected_us'] * 1000 / count:.0f} "
                f"expected (byte-time IPG at the link rate); ratio {ns / (p['expected_us'] * 1000 / count):.2f}")
        record({"stage": 2, "probe_ipg": ipg_probe, **p})
    return 0 if ok else 1


# ---- stage 3 ---------------------------------------------------------------------------
def nic_rx(nic: str) -> int:
    return int(Path(f"/sys/class/net/{nic}/statistics/rx_packets").read_text())


def stage3(con: Console, count: int, ipg: int, nic: str, watch_s: float) -> int:
    if count > 1000:
        raise SystemExit("stage3 count is capped at 1000 (allow-lit)")
    host_mac = Path(f"/sys/class/net/{nic}/address").read_text().strip()
    rtk(con, "rtk laser 1", 1, "laser cage 1 only")
    cs = cages(status(con))
    c1 = cs.get(1)
    if not c1 or c1["link"] != "up":
        log(f"stage3 FAIL: cage 1 link {c1 and c1['link']} ({c1 and c1['why']}): fibre to the house switch?")
        return 1
    # storm_watch: 3 s baseline then armed; runs past the burst so a late loop is caught too
    sw = subprocess.Popen([sys.executable, str(ROOT / "scripts/storm_watch.py"), "--nic", nic, "--duration",
                           str(watch_s)], stdout=subprocess.PIPE, text=True)
    t0 = time.monotonic()
    for line in sw.stdout:  # "ARMED" ~3.5 s after start (baseline 3 s + ethtool); cap 5 s below
        if "ARMED" in line:
            break
        if time.monotonic() - t0 > 5:
            sw.kill()
            raise SystemExit("TIMEOUT 5s: storm_watch did not arm")
    log(f"  storm_watch armed ({watch_s:.0f} s window)")
    root = subprocess.run(["sudo", "-n", "true"], capture_output=True, timeout=5).returncode == 0  # 5 s = sudo prompt hang
    cap = None
    if root:
        cap = subprocess.Popen(["sudo", "-n", sys.executable, "-B", "-I", str(Path(__file__).resolve()), "_capture",
                                "--nic", nic, "--src", SA, "--cap", str(CAPTURE_CAP_S)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        if cap.stdout.readline().strip() != "ready":  # child binds in ms; a sudo failure ends the pipe
            raise SystemExit("FAIL: capture child did not start")
    rx0 = nic_rx(nic)
    load(con, 0, 128, host_mac)
    row = start(con, 0, count, f"{ipg} allow-lit")
    rx1 = nic_rx(nic)
    host = None
    if cap:
        out, _ = cap.communicate("stop\n", timeout=CAPTURE_CAP_S)
        host = json.loads(out.strip().splitlines()[-1])
        log(f"  host capture: {host['frames']} frames from {SA} (lens {host['lens']}, payload ok "
            f"{host['payload_ok']}), socket drops {host['drops']}")
    rc_sw = sw.wait(timeout=watch_s + 5)  # storm_watch ends at its own --duration
    log(f"  storm_watch rc {rc_sw} ({'no storm' if rc_sw == 0 else 'STORM: relay cut'})")
    log(f"  host {nic} rx_packets delta {rx1 - rx0} (all traffic)")
    if host is None:
        log("stage3 UNVERIFIED: no root for AF_PACKET capture (sudo -n); host rx delta is not exact")
        record({"stage": 3, "verified": False, "rx_delta": rx1 - rx0, "storm_rc": rc_sw, **row})
        return 3
    ok = (row["result"] in ("DONE", "COUNT") and row["sent"] == count and host["frames"] == count
          and host["drops"] == 0 and rc_sw == 0)
    log(f"stage3 {'PASS' if ok else 'FAIL'}: switch sent {row['sent']}, host got {host['frames']}, count {count}")
    record({"stage": 3, "verified": True, "host": host, "storm_rc": rc_sw, "rx_delta": rx1 - rx0, **row})
    return 0 if ok else 1


# ---- root capture child ------------------------------------------------------------------
def capture(nic: str, src: str, cap_s: float) -> int:
    srcb = bytes.fromhex(src.replace(":", ""))
    s = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(ETYPE))
    s.setsockopt(socket.SOL_SOCKET, 33, 16 << 20)  # SO_RCVBUFFORCE: 1000 frames x skb truesize >> default
    s.bind((nic, ETYPE))
    s.setblocking(False)
    print("ready", flush=True)
    frames, lens, bad = 0, set(), 0

    def drain() -> None:
        nonlocal frames, bad
        while True:
            try:
                f = s.recv(4096)
            except BlockingIOError:
                return
            if f[6:12] != srcb:
                continue
            frames += 1
            lens.add(len(f))
            pay = f[14:]
            bad += pay != bytes(i & 0xFF for i in range(len(pay)))

    t0 = time.monotonic()
    while time.monotonic() - t0 < cap_s:
        r, _, _ = select.select([s, sys.stdin], [], [], 0.1)
        if s in r:
            drain()
        if sys.stdin in r:
            sys.stdin.readline()
            break
    else:
        print(f"capture: cap {cap_s}s reached without stop", file=sys.stderr)
    drain()
    pk, drops = struct.unpack("II", s.getsockopt(263, 6, 8))  # SOL_PACKET, PACKET_STATISTICS
    print(json.dumps({"frames": frames, "lens": sorted(lens), "payload_ok": frames - bad, "drops": drops,
                      "sock_packets": pk}), flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="stage", required=True)
    sub.add_parser("stage1")
    s2 = sub.add_parser("stage2")
    s2.add_argument("--count", type=int, default=1000)
    s2.add_argument("--ipg-probe", type=int, default=1000, help="second run's IPG_LEN (0 = skip)")
    s3 = sub.add_parser("stage3")
    s3.add_argument("--count", type=int, default=1000)
    s3.add_argument("--ipg", type=int, default=10000, help="IPG_LEN: ~8 us/frame at 10G if byte times")
    s3.add_argument("--nic", default="enp7s0")
    s3.add_argument("--watch", type=float, default=15, help="storm_watch window, s (3 s baseline included)")
    c = sub.add_parser("_capture")
    c.add_argument("--nic", required=True)
    c.add_argument("--src", required=True)
    c.add_argument("--cap", type=float, required=True)
    a = ap.parse_args()
    if a.stage == "_capture":
        return capture(a.nic, a.src, a.cap)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    log(f"=== spg_test {a.stage}")
    con = Console()
    con.run("", PROMPT, 1, "our U-Boot prompt")  # prompt echo < 10 ms; 1 s names a wrong prompt / dead console
    if a.stage == "stage1":
        return stage1(con)
    if a.stage == "stage2":
        return stage2(con, a.count, a.ipg_probe)
    return stage3(con, a.count, a.ipg, a.nic, a.watch)


if __name__ == "__main__":
    sys.exit(main())
