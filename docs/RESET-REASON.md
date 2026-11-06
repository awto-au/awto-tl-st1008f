# Reset reason: the black box (#144)

Why the last boot ended, kept across panic, watchdog reset and reboot, readable with no console.

## Mechanism
- Page: phys `0x0e000000`, 4 KiB, DT `reserved-memory` `bootrec@e000000` (`no-map`). Survives panic, SoC watchdog reset and reboot (DRAM is not cleared). U-Boot's boot-attempt record uses the first 16 bytes; the black box sits at `+0x100`.
- 6.18 DTS: reservation added in `openwrt/backport-6.18/openwrt-tree.patch` (before #144 only the mainline DTS and `--default-boot` images had it). sw1 had none until its next image.
- Record (kernel, `tplink-st1008f-mode.c` in `300-06`): magic `BBOX`, boot number, state, uptime s, heartbeat count, 80-byte message, CRC32 of the first 104 bytes.
- Kernel writes: at boot (state RUNNING), every 1 s (heartbeat), panic notifier (state PANIC, message = panic text), reboot notifier (state CLEAN, `restart` / `halt` / `power off`). Userspace may set the message: `echo STAGE > /sys/kernel/debug/st1008f-blackbox/note`.
- U-Boot (`bootsel.c`, `bb_read`) reads the record before `bootm`, prints `Last:  <kind>, boot #N, up S s, hb H, msg "..."` and passes `st1008f.lastreset=<kind>`. The record stays for the kernel.
- Kernel at boot: `st1008f-blackbox: previous boot #N ended <state> after S s` and `/sys/kernel/debug/st1008f-blackbox/last`.

| Kind | Meaning | Message |
|---|---|---|
| `clean` | reboot / halt / power off through the kernel | `restart`, `halt`, `power off` |
| `panic` | kernel panic (also `kernel.panic=0` hangs) | the panic text |
| `unclean` | kernel was running, no panic: hang (SoC watchdog), bus lock, power cut | last note, `boot` by default |
| `cold` | no valid record: power-up (DRAM random) or first boot of an image without the black box | - |

- `unclean` locates a hang to the last heartbeat (`up_s`, about 1 s before the end).
- The SoC reset-status words `RST_GLB_STS_0/1` (`0xBB000010/14`) read 0 after a panic, a hang reset and a reboot on sw2 (2026-11-06): they do not tell the cases apart, so they are not used.

## Validated on sw2 (2026-11-06, network only, `./dev.py stress-trace --inject ...`)
- panic injection (`sysrq c`): `lastreset=panic`, `msg=sysrq triggered crash`, up 76 s (last trace sample 0.15 s earlier).
- clean reboot: `lastreset=clean`, `msg=restart`.
- bus lock (`devmem` on a wrong physical address): `lastreset=unclean`, last heartbeat 70 s, outage 70 s (SoC watchdog).
- first boot of the image: `lastreset=cold`.

## Not done
- netconsole (`60-st1008f-netconsole` hotplug, module loads, "network logging started") put no datagram on the host NIC; the panic text comes from the black box instead.
- sw1 has not received this image or the U-Boot slot.
