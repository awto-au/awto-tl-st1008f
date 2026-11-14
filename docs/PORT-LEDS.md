# Port LEDs

Reference for the 24 port LEDs (8 cages x 3). Hardware layout and registers: [hardware.md](hardware.md#port-leds), [RTK-COMMANDS.md](RTK-COMMANDS.md#port-leds). Design and owner decisions: #120.

## Hardware capability
- Software override per LED: off, on, or a symmetric blink at 32 / 64 / 128 / 256 / 512 / 1024 ms.
- A blink runs inside the LED engine: it keeps showing with the CPU stopped or hung.
- No asymmetric duty cycle, no phase control between LEDs: any sequence needs a CPU timer.
- Linux policy uses hardware blink only: no timer of ours; U-Boot keeps its snake for the autoboot countdown.

## Speed to LED (Linux, DTS `led_set0`)
- LED0 = 1G (also 100M/10M), LED1 = 2.5G, LED2 = 10G; 5G shares LED2.
- Stock-equivalent U-Boot maps LED0 = 10G, LED2 = 1G (hardware.md).

## Per-cage policy (Linux, driver `tplink-st1008f-leds.c`, patch 300-16)

| State | LEDs |
|---|---|
| Kernel up, no module report yet | all three blink 512 ms |
| No SFP | all three blink 32 ms |
| Module answers on the bus, type unread | all three on |
| Type known, no link | max-speed LED on |
| Linked at max speed | released to the hardware link/activity engine |
| Linked below max (10G module at 2.5G) | max-speed LED on, trained-speed LED blinks 512 ms |

- Module state and max speed: `st1008f_led_module()` called by the mode-switch driver (300-06) from its media pass (existing 500 ms poll).
- Max speed from the ID EEPROM: 10G compliance bits or nominal bitrate >= 0x60 -> 10G; 0x19-0x20 -> 2.5G; else 1G.
- Trained speed: netdev events on `lanN` (cage N) queue one work item that reads the ethtool link settings under rtnl.
- Overrides: sysfs `pattern` (manual) or an error latch stop the policy; `auto` / `clear` resume it.
- sysfs `/sys/devices/platform/st1008f-leds/`: `state`, `pattern`, `error`, `clear`, `cages` (module state, max, trained speed per cage).
- Config: `CONFIG_TPLINK_ST1008F_LEDS=y` in `mainline/st1008f-v2.config` and `openwrt/kernel-7.4/config-7.4`. The 6.18 OpenWrt build does not carry 300-16.
- Not yet on hardware: build, boot, front-panel check of the 32 ms blink against "all on".
