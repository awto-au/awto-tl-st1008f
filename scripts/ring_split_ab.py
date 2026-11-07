#!/usr/bin/env python3
"""ring_split_ab — two-ring receive split A/B (#146, openwrt/patches/300-43): one route trap, two CPU rings, two VPEs.

- Needs the ring image (tmp/tftp/mainline-7.4-rc1-ring.bin, `./dev.py ramload ... --kernel mainline-7.4-rc1-ring.bin`), bench setup done here.
- Traffic: udpblast 1400 B, 64 flows (source ports 40000+i, one destination port), zc path on both rings (zc_ring 2).
- Fixed: threaded NAPI ring0 -> VPE0 / ring1 -> VPE1, tx_by_cpu=1, eth0 noqueue, CPU queue 0 and 1 drop threshold 1024 pages.
- Variants (n runs each, interleaved): rt0 / rt1 = l3_net_route ring 0 / 1 (baseline); par = rt1 + PIE `sport 1 0 0` / `sport 1 1 1`
  (udpblast varies the source port only: even -> ring 0, odd -> ring 1); par_acl1 = par + acl_hit queue 1 (fallback of the design).
- Per run (whole sender run, counters read idle before/after): kpps, VPE0/VPE1 busy, rx ring frames, tag QID counts, zc per ring, EGR_QUEUE drops;
  per variant and round one udpcheck run (bad payloads, reorder per source port).
- Verdict rule = design on #146: PASS = >= 143 kpps, both VPEs 60-90 %, EGR_QUEUE below rt1, 0 bad, 0 reorder, ring share 40-60 %.
- Log tmp/logs/ring_split_ab.log, rows tmp/logs/ring_split_ab.jsonl.
    python3 scripts/ring_split_ab.py --tag ring1 --n 3 [--variants rt0,rt1,par,par_acl1] [--secs 10] [--dry-run]
"""
import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/ring_split_ab.log"
JSONL = ROOT / "tmp/logs/ring_split_ab.jsonl"
P = "/sys/module/rtl838x_eth/parameters"
D = "/sys/kernel/debug/rteth"
THR_PHYS = 0x1B007DC0  # FC_CPU_Q_EGR_DROP_THR[0]; queue 1 follows at +4 (300-40)
PASS_KPPS = 143.0      # design on #146: forwarding ceiling of the single-ring path at 1400 B
RESET = [f"echo clear > {D}/rxq_pie", f"echo rr > {D}/rxq"]
RULES = [f"echo 'sport 1 0 0 udp' > {D}/rxq_pie", f"echo 'sport 1 1 1 udp' > {D}/rxq_pie"]
VARIANTS = {
    "rt0": [f"echo 'l3_net_route 0' > {D}/rxq"],
    "rt1": [f"echo 'l3_net_route 1' > {D}/rxq"],
    "par": [f"echo 'l3_net_route 1' > {D}/rxq", *RULES],
    "par_acl1": [f"echo 'l3_net_route 1' > {D}/rxq", f"echo 'acl_hit 1' > {D}/rxq", *RULES],
}
SSH_LOADED_S = 60  # ssh while a VPE is 100 % busy: 20 s default timed out under load; 60 s = stall rule
KNOBS = {"napi_thread": "on", "tx_by_cpu": "1", "qdisc": "noqueue"}  # + ring N NAPI thread pinned to VPE N (pin_napi)


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def parse_rxq(text):
    out = {}
    for ln in text.splitlines():
        f = ln.split()
        if len(f) == 2 and f[1].isdigit() and not f[0].startswith("pie_rule"):
            out[f[0]] = int(f[1])
    return out


