#!/usr/bin/env python3
"""Inventory a TP-Link managed-switch web UI (Vue `dmui` bundle) + its TDCP backend handlers.

- Input: web tree unpacked by `tplink_ow_unpack.py` (`<web>/rc_filesys/doc/js`) and the rootfs `usrImage`.
- Menu: JSON config module in `app.*.js` (`"dynamicMenu":true`); labels `$t(N)` resolved from the English i18n table.
- Per page: webpack module of `src/module/<component>.vue` plus the modules it pulls in from its own dir
  (dialogs, script, render) -> requests (`{<module>:{name|table:"x"}}`, `method:"set",<module>:{<table>:`),
  form fields (`label:$t(N),prop:"x"`) and grid columns (`label:$t(N),name:"x"`).
- Runtime menu trim: `{function:{name:"new_module_spec"}}` + path->capability map; reproduced statically as
  "backed" = a request table has a backend handler: `REGISTER_CB_FOR_TDCP_JSON` tuple, exact table-name
  string in a backend binary (not cli_server), or an `imi_slp_*` name containing it.
- Parse only, never execute. Run with `python3 -I`. Output JSON + Markdown to `--out`.
- Log: tmp/logs/tplink_webui_inventory.log
"""

import argparse
import json
import logging
import re
import sys
from pathlib import Path

log = logging.getLogger("tplink_webui_inventory")
MOD_RE = re.compile(r"[{,](\d+):function\(([\w$]+)(?:,([\w$]+))?(?:,([\w$]+))?\)\{")
FILE_RE = re.compile(r'__file="src/module/([^"]+)\.vue"')
REQ_GET_RE = re.compile(r'\{(\w+):\{(name|table):(\[[^\]]*\]|"\w+")')
REQ_SET_RE = re.compile(r'method:"(\w+)",(\w+):\{(?:(name|table):"(\w+)"|(\w+):)')
FIELD_RE = re.compile(r'label:\$t\("(\d+)"\),prop:"(\w+)"')
COL_RE = re.compile(r'\{label:\$t\("(\d+)"\),name:"(\w+)"')
REG_RE = re.compile(rb'REGISTER_CB_FOR_TDCP_JSON\("(\w+)", *"(\w+)", *TDCP_MTH_(\w+), *(\w+)\)')
SMALL_MODULE = 15000  # chars; shared component-library modules are larger
IMI_RE = re.compile(rb"\bimi_slp_\w+")
WORD_RE = re.compile(rb"(?<=\0)(\w{3,64})(?=\0)")  # whole NUL-terminated identifier strings


def strings_set(path: Path) -> tuple[set, set, set]:
    data = path.read_bytes()
    regs = {tuple(x.decode() for x in m.groups()) for m in REG_RE.finditer(data)}
    imis = {m.group().decode() for m in IMI_RE.finditer(data)}
    words = {m.group(1).decode() for m in WORD_RE.finditer(data)}
    return regs, imis, words


def load_i18n(js: Path) -> dict:
    d = next(js.glob("i18n.*.js")).read_text()
    start = d.find('e.exports={0:"Stack Management"')
    if start < 0:
        start = 0
    end = d.find(":function(e){e.exports=", start + 40)
    tbl = {}
    for m in re.finditer(r'(\d+):"((?:[^"\\]|\\.)*)"', d[start:end if end > 0 else None]):
        try:
            tbl.setdefault(m.group(1), json.loads(f'"{m.group(2)}"'))
        except ValueError:
            tbl.setdefault(m.group(1), m.group(2))
    log.info("i18n: %d English strings", len(tbl))
    return tbl


def index_modules(js: Path) -> dict:
    mods = {}
    for f in sorted(js.glob("*.js")):
        d = f.read_text(errors="replace")
        ms = list(MOD_RE.finditer(d))
        for i, m in enumerate(ms):
            body = d[m.start():ms[i + 1].start() if i + 1 < len(ms) else len(d)]
            mods.setdefault(m.group(1), {"req": m.group(4) or m.group(3) or "n", "body": body, "file": f.name})
    log.info("modules indexed: %d", len(mods))
    return mods


def page_text(comp: str, mods: dict, by_file: dict) -> str:
    """Collect the page wrapper, its own-dir siblings and the modules they pull in.

    - Follows wrappers under the same top-level module dir, and small plain modules (script, render,
      column/param configs) up to depth 3; skips the shared component library (large modules).
    """
    pdir = comp.rsplit("/", 1)[0] + "/"
    top = comp.split("/", 1)[0] + "/"
    todo = [(mid, 0) for f, mid in by_file.items()
            if f == comp or (f.startswith(pdir) and "index" not in f[len(pdir):])]
    seen, out = set(), []
    while todo:
        mid, depth = todo.pop()
        if mid in seen or mid not in mods:
            continue
        seen.add(mid)
        m = mods[mid]
        out.append(m["body"])
        if depth >= 3:
            continue
        req = re.escape(m["req"])
        for r in re.finditer(rf"\b{req}\((\d+)\)|bind\({req},(\d+)\)", m["body"]):
            rid = r.group(1) or r.group(2)
            t = mods.get(rid)
            if not t:
                continue
            tf = FILE_RE.search(t["body"])
            if (tf and tf.group(1).startswith(top)) or (tf is None and len(t["body"]) < SMALL_MODULE):
                todo.append((rid, depth + 1))
    return "\n".join(out)


