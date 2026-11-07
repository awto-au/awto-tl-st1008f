#!/usr/bin/env python3
"""uboot_chain_layout — the ONE definition of our U-Boot chain slot size in flash `jffs2-log` (#155).

- Default 0x80000 (512 KiB). Select 0xF0000 (960 KiB) with env `UBOOT_CHAIN_SLOT=0xF0000` or the
  flag `--chain-slot 0xF0000` (read from sys.argv at import, so every script that imports this agrees).
- Users: uboot_chain_image (build/check), uboot_chain_env (ub_ld/ub_ck), uboot_chain_install,
  flash_guard (check_chain_slot), build_uboot_mainline, st1008_ramload --from-flash, nat_clock_variants.
- Hard limits (refused in `validate`): inside 0x200000-0x2EFFFF (bootstate at 0x2F0000 is never
  touched), multiple of the 64 KiB erase sector, > trailer. Stock area 0x0-0xDFFFF is flash_guard's.
- `--selftest`: pure-Python regression (default strings byte-equal to the live env) + 960 KiB build.
- Log: tmp/logs/uboot_chain_layout.log
"""

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/uboot_chain_layout.log"

DEFAULT_SLOT = 0x80000
REGION_START = 0x200000      # flash offset of jffs2-log = slot start
REGION_END = 0x2F0000        # bootstate (A/B record, Linux-owned): never touched
ERASE = 0x10000              # W25Q256 64 KiB erase sector (mtd erase block)
TRAILER_SIZE = 0x40
FLASH_WINDOW = 0x94200000    # KSEG0 cached read window of flash 0x200000
LOAD = 0x81000000            # TEXT_BASE; ub_ld copies the slot here
SCRATCH = 0x80ffff00         # stock `crc32` result word, below LOAD
STOCK_UBOOT_RAM = 0x83f00000  # stock U-Boot runs here: the copy must end below it


def validate(slot: int) -> int:
    """Return slot or raise SystemExit naming the rule it breaks."""
    if slot % ERASE:
        raise SystemExit(f"FAIL chain slot {slot:#x}: not a multiple of the {ERASE:#x} erase sector")
    if slot <= TRAILER_SIZE + 0x1000:
        raise SystemExit(f"FAIL chain slot {slot:#x}: too small for an image + trailer")
    if REGION_START + slot > REGION_END:
        raise SystemExit(f"FAIL chain slot {slot:#x}: ends at {REGION_START + slot:#x}, past {REGION_END:#x} "
                         f"(bootstate at {REGION_END:#x} is never touched; max {REGION_END - REGION_START:#x})")
    if LOAD + slot > STOCK_UBOOT_RAM:
        raise SystemExit(f"FAIL chain slot {slot:#x}: RAM copy overlaps stock U-Boot at {STOCK_UBOOT_RAM:#x}")
    return slot


def _requested() -> int:
    argv = sys.argv
    for i, a in enumerate(argv):
        if a == "--chain-slot" and i + 1 < len(argv):
            return int(argv[i + 1], 0)
        if a.startswith("--chain-slot="):
            return int(a.split("=", 1)[1], 0)
    return int(os.environ.get("UBOOT_CHAIN_SLOT") or str(DEFAULT_SLOT), 0)


SLOT = validate(_requested())
IS_DEFAULT = SLOT == DEFAULT_SLOT


def trailer(slot: int = SLOT) -> int:
    return slot - TRAILER_SIZE


def ld_cmd(slot: int = SLOT) -> str:
    return f"cp.b 0x{FLASH_WINDOW:08x} 0x{LOAD:08x} 0x{slot:x}"


def ck_cmd(slot: int = SLOT) -> str:
    """crc32 over slot-4 bytes at LOAD vs the slot's last word. Stock: no hush, no `crc32 -v`."""
    return (f"crc32 0x{LOAD:08x} 0x{slot - 4:x} 0x{SCRATCH:08x}; "
            f"cmp.l 0x{SCRATCH:08x} 0x{LOAD + slot - 4:08x} 1")


def check_pair(env_slot: int, image_len: int) -> None:
    """Env copy length and the image in/for the flash slot must be the same. Host pre-check:
    a mismatch must never reach the board (env 512 KiB + image 960 KiB, or the reverse)."""
    validate(env_slot)
    if image_len != env_slot:
        raise SystemExit(f"FAIL chain slot mismatch: env copies {env_slot:#x} B, image is {image_len:#x} B "
                         f"(UBOOT_CHAIN_SLOT / --chain-slot must match the image; nothing sent to the board)")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


# Strings as shipped before #155 (docs/DEFAULT-BOOT.md): the default must stay byte-equal.
OLD_LD = "cp.b 0x94200000 0x81000000 0x80000"
OLD_CK = "crc32 0x81000000 0x7fffc 0x80ffff00; cmp.l 0x80ffff00 0x8107fffc 1"


