#!/usr/bin/env python3
"""Generate docs/NAT-REPORT.html (self-contained, inline SVG, no JS/CDN).

- Numbers: jsonl under tmp/logs where present (nat161, zc_prefetch_ab),
  canary_baseline.json, else the doc tables named in each `# src:` comment.
- Series actually plotted are logged to tmp/logs/nat_report.log.
- Host only, no hardware.
"""
import html
import json
import os
import statistics as st
import subprocess
import sys
from pathlib import Path


def repo_root():
    env = os.environ.get("ST1008F_REPO")
    if env:
        return Path(env)
    try:
        out = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, cwd=Path(__file__).resolve().parent, check=True)
        return Path(out.stdout.strip())
    except Exception:
        return Path(__file__).resolve().parent.parent


ROOT = repo_root()
LOGDIR = ROOT / "tmp" / "logs"
OUT = ROOT / "docs" / "NAT-REPORT.html"
LOG_LINES = []
E = html.escape


def log(msg):
    LOG_LINES.append(msg)


def mean(v):
    return sum(v) / len(v)


def jsonl(name):
    rows = []
    p = LOGDIR / name
    if p.exists():
        for line in p.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


# ---------------------------------------------------------------- svg helpers
W = 520


def svg_open(h, label):
    return (f'<svg viewBox="0 0 {W} {h}" role="img" aria-label="{E(label)}" '
            f'xmlns="http://www.w3.org/2000/svg">')


def fmt(v, d=1):
    return f"{v:.{d}f}"


def hbars(title, rows, xmax, unit, xmin=0, label_w=170, row_h=24, ticks=None,
          refline=None, diverge=False):
    """rows: (label, value, cls, annot). cls: win|tie|lose|neutral|target."""
    log(f"chart '{title}':")
    for r in rows:
        log(f"  {r[0]} = {fmt(r[1], 2)} {unit} [{r[2]}] {r[3] if len(r) > 3 else ''}")
    top, bot = 8, 34
    h = top + row_h * len(rows) + bot
    pw = W - label_w - 70
    x0 = label_w

    def sx(v):
        return x0 + (v - xmin) / (xmax - xmin) * pw

    out = [svg_open(h, title)]
    ticks = ticks or [xmin, (xmin + xmax) / 2, xmax]
    for t in ticks:
        out.append(f'<line class="grid" x1="{sx(t):.1f}" y1="{top}" x2="{sx(t):.1f}" y2="{h - bot + 4}"/>')
        out.append(f'<text class="tick" x="{sx(t):.1f}" y="{h - bot + 17}" text-anchor="middle">{fmt(t, 0)}</text>')
    out.append(f'<text class="axis" x="{x0 + pw / 2:.1f}" y="{h - 4}" text-anchor="middle">{E(unit)}</text>')
    zero = sx(0) if diverge else x0
    out.append(f'<line class="base" x1="{zero:.1f}" y1="{top}" x2="{zero:.1f}" y2="{h - bot + 4}"/>')
    if refline:
        rv, rl = refline
        out.append(f'<line class="ref" x1="{sx(rv):.1f}" y1="{top}" x2="{sx(rv):.1f}" y2="{h - bot + 4}"/>')
        out.append(f'<text class="tick" x="{sx(rv) - 3:.1f}" y="{top + 9}" text-anchor="end">{E(rl)}</text>')
    for i, r in enumerate(rows):
        label, v, cls = r[0], r[1], r[2]
        annot = r[3] if len(r) > 3 else ""
        y = top + i * row_h
        bw = abs(sx(v) - zero)
        bx = min(sx(v), zero)
        out.append(f'<text class="lbl" x="{label_w - 6}" y="{y + row_h / 2 + 4}" text-anchor="end">{E(label)}</text>')
        out.append(f'<rect class="b-{cls}" x="{bx:.1f}" y="{y + 3}" width="{max(bw, 1):.1f}" height="{row_h - 8}" rx="2"/>')
        tx = (sx(v) + 5) if v >= 0 or not diverge else (sx(v) - 5)
        anc = "start" if v >= 0 or not diverge else "end"
        if diverge and v < 0:
            tx = zero + 5
            anc = "start"
        out.append(f'<text class="val" x="{tx:.1f}" y="{y + row_h / 2 + 4}" text-anchor="{anc}">{E(annot)}</text>')
    out.append("</svg>")
    return "".join(out)


def lines(title, series, xlim, ylim, xticks, yticks, xlabel, ylabel, h=290, notes=None):
    """series: dict(name, cls, pts=[dict(x,y,ok,lab,pos)])."""
    log(f"chart '{title}':")
    l, r, t, b = 50, 78, 12, 42
    pw, ph = W - l - r, h - t - b

    def sx(v):
        return l + (v - xlim[0]) / (xlim[1] - xlim[0]) * pw

    def sy(v):
        return t + ph - (v - ylim[0]) / (ylim[1] - ylim[0]) * ph

    out = [svg_open(h, title)]
    for yv in yticks:
        out.append(f'<line class="grid" x1="{l}" y1="{sy(yv):.1f}" x2="{l + pw}" y2="{sy(yv):.1f}"/>')
        out.append(f'<text class="tick" x="{l - 5}" y="{sy(yv) + 4:.1f}" text-anchor="end">{fmt(yv, 0)}</text>')
    for xv in xticks:
        out.append(f'<line class="tickmark" x1="{sx(xv):.1f}" y1="{t + ph}" x2="{sx(xv):.1f}" y2="{t + ph + 4}"/>')
        out.append(f'<text class="tick" x="{sx(xv):.1f}" y="{t + ph + 16}" text-anchor="middle">{fmt(xv, 0)}</text>')
    out.append(f'<line class="base" x1="{l}" y1="{t + ph}" x2="{l + pw}" y2="{t + ph}"/>')
    out.append(f'<text class="axis" x="{l + pw / 2:.1f}" y="{h - 4}" text-anchor="middle">{E(xlabel)}</text>')
    out.append(f'<text class="axis" transform="translate(11 {t + ph / 2:.1f}) rotate(-90)" text-anchor="middle">{E(ylabel)}</text>')
    for s in series:
        ok = sorted([p for p in s["pts"] if p.get("ok", True)], key=lambda p: p["x"])
        log(f"  series {s['name']}: " + ", ".join(
            f"{p['x']}->{p['y']}{'' if p.get('ok', True) else ' (FAIL)'}" for p in s["pts"]))
        if len(ok) > 1:
            d = " ".join(f"{sx(p['x']):.1f},{sy(p['y']):.1f}" for p in ok)
            out.append(f'<polyline class="ln-{s["cls"]}" points="{d}"/>')
        for p in s["pts"]:
            cx, cy = sx(p["x"]), sy(p["y"])
            if p.get("ok", True):
                out.append(f'<circle class="pt-{s["cls"]}" cx="{cx:.1f}" cy="{cy:.1f}" r="4"/>')
            else:
                out.append(f'<path class="bad" d="M{cx - 5:.1f} {cy - 5:.1f}L{cx + 5:.1f} {cy + 5:.1f}M{cx - 5:.1f} {cy + 5:.1f}L{cx + 5:.1f} {cy - 5:.1f}"/>')
            lab = p.get("lab")
            if lab:
                pos = p.get("pos", "above")
                dx, dy, anc = {"above": (0, -8, "middle"), "below": (0, 15, "middle"),
                               "left": (-8, 4, "end"), "right": (8, 4, "start")}[pos]
                cls = "val bad-t" if not p.get("ok", True) else "val"
                out.append(f'<text class="{cls}" x="{cx + dx:.1f}" y="{cy + dy:.1f}" text-anchor="{anc}">{E(lab)}</text>')
        last = ok[-1] if ok else s["pts"][-1]
        out.append(f'<text class="sname-{s["cls"]}" x="{sx(last["x"]) + 10:.1f}" y="{sy(last["y"]) + 4 + s.get("name_dy", 0):.1f}">{E(s["name"])}</text>')
    out.append("</svg>")
    return "".join(out)


