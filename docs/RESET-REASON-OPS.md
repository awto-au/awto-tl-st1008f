# Reset reason and remote stress: operations (#144)

Facts: [RESET-REASON.md](RESET-REASON.md).

## Read the last reset
- On the unit: `cat /proc/cmdline | tr ' ' '\n' | grep lastreset`, `cat /sys/kernel/debug/st1008f-blackbox/last`, `dmesg | grep blackbox`.
- Console units: U-Boot prints the `Last:` line before `bootm`.

## Stress a unit over the network only (no console, sw1-style)
```
./dev.py stress-trace --ip 192.168.25.56 --cpu-secs 60 --mem-secs 30
./dev.py stress-trace --ip A.B.C.D --sw1-ok ...      # sw1: owner request only; a failing run costs about 100 s outage
./dev.py stress-trace --ip IP --inject panic|hang|bus|reboot --inject-at 20   # validate the recorder
```
- Needs: nothing on the unit (the sampler `st1008f-trace` is copied to `/tmp`); `sudo -n tcpdump` on the host for the netconsole capture.
- Waits for the unit's own boot selftest (about 30 s after boot) before starting.
- Output: `tmp/logs/stress_trace-<ip>-<ts>.trace` (every line host-timed: ping, per-VPE samples, selftest) and `.json` (result, last sample per VPE, outage, post-mortem including `lastreset` and the black-box record).
- Samples: 1 per second per VPE: uptime, tick jitter `dt`, SoC temperature, load, busy % per VPE, memory, last selftest line.
- Loss = no ping reply for 3 s. Back = a new boot (uptime lower than before).

## Deploy to a console-less unit (sw1) remotely
1. `./dev.py uboot-chain-install-ssh --ip IP` (U-Boot slot with the `Last:` read), 2. `./dev.py openwrt-sysupgrade-ssh --ip IP` (image with the black box + DTS reservation). Both only on owner request for sw1.
