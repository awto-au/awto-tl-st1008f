#!/usr/bin/env python3
"""udivdi3_host_test — run uboot-port/arch/mips/lib/udivdi3.c on the host under qemu-mips (#33).

- Builds a freestanding MIPS32r2 big-endian o32 program (same flags as the U-Boot build) from the
  staged udivdi3.c plus a generated test: u64 `/` and `%` against Python-computed results.
- Also shows the mainline bug: a `(long long, int)` callee called with the libgcc
  `(u64, u64)` ABI sees the divisor's high word (0 for a 32-bit divisor).
- Needs mips64-linux-gnu-gcc and qemu-mips-static. Log: tmp/logs/udivdi3_host_test.log. Exit 0 = pass.
"""

import random
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "uboot-port/arch/mips/lib/udivdi3.c"
WORK = ROOT / "tmp/udivdi3-test"
LOG = ROOT / "tmp/logs/udivdi3_host_test.log"
CC = "mips64-linux-gnu-gcc"
CFLAGS = ["-march=mips32r2", "-mabi=32", "-EB", "-O2", "-static", "-nostdlib", "-ffreestanding",
          "-fno-pic", "-mno-abicalls", "-Wall", "-Werror"]
# compile: one small file, < 1 s; run: ~200 divides under qemu user mode, < 0.2 s. Both x ~10
# because qemu/gcc start-up dominates and varies with host load; expiry = logged FAIL.
CC_TIMEOUT_S, RUN_TIMEOUT_S = 10, 5
M64 = (1 << 64) - 1

TEST_C = r"""
typedef unsigned long long u64;
struct tc { u64 n, d, q, r; };
static const struct tc t[] = {
%CASES%
};

static long sys3(long nr, long a, long b, long c)
{
	register long v0 asm("$2") = nr, a0 asm("$4") = a, a1 asm("$5") = b, a2 asm("$6") = c;
	register long a3 asm("$7");
	asm volatile("syscall" : "+r"(v0), "=r"(a3) : "r"(a0), "r"(a1), "r"(a2)
		     : "$1", "$3", "$8", "$9", "$10", "$11", "$12", "$13", "$14", "$15", "$24", "$25",
		       "hi", "lo", "memory");
	return v0;
}

static void say(const char *s)
{
	int n = 0;

	while (s[n])
		n++;
	sys3(4004, 1, (long)s, n);	/* write(1) */
}

/* mainline v2026.07 arch/mips/lib/udivdi3.c signature: returns the divisor it sees */
__attribute__((noinline)) long long old_abi(long long u, int b) { (void)u; return b; }

int main(void)
{
	long long (*as_libgcc)(u64, u64) = (void *)old_abi;
	volatile u64 n, d;
	unsigned i, bad = 0;

	for (i = 0; i < sizeof(t) / sizeof(t[0]); i++) {
		n = t[i].n;
		d = t[i].d;
		if (n / d != t[i].q || n % d != t[i].r)
			bad++;
	}
	say(bad ? "FAIL: u64 divide mismatch\n" : "PASS: u64 divide\n");
	say(as_libgcc(1000000000000ULL, 1000) == 0 ?
	    "mainline signature sees divisor 0 for 1000 (BE high word): confirms the trap\n" :
	    "mainline signature sees the right divisor (not the BE high-word bug)\n");
	return bad;
}

void __start(void)
{
	sys3(4001, main(), 0, 0);	/* exit */
}
"""


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def cases() -> list[tuple[int, int]]:
    rng = random.Random(33)  # fixed seed: same cases every run
    fixed = [(10**12, 1000), (0x123456789ABCDEF0, 0x12345), (M64, 0x100000001), (M64, 1), (M64, M64),
             (5, 7), (0, 3), (1 << 63, 3), (0xFFFFFFFF, 0xFFFFFFFF), (1 << 32, 1 << 32), (M64, 1 << 63)]
    rnd = [(rng.getrandbits(64), rng.getrandbits(rng.choice((8, 16, 32, 33, 48, 64))) or 1) for _ in range(200)]
    return fixed + rnd


def main() -> int:
    WORK.mkdir(parents=True, exist_ok=True)
    rows = ",\n".join(f"\t{{ {n:#x}ULL, {d:#x}ULL, {n // d:#x}ULL, {n % d:#x}ULL }}" for n, d in cases())
    test = WORK / "test.c"
    test.write_text(TEST_C.replace("%CASES%", rows))
    exe = WORK / "test"
    try:
        r = subprocess.run([CC, *CFLAGS, "-e", "__start", str(test), str(SRC), "-o", str(exe)],
                           capture_output=True, text=True, timeout=CC_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log(f"FAIL: compile exceeded {CC_TIMEOUT_S} s")
        return 1
    if r.returncode:
        log(f"FAIL: compile\n{r.stderr}")
        return 1
    try:
        r = subprocess.run(["qemu-mips-static", str(exe)], capture_output=True, text=True, timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        log(f"FAIL: run exceeded {RUN_TIMEOUT_S} s")
        return 1
    for line in r.stdout.splitlines():
        log(line)
    ok = r.returncode == 0 and "PASS" in r.stdout
    log(f"{'PASS' if ok else 'FAIL'} udivdi3: {len(cases())} cases, exit {r.returncode}"
        + (f", stderr {r.stderr.strip()!r}" if r.stderr.strip() else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
