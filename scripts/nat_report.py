#!/usr/bin/env python3
"""Generate docs/NAT-REPORT.html (self-contained, inline SVG, no JS/CDN).

- Numbers: only the controlled table in docs/NAT-STACK-RESULTS.md (TrueNAS, 2026-11-09) plus text from docs/FINDINGS.md.
- Old campaign numbers are history (docs/history/) and are not plotted. Owner decision 2026-11-08.
- `--artifact PATH` also writes the artifact variant. Series plotted are logged to tmp/logs/nat_report.log.
- Host only, no hardware.
"""
import html
import json
import os
import re
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


def lines(title, series, xlim, ylim, xticks, yticks, xlabel, ylabel, h=290, notes=None,
          xlab=None, missing=None, r=78):
    """series: dict(name, cls, pts=[dict(x,y,ok,lab,pos)]).
    xlab: {x: tick text}; missing: [(x, text)] hollow dashed markers on the baseline = not measured."""
    log(f"chart '{title}':")
    l, t, b = 50, 12, 42
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
        out.append(f'<text class="tick" x="{sx(xv):.1f}" y="{t + ph + 16}" text-anchor="middle">{E((xlab or {}).get(xv, fmt(xv, 0)))}</text>')
    out.append(f'<line class="base" x1="{l}" y1="{t + ph}" x2="{l + pw}" y2="{t + ph}"/>')
    out.append(f'<text class="axis" x="{l + pw / 2:.1f}" y="{h - 4}" text-anchor="middle">{E(xlabel)}</text>')
    out.append(f'<text class="axis" transform="translate(11 {t + ph / 2:.1f}) rotate(-90)" text-anchor="middle">{E(ylabel)}</text>')
    for mx, mt in (missing or []):
        log(f"  not measured at x={mx}: {mt}")
        out.append(f'<circle class="pt-hollow" cx="{sx(mx):.1f}" cy="{t + ph - 9:.1f}" r="6"/>')
        out.append(f'<text class="tick" x="{sx(mx) + 10:.1f}" y="{t + ph - 5:.1f}" text-anchor="start">{E(mt)}</text>')
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
        nx, ny = sx(last["x"]) + 10, sy(last["y"]) + 4 + s.get("name_dy", 0)
        nl = s["name"].split("\n")
        tsp = "".join(f'<tspan x="{nx:.1f}" dy="{0 if k == 0 else 12}">{E(t_)}</tspan>' for k, t_ in enumerate(nl))
        out.append(f'<text class="sname-{s["cls"]}" x="{nx:.1f}" y="{ny - 6 * (len(nl) - 1):.1f}">{tsp}</text>')
    out.append("</svg>")
    return "".join(out)


def vgroups(title, cats, series, ymax, unit, h=280, yticks=None):
    """grouped vertical bars. cats: labels. series: (name, cls, [values])."""
    log(f"chart '{title}':")
    for n, c, v in series:
        log(f"  series {n}: " + ", ".join(f"{a.replace(chr(10), ' ')}={b}" for a, b in zip(cats, v)))
    l, r, t, b = 50, 12, 14, 70 + 12 * max(c.count("\n") for c in cats)
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
            if v is None:
                out.append(f'<text class="sn" x="{x + bw / 2 - 1:.1f}" y="{t + ph + 11}" text-anchor="middle">{E(n)}</text>')
                out.append(f'<text class="val" x="{x + bw / 2 - 1:.1f}" y="{t + ph - 4:.1f}" text-anchor="middle">n/a</text>')
                continue
            out.append(f'<rect class="b-{cls}" x="{x:.1f}" y="{sy(v):.1f}" width="{bw - 2:.1f}" height="{t + ph - sy(v):.1f}" rx="2"/>')
            out.append(f'<text class="val" x="{x + bw / 2 - 1:.1f}" y="{sy(v) - 4:.1f}" text-anchor="middle">{v:g}</text>')
            out.append(f'<text class="sn" x="{x + bw / 2 - 1:.1f}" y="{t + ph + 11}" text-anchor="middle">{E(n)}</text>')
        for k, c_ in enumerate(c.split("\n")):
            out.append(f'<text class="lbl" x="{gx + gw * 0.4:.1f}" y="{t + ph + 30 + 12 * k}" text-anchor="middle">{E(c_)}</text>')
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
# Only source of numbers: the controlled table in docs/NAT-STACK-RESULTS.md ('Detailed measurements').
RESULTS = ROOT / "docs" / "NAT-STACK-RESULTS.md"
FINDINGS = ROOT / "docs" / "FINDINGS.md"
CELL = re.compile(r"^([\d.]+)\s*(?:\(([\d.]+)-([\d.]+)\))?$")


