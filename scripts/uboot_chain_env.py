#!/usr/bin/env python3
"""uboot_chain_env — stock U-Boot env for chainloading our U-Boot from flash jffs2-log (#47 A).

- test:   power cycle -> stock prompt -> set the chain vars WITHOUT saving -> `run bootcmd` -> our banner,
          autoboot, flash OpenWrt. Nothing written.
- test-bad: as test, but one RAM word of the copy is changed before the check -> `cmp.l` fails ->
          `run` stops before `go` -> stock `boota` boots flash OpenWrt (#105). Nothing written.
- apply:  stock prompt: chain vars in RAM, check the jffs2-log slot with them (refuse unless it
          verifies; --allow-fallback = save anyway, boots stock `boota` until uboot-chain-install),
          then saveenv; printenv check.
- revert: stock prompt: setenv bootcmd boota; clear the chain vars; saveenv.
- prompt: power cycle with the saved chain, ESC in our 2 s window -> our prompt (#46).
- turbo show|set PROFILE: `st1008f_turbo` in the stock env (#46; applied by our U-Boot in M3 only).
  No profile (or stock values) = stock clocks in every mode; apply never writes one (owner 2026-10-13).
- --ssh --ip A.B.C.D (apply, revert, turbo): from a running OpenWrt (sw1: no console) with
  `fw_setenv -s` (uboot-envtools, /etc/fw_env.config = u-boot-env mtd 0x0 0x10000, #86): one env
  write, then `fw_printenv` read-back. apply --ssh pulls the jffs2-log slot and CRC-checks it first.
- set-mac [MAC]: stock prompt: setenv ethaddr; saveenv; verify (#91). Default: random locally
  administered unicast; refuses the Realtek placeholder and sw1's MAC.
- boot:   power cycle with the daemon policy `run bootcmd` (= the saved autoboot) and follow it to
          flash OpenWrt; daemon back to `hold` after.
- Chain (#105): ub_ld copies the 512 KiB slot from flash 0x200000 (cached window 0x94200000) to
  0x81000000; ub_ck = slot CRC32 check (scripts/uboot_chain_image.py); ub_go = marker 0xa5a51008 @
  0xa0f80000 (ours autoboots on it) + go. bootcmd = `run ub_ld ub_ck ub_go; run bootcmd_stock`:
  stock (no hush) `run` stops at the first failing var, `;` goes on to boota.
- Log: tmp/logs/uboot_chain_env.log
"""

import argparse
import random
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import flash_guard  # noqa: E402
from boards import SW1_MAC  # noqa: E402
from st1008_ramload import OW_READY, ROOT, SOCK, Console, openwrt_stp, power, restart_board, restart_daemon  # noqa: E402
JFFS2_FORMAT = r"jffs2_build_filesystem\(\): unlocking"  # overlay format: first boot after sysupgrade
from uboot_chain_image import LOAD, SLOT, check as slot_ok, stock_check_cmd  # noqa: E402

LOG = ROOT / "tmp/logs/uboot_chain_env.log"
VARS = {  # saved in this order; bootcmd last
    "bootcmd_stock": "boota",
    "ub_ld": f"cp.b 0x94200000 0x{LOAD:08x} 0x{SLOT:x}",
    "ub_ck": stock_check_cmd(),
    "ub_go": f"mw.l 0xa0f80000 0xa5a51008; go 0x{LOAD:08x}",
    "bootcmd": "run ub_ld ub_ck ub_go; run bootcmd_stock",
}
# Turbo profile (#46). Value sets mirror uboot-port clocks.c cpu_code / mem_bins / lx_pts + sram
TURBO_VAR = "st1008f_turbo"
STOCK_NOTE = "NOTE: default = stock clocks (CPU 800, DDR 600, LX 175, SRAM 250, SPI 25.5) in every mode; this unit leaves today's 1000/650 at its next power-up until a profile is written: ./dev.py uboot-chain-env turbo set PROFILE [--ssh --ip IP] + mode switch M3 (#46)"
TURBO_SETS = {"cpu": {800, 1000, 1050} | set(range(1100, 1426, 25)),
              "ddr": {800, 775, 750, 725, 700, 675, 662, 650, 625, 600, 550, 500, 450, 400, 350, 300},
              "lx": {175, 204, 245, 306}, "sram": {250, 500}, "spi": {25}}