def snapshot(nb, zb, dev):
    """rx counter first (local, fast), then rxq + /proc/stat in one ssh call."""
    t = time.monotonic()
    rx = zb.rx(dev)
    out = nb.sw(f"cat {D}/rxq; grep -E '^cpu[01] ' /proc/stat", tmo=SSH_LOADED_S)
    cpu = {}
    for ln in out.splitlines():
        if ln.startswith("cpu"):
            f = [int(x) for x in ln.split()[1:9]]
            cpu[ln.split()[0]] = (sum(f), f[3] + f[4])
    return {"t": t, "rx": rx, "rxq": parse_rxq(out), "cpu": cpu}


def busy(a, b, k, dt):
    """Non-idle jiffies of the run over its wall time (USER_HZ 100); idle ticks after the run do not count."""
    return 100 * ((b["cpu"][k][0] - a["cpu"][k][0]) - (b["cpu"][k][1] - a["cpu"][k][1])) / (100 * dt)


def one_run(nb, zb, dc, secs, ln, flows):
    """Counters read idle before and after the run: ssh to the board stalls while a loaded ring carries the control plane."""
    dev = f"{nb.HOST_NIC}.992"
    cmd = ["sudo", "-n", "ip", "netns", "exec", "natlan", str(ROOT / "tmp/udpblast"), "10.99.1.2", "10.99.2.2", "5201",
           str(ln), str(secs), str(flows)]
    dc.snap()  # clear-on-read: the next read counts this run only
    a = snapshot(nb, zb, dev)
    t0 = time.monotonic()
    subprocess.run(cmd, capture_output=True, text=True, timeout=secs * 3 + 30)  # sender stops itself at secs
    b = snapshot(nb, zb, dev)  # rx counter first, so the tail after the sender is not counted as run time
    drops = dc.delta([0] * dc.N, dc.snap())
    dt = b["t"] - t0
    d = {k: b["rxq"].get(k, 0) - a["rxq"].get(k, 0) for k in b["rxq"]}
    rings = [d.get("ring0_frames", 0), d.get("ring1_frames", 0)]
    return {
        "kpps": (b["rx"] - a["rx"]) / dt / 1000, "window_s": round(dt, 2), "vpe0": busy(a, b, "cpu0", dt), "vpe1": busy(a, b, "cpu1", dt),
        "rings": rings, "share0": rings[0] / max(1, sum(rings)),
        "tagqid": {k: v for k, v in d.items() if k.startswith("tagqid") and v},
        "zc": {k: v for k, v in d.items() if "zc_" in k}, "egr_queue": drops.get("EGR_QUEUE", 0), "drops": drops,
    }