def controlled():
    """cell -> {A|B|C: mean or None} from the table under '## Detailed measurements'."""
    text = RESULTS.read_text()
    part = text.split("## Detailed measurements", 1)[1].split("\n## ", 1)[0]
    data = {}
    for line in part.splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) < 4 or not re.match(r"^(nat|nat-ft|stack-udp|l3on|l3off|zcnat)", c[0]):
            continue
        row = {}
        for k, v in zip("ABC", c[1:4]):
            m = CELL.match(v)
            row[k] = float(m.group(1)) if m else None
        data[c[0]] = row
    if not data:
        raise SystemExit(f"no controlled rows parsed from {RESULTS}")
    log(f"controlled rows parsed: {len(data)} from {RESULTS.name}")
    return data


D = controlled()
SRC = "docs/NAT-STACK-RESULTS.md 'Detailed measurements' (TrueNAS, 2026-11-09, mean of n=3)"
STK = [("A", "b", "A OpenWrt 6.18"), ("B", "a", "B OpenWrt 7.4"), ("C", "c", "C plain 7.4")]


def v(cell, s):
    return D.get(cell, {}).get(s)


def gbit(x):
    return f"{x / 1000:.2f} Gbit/s"


def sec(i, title, body):
    return f"<section id='s{i}'><h2>{i}. {E(title)}</h2>{body}</section>"


def s1():
    zc = v("zcnat-P4-fwd", "B")
    ft = v("nat-ft-P4-fwd", "C")
    l3 = v("l3on-tcp-P4-fwd", "B")
    tiles = ("<div class='tiles'>"
             f"<div class='tile'><b>{gbit(zc)}</b><span>zero-copy NAT, TCP P4 (B)</span></div>"
             f"<div class='tile'><b>{ft:.0f} Mbit/s</b><span>NAT + flowtable (C, best stack path)</span></div>"
             f"<div class='tile'><b>{gbit(l3)}</b><span>routed in the ASIC (B)</span></div></div>")
    items = [
        "IPv4 NAT: the ASIC rewrites MACs and TTL only, so every NAT packet crosses the CPU port twice.",
        "Zero-copy fast path (in-place rewrite, no skb) is the only route near 2 Gbit/s; 2.5 Gbit/s is not reachable.",
        "Limits: switch-core clock sets the 1400 B rate; CPU-bound at core 608 (one VPE 97-99 % busy); a second CPU adds nothing.",
        "No effect: ring split, NAPI split, SRAM rings, queue thresholds, cache / prefetch variants, GDMA, GRO changes.",
        "Final settings: core 608, CPU 1325 (1350 plain kernel only), DDR 662, SRAM 500, LX ~304.",
        "Full text: <a href='FINDINGS.md'>FINDINGS.md</a>. Only controlled data is plotted; old runs are history (section 8).",
    ]
    return sec(1, "Findings", tiles + ul(items) + f"<p class='src'>source: docs/FINDINGS.md; tiles from {E(SRC)}</p>")


