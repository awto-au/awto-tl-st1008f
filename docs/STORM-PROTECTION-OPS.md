# Storm and loop protection: operations (#111)

Facts, limits and code: [STORM-PROTECTION.md](STORM-PROTECTION.md).

## Build

- U-Boot: `./dev.py build-uboot` (or `scripts/build_uboot_mainline.py`); copies `shared/rtl930x-storm/rtl930x_storm.h`.
- Kernel: `./dev.py build-kernel` (`scripts/mainline_build_check.py`); 300-26 + the shared header. OpenWrt on mainline: `scripts/build_openwrt.py --kernel mainline`.

## Check the state

- U-Boot: `rtk storm` (meters per cage + CPU, EXCEEDED, bypass), `rtk loopdetect` (trap, cage forwarding, MAC TX/RX).
- Linux: `cat /sys/kernel/debug/rtl838x/storm`; `dmesg | grep -E 'storm|loop:'`.
- Host: `./dev.py switch-check` (`storm=` lines), `./dev.py drop-counters snap` (STORM_CONTROL total + debugfs), `./dev.py selftest` (item `storm`).

## Change at run time

- U-Boot: `rtk storm <bc> <mc> <uc>` (pps, 0 = off), `rtk storm off|on`; persistent: env `rtk_storm=off` or `rtk_storm=<bc>,<mc>,<uc>`.
- Linux: `echo "<bc> <mc> <uc>" > /sys/kernel/debug/rtl838x/storm`; `echo "loop off"` / `"loop on"` / `"unshut"` to the same file.
- Linux boot: `rtl_otto_dsa.storm_bc=N rtl_otto_dsa.storm_mc=N rtl_otto_dsa.storm_uc=N rtl_otto_dsa.loop_detect=0 rtl_otto_dsa.loop_recover_s=N`.

## Recover a shut port

- Wait `loop_recover_s` (60 s): TX/RX return by themselves, logged `loop: lanN back up`.
- Now: `echo unshut > /sys/kernel/debug/rtl838x/storm` (after removing the loop cable).

## sw2 test plan

- sw2 only (`scripts/boards.py`); never sw1. Fitted loops (CLAUDE.md Hazards, docs/hardware.md "sw2 loopbacks"): cages 3 ↔ 4 passive DAC (ports 16 ↔ 20, always transmitting), cages 7 ↔ 8 fibre (ports 26 ↔ 27).
- The storm guard (`storm_watch.py --guard`) runs automatically under every `./dev.py` hardware command; its trip (2 × 1 s samples over max(2000 pps, 20 × baseline)) is the pass/fail witness for anything that reaches the host.
- Steps L2-L5 keep the management cage out of the test bridge: a loop never reaches the house LAN.
- Script the console steps into one `./dev.py` flow (CLAUDE.md: no hand-typed sequences); each step = one quick check, no repeats.
- Every boot: `./dev.py check-log`. The probe line is allowlisted; `loop:` / `storm:` warnings are not, so steps L3-L5 are expected to flag them (a real event).

### U1: U-Boot defaults

- `./dev.py ramload uboot-mainline`, then `rtk storm` and `rtk loopdetect`.
- Expect: boot line `rtk: storm control bc/mc/uc 10000/20000/20000 ...`; cages 1-8: `broadcast 10000 pps/1000 multicast 20000 pps/2000 unknown-unicast 20000 pps/2000`; cpu: same with `unknown-unicast off` (pps read back via the 1000/1014 conversion: ±1); bypass bpdu 1 rma 1 rtkpkt 1; mode 0x00000000; trap `to CPU`; every cage `forwards to cages 0x0000000`, `guard` line.
- Fails if: a meter reads `off`, the trap is OFF, or `LOOP POSSIBLE` shows without `port-isolation off`.

### L1: Linux defaults

