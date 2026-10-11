#!/usr/bin/env python3
"""Dump the command tree of a TP-Link managed-switch `cli_server` (MIPS32 BE ELF, static tables in .data).

Node = 12 BE u32 words (48 bytes):
- 0 keyword*, 1 help* (NULL = hidden), 2 rare callback, 3 flags, 4 prompt* of the mode it enters,
  5 mode/level id, 6/7 (nchild<<16, child array*), 8/9 (nparam<<16, param array*), 10/11 (nhandler<<16, handler*).
Param = 5 words: name*, type (0x15 enum, 0x0d int, ...), flags, n, desc*; an enum desc holds "N=<k> D=..."
at +12 and a pointer at +16 to k entries of {string*, value, value}.
Handler = 4 words {flags, func*, nargs, argmap*}. Dispatch: node -> `wmcli_*` -> `cli_*` -> IMI call by
name string `imi_cli_*`; a backend daemon registers that name with `TPIMI_REGISTER_COMMAND(imi_cli_*)`.
- Root: the run of unreferenced nodes containing `configure` (exec mode).
- The binary is shared across TP-Link product lines (BGP, MPLS, BFD, PoE nodes present). `impl` = every IMI name
  the command reaches is registered by a binary in `--backend` (default: siblings of cli_server + ../../lib).
- Parse only, never execute. Run with `python3 -I`. Needs pyelftools.
- Log: tmp/logs/tplink_cli_tree.log
"""

import argparse
import collections
import json
import logging
import re
import struct
import sys
from pathlib import Path

from elftools.elf.elffile import ELFFile

log = logging.getLogger("tplink_cli_tree")
NODE = 48
MAX_DEPTH = 24
FN_SCAN = 600  # instructions scanned per handler function before giving up on finding jr ra
REG_RE = re.compile(rb"TPIMI_REGISTER_COMMAND(?:_SHOW)?\((imi_cli_\w+)\)")