def s2():
    cats = ["NAT\n(conntrack)", "NAT +\nflowtable", "NAT +\nzero-copy"]
    cells = ["nat-P4-fwd", "nat-ft-P4-fwd", "zcnat-P4-fwd"]
    series = [(name, cls, [v(c, k) for c in cells]) for k, cls, name in STK]
    svg = vgroups("NAT TCP P4 forward, A / B / C", cats, series, 1800, "Mbit/s", yticks=[0, 600, 1200, 1800])
    note = ("<p class='note'>A has no zero-copy path (n/a). A is not a fair head-to-head with B / C: other kernel, "
            "interrupts on CPU0 (gate NOT CONTROLLED). B vs C is CONTROLLED.</p>")
    return sec(2, "Headline NAT paths A / B / C (TCP, 4 connections, LAN to WAN)",
               fig(svg, SRC + " cells nat-P4-fwd, nat-ft-P4-fwd, zcnat-P4-fwd", "Mbit/s, higher is better") + note)


def s3():
    out = ""
    cats = ["P1\nfwd", "P1\nrev", "P2\nfwd", "P2\nrev", "P4\nfwd", "P4\nrev"]
    for k, cls, name in STK[1:]:
        series = [("nat", "neutral", [v(f"nat-P{p}-{d}", k) for p in (1, 2, 4) for d in ("fwd", "rev")]),
                  ("nat-ft", cls, [v(f"nat-ft-P{p}-{d}", k) for p in (1, 2, 4) for d in ("fwd", "rev")]),
                  ("zc", "c" if cls != "c" else "e", [v(f"zcnat-P{p}-{d}", k) if p == 4 else None
                                                       for p in (1, 2, 4) for d in ("fwd", "rev")])]
        svg = vgroups(f"nat vs nat-ft vs zc, stack {k}", cats, series, 1800, "Mbit/s", yticks=[0, 600, 1200, 1800])
        out += fig(svg, SRC + f" cells nat-P*, nat-ft-P*, zcnat-P4 (stack {k})", f"Stack {name}: nat vs nat-ft vs zc (zc measured at P4 only)")
    out += "<p class='note'>nat = conntrack + masquerade; nat-ft = + nftables software flowtable; zc = this project's in-place fast path.</p>"
    return sec(3, "nat vs nat-ft vs zc, by streams and direction", out)


def s4():
    rows = [("L3 off, CPU routes (TCP P4)", v("l3off-tcp-P4-fwd", "B"), "lose", f"{v('l3off-tcp-P4-fwd', 'B'):.0f}"),
            ("L3 on, ASIC routes (TCP P4)", v("l3on-tcp-P4-fwd", "B"), "win", f"{v('l3on-tcp-P4-fwd', 'B'):.0f}")]
    svg = hbars("Routed, directly connected networks, stack B", rows, 6000, "Mbit/s", ticks=[0, 2000, 4000, 6000])
    u = v("l3on-udp1400", "B")
    note = (f"<p class='note'>Routed UDP 1400 B with L3 on: {u:.1f} kpps (B only; no L3-off UDP row in the controlled set). "
            "Only B has the directly-connected L3 offload (<code>300-17</code>); hardware-routed traffic bypasses the CPU firewall and NAT "
            "(<a href='ROUTING-OFFLOAD.md'>ROUTING-OFFLOAD.md</a>).</p>")
    return sec(4, "Routed on / off", fig(svg, SRC + " cells l3on-tcp-P4-fwd, l3off-tcp-P4-fwd, l3on-udp1400", "Routing without NAT, stack B") + note)


def s5():
    cats = ["64 B", "500 B", "1400 B"]
    series = [(name, cls, [v(f"stack-udp{n}", k) for n in (64, 500, 1400)]) for k, cls, name in STK]
    out = fig(vgroups("routed UDP through the stack, kpps", cats, series, 100, "kpps", yticks=[0, 50, 100]), SRC + " cells stack-udp64/500/1400", "Stack UDP (normal network stack)")
    zs = [(name, cls, [v(f"zcnat-udp{n}", k) for n in (64, 500, 1400)]) for k, cls, name in STK[1:]]
    out += fig(vgroups("zero-copy NAT UDP, kpps", cats, zs, 500, "kpps", yticks=[0, 250, 500]), SRC + " cells zcnat-udp64/500/1400", "Zero-copy NAT UDP (B and C)")
    return sec(5, "UDP by frame size", out)


