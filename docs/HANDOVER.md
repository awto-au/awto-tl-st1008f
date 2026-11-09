# Handover 2026-11-09

## State
- Nothing running. sw2 state unknown; the next `./dev.py` flow resets it in software.
- Load generator now runs on TrueNAS (#165): `truenas/nat-bench-app.json` (privileged host-network Alpine app with iperf3/iproute2), VLAN subinterfaces of `enp7s0f0` in netns `natlan`/`natwan`, reached via sw1 lan6 -> lan4 -> sw2. Driven by `nat_bench.py`, `stack_compare.py`, `stack_normalize.py` (sw2-only guard kept).
- A/B/C results on that generator: [NAT-STACK-RESULTS.md](NAT-STACK-RESULTS.md). Earlier dev-host results are void (owner 2026-11-09); `tmp/controlled/` and `tmp/controlled/149/` (V0-V5) are history only.
- Watchdog reset at ~94 s (#166): GPIO21 `wdt-gpio` (watchdog1) was only fed by the kernel until `watchdog.open_timeout=92`; procd feeds watchdog0 only. Disabled in the OpenWrt overlay. Validated on RAM-loaded debug images, not yet on flash. Tool: `./dev.py debug-soak`.
- #167: `BUG: scheduling while atomic` during a procd-triggered reboot; caller unidentified.

## Plan
1. **Flash validation of #166**: build, sysupgrade sw2, bounded `debug-soak`; every boot judged by `check-log`.
2. **#149 root cause** (B at common clocks panicked 9/11 boots; C plain 7.4-rc1 never; B at core 608 / CPU 1325 never)
   - `./dev.py panic-trigger V0..V8 --boots N`. V0-V5 (dev-host generator, void) all still panicked with one factor changed (GRO off, rx-gro-list off, RPS unpinned, IRQ on VPE0, fq_codel); rerun on TrueNAS before trusting. V6-V8 unrun.
   - Decoded: GRO bucket list holds a pointer into the NIC's napi struct (`&napi->poll_list`); no writer found.
   - Debug image: `./dev.py build-openwrt --kernel mainline --clean --debug` (DEBUG_LIST, SLUB_DEBUG_ON, DEBUG_NET, DEBUG_VM, PAGE_POISONING). Build only while no bench run is in progress.
   - If that does not name the writer: MIPS watch registers (HARDWARE-INVENTORY.md) on `&napi->gro.hash[0].list.next`, both VPEs, `dump_stack()` on a write pointing into napi. Blind to DMA writers. EJTAG needs a probe adapter (none in repo).
3. **#167** reboot notifier: identify the atomic-context caller.
4. Owner dropped: further NAT testing on 6.18.

## Rules that bite here
- sw2 only for hardware flows; never power-cycle sw1. Reboot in software (`reboot` / `reset`).
- No long soaks; midpoint-bisection sweeps; one quick test per point.
- GitHub writes go through awto-dan's `scripts/gh_claudia.py` (bot identity).
