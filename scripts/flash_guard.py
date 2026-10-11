#!/usr/bin/env python3
"""flash_guard — host-side gate: no flash write may overlap stock LOADER 0x0-0xDFFFF (#81).

- check_range(offset, size, what): raises FlashGuardError on overlap, empty or off-chip range.
- check_mtd(name, what): partition name / mtdN / /dev/mtd[block]N -> range check. Unknown names
  are refused (fail closed); mtd0 is LOADER in every layout we ship (partition@0 = 0x0-0xDFFFF).
- check_cmd(line): any console line (U-Boot or OpenWrt shell). Flash-writing commands (sf, mtd,
  flashcp, dd of=, > /dev/mtd, cp/mw/erase into the flash window, upgrade, *force, sysupgrade)
  get their target checked; everything else passes. Called by Console.send and the console daemon.
- Other gates: U-Boot driver (spi-realtek-rtl.c), DTS read-only. `--selftest` runs the unit tests.
"""

import re
import sys
import time
from pathlib import Path

LOG = Path(__file__).resolve().parent.parent / "tmp/logs/flash_guard.log"

LOADER = (0x0, 0xE0000)
CHIP = 0x2000000
WINDOWS = (0x14000000, 0x94000000, 0xB4000000)  # flash read window: phys, KSEG0, KSEG1
FIRMWARE = (0x300000, 0x1D00000)
# name -> (offset, size): upstream OpenWrt DTS, our U-Boot DTS (stock labels), split layout (#73)
PARTS = {
    "u-boot": LOADER, "loader": LOADER, "mtd0": LOADER,
    "u-boot-env": (0xE0000, 0x10000), "bdinfo": (0xE0000, 0x10000),
    "u-boot-env2": (0xF0000, 0x10000), "sysinfo": (0xF0000, 0x10000),
    "jffs2-cfg": (0x100000, 0x100000), "jffs2-log": (0x200000, 0x100000),
    "firmware": FIRMWARE, "kernel": FIRMWARE, "rootfs": FIRMWARE, "rootfs_data": FIRMWARE,
    "recovery": (0x1900000, 0x700000),
    "runtime1": (0x300000, 0xE80000), "runtime2": (0x1180000, 0xE80000),
}


class FlashGuardError(Exception):
    pass


def log(msg) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def check_range(offset: int, size: int, what: str = "flash write") -> None:
    end = offset + size
    if size <= 0 or offset < 0 or end > CHIP:
        raise FlashGuardError(f"REFUSED (#81): {what}: range {offset:#x}+{size:#x} is empty or off-chip")
    if offset < LOADER[1] and end > LOADER[0]:
        raise FlashGuardError(f"REFUSED (#81): {what}: {offset:#x}-{end - 1:#x} overlaps stock LOADER "
                              f"{LOADER[0]:#x}-{LOADER[1] - 1:#x}")


def check_mtd(name: str, what: str = "mtd write") -> None:
    n = re.sub(r"^/dev/", "", name.strip()).lower()
    n = re.sub(r"^mtdblock(\d+)$", r"mtd\1", n)
    n = re.sub(r"^(mtd\d+)ro$", r"\1", n)
    if re.fullmatch(r"mtd\d+", n) and n != "mtd0":
        return  # every shipped layout: index >= 1 starts at or above 0xE0000
    if n not in PARTS:
        raise FlashGuardError(f"REFUSED (#81): {what}: unknown partition {name!r} (fail closed)")
    check_range(*PARTS[n], f"{what} {name}")


def _num(tok: str) -> int:
    """U-Boot numbers: hex with or without 0x."""
    return int(tok, 16)


def _flash_off(addr: int) -> int | None:
    for base in WINDOWS:
        if base <= addr < base + CHIP:
            return addr - base
    return None


def _check_mem_dst(cmd: str, dst: str, count: str | None, what: str) -> None:
    width = {"b": 1, "w": 2, "l": 4, "q": 8}.get(cmd.partition(".")[2] or "l", 4)
    if dst.startswith("/dev/mtd"):
        return check_mtd(dst, what)  # Linux cp onto an mtd device
    try:
        off = _flash_off(_num(dst))
    except ValueError:
        return  # not a literal address (Linux `cp` paths; U-Boot $vars are not resolved here)
    try:
        n = _num(count) if count else 1
    except ValueError:
        raise FlashGuardError(f"REFUSED (#81): {what}: unparsed count {count!r}")
    if off is not None:
        check_range(off, n * width, what)