def vgroups(title, cats, series, ymax, unit, h=280, yticks=None):
    """grouped vertical bars. cats: labels. series: (name, cls, [values])."""
    log(f"chart '{title}':")
    for n, c, v in series:
        log(f"  series {n}: " + ", ".join(f"{a}={b}" for a, b in zip(cats, v)))
    l, r, t, b = 50, 12, 14, 70
    pw, ph = W - l - r, h - t - b
    gw = pw / len(cats)
    bw = gw * 0.8 / len(series)
    sy = lambda v: t + ph - v / ymax * ph
    out = [svg_open(h, title)]
    for yv in (yticks or [0, ymax / 2, ymax]):
        out.append(f'<line class="grid" x1="{l}" y1="{sy(yv):.1f}" x2="{l + pw}" y2="{sy(yv):.1f}"/>')
        out.append(f'<text class="tick" x="{l - 5}" y="{sy(yv) + 4:.1f}" text-anchor="end">{fmt(yv, 0)}</text>')
    out.append(f'<text class="axis" transform="translate(11 {t + ph / 2:.1f}) rotate(-90)" text-anchor="middle">{E(unit)}</text>')
    out.append(f'<line class="base" x1="{l}" y1="{t + ph}" x2="{l + pw}" y2="{t + ph}"/>')
    for i, c in enumerate(cats):
        gx = l + i * gw + gw * 0.1
        for j, (n, cls, vals) in enumerate(series):
            v = vals[i]
            x = gx + j * bw
            out.append(f'<rect class="b-{cls}" x="{x:.1f}" y="{sy(v):.1f}" width="{bw - 2:.1f}" height="{t + ph - sy(v):.1f}" rx="2"/>')
            out.append(f'<text class="val" x="{x + bw / 2 - 1:.1f}" y="{sy(v) - 4:.1f}" text-anchor="middle">{v:g}</text>')
            out.append(f'<text class="sn" x="{x + bw / 2 - 1:.1f}" y="{t + ph + 11}" text-anchor="middle">{E(n)}</text>')
        out.append(f'<text class="lbl" x="{gx + gw * 0.4:.1f}" y="{t + ph + 30}" text-anchor="middle">{E(c)}</text>')
    out.append("</svg>")
    return "".join(out)


def table(head, rows, cls=""):
    h = "".join(f"<th>{E(c)}</th>" for c in head)
    body = ""
    for r in rows:
        tds = ""
        for c in r:
            if isinstance(c, tuple):
                tds += f'<td class="{c[1]}">{E(c[0])}</td>'
            else:
                tds += f"<td>{E(str(c))}</td>"
        body += f"<tr>{tds}</tr>"
    return f'<div class="tw"><table class="{cls}"><thead><tr>{h}</tr></thead><tbody>{body}</tbody></table></div>'


def fig(svg, source, cap=""):
    c = f'<p class="cap">{E(cap)}</p>' if cap else ""
    return f'<figure>{c}{svg}<p class="src">source: {E(source)}</p></figure>'


def ul(items):
    return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"


def code(s):
    return f"<code>{E(s)}</code>"


# ------------------------------------------------------------------- data
# src: docs/NAT.md numbers table; docs/CAMPAIGN-PLAIN-7.4.md 'Old options re-tested at 608 MHz'
TARGET_MBIT = 2500
TARGET_KPPS = 312  # src: docs/NAT.md 'What the remaining limit is' (2.5 Gbit/s of 1500 B frames)

# src: docs/CAMPAIGN-PLAIN-7.4.md 'Switch-core clock vs the 1400 B ceiling' and '#148 steps'
CORE = [  # mhz, lx, rx_only, fwd, boots, status
    (245, 306, 86.6, None, "n=3 rx", "stable"),
    (306, 306, 108.1, 110.0, "ok", "stable"),
    (408, 306, 143.5, 144.8, "stock", "stable"),
    (508, 305, mean([164.0, 171.8, 167.6]), mean([159.4, 159.2, 158.9]), "3/3", "stable"),
    (575, 246, mean([173.5, 145.4, 168.9]), mean([153.2, 153.7, 153.4]), "3/3", "stable"),
    (608, 304, mean([173.0, 174.6, 175.9]), mean([170.4, 170.0, 170.3]), "3/3", "stable"),
    (658, 247, mean([182.4, 175.7, 155.3]), mean([153.5, 153.3, 153.2]), "3/3", "stable"),
]
CORE_612_RX = 182.3  # code 0, rx-only n=3; forwarding wedges 4/4

# src: docs/FASTEST-SETTINGS.md 'Results 2026-11-07 (core 608)' CPU table (plain kernel, rx-only)
CPU_RX = [(1000, 151.1, 182.9), (1050, 150.8, 192.4), (1100, 158.6, 193.5),
          (1250, 175.6, 217.2), (1325, 173.5, 220.2), (1350, 180.5, 226.2)]
CPU_FAIL = (1375, 179.4, 231.6)  # HANG: integrity FAIL, Kernel panic
# src: docs/CAMPAIGN-PLAIN-7.4.md 'Highest stable CPU at core 608 on OpenWrt' (zc+nat 1400 B kpps)
CPU_IMG = [(1000, 161.7), (1200, 160.4), (1275, 160.2), (1325, 170.4)]
CPU_IMG_BOOTS = {1000: "3/3", 1200: "3/3", 1275: "3/3", 1325: "5/5", 1350: "0/2"}

# src: docs/CPU-PORT.md frame-size sweep (picks, core 408)
SIZES = [(64, 2.0), (200, 2.4), (500, 3.2), (800, 4.4), (1100, 5.8), (1400, 7.0)]

# src: docs/CAMPAIGN-PLAIN-7.4.md options tables; docs/FASTEST-SETTINGS.md scans
def delta(v, base):
    return (v / base - 1) * 100


def verdict(p, band=3.0):
    return "win" if p >= band else ("lose" if p <= -band else "tie")


def prefetch_means():
    rows = [r for r in jsonl("zc_prefetch_ab.jsonl") if r.get("tag") == "pf1"]
    out = {}
    for var in ("base", "desc", "hdr", "both"):
        for ln in (1400, 64):
            v = [r["kpps"] for r in rows if r["variant"] == var and r["len"] == ln]
            if v:
                out[(var, ln)] = mean(v)
    if not out:  # src: docs/NAT-HISTORY.md '#147 prefetch A/B'
        out = {("base", 1400): 166.8, ("desc", 1400): 166.5, ("hdr", 1400): 166.7, ("both", 1400): 165.9,
               ("base", 64): 424.8, ("desc", 64): 441.2, ("hdr", 64): 400.6, ("both", 64): 439.9}
    return out


