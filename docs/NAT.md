# NAT on the TL-ST1008F (RTL9303): live state

- Target: IPv4 NAT at 2.5 Gbit/s (owner ISP: NBN HFC ~2 Gbit/s down), #65 (closed). Owner decision: go with what works ([DECISIONS.md](DECISIONS.md)).
- Conclusions, limits, what does not help: [FINDINGS.md](FINDINGS.md). Controlled comparison (the only comparable data): [NAT-STACK-RESULTS.md](NAT-STACK-RESULTS.md), plan [NAT-STACK-TESTS.md](NAT-STACK-TESTS.md).
- Dated experiments, old stack progression, option tests, image runs: [history/](history/README.md) (not comparable).
- Graphs: `code-insiders --reuse-window docs/NAT-REPORT.html`; regenerate `python3 scripts/nat_report.py`.
- Run the measurements: [NAT-OPS.md](NAT-OPS.md). CPU-port registers: [CPU-PORT.md](CPU-PORT.md). No NAT hardware in the die: [HIDDEN-FEATURES.md](HIDDEN-FEATURES.md) (#68).

## Verdict
- IPv4 and IPv6 routing is done by the ASIC at ~0 % CPU with `300-17` (#59).
- IPv4 NAT on the in-place fast path (`300-39`, `zc=1`) reaches ~1.67 Gbit/s TCP; the skb stack (nftables flowtable, `nat-ft`) is about a third of that. Numbers: controlled table in [NAT-STACK-RESULTS.md](NAT-STACK-RESULTS.md).
- The ASIC rewrites MACs and TTL only, no IP or L4 port (#58, #68). Every NAT packet crosses the CPU port twice.
- 2.5 Gbit/s is not reachable by clocks or driver options ([FINDINGS.md](FINDINGS.md)).


## Final settings (owner 2026-11-07, CPU refined 2026-11-07 by #160)
| Domain | Setting | Notes |
|---|---|---|
| Switch core | 608 MHz (SW VCO 3650, code 1; e214 `0x478`, e220 `0x36826`) | code 0 (/4 divider) wedges CPU-port DMA; code 1 passes up to 783 MHz live, see CLOCKS.md |
| CPU | **1325 MHz** on the OpenWrt image (5/5 stable); 1350 on the plain kernel | 1350 fails on the image at core 575 / 608 (xz decode errors, Oops, #160); 1375 fails at core 608 |
| DDR | 662 MHz | 675 / 700 pass only with `ddr-retrain --write`, no gain beyond noise |
| LX | ~304 MHz | follows the SW VCO |
| SRAM | 500 MHz | no effect on the NAT rate |

- Per domain: stock | final | why the gap: [FASTEST-SETTINGS.md](FASTEST-SETTINGS.md#final-settings).
- Not default on the flash chain: stock clocks unless the M3 turbo profile is set (#109, #152).
- Flash chain profile stays `cpu=1350,ddr=662,sram=500` without `swcore`: the flash OpenWrt console garbles at LX 304 (UART `base_baud` assumes LX 175, #159). `300-23` (clocks from PLL) is in the 6.18 flash build list, untested.
- Temperature is logged only; there is no 85 C abort (owner 2026-11-07). Idle readings 46-63 C.

## Data path
- ASIC: L2 switching, L3 routing (MAC rewrite, TTL, checksum; v4 and v6). `0/0` and `::/0` defaults and on-link neighbours trap to the CPU; `300-17` (`l3_default_v4/v6`, `l3_onlink`, opt-in) adds them ([ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md), #59).
- CPU port: port 28, internal DMA NIC (`rtl838x_eth`), 2 RX + 2 TX rings, RX ring chosen by trap reason (`/sys/kernel/debug/rteth/rxq`, `300-38`). Forwarded traffic is one reason, so ring 1 is idle.
- Fast path (`300-39`, `zc=1`): the frame is rewritten in its RX buffer (MACs, VLAN id, TTL, NAT address and port, incremental IP/TCP/UDP checksums) and sent from the same buffer; no skb, GRO, netfilter or qdisc.
  - Flows come from the nftables flowtable (`flags offload`) through DSA `TC_SETUP_FT`: two entries per connection; stats go back so timeouts refresh. Conntrack, new flows, SYN/FIN, ICMP errors, fragments and expiry stay in the stack.
  - Prototype limits: IPv4 only, DDR buffers, <= 2048 flows, UDP and TCP, no soak. Productising: #158.
- Stack path (zc off): NAPI on VPE0 -> fraglist GRO (on at boot) -> conntrack + nf_nat -> nftables software flowtable (fw4 `flow_offloading=1`) -> DSA xmit -> `300-27` queue select -> TX ring 128, doorbell per <= 16 frames, reclaim in xmit (`300-12`).
- Driver patches in the path: `300-11`, `300-12`, `300-13`, `300-27`, `300-28`, `300-40`, `300-39`. Parked: `300-14`, `300-42` (cache variants), `300-43` (ring split), `300-44` (prefetch).
- One NAT interface only (WAN side + LAN side); no multi-WAN design or tests.

## What the remaining limit is
- The fast path is CPU-bound: the NIC IRQ + softirq VPE (VPE1) is 97-99 % busy at every size, ~170-180 kpps at 1400 B.
- Cost per packet: ~2 us fixed + a part that follows the switch-core clock (1400 B rate scales with it up to ~500, then the CPU binds; code-0 divider wedges, not the frequency). Not cache maintenance.
- 2.5 Gbit/s of 1500 B frames is ~312 kpps through the CPU port (data + ACKs); the fast path does ~170-180 kpps. Clocks cannot close it: CPU above 1350 fails at 608, DDR 675+ gives no gain, LX / SRAM do not move the rate.
- `rxdrop` (receive and drop) stops at about the same rate at 1400 B: the limit is receive-side, not the NAT rewrite.

## What works
- Stack path: TCP, UDP, ICMP and fragments follow normal Linux forwarding; TCP and UDP benchmarked.
- Fast path: IPv4 TCP and UDP NAT with kernel-fed flows, both directions. IPv6 is not in the fast path.
- Routing offload (`300-17`, 7.4 base, #59): checks a-g and i pass (neighbour delete / MAC change, covering prefix, local `/32`, `ip rule`, source-specific `::/0`, 120 s run, all params 0); v4 `rt_offload` clears when `l3_default_v4` goes 1 -> 0. Check h fails: DIP `0.0.0.1` is forwarded (needs a trap row for `0.0.0.0/8`).
- ASIC-routed traffic bypasses nftables (#66): `300-37` offloads tc flower `tcp_flags`, a stateless SYN drop on lan1 ingress works.
- Big-endian flowtable issue: `nf_flow_table_offload.c` builds the 16-bit Ethernet address pieces from host-order constants, byte-correct on little-endian only. The driver decodes the four Ethernet entries by numeric value for both byte orders. Candidate upstream report (#85).

## Runtime tunables
| Tunable | Default | Effect |
|---|---|---|
| `rx-gro-list` on eth0 + lan1 | on (image sets it at boot) | off: -29 to -41 % on the stack path |
| fw4 `flow_offloading` | 1 | off: -74 % |
| eth0 `rps_cpus` | 0 (image: uci `network.globals.packet_steering=0`, `91_st1008f_steering`) | netifd default 1 cost 12-16 % on `nat-ft` (#161) |
| eth0 IRQ affinity | default (both CPUs; no pin) | no effect: zc 1673-1679 Mbit/s and stack 530-590 Mbit/s with the IRQ on CPU0 or CPU1 (matrix below, 2026-11-23); the pin default was removed |
| eth0 qdisc | `mq` / `pfifo_fast` (image `fq_codel`) | `noqueue`: +12-15 % on the stack at stock clocks, ties on zc |
| `tx_by_cpu` (rteth) | 0 | stack path with pinned NAPI only (#145) |
| `cpuq_drop_pages` (rteth, read at open) | 1024 | queue-1 ON pages, OFF = ON - 16; 0 keeps the chip value (78) |
| `zc`, `zc_*` (rteth, runtime) | 0 | in-place fast path and its match / rewrite fields; do not change `zc_ring` under load |
| `sram_rings` (rteth) | 0 | any non-zero value gives no traffic |
| `rx-udp-gro-forwarding` | off | on: worse |
| storm control unknown-unicast | off (#111) | on at 20000 pps capped NAT at ~19 kpps |
| clocks | stock on the flash chain | final settings via `ramload ... --pre "turbo cpu=1325,ddr=662,lx=304,sram=500"` after the core is set, or the M3 profile (#109) |

- `turbo` steps: LX 175 / 204 / 245 / 306; CPU 800 / 1000 / 1050 / 1100-1425 in steps of 25; an invalid value rejects the whole profile.

## Hazards
- #149: the 7.3 OpenWrt RX path panicked in `gro_list_prepare` (NULL deref) at LX 204 / 245 and with `perf record -a` (2/5 boots at CPU 1350); not seen on plain 7.4 (0/9). Use LX 245 or higher; no `perf -a` on sw2 at the final settings.
- #160: CPU 1350 at core 575 / 608 on the OpenWrt image corrupts computation (xz decode errors, Oops at 32-53 s). Use CPU 1325 there.
- #163: the OpenWrt boot selftest resets the SoC when `st1008f-stx` is missing; `build_openwrt` now fails without the helper.
- LX 204 and LX 304 under Linux print garbage on the flash console (UART rate mismatch, #159).
- Writing `MAC_FORCE_MODE_CTRL(28)` speed bits drops the CPU port; restore `0x217` over the console.
- `300-12` doorbell writes 0 into the other ring's `TX_FETCH`; whether that cancels a pending fetch is undocumented (risk on SMP).
- Fast path: prototype, no soak; ASIC egress-queue drops show as TCP retransmits at saturation.
- Receive floods can go dead after 1-3 runs (#156). Tooling flakes at the final profile (#162). Cage loops and fast SPI: see CLAUDE.md hazards.

## Open issues
- Open NAT / clock issues with one line each: [FINDINGS.md](FINDINGS.md#open-items-nat--clock-related-gh-issue-list---state-open-2026-11-27).

## Sources
- Ceiling and cost model: [CPU-PORT.md](CPU-PORT.md). Datasheet audit: [DATASHEET-AUDIT.md](DATASHEET-AUDIT.md). Routing offload: [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md). Mainline throughput: [MAINLINE-PORT.md](MAINLINE-PORT.md). Canary baseline: [CANARY.md](CANARY.md).
- Controlled rows: `tmp/controlled/`. Old campaign rows: `tmp/history-logs/` (see [history/README.md](history/README.md)).
