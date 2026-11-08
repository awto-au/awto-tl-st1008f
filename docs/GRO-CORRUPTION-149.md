# #149: GRO bucket corruption investigation (2026-11-08)

Status: writer **not identified**. The change adds opt-in diagnostics and reuses
existing board tooling. No board run, kernel target build, hardware fix or merge
is claimed by this investigation.

## Evidence that governs this investigation

- [Latest issue result](https://github.com/awto-au/awto-tl-st1008f/issues/149#issuecomment-6718980229):
  B-clean, OpenWrt r38178 + patches on **7.4-rc1**, failed nine times across eleven
  boots at common clocks: core 508, CPU 1350, DDR 662, SRAM 500, LX about 305-306.
  It is not confined to 7.3, perf-enabled kernels, or low LX clocks.
- [Controlled results](NAT-STACK-RESULTS.md) records nine recoveries, but also says
  two hangs had no oops captured. All captured initial oopses share
  `gro_list_prepare`; do not manufacture a GRO backtrace for a silent hang.
  The eleven boots are not eleven identical, independent short trials.
- B survived one full final-clock campaign boot (core 608 / CPU 1325). C-clean3
  survived one boot at each clock set. Earlier B-profile images survived extended
  runs at different clocks. These are useful controls, not proof of a cure or of
  a particular failure probability for this shorter reproducer.
- The earlier 7.3 register decode places the bad list node inside NIC private
  memory, apparently `napi->poll_list`, rather than a slab skb. Its inferred
  layout must be rechecked against the **actual failing B-clean vmlinux**. Do not
  reuse offsets across builds or assume that the new panics have the same
  register values merely because they share a function name.

## Reconstructed source and B/C differences

The driver reviewed here is OpenWrt commit
`7e8bfcfe76204efc9433be341642901876eb555b`,
`target/linux/realtek/files-6.18/drivers/net/ethernet/realtek/rtl838x_eth.{c,h}`,
with this repository's active rteth patches applied in order through 300-43.
They apply with fuzz zero (some line offsets). Linux core reviewed is
`v7.4-rc1`, commit `6628e7d4c6b25c8d18f1345e3a20d21829aae7e4`.

| Area | B-clean | C-clean3 | Implication |
|---|---|---|---|
| Linux base / active rteth patches | 7.4-rc1 / 300 series | same | Kernel generation alone cannot explain this result |
| Kernel compiler | OpenWrt GCC 14.4.0 | host cross GCC 16.2.1 | Code generation remains unisolated |
| Extra generic patches | pending 700, 701, 344, 644, 645; hack 910, 911, 940 | pending 344, 644 | B/C are not identical kernel source trees |
| 700 / 701 / 645 | flowtable NETDEV_DOWN cleanup; tolerate unsupported offload binding; DSA multicast-snooping hook | absent | No direct GRO list write; device transitions and offload lifetimes still matter |
| PREEMPT / HZ, tracing | VOLUNTARY / 100, clean | aligned by clean fragment | Compare final built configs, not only seed fragments |
| Userspace tools | OpenWrt | B's BusyBox, musl, nft, ip/tc, ethtool, dropbear | Tool version differences largely removed in clean3 |
| Services / topology | procd, netifd, logd, linkwatch and OpenWrt base remain | minimal initramfs | Device up/down, bridge activity and timing remain different |
| Latest normalised receive settings | RPS/XPS 0, noqueue, IRQ VPE1, GRO + rx-gro-list on | same | RPS-off and direct TX can change timing and skb lifetimes; neither is itself a proof of a core race |

`scripts/mainline_build_check.py` and `scripts/build_openwrt.py` share the pinned
driver inputs. Neither extra B patch set directly changes `net/core/gro.c` or
`net/core/dev.c`. The saved final B/C configs, image binaries, vmlinux files and
console captures are not in this checkout, so a full binary/config comparison
cannot be completed here. In particular `openwrt/kernel-7.4/config-7.4` is an
input, not the final B-clean `.config`.

## Receive and scheduling paths

1. `rteth_net_irq()` acknowledges/masks pending ring interrupts and calls
   **`napi_schedule()`**, not raw `__napi_schedule()`, for each ring.
2. Both TX-full paths in `rteth_start_xmit()` can schedule the RX NAPI on the
   transmitting CPU. They also use `napi_schedule()`. In the pinned core,
   `napi_schedule_prep()` atomically acquires SCHED or sets MISSED; only the
   successful acquirer links `poll_list` into that CPU's softnet list.
3. `rteth_poll_rx()` reclaims TX under each txq lock, receives from its ring,
   and returns the full budget while stopped TX queues still have pending DMA.
   This can extend polling and changes timing, but does not release SCHED or
   authorize a second poller. Both RX NAPIs can reclaim either TX ring; the
   txq lock serializes those accesses (`tx_by_cpu` additionally restricts them).
4. RX tests OWN, executes `rmb()`, invalidates/caches the descriptor, checks
   length, and allocates a replacement fragment before consuming the old one.
   Stack RX synchronizes the old page for CPU access and builds a recyclable
   skb. The ring gets the replacement page before OWN is returned with
   `dma_wmb()`. A held GRO skb's old fragment must not reappear in the RX ring.
5. `napi_gro_receive()` hands over skb ownership; the driver then drops its
   local pointer. Fast-path success transfers the old page to a TX slot with
   `RTETH_ZC_MARK`, and skips skb construction/GRO; TX completion returns that
   page through the non-direct page-pool return. Stack fallbacks still use GRO
   during a zc test. `zc=0` therefore separates ZC ownership from stack failure.
6. `napi_complete_done()` flushes GRO and the normal batch **before** removing
   `poll_list` and atomically clearing SCHED (or rescheduling for MISSED).
   A new CPU can legitimately begin polling after SCHED is released while the
   old callback is still returning. The current driver only rearms IRQs after
   a successful completion; it does not touch GRO after completion.
7. A full-budget return leaves core ownership intact; `__napi_poll()` may flush
   GRO and then repoll. A driver-only RX-body guard cannot observe all of that
   core flushing, so its silence cannot exclude a completion/core race.

RPS normally queues already delivered skbs to another CPU's backlog NAPI, not
into the NIC's GRO buckets. With RPS disabled, noqueue can make forwarding/TX
reclaim occur synchronously while GRO delivers a batch. That is a useful timing
and ownership discriminator, not an identified illegal operation.

## Operations that could create the observed list

| Candidate | Specific operation / required failure | What would discriminate it |
|---|---|---|
| Duplicate NAPI list ownership | Two successful schedule/list-add operations on the same `poll_list`, premature SCHED release, or poll/core-flush overlap | DEBUG_LIST / DEBUG_NET first warning; RX overlap diagnostic; compare IRQ VPE0 vs VPE1 while all other settings stay fixed |
| Completion race | GRO receive on one CPU while another flushes/removes that bucket; late write after completion releases ownership | Diagnostic boundary plus first core list error; guard must **not** span callback return and classify legitimate migration as a race |
| skb lifetime error | An skb still linked in `gro.hash[b]` is delivered/freed, recycled through the per-CPU napi skb cache, or reused on a second list | Bucket check around GRO and TX reclaim; SLUB debug; RPS / qdisc arms; inspect first invalid list-op stack |
| Layout / stale object mismatch | Caller and core disagree on `napi_struct`/`gro_node` layout, or core receives the wrong base pointer | Fresh build outputs; compare DWARF `offsetof(napi_struct, gro/poll_list)` and disassembly arguments in the **same** vmlinux; diagnostic prints actual driver addresses |
| Netpoll | `poll(napi, 0)` or emergency TX interleaves with normal polling | Establish NETPOLL/NETCONSOLE in final config, active setup, and zero-budget counts before ranking it highly |
| DMA / fragment ownership | A held fragment is returned twice, an in-flight descriptor points at private memory, or a stray DMA/cache operation overwrites a software list | Reproduce with ZC disabled; capture descriptor DMA ranges and page refs at first failure if software ownership checks remain clean |
| Flowtable lifetime | Concurrent flow removal/replacement or NETDEV_DOWN callback invalidates ZC action/page ownership | Ordinary stack `nat` with ZC disabled vs `nat-ft` / ZC; correlate netifd and device transition logs |

`napi->poll_list` and `skb->list` are different intrusive lists. The core's
`list_add_tail(&napi->poll_list, &sd->poll_list)` does **not** normally write a GRO
bucket. A race allegation still needs a wrong pointer, alias, stale skb, or
invalid ownership transition connecting those operations. DEBUG_LIST detects
bad link operations, not arbitrary DMA overwrites; a bad write can also leave
locally reciprocal links, so it does not guarantee detection of the first writer.

Netpoll is lower priority than the earlier issue analysis assumed: the checked-in
7.4 input has NETPOLL=n and NETCONSOLE=n. If the actual B config agrees, that
mechanism is absent. If enabled, core `poll_owner` serializes poll calls and
NPSVC prevents completion from dequeuing the NAPI. Budget zero skips the RX
loop and completion (`0 < 0` is false), but this driver still reads/writes the
saved partial skb, updates counters and may kick ZC TX; its ZC reclamation also
returns pages. Audit that against the zero-budget API restrictions, rather than
assuming netpoll must corrupt the list. No such contract change is bundled here.

## Diagnostic patch 300-45

- Only CONFIG_DEBUG_NET builds contain the code/extra per-ring state. Enable at
  boot with `rtl838x_eth.gro_diag=1`; the parameter is boot-only, defaults off.
  Ordinary DEBUG_NET=n builds retain the original layout and compiled hot path.
- A per-ring atomic owner catches overlapping positive-budget **RX bodies**.
  It releases ownership before calling completion; it does not serialize or
  repair NAPI. Panic output includes CPU+1 owner, CPU, ring/slot, phase, actual
  NAPI/poll-list/GRO addresses, state/list_owner, CPU poll counts and budget-0 count.
- Bounded bucket checks run at poll entry, after TX reclaim, before/after every
  GRO handoff, and before completion. They check count, bitmask and forward/back
  links, reject NULL/misalignment and **any address inside ctrl** before treating
  a list node as an skb, and bound traversal to 8 (pinned kernel MAX_GRO_SKBS).
  The observed poll_list alias is rejected even if it appears after a valid node.
- Limitations: diagnostic panics deliberately stop the bench; enable only on sw2.
  Arbitrary unmapped addresses can still fault; this is not a safe arbitrary
  memory reader. The RX-body guard misses core flush-only overlap. The final
  pre-completion check cannot observe corruption occurring later inside core
  completion/repoll; the next poll or DEBUG_LIST may detect it. Extra memory and
  timing changes can hide a race. No result from this image is a speed figure.

## Small, adaptive board experiment

Use sw2 only, one cage, RAM boot, no flash writes. Keep common clocks fixed.
Do not infer a fix from final-clock success. Run commands through existing tools.

1. Preserve B-clean/C-clean3 and their sha256, saved final `.config`, compiler
   version, vmlinux and prepared rteth/core source hashes. Copy the original
   failing capture. Reconfirm one short B-clean TCP reproduction, bounded at
   three fresh boots. If it does not reproduce, stop and match the failing cell
   and state before comparing arms. Do not run the full throughput campaign.
2. Build one B-clean+DEBUG image from this branch, in a separate output tree:
   `./dev.py build-openwrt --kernel mainline --clean --debug --tag=-gro149 --no-comment`.
   This intentionally combines allocator/list diagnostics with 300-45. Verify
   final DEBUG_NET/DEBUG_LIST/SLUB_DEBUG_ON and actual NETPOLL/NETCONSOLE, parameter
   activation, config and image hashes. The clean/profile suffix alone is not evidence.
   Use the existing `openwrt-ours-debug` ramload key with its image path pointed
   to this archived build (the build tag is not automatically a ramload key).
3. One diagnostic boot first; if quiet, at most three matched boots. Preserve
   the **first** warning/panic and full console bytes, not only the later GRO
   crash. `phase=after-gro` narrows detection to GRO/delivery/reclaim work;
   `phase=poll-enter` brackets damage to the previous completion/core/idle
   window or an external writer. Neither identifies the writer by itself.
4. If no first-writer evidence, use the **original B-clean**, not the diagnostic
   build, for one change at a time: rx-gro-list off (GRO on), then GRO off if
   needed; RPS mask 1 (CPU0), qdisc fq_codel, then IRQ CPU0. Stop on a discriminating
   result and interleave a failing baseline before spending more boots. Bound
   each initial arm at three boots; a quiet arm is only a lead. RPS/qdisc/GRO/IRQ
   must be read back in pre/post snapshots because services can overwrite them.
5. Then B-profile at identical common clocks and normaliser settings, **no perf
   process**. Compare final configs. If only that build differs, rebuild B-clean
   and C-clean3 with the same compiler before changing driver semantics. A
   threaded-NAPI run comes later; do not combine it with the IRQ/RPS tests.
6. If all software diagnostics stay clean, add page/descriptor ownership tracing
   around the narrowed boundary. Capture RX slot DMA and old/new page+offset,
   ZC transfer/reclaim, and slab skb lifetime; do not replace barriers or copy
   every packet as an unexplained production workaround.

Existing reproducer, baseline example (print with `--dry-run` first):

```sh
python3 scripts/panic_repro_trial.py owrt --clock-set common \
  --image openwrt-ours-clean --normalize --no-perf --tcp --secs 15
```

Append just one of `--gro-mode list-off`, `--gro-mode off`, `--rps-mask 1`,
`--qdisc fq_codel`, or `--napi irq0`. IRQ0 is passed to both normaliser and traffic
helper so the latter cannot silently restore IRQ1. C control uses `plain
--kernel mainline-7.4-rc1-clean3.bin` with the same remaining options. Diagnostic
boot adds `--image openwrt-ours-debug --bootargs rtl838x_eth.gro_diag=1` after the
image key has been pointed at the new build.

This runs the existing zc_bench TCP P4 stack/ZC cells in both directions, not the
entire campaign and not an exact replay of every failing nat-ft cell. The saved
plan records that difference. For the original UDP sequence omit `--tcp`;
`panic_ab_trial.py` remains available unchanged for historical perf trials.
TCP trials require `--no-perf` because the existing TCP helper has no perf wrapper.

The reproducer returns 1 for a captured panic, 2 for failed setup/trigger/SSH, a changed boot identity or
normalisation, and 0 for no panic with successful steps and final SSH health.
A diagnostic failure takes precedence over a secondary traffic failure. Each
run records the command/options, identity/clock register readback, console slice,
and pre/post snapshots. Final-clock readback and pre/post drift still need review;
exit 0 is not an assertion that those snapshots are identical or that a bug is fixed.

## Software validation in this workspace

- Reconstructed pinned upstream driver plus all active rteth patches; 300-45
  applies with `patch -p1 -F0 --dry-run` without fuzz or offset.
- `python3 scripts/panic_repro_host_test.py -v`: 11 tests pass. Includes actual
  bucket-walker C extracted from the patch, compiled with GCC `-Wall -Wextra
  -Werror -fsanitize=address,undefined`: healthy 0..8-node lists, overfull/cycles,
  bad prev/tail/count/bitmask, NULL/misaligned nodes and poll_list/foreign bucket
  aliases at both the first and later node. Leak sanitizer is disabled for this
  ptraced runner; address and undefined-behaviour sanitizers remain enabled.
- Command/normaliser checks cover shell syntax, independent arms, identical
  clock recipes, no accidental perf on clean trials, dry-run without hardware,
  invalid/panic/healthy verdicts, and refusal of failed/missing TCP measurements.
- Python syntax compilation and `git diff --check` pass.
- **Not run:** target kernel compile, boot-log/board checks, traffic or corruption
  reproduction on hardware. No MIPS cross compiler, images, serial captures or
  connected bench are available in this workspace. Host fixtures do not prove
  target concurrency (the C11 owner fixture tests acquisition/release semantics only), cache behaviour or the complete driver's compilation.
