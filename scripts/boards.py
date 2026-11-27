"""Which ST1008F unit is which. Addresses: awto-terminal ip-registry (st1008f-1/-2 blocks).

- Identity (name, mgmt IP, MAC) stays with the hardware (owner 2026-11-27).
- Role follows the position: BENCH = relay (.49) + serial console, every hardware flow targets it;
  LAB = no relay, no serial, network checks only, reboot only on owner request (guards refuse it).
- Units swapped position 2026-11-27 (#186: faulty sw1 onto the bench): flip BENCH_UNIT only.
"""

SW1_IP = "192.168.25.48"     # st1008f-1-mgmt
SW2_IP = "192.168.25.56"     # st1008f-2-mgmt
SW1_MAC = "16:b0:46:e9:0d:c0"  # sw1 base MAC (u-boot-env ethaddr; docs/hardware.md)
SW2_MAC = "3a:de:0a:91:10:d0"  # sw2 base MAC (set-mac 2026-10-12)

BENCH_UNIT = "sw1"  # unit on the relay + serial console (sw2 until the 2026-11-28 swap, #186)
_UNITS = {"sw1": (SW1_IP, SW1_MAC), "sw2": (SW2_IP, SW2_MAC)}
LAB_UNIT = "sw1" if BENCH_UNIT == "sw2" else "sw2"
BENCH_IP, BENCH_MAC = _UNITS[BENCH_UNIT]  # ramload, nat-bench, U-Boot ipaddr
LAB_IP, LAB_MAC = _UNITS[LAB_UNIT]
BENCH_CONSOLE = "/dev/serial/by-id/usb-1a86_USB2.0-Serial-if00-port0"  # bench UART (CH340 "USB2.0-Serial", 2026-11-18); the Prolific PL2303 is the US-48 bench console

BENCH_NIC_MAC = "00:02:c9:56:ff:e2"  # selwyn 10G NIC (bench cage 1, .30); its enpNs0 name moves between boots


def bench_nic(default: str = "enp7s0") -> str:
    """Host interface carrying BENCH_NIC_MAC (kernel names change with PCI enumeration)."""
    from pathlib import Path
    for p in Path("/sys/class/net").iterdir():
        try:
            if (p / "address").read_text().strip().lower() == BENCH_NIC_MAC:
                return p.name
        except OSError:
            continue
    return default


# Hostname = registry box name (awto-terminal ip-registry `[[block]] name`); sw1/sw2 are short aliases only.
HOSTNAMES = {SW1_IP: "st1008f-1", SW2_IP: "st1008f-2"}