def options_rows():
    pf = prefetch_means()
    rows = []  # (group, label, pct, note)

    def add(group, label, v, b, note=""):
        rows.append((group, label, delta(v, b), note))

    add("Second CPU", "ring split (par)", 123.8, 163.6, "both VPEs busy")
    add("Second CPU", "NAPI split, ring thread per VPE", mean([165.3, 151.0, 166.2]), 169.3)
    add("Second CPU", "NAPI threaded, unpinned", mean([162.6, 157.5, 164.6]), 169.3)
    add("Queues", "tx_by_cpu=1", 168.5, 169.3)
    add("Queues", "noqueue", 169.2, 169.3)
    add("Queues", "tx_by_cpu + noqueue", 170.2, 169.3)
    add("Queues", "CPU q1 threshold 78/512/4095", mean([169.1, 169.5, 169.4]), 169.3)
    add("Queues", "CPU q0 threshold 78/4095", mean([161.5, 164.2]), 163.6)
    add("Cache / prefetch", "cache: TX writeback 1536 B", 165.6, 165.8)
    add("Cache / prefetch", "cache: header-only recycle", 165.2, 165.8)
    add("Cache / prefetch", "cache: both", 165.1, 165.8)
    for var, nm in (("desc", "descriptor"), ("hdr", "header"), ("both", "both")):
        add("Cache / prefetch", f"prefetch {nm}, 1400 B", pf[(var, 1400)], pf[("base", 1400)])
    for var, nm in (("desc", "descriptor"), ("hdr", "header"), ("both", "both")):
        add("Cache / prefetch", f"prefetch {nm}, 64 B", pf[(var, 64)], pf[("base", 64)], "64 B only")
    add("GRO", "GRO fraglist off, stack TCP P4", mean([275, 271]), mean([422, 413]))
    add("GRO", "GRO fraglist off, zc TCP P4", mean([1630, 1642]), mean([1634, 1631]))
    add("Bus / clocks", "LX arbitration swap", 174.1, 180.1, "rx-only")
    add("Bus / clocks", "LX arbitration m1", 176.4, 180.1, "rx-only")
    add("Bus / clocks", "LX arbitration m0", 182.8, 180.1, "rx-only")
    add("Bus / clocks", "SRAM 250 (stock)", 174.3, 174.6, "rx-only")
    add("Bus / clocks", "SRAM bridge pulse down", 169.3, 174.6, "rx-only")
    add("Bus / clocks", "SRAM bridge pulse up", 174.6, 174.6, "rx-only")
    add("Bus / clocks", "DDR 650 vs 662", 177.3, 174.4, "rx-only")
    return rows


# src: docs/CAMPAIGN-PLAIN-7.4.md 'L3 offload checks on the 7.4 base' (docs/NAT-HISTORY.md)
L3 = [("v4 on-link fwd", 90, 9197), ("v4 on-link rev", 90, 9201), ("v4 default fwd", 94, 9201),
      ("v4 default rev", 90, 9189), ("v6 on-link fwd", 86, 9058), ("v6 on-link rev", 89, 9068),
      ("v6 default fwd", 171, 9066), ("v6 default rev", 1456, 9058)]


def nat161():
    rows = jsonl("nat161.jsonl")
    d = {}
    for r in rows:
        if r.get("tag") or r.get("path") == "zc_bench" or r.get("mbit") is None:
            continue
        d.setdefault((r["img"], r["irq"], r["path"], r["dir"]), []).append(r["mbit"])
    tag = {}
    for r in rows:
        if r.get("tag") in ("rps0", "rps0+ctcsum1") and r.get("irq") == "irq1" and r.get("dir") == "fwd" and r.get("mbit"):
            tag[r["tag"]] = r["mbit"]
    if not d:  # src: docs/NAT-HISTORY.md '#161'
        d = {("plain", "default", "nat", "fwd"): [240], ("plain", "default", "nat-ft", "fwd"): [323],
             ("openwrt", "default", "nat", "fwd"): [85.5], ("openwrt", "default", "nat-ft", "fwd"): [267.7],
             ("openwrt", "irq1", "nat", "fwd"): [76.6], ("plain", "irq1", "nat", "fwd"): [240.6]}
        tag = {"rps0": 106.6, "rps0+ctcsum1": 108.5}
    return {k: mean(v) for k, v in d.items()}, tag


# ---------------------------------------------------------------- sections
def s1():
    zc_plain, zc_img = 1634, 1536  # src: docs/NAT.md numbers; docs/NAT-HISTORY.md #161 (core 508)
    res, tag = nat161()
    rows = [
        ("Target", TARGET_MBIT, "target", f"{TARGET_MBIT}"),
        ("zc+nat, plain kernel", zc_plain, "win", f"{zc_plain}  ({zc_plain / TARGET_MBIT * 100:.0f} %)"),
        ("zc+nat, OpenWrt image", zc_img, "win", f"{zc_img}  ({zc_img / TARGET_MBIT * 100:.0f} %)"),
        ("stack nat-ft, plain (core 608)", 422, "neutral", "422"),
        ("stack nat-ft, image (core 508)", res[("openwrt", "default", "nat-ft", "fwd")], "neutral",
         fmt(res[("openwrt", "default", "nat-ft", "fwd")], 0)),
        ("stack nat (conntrack), image", res[("openwrt", "default", "nat", "fwd")], "lose",
         fmt(res[("openwrt", "default", "nat", "fwd")], 0)),
    ]
    g1 = hbars("NAT TCP -P 4 forward goodput vs the 2.5 Gbit/s target", rows, 2500, "Mbit/s, iperf3 TCP -P 4, one direction",
               ticks=[0, 500, 1000, 1500, 2000, 2500], label_w=190)
    rows2 = [("CPU-port rate needed", TARGET_KPPS, "target", f"~{TARGET_KPPS}"),
             ("zc+nat 1400 B, final", 170, "win", "170  (54 %)"),
             ("stack 1400 B", 60.2, "neutral", "60")]
    g2 = hbars("1400 B forwarding rate vs the rate 2.5 Gbit/s needs", rows2, 350, "kpps (frames per second through the CPU port, 1400 B UDP payload)",
               ticks=[0, 100, 200, 300], label_w=170)
    return (
        "<h2 id='s1'>1 Where we are</h2>"
        "<div class='tiles'>"
        "<div class='tile'><b>1634</b><span>Mbit/s NAT TCP, zc fast path (65 % of 2500)</span></div>"
        "<div class='tile'><b>170</b><span>kpps 1400 B zc+nat (needs ~312)</span></div>"
        "<div class='tile'><b>9.1</b><span>Gbit/s routed in the ASIC, 0 % CPU (no NAT)</span></div>"
        "<div class='tile'><b>2.8x</b><span>zc fast path over the skb stack</span></div>"
        "</div>"
        + ul([
            "Target 2.5 Gbit/s IPv4 NAT (NBN HFC ~2 Gbit/s, #65). Not reachable by clocks; every clock/option left is at its limit or a tie.",
            "The ASIC rewrites MACs and TTL only; every NAT packet crosses the CPU port twice.",
            "Final settings: core 608, CPU 1325 (OpenWrt-stable) / 1350 (plain, short runs), DDR 662, LX 304, SRAM 500.",
        ])
        + fig(g1, "docs/NAT.md numbers table; docs/NAT-HISTORY.md #161 (image rows at core 508, tmp/logs/nat161.jsonl means)",
              "NAT TCP goodput, one direction")
        + fig(g2, "docs/NAT.md 'What the remaining limit is'; docs/CAMPAIGN-PLAIN-7.4.md", "Frames per second through the CPU port")
    )


