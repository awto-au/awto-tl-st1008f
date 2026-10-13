# Remote syslog (#115)

Owner 2026-10-13: switch logs go to TrueNAS, so a reboot no longer loses them.

## Receiver

- TrueNAS (`192.168.25.64`, TrueNAS 27.0.0-RC.1), custom app `syslog`: `balabit/syslog-ng:4.11.0`, UDP 514 + TCP 601.
- Definition: [truenas/syslog-app.json](../truenas/syslog-app.json) (`app.create` params; config inline as a Compose `configs:` entry).
  - syslog-ng macros are written `$${...}` there: Compose interpolates `${...}` itself (the first deploy wrote `--.log`).
- Files: dataset `p3/syslog`, `/mnt/p3/syslog/<sender IP>/<YYYY>-<MM>-<DD>.log`. Sender IP, not hostname: both switches report hostname `OpenWrt`. Dates follow the switch clock (UTC).
- Rebuild: awto-terminal `scripts/truenas.py call app.create "$(cat truenas/syslog-app.json)"` (then `app.update` for changes). Stray `/mnt/p3/syslog/--.log` from the first deploy is harmless.

## Senders

- `./dev.py openwrt-syslog [--ip A.B.C.D]`: `system.@system[0].log_ip=192.168.25.64`, `log_port=514`, `log_proto=udp`, `uci commit`, `log` restart, test line, PASS when the receiver file grows (TrueNAS API `filesystem.stat`; the API has no file read).
- Set on sw1 (`.48`) and sw2 (`.56`) 2026-10-14T09:07+11:00. Kept across sysupgrade (config kept); a `sysupgrade -n` install (sw2 `openwrt-install`) needs the flow again.
- Not covered: U-Boot and the kernel before `logd` starts; those stay on the serial console (sw2) and in `logread` replay of the kernel ring after logd starts.
