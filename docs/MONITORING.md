# Monitoring: 1 s trends in Netdata on TrueNAS

Owner 2026-10-14: every lab device polled at 1 s for full trends (temperatures, ports). TrueNAS's own reporting graphs only TrueNAS; the same engine (Netdata) runs as a TrueNAS custom app and graphs other devices.

## Pieces

- Netdata app on TrueNAS: http://192.168.25.64:19999/ (`netdata/netdata:v2.12.1`, data on dataset `p3/netdata`). Deploy/update: awto-terminal `python3 scripts/netdata_deploy.py plan|apply` (SNMP community from secrets, never in a repo).
- Ports, traffic, errors: SNMP v2c every 1 s (Netdata go.d `snmp`) against each switch's `snmpd` (`./dev.py openwrt-snmp`). Nodes named by `snmpd` sysName = hostname (`./dev.py openwrt-hostname`).
- Sensors: `st1008f-metricsd` on each switch pushes statsd gauges over TCP 8125 every 1 s: SoC (`cpu_thermal`, Realtek conversion #13) and per SFP module `temp_mC`, `vcc_mV`, `bias_mA`, `tx_uW`, `rx_uW` (sfp hwmon = DDM), copper PHY temperature (`smbussfpp*`), `load1`. Install: `./dev.py openwrt-metrics [--ip]` (any unit); shipped in every image, off until `/etc/st1008f-metrics.conf` exists.
- Logs: remote syslog to the same TrueNAS ([SYSLOG.md](SYSLOG.md)).

## Cost on the switch (sw2, 2026-10-14, OpenWrt main 0ad1348, CPU 1000 MHz)

| Collector | CPU per 1 s period |
|---|---|
| `snmpd` serving one Netdata SNMP poll (ifXTable bulk walk, 216 OIDs) | 43 ms |
| `st1008f-metricsd` (6 hwmon on sw2, nc + sleep forks) | 32 ms |
| `prometheus-node-exporter-lua`, all collectors (rejected) | 473 ms per scrape |
| same, hwmon + thermal only (rejected) | 292 ms per scrape |

- Total ~7.5 % of one VPE; userspace, so it runs on the VPE the NAT softirq leaves idle (#65).

## Devices

| Device | SNMP 1 s | Sensors |
|---|---|---|
| st1008f-1 (sw1, .48) | yes | metricsd |
| st1008f-2 (sw2, .56) | yes | metricsd |
| US-48 (us48-mgmt .206) | no answer 2026-10-14 | - |
| UNVR (woomera .40) | offline 2026-10-14 | - |

- Adding a device: enable its SNMP agent with the site community, add it to `DEVICES` in awto-terminal `scripts/netdata_deploy.py`, `apply`.