def s2():
    pts_rx = []
    pts_fw = []
    pos_rx = {245: "above", 306: "above", 408: "above", 508: "above", 575: "above", 608: "left", 658: "above"}
    for mhz, lx, rx, fw, boots, status in CORE:
        pts_rx.append(dict(x=mhz, y=round(rx, 1), lab=fmt(rx, 0), pos=pos_rx[mhz]))
        if fw is not None:
            pts_fw.append(dict(x=mhz, y=round(fw, 1), lab=fmt(fw, 0), pos="below"))
    pts_rx.append(dict(x=612, y=CORE_612_RX, ok=False, lab="612 code 0: wedge", pos="above"))
    g_core = lines("1400 B rx-only and forwarding rate vs switch-core clock",
                   [dict(name="rx-only", cls="a", pts=pts_rx, name_dy=-6),
                    dict(name="forwarding", cls="b", pts=pts_fw, name_dy=8)],
                   (220, 690), (60, 200), [245, 306, 408, 508, 575, 608, 658], [60, 100, 140, 180],
                   "switch-core clock, MHz (circle = stable 3/3 boots, X = wedge)", "1400 B rate, kpps")
    core_tab = table(["Core MHz", "LX MHz", "rx-only kpps", "zc+nat fwd kpps", "boots / status"],
                     [[m, lx, fmt(rx, 1), fmt(fw, 1) if fw else "not obtained", b + " stable"] for m, lx, rx, fw, b, s in CORE]
                     + [["612 (code 0)", 306, "173-182", "wedge", ("4 of 4 wedge, forbidden", "badc")]])
    pts_c = [dict(x=x, y=a, lab=fmt(a, 0), pos="above") for x, a, b in CPU_RX]
    pts_c.append(dict(x=CPU_FAIL[0], y=CPU_FAIL[1], ok=False, lab="1375 panic", pos="below"))
    pts_i = [dict(x=x, y=y, lab=fmt(y, 0), pos="below") for x, y in CPU_IMG]
    pts_i.append(dict(x=1350, y=125, ok=False, lab="1350 fails", pos="below"))
    g_cpu = lines("1400 B rate vs CPU clock at switch core 608",
                  [dict(name="rx-only, plain", cls="a", pts=pts_c, name_dy=-4),
                   dict(name="zc+nat, image", cls="c", pts=pts_i, name_dy=10)],
                  (960, 1400), (110, 200), [1000, 1100, 1200, 1300, 1350], [120, 140, 160, 180],
                  "CPU clock, MHz (X = failure; image 1350 plotted at the axis floor)", "1400 B rate, kpps")
    pts64 = [dict(x=x, y=b, lab=fmt(b, 0), pos="above") for x, a, b in CPU_RX]
    pts64.append(dict(x=CPU_FAIL[0], y=CPU_FAIL[2], ok=False, lab="1375 panic", pos="below"))
    g_cpu64 = lines("64 B rx-only rate vs CPU clock at switch core 608",
                    [dict(name="rx-only 64 B", cls="a", pts=pts64)],
                    (960, 1400), (160, 250), [1000, 1100, 1200, 1300, 1350], [180, 200, 220, 240],
                    "CPU clock, MHz", "64 B rate, kpps")
    g_size = lines("CPU time per packet vs frame size",
                   [dict(name="us/packet", cls="a", pts=[dict(x=s, y=u, lab=f"{u:g}", pos="above") for s, u in SIZES])],
                   (0, 1500), (0, 8), [64, 500, 800, 1100, 1400], [0, 2, 4, 6, 8],
                   "UDP payload, bytes", "CPU time per forwarded packet, us")
    return (
        "<h2 id='s2'>2 What limits NAT</h2>"
        + ul([
            "Cost per packet ~2 us fixed (64 B) + ~4 ns per byte; the per-byte part follows the switch-core clock.",
            "Receive side is the limit: ASIC to CPU queue 1 to NIC DMA to VPE1 softirq. VPE1 97-99 % busy at every size.",
            "rx-only 1400 B (143 kpps) equals forwarding (142 kpps) at core 408; receive-and-drop stops at the same rate.",
            "612 MHz via divider code 0 wedges CPU-port DMA under forwarding (4 of 4); 608 via VCO 3650 / code 1 is the same speed and passes.",
            "Above ~500 MHz gain flattens at 170-180 kpps: VPE1 is the limit, not the core clock. CPU raises give little: 64 B follows the CPU clock.",
            "Not cache maintenance (falsified: TX writeback and header-only recycle both &lt; 0.5 % at 1400 B).",
        ])
        + fig(g_core, "docs/CAMPAIGN-PLAIN-7.4.md 'Switch-core clock vs the 1400 B ceiling' + '#148 steps' (means of the boots listed; plain 7.4-rc1, 2026-11-07)")
        + "<p class='note'>575 and 658 forward lower because the re-code puts LX at 246/247 MHz; compare equal-LX rows only.</p>"
        + core_tab
        + fig(g_cpu, "docs/FASTEST-SETTINGS.md CPU table (rx-only, plain); docs/CAMPAIGN-PLAIN-7.4.md 'Highest stable CPU at core 608 on OpenWrt' (zc+nat, image)")
        + fig(g_cpu64, "docs/FASTEST-SETTINGS.md CPU table (64 B column)")
        + ul([
            "CPU 1375 passes at core 408 and fails at core 608 (xz decode errors, panic): the CPU limit moves with the core clock. PLL locks at once; the fault is CPU logic.",
            "OpenWrt image at core 608: 1000-1325 pass, 1350 fails 0/2 (xz decode wrong, Oops at 32-53 s). Plain kernel 1350 passes short runs.",
        ])
        + fig(g_size, "docs/CPU-PORT.md frame-size sweep (picks clocks, core 408, 2026-11-07)",
              "Fixed ~2 us + proportional part; not a flat byte-rate cap")
    )


def s3():
    final = table(
        ["Domain", "Stock", "Final", "Why the gap"],
        [["Switch core", "408 MHz", "608", "612 (code 0) wedges CPU-port DMA; 608 best forwarding; 575 / 658 re-code LX to 246 / 247"],
         ["CPU", "800", "1325 (image) / 1350 (plain)", "1350 fails on the image at core 575 / 608 (#160); 1375 fails at 608; PLL locks at once"],
         ["DDR", "600", "662", "675 / 700 pass only after ddr-retrain --write, no gain beyond noise"],
         ["LX", "175", "~304", "follows the SW VCO; 204 panicked on the 7.3 image (#149); above 306 needs a clocks.c change"],
         ["SRAM", "250", "500", "already the maximum; no effect on the NAT rate"],
         ["SPI (Linux)", "25.5 MHz", "23.4 (follows core 608)", "fast SPI corrupts reads under Linux (#50)"]])
    img = table(
        ["Core", "CPU", "Boots passed", "zc+nat kpps", "First failure"],
        [[408, 1350, "3/3", "-", "none"],
         [508, 1350, "5/5", "154.9", "none"],
         [575, 1350, "0/1", "-", ("xz decode wrong after 120 s iperf", "badc")],
         [608, 1000, "5/5", "161.7", "none"],
         [608, 1200, "3/3", "160.4", "none"],
         [608, 1275, "3/3", "160.2", "none"],
         [608, 1325, "5/5", "170.4", "none (final pick)"],
         [608, 1350, "0/2", "-", ("xz decode wrong / Oops, 32-53 s", "badc")]])
    return (
        "<h2 id='s3'>3 Final settings and the OpenWrt-image caveat</h2>"
        + final
        + "<p class='src'>source: docs/FASTEST-SETTINGS.md 'Final settings'; docs/CAMPAIGN-PLAIN-7.4.md 'Highest stable CPU at core 608 on OpenWrt'</p>"
        + "<h3>OpenWrt-image caveat (#160)</h3>"
        + img
        + "<p class='src'>source: docs/CAMPAIGN-PLAIN-7.4.md 'OpenWrt image stability at core 508/575/608' and 'Highest stable CPU'</p>"
        + ul([
            "Culprit: CPU 1350 at core &gt;= 575. Core 608 with CPU 1000-1325 and core 508 with CPU 1350 pass.",
            "Image pick: core 608 + CPU 1325 (5/5): zc +10 % over core 508 + CPU 1350 (170.4 vs 154.9 kpps).",
            "Flash console garbles at LX 304 (#159: UART base_baud assumes LX 175). The flash chain profile stays cpu=1350, ddr=662, sram=500 without swcore; 300-23 is in the 6.18 build list, untested.",
            "Owner choice 2026-11-08: CPU 1325 (the image result moved the pick from 1350).",
            "Temperature is logged only; there is no 85 C abort (owner 2026-11-07). Idle readings 46-63 C.",
        ])
    )


