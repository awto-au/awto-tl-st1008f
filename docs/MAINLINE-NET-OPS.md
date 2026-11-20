# Mainline 7.3 network bring-up: operations

Facts (what is built, safety defaults, patch status): [MAINLINE-PORT.md](MAINLINE-PORT.md) sections 7-8. Issue #16.

## Preconditions

- `./dev.py build-kernel` OK (writes `tmp/tftp/mainline.bin`); fibre in cage 1 to the house switch.
- Host watching for loops: `./dev.py storm-watch --duration 3600` in a second terminal for the whole session.
- Console log open (`logs/serial/st1008-console.log`).

## Boot

```
./dev.py ramload mainline-kernel --cage 1                          # stock clocks: CPU 800 MHz
./dev.py ramload uboot-mainline --then mainline-kernel --cage 1    # via ours after `clocks fast`: CPU 1 GHz (NAT numbers)
```

- Stock U-Boot `rtk network on` lights cage 1 only; Linux then isolates every port at DSA setup.
- `check-log` is clean on both paths (2026-10-12); a new driver line shows up as UNKNOWN.

## At `st1008f-linux # `

| Check | Command | Expected |
|---|---|---|
| Drivers probed | `dmesg \| grep -iE 'rtl83xx\|rteth\|rtl838x\|pcs\|otto\|sfp\|dsa'` | eth0 MAC line; DSA switch registered; no `-EPROBE_DEFER` loop, no `Call Trace` |
| Ports exist, all down | `ip -br link` | `eth0`, `lan1`..`lan8`, all `DOWN` |
| No bridge | `ls /sys/class/net/*/bridge 2>/dev/null` | empty |
| Lasers off | `cat /sys/kernel/debug/sfp-p*/state` (debugfs is mounted) | `tx_disable: 1` for every cage with a module |
| MAC | `dmesg \| grep 'Using MAC'` | `16:b0:46:e9:0d:c0` (U-Boot env `ethaddr` via nvmem) |
| Thermal | `cat /sys/class/thermal/thermal_zone0/temp` | m°C, plausible |

## One cage up, ping the house LAN

```
port-up 1 192.168.25.48/24          # cage 1 only; .48 = st1008f-1-mgmt (ip-registry)
ip route add default via 192.168.25.254
ping -c 5 192.168.25.254
ethtool lan1                         # link speed / port
cat /sys/kernel/debug/sfp-p1/state   # tx_disable: 0 now
```