def _check_segment(seg: str) -> None:
    t = seg.split()
    if not t:
        return
    w, what = t[0], seg.strip()
    # OpenWrt / Linux: any write path into an mtd device
    for m in re.finditer(r"(?:>>?|\bof=)\s*(/dev/mtd\w*)", seg):
        check_mtd(m.group(1), what)
    if w in ("flashcp", "flash_erase", "flash_eraseall", "flash_unlock", "nandwrite", "tee", "mtd_debug"):
        for d in [x for x in t[1:] if x.startswith("/dev/mtd")]:
            check_mtd(d, what)
    elif w == "mtd":
        acts = [i for i, x in enumerate(t) if x in ("write", "jffs2write", "erase", "unlock", "fixtrx")]
        if acts:
            check_mtd(t[-1], what)
        for i, x in enumerate(t[:-1]):
            if x == "-e":
                check_mtd(t[i + 1], what)
    elif w == "mount" and any("/dev/mtd" in x for x in t) and not re.search(r"-o\s*\S*\bro\b", seg):
        for d in [x for x in t if x.startswith("/dev/mtd")]:
            check_mtd(d, what)
    elif w == "sysupgrade":
        check_mtd("firmware", what)
    elif w == "fw_setenv":
        check_range(0xE0000, 0x10000, what)
    # U-Boot (stock and ours)
    elif w == "sf" and len(t) > 1 and t[1] in ("write", "update", "erase"):
        a = t[2:]
        off_tok, len_tok = (a[1:3] + [None, None])[:2] if t[1] != "erase" else (a[0:2] + [None, None])[:2]
        if off_tok is None:
            raise FlashGuardError(f"REFUSED (#81): {what}: no offset")
        try:
            off = _num(off_tok)
        except ValueError:
            check_mtd(off_tok, what)  # partition name
            return
        try:
            size = _num((len_tok or "").lstrip("+"))
        except ValueError:
            raise FlashGuardError(f"REFUSED (#81): {what}: unparsed length {len_tok!r}")
        check_range(off, size, what)
    elif re.fullmatch(r"(cp|mw)(\.[bwlq])?", w):
        if w.startswith("cp") and len(t) >= 3:
            _check_mem_dst(w, t[2], t[3] if len(t) > 3 else None, what)
        elif w.startswith("mw") and len(t) >= 2:
            _check_mem_dst(w, t[1], t[3] if len(t) > 3 else None, what)
    elif w == "erase":
        try:
            s, e = t[1], t[2]
            start = _num(s)
            end = start + _num(e[1:]) - 1 if e.startswith("+") else _num(e)
        except (IndexError, ValueError):
            raise FlashGuardError(f"REFUSED (#81): {what}: CFI erase form not range-checkable")
        off = _flash_off(start)
        if off is not None:
            check_range(off, end - start + 1, what)
    elif w == "flerase":
        if len(t) < 2:
            raise FlashGuardError(f"REFUSED (#81): {what}: no partition")
        check_mtd(t[1], what)
    elif w == "upgrade":
        if len(t) < 2:
            raise FlashGuardError(f"REFUSED (#81): {what}: no target")
        check_mtd(t[1], what)  # loader/rom refused: loader -> LOADER, rom unknown
    elif w.endswith("force"):
        raise FlashGuardError(f"REFUSED (#81): {what}: *force rewrites the bootloader")
    elif w == "saveenv":
        check_range(0xE0000, 0x20000, what)  # env + env2 (redundant copy)


def check_cmd(line: str) -> None:
    """Raise FlashGuardError if any command in `line` writes flash over stock LOADER."""
    for seg in re.split(r"[;\r\n|&'\"]+", line):
        _check_segment(seg)


def dtb_problem(dtb: bytes) -> str | None:
    """DTS gate check on a built image's DTB: partition@0 must be read-only. None = good."""
    import subprocess
    r = subprocess.run(["dtc", "-q", "-I", "dtb", "-O", "dts", "-"], input=dtb, capture_output=True,
                       timeout=5)  # local decompile of a ~20 KB blob: < 0.1 s; 5 s names a hang
    m = re.search(rb"partition@0 \{([^}]*)\}", r.stdout)
    if r.returncode or not m:
        return f"DTB: no partition@0 (dtc rc {r.returncode})"
    return None if b"read-only;" in m.group(1) else "DTB: partition@0 (stock LOADER) not read-only (#81)"