def s4():
    rows = options_rows()
    out = ["<h2 id='s4'>4 Every option tried</h2>"]
    out += [ul([
        "Metric = zc+nat 1400 B forwarding at core 608 unless the label says otherwise. Win &gt;= +3 %, lose &lt;= -3 %, else tie (spread 0.1-0.4 %; rx-only varies +-6 %).",
        "Bars carry the verdict word; colour is a second cue (blue win, grey tie, orange lose).",
    ])]
    groups = []
    for g, *_ in rows:
        if g not in groups:
            groups.append(g)
    for g in groups:
        rr = []
        for gg, label, pct, note in rows:
            if gg != g:
                continue
            v = verdict(pct, 6.0 if note == "rx-only" else 3.0)
            ann = f"{pct:+.1f} %  {v.upper()}" + (f" ({note})" if note else "")
            rr.append((label, pct, v, ann))
        out.append(f"<h3>{E(g)}</h3>")
        out.append(hbars(f"Delta vs baseline: {g}", rr, 10, "change vs baseline, %", xmin=-40, label_w=185,
                         ticks=[-40, -30, -20, -10, 0, 10], diverge=True))
    out.append("<p class='src'>source: docs/CAMPAIGN-PLAIN-7.4.md 'Old options re-tested at 608 MHz', 'Cache variants at 608 MHz'; docs/NAT-HISTORY.md '#147 prefetch A/B' (tmp/logs/zc_prefetch_ab.jsonl means); docs/FASTEST-SETTINGS.md scans (rx-only)</p>")
    out.append("<h3>Options without a rate delta</h3>")
    out.append(table(
        ["Option", "Result", "Verdict"],
        [["zc fast path vs skb stack", "169.3 vs 60.2 kpps at 608 (2.8x); TCP P4 1634 vs 422 Mbit/s", ("win", "winc")],
         ["Rings in SRAM (sram_rings=3)", "no traffic at 408 and 608 (NIC DMA does not work from SRAM)", ("dead", "badc")],
         ["SRAM packet buffers", "no driver parameter exists", "not testable"],
         ["SRAM bridge CMUCR_OC0 bit 9", "hang (no ssh after ramload)", ("hang", "badc")],
         ["nftables flowtable off (stack)", "-74 %", ("lose", "badc")],
         ["UDP GRO forwarding on", "worse", ("lose", "badc")],
         ["RPS on the stack path", "worse (image sets rps_cpus=1, #161)", ("lose", "badc")],
         ["GDMA dmaengine (300-41)", "correct (0 bad); no copy in the NAT path to offload; 4096 B xfer 15 us at picks", "n/a"],
         ["DDR 675 / 700", "pass only with ddr-retrain --write; no gain", "tie"],
         ["CPU 1375+ at core 608", "xz corrupt / panic: real limit", ("lose", "badc")],
         ["Conntrack / flowtable sysctls (#71)", "all within 2 %", "tie"]]))
    out.append("<p class='src'>source: docs/NAT.md 'What does not help'; docs/CAMPAIGN-PLAIN-7.4.md; docs/FASTEST-SETTINGS.md; docs/NAT-HISTORY.md #71</p>")
    return "".join(out)


def s5():
    res, tag = nat161()
    g = lambda *k: res[k]
    cats = ["nat", "nat-ft", "zc+nat"]
    plain_zc, img_zc = 1565, 1536  # src: docs/NAT-HISTORY.md #161 (zc_bench --tcp)
    ch = vgroups("NAT TCP forward goodput by path, plain vs OpenWrt image (core 508)", cats,
                 [("plain", "a", [round(g("plain", "default", "nat", "fwd")), round(g("plain", "default", "nat-ft", "fwd")), plain_zc]),
                  ("image", "c", [round(g("openwrt", "default", "nat", "fwd")), round(g("openwrt", "default", "nat-ft", "fwd")), img_zc])],
                 1800, "TCP -P 4 forward, Mbit/s", yticks=[0, 600, 1200, 1800])
    rps = [("image as booted (irq1)", g("openwrt", "irq1", "nat", "fwd"), "lose", fmt(g("openwrt", "irq1", "nat", "fwd"), 0)),
           ("+ rps_cpus = 0", tag["rps0"], "tie", fmt(tag["rps0"], 0)),
           ("+ nf_conntrack_checksum = 1", tag["rps0+ctcsum1"], "tie", fmt(tag["rps0+ctcsum1"], 0)),
           ("plain, same path", g("plain", "irq1", "nat", "fwd"), "win", fmt(g("plain", "irq1", "nat", "fwd"), 0))]
    gr = hbars("Image nat path: forward goodput as settings are removed", rps, 300, "Mbit/s, TCP -P 4 forward, irq on VPE1",
               ticks=[0, 100, 200, 300], label_w=190)
    return (
        "<h2 id='s5'>5 NAT paths compared</h2>"
        + ul([
            "stack <b>nat</b> = conntrack + masquerade on every packet. <b>nat-ft</b> = nftables software flowtable. <b>zc+nat</b> = in-place fast path fed by the flowtable (300-39).",
            "#161: the 83-104 Mbit/s figure is the image on <b>nat</b>; the 413-422 plain figure is <b>nat-ft</b>. Different paths, not a regression.",
            "Image zc+nat is within 2 % of plain. Image nat-ft is 17-28 % below plain; image nat is 2.2-2.8x below.",
            "Finding: the image sets <code>rps_cpus=1</code> on eth0, which defeats <code>--napi irq1</code> (stack never runs on VPE1). Removing it gives +23-39 % on nat.",
            "Not explained: remaining ~2.2x per packet on nat. Candidates: fw4 hook chains, fq_codel, build config. Next probe in #161.",
            "Stack numbers differ by setup: 413-422 (NAT.md, nat-ft, core 608) vs 323 (nat-ft, core 508, #161) vs 242 (canary boots, nat).",
        ])
        + fig(ch, "docs/NAT-HISTORY.md #161 (tmp/logs/nat161.jsonl means, 3 runs x 15 s; zc+nat from zc_bench --tcp); core 508, CPU 1350")
        + fig(gr, "docs/NAT-HISTORY.md #161 'Partial A/B on the image' (tmp/logs/nat161.jsonl, 1 x 15 s per point)")
    )


