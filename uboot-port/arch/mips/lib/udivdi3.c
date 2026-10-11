// SPDX-License-Identifier: GPL-2.0
/*
 * libgcc u64 divide/modulo for MIPS32 (o32: both operands are 64-bit register pairs).
 * Replaces v2026.07's `__udivdi3(long long, word_type b)`: on big-endian `b` is the divisor's
 * high word (0 for any 32-bit divisor) -> `divu` by zero -> teq trap (#33). No `divu` here.
 */

typedef unsigned long long u64_t;

/* Shift-subtract; at most 64 rounds. d == 0 traps, as a hardware divide by zero does. */
static u64_t udivmod(u64_t n, u64_t d, u64_t *rem)
{
	u64_t q = 0;
	int shift = 0;

	if (!d)
		__builtin_trap();
	while (!(d >> 63) && (d << 1) <= n) {
		d <<= 1;
		shift++;
	}
	for (; shift >= 0; shift--) {
		q <<= 1;
		if (n >= d) {
			n -= d;
			q |= 1;
		}
		d >>= 1;
	}
	*rem = n;
	return q;
}

u64_t __udivdi3(u64_t n, u64_t d);
u64_t __umoddi3(u64_t n, u64_t d);

u64_t __udivdi3(u64_t n, u64_t d)
{
	u64_t r;

	return udivmod(n, d, &r);
}

u64_t __umoddi3(u64_t n, u64_t d)
{
	u64_t r;

	udivmod(n, d, &r);
	return r;
}