def selftest() -> int:
    ok_cmds = [
        "mtd write /tmp/u.bin jffs2-log && echo MTD_OK",
        "mtd write /tmp/r.bin recovery && echo MTD_OK",
        "mtd write /tmp/f.bin firmware && echo MTD_OK",
        "sysupgrade -n /tmp/p.bin",
        "saveenv",
        "fw_setenv st1008f_boot fallback",
        "setenv bootcmd 'mw.l 0xa0f80000 0xa5a51008; cp.b 0x94200000 0x81000000 0x80000; go 0x81000000'",
        "sf write 0x86100000 0x1ff0000 0x100",
        "sf erase 0x1ff0000 0x1000",
        "sf erase 0xff000 0x1000",  # env2: host allows, our U-Boot driver refuses (#81 test)
        "sf update 0x86100000 0x1ff0000 0x100",
        "sf read 0x86000000 0x0 0x10000",
        "cat /dev/mtd0ro > /tmp/x",
        "hexdump -C /dev/mtdblock4 | head -4",
        "head -c 300000 /dev/mtdblock4 | md5sum",
        "dd if=/dev/mtd0 of=/tmp/loader.bin",
        "mount -t jffs2 /dev/mtdblock7 /tmp/ov && echo MNT_OK",
        "flashcp /tmp/x /dev/mtd4",
        "crc32 0xb4000000 0x2000000",
        "cp.b 0xb4000000 0x86000000 0xe0000",
        "rtk network on",
        "i=0; while [ $i -lt 4 ]; do cp /mnt/ms/seed /mnt/ms/c$i || break; i=$((i+1)); done",
        "mw.l b8001200 1fc00000",
    ]
    bad_cmds = [
        "mtd write /tmp/x u-boot", "mtd -r write /tmp/x mtd0", "mtd erase LOADER",
        "mtd -e u-boot write /tmp/x jffs2-log", "mtd write /tmp/x nosuchpart",
        "flashcp /tmp/x /dev/mtd0", "flash_erase /dev/mtd0 0 0", "dd if=/tmp/x of=/dev/mtdblock0",
        "cat /tmp/x > /dev/mtd0", "mount -t jffs2 /dev/mtdblock0 /mnt",
        "sf write 0x86000000 0x0 0x1000", "sf erase 0xd0000 0x20000", "sf update 0x86000000 0xdf000 +0x1000",
        "sf erase 0 +1000", "sf erase LOADER 0x1000", "sf erase",
        "sf probe 0; sf erase 0x0 0x10000", "setenv x 'sf erase 0 1000'",
        "cp.b 0x86000000 0xb4000000 0x100", "mw.l 0x940df000 0 4", "erase 0xb4000000 0xb40fffff",
        "erase all", "flerase LOADER", "cp /tmp/x /dev/mtd0", "upgrade loader", "upgrade rom", "loaderforce",
    ]
    fails = 0
    for c in ok_cmds:
        try:
            check_cmd(c)
        except FlashGuardError as e:
            fails += 1
            log(f"FAIL allowed cmd refused: {c!r}: {e}")
    for c in bad_cmds:
        try:
            check_cmd(c)
            fails += 1
            log(f"FAIL not refused: {c!r}")
        except FlashGuardError:
            pass
    ranges = [((0x200000, 0x100000), True), ((0xE0000, 0x10000), True), ((0xDFFFF, 1), False),
              ((0x0, 1), False), ((0xD0000, 0x20000), False), ((0x1FFF000, 0x2000), False),
              ((0x300000, 0), False)]
    for (o, s), want in ranges:
        try:
            check_range(o, s)
            got = True
        except FlashGuardError:
            got = False
        if got != want:
            fails += 1
            log(f"FAIL check_range({o:#x}, {s:#x}) ok={got}, want {want}")
    import subprocess
    for ro, want in (("read-only;", None), ("", "not read-only")):
        dts = f'/dts-v1/; / {{ partitions {{ partition@0 {{ label = "u-boot"; reg = <0 0xe0000>; {ro} }}; }}; }};'
        dtb = subprocess.run(["dtc", "-q", "-I", "dts", "-O", "dtb", "-"], input=dts.encode(),
                             capture_output=True, timeout=5).stdout  # local compile < 0.1 s
        got = dtb_problem(dtb)
        if (got is None) != (want is None) or (want and want not in got):
            fails += 1
            log(f"FAIL dtb_problem({ro or 'writable'}) = {got!r}")
    n = len(ok_cmds) + len(bad_cmds) + len(ranges) + 2
    log(f"{'PASS' if not fails else 'FAIL'} flash_guard selftest: {n - fails}/{n}")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--selftest"]:
        sys.exit(selftest())
    for arg in sys.argv[1:]:
        try:
            check_cmd(arg)
            log(f"ok: {arg}")
        except FlashGuardError as e:
            log(e)
            sys.exit(1)
