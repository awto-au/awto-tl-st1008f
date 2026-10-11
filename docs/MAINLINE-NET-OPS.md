# Mainline 7.3 network bring-up: operations

Facts (what is built, safety defaults, patch status): [MAINLINE-PORT.md](MAINLINE-PORT.md) sections 7-8. Issue #16.

## Preconditions

- `./dev.py build-kernel` OK (writes `tmp/tftp/mainline.bin`); fibre in cage 1 to the house switch.
- Host watching for loops: `./dev.py storm-watch --duration 3600` in a second terminal for the whole session.
- Console log open (`private/serial/st1008-console.log`).

## Boot

```
./dev.py ramload mainline-kernel --cage 1
```

- Stock U-Boot `rtk network on` lights cage 1 only; Linux then isolates every port at DSA setup.
- `check-log` will flag the new driver lines (DSA, rteth, PCS, SFP probe lines, `rtldsa_93xx_setup called`): review them, add allowlist entries with an issue number.

## At `st1008f-linux # `

| Check | Command | Expected |
|---|---|---|
| Drivers probed | `dmesg \| grep -iE 'rtl83xx\|rteth\|rtl838x\|pcs\|otto\|sfp\|dsa'` | eth0 MAC line; DSA switch registered; no `-EPROBE_DEFER` loop, no `Call Trace` |
| Ports exist, all down | `ip -br link` | `eth0`, `lan1`..`lan8`, all `DOWN` |
| No bridge | `ls /sys/class/net/*/bridge 2>/dev/null` | empty |
| Lasers off | `cat /sys/kernel/debug/sfp-p*/state` (debugfs is mounted) | `tx_disable: 1` for every cage with a module |
| Isolation matrix | `cat /sys/kernel/debug/rtl838x/port_masks_table` | each front port: itself only (CPU port added once the port is up) |
| Thermal | `cat /sys/class/thermal/thermal_zone0/temp` | m°C, plausible |

## One cage up, ping the house LAN

```
port-up 1 192.168.25.48/24          # cage 1 only; .48 = st1008f-1-mgmt (ip-registry)
ip route add default via 192.168.25.254
ping -c 5 192.168.25.254
ethtool lan1                         # link speed / port
cat /sys/kernel/debug/sfp-p1/state   # tx_disable: 0 now
```

- `port-up` refuses while another `lanN` is up or a bridge exists.
- Tagged test instead of the house VLAN: `port-up 1 10.99.1.1/24 991`, host netns `natlan` on `enp7s0.991` = 10.99.1.2 (same VLAN as [NAT-OPS.md](NAT-OPS.md)); `ping 10.99.1.2`.
- 10G optics: if no link at 10G, record `ethtool lan1` + `dmesg` tail; PCS calibration is the known risk (#16 stage 5).

## Loop check

- `bridge link` -> empty; `ip -d link show lan1` -> no `master`.
- `storm-watch` silent; SG2008P log has no `OSW_DET_LOOP`.
- Cages 3 and 7 (GLC-T copper, cabled to each other) stay down: never `port-up` both, and never bridge without `stp_state 1`.

## Recover

- Power-cycle via the relay: `./dev.py power off`, `./dev.py power on` (flash chain boots OpenWrt with STP). `./dev.py stock` to stop at the stock prompt.
