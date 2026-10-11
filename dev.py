#!/usr/bin/env python3
"""dev.py — canonical entry point for awto-tl-st1008f (awto dev.py convention).

AI agents: run `./dev.py describe` for machine-readable JSON help.
Humans: run `./dev.py --help`.

All output is timestamped in LOCAL time and mirrored to ./tmp/logs/dev.log.

TP-Link TL-ST1008F v2 (Realtek RTL9303, MIPS 34Kc BE, 8x SFP+). Every hardware
flow goes through here so it is scripted, not hand-typed: power, console, RAM
loads, builds, log checks.

Console model: scripts/switch_console_daemon.py is the ONLY owner of the UART
(unix socket + private/serial/st1008-console.log). After any power cut it must
be restarted (PL2303 RX stalls) — `power-cycle` and `ramload` do that for you.
Hazard: light ONE cage only (cage loop, #19); no flash-write commands, ever.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT = "awto-tl-st1008f"
REPO = Path(__file__).resolve().parent
TMP = REPO / "tmp"
LOGS = TMP / "logs"
LOG = LOGS / "dev.log"
SCRIPTS = REPO / "scripts"
CONSOLE_LOG = REPO / "private/serial/st1008-console.log"
CONSOLE_DEV = "/dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller-if00-port0"
SOCK = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "tio-st1008.daemon.sock"


def _stamp() -> str:
    return datetime.now().astimezone().strftime("%H:%M:%S.%f%z")  # local zone incl. DST


def log(msg: str, level: str = "INFO") -> None:
    line = f"{_stamp()}  {level:<5} [dev.py] {msg}"
    sys.stderr.write(line + "\n")
    sys.stderr.flush()
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


COMMANDS: dict[str, dict] = {}


def command(summary: str, *, args: str = "", kind: str = "action"):
    """Registry: drives dispatch, --help and describe, so they cannot drift."""
    def deco(fn):
        COMMANDS[fn.__name__.replace("cmd_", "").replace("_", "-")] = {
            "summary": summary, "args": args, "kind": kind, "fn": fn}
        return fn
    return deco


def _script(rel: str, extra: list[str], sudo: bool = False) -> int:
    p = SCRIPTS / rel
    if not p.exists():
        log(f"scripts/{rel} not found", "ERROR")
        return 1
    cmd = (["sudo", "-n"] if sudo else []) + [sys.executable, str(p), *extra]
    log("run: " + " ".join(cmd))
    rc = subprocess.call(cmd, cwd=REPO, env={**os.environ, "AWTO_VIA_DEVPY": "1"})
    log(f"rc={rc}: scripts/{rel}", "INFO" if rc == 0 else "ERROR")
    return rc


# ---- hardware: power, console, RAM loads ---------------------------------
@command("RAM-load and run an image from stock U-Boot, then check the boot log",
         args="uboot-mainline|openwrt|mainline-kernel|stock [--cage N] [--no-cycle] [--no-network]",
         kind="hardware")
def cmd_ramload(extra: list[str]) -> int:
    return _script("st1008_ramload.py", extra)


@command("get to a caught stock U-Boot prompt with networking on (power-cycle + catch)",
         args="[--cage N]", kind="hardware")
def cmd_stock(extra: list[str]) -> int:
    return _script("st1008_ramload.py", ["stock", *extra])


@command("relay control; `off`/`on` only — use `stock` for a full safe cycle",
         args="on|off", kind="hardware")
def cmd_power(extra: list[str]) -> int:
    if extra[:1] not in (["on"], ["off"]):
        log("usage: ./dev.py power on|off", "ERROR")
        return 2
    return _script("switch_power.py", extra)


@command("start/restart the console daemon (UART owner)", kind="hardware")
def cmd_console_restart(_extra: list[str]) -> int:
    subprocess.call(["pkill", "-f", "scripts/switch_console_daemon.py"])
    out = (LOGS / "switch_console_daemon.out").open("a")
    subprocess.Popen([sys.executable, str(SCRIPTS / "switch_console_daemon.py"), "--dev", CONSOLE_DEV,
                      "--baud", "115200", "--policy", "hold"], cwd=REPO, stdout=out,
                     stderr=subprocess.STDOUT, start_new_session=True)
    log("console daemon started")
    return 0


@command("send one line to the switch console and print the reply",
         args='"<text>" [--secs N]', kind="hardware")
def cmd_send(extra: list[str]) -> int:
    return _script("switch_console.py", ["send", *extra])


@command("SFP ID EEPROM / DDM from stock U-Boot", args="probe | dump --dev N | ddm --dev N --intf 0 --sda N",
         kind="hardware")
def cmd_sfp(extra: list[str]) -> int:
    return _script("st1008_sfp_ddm.py", extra)


@command("host-side broadcast-storm watcher with relay kill", args="[--duration S] [--abs-pps N]",
         kind="hardware")
def cmd_storm_watch(extra: list[str]) -> int:
    return _script("storm_watch.py", extra)


@command("on-board checks at the mainline U-Boot prompt (timer, bdinfo, dm, drivers)",
         args="[check ...]  (default: all; run `ramload uboot-mainline` first)", kind="check")
def cmd_uboot_test(extra: list[str]) -> int:
    return _script("uboot_mainline_test.py", extra)


@command("SPI-NOR read A/B under the mainline kernel: PIO vs mmio dirmap, md5 + MB/s (#61)",
         args="[--part firmware] [--modes 0,2,1]  (run `ramload mainline-kernel` first)", kind="check")
def cmd_spi_dirmap_test(extra: list[str]) -> int:
    return _script("spi_dirmap_test.py", extra)


@command("console UART baud ladder (self-restoring; board ends at 115200)",
         args="[divisor ...]  (default 47 24 12 6 5 4 3 2 1; mainline prompt)", kind="check")
def cmd_serial_speed(extra: list[str]) -> int:
    return _script("serial_speed_test.py", extra)


@command("CPU PLL experiment: set e208/e210 from SRAM, decode, measure real rate via sleep (#38)",
         args="<e210> <e208> [e208 ...] [--relock 0|1]  (ladder; values: scripts/clock_calc.py cpu <MHz>)", kind="hardware")
def cmd_cpu_clock(extra: list[str]) -> int:
    return _script("cpu_clock_step.py", extra)


@command("DDR3 clock experiment: self-refresh + MEM PLL + DTRs from SRAM; crc32/highmem verify (#39)",
         args="<MHz> [MHz ...] [--nosr]  (stock bins; e.g. 600 650; mainline prompt)", kind="hardware")
def cmd_mem_clock(extra: list[str]) -> int:
    return _script("mem_clock_step.py", extra)


@command("DDR3 probe sweep: `clocks set mem <MHz> nosr probe ...` per setting, canary-bad count each (#48 #49 #56)",
         args="field|dqshift|mpcr|once --mhz N [--reg A --fields 28:24,20:16 --values 0-31] [--extra OPTS]",
         kind="hardware")
def cmd_mem_tap_sweep(extra: list[str]) -> int:
    return _script("mem_tap_sweep.py", extra)


@command("turn bridge STP on in the flash OpenWrt config, from RAM-booted OpenWrt (#43)",
         args="(run after `ramload openwrt`)", kind="hardware")
def cmd_openwrt_flash_stp(extra: list[str]) -> int:
    return _script("openwrt_flash_stp.py", extra)


@command("boot the flash OpenWrt as an unattended power-up would; log STP/ports/uptime/temp (#43)",
         args="[--minutes 10] [--every 30]  (run storm-watch alongside)", kind="hardware")
def cmd_flash_openwrt_watch(extra: list[str]) -> int:
    return _script("flash_openwrt_watch.py", extra)


@command("running OpenWrt: static registry address .48/24, gw+DNS .254 (persists on flash OpenWrt)",
         args="[--ip A.B.C.D]", kind="hardware")
def cmd_openwrt_static_ip(extra: list[str]) -> int:
    return _script("openwrt_static_ip.py", extra)


@command("U-Boot bench (CPU/cache/DRAM/flash MB/s): run <label> | compare [label ...]",
         args="run <label> | compare [label ...]", kind="check")
def cmd_bench(extra: list[str]) -> int:
    return _script("bench.py", extra)


@command("SPI-NOR clock ladder: SFCR divider, whole-chip CRC vs baseline, bench flash (#32)",
         args="[D ...]  (default 1 0 = /4 then /2; stock D=2 = /6)", kind="hardware")
def cmd_flash_speed(extra: list[str]) -> int:
    return _script("flash_speed_step.py", extra)


@command("put our U-Boot into flash jffs2-log from the running flash OpenWrt (#47 A; no env change)",
         args="[--overwrite]", kind="hardware")
def cmd_uboot_chain_install(extra: list[str]) -> int:
    return _script("uboot_chain_install.py", extra)


@command("stock env for chainloading our U-Boot from flash (#47 A): test (no save) | apply | revert",
         args="test|apply|revert", kind="hardware")
def cmd_uboot_chain_env(extra: list[str]) -> int:
    return _script("uboot_chain_env.py", extra)


@command("mode switch (#8 #46): live = owner slides M1->M2->M3->M1 at our prompt; boot = chain power-on at a set position",
         args="live | boot --expect M1|M2|M3", kind="hardware")
def cmd_mode_map(extra: list[str]) -> int:
    return _script("mode_switch_map.py", extra)


@command("hash every file of the running flash OpenWrt's squashfs root (+ SQUASHFS error count)",
         args="<label> [--against <label>]", kind="check")
def cmd_rootfs_hash(extra: list[str]) -> int:
    return _script("openwrt_rootfs_hash.py", extra)


@command("fastest SPI-NOR clock Linux reads correctly: RAM OpenWrt reads firmware via SPI per step (#50)",
         args="[D:CODE ...]  (first = baseline; default 2:6 1:6 0:6 0:5 0:4 0:3)", kind="hardware")
def cmd_spi_linux(extra: list[str]) -> int:
    return _script("spi_linux_ladder.py", extra)


@command("live M1/M2/M3 switch position from the running OpenWrt over SSH, printed on change (#8)",
         args="[--ip A.B.C.D]", kind="check")
def cmd_mode_watch(extra: list[str]) -> int:
    return _script("mode_watch.py", extra)


@command("CPU-path NAT/routing throughput, one-armed over lan1 VLANs 991/992 (docs/NAT-OPS.md)",
         args="setup | mode nat|nat-ft|route|route-ft | run|local [--secs N] [-P N] [--reverse] "
              "[--udp MBPS --len B] | pktgen | rxdrop | v6-setup | v6-run [--onlink] [--dst A] | status | teardown",
         kind="hardware")
def cmd_nat_bench(extra: list[str]) -> int:
    return _script("nat_bench.py", extra)


@command("fill-verify most of RAM (tmpfs, md5) from the mainline 7.3 initramfs shell; meminfo check (#27)",
         args="[--passes N] [--min-total-kb K]  (run `ramload uboot-mainline --then mainline-kernel` first)",
         kind="check")
def cmd_mem_stress(extra: list[str]) -> int:
    return _script("mem_stress.py", extra)


@command("function_graph timing of rteth RX/TX under nat-bench load, mainline 7.3 initramfs (#65 #67)",
         args="[--depth N] [--roots f,g] [--load \"--secs 3 -P 4\"]  (nat-bench setup + mode first)",
         kind="hardware")
def cmd_rteth_ftrace(extra: list[str]) -> int:
    return _script("rteth_ftrace.py", extra)


@command("rteth NIC-path before/after suite on mainline 7.3: boot | run --tag T [--runs 3] | table [T ...] (#60 #65)",
         args="boot | run --tag T [--runs N] [--only L ...] | table [T ...]", kind="hardware")
def cmd_nic_bench(extra: list[str]) -> int:
    return _script("nic_path_bench.py", extra)


@command("CPU-path cost vs clocks: boot flash OpenWrt from ours with one clock change, run the nat-bench set (#65)",
         args="base|cpu800|ddr600|nopref|lx204|all|table [--bench-only]", kind="hardware")
def cmd_nat_clock_variants(extra: list[str]) -> int:
    return _script("nat_clock_variants.py", extra)


@command("dump pinmux/GPIO/I2C registers at the live prompt, or diff two dumps (#51)",
         args="capture <label> | compare <a> <b>", kind="check")
def cmd_reg_diff(extra: list[str]) -> int:
    return _script("reg_diff.py", extra)


@command("read-only presence probes of every RTL9303 block at the U-Boot prompt (#62, docs/HARDWARE-INVENTORY.md)",
         args="[--label L] [--gated]  (--gated also reads IP blocks whose enable bit is 0: may hang)", kind="check")
def cmd_hw_probe(extra: list[str]) -> int:
    return _script("hw_probe.py", extra)


@command("read-only md.l probes for hidden/disabled hardware: bonding, encap, HSA/HSM, dummy regs (#68)",
         args="[--label L] [--holes] [--alias] [--list]  (--holes/--alias read unnamed addresses: may hang)",
         kind="check")
def cmd_hidden_probe(extra: list[str]) -> int:
    return _script("hidden_probe.py", extra)


@command("owner-approved write probes (#68): eFuse read, CHIP_INFO, CHIP_MODE, free table codes, DMY r/w; "
         "every write journaled + restored",
         args="snapshot <label> | diff <a> <b> | chipinfo | efuse [--addrs R] [--en V] | chipmode <n> [--reg 7c|c6fc] "
              "[--snap] | tables | dmy  (our prompt; power cycle recovers)", kind="hardware")
def cmd_hidden_write_probe(extra: list[str]) -> int:
    return _script("hidden_write_probe.py", extra)


@command("run the rtk command list on stock and on our U-Boot, diff (see scripts/rtk_parity.py)",
         args="capture --side stock|ours | compare | both [--state] [--slow]", kind="check")
def cmd_rtk_parity(extra: list[str]) -> int:
    return _script("rtk_parity.py", extra)


# ---- builds ----------------------------------------------------------------
@command("build mainline U-Boot stage 0 (uboot-port/ -> tmp/tftp/uboot-mainline.bin)",
         args="[--clean]", kind="build")
def cmd_build_uboot(extra: list[str]) -> int:
    return _script("build_uboot_mainline.py", extra)


@command("build mainline Linux (SMP: both VPEs) and wrap it as tmp/tftp/mainline.bin",
         args="[--dtb-only] [--up] [--no-highmem]  (--up: one VPE, A/B #16; --no-highmem: 256 MiB reference #27)",
         kind="build")
def cmd_build_kernel(extra: list[str]) -> int:
    rc = _script("mainline_build_check.py", extra)
    if rc:
        return rc
    sys.path.insert(0, str(SCRIPTS))
    from mainline_build_check import out_dir
    b = out_dir("--no-highmem" in extra, "--up" in extra)
    return _script("mainline_uimage.py", ["--vmlinux", str(b / "vmlinux"), "--dtb",
                   str(b / "arch/mips/boot/dts/realtek/tplink-tl-st1008f-v2.dtb")])


# ---- checks ----------------------------------------------------------------
@command("strict allowlist check of the console boot log", args="[--boot -1|--all] [--from-line N]",
         kind="check")
def cmd_check_log(extra: list[str]) -> int:
    return _script("boot_log_check.py", extra)


# ---- meta ------------------------------------------------------------------
@command("machine-readable command list (for agents)", kind="meta")
def cmd_describe(_extra: list[str]) -> int:
    print(json.dumps({
        "project": PROJECT, "schema": 1, "entrypoint": "./dev.py",
        "log": str(LOG.relative_to(REPO)),
        "console": {"device": CONSOLE_DEV, "socket": str(SOCK), "log": str(CONSOLE_LOG.relative_to(REPO)),
                    "baud": 115200},
        "exit_codes": {"0": "success", "1": "failure / UNKNOWN log lines", "2": "usage / ERROR log lines"},
        "commands": {n: {k: v for k, v in m.items() if k != "fn"} for n, m in COMMANDS.items()},
    }, indent=2))
    return 0


@command("check tools, adapter, daemon, sudo; run this first when stuck", kind="meta")
def cmd_doctor(_extra: list[str]) -> int:
    bad = 0
    for tool in ("mips64-linux-gnu-gcc", "dtc", "ethtool", "gh", "unsquashfs", "cpio"):
        ok = shutil.which(tool) is not None
        log(f"{tool:22s}: {'ok' if ok else 'MISSING'}", "INFO" if ok else "ERROR")
        bad += not ok
    ok = Path(CONSOLE_DEV).exists()
    log(f"{'serial adapter':22s}: {'ok' if ok else 'MISSING'}", "INFO" if ok else "ERROR")
    bad += not ok
    log(f"{'console daemon':22s}: {'running' if SOCK.exists() else 'not running (./dev.py console-restart)'}",
        "INFO" if SOCK.exists() else "WARN")
    sudo_ok = subprocess.call(["sudo", "-n", "true"], stderr=subprocess.DEVNULL) == 0
    log(f"{'sudo -n (tftpd :69)':22s}: {'ok' if sudo_ok else 'needs password'}", "INFO" if sudo_ok else "WARN")
    return 1 if bad else 0


def usage() -> int:
    print(__doc__.split("Console model:")[0].rstrip())
    print("\nUsage: ./dev.py <command> [args]\n")
    order = ["hardware", "build", "check", "meta"]
    for kind in order:
        group = {n: m for n, m in COMMANDS.items() if m["kind"] == kind}
        print(f"  {kind}:")
        for name, meta in sorted(group.items()):
            arg = f" {meta['args']}" if meta["args"] else ""
            print(f"    {name:<16}{meta['summary']}{arg}")
        print()
    print(f"Log: {LOG.relative_to(REPO)}   JSON help: ./dev.py describe")
    return 2


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help", "help"):
        return usage()
    name, *extra = argv
    meta = COMMANDS.get(name)
    if meta is None:
        print(f"unknown command: {name!r} - try ./dev.py describe", file=sys.stderr)
        return 2
    if any(a in ("-h", "--help") for a in extra):  # never run a command when asked for help
        print(f"./dev.py {name}{' ' + meta['args'] if meta['args'] else ''}\n\n{meta['summary']}")
        return 0
    return meta["fn"](extra)


if __name__ == "__main__":
    sys.exit(main())