def walk_menu(menu: list, tr, trail=()):
    for e in menu:
        title = tr(e.get("title") or e.get("label") or e.get("path", ""))
        here = trail + (title,) if title else trail
        if e.get("component") and not e.get("subMenu") and not e.get("tabs"):
            yield here, e
        for t in e.get("tabs", []) or []:
            yield from walk_menu([t], tr, here)
        yield from walk_menu(e.get("subMenu", []) or [], tr, here)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("web", type=Path, help="unpacked bundle root (contains rc_filesys/doc)")
    ap.add_argument("usrimage", type=Path, help="rootfs usrImage dir (app/sbin, lib)")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    Path("tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.FileHandler("tmp/logs/tplink_webui_inventory.log", "w"),
                                  logging.StreamHandler()])
    js = a.web / "rc_filesys/doc/js"
    i18n = load_i18n(js)

    def tr(s: str) -> str:
        return re.sub(r"\$t\((\d+)\)", lambda m: i18n.get(m.group(1), m.group(0)), s or "")

    app = next(js.glob("app.*.js")).read_text()
    j = app.find("JSON.parse('{\"devType\"") + len("JSON.parse('")
    cfg = json.loads(app[j:app.find("')", j)])
    capm = re.search(r"c=\{(ERPS:\"erps\".*?)\},d=", app)
    capmap = dict(re.findall(r'(\w+):(?:"([^"]*)"|l\(\))', capm.group(1))) if capm else {}

    mods = index_modules(js)
    by_file = {}
    for mid, m in mods.items():
        fm = FILE_RE.search(m["body"])
        if fm and m["body"].find("__file") < 2000 or (fm and "a.options.__file" in m["body"]):
            by_file.setdefault(fm.group(1), mid)

    backend, regs_all, imis_all, words_all = {}, set(), set(), set()
    for p in sorted(list((a.usrimage / "app/sbin").iterdir()) + list((a.usrimage / "lib").glob("*.so.1.0"))):
        if p.is_file():
            regs, imis, words = strings_set(p)
            if p.name != "cli_server":  # CLI client: its strings do not prove a backend
                words_all |= words
            if regs or imis:
                backend[p.name] = {"tdcp": sorted(regs), "imi_slp": sorted(imis)}
                regs_all |= regs
                imis_all |= imis
    reg_tables = {(r[0], r[1]) for r in regs_all}
    imi_flat = {i.lower().replace("_", "") for i in imis_all}
    log.info("backend: %d TDCP registrations, %d imi_slp handlers", len(regs_all), len(imis_all))

    def backed(mod: str, table: str) -> str:
        mod = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", mod).lower()
        if (mod, table) in reg_tables:
            return "tdcp"
        if table in words_all:
            return "string"
        key = table.lower().replace("_", "")
        if any(key in h for h in imi_flat):
            return "imi"
        return ""

    pages = []
    for trail, e in walk_menu(cfg["menu"], tr):
        comp = e["component"]
        txt = page_text(comp, mods, by_file)
        reqs = set()
        for m in REQ_GET_RE.finditer(txt):
            for t in re.findall(r'"(\w+)"', m.group(3)):
                reqs.add(("get", m.group(1), t))
        for m in REQ_SET_RE.finditer(txt):
            reqs.add((m.group(1), m.group(2), m.group(4) or m.group(5)))
        reqs = {r for r in reqs if r[1] not in ("method", "name", "table") and r[2]}
        fields = sorted({(p, i18n.get(l, l)) for l, p in FIELD_RE.findall(txt)})
        cols = sorted({(p, i18n.get(l, l)) for l, p in COL_RE.findall(txt)})
        b = sorted({backed(m, t) for _, m, t in reqs} - {""})
        pages.append({"menu": list(trail), "path": e.get("path"), "component": comp,
                      "authority": e.get("authority"), "cap_gate": capmap.get(e.get("path", ""), ""),
                      "found": bool(txt), "requests": sorted(reqs), "backed": b,
                      "fields": fields, "columns": cols})
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "webui.json").write_text(json.dumps({"pages": pages, "backend": backend, "capmap": capmap}, indent=1,
                                                 ensure_ascii=False))
    lines = ["# Web UI inventory (generated by scripts/tplink_webui_inventory.py)", ""]
    for p in pages:
        flag = "backed" if p["backed"] else ("no-backend" if p["requests"] else "static")
        lines.append(f"## {' > '.join(p['menu'])}  [{flag}]")
        lines.append(f"- component `{p['component']}` path `{p['path']}` gate `{p['cap_gate']}`")
        if p["requests"]:
            lines.append("- api: " + ", ".join(f"{m} {mod}.{t}" for m, mod, t in p["requests"]))
        if p["fields"]:
            lines.append("- fields: " + "; ".join(f"{k} ({v})" for k, v in p["fields"]))
        if p["columns"]:
            lines.append("- columns: " + "; ".join(f"{k} ({v})" for k, v in p["columns"]))
        lines.append("")
    (a.out / "webui.md").write_text("\n".join(lines))
    nb = sum(1 for p in pages if p["backed"])
    log.info("pages: %d (backed %d, with requests %d); fields %d", len(pages), nb,
             sum(1 for p in pages if p["requests"]), sum(len(p["fields"]) + len(p["columns"]) for p in pages))
    return 0


if __name__ == "__main__":
    sys.exit(main())
