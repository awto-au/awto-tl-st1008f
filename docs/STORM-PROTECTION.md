# Storm and loop protection (#111)

- The switch caps flood traffic in hardware and shuts a looped port, on by default, in U-Boot and Linux.
- Storm control = RTL9303 ingress meters. Loop detection = our probe frames + the RLDP trap + a MAC shut; the chip has no hardware loop detection.
- Bridge STP stays on (#43); loop detection is the second line behind it.
- Status 2026-10-13: built (U-Boot, kernel next-20261009). Not yet run on hardware; test plan: [STORM-PROTECTION-OPS.md](STORM-PROTECTION-OPS.md).
- Steps: [STORM-PROTECTION-OPS.md](STORM-PROTECTION-OPS.md).

## Code

- `shared/rtl930x-storm/rtl930x_storm.h` — registers, defaults, meter set/get, EXCEED flags. Shared core: the builds copy it into U-Boot and the kernel; edit only here.
- U-Boot: `uboot-port/board/tplink/tl-st1008f/rtk_storm.c` — defaults at `rtk network on` (and after a stock `network on`); `rtk storm`, `rtk loopdetect`.
- Linux: `openwrt/patches/300-26-realtek-rtl930x-storm-control-loop-detect.patch` — `drivers/net/dsa/rtl83xx/storm.c`, armed at switch probe (RTL930x only).
- Mainline kernel path only (`mainline_build_check.py`, `build_openwrt.py --kernel mainline`). The OpenWrt 6.18 build (`--kernel 6.18`) does not carry 300-26.

## Hardware (SDK sources)

- Sources: Realtek SDK `swcore_rtl9300.h`, `dal_longan_rate.c`, `dal_longan_trap.c` (GPL-2.0; [SDK-SOURCES.md](SDK-SOURCES.md)).
- Three ingress meters per port, ports 0-28 (28 = CPU): broadcast, multicast, unicast. Over the rate = dropped; no other action exists.
- Per-port mode `STORM_PORT_CTRL` 0x8A6C bit per port: 0 = pps, 1 = 16 kbps units. Shared by the three meters.
- Meter = 64 bit at base + 8 × port; word +0 = TYPE[25] EN[24] RATE[23:0], word +4 = BURST[15:0]. Word order from the stock loader's `reg_field_set_in_buf`.

| Meter | Base | LB_RST | EXCEED |
|---|---|---|---|
| unicast | 0x8A70 | 0x8B58 | 0x8B5C |
| multicast | 0x8B60 | 0x8C48 | 0x8C4C |
| broadcast | 0x8C50 | 0x8D38 | 0x8D3C |

- TYPE (UC/MC only): 0 = unknown only (DLF / unknown MC), 1 = known + unknown.
- RATE in pps mode: SDK writes rate × 1000 / 1014 (rounded, "LONGAN SS-528"); max 0xFFFFFF. BURST in packets (pps mode), max 0xFFFF.
- LB_RST: bit per port, bucket reset; the SDK writes it after every meter change. EXCEED: bit per port, 1 = rate exceeded, write 1 to clear.
- `STORM_CTRL` 0x8A60: `ADMIT_*` = frame type bypasses the meters: RIP 6, DHCP 5, ARPREQ 4, RMA 3, BPDU 2, RTKPKT 1, IGMP 0; INC_IFG 9 (bps mode).
- Per-protocol meters (DHCP 0x98A4, BPDU 0x9920, IGMP 0x999C, ARP 0x9A18; + 4 × port; EN 20, RATE 16:8 pps, BURST 7:0): not used.
- Drop counter: drop reason 60 `STORM_CONTROL` (0xB6A8), global, 16 bit, clear on read ([drop_counters.py](../scripts/drop_counters.py)). No storm interrupt.
- Reset state (2026-10-12 register snapshot, our U-Boot, no `network on`): every meter EN 0, RATE 0xFFFFF, BURST 0xFF; `STORM_CTRL` 0; mode 0 (pps); `RLDP_RLPP_CTRL` 0. Stock firmware never enables them.
- Loop: `RLDP_RLPP_CTRL` 0xA250 `RLDP_RLPP_TRAP[1:0]`: 0 forward, 1 trap to CPU, 2 master CPU. Matches ethertype 0x8899 frames classified RLDP/RLPP. CPU queue: `QM_RSN2CPUQID_CTRL_7` 0xA360 [9:5].
- No RLDP protocol in the SDK drops (no `rtk_rldp_*`). Vendor ST5008F `loopbackDetection` uses an ACL trap, not this register.
- Port shut: `MAC_L2_PORT_CTRL` 0x3268 + 64 × port, TX_EN 1, RX_EN 0. OpenWrt phylink `link_up` sets both again (handled, below).

## Limits

| Meter | Default | Mode | Burst |
|---|---|---|---|
| broadcast | 10000 pps | — | 1000 |
| multicast | 20000 pps | all (TYPE 1) | 2000 |
| unknown unicast | 20000 pps | unknown only (TYPE 0) | 2000 |

- Applied to the 8 cage ports, pps mode. Burst = 100 ms of the rate.
- CPU port (CPU-originated floods): broadcast + multicast only. No unknown-unicast meter: tagged CPU TX may count as unknown unicast and would cap the NAT/routing path (#65) at 20000 pps.
- Line rate, 64 B frames: 14.88 Mpps at 10G, 1.488 Mpps at 1G. The broadcast cap is 0.07 % of 10G, 0.7 % of 1G.
- Normal LAN broadcast (ARP, DHCP, NetBIOS) is tens to hundreds of pps: the cap leaves ≥ 50× headroom; bursts ride the bucket.
- Multicast 20000 pps ≈ 240 Mbit/s of 1500 B frames: room for mDNS/SSDP and several IPTV streams. All multicast, not only unknown: without IGMP snooping offload every group floods anyway.
- Unicast meter counts only unknown destinations (flooded); learned unicast is never metered.
- Bypass on (`ADMIT_BPDU`, `ADMIT_RMA`, `ADMIT_RTKPKT`): STP, LACP/LLDP and our loop probes still pass during a storm.
- Worst case into the CPU: 8 ports × 10000 broadcast pps.
- Override: U-Boot env `rtk_storm` (`off` or `<bc>,<mc>,<uc>`), `rtk storm <bc> <mc> <uc>`; Linux `rtl_otto_dsa.storm_bc|storm_mc|storm_uc=` on the command line, or debugfs at run time. 0 = that meter off.

## Loop detection (Linux, 300-26)

- RLDP trap set to CPU at probe.
- Every 1 s: a probe out of each user port that is a forwarding bridge member with carrier.
  - 60 B: DA ff:ff:ff:ff:ff:ff, SA 02:93:03:4c:44:<port> (no real host: learning it is harmless), ethertype 0x8899, proto 0x03 (RLDP), "STLD", tx port, per-boot random nonce, sequence.
- RX: an `ETH_P_ALL` packet tap on each user netdev (runs before the bridge rx_handler; `ignore_outgoing`, no TX clones). Frees its reference before the bridge, so no extra clone per CPU-path frame.
- A probe with our nonce, sent on port A, received on port B:
  - Loop when A and B are both forwarding members of the same bridge (A = B counts: a loop outside the switch).
  - Otherwise counted `ignored` (STP blocks one side, or different bridges: the ASIC cannot loop it).
  - Probes from another switch (other nonce) are ignored.
- Action: MAC TX/RX of the higher port number off; `dev_warn` `loop: probe sent on lanA came back on lanB: lanB shut down for 60 s (#111)`.
- Recovery: after `loop_recover_s` (60 s) TX/RX back on (if carrier) and probing resumes; a loop still cabled is shut again within 1 s.
- While shut, the period re-clears TX/RX each second (phylink `link_up` sets them on a link flap).
- Netdev carrier stays up while shut; the state shows in debugfs.
- Detection time ≤ 1 s + one frame round trip. The meters cap the storm meanwhile.
- The probe reaches the CPU either way: trapped (RLDP rule) or, if the chip does not classify proto 0x03 as RLDP, flooded as a broadcast. The trap only stops it circulating. Which one happens is still unverified (test plan).

## Storm reporting (Linux, 300-26)

- EXCEED flags read + cleared every 1 s: `dev_warn` `storm: lanN broadcast over the limit, excess dropped (#111)` on the first period, `dev_info` `... back under the limit` at the end.
- Per port and meter: seconds with the flag set (`storm_s`).
- debugfs `/sys/kernel/debug/rtl838x/storm` (0600):
  - Read: mode, bypass bits, trap; per port each meter `pps/burst`, `storm_s`, `NOW`; loop state, probes, ignored; per port loops, last partner, `SHUT n s left`.
  - Write: `<bc> <mc> <uc>` (pps, 0 = off), `loop on`, `loop off` (also re-opens shut ports), `unshut`.
- Module params (read-only at run time): `storm_bc`, `storm_mc`, `storm_uc`, `loop_detect`, `loop_recover_s`.
- Reported by: `st1008f-selftest` item `storm` ([SELFTEST.md](SELFTEST.md)), `./dev.py switch-check` (`storm=` lines), `./dev.py drop-counters snap|diff` (debugfs after the counters).

## U-Boot

- `rtk network on` and `rtk_guard_after_stock()` (after a stock `network on`) program the meters on the 8 cages + CPU and the RLDP trap.
- No loop detection task: U-Boot has no background loop. The isolation guard (every cage forwards to the CPU only, #19) means no cage loop can form while our U-Boot owns the switch.
- `rtk storm [show | clear | on | off | <bc> <mc> <uc>]`: per port meters, EXCEEDED flags (`clear` clears them), bypass bits, drop counter (read clears it).
- `rtk loopdetect`: trap state; per cage the cages it can forward to (isolation table read), MAC TX/RX; `LOOP POSSIBLE` after `rtk port-isolation off`.
- Boot log line `rtk: storm control bc/mc/uc 10000/20000/20000 pps per port, loop-probe trap on (env rtk_storm=default)` (allowlisted).
- Size: +4.3 KiB (488241 B image, 2026-10-13).

## Open

- RLDP classification of our proto 0x03 probe (trapped vs flooded): test plan step L2.
- Whether TX tagged frames from the CPU count against the CPU port's ingress meters: test plan step L1.
- Tool guards (#70 SPG refusals, storm_watch relay kill) become warnings/logging only after the sw2 test (#111 step 4).

## Measured on sw2 (2026-10-13T18:20-18:26+11:00)

Conditions: our U-Boot RAM-loaded (U1), mainline kernel next-20261009 + 300-26 RAM-loaded (L1-L5); `./dev.py storm-test`; test bridge `br-t` = lan7 + lan8 (fibre loop 7 <-> 8), mgmt cage never in it; host storm guard armed, no trip.

| Step | Result |
|---|---|
| U1 U-Boot defaults | pass: every cage bc/mc/uc 10000/20000/20000 pps, CPU uc off, bypass bpdu/rma/rtkpkt 1, probe trap to CPU, cages forward to CPU only |
| L1 Linux defaults | pass: same meters, `loop: on, period 1000 ms, recover 60 s` |
| L2 STP on | pass: lan8 blocking (state 4), probes sent, no shut |
| L3 STP off | pass: `probe sent on lan7 came back on lan8: lan8 shut down for 60 s` within 2 s |
| L4 recovery | pass: `lan8 back up after 60 s`, shut again within 1 s |
| L5 meters alone (`loop off`) | pass: the loop circulates multicast; meters cap it (`storm_s` 3-4, `storm: lanN multicast over the limit, excess dropped`), loadavg 0.36; `loop on` then shuts lan8 within 1 s |

- `loops` counts every returned probe while the loop runs (hundreds per event), not events.
- DAC pair 3 <-> 4 does not link under the mainline kernel (lan3 never up, lan4 flaps): the #112 DAC media fix is in the OpenWrt tree only. Fibre pair used instead.
- Not run: L6 (OpenWrt management bridge with STP off): 300-26 is not in the OpenWrt 6.18 image yet.