CHECK_OK = r"Total of 1 word"   # stock cmp.l: equal
CHECK_BAD = r"word at 0x"        # stock cmp.l: differ
STOCK = r"\r?\nRTL9300# "
OURS_PROMPT = r"\r?\nst1008f-mainline # "
ESC_WINDOW = r"Autoboot in \d s, ESC for the prompt"


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def to_stock() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "scripts/st1008_ramload.py"), "stock", "--no-network"],
                       timeout=30)  # relay + daemon restart + banner ~6 s; 30 s names a hang
    if r.returncode:
        raise SystemExit(f"FAIL: no stock prompt (rc {r.returncode})")


def set_policy(policy: str) -> None:
    import json
    import socket
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(5)  # local unix socket; 5 s names a dead daemon
    s.connect(str(SOCK))
    s.sendall((json.dumps({"op": "policy", "policy": policy}) + "\n").encode())
    s.recv(65536)
    s.close()


def set_vars(con) -> None:
    """Chain vars into the stock RAM env (not saved). <= 14 words each (stock MAXARGS 16)."""
    for k, v in VARS.items():
        con.run(f"setenv {k} '{v}'" if ";" in v else f"setenv {k} {v}", STOCK, 1, f"setenv {k}")


def slot_check(con) -> bool:
    """Copy + CRC-check the jffs2-log slot with the stock commands, as the saved bootcmd does."""
    # 512 KiB copy from the cached flash window + crc32 at stock clocks: well under 0.2 s; cap 2 s
    _, out = con.run("run ub_ld ub_ck", rf"({CHECK_OK}|{CHECK_BAD})[\s\S]*?{STOCK}", 2, "slot check")
    ok = re.search(CHECK_OK, out) is not None
    log(f"slot check (stock crc32 + cmp.l): {'OK' if ok else 'MISMATCH'}")
    return ok


def stamp_check(banner: str) -> None:
    """Flashed chain U-Boot vs the source (#130, #121: a stale slot ran for a day unnoticed)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from build_uboot_mainline import src_stamp
    got = re.search(r"-st1008f-([0-9a-f]+(?:-mod)?|nogit)", banner)
    want = src_stamp().removeprefix("-st1008f-")
    if not got:
        log(f"  WARN chain U-Boot has no source stamp (built before #130): rebuild + uboot-chain-install")
    elif got[1] != want:
        log(f"  WARN chain U-Boot {got[1]} != source {want} (#130): ./dev.py build-uboot && uboot-chain-install")
    else:
        log(f"  chain U-Boot = source {want}")


def boot() -> int:
    con = Console()
    mark = restart_board(con, policy="run bootcmd")  # software reboot; relay only as fallback
    try:
        # stock banner ~2 s after power-on; chain + our banner < 1 s more; x1.25 + relay latency
        m, _ = con.expect(r"U-Boot 2026\.07[^\n(]*", 6, mark, "stock -> saved bootcmd -> our U-Boot", boot_ok=True)
        stamp_check(m.group(0))
        # clock line after the 2 s window: `bootsel: M<n>:` (#46 slot) or `clocks: fast =` (pre-#46 slot, #113)
        m, _ = con.expect(r"bootsel: M\d: [^\n]*|clocks: fast = [^\n]*", 4, mark,
                          "our autoboot: clock policy (#46)", boot_ok=True)
        log(f"  {m.group(0).strip()}")
        # 2 s ESC window + bootm from flash + kernel to console ~24 s after ours (measured 24 s with a
        # 1 s window); x1.25
        m, _ = con.expect(f"(?:{OW_READY})|{JFFS2_FORMAT}", 31, mark, "flash OpenWrt console", boot_ok=True)
        if re.search(JFFS2_FORMAT, m.group(0)):
            # first boot after a sysupgrade formats the overlay: console ~65 s later than a normal boot
            # (docs/OPENWRT-BUILD-OPS.md, #132); x1.25
            log("  first boot after sysupgrade: jffs2 overlay format, waiting longer")
            con.expect(OW_READY, 82, mark, "flash OpenWrt console (after jffs2 format)", boot_ok=True)
        openwrt_stp(con)
    finally:
        set_policy("hold")
    log("PASS boot: power-on -> stock -> saved chain -> ours -> flash OpenWrt, STP on")
    return 0


def prompt() -> int:
    """Power cycle with the saved chain; ESC in our 2 s window (#46) -> our prompt."""
    con = Console()
    mark = restart_board(con, policy="pass")  # software reboot; relay only as fallback
    # stock banner ~2.5 s after power-on + 1 s stock window + chain < 1 s + our banner: ~5 s; x1.25 + relay
    con.expect(ESC_WINDOW, 8, mark, "our 2 s ESC window", boot_ok=True)
    con.send("\x1b", cr=False)
    con.expect(OURS_PROMPT, 3, mark, "our prompt after ESC", boot_ok=True)  # window 2 s; x1.25 + echo
    log("PASS prompt: ESC stopped our autoboot")
    return 0


PLACEHOLDER = "00:e0:4c:00:00:00"


def pick_mac(mac: str | None) -> str:
    if mac is None:
        b = [random.randrange(256) for _ in range(6)]
        b[0] = (b[0] & 0xFC) | 0x02  # unicast, locally administered
        mac = ":".join(f"{x:02x}" for x in b)
    mac = mac.lower()
    if not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac) or int(mac[:2], 16) & 1:
        raise SystemExit(f"FAIL set-mac: {mac!r} is not a unicast MAC")
    if mac in (PLACEHOLDER, SW1_MAC.lower()):
        raise SystemExit(f"FAIL set-mac: {mac} is the placeholder or sw1's MAC")
    return mac