def integrity(nb, ln, flows, secs=3):
    chk = subprocess.Popen(["sudo", "-n", "ip", "netns", "exec", "natwan", str(ROOT / "tmp/udpcheck"), "5201", str(secs + 1), str(ln)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    chk.stdout.readline()  # "ready" after bind
    subprocess.run(["sudo", "-n", "ip", "netns", "exec", "natlan", str(ROOT / "tmp/udpblast"), "10.99.1.2", "10.99.2.2", "5201",
                    str(ln), str(secs), str(flows), "1"], capture_output=True, text=True, timeout=secs * 3 + 30)
    out, _ = chk.communicate(timeout=30)  # udpcheck exits at secs+1
    f = out.split()
    try:
        return {"good": int(f[f.index("good") + 1]), "bad": int(f[f.index("bad") + 1]), "reorder": int(f[f.index("reorder") + 1])}
    except (ValueError, IndexError):
        return {"good": 0, "bad": -1, "reorder": -1, "raw": out.strip()}


def pin_napi(nb):
    """napi/eth0-<id> thread of ring N -> VPE N, ids from the driver's napi_id_ringN lines."""
    ids = parse_rxq(nb.sw(f"cat {D}/rxq"))
    cmd = [f"for t in $(ps | awk '/napi\\/eth0-{ids[f'napi_id_ring{r}']}\\]/{{print $1}}'); do taskset -p {1 << r} $t; done"
           for r in (0, 1)]
    nb.sw("; ".join(cmd))
    return nb.sw("ps | grep 'napi/eth0'").replace("\n", " ")


def prepare(nb, nk, zb, a):
    for sub in ([] if a.no_setup else (["setup"], ["mode", "route"])):
        subprocess.run([str(ROOT / "dev.py"), "nat-bench", *sub], capture_output=True, text=True, timeout=240)  # ~20 ssh round trips
    if "rxq_pie" not in nb.sw(f"ls {D}"):
        sys.exit("kernel has no rteth/rxq_pie: boot tmp/tftp/mainline-7.4-rc1-ring.bin (300-43)")
    nk.apply(KNOBS)
    log("napi threads: " + pin_napi(nb) + " | pins " + nb.sw(nk.KNOBS["napi_pin"]["read"]).strip() + " | tx_by_cpu " + nb.sw(nk.KNOBS["tx_by_cpu"]["read"]).strip()
        + " | qdisc " + nb.sw(nk.KNOBS["qdisc"]["read"]).strip())
    nb.sw(f"echo {zb.NATWAN_MAC} > {P}/zc_dmac; echo 992 > {P}/zc_vid; echo 5201 > {P}/zc_dport; echo 10,99,2,1 > {P}/zc_sip; "
          f"echo 1000 > {P}/zc_sport_add; echo 2 > {P}/zc_ring; echo 1 > {P}/rx_qid_stats; echo 1 > {P}/zc")
    on = a.cpuq0
    v = (on << 16) | (on - 16)
    cur = [int(x, 16) for x in nb.sw(f"devmem 0x{THR_PHYS:08X} 32; devmem 0x{THR_PHYS + 4:08X} 32").split()]
    if cur[0] != v:  # boot without rtl838x_eth.cpuq0_drop_pages: same register write the driver does
        nb.sw(f"devmem 0x{THR_PHYS:08X} 32 0x{v:08X}")
    log(f"drop threshold q0 0x{cur[0]:08X} -> 0x{v:08X}, q1 0x{cur[1]:08X}; zc_ring "
        + nb.sw(f"cat {P}/zc_ring").strip() + ", rx_qid_stats " + nb.sw(f"cat {P}/rx_qid_stats").strip())


def finish(nb):
    nb.sw(f"echo 0 > {P}/zc; echo 1 > {P}/zc_ring; echo 0 > {P}/rx_qid_stats; echo 0 > {P}/zc_sport_add; "
          f"echo clear > {D}/rxq_pie; echo rr > {D}/rxq", check=False, tmo=SSH_LOADED_S)


def verdict(name, rows, base):
    k = statistics.mean(r["kpps"] for r in rows)
    v0, v1 = (statistics.mean(r[x] for r in rows) for x in ("vpe0", "vpe1"))
    drops = statistics.mean(r["egr_queue"] for r in rows)
    sh = statistics.mean(r["share0"] for r in rows)
    bad = sum(r["integrity"]["bad"] for r in rows)
    reo = sum(r["integrity"]["reorder"] for r in rows)
    crit = {"kpps>=143": k >= PASS_KPPS, "VPEs 60-90": 60 <= v0 <= 90 and 60 <= v1 <= 90,
            "drops<rt1": base is not None and drops < base["drops"], "bad==0": bad == 0, "reorder==0": reo == 0,
            "share 40-60": 0.4 <= sh <= 0.6}
    if name in ("rt0", "rt1"):
        return f"baseline ({'ring ' + name[2]})", crit
    if not crit["share 40-60"]:
        return "STEERING NOT EFFECTIVE: ring frames not ~50/50 (rule or ACL queue ignored)", crit
    if all(crit.values()):
        return "PASS", crit
    both = v0 >= 60 and v1 >= 60
    if k <= PASS_KPPS and both:
        if base and k < base["kpps"] * 0.98:
            return "FAIL: rate drops with both VPEs busy (shared 34Kc pipeline)", crit
        return "FAIL: <= 143 kpps with both VPEs busy (ceiling is the chip-to-NIC transfer)", crit
    return "FAIL: " + ", ".join(c for c, ok in crit.items() if not ok), crit


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--secs", type=int, default=10)
    ap.add_argument("--len", type=int, default=1400)
    ap.add_argument("--flows", type=int, default=64)
    ap.add_argument("--cpuq0", type=int, default=1024, help="queue 0 drop threshold pages (0x7DC0)")
    ap.add_argument("--variants", default=",".join(VARIANTS))
    ap.add_argument("--no-setup", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the plan only; no board, no host traffic")
    a = ap.parse_args()
    variants = a.variants.split(",")
    bad = [v for v in variants if v not in VARIANTS]
    if bad:
        sys.exit(f"unknown variants {bad}; have {list(VARIANTS)}")
    if a.dry_run:
        print(f"plan {a.tag}: n={a.n} secs={a.secs} len={a.len} flows={a.flows} cpuq0={a.cpuq0}")
        print("  fixed:", KNOBS, "| zc_ring 2, rx_qid_stats 1, zc on (NAT params as zc_bench --nat)")
        for v in variants:
            print(f"  {v}:", *RESET, *VARIANTS[v], sep="\n    ")
        return 0
    import drop_counters as dc
    dc.READ_S = SSH_LOADED_S
    import nat_bench as nb
    import nat_knobs as nk
    import zc_bench as zb
    if nb.SW_IP == "192.168.25.48":
        sys.exit("refusing sw1")
    prepare(nb, nk, zb, a)
    res = {}
    try:
        for rnd in range(1, a.n + 1):
            for v in variants:
                out = nb.sw("; ".join([*RESET, *VARIANTS[v], f"cat {D}/rxq_pie"]), check=False)
                log(f"round {rnd} {v}: rules: {' | '.join(x for x in out.splitlines() if x.startswith('pie_rule')) or 'none'}")
                r = one_run(nb, zb, dc, a.secs, a.len, a.flows)
                r["integrity"] = integrity(nb, a.len, a.flows)
                res.setdefault(v, []).append(r)
                JSONL.open("a").write(json.dumps({"tag": a.tag, "round": rnd, "variant": v, **r}) + "\n")
                log(f"round {rnd} {v}: {r['kpps']:.1f} kpps VPE0/1 {r['vpe0']:.0f}/{r['vpe1']:.0f}% rings {r['rings']} "
                    f"tagqid {r['tagqid']} zc {r['zc']} EGR_QUEUE {r['egr_queue']} integrity {r['integrity']}")
    finally:
        finish(nb)
    log(f"SUMMARY {a.tag}")
    base = None
    if "rt1" in res:
        base = {"kpps": statistics.mean(r["kpps"] for r in res["rt1"]), "drops": statistics.mean(r["egr_queue"] for r in res["rt1"])}
    for v in variants:
        rows = res.get(v)
        if not rows:
            continue
        ks = [r["kpps"] for r in rows]
        m = statistics.mean(ks)
        text, crit = verdict(v, rows, base)
        log(f"  {v:8s} mean {m:6.1f} kpps (min {min(ks):.1f} max {max(ks):.1f} spread {(max(ks) - min(ks)) / m * 100:.1f}%) "
            f"VPE0/1 {statistics.mean(r['vpe0'] for r in rows):.0f}/{statistics.mean(r['vpe1'] for r in rows):.0f}% "
            f"ring0 share {statistics.mean(r['share0'] for r in rows) * 100:.0f}% EGR_QUEUE {statistics.mean(r['egr_queue'] for r in rows):.0f} "
            f"bad {sum(r['integrity']['bad'] for r in rows)} reorder {sum(r['integrity']['reorder'] for r in rows)} -> {text}")
        if not text.startswith("baseline"):
            log("    criteria: " + ", ".join(f"{c} {'ok' if ok else 'NO'}" for c, ok in crit.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
