# CPU port (RTL9303 port 28): registers and measured rate

Facts only. Procedures and results over time: [NAT-PROGRESS.md](NAT-PROGRESS.md). Issue #148.

## What it is
- Port 28 = internal CPU port: DMA to RAM through `rtl838x_eth`, no SerDes, no PHY. 2 RX rings, 2 TX rings, ring chosen by RX reason (`QM_RSN2CPUQID`).
- `MAC_L2_CPU_PORT_CTRL` (`0xC70C`) `INTF_P28_SEL` / `CPU_PORT`: 0 = CPU is port 28 (internal NIC); 1 = port 27 (external CPU interface, 10G). Here port 27 is cage 8 and the strap pin S0 is not wired, so the external mode is not available.
- Datasheet has no CPU-port speed or DMA figures. No public source found (2026-11-06, NAT-PROGRESS.md).
- Ports on this board: cages 1-8 = switch ports 0, 8, 16, 20, 24, 25, 26, 27 (SerDes 2-9); 28 = CPU. Other port numbers unwired.

## Registers (offsets in the switch block; physical = `0x1b000000` + offset; `devmem` wants the physical address)
- 64-bit registers are two words; the word at the lower address holds bits 63:32.

| Register | Offset | Fields | sw2 value |
|---|---|---|---|
| `MAC_FORCE_MODE_CTRL(28)` | `0xCA8C` (`0xCA1C + 4*port`) | SPD_SEL 6:3 (2 = 1G, 4 = 10G, 5 = 2.5G, 6 = 5G), DUP 2, FORCE_LINK 1, MAC_FORCE 0, FC 9 | `0x217` |
| `MAC_L2_CPU_PORT_CTRL` | `0xC70C` | INTF_P28_SEL 1, CPU_PORT 0 | `0` |
| `MAC_L2_PORT_MAX_LEN_CTRL(28)` | `0x396C` | two 14-bit lengths: 1G+ [13:0], 10/100M [27:14] | `0x017E85FA` (1530 / 1530 + flags) |
| `MAC_L2_CPU_MAX_LEN_CTRL` | `0xA3A0` | max length | `0x5FA` (1530) |
| `EGBW_PORT_CTRL(28)` | `0x7820` (base `0x7660`, 16 B stride) | EN 52, RATE 51:32, BURST 15:0 | `0x000FFFFF` (EN off) |
| `IGBW_PORT_CTRL(28)` | `0x80D8` | BW_EN, rate | `0x000FFFFF` |
| `EGBW_CTRL` | `0x78E4` | INC_IFG 1, RATE_MODE_CPU 0 | `0` |
| `EGBW_CPU_PPS_LB_CTRL` | `0x78E8` | TKN 31:24, TICK 23:0 | `0x01000185` |
| `EGBW_CPU_Q_MAX_LB_CTRL[q]` | `0x7CB8 + 8*q` | EN 52, RATE 51:32 (word at `+0`), BURST 15:0 (word at `+4`) | q0/q1: RATE max, EN off, BURST `0x8000` |
| `SCHED_CPU_Q_CTRL[q]` | `0x7F44 + 4*q` | STRICT_EN 7, WEIGHT 6:0 | weight 1, not strict (equal) |
| `QM_CPUQID2QID_CTRL` | `0xA324` | 3 bits per CPU queue | identity |
| `QM_CPUQID2XGQID_CTRL` | `0xA334` | 4 bits per CPU queue | identity (`0x76543210`, `0xBA98`) |
| `FC_CPU_Q_EGR_DROP_CTRL` | `0xC468` | EN, 1 bit per queue | `0xFFFFFFFF` (all on) |
| `FC_CPU_Q_EGR_DROP_THR[q]` | `0x7DC0 + 4*q` | ON 27:16, OFF 11:0 (pages) | `0x004E0044` (ON 78, OFF 68 pages) on the 7.3 boot; `0x00340024` (52/36) on a flash boot; queue 1 = `0x040003F0` with 300-40 |
| `FC_CPU_Q_EGR_PAGE_CNT[q]` | `0x7E40 + 4*q` | PEAK 30:16, CUR 14:0 (clear on read) | |
| `FC_CPU_Q_EGR_PKT_CNT[q]` | `0x7EC0 + 4*q` | PEAK 28:16, CUR 12:0 (clear on read) | |
| `FC_CPU_Q_EGR_FORCE_DROP_CTRL` | `0xC4DC` | EN, 1 bit per queue | `0` |