class Img:
    def __init__(self, path: Path):
        self.raw = path.read_bytes()
        with path.open("rb") as f:
            secs = {s.name: (s["sh_addr"], s["sh_size"], s["sh_offset"]) for s in ELFFile(f).iter_sections()}
        self.ro, self.da, self.tx = secs[".rodata"], secs[".data"], secs[".text"]
        self.sym = {}
        with path.open("rb") as f:
            for sec in ELFFile(f).iter_sections():
                if sec.name in (".symtab", ".dynsym"):
                    for sy in sec.iter_symbols():
                        if sy["st_info"]["type"] == "STT_FUNC" and sy["st_value"]:
                            self.sym.setdefault(sy["st_value"], sy.name)

    def ins(self, va):
        return struct.unpack_from(">I", self.raw, self.tx[2] + va - self.tx[0])[0]

    def istx(self, va):
        return self.tx[0] <= va < self.tx[0] + self.tx[1]

    def imi_names(self, fn, depth=0, memo=None):
        """`imi_cli_*` strings built with lui/addiu in fn and in .text callees (j/jal), 2 levels deep."""
        memo = {} if memo is None else memo
        if fn in memo:
            return memo[fn]
        memo[fn] = set()
        hi, out, calls = {}, set(), []
        for k in range(FN_SCAN):
            i = self.ins(fn + 4 * k)
            op, rs, rt, imm = i >> 26, (i >> 21) & 31, (i >> 16) & 31, i & 0xffff
            if op == 0xf:
                hi[rt] = imm << 16
            elif op == 9 and rs in hi:
                st = self.s((hi[rs] + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xffffffff)
                if st and st.startswith("imi_cli_"):
                    out.add(st)
            elif op in (2, 3):
                calls.append(((fn + 4 * k) & 0xf0000000) | ((i & 0x3ffffff) << 2))
            if i == 0x03e00008:  # jr ra
                break
        if depth < 2:
            for c in calls:
                if self.istx(c):
                    out |= self.imi_names(c, depth + 1, memo)
        memo[fn] = out
        return out

    def isro(self, v):
        return self.ro[0] <= v < self.ro[0] + self.ro[1]

    def isda(self, v):
        return self.da[0] <= v < self.da[0] + self.da[1] - 4

    def w(self, va):
        return struct.unpack_from(">I", self.raw, self.da[2] + va - self.da[0])[0]

    def s(self, va):
        if not va or not self.isro(va):
            return None
        o = self.ro[2] + va - self.ro[0]
        return self.raw[o:self.raw.find(b"\0", o)].decode("latin1")


def is_node(img, va):
    ws = [img.w(va + 4 * i) for i in range(12)]
    if not img.isro(ws[0]) or not (ws[1] == 0 or img.isro(ws[1])):
        return None
    for i in (6, 8, 10):
        if ws[i] & 0xffff or (ws[i] >> 16) > 512:
            return None
        if (ws[i] >> 16) and not img.isda(ws[i + 1]):
            return None
        if not (ws[i] >> 16) and ws[i + 1]:
            return None
    return ws


def params(img, ws):
    out = []
    for k in range(ws[8] >> 16):
        p = ws[9] + 20 * k
        name, typ, desc = img.s(img.w(p)), img.w(p + 4), img.w(p + 16)
        choices = []
        if img.isda(desc):
            spec = img.s(img.w(desc + 12)) or ""
            m = re.match(r"N=(\d+)", spec)
            lst = img.w(desc + 16)
            if m and img.isda(lst):
                for j in range(min(int(m.group(1)), 64)):
                    c = img.s(img.w(lst + 12 * j))
                    if c:
                        choices.append(c)
        out.append({"name": name, "type": typ, "choices": choices})
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cli_server", type=Path)
    ap.add_argument("--out", type=Path, required=True, help="output dir (put it under private/)")
    ap.add_argument("--backend", type=Path, nargs="*", help="backend ELF files registering imi_cli_* names")
    a = ap.parse_args()
    Path("tmp/logs").mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(message)s",
                        handlers=[logging.FileHandler("tmp/logs/tplink_cli_tree.log", "w"),
                                  logging.StreamHandler()])
    img = Img(a.cli_server)
    be = a.backend or [p for p in list(a.cli_server.parent.iterdir()) + list((a.cli_server.parent / "../../lib").glob("*.so.1.0"))
                       + list((a.cli_server.parent / "../../frr").iterdir()) if p.is_file()]
    registered = {}
    for p in be:
        for m in REG_RE.finditer(p.read_bytes()):
            registered.setdefault(m.group(1).decode(), p.name)
    log.info("backend IMI registrations: %d", len(registered))
    memo = {}
    nodes = {}
    for va in range(img.da[0], img.da[0] + img.da[1] - NODE, 4):
        ws = is_node(img, va)
        if ws:
            nodes[va] = ws
    child = {ws[7] + NODE * k for ws in nodes.values() for k in range(ws[6] >> 16)}
    roots = sorted(set(nodes) - child)
    runs, cur = [], []
    for r in roots:
        if cur and r == cur[-1] + NODE:
            cur.append(r)
        else:
            if cur:
                runs.append(cur)
            cur = [r]
    runs.append(cur)
    root = next(r for r in runs if "configure" in [img.s(nodes[v][0]) for v in r])
    log.info("node candidates %d, exec root %#x (%d entries)", len(nodes), root[0], len(root))

    cmds, seen = [], set()

    def walk(arr, n, path, mode, depth):
        for k in range(n):
            va = arr + NODE * k
            ws = nodes.get(va) or is_node(img, va)
            if not ws or depth > MAX_DEPTH:
                continue
            kw, hlp = img.s(ws[0]), img.s(ws[1])
            here = path + [kw]
            newmode = img.s(ws[4]) or mode
            if ws[10] >> 16:
                fns = [img.w(ws[11] + 16 * j + 4) for j in range(ws[10] >> 16)]
                fns = [f for f in fns if img.istx(f)]
                imis = sorted(set().union(*[img.imi_names(f, 0, memo) for f in fns])) if fns else []
                owners = sorted({registered[i] for i in imis if i in registered})
                impl = bool(imis) and all(i in registered for i in imis)
                cmds.append({"mode": mode, "cmd": " ".join(here), "help": hlp, "hidden": hlp is None,
                             "flags": ws[3], "params": params(img, ws), "enters": img.s(ws[4]),
                             "handlers": [img.sym.get(f, hex(f)) for f in fns], "imi": imis,
                             "backend": owners, "impl": impl})
            if ws[6] >> 16 and (va, mode) not in seen:
                seen.add((va, mode))
                walk(ws[7], ws[6] >> 16, here, newmode, depth + 1)

    walk(root[0], len(root), [], "exec", 0)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "cli-tree.json").write_text(json.dumps(cmds, indent=1))
    lines = []
    for c in cmds:
        ps = " ".join(f"<{p['name']}{'=' + '|'.join(p['choices']) if p['choices'] else ''}>" for p in c["params"])
        tag = ("IMPL " + ",".join(c["backend"])) if c["impl"] else ("local" if not c["imi"] else "NOBACKEND")
        lines.append(f"{tag:24} {c['mode']:20} {c['cmd']} {ps}".rstrip() + ("   [hidden]" if c["hidden"] else
                                                                            f"   -- {c['help']}"))
    (a.out / "cli-tree.txt").write_text("\n".join(lines) + "\n")
    top = collections.Counter()
    for c in cmds:
        parts = c["cmd"].split()
        key = parts[1] if parts[0] in ("configure", "show", "no", "clear", "debug") and len(parts) > 1 else parts[0]
        top[(parts[0] if parts[0] in ("show", "clear", "debug") else "cfg", key)] += 1
    log.info("commands %d (hidden %d), modes %d; impl %d, local %d, no-backend %d", len(cmds),
             sum(c["hidden"] for c in cmds), len({c["mode"] for c in cmds}), sum(c["impl"] for c in cmds),
             sum(not c["imi"] for c in cmds), sum(bool(c["imi"]) and not c["impl"] for c in cmds))
    (a.out / "cli-groups.json").write_text(json.dumps(sorted(([*k, v] for k, v in top.items())), indent=0))
    return 0


if __name__ == "__main__":
    sys.exit(main())