def s6():
    rows = []
    for n, a, b in L3:
        rows.append((f"{n} off", a, "d", f"{a}"))
        rows.append((f"{n} on", b, "a", f"{b}"))
    gl = hbars("L3 routing offload off vs on", rows, 10000, "TCP -P 4 goodput, Mbit/s (off = trapped to the CPU)",
               ticks=[0, 2500, 5000, 7500, 10000], label_w=150, row_h=18)
    checks = table(["Check", "Result"], [
        ["a ip neigh del", ("PASS", "winc")], ["b neighbour MAC change", ("PASS", "winc")],
        ["c ip route add (covering prefix)", ("PASS", "winc")], ["d local /32", ("PASS", "winc")],
        ["e ip rule add", ("PASS", "winc")],
        ["f source-specific ::/0", ("PASS: plain ::/0 back to fwd in ~4 s after the delete", "winc")],
        ["g 120 s run, neighbour states", ("PASS", "winc")],
        ["h martian DIPs", ("FAIL: 0.0.0.1 forwarded to natwan (2/2); 127.0.0.2 and ::1 not seen", "badc")],
        ["i all params 0", ("PASS", "winc")]])
    return (
        "<h2 id='s6'>6 Routing offload (#59)</h2>"
        + ul([
            "ASIC routing keeps wire speed: 9.06-9.20 Gbit/s at ~345 pps on eth0 (off: 22-30 kpps trapped to the CPU).",
            "Image <code>openwrt-ours-l3fix2</code> (7.4-rc1 + 300-17 fixes), core 608, CPU 1325, n=3, one boot, 2026-11-08; no panic or reset.",
            "Fixes confirmed: plain ::/0 stays trap after a source-route delete; v4 rt_offload clears when l3_default_v4 goes 1 to 0.",
            "Open: h needs a trap row for 0.0.0.0/8 above the default; notifier updates; sampling/mirror.",
            "Earlier 5/5 image resets at 26-32 s were a missing <code>st1008f-stx</code> selftest helper (#163), not the 300-17 fixes.",
            "Offload bypasses nftables (#66): opt-in only; this box keeps v4 default off (ASIC cannot NAT).",
        ])
        + fig(gl, "docs/NAT-HISTORY.md 'L3 offload checks on the 7.4 base with the fixes' (medians of n=3; tmp/logs/l3_offload_ab-20261108-*.txt)")
        + checks
        + "<p class='src'>source: docs/NAT-HISTORY.md 'L3 offload checks on the 7.4 base' (#59)</p>"
    )


def s7():
    base = json.loads((ROOT / "scripts" / "canary_baseline.json").read_text())
    log(f"canary baseline: {json.dumps({k: base[k] for k in ('boot_link', 'hang_test', 'gdma', 'zc', 'dss')})}")
    ct = table(["Value", "Baseline", "Rule"], [
        ["zc 1400 B, final profile, under perf", f"{base['zc']['kpps_1400']} kpps", f"+-{base['zc']['tol_pct']} % PASS, below FAIL, above WARN"],
        ["gdma 4096 B", f"{base['gdma']['ns_4096'] / 1000:.1f} us", f"ceiling {base['gdma']['max_ns_4096'] / 1000:.1f} us (x1.25), over = FAIL"],
        ["hang reset", f"{base['hang_test']['reset_s']} s", f"WARN above {base['hang_test']['warn_above_s']} s"],
        ["dss polls", base["dss"]["polls"], "any other = FAIL"],
        ["boot-link rounds", base["boot_link"]["rounds"], "all must pass"]])
    boots = vgroups("zc+nat 1400 B across five plain boots at the final profile",
                    ["boot 1", "boot 2", "boot 3*", "boot 4", "boot 5"],
                    [("kpps", "a", [170.0, 168.7, 0, 170.1, 169.9])], 200, "zc+nat 1400 B, kpps", h=250,
                    yticks=[0, 50, 100, 150, 200])
    verd = table(["Check", "Verdict (2026-11-07)", "Note"], [
        ["boot_link", ("PASS", "winc"), "3/3, bounces 0"],
        ["hang_test", ("PASS", "winc"), "reset 93 s; #157 did not show"],
        ["plain_boot, pre, prep, vlanproto, gdma, dss, bootlog, consolescan", ("PASS", "winc"), "gdma 92.7 us"],
        ["selftest", ("FAIL", "badc"), "sfp 2 s timeout only (#162); other items PASS"],
        ["zc", ("WARN", "warnc"), "165.9 kpps vs old 143.3 baseline; new baseline set"]])
    return (
        "<h2 id='s7'>7 Stability and tooling</h2>"
        "<h3>Panics and resets</h3>"
        + table(["Issue", "Finding", "State"], [
            ["#149", "rteth RX gro_list_prepare NULL deref: OpenWrt 7.3 2/5 at CPU 1350 LX 204/245/175; plain 7.4-rc1 0/9", "not seen on 7.4; needs-test"],
            ["#160", "core 608 + CPU 1350 panics or xz-decode errors on the 7.4-rc1 image; plain clean; 1325 5/5", "1325 chosen (owner 2026-11-08)"],
            ["#163", "l3fix initramfs reset 5/5 at 26-32 s = missing st1008f-stx helper; rebuild passes 3/3 at 608/1325", "build now fails without helper; strict path untested"],
            ["#156", "receive floods go dead after 1-3 runs (43 of 69 rx runs stalled), recovers later", "open, needs-test"],
            ["#157", "SoC watchdog did not reset a hung board once in 14 hang-tests; later runs reset at 93 s", "intermittent"],
            ["#159", "608 profile garbles the flash console (UART base_baud assumes LX 175)", "300-23 untested"]])
        + "<p class='src'>source: docs/CAMPAIGN-PLAIN-7.4.md; docs/CANARY.md; docs/NAT-HISTORY.md #59</p>"
        "<h3>Canary baseline</h3>" + ct
        + "<p class='src'>source: scripts/canary_baseline.json (recorded " + E(base["recorded"]) + "), docs/CANARY.md#baseline</p>"
        + fig(boots, "docs/CANARY.md 'Five plain boots at the final profile'; * boot 3: ramload rc 1 before the load ran (plotted as 0)")
        + verd
        + ul([
            "Hang test: #138 passed 2026-10-15, failed on the 2026-11-04 flash image, passes at 93 s on the final profile.",
            "Flakes (#162): ramload rc 1 after bootm in 2 of 15 runs (console garble at LX 304, #159); selftest sfp 2 s timeout blocks the all-PASS run needed for --update-baseline.",
            "Boot-link x10 on flash 6.18.60: 10/10 clean, 0 of the 4 failure strings.",
        ])
    )