def set_mac(con, mac: str) -> int:
    _, out = con.run(f"setenv ethaddr {mac}", STOCK, 1, "setenv ethaddr")
    if "overwrite" in out.lower():
        log(f"FAIL set-mac: stock U-Boot refuses: {out.strip()!r}")
        return 1
    con.run("saveenv", STOCK, 4, "saveenv")  # 64 KiB sector erase + write, W25Q256 max 2 s; x1.25 + output
    _, out = con.run("printenv ethaddr", STOCK, 1, "verify")
    ok = f"ethaddr={mac}" in out.lower()
    log(f"{'PASS' if ok else 'FAIL'} set-mac: {out.strip()!r}")
    return 0 if ok else 1


def turbo_problem(p: str) -> str | None:
    """Host copy of bootsel.c turbo_parse + otto_turbo_check: None = our U-Boot applies it."""
    if len(p) > 62 or not p:
        return "empty or longer than 62 chars"
    for item in p.split(","):
        k, eq, v = item.partition("=")
        if not eq or not v.isdigit() or len(v) > 4:
            return f"{item!r}: not key=<decimal MHz>"
        if int(v) not in TURBO_SETS.get(k, set()):
            return f"{item!r}: unknown key or unsupported value ({k}: {sorted(TURBO_SETS.get(k, []))})"
    return None


SSH_S = 5  # dropbear connect ~1 s on the LAN; x5
ENV_WRITE_S = SSH_S + 3  # fw_setenv: one 64 KiB erase (W25Q256 max 2 s) + write; x1.25 + connect


def ssh(ip: str, cmd: str, cap: float, stdin: bytes | None = None) -> bytes:
    r = subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes", f"root@{ip}", cmd],
                       input=stdin, capture_output=True, timeout=cap)
    if r.returncode:
        raise SystemExit(f"FAIL ssh {ip}: rc {r.returncode} {r.stderr.decode(errors='replace').strip()} ({cmd[:60]})")
    return r.stdout


def ssh_env(ip: str) -> dict[str, str]:
    out = ssh(ip, "fw_printenv", SSH_S * 2).decode(errors="replace")
    return dict(ln.split("=", 1) for ln in out.splitlines() if "=" in ln)


