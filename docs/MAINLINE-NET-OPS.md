# Mainline 7.3 network bring-up: operations

Facts (what is built, safety defaults, patch status): [MAINLINE-PORT.md](MAINLINE-PORT.md) sections 7-8. Issue #16.

## Preconditions

- `./dev.py build-kernel` OK (writes `tmp/tftp/mainline.bin`); fibre in cage 1 to the house switch.
- Host watching for loops: `./dev.py storm-watch --duration 3600` in a second terminal for the whole session.
- Console log open (`private/serial/st1008-console.log`).

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
- Tagged test instead of the house VLAN: `port-up 1 10.99.1.1/24 991`, host netns `natlan` on `enp7s0.991` = 10.99.1.2 (same VLAN as [NAT-OPS.md](NAT-OPS.md)); `ping 10.99.1.2`.
- 10G optics: if no link at 10G, record `ethtool lan1` + `dmesg` tail; PCS calibration is the known risk (#16 stage 5).

## Loop check

- `bridge link` -> empty; `ip -d link show lan1` -> no `master`.
- `storm-watch` silent; SG2008P log has no `OSW_DET_LOOP`.
- Cages 3 and 7 (GLC-T copper, cabled to each other) stay down: never `port-up` both, and never bridge without `stp_state 1`.

## Recover

- Power-cycle via the relay: `./dev.py power off`, `./dev.py power on` (flash chain boots OpenWrt with STP). `./dev.py stock` to stop at the stock prompt.
