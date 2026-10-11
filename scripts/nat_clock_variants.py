#!/usr/bin/env python3
"""nat_clock_variants — CPU-path packet cost vs clocks: boot flash OpenWrt from our U-Boot with one
clock change vs `clocks fast`, then run the nat-bench set (#65, docs/NAT.md).

- Per variant: power-cycle -> stock prompt (caught) -> ours from flash jffs2-log (no `rtk network on`,
  no chain marker = stays at the prompt) -> `clocks fast` -> variant commands -> `clocks` (logged) ->
  `bootm 0xb4300000` (flash OpenWrt) -> STP step (openwrt_stp) -> SSH up -> nat-bench set -> teardown.
- SPI stays stock in every variant (Linux SPI > stock corrupts reads, #50).
- Bench set (NAT + flowtable): TCP P4; UDP 1400 B at 600 Mbit/s offered; UDP 64 B at 100 Mbit/s offered;
  pktgen TX 1400/64 B; rxdrop RX 1400/64 B. Rows tagged with the variant in tmp/logs/nat_bench.jsonl.
- `table` prints the summary from the jsonl. Log: tmp/logs/nat_clock_variants.log
- Leaves the board in flash OpenWrt booted this way; `./dev.py uboot-chain-env boot` = normal power-up.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from st1008_ramload import OW_READY, ROOT, Console, openwrt_stp, to_stock_uboot  # noqa: E402

LOG = ROOT / "tmp/logs/nat_clock_variants.log"
JSONL = ROOT / "tmp/logs/nat_bench.jsonl"
P = r"st1008f-mainline # "
MCR = 0xB8001000
MCR_PREF = (1 << 23) | (1 << 22)

# variant -> U-Boot commands after `clocks fast` (docs/CLOCKS.md: e208/e210 table, lx codes, mem bins)
VARIANTS = {
    "base": [],
    "cpu800": ["clocks set cpu 0x3e8 0x6b439e23 force"],      # stock 800 MHz
    "ddr600": ["clocks set mem 600 nosr force"],               # stock DDR bin
    "nopref": ["MCR_PREF_OFF"],                                # MCR ip_ref/dp_ref cleared
    "lx204": ["clocks set lx 4 force"],                        # LX 175 -> 204 MHz (code 4, tested #32)
}
CONSOLE_GARBLED = {"lx204"}  # 2026-10-11: Linux console bytes unreadable after `clocks set lx 4` (DTB rate patch)
SSH = ["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "LogLevel=ERROR",
       "-o", "BatchMode=yes", "-o", "ConnectTimeout=3", "root@192.168.25.48"]
# `clocks set lx` accepts codes 2..5 only (5 = stock 175): no slower LX step exists in the command.


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def boot_variant(name: str) -> None:
    con = Console()
    to_stock_uboot(con)
    # 512 KiB copy from the cached flash window at stock SPI ~0.1 s; our banner < 1 s
    con.run("cp.b 0x94200000 0x81000000 0x80000; go 0x81000000", P, 3, "ours from flash (no network)")
    con.note("interactive-begin")
    # cpu + mem (SRAM routines) + tREFI + prefetch: < 0.1 s measured; 3 s names a hang
    con.run("clocks fast", r"clocks: fast = [^\n]*\n[^#]*" + P, 3, "clocks fast")
    for cmd in VARIANTS[name]:
        if cmd == "MCR_PREF_OFF":
            _, out = con.run(f"md.l {MCR:x} 1", r"b8001000: ([0-9a-f]{8})[^\n]*\r?\n" + P, 1, "MCR")
            v = int(out.split("b8001000: ")[1][:8], 16)
            con.run(f"mw.l {MCR:x} {v & ~MCR_PREF:08x}", P, 1, "MCR prefetch off")
            _, out = con.run(f"md.l {MCR:x} 1", r"b8001000: ([0-9a-f]{8})[^\n]*\r?\n" + P, 1, "MCR readback")
            log(f"  MCR {v:08x} -> {out.split('b8001000: ')[1][:8]}")
        else:
            # PLL/mem routines finish < 10 ms; lx re-programs the UART divisor first. 3 s names a hang
            con.run(cmd, P, 3, cmd)
    _, out = con.run("clocks", r"(?s)mem \d+ MHz.*" + P, 2, "clocks readout")
    con.note("interactive-end")
    for line in out.splitlines():
        if line.startswith(("cpu ", "lx ", "spi ", "mem ")):
            log(f"  {line.strip()}")
    if name in CONSOLE_GARBLED:
        # Linux UART output is unreadable at this LX: STP is checked over SSH instead (flash config has
        # stp=1 saved, #43); no stp_state 1 -> lan* down + relay off
        con.send("bootm 0xb4300000")
        return
    # bootm from flash + kernel to console: chain boot measured ~23 s; x1.25 + margin
    con.run("bootm 0xb4300000", OW_READY, 35, "flash OpenWrt console")
    openwrt_stp(con)


def ssh_stp_check() -> None:
    r = subprocess.run(SSH + ["cat /sys/class/net/switch/bridge/stp_state"], capture_output=True, text=True,
                       timeout=10)  # LAN login ~0.3 s; 10 s names a hang
    if r.stdout.strip() != "1":
        subprocess.run(SSH + ["for p in /sys/class/net/lan*; do ip link set ${p##*/} down; done"], timeout=10)
        subprocess.run([sys.executable, str(ROOT / "scripts/switch_power.py"), "off"], timeout=12)
        raise SystemExit(f"FAIL: stp_state {r.stdout.strip()!r} != 1 over SSH: lan* down + relay off (#19)")
    log("  STP on (checked over SSH)")


def wait_ssh(cap: float = 120) -> None:
    """Flash OpenWrt: netifd + bridge + STP forward ~45-75 s after the console (#26); cap 120 s."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < cap:
        r = subprocess.run(["ssh", "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
                            "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=2",
                            "root@192.168.25.48", "cat /sys/class/net/lan1/operstate"],
                           capture_output=True, text=True, timeout=6)  # 2 s connect + login
        if r.returncode == 0 and "up" in r.stdout:
            log(f"  ssh + lan1 up after {time.monotonic() - t0:.0f}s")
            return
        time.sleep(2)  # poll period; the boot takes tens of seconds
    raise SystemExit(f"TIMEOUT {cap}s: no ssh to .48 after flash OpenWrt boot")


def bench(name: str) -> None:
    env = {**os.environ, "NAT_BENCH_TAG": name}
    nb = [sys.executable, str(ROOT / "scripts/nat_bench.py")]
    steps = [["setup"], ["mode", "nat-ft"],
             ["run", "--secs", "10", "-P", "4", "--label", "natft-tcp-P4"],
             ["run", "--secs", "8", "-P", "1", "--udp", "600", "--len", "1400", "--label", "natft-udp1400-600M"],
             ["run", "--secs", "8", "-P", "1", "--udp", "100", "--len", "64", "--label", "natft-udp64-100M"],
             ["pktgen", "--count", "50000", "--size", "1400"], ["pktgen", "--count", "50000", "--size", "64"],
             ["rxdrop", "--secs", "5", "--size", "1400"], ["rxdrop", "--secs", "5", "--size", "64"],
             ["teardown"]]
    for st in steps:
        # longest step: 10 s iperf + omit/connect + ssh snapshots ~25 s; 90 s names a hang
        r = subprocess.run(nb + st, env=env, capture_output=True, text=True, timeout=90)
        for line in r.stdout.splitlines():
            if "RESULT" in line or "FAIL" in line or "error" in line:
                log("  " + line.split(" ", 1)[1])
        if r.returncode and st[0] not in ("teardown",):
            log(f"  step {st} rc={r.returncode}: {r.stderr.strip()[-300:]}")
            if st[0] == "mode":  # setup pings before forwarding is allowed: rc 1 there is expected
                raise SystemExit(f"FAIL: nat-bench {st[0]}")


def table() -> int:
    rows: dict = {}
    for line in JSONL.read_text().splitlines():
        r = json.loads(line)
        if r.get("tag"):
            rows.setdefault(r["tag"], {})[r["label"]] = r  # last run per (tag, label) wins
    print("| variant | NAT+ft TCP Mbit/s | µs/pkt | UDP1400 fwd kpps | UDP64 fwd kpps | "
          "TX pktgen 1400/64 kpps | RX drop 1400/64 kpps | RX µs/pkt (64) |")
    print("|---|---|---|---|---|---|---|---|")
    for tag in VARIANTS:
        d = rows.get(tag)
        if not d:
            continue

        def g(lbl, key, scale=1.0, nd=1):
            v = d.get(lbl, {}).get(key)
            return f"{v * scale:.{nd}f}" if isinstance(v, (int, float)) else "-"

        def pg(size):
            res = d.get(f"pktgen-tx-{size}B", {}).get("result", "")
            return f"{int(res.split('pps')[0].split()[-1]) / 1000:.1f}" if "pps" in res else "-"
        print(f"| {tag} | {g('natft-tcp-P4', 'mbps')} | {g('natft-tcp-P4', 'ns_vpe_per_rx_pkt', 1e-3)} | "
              f"{g('natft-udp1400-600M', 'eth0_tx_pps', 1e-3)} | {g('natft-udp64-100M', 'eth0_tx_pps', 1e-3)} | "
              f"{pg(1400)}/{pg(64)} | {g('rxdrop-1400B', 'eth0_rx_pps', 1e-3)}/"
              f"{g('rxdrop-64B', 'eth0_rx_pps', 1e-3)} | {g('rxdrop-64B', 'ns_vpe_per_pkt', 1e-3)} |")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("variant", choices=list(VARIANTS) + ["all", "table"])
    ap.add_argument("--bench-only", action="store_true", help="board already booted in this variant")
    a = ap.parse_args()
    if a.variant == "table":
        return table()
    for name in (VARIANTS if a.variant == "all" else [a.variant]):
        log(f"=== variant {name}: clocks fast + {VARIANTS[name] or 'nothing'}")
        if not a.bench_only:
            boot_variant(name)
            wait_ssh()
            ssh_stp_check()
        bench(name)
    return table()


if __name__ == "__main__":
    sys.exit(main())