def env_ssh(ip: str, mode: str, profile: str | None, allow_fallback: bool) -> int:
    """apply | revert | turbo over SSH: checks, one fw_setenv -s write, read-back."""
    flash_guard.check_range(0xE0000, 0x10000, f"uboot-chain-env {mode} --ssh")
    mtd = ssh(ip, "cat /proc/mtd", SSH_S * 2).decode()
    n = re.search(r'mtd(\d+): 00010000 00010000 "u-boot-env"', mtd)
    cfg = ssh(ip, "cat /etc/fw_env.config", SSH_S * 2).decode()
    lines = [ln.split() for ln in cfg.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    if not n or len(lines) != 1 or lines[0][:3] != [f"/dev/mtd{n.group(1)}", "0x0", "0x10000"]:
        log(f"FAIL {mode} --ssh: fw_env.config {lines} is not the single u-boot-env copy (mtd {n and n.group(1)})")
        return 1
    env = ssh_env(ip)
    if "ethaddr" not in env:
        log(f"FAIL {mode} --ssh: fw_printenv shows no ethaddr (env CRC bad?); nothing written")
        return 1
    if mode == "apply":
        part = re.search(r'mtd(\d+): 00100000 00010000 "jffs2-log"', mtd)
        slot = ssh(ip, f"head -c {SLOT} /dev/mtdblock{part.group(1)}", SSH_S * 2) if part else b""
        ok, detail = slot_ok(slot)
        log(f"jffs2-log slot on {ip}: {'OK' if ok else 'BAD'}, {detail}")
        if not ok and not allow_fallback:
            log("FAIL apply --ssh: slot does not verify; nothing written (uboot-chain-install-ssh first)")
            return 1
        want = dict(VARS)
        log(f"{TURBO_VAR} on {ip}: {env.get(TURBO_VAR, '(unset)')}")
        if TURBO_VAR not in env:
            log(STOCK_NOTE)
    elif mode == "revert":
        want = {"bootcmd": "boota", "ub_ld": "", "ub_ck": "", "ub_go": ""}
    else:
        want = {TURBO_VAR: profile}
    for v in want.values():
        flash_guard.check_cmd(v)
    script = "".join(f"{k} {v}\n" if v else f"{k}\n" for k, v in want.items()).encode()
    ssh(ip, "cat > /tmp/st1008f-env.txt", SSH_S * 2, stdin=script)
    flash_guard.check_cmd("fw_setenv -s /tmp/st1008f-env.txt")
    ssh(ip, "fw_setenv -s /tmp/st1008f-env.txt && rm /tmp/st1008f-env.txt", ENV_WRITE_S)
    got = ssh_env(ip)
    bad = [k for k, v in want.items() if got.get(k, "") != v] + [k for k in ("ethaddr",) if got.get(k) != env.get(k)]
    log(f"{'PASS' if not bad else 'FAIL'} {mode} --ssh {ip}: "
        f"{', '.join(f'{k}={v!r}' for k, v in want.items()) if not bad else 'differ: ' + ', '.join(bad)}")
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", choices=["test", "test-bad", "apply", "revert", "boot", "prompt", "set-mac", "turbo"])
    ap.add_argument("args", nargs="*", help="set-mac: [MAC] (default random, locally administered); "
                    "turbo: show | set PROFILE")
    ap.add_argument("--allow-fallback", action="store_true",
                    help="apply: save even if the slot does not verify (boots stock boota until reinstalled)")
    ap.add_argument("--ssh", action="store_true", help="apply/revert/turbo from a running OpenWrt (fw_setenv)")
    ap.add_argument("--ip", help="with --ssh: switch mgmt IP")
    a = ap.parse_args()
    a.mac = a.args[0] if a.mode == "set-mac" and a.args else None
    profile = None
    if a.mode == "turbo":
        if a.args[:1] == ["set"] and len(a.args) == 2:
            profile = a.args[1]
            if why := turbo_problem(profile):
                log(f"FAIL turbo set: {why}")
                return 1
        elif a.args != ["show"]:
            ap.error("turbo show | turbo set PROFILE")
    if a.ssh:
        if not a.ip or a.mode not in ("apply", "revert", "turbo"):
            ap.error("--ssh --ip A.B.C.D: apply | revert | turbo only")
        if a.mode == "turbo" and profile is None:
            log(f"{TURBO_VAR} on {a.ip}: {ssh_env(a.ip).get(TURBO_VAR, '(unset)')}")
            return 0
        return env_ssh(a.ip, a.mode, profile, a.allow_fallback)
    if a.mode == "boot":
        return boot()
    if a.mode == "prompt":
        return prompt()
    if a.mode == "set-mac":
        mac = pick_mac(a.mac)
        flash_guard.check_range(0xE0000, 0x20000, "uboot-chain-env set-mac")
        log(f"set-mac: {mac}")
        to_stock()
        return set_mac(Console(), mac)
    if a.mode in ("apply", "revert", "turbo"):  # stock saveenv: env 0xE0000 + env2 0xF0000 (#81)
        flash_guard.check_range(0xE0000, 0x20000, f"uboot-chain-env {a.mode}")
    for v in VARS.values():
        flash_guard.check_cmd(v)
    to_stock()
    con = Console()
    if a.mode == "turbo":
        _, out = con.run(f"printenv {TURBO_VAR}", STOCK, 1, "turbo profile")
        log(f"{TURBO_VAR}: {out.strip()!r}")
        if profile is None:
            return 0
        con.run(f"setenv {TURBO_VAR} {profile}", STOCK, 1, "set turbo profile")
        con.run("saveenv", STOCK, 4, "saveenv")  # 64 KiB erase + write (W25Q256 max 2 s) x1.25 + output
        _, out = con.run(f"printenv {TURBO_VAR}", STOCK, 1, "verify")
        ok = f"{TURBO_VAR}={profile}" in out
        log(f"{'PASS' if ok else 'FAIL'} turbo set {profile}")
        return 0 if ok else 1
    if a.mode in ("test", "test-bad"):
        set_vars(con)
        mark = con.size()
        if a.mode == "test":
            # slot copy + CRC < 0.2 s; our banner < 1 s after go
            m, _ = con.run("run bootcmd", rf"U-Boot 2026\.07|{CHECK_BAD}", 3, "chain (not saved) -> check")
            fell_back = m.group(0) != "U-Boot 2026.07"
            what = ("slot check FAILED -> stock boota -> flash OpenWrt (install the slot first)" if fell_back
                    else "check OK -> ours -> flash OpenWrt")
        else:
            con.run("run ub_ld", STOCK, 2, "slot copy")
            con.run(f"mw.l 0x{LOAD + 0x100:08x} 0x5a5aa5a5", STOCK, 1, "corrupt one RAM word of the copy")
            con.run("run ub_ck ub_go; run bootcmd_stock", CHECK_BAD, 2, "check must fail")
            what = "check failed -> stock boota -> flash OpenWrt"
        # no keypress here (ESC stops ours). 2 s window + bootm from flash + kernel ~25 s; x1.25 + slack
        _, out = con.expect(OW_READY, 40, mark, what)
        if a.mode == "test-bad" and re.search(r"U-Boot 2026\.07", out):
            log("FAIL test-bad: our U-Boot ran from a corrupt copy (`run` did not stop on cmp.l)")
            return 1
        openwrt_stp(con)
        if a.mode == "test" and fell_back:
            log(f"FAIL test: {what} (nothing saved; the fallback itself worked)")
            return 1
        log(f"PASS {a.mode}: {what} (nothing saved)")
        return 0
    if a.mode == "apply":
        set_vars(con)
        if not slot_check(con) and not a.allow_fallback:
            log("FAIL apply: jffs2-log slot does not verify; nothing saved. Install first "
                "(./dev.py uboot-chain-install) or --allow-fallback (boots stock boota until then)")
            return 1
        _, out = con.run(f"printenv {TURBO_VAR}", STOCK, 1, "turbo profile present?")
        if f"{TURBO_VAR}=" not in out:
            log(STOCK_NOTE)
    else:
        con.run("setenv bootcmd boota", STOCK, 1, "stock bootcmd")
        for k in ("ub_ld", "ub_ck", "ub_go"):
            con.run(f"setenv {k}", STOCK, 1, f"clear {k}")
    # saveenv: one 64 KiB env sector erase + write (W25Q256 max 2 s erase) x1.25 + output
    con.run("saveenv", STOCK, 4, "saveenv")
    names = ["bootcmd"] + (list(VARS)[:-1] if a.mode == "apply" else [])
    _, out = con.run("printenv " + " ".join(names), STOCK, 1, "verify")
    want = VARS if a.mode == "apply" else {"bootcmd": "boota"}
    bad = [k for k, v in want.items() if f"{k}={v}" not in out]
    log(f"{'PASS' if not bad else 'FAIL'} {a.mode}: {'all vars as set' if not bad else 'differ: ' + ', '.join(bad)}")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
