# fib_offload library skeleton (#85), retired 2026-11-17

- Source: branch `worktree-agent-a700be6d0c0ffee03`, commit 86b3875 (2026-10-12), agent stopped at its usage limit; never built.
- Content: design text only in three patch stubs (shared FIB/netevent/neighbour plumbing for switch drivers) + `fib_offload_vmtest.py` (VM selftest runner).
- Why retired: patch numbers 300-21/22/23 now belong to other patches; the upstream plan lives in docs/UPSTREAM-L3.md (#85).
- The branch's other commit (no netfilter guard decision) is already on main (docs/DECISIONS.md).