ISSUES = [  # group, number, title-short, status, next
    ("NAT / clock", 163, "Boot selftest reset when st1008f-stx missing", "root cause found: missing helper, not 300-17", "strict build path untested; close after a strict build"),
    ("NAT / clock", 162, "Tooling flakes at final profile", "ramload rc 1 2/15; selftest sfp 2 s timeout", "fix the bound or cause; then --update-baseline"),
    ("NAT / clock", 161, "Image NAT TCP 83-104 vs plain 413-422", "answered: nat vs nat-ft; rps_cpus=1 costs 23-39 %", "nft delete fw4 + noqueue + perf on both images"),
    ("NAT / clock", 160, "Core 608 + CPU 1350 panics on image", "1350 fails, 1325 5/5", "1325 chosen (owner 2026-11-08); failure rate at 1350 unmeasured"),
    ("NAT / clock", 159, "608 profile garbles flash console", "300-23 in 6.18 flash build list", "build, flash, test console at LX 304"),
    ("NAT / clock", 158, "Productise the zc fast path", "prototype works (IPv4, TCP/UDP)", "IPv6, new flows/ICMP/fragments, tx_by_cpu reclaim, boot defaults"),
    ("NAT / clock", 156, "Receive floods go dead after 1-3 runs", "ingress discards with empty CPU queue", "needs-test"),
    ("NAT / clock", 149, "OpenWrt 7.3 RX panic gro_list_prepare", "not seen on plain 7.4 (0/9)", "needs-test on the 7.4 image"),
    ("NAT / clock", 147, "Fewer DDR misses per packet", "cache + prefetch: no gain at 1400 B", "remaining: DMA/bus time of RX and TX"),
    ("NAT / clock", 144, "sw1 resets at CPU 1350", "owner: sw1 untouched until clocks settle", "parked"),
    ("NAT / clock", 66, "ASIC-routed traffic and nftables", "SYN drop works (300-37)", "UDP policy, ICMPv6, PIE capacity"),
    ("NAT / clock", 59, "L3 offload", "a-g, i PASS on 7.4; h FAIL", "0.0.0.0/8 trap row; notifier updates; sampling"),
    ("NAT / clock", 57, "DDR tooling reusable on other boards", "open (P3)", "-"),
    ("NAT / clock", 50, "SPI under Linux above 25.5 MHz unsafe", "stock SPI kept (P3)", "spi-mem dirmap idea in #61"),
    ("NAT / clock", 48, "DDR3 above 650 MHz (reopened)", "675 / 700 pass after ddr-retrain --write; no gain", "DDR testing stopped by owner"),
    ("NAT / clock", 27, "Build settings vs the 34Kc", "open (P3)", "-"),
    ("NAT / clock", 22, "All-port wire-speed routed test", "open, needs-test", "-"),
    ("U-Boot", 155, "Grow chain slot 512 KiB to 960 KiB", "slot size is one parameter", "migrate layout"),
    ("U-Boot", 154, "Add SDK U-Boot features", "batch 1-2 done (dt, loadb, hash, mtest, dss)", "DQ retrain, bus stress, watchdog before bootm"),
    ("U-Boot", 105, "Stock loader replacement (own SPL)", "plan in SPL-RAM-TRIAL.md", "RAM-loaded trial on sw2"),
    ("U-Boot", 88, "U-Boot unmanaged-switch mode", "open", "-"),
    ("U-Boot", 83, "U-Boot drivers reuse Linux code", "open", "-"),
    ("U-Boot", 81, "Stock U-Boot chain-load only + write protect", "layered gates in place", "flash block-protect on sw2"),
    ("U-Boot", 80, "Feature-rich U-Boot", "open", "-"),
    ("U-Boot", 46, "Mode switch selects boot policy", "M1/M2/M3 done", "M3 console-speed boot default"),
    ("U-Boot", 37, "rtk SerDes / thermal poll caps from measurement", "open", "-"),
    ("U-Boot", 120, "Boot LED chase, restore switch state at power-on", "open", "-"),
    ("U-Boot", 114, "Boot time profile", "open", "-"),
    ("Kernel / OpenWrt", 157, "SoC watchdog missed 1 of 14 hang-tests", "intermittent", "needs-test"),
    ("Kernel / OpenWrt", 152, "OpenWrt path for turbo clocks", "open", "read-only clk provider, uci profile, fallback"),
    ("Kernel / OpenWrt", 139, "OpenWrt shutdown up to ~26 s with selftest", "open", "needs-test"),
    ("Kernel / OpenWrt", 136, "st1008f-sds Linux port of rtk sds", "open", "needs-test"),
    ("Kernel / OpenWrt", 127, "AQR113C copper SFP read_status -145", "watch", "needs-test; verify 300-30 clamp"),
    ("Kernel / OpenWrt", 126, "Classify SFPs without compliance code", "open", "needs-test"),
    ("Kernel / OpenWrt", 118, "Config A/B slots in jffs2-cfg", "open", "-"),
    ("Kernel / OpenWrt", 85, "Upstream: reuse switchdev L3 code", "pitch drafted, not sent", "second owner approval of text"),
    ("Kernel / OpenWrt", 79, "Feature parity with TP-Link managed firmware", "open", "-"),
    ("Kernel / OpenWrt", 73, "Master plan", "umbrella", "-"),
    ("Kernel / OpenWrt", 61, "SPI-NOR under Linux: PIO reads", "open (P3)", "spi-mem dirmap; check Quad I/O"),
    ("Tooling", 111, "Storm/loop protection in the ASIC", "SPG guards relaxed (owner)", "storm control + loop detection"),
    ("Tooling", 108, "Boot-time self-test on Linux", "selftest runs; sfp 2 s timeout (#162)", "needs-test"),
    ("Tooling", 102, "Register naming pass", "open", "one generated header"),
    ("Tooling", 89, "Docs: tables wider than 5 columns", "open", "reshape"),
    ("Parked / blocked", 153, "Soak 60 min (deferred)", "parked: no long soaks", "-"),
    ("Parked / blocked", 45, "Upstream OpenWrt doc fix (HELD)", "held by owner", "-"),
]
CLOSED = [
    (65, "Fast NAT umbrella", "final state in NAT.md"), (71, "NAT path review", "no conntrack/sysctl effect once the flowtable carries a flow"),
    (103, "Overclock other domains", "picks are the fastest viable"), (140, "zc fast path prototype", "works; productising moved to #158"),
    (145, "Knob combination as default", "stack-path default; zc off"), (146, "Balance the two VPEs", "ring split FAIL: -24 %"),
    (148, "1400 B ceiling", "switch core 408 to 608: +17 %"), (151, "Parked: #148 investigation state", "folded"),
    (28, "Boot-log allowlist reference", "done"),
]


def s8():
    order = ["NAT / clock", "U-Boot", "Kernel / OpenWrt", "Tooling", "Parked / blocked"]
    out = ["<h2 id='s8'>8 Issue board</h2>",
           f"<p class='note'>{len(ISSUES)} open issues (gh issue list, 2026-11-08). Status for #158-#163 and #59 #65 #147 #148 #149 #160 #161 comes from the docs; for the rest from the title and labels only.</p>"]
    for g in order:
        rows = [[f"#{n}", t, s, nx] for gg, n, t, s, nx in ISSUES if gg == g]
        out.append(f"<h3>{E(g)} ({len(rows)})</h3>")
        out.append(table(["#", "Title", "Status", "Next"], rows))
    out.append("<h3>Closed in this campaign</h3>")
    out.append(table(["#", "Title", "Outcome"], [[f"#{n}", t, o] for n, t, o in CLOSED]))
    out.append("<ul><li>Reopened: <b>#48</b> (DDR above 650).</li><li>New: <b>#158</b> zc productise, <b>#159</b> console garble, <b>#160</b> CPU 1350 panic, <b>#161</b> image NAT, <b>#162</b> tooling flakes, <b>#163</b> selftest reset.</li></ul>")
    log(f"issues: {len(ISSUES)} open listed, {len(CLOSED)} closed listed")
    return "".join(out)