def selftest() -> int:
    import struct
    import zlib
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import uboot_chain_image as img
    import flash_guard
    fails = 0

    def expect(ok: bool, what: str) -> None:
        nonlocal fails
        if not ok:
            fails += 1
        log(f"{'ok  ' if ok else 'FAIL'} {what}")

    def refuses(fn, *a) -> bool:
        try:
            fn(*a)
        except (SystemExit, flash_guard.FlashGuardError):
            return True
        return False

    expect(ld_cmd(DEFAULT_SLOT) == OLD_LD and ck_cmd(DEFAULT_SLOT) == OLD_CK,
           f"default strings byte-equal to the live env: {ld_cmd(DEFAULT_SLOT)!r} / {ck_cmd(DEFAULT_SLOT)!r}")
    new = 0xF0000
    log(f"960 KiB ub_ld = {ld_cmd(new)}")
    log(f"960 KiB ub_ck = {ck_cmd(new)}")
    expect(ck_cmd(new) == "crc32 0x81000000 0xefffc 0x80ffff00; cmp.l 0x80ffff00 0x810efffc 1",
           "960 KiB ub_ck = crc32 len 0xefffc, cmp.l at 0x810efffc")
    expect(len(ck_cmd(new).split()) <= 14 and len(ld_cmd(new).split()) <= 14, "each var <= 14 words")
    for bad in (0x100000, 0xF1000, 0x110000, 0x1000, 0, 0x2000000):
        expect(refuses(validate, bad), f"validate refuses {bad:#x} (bootstate/alignment/size)")
    for good in (0x80000, 0xA0000, 0xF0000):
        expect(not refuses(validate, good), f"validate accepts {good:#x}")
    expect(refuses(check_pair, 0x80000, 0xF0000) and refuses(check_pair, 0xF0000, 0x80000),
           "check_pair refuses 512K env + 960K image and the reverse")
    expect(not refuses(check_pair, 0xF0000, 0xF0000), "check_pair accepts equal")
    expect(not refuses(flash_guard.check_chain_slot, new), "flash_guard accepts 0x200000+0xF0000")
    expect(refuses(flash_guard.check_chain_slot, 0x100000), "flash_guard refuses a slot reaching bootstate")
    expect(refuses(flash_guard.check_chain_slot, 0x80000, 'x', 0x1F0000), "flash_guard refuses a write below 0x200000")
    expect(refuses(flash_guard.check_chain_slot, 0x80000, 'x', 0x2F0000), "flash_guard refuses a write at bootstate")

    # regression: rebuild the live default slots with the new code, same name -> byte-identical
    tftp = ROOT / "tmp/tftp"
    for name in ("uboot-mainline-chain.bin", "uboot-mainline-b2-chain.bin"):
        p = tftp / name
        if not p.exists():
            log(f"skip {name} (absent)")
            continue
        old = p.read_bytes()
        t = old[DEFAULT_SLOT - TRAILER_SIZE:]
        size, = struct.unpack(">I", t[16:20])
        nm = t[24:56].split(b"\x00")[0].decode()
        expect(img.make(old[:size], nm, DEFAULT_SLOT) == old, f"default 512 KiB rebuild of {name} is byte-identical ({size} B, {nm!r})")
    raw = tftp / "uboot-mainline-b2.bin"
    if raw.exists():
        data = raw.read_bytes()
        s960 = img.make(data, "selftest", new)
        ok, detail = img.check(s960, new)
        expect(len(s960) == new and ok, f"960 KiB image from {raw.name} ({len(data)} B): {detail}")
        expect(struct.unpack(">I", s960[-4:])[0] == zlib.crc32(s960[:-4]), "960 KiB last word = CRC32 of bytes 0..slot-5")
        expect(img.check(s960, DEFAULT_SLOT)[0] is False, "960 KiB image fails the 512 KiB check")
        expect(img.check(s960[:DEFAULT_SLOT], new)[0] is False, "512 KiB truncation fails the 960 KiB check")
        expect(img.check(img.make(data, "selftest", DEFAULT_SLOT), new)[0] is False, "512 KiB image fails the 960 KiB check")
    else:
        expect(False, f"{raw} missing")
    log(f"{'PASS' if not fails else 'FAIL'} uboot_chain_layout selftest ({fails} failures)")
    return 1 if fails else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    log(f"chain slot {SLOT:#x} ({'default' if IS_DEFAULT else 'NON-DEFAULT'}), trailer {trailer():#x}")
    log(f"ub_ld={ld_cmd()}")
    log(f"ub_ck={ck_cmd()}")
