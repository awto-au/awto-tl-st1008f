#!/usr/bin/env python3
"""openwrt_snmp — SNMP v2c read-only on a running OpenWrt switch, same community as the Omada site.

- `apk update`, `apk add snmpd luci-app-snmpd`; uci: v2c read-only community = secrets `omada.snmp_community`
  source limited to 192.168.25.0/24, IPv6 com2sec off.
- Verifies from the host with `snmpget` (sysName, ifNumber). Log: tmp/logs/openwrt_snmp.log
"""

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from boards import BENCH_IP  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/openwrt_snmp.log"
SECRETS = Path.home() / ".config/awto/secrets.yaml"
SSH_S = 5      # LAN dropbear connect ~1 s; x5
APK_S = 240    # index fetch ~8 s + snmpd/libnetsnmp ~1.5 MB + luci app; ~1-3 min worst on this MIPS; x1.25
LAN = "192.168.25.0/24"
CONFIG = r"""uci -q delete snmpd.public6
uci set snmpd.public.community="%(comm)s"
uci set snmpd.public.source='%(lan)s'
uci set snmpd.@system[0].sysName="$(uci -q get system.@system[0].hostname)"
uci set snmpd.@system[0].sysLocation='office bench'
uci commit snmpd
/etc/init.d/snmpd enable
/etc/init.d/snmpd restart
"""


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def community() -> str:
    m = re.search(r'^\s+snmp_community:\s*"?([^"\n]+)"?\s*$', SECRETS.read_text(), re.M)
    if not m:
        raise SystemExit("FAIL: omada.snmp_community missing in secrets (run awto-terminal scripts/omada.py snmp --enable)")
    return m.group(1)


def ssh(ip: str, cmd: str, limit: int, stdin: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", f"ConnectTimeout={SSH_S}", "-o", "BatchMode=yes",
                           "-o", "StrictHostKeyChecking=accept-new", f"root@{ip}", cmd],
                          input=stdin, capture_output=True, text=True, timeout=limit)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ip", default=BENCH_IP)
    a = ap.parse_args()
    comm = community()
    for name, cmd, limit in (("apk update", "apk update 2>&1 | tail -1", 120),
                             ("apk add", "apk add snmpd luci-app-snmpd 2>&1 | tail -2", APK_S)):
        r = ssh(a.ip, cmd, limit)
        log(f"{name}: rc {r.returncode}: {(r.stdout + r.stderr).strip()}")
        if r.returncode:
            return 1
    r = ssh(a.ip, "sh -s", 30, stdin=CONFIG % {"comm": comm, "lan": LAN})  # snmpd restart ~1 s; 30 s names a hang
    log(f"configure: rc {r.returncode} {r.stderr.strip()}")
    if r.returncode:
        return 1
    # snmpd binds within ~1 s of restart; 3 tries x 1 s; community from ~/.snmp/snmp.conf (omada.py snmp --enable)
    for _ in range(3):
        p = subprocess.run(["snmpget", "-t", "1", "-r", "0", "-Oqv", a.ip,  # v2c + community: ~/.snmp/snmp.conf
                            "SNMPv2-MIB::sysName.0", "IF-MIB::ifNumber.0"], capture_output=True, text=True)
        if p.returncode == 0:
            log(f"PASS: snmpget {a.ip}: sysName/ifNumber = {p.stdout.split()}")
            return 0
        time.sleep(1)
    log(f"FAIL: snmpget {a.ip}: {p.stderr.strip()}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