def s6():
    rows = [["A", "OpenWrt r38178, Linux 6.18.60", "none of this project's changes", "CPU0", "gate NOT CONTROLLED"],
            ["B", "OpenWrt r38178 + ours, Linux 7.4-rc1", "driver fixes + zero-copy + L3 offload", "CPU1", "B vs C CONTROLLED"],
            ["C", "minimal Linux 7.4-rc1 + ours", "same driver changes, no OpenWrt system", "CPU1", "B vs C CONTROLLED"]]
    t = table(["Stack", "Software", "Project changes", "NIC IRQ", "Gate"], rows)
    note = ("<p class='note'>Generator: TrueNAS. n=3 per cell, 15 s TCP / 10 s UDP. Common clock e220 <code>0x30626</code> read back on each stack. "
            "A lacks the CP0 timer fix: switch-side CPU percentages are not comparable.</p>")
    fs = []
    for line in FINDINGS.read_text().split("## Final settings", 1)[1].split("\n## ", 1)[0].splitlines():
        c = [x.strip() for x in line.strip().strip("|").split("|")]
        if len(c) == 3 and c[0] not in ("Domain",) and not set(c[0]) <= set("-"):
            fs.append(c)
    t2 = table(["Domain", "Setting", "Why the gap to the maximum"], [[re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", x) for x in r] for r in fs])
    return sec(6, "Configuration", fig(t, "docs/NAT-STACK-RESULTS.md 'What we found' and 'Detailed measurements' (stack definitions, gate state)", "Stacks compared")
               + note + fig(t2, "docs/FINDINGS.md 'Final settings' (settings, not measurements)", "Final clock settings"))


def s7():
    items = []
    for line in FINDINGS.read_text().split("## Open items", 1)[1].splitlines():
        if line.startswith("- #"):
            items.append(E(line[2:]))
    return sec(7, "Open items (NAT / clock)", ul(items) + "<p class='src'>source: docs/FINDINGS.md 'Open items' (gh issue list, 2026-11-27)</p>")


def s8():
    hist = [("NAT-HISTORY.md", "NAT / NIC experiments and dead ends"), ("NAT-STACKS.md", "old per-stack audit"),
            ("history/CAMPAIGN-PLAIN-7.4.md", "plain 7.4-rc1 campaign"), ("NAT-measurements-2026-11.md", "dated tables and image runs"),
            ("NAT-STACK-RESULTS-shared-host-2026-11.md", "shared-host and local-generator runs"),
            ("FASTEST-SETTINGS-results-2026-11.md", "core 608 bisection"), ("OVERCLOCK-experiments-2026-10.md", "first overclock survey")]
    items = [f"<a href='history/{n}'>{n}</a>: {E(d)}" for n, d in hist]
    return sec(8, "History (not comparable)",
               "<p>Old runs differ in generator, clocks, kernel, uptime and image; their numbers are kept unchanged in "
               "<a href='history/README.md'>docs/history/</a> and are not plotted here.</p>" + ul(items))



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
svg polyline{fill:none;stroke-width:2}.ln-a{stroke:var(--a)}.ln-b{stroke:var(--b)}.ln-c{stroke:var(--c)}.ln-d{stroke:var(--d);stroke-dasharray:5 4}.ln-e{stroke:var(--lose)}
.pt-d{fill:var(--d)}.pt-e{fill:var(--lose)}svg .pt-hollow{fill:none;stroke:var(--mut);stroke-width:1.5;stroke-dasharray:2 2}
.b-b{fill:var(--b)}.b-e{fill:var(--lose)}.b-hollow{fill:none;stroke:var(--mut);stroke-width:1.5;stroke-dasharray:3 3}
.m-ok{fill:var(--card);stroke:var(--line)}.m-no{fill:none;stroke:var(--mut);stroke-dasharray:3 3}
svg .sname-d{fill:var(--d);font-weight:600}svg .sname-e{fill:var(--lose);font-weight:600}
.pt-a{fill:var(--a)}.pt-b{fill:var(--b)}.pt-c{fill:var(--c)}
svg .bad{stroke:var(--bad);stroke-width:2.5;fill:none}
svg .sname-a{fill:var(--a);font-weight:600}svg .sname-b{fill:var(--b);font-weight:600}svg .sname-c{fill:var(--c);font-weight:600}
"""


def write_artifact(secs, nav, path):
    """Artifact variant: no html/head/body, explicit data-theme dark block, side gutters, md links -> GitHub."""
    import re
    css = CSS
    m = re.search(r"@media \(prefers-color-scheme:dark\)\{:root:not\(\[data-theme=light\]\)\{(.*?)\}\}", css, re.S)
    dark = m.group(1).replace("\n", "") if m else ""
    css = css.replace(m.group(0), "@media (prefers-color-scheme:dark){:root:not([data-theme=light]){" + dark + ";color-scheme:dark}}"
                      ":root[data-theme=dark]{" + dark + ";color-scheme:dark}") if m else css
    css = css.replace("main{max-width:860px;margin:0 auto;padding:16px}",
                      "main{max-width:860px;margin:0 auto;padding:16px max(16px,env(safe-area-inset-right,0px)) 16px max(16px,env(safe-area-inset-left,0px))}")
    body = "".join(secs)
    gh = "https://github.com/awto-au/awto-tl-st1008f/blob/main/docs/"
    body = re.sub(r"href=(['\"])((?:history/)?[A-Za-z0-9_.-]+\.md)", lambda mo: f"href={mo.group(1)}{gh}{mo.group(2)}", body)
    head = ("<title>NAT and clocks report</title><meta name='claude:viewport-fit-sides' content='cover'><style>" + css + "</style>"
            "<main><h1>TL-ST1008F: NAT and clocks report</h1>"
            f"<p class='sub'>Controlled data only (TrueNAS, 2026-11-09). Findings: <a href='{gh}FINDINGS.md'>FINDINGS.md</a>; live state: <a href='{gh}NAT.md'>NAT.md</a>; history: <a href='{gh}history/README.md'>docs/history/</a>. Generated by scripts/nat_report.py.</p>"
            f"<nav>{nav}</nav>")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(head + body + "</main>")
    print(f"wrote artifact page {path}")



def main():
    secs = [s1(), s2(), s3(), s4(), s5(), s6(), s7(), s8()]
    nav = " ".join(f'<a href="#s{i}">{i}</a>' for i in range(1, 9))
    doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>NAT and clocks report</title><style>" + CSS + "</style></head><body><main>"
        "<h1>TL-ST1008F: NAT and clocks report</h1>"
        "<p class='sub'>Controlled data only (TrueNAS, 2026-11-09). Findings: <a href='FINDINGS.md'>FINDINGS.md</a>; "
        "live state: <a href='NAT.md'>NAT.md</a>; history: <a href='history/README.md'>docs/history/</a>. Generated by scripts/nat_report.py.</p>"
        f"<nav>{nav}</nav>" + "".join(secs) + "</main></body></html>")
    OUT.write_text(doc)
    if "--artifact" in sys.argv:
        write_artifact(secs, nav, Path(sys.argv[sys.argv.index("--artifact") + 1]))
    LOGDIR.mkdir(parents=True, exist_ok=True)
    (LOGDIR / "nat_report.log").write_text("\n".join(LOG_LINES) + f"\nwrote {OUT} ({len(doc)} bytes)\n")
    print(f"wrote {OUT} ({len(doc)} bytes); log {LOGDIR / 'nat_report.log'}")


if __name__ == "__main__":
    sys.exit(main())
