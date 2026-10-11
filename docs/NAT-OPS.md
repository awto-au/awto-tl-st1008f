# NAT measurements: operations

Facts and results: [NAT.md](NAT.md). Everything runs through `./dev.py nat-bench` (`scripts/nat_bench.py`). Log: `tmp/logs/nat_bench.log`; one JSON row per run: `tmp/logs/nat_bench.jsonl`.

## Preconditions

- Board runs OpenWrt reachable at `192.168.25.48`, with SSH as root and no password. This is either the flash OpenWrt (normal power-up) or `./dev.py ramload openwrt` plus a static IP.
- Packages installed in the switch overlay: `iperf3 ip-full ip-bridge tcpdump-mini kmod-pktgen`.
  - Install: `apk update && apk add ...`. This writes to the flash overlay, which is allowed.
  - `kmod-pktgen` must match the kernel's kmods hash in `/etc/apk/repositories.d`.
- Host side: `enp7s0` (10G), `sudo -n`, `iperf3`.
- Run `./dev.py storm-watch --duration 3600` alongside any test that changes switching.

## Topology and safety

- Host netns `natlan` uses `enp7s0.991` (10.99.1.2, fd99:1::2). Host netns `natwan` uses `enp7s0.992` (10.99.2.2, fd99:2::2).
- Switch SVIs are `switch.991` (10.99.1.1) and `switch.992` (10.99.2.1).
- VLANs 991/992 are tagged on lan1 only. They are never in VLAN 1, there is no DHCP, and masquerade applies only out `switch.992`.
- All switch config is runtime only (bridge/ip/nft), with no `uci commit`. A reboot or `teardown` removes it.
- The test subifs get MTU 1500 and their own MACs (`02:99:00:00:09:9x`):
  - The host NIC runs MTU 9000. Jumbo frames land in lan1 `ParserErrors`/`rx_MacDiscards` and TCP stalls silently.
  - With a shared MAC and link-local address, v6 ND towards natwan failed.
- fw4 gets rules tagged `nattest`: forward accept for the test SVIs, and input accept for ICMPv6 ND and for the local iperf3 server. `teardown` reloads fw4.
- The `rxdrop` flood runs at up to ~9 Gbit/s unicast towards the switch MAC across the house switch. Keep `--secs` short.

## Commands

```
./dev.py nat-bench setup                     # SVIs + host netns, ping check
./dev.py nat-bench mode nat|nat-ft|route|route-ft
./dev.py nat-bench run --secs 10 -P 4 [--reverse]               # TCP natlan -> natwan
./dev.py nat-bench run --secs 10 -P 1 --udp 250 --len 1400      # UDP, loss %
./dev.py nat-bench local --secs 10 -P 1 [--reverse]             # CPU-terminated iperf3
./dev.py nat-bench pktgen --count 50000 --size 1400             # TX-only driver cost
./dev.py nat-bench rxdrop --secs 8 --size 64                    # RX-only driver cost
./dev.py nat-bench v6-setup                                     # gateway-routed v6 far /64s
./dev.py nat-bench v6-run --secs 10 -P 4 [--onlink] [--dst 2001:db8:22::5]
./dev.py nat-bench teardown
```

- `mode` replaces the `inet nattest` table:
  - `nat` = masquerade.
  - `-ft` = flowtable `ft` on `lan1` plus `flow add` for tcp/udp in the forward hook.
  - `route` = no NAT, and natwan gets a route back to 10.99.1.0/24.
- Testing the v6 default-route workaround:
  - On the switch: `ip -6 route replace 2000::/3 via fd99:2::2 dev switch.992`.
  - Host: `ip -n natwan -6 addr add 2001:db8:22::5/128 dev enp7s0.992 nodad`.
  - Then `v6-run --dst 2001:db8:22::5`. `teardown` removes the route.
- Runtime knobs tested:
  - RPS: `echo 2 > /sys/class/net/eth0/queues/rx-{0,1}/rps_cpus`; `0` restores. It measured worse.
  - GRO: `ethtool -K eth0|lan1 gro off rx-gro-list off`; the default is on, which is slightly better.

## Clock variants

```
./dev.py nat-clock-variants base|cpu800|ddr600|nopref|lx204   # one boot + bench set each
./dev.py nat-clock-variants table                             # summary from tmp/logs/nat_bench.jsonl
```

- Steps per variant:
  - Power cycle to the stock prompt.
  - Load ours from flash (`--from-flash` path, no `rtk network on`).
  - `clocks fast`, then the variant's command, then `clocks` (logged).
  - `bootm 0xb4300000`, then the STP step on the console (`openwrt_stp`).
  - SSH up, then the bench set, then teardown.
- `lx204`: the Linux console is unreadable. STP is checked over SSH instead; if `stp_state` is not 1, lan* go down and the relay goes off.
- Ends in flash OpenWrt booted this way. Normal power-up: `./dev.py uboot-chain-env boot`.
- Rows carry `"tag": <variant>` (env `NAT_BENCH_TAG`).

## Reading results

- `RESULT` line fields:
  - iperf3 goodput.
  - CPU-port (eth0) Mbit/s and pps per direction, and driver `rx_dropped`.
  - IRQ/s.
  - Per-VPE busy and softirq % (`/proc/stat`).
  - `VPE-ns/pkt` = busy VPE time / eth0 RX packets.
- HW-offload proof: eth0 pps stays near 0 and `realtek_otto_l3/routes` shows `fwd`.
- eth0 byte counters are 32-bit; the script takes deltas mod 2^32.
- `rxdrop` rate = eth0 `rx_packets`. With rx-gro-list on (default), the lan1 ingress counter sees GRO skbs, not packets.
- Registers are read-only: `/sys/kernel/debug/regmap/dummy-ethernet-switch@0x1b000000/registers`. There is no `/dev/mem` or devmem in the OpenWrt image.

## Recover

- `./dev.py nat-bench teardown`.
- If SSH is lost: reboot via the console (`./dev.py send "reboot"`) or run `./dev.py uboot-chain-env boot`. The flash OpenWrt comes back clean at `.48` with STP on.
