# HW L3 routing offload: operations (#59, `300-17`)

Facts and design: [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md). Bench: `./dev.py nat-bench` ([NAT-OPS.md](NAT-OPS.md) for topology, safety, result fields). Log `tmp/logs/nat_bench.log`, rows `tmp/logs/nat_bench.jsonl`.

## Preconditions

- Kernel with `300-17`: `./dev.py build-kernel --up` (the SMP default is untested here).
- One cage only (cage loop hazard, CLAUDE.md): `./dev.py ramload uboot-mainline --then mainline-kernel --cage 1`, then `port-up 1 192.168.25.48/24` on the console. Other fibres unplugged.
- `./dev.py storm-watch --duration 3600` running alongside.
- `./dev.py check-log` passes on the boot (300-17 adds no boot-time message).
- Present: `ls /sys/module/rtl_otto_dsa/parameters/` shows `l3_default_v4 l3_default_v6 l3_onlink` (all `N`).

## Commands added for this

```
./dev.py nat-bench offload [--onlink 0|1] [--default-v4 0|1] [--default-v6 0|1]   # write the parameters, wait for the l3.c poll, dump tables
./dev.py nat-bench dflt-setup                               # switch default v4+v6 via natwan; natwan holds 198.51.100.5, 2001:db8:22::5
./dev.py nat-bench routes                                   # test rows of realtek_otto_l3/routes + nexthops + parameters
./dev.py nat-bench run ... --dst 198.51.100.5               # v4 to an address only the default route reaches
```

- `offload` waits up to 6.25 s (1.25 x the 5 s poll) for the dump to show the change; expiry logs `NOT seen after` and exits 1.
- `run` clears the route HIT bits first and dumps the test rows after.

## Test plan

Each measurement: TCP `-P 4`, 15 s, both directions (`--reverse`); record goodput, eth0 pps, per-VPE busy %. Same boot for before and after.

### 0. Setup

```
./dev.py nat-bench setup
./dev.py nat-bench mode route          # no NAT: natwan routes 10.99.1.0/24 back via the switch
./dev.py nat-bench v6-setup
./dev.py nat-bench offload --onlink 0 --default-v4 0 --default-v6 0
```

- Expect: `routes` shows `10.99.1.0/24` and `10.99.2.0/24` `trap` (on-link prefixes), no `/32` neighbour rows, catch-all `0.0.0.0/0` and `::/0` `trap` NH 0 last.

### 1. On-link IPv4

| Step | Command | Expect |
|---|---|---|
| before | `run --secs 15 -P 4` and `--reverse` | ~60-70 Mbit/s, eth0 rx+tx ~ 2x goodput, VPE ~100 % |
| enable | `offload --onlink 1` | host rows `10.99.1.2/32` and `10.99.2.2/32` `fwd` `chk,dec`, NH_ID >= 512; `nexthops`: those NH ids -> L2 port lan1, VID 991/992, the netns MACs `02:99:00:00:09:91/92` |
| after | same two runs | ~9.2 Gbit/s goodput (gateway-routed reference 9.19), eth0 pps ~0, VPE ~0 %, HIT 1 on both rows |

### 2. On-link IPv6

| Step | Command | Expect |
|---|---|---|
| before | `offload --onlink 0`, `v6-run --onlink --secs 15 -P 4` | ~58 Mbit/s, VPE ~100 % |
| after | `offload --onlink 1`, same run | host rows `fd99:1::2/128`, `fd99:2::2/128` WIDTH 3 `fwd`; ~9 Gbit/s, eth0 ~0 |

- No row for the netns link-local addresses (`fe80::...`): never offloaded.

### 3. Default route IPv4 and IPv6

```
./dev.py nat-bench dflt-setup
```

| Step | Command | Expect |
|---|---|---|
| before | `offload --default-v4 0 --default-v6 0`; `run --dst 198.51.100.5`; `v6-run --dst 2001:db8:22::5` | rows `0.0.0.0/0` / `::/0` `trap` with NH 0 **above** the catch-alls (two `/0` rows per family); CPU path rates |
| v6 only | `offload --default-v4 0 --default-v6 1`; same runs | `::/0` upper row `fwd` NH > 0; `0.0.0.0/0` upper row still `trap` NH 0; v4 CPU path rate, v6 ~9 Gbit/s |
| after | `offload --default-v4 1 --default-v6 1`; same runs | the upper `/0` row `fwd` NH > 0 in both families, catch-all still `trap` last; ~9 Gbit/s, eth0 ~0 |

### 4. Correctness (each with `routes` before/after)

| # | Action (switch console / ssh unless noted) | Expect |
|---|---|---|
| a | `ip neigh del 10.99.2.2 dev lan1.992` | `10.99.2.2/32` row gone at once; next ping re-resolves, row back `fwd` |
| b | host: `ip -n natwan link set enp7s0.992 address 02:99:00:00:09:93`, then ping from natwan | after the neighbour update: `nexthops` shows the new MAC for that NH; traffic flows |
| c | `ip route add 10.99.2.0/25 via 10.99.1.2 dev lan1.991` | `10.99.2.2/32` neighbour row torn down (address no longer on-link); `ip route del` of it -> row back |
| d | `ip addr add 10.99.2.2/32 dev lan1.992` (address taken by the box) | neighbour row gone, local `/32` `trap`; `ip addr del` -> row back after the next neighbour event |
| e | `ip rule add from 10.99.1.2 table 100` | log `IPv4 forwarding offload suspended`; every v4 row incl. neighbour and default -> `trap`; `ip rule del` -> back to `fwd` |
| f | `ip -6 route add ::/0 from fd99:11::/64 via fd99:2::2 dev lan1.992` | v6 default row `trap` (source-specific default); `del` -> back after the next replace or `offload --default-v6 0` then `1` |
| g | run 120 s HW-forwarded (`run --secs 120`); `ip neigh show dev lan1.992` every 10 s | `10.99.2.2` cycles `STALE -> DELAY -> REACHABLE` (refresh poll), never `FAILED`; no `no valid neighbour` in dmesg |
| h | optional (host `scapy`): from natlan, frames to the switch MAC with DIP 127.0.0.2, 0.0.0.1, ::1 while `l3_default_v4=1` and `l3_default_v6=1`; `tcpdump -n -i enp7s0.992` in natwan | nothing arrives at natwan (`BAD_DIP_ACT` drop); if it does, file it: martian trap rows are needed |
| i | `offload --onlink 0 --default-v4 0 --default-v6 0` | neighbour rows gone, default rows `trap`, rates back to the CPU path |

### 5. Close

```
./dev.py nat-bench teardown        # also clears both parameters and the test default routes
./dev.py check-log
```

- Results: comment on #59 (rates, eth0 pps, CPU, the `routes` excerpts) and the measured section of [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md) with date, commit and conditions.

## Recover

- `./dev.py nat-bench teardown`; parameters reset to 0 there.
- Wrong forwarding with a parameter on: `echo 0 > /sys/module/rtl_otto_dsa/parameters/l3_onlink` (and `l3_default_v4`, `l3_default_v6`); applied within one poll (5 s).
- SSH lost: `./dev.py power off` / `on` (RAM-loaded kernel, nothing persists).
