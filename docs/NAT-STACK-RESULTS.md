# Normal NAT: minimal Linux was 2.3 times faster than our OpenWrt build

## What we found

Four simultaneous TCP connections, from LAN to WAN. Each number is the average of three 15-second runs, in megabits per second.

| Test | OpenWrt r38178 / Linux 6.18.60 (A) | OpenWrt r38178 / Linux 7.4-rc1 (B) | Minimal Linux 7.4-rc1 (C) |
|---|---:|---:|---:|
| Normal NAT forwarding | 113.2 | 164.6 | 373.8 |
| NAT with software flow acceleration | 325.8 | 523.7 | 606.1 |
| NAT with our experimental zero-copy path | unavailable | 1,674.4 | 1,674.1 |
| Routing without NAT, directly connected networks, CPU | not measured | 184.5 | not measured |
| Routing without NAT, directly connected networks, switch chip | unavailable | 5,210.7 | not measured |

For this test, minimal Linux was about **2.3 times faster** than our OpenWrt build with normal NAT, and **16% faster** with software flow acceleration. B and C passed the comparison checks, but still differ in their operating-system services and kernel compiler; the test does not establish why C was faster.

Our experimental zero-copy NAT path reached about **1.67 Gbit/s** on both B and C. Routing directly connected networks on the switch chip reached **5.21 Gbit/s** on B; that is a separate test without NAT. A's CPU-routing TCP test was not run, and C was left out by owner decision. The switch-chip option for directly connected networks is not available in A.

OpenWrt r38178 already supports hardware routing for eligible routes **via a gateway**. This project's changes add optional hardware routing for directly connected networks and default routes. Hardware-routed traffic bypasses the CPU firewall and NAT; see [ROUTING-OFFLOAD.md](ROUTING-OFFLOAD.md).

**A is not a fair head-to-head comparison with B/C:** it ran a different Linux version and handled network interrupts on a different CPU core, among other differences. The numbers do not prove how much of the gap comes from our changes.

- **A:** OpenWrt r38178, including its Linux patches but none of this project's changes (Linux 6.18.60).
- **B:** OpenWrt r38178 with this project's switch-driver fixes and performance changes (Linux 7.4-rc1).
- **C:** a minimal Linux test image with this project's switch-driver changes, but without the full OpenWrt system (Linux 7.4-rc1).

## Detailed measurements (TrueNAS, 2026-11-09)

Plan and comparison checks: [NAT-STACK-TESTS.md](NAT-STACK-TESTS.md).

