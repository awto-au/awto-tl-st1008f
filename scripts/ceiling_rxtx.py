#!/usr/bin/env python3
"""ceiling_rxtx — CPU-port ceiling by direction: rx-only (rxdrop) vs tx-only (pktgen) per frame size (docs/CAMPAIGN-PLAIN-7.4.md).

- Precondition: plain bench kernel booted (`./dev.py ramload ... mainline-kernel --mgmt`); nat-bench setup + mode route done here.
- rx: nat_bench rxdrop (UDP flood host -> lan1.991, dropped at ingress); per run ASIC drop counters (clear-on-read)
  and CPU queue peaks (FC_CPU_Q_EGR_PAGE_CNT / PKT_CNT, clear-on-read) around it.
- tx: nat_bench-style pktgen on lan1 -> VLAN 992 -> host natwan; far-end rx counted on the host NIC.
- Sizes are UDP payload bytes (rx: flood payload; tx: pktgen frame = size + 42).
- Output: tmp/logs/ceiling_rxtx.log, tmp/logs/ceiling_rxtx.jsonl
    python3 scripts/ceiling_rxtx.py --tag picks --n 3 [--sizes 64,200,...] [--modes rx,tx] [--secs 8]
"""
import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drop_counters as dc  # noqa: E402
import nat_bench as nb  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/ceiling_rxtx.log"
JSONL = ROOT / "tmp/logs/ceiling_rxtx.jsonl"
PHYS = 0x1B000000
PAGE, PKT, THR = 0x7E40, 0x7EC0, 0x7DC0
PG_COUNT = 100_000  # pktgen frames per run: ~0.3-1 s at the expected 150-400 kpps; pktgen timeout in nb.pktgen = count/5000*1.25+10


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def devmem(off, n=4):
    cmd = "; ".join(f"devmem 0x{PHYS + off + 4 * q:08X} 32" for q in range(n))
    return [int(x, 16) for x in nb.sw(cmd).split()]


def queue_peaks():
    """Per CPU queue peak pages / packets since the last read (clear-on-read)."""
    pg, pk = devmem(PAGE), devmem(PKT)
    return {"pages": [(v >> 16) & 0x7FFF for v in pg], "pkts": [(v >> 16) & 0x1FFF for v in pk]}


def thresholds():
    return [{"on": (v >> 16) & 0xFFF, "off": v & 0xFFF} for v in devmem(THR)]


def last_row(label):
    for ln in reversed(JSONL_NB.read_text().splitlines()):
        r = json.loads(ln)
        if r["label"] == label:
            return r
    raise SystemExit(f"no nat_bench row {label}")


JSONL_NB = nb.JSONL


def host_rx():
    out = nb.host(["ip", "netns", "exec", nb.NS_WAN, "cat", f"/sys/class/net/{nb.HOST_NIC}.{nb.WAN_VID}/statistics/rx_packets"])
    return int(out.strip())


def one_rx(size, secs, xdp=None):
    dc.snap()
    queue_peaks()
    nb.rxdrop(secs, size, xdp)
    row = last_row(f"rxdrop-{size}B" + (f"-xdp-{xdp}" if xdp else ""))
    drops = dc.delta([0] * dc.N, dc.snap())
    qp = queue_peaks()
    return {"kpps": row["eth0_rx_pps"] / 1e3, "sent_kpps": row["sent"] / secs / 1e3,
            "vpe0": row["cpu"].get("cpu0", {}).get("busy"), "vpe1": row["cpu"].get("cpu1", {}).get("busy"), "drops": drops, "qpeak": qp, "ns_per_pkt": row["ns_vpe_per_pkt"]}


def one_tx(size):
    dc.snap()
    queue_peaks()
    h0 = host_rx()
    a = nb.snap()
    nb.pktgen(PG_COUNT, size + 42)
    b = nb.snap()
    far = host_rx() - h0
    row = last_row(f"pktgen-tx-{size + 42}B")
    m = re.search(r"(\d+)\(c\d+\+d\d+\) usec, (\d+) .*?(\d+)pps", row["result"])
    usec, cnt, pps = (int(x) for x in m.groups())
    drops = dc.delta([0] * dc.N, dc.snap())
    qp = queue_peaks()
    cpu = row["cpu"]
    eth_tx = (b["eth0"]["tx_packets"] - a["eth0"]["tx_packets"]) % 2**32
    return {"kpps": pps / 1e3, "far_kpps": round(far / (usec / 1e6) / 1e3, 1), "far_ratio": round(far / cnt, 4), "eth_tx": eth_tx,
            "vpe1": cpu.get("cpu1", {}).get("busy"), "vpe0": cpu.get("cpu0", {}).get("busy"), "drops": drops, "qpeak": qp}