- `./dev.py ramload mainline-kernel` (initramfs) with a 300-26 kernel.
- Expect: dmesg `storm control bc/mc/uc 10000/20000/20000 pps per port, loop detect on (recover 60 s) (#111)`; debugfs as U1 plus `loop: on, period 1000 ms, recover 60 s, probes 0`.
- Management traffic (SSH, TFTP) over the mgmt cage works as before (meters only drop floods).
- CPU-port meter: a ping flood (`ping -f -b` on a test bridge, short) from the switch; `storm_s` on `cpu` > 0 means CPU TX is metered (open item).

### L2: STP blocks the loop (no shut)

- Bridge `br-t` = lan3 + lan4 only, `stp_state 1`, forward_delay 2 s; bring both up (cage 3 ↔ 4 DAC).
- Expect: STP blocks one port within ~4 s; `probes` rises 1/s; `ignored` rises (probe from the forwarding port lands on the blocked one); `loops 0`, no `SHUT`, no dmesg `loop:`.
- Also read the drop/trap side: the probe reaching the CPU with RLDP reason (trapped) vs flooded. Trapped = `ignored` counts but the blocked port's MIB shows no RX broadcast forwarding; record which in STORM-PROTECTION.md (open item).

### L3: loop without STP: shut within 1 s

- `br-t` = lan3 + lan4, `stp_state 0` (both forwarding at once).
- Expect within ≤ 2 s of the ports forwarding: dmesg `loop: probe sent on lan3 came back on lan4: lan4 shut down for 60 s (#111)` (or lan4 → lan3 → lan4 shut: higher port shut either way); debugfs `lan4: loops 1 last with lan3 SHUT 5x s left`; `rtk`-style MAC read: `MAC_L2_PORT_CTRL(20)` bits 1:0 = 0.
- During the < 1 s storm: `storm_s` on lan3/lan4 0 or 1, drop reason STORM_CONTROL > 0 possible. Host storm guard: no trip (traffic stayed in br-t).

### L4: recovery and re-detection

- Leave L3 cabled. Expect at +60 s: `loop: lan4 back up after 60 s, probing again`, then a new `loop:` shut within 1 s; `loops 2`.
- `echo "loop off"` → lan4 TX/RX on, no new shut (now only the meters hold the loop: go straight to L5 or tear down).

### L5: meters alone cap a loop

- `br-t` = lan3 + lan4, `stp_state 0`, `echo "loop off"` first; seed one broadcast (`arping -b -c 1 -I br-t` or the bridge's own ARP).
- Expect: `NOW` on lan3/lan4 broadcast, `storm_s` rising 1/s, dmesg `storm: lan3 broadcast over the limit, excess dropped`; drop-counters STORM_CONTROL nonzero each read; CPU load bounded (≤ 2 × 10000 pps of broadcast reach the CPU).
- Tear down after ≤ 10 s: `echo "loop on"` → shut within 1 s (proves L3 again from a running storm), then delete br-t.
- Repeat L3 once on the fibre pair 7 ↔ 8 (lasers on both cages: one pair lit at a time).

### L6: management bridge (last, only after L3 + L5 pass)

- OpenWrt (flash layout, bridge `switch` with STP on, mgmt cage included) + cage 3 ↔ 4 added: STP blocks (L2 behaviour), no `loop:` line.
- Then STP off on `switch` (the 2026-10-10 incident shape): expect a `loop:` shut ≤ 1 s and the host storm guard not tripping. If it trips, the relay kill ends the test: record the storm_watch log and dmesg in #111.
- Run: `./dev.py ramload openwrt-ours-6.18`, then `./dev.py storm-test l6` (fibre pair 7 ↔ 8 by default, `--pair` to change).
- lan1 (mgmt/uplink) is taken out of `switch` for the test: the loop never reaches sw1 or the house LAN. Same bridge, kernel and netifd path; a shut that takes 1 s would still put ~1 s of storm on the uplink if lan1 stayed in.
- STP-on half (L2 behaviour in `switch`) not scripted yet.

## After the test

- Results (pass/fail per step, trapped vs flooded, CPU-port meter yes/no) go in STORM-PROTECTION.md with date + commit.
- #111 step 4: SPG refusals (#70) → warnings; storm_watch → logger. Only after L3 + L5 pass.