- 174/174 rows passed: A 45, B 69, C 60. B/C's original 129 rows were preserved. B/C gate: **CONTROLLED (all remaining differences listed)**, report `tmp/controlled/truenas-static/stack_compare_result-20261109-112542.txt`.
- A handled network interrupts on CPU0; B/C used CPU1. The owner chose to preserve the B/C results rather than rerun them. The A/B/C gate is **NOT CONTROLLED** (five unlisted snapshot fields), report `tmp/controlled/truenas-static/stack_compare_result-20261109-125315.txt`.
- The other unlisted fields are `tls-hw-record: off [fixed]` present only on A, on both `eth0` and `lan1`; and six sysctls absent on A but present on B/C: `net.core.bypass_prot_mem=0`, `neigh_inherit_init_net=1`, `qdisc_max_burst=1000`, `txq_reselection_ms=1000`, `net.ipv4.tcp_comp_sack_rtt_percent=33`, `tcp_rcvbuf_low_rtt=1000`. Do not attribute A/B/C gaps solely to the kernel or patch set.
- All three report GRO and `rx-gro-list` on and GSO effectively `off [requested on]`. A's conntrack buckets, `skb_defer_max`, and `tcp_comp_sack_slack_ns` were aligned to B/C. Pinned iperf3/ip/tc/fw4 hashes match; B/C's legacy `sha_pinned` data was recovered from the `v_musl` snapshot field.
- Common clock `e220=0x30626` was read back for each stack. A lacks the CP0 timer fix: switch-side CPU percentages are not comparable; throughput is timed by the TrueNAS endpoints.
- A's flowtable TCP rows passed but recorded 1,092–5,467 retransmissions per 15-second run. A lacks this project's zero-copy NAT and directly connected hardware-routing extensions; the routed TCP rows here are B-only. A drift was limited to the expected nft ruleset changes; B/C also had expected runtime process/rteth changes.
- A initially lost management after CPU1 normalization; the missing `300-18` IRQ fix is a likely, unproven cause. CPU0 normalization retained management and read back the requested affinity. A's 200000-baud handoff garbled some early serial bytes: the captured console and recovered kernel ring passed `check-log`, but the ring cannot prove messages that never reached it.
- The A post-run kernel ring contains 38 reviewed informational `clear_route_hits` messages from the benchmark reset. Its earlier smoke teardown logged `rmmod: module is not loaded` (#161); teardown now checks before unloading.
- TCP: Mbit/s; UDP: kpps; mean (min–max), n=3, with 15 s per TCP row and 10 s per UDP row.

Table labels: `nat` is normal address translation; `nat-ft` adds software flow acceleration. `P1`, `P2` and `P4` are the number of simultaneous TCP connections; `fwd` and `rev` are the two directions. `stack-udp` is routed UDP through the normal network stack; the number is payload bytes. `l3on`/`l3off` compare this project's directly connected hardware routing on/off, and `zcnat` uses this project's zero-copy forwarding path. `kpps` means thousands of packets per second; `-` means not measured or unavailable.

| Cell | A | B | C | Note |
|---|---:|---:|---:|---|
| nat-P1-fwd | 154.1 (146.5-160.6) | 215.0 (212.1-217.1) | 345.6 (344.1-347.1) | |
| nat-P1-rev | 169.6 (165.2-177.9) | 219.9 (213.7-229.3) | 506.0 (496.7-512.9) | |
| nat-P2-fwd | 123.0 (116.9-128.3) | 189.8 (179.0-197.3) | 366.4 (365.8-367.1) | |
| nat-P2-rev | 125.9 (121.3-134.0) | 208.8 (204.7-215.2) | 472.9 (465.2-484.6) | |
| nat-P4-fwd | 113.2 (111.4-115.9) | 164.6 (156.7-169.4) | 373.8 (372.0-374.9) | |
| nat-P4-rev | 119.5 (118.0-120.3) | 189.9 (187.0-195.3) | 431.2 (428.2-433.0) | |
| nat-ft-P1-fwd | 339.9 (338.0-341.3) | 513.7 (507.2-519.1) | 562.8 (560.0-565.1) | |
| nat-ft-P1-rev | 349.5 (348.6-350.4) | 711.5 (703.8-722.7) | 807.2 (802.6-812.1) | |
| nat-ft-P2-fwd | 347.9 (344.8-349.5) | 520.7 (518.6-523.4) | 592.5 (589.7-594.7) | |
| nat-ft-P2-rev | 355.3 (355.2-355.4) | 689.6 (682.0-697.1) | 795.6 (787.1-801.2) | |
| nat-ft-P4-fwd | 325.8 (323.7-327.4) | 523.7 (520.9-526.1) | 606.1 (604.9-607.5) | |
| nat-ft-P4-rev | 333.2 (329.6-336.1) | 664.5 (655.4-672.9) | 777.8 (771.4-783.7) | |
| stack-udp1400 | 16.2 (15.9-16.4) | 19.9 (17.8-21.7) | 46.0 (45.2-47.5) | |
| stack-udp500 | 38.5 (38.2-38.7) | 51.4 (51.3-51.5) | 79.6 (79.2-79.9) | |
| stack-udp64 | 44.4 (44.3-44.6) | 60.8 (60.7-61.0) | 90.0 (88.8-90.6) | |
| l3on-udp1400 | - | 369.3 (296.5-406.4) | - | |
| l3on-tcp-P4-fwd | - | 5210.7 (5193.7-5223.1) | - | |
| l3off-tcp-P4-fwd | - | 184.5 (182.2-186.6) | - | |
| zcnat-udp1400 | - | 157.0 (156.9-157.2) | 157.9 (157.6-158.0) | |
| zcnat-udp500 | - | 329.6 (329.5-329.8) | 325.9 (308.6-334.6) | |
| zcnat-udp64 | - | 433.8 (386.3-458.4) | 425.1 (416.5-430.8) | |
| zcnat-P4-fwd | - | 1674.4 (1673.7-1675.1) | 1674.1 (1672.0-1675.3) | |
| zcnat-P4-rev | - | 1669.9 (1663.8-1673.7) | 1673.4 (1671.4-1676.4) | |

## History

- Shared-host run (VOID) and local-generator run: [history/NAT-STACK-RESULTS-shared-host-2026-11.md](history/NAT-STACK-RESULTS-shared-host-2026-11.md).