def one_tx2(size):
    """pktgen on both VPEs (lan1@0 on kpktgend_0, lan1@1 on kpktgend_1): the generator is the limit of `tx` (VPE0 94 % busy)."""
    mac = nb.host(["ip", "netns", "exec", nb.NS_WAN, "cat", f"/sys/class/net/{nb.HOST_NIC}.{nb.WAN_VID}/address"]).strip()
    pg, d = "/proc/net/pktgen", nb.SW_PORT
    cfg = [f"echo rem_device_all > {pg}/kpktgend_{t}" for t in (0, 1)]
    for t in (0, 1):
        cfg.append(f"echo add_device {d}@{t} > {pg}/kpktgend_{t}")
        cfg += [f"echo '{c}' > {pg}/{d}@{t}" for c in (
            f"count {PG_COUNT}", "clone_skb 0", f"pkt_size {size + 42}", "delay 0", f"dst {nb.H_WAN}", f"dst_mac {mac}",
            f"src_min {nb.SW_WAN}", f"src_max {nb.SW_WAN}", f"vlan_id {nb.WAN_VID}", "udp_dst_min 9", "udp_dst_max 9", f"queue_map_min 0", "queue_map_max 0")]
    nb.sw(" && ".join(cfg))
    dc.snap()
    queue_peaks()
    h0 = host_rx()
    a = nb.snap()
    nb.sw(f"echo start > {pg}/pgctrl", tmo=PG_COUNT / 5000 * 1.25 + 10)  # pgctrl start blocks until both threads finish
    b = nb.snap()
    far = host_rx() - h0
    res = [nb.sw(f"grep -A2 Result {pg}/{d}@{t}") for t in (0, 1)]
    ms = [re.search(r"(\d+)\(c\d+\+d\d+\) usec, (\d+) .*?(\d+)pps", " ".join(r.split())) for r in res]
    pps = [int(m.group(3)) for m in ms]
    usec = max(int(m.group(1)) for m in ms)
    cpu = nb.cpu_report(a, b)
    nb.sw(f"echo rem_device_all > {pg}/kpktgend_0; echo rem_device_all > {pg}/kpktgend_1")
    eth_tx = (b["eth0"]["tx_packets"] - a["eth0"]["tx_packets"]) % 2**32
    return {"kpps": sum(pps) / 1e3, "per_thread_kpps": [p / 1e3 for p in pps], "far_kpps": round(far / (usec / 1e6) / 1e3, 1),
            "far_ratio": round(far / (2 * PG_COUNT), 4), "eth_tx": eth_tx, "vpe0": cpu["cpu0"]["busy"], "vpe1": cpu["cpu1"]["busy"],
            "drops": dc.delta([0] * dc.N, dc.snap()), "qpeak": queue_peaks()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tag", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--secs", type=int, default=8)
    ap.add_argument("--sizes", default="64,200,500,800,1100,1400")
    ap.add_argument("--modes", default="rx,rxx,tx", help="rx = drop at netdev ingress; rxx = generic XDP drop, before GRO/DSA rx (#140; native drv mode is not supported); tx = pktgen")
    ap.add_argument("--napi", choices=["irq", "irq1"], default="irq1", help="irq1 = NIC IRQ + softirq on VPE1 (as the forwarding benches)")
    ap.add_argument("--no-setup", action="store_true")
    a = ap.parse_args()
    if not a.no_setup:
        nb.setup()
        nb.set_mode("route")
    if a.napi == "irq1":
        nb.sw("echo 0 > /sys/class/net/eth0/threaded; echo 2 > /proc/irq/$(awk '/eth0/{print +$1}' /proc/interrupts)/smp_affinity")
    log(f"start tag {a.tag}: CPU queue thresholds (on/off pages) {thresholds()}")
    for size in (int(s) for s in a.sizes.split(",")):
        for mode in a.modes.split(","):
            runs = []
            for i in range(a.n):
                r = one_tx(size) if mode == "tx" else one_tx2(size) if mode == "tx2" else one_rx(size, a.secs, "skb" if mode == "rxx" else None)
                log(f"{mode} {size} B run {i + 1}/{a.n}: {json.dumps(r)}")
                runs.append(r)
                with JSONL.open("a") as fh:
                    fh.write(json.dumps({"tag": a.tag, "mode": mode, "size": size, "run": i + 1, "when": time.strftime("%Y-%m-%dT%H:%M:%S%z"), **r}) + "\n")
            k = [r["kpps"] for r in runs]
            sp = (max(k) - min(k)) / statistics.mean(k) * 100
            log(f"SUMMARY {mode} {size} B: {statistics.mean(k):.1f} kpps spread {sp:.1f} % n={len(k)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