- `port-up` refuses while another `lanN` is up or a bridge exists. It sets `rx-gro-list on` and starts dropbear: `ssh root@192.168.25.48` (blank password).
- Host side: `ping 192.168.25.48`, `iperf3 -c 192.168.25.48` after `iperf3 -s -D` on the switch.
- NAT bench: `./dev.py nat-bench setup|mode|run|local|pktgen|rxdrop` detect the mainline shell (no `switch` bridge): SVIs are `lan1.991`/`lan1.992`, no fw4, `ip_forward` set by `setup`.
- NIC path timing: `./dev.py rteth-ftrace --depth 1|2|3` (after `nat-bench setup` + `mode nat-ft`).
- Driver before/after: `./dev.py nic-bench boot` (ramload at 1 GHz + `port-up 1` + `nat-bench setup` + `mode nat-ft`), `./dev.py nic-bench run --tag T` (3 runs: TCP P4, UDP 1400 B at 600/700/900, UDP 64 B), `./dev.py nic-bench table T1 T2`.
- Tagged test instead of the house VLAN: `port-up 1 10.99.1.1/24 991`, host netns `natlan` on `enp7s0.991` = 10.99.1.2 (same VLAN as [NAT-OPS.md](NAT-OPS.md)); `ping 10.99.1.2`.
- 10G optics: if no link at 10G, record `ethtool lan1` + `dmesg` tail; PCS calibration is the known risk (#16 stage 5).

## Loop check

- `bridge link` -> empty; `ip -d link show lan1` -> no `master`.
- `storm-watch` silent; SG2008P log has no `OSW_DET_LOOP`.
- sw2 loopbacks (3 ↔ 4 DAC, 7 ↔ 8 fibre, docs/hardware.md): mainline initramfs never bridges; never `port-up` both ends of a pair.

## sw1 <-> sw2 routed copper test link (2026-11-20)

- sw1-lan2 (FS SFP-10G-T, AQR113C) <-> sw2-lan2 (GLC-T, 88E1111) is a second link between the two switches next to the 10G DAC (sw2-lan1 <-> sw1-lan4). Bridged it would be a loop (STP is per bridge, so a separate VLAN does not avoid the STP block either).
- Both ends run `lan2` as a standalone routed port, not in the `switch` bridge: uci `network.testlink` (device `lan2`, static), sw1 `10.99.0.1/30`, sw2 `10.99.0.2/30`, in firewall zone `lan`; `lan2` removed from `network.lan_vlan.ports`. Persistent (uci commit), carried by the sysupgrade config backup.
- Use: `ping 10.99.0.2` from sw1 / `10.99.0.1` from sw2, iperf3 over it; the link is invisible to the house LAN and to M1/M2 bridging. Undo: `uci del network.testlink`, add `lan2` back to `lan_vlan.ports`, remove `testlink` from the firewall zone, `network reload`.
- Checked 2026-11-20T22:32+11:00: both ends 1000 full, 0% loss, 0.7-1.6 ms.

## OpenWrt with the sw2 loopbacks fitted (#110)

- Boot as usual: `./dev.py ramload uboot-mainline --then openwrt-ours`. Our U-Boot `rtk linkcheck` reports LOOP; ramload accepts it for `openwrt-ours*` (refuses it for other images).
- `st1008f-linkcheck` (START=19, before netifd) finds the loops itself and takes both ends out of every uci `ports` list, logged with the reason; STP on as the second layer:
  - same vendor + serial on two ports (DAC 3 ↔ 4);
  - laser probe: each dark DDM fibre port up alone (standalone, CPU only), light on another port (7 ↔ 8).
- Verified 2026-10-13T15:11 on sw2: console `linkcheck loop lan3<->lan4: same cable`, `lan7->lan8` / `lan8->lan7: passive`, `linkcheck bridge lan_vlan: removed lan3 lan4 lan7 lan8 (loop)`; `bridge link` without lan3/4/7/8; those ports DOWN.
- Earlier check with the ports kept down (15:06): port MIB in/out of ports 16/20/26/27 = 0, storm guard no trip.
- All ports bridged (before the automatic removal): STP blocked lan4 and lan8.

## SMP: IRQ routing and latency (#73)

```
./dev.py build-kernel                 # SMP (default); --up = one VPE; --latency = timerlat + irqsoff tracers
./dev.py irq-check snap A             # per-CPU /proc/interrupts + effective affinity over SSH
./dev.py irq-check diff A B
./dev.py irq-check pin eth0 2         # NIC IRQ to CPU1 (needs 300-18; without it the NIC goes dead)
./dev.py irq-check latency L [--secs S] [--load]
```

- Results: [MAINLINE-PORT.md](MAINLINE-PORT.md) section 9.

## Recover

- Power-cycle via the relay: `./dev.py power off`, `./dev.py power on` (flash chain boots OpenWrt with STP). `./dev.py stock` to stop at the stock prompt.

## Line-rate loop test: selwyn -> sw2 lan3 -> cable -> lan6 -> selwyn (#182)

- `python3 scripts/iperf_hwloop.py [--only tcp-bidir,...]`: iperf3 in host netns on VLANs 991/992, ASIC-switched through the lan3 <-> lan6 fibre (1G, GLC-SX-MM). Kernel loop detect off on sw1 and sw2 for the run (sw1 shuts its DAC lan4 otherwise), STP off on sw2, watchdogs revert both switches.
- Measured 2026-11-21T02:09+11:00, 8 s runs, TCP, selwyn enp8s0 10G -> sw1 10G -> sw2 lan1 10G, sw2 on OpenWrt 7.4-rc3 both CPUs, stock bridge config:
  - One direction: 941 Mbit/s receiver. Both directions at once, unpaced: 932 Mbit/s one stream, 280-333 Mbit/s the other (which one varies per run), 200-380 retransmits, sw2 lan1 `dot1dTpPortInDiscards` +1300..2700 per run.
  - Both directions at once, each paced to 900 Mbit/s (`iperf3 --bidir -b 900M`): 900 + 900 Mbit/s, 0 retransmits, 0 discards.
  - sw2 CPU 1-2 % in every run (eth0 IRQ about 50-80 per 8 s): the path is ASIC only. Selwyn CPU at most 25 % on one core.
- Cause: unpaced TCP bursts arrive at 10G on lan1 and leave at 1G; the ASIC drops at lan1 ingress when two such streams overlap, one stream loses repeatedly. Pause is off on lan1 (RX/TX off) and on the host NIC/sw1 lan4/lan5.