TIMELINE = [
    ("2026-11-06", "zc fast path (300-39) fed by the nftables flowtable: TCP P4 1250 / 1187 Mbit/s (#140, #148)"),
    ("2026-11-06", "CPU queue 1 threshold raised (300-40): TCP +17-21 %, retransmits /8"),
    ("2026-11-06", "1400 B ceiling does not follow CPU, DDR or LX clocks (-3 to -8 % for -25 %); LX 204 panic (#149)"),
    ("2026-11-07", "rx-only reproduces the forwarding ceiling: receive side is the limit (143.3 vs 142.5 kpps)"),
    ("2026-11-07", "switch-core clock sets the 1400 B rate: 86.6 / 108.1 / 143.5 / 182.3 kpps at 245 / 306 / 408 / 612"),
    ("2026-11-07", "612 via code 0 wedges CPU-port DMA 4/4; 508 / 575 / 608 / 658 via code 1 pass 3/3"),
    ("2026-11-07", "two-ring split: 124-128 vs 143 kpps, FAIL (#146); cache variants tie (#147)"),
    ("2026-11-07", "OpenWrt main bumped, kernel base v7.4-rc1 (#151)"),
    ("2026-11-07", "old options re-tested at 608: no second-CPU gain; zc+nat 169-171 kpps"),
    ("2026-11-07", "CPU 1375+ and DDR 675+ are real limits, not PLL lock (#103, #148)"),
    ("2026-11-07", "owner: final settings, go with what works; 608 / 1350 / 662 / 304 / 500 (CPU later set to 1325, 2026-11-08); #65 #146 #148 closed"),
    ("2026-11-07", "swcore=608 chain install: flash console garbles at LX 304 (#159); profile left without swcore"),
    ("2026-11-07", "OpenWrt image: CPU 1350 fails at core 575 / 608; 1325 stable 5/5 (#160)"),
    ("2026-11-07", "85 C temperature abort removed from scripts and docs (owner)"),
    ("2026-11-07", "L3 offload on 7.4 keeps 9.1-9.2 Gbit/s; NAT path cost: no conntrack/sysctl effect (#59, #71)"),
    ("2026-11-07", "canary baseline at the final profile: zc 165.9 kpps, gdma 92.7 us, hang reset 93 s"),
    ("2026-11-08", "prefetch (300-44) parked: no variant past noise at 1400 B (#147)"),
    ("2026-11-08", "#161: image zc+nat within 2 % of plain; the 83-104 figure is the nat path; rps_cpus=1 costs 23-39 %"),
    ("2026-11-08", "#163: l3fix initramfs resets = missing st1008f-stx helper, not 300-17"),
    ("2026-11-08", "#59: checks a-g, i PASS on 7.4 with fixes; h FAIL (0.0.0.1 forwarded)"),
]


def s9():
    rows = [[d, t] for d, t in TIMELINE]
    log(f"timeline: {len(rows)} entries")
    return "<h2 id='s9'>9 Timeline</h2>" + table(["Date", "Finding"], rows) + "<p class='src'>source: git log 2026-11-06..2026-11-08; docs/DECISIONS.md</p>"


CSS = """
:root{--bg:#fbfbf9;--fg:#1d2024;--mut:#5a6270;--card:#f0f1ee;--line:#d6d8d3;--grid:#e3e4e0;
--a:#2563c9;--b:#7a4fb5;--c:#0f8a6d;--d:#8b93a1;--win:#2563c9;--tie:#9aa1ad;--lose:#d9541e;--tgt:#1d2024;--neutral:#6b7686;--bad:#c4381a}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15171a;--fg:#e6e7e9;--mut:#9aa1ad;--card:#1f2226;--line:#33373d;--grid:#2a2d32;
--a:#6ea2ff;--b:#b394e6;--c:#4fcfae;--d:#7d8695;--win:#6ea2ff;--tie:#7d8695;--lose:#ff8a5c;--tgt:#e6e7e9;--neutral:#8b95a6;--bad:#ff7a5a}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:860px;margin:0 auto;padding:16px}
h1{font-size:1.5rem;margin:.2em 0}h2{font-size:1.25rem;margin:2em 0 .5em;border-bottom:1px solid var(--line);padding-bottom:.2em}
h3{font-size:1rem;margin:1.4em 0 .4em;color:var(--mut)}
.sub{color:var(--mut);margin:0 0 .8em}
nav{display:flex;flex-wrap:wrap;gap:6px 14px;margin:.6em 0;font-size:.9rem}
a{color:var(--a)}
ul{padding-left:1.2em;margin:.5em 0}li{margin:.2em 0}
code{background:var(--card);padding:0 4px;border-radius:3px;font-size:.9em}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:.6em 0}
.tile{background:var(--card);border-radius:8px;padding:10px 12px}
.tile b{display:block;font-size:1.7rem;line-height:1.1}.tile span{color:var(--mut);font-size:.85rem}
figure{margin:1em 0;padding:0}svg{width:100%;height:auto;display:block}
.cap{margin:0 0 4px;font-weight:600}
.src{color:var(--mut);font-size:.8rem;margin:.2em 0 .6em}.note{color:var(--mut);font-size:.85rem}
.tw{overflow-x:auto;margin:.5em 0}table{border-collapse:collapse;width:100%;font-size:.85rem}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--mut);font-weight:600;white-space:nowrap}
td.winc{color:var(--c);font-weight:600}td.badc{color:var(--bad);font-weight:600}td.warnc{color:var(--lose);font-weight:600}
svg text{fill:var(--fg);font:11px system-ui,sans-serif}
svg .tick,svg .axis,svg .sn{fill:var(--mut)}svg .axis{font-size:11px}
svg .lbl{font-size:11px}svg .val{font-size:11px;font-weight:600}svg .bad-t{fill:var(--bad)}
svg .grid{stroke:var(--grid);stroke-width:1}svg .base{stroke:var(--mut);stroke-width:1}
svg .tickmark{stroke:var(--mut)}svg .ref{stroke:var(--tgt);stroke-dasharray:4 3}
.b-win{fill:var(--win)}.b-tie{fill:var(--tie)}.b-lose{fill:var(--lose)}.b-neutral{fill:var(--neutral)}.b-target{fill:none;stroke:var(--tgt);stroke-width:1.5;stroke-dasharray:4 3}
.b-a{fill:var(--a)}.b-c{fill:var(--c)}.b-d{fill:var(--d)}
svg polyline{fill:none;stroke-width:2}.ln-a{stroke:var(--a)}.ln-b{stroke:var(--b)}.ln-c{stroke:var(--c)}
.pt-a{fill:var(--a)}.pt-b{fill:var(--b)}.pt-c{fill:var(--c)}
svg .bad{stroke:var(--bad);stroke-width:2.5;fill:none}
svg .sname-a{fill:var(--a);font-weight:600}svg .sname-b{fill:var(--b);font-weight:600}svg .sname-c{fill:var(--c);font-weight:600}
"""


def main():
    secs = [s1(), s2(), s3(), s4(), s5(), s6(), s7(), s8(), s9()]
    nav = " ".join(f'<a href="#s{i}">{i}</a>' for i in range(1, 10))
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>NAT and clocks report</title><style>" + CSS + "</style></head><body><main>"
        "<h1>TL-ST1008F: NAT and clocks report</h1>"
        "<p class='sub'>State as of 2026-11-08. sw2, RTL9303, one NAT interface. Facts: <a href='NAT.md'>NAT.md</a>; history: <a href='NAT-HISTORY.md'>NAT-HISTORY.md</a>. Generated by scripts/nat_report.py.</p>"
        f"<nav>{nav}</nav>" + "".join(secs) + "</main></body></html>")
    OUT.write_text(doc)
    LOGDIR.mkdir(parents=True, exist_ok=True)
    (LOGDIR / "nat_report.log").write_text("\n".join(LOG_LINES) + f"\nwrote {OUT} ({len(doc)} bytes)\n")
    print(f"wrote {OUT} ({len(doc)} bytes); log {LOGDIR / 'nat_report.log'}")


if __name__ == "__main__":
    sys.exit(main())
