"""Which ST1008F unit is which (owner, 2026-10-12). Addresses: awto-dan ip-registry (st1008f-1/-2 blocks).

- sw1 = st1008f-1: in service as the house switch, mgmt .48, no relay, no serial. Never power-cycle or ramload.
- sw2 = st1008f-2: bench unit on the relay (.49) and the serial console; every hardware flow targets it.
"""

SW1_IP = "192.168.25.48"     # st1008f-1-mgmt (production)
SW1_MAC = "16:b0:46:e9:0d:c0"  # sw1 base MAC (u-boot-env ethaddr; docs/hardware.md)
SW2_MAC = "3a:de:0a:91:10:d0"  # sw2 base MAC (set-mac 2026-10-12)
BENCH_IP = "192.168.25.56"   # st1008f-2-mgmt (bench: ramload, nat-bench, U-Boot ipaddr)
BENCH_CONSOLE = "/dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller-if00-port0"  # sw2 UART (PL2303)

# Hostname = registry box name (awto-dan ip-registry `[[block]] name`); sw1/sw2 are short aliases only.
HOSTNAMES = {SW1_IP: "st1008f-1", BENCH_IP: "st1008f-2"}