- Dump: `scripts/cpuport_regs.py` (read-only), log `tmp/logs/cpuport_regs.log`. Same values on the flash OpenWrt (6.18) and the 7.3 image.
- No rate limiter is enabled on port 28 or on CPU queues 0/1.

## SPD_SEL writes (2026-11-06, `scripts/cpuport_speed_ab.py`)
- `0x227` (10G), `0x22F` (2.5G), `0x237` (5G) written alone: CPU-port traffic stops; restoring `0x217` over the console recovers it.
- No rate measured at any setting but 1G.

## Measured rate: 1.66 Gbit/s
- 1400 B UDP + NAT, one direction, picks clocks: 143.7 kpps x 1446 B x 8 = 1.66 Gbit/s (1446 = 1400 + 8 UDP + 20 IP + 14 Ethernet + 4 FCS). Each frame crosses the CPU port twice (RX + TX): 3.3 Gbit/s total.
- Size dependence: the same CPU (94-96 % busy) forwards 490.7 kpps at 64 B (2 us/packet) and 143 kpps at 1400 B (6.6-6.9 us/packet); a bare receive-and-drop (`rxdrop`, NAT.md) also tops out at 137 kpps at 1400 B. The extra ~4.6 us scales with frame size, so the ceiling is a byte-dependent path (NIC DMA, bus/DDR contention or the chip feeding the CPU queue), not forwarding work. Clock sweep below.

## CPU queue 1 drop threshold (300-40, 2026-11-06, picks clocks, iperf3 TCP P4 through NAT, fast path, `--napi irq1`)
- Queue 1 (fast-path ring) peaked at 82 pages / 17 packets under load against ON = 78: the chip drops there (egress-queue drops), not in our 128-entry ring.
- A/B, one variable (queue-1 ON/OFF pages), forward / reverse:

| ON/OFF | Goodput | Retransmits |
|---|---|---|
| 52/36 | 1117 / 1178 Mbit/s | 21.7k / 22.6k |
| 78/68 (boot) | 1257 / 1295 Mbit/s | 15.1k / 15.3k |
| 1024/1008 (300-40 default) | 1517 / 1519 Mbit/s | 1.9k / 2.0k |
| 4095/4080 | 1507 / 1504 Mbit/s | 1.3k / 1.3k |

- 4095 buffers up to 3634 pages in queue 1 for no goodput gain, so 1024 is the default; queue 0 (control plane) unchanged.

## Clock sweep at 1400 B (2026-11-06, UDP + NAT, fast path, `--napi irq1`, one variable at a time, others at picks)

| Changed | Value | kpps | vs 143 |
|---|---|---|---|
| none (CPU 1350, DDR 662, LX 306) | - | ~143 | - |
| LX bus | 245 MHz (-20 %) | 138.4 | -3 % |
| DDR | 500 MHz (-25 %) | 136.2 | -5 % |
| CPU | 1000 MHz (-26 %) | 132.3 | -7.5 % |

- Cutting any one clock by a quarter costs 3-8 %: the 1400 B ceiling is almost independent of CPU, DDR and LX clocks, so it sits in a fixed-rate path outside them (switch core to NIC / CPU-queue transfer). `rxdrop` (receive and drop) stops at the same 137 kpps.
- LX 204 MHz: the 7.3 RX path panics in `gro_list_prepare` (2/2, #149); 245 and 306 are stable.
- Valid `turbo` steps: LX 175 / 204 / 245 / 306; CPU 800 / 1000 / 1050 / 1100-1425 step 25; an invalid value rejects the whole profile ('nothing changed', board stays at stock clocks).
