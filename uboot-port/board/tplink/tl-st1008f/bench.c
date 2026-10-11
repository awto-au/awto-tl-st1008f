// SPDX-License-Identifier: GPL-2.0+
/*
 * `bench`: CPU, cache, DRAM and flash throughput, one line per test: `bench <name> <value> <unit>`.
 * Compared across clock settings by scripts/bench.py (docs/CLOCKS.md). Timed with CP0 ticks.
 */

#include <command.h>
#include <cpu_func.h>
#include <div64.h>
#include <time.h>
#include <u-boot/crc.h>
#include <vsprintf.h>
#include <asm/io.h>
#include <asm/mipsregs.h>
#include <linux/sizes.h>
#include <linux/string.h>

#define BUF		0x82000000	/* KSEG0, low bank, below relocated U-Boot (0x8ff.....) */
#define BUF_UC		0xa2000000	/* same memory, KSEG1 uncached */
#define FLASH_UC	0xb4000000
#define FLASH_C		0x94000000

static u64 bench_start;

static void start(void)
{
	bench_start = get_ticks();
}

/* print bytes/s (or ops/s) as an integer x 1000 / 1e6 = "MB/s" with 3 decimals */
static void done(const char *name, u64 amount, const char *unit)
{
	u64 ticks = get_ticks() - bench_start;
	u64 per_s = amount * get_tbclk();	/* units per second, after the divide */
	u32 milli;

	do_div(per_s, ticks ? (u32)ticks : 1);	/* u32 ticks: runs < 8.6 s */
	do_div(per_s, 1000);			/* thousandths of a mega-unit */
	milli = (u32)per_s;

	printf("bench %s %u.%03u %s\n", name, milli / 1000, milli % 1000, unit);
}

/* ns per access of a dependent chain: one miss at a time (latency, not bandwidth) */
static void done_ns(const char *name, u32 n)
{
	u64 ns = (get_ticks() - bench_start) * 1000000000ULL;

	do_div(ns, (u32)get_tbclk());
	do_div(ns, n);
	printf("bench %s %u.000 ns\n", name, (u32)ns);
}

/* chain of N nodes, stride 4 KiB + 64 (new line, spread over sets), visited in a scrambled order */
#define CHAIN_N		8192
#define CHAIN_STRIDE	(SZ_4K + 64)

static u32 *chain_build(ulong base)
{
	u32 i, j;

	for (i = 0; i < CHAIN_N; i++) {
		j = (i * 4099 + 1) % CHAIN_N;	/* 4099 prime, coprime to N: one cycle over all */
		*(u32 *)(base + i * CHAIN_STRIDE) = base + j * CHAIN_STRIDE;
	}
	return (u32 *)base;
}

static u32 chain_walk(u32 *p, u32 n)
{
	while (n--)
		p = (u32 *)*p;
	return (u32)(ulong)p;
}

static u32 cpu_loop(u32 n)
{
	u32 a = 1, b = 7;

	while (n--) {		/* dependent chain: no memory, no cache effects */
		a = a * 1664525 + 1013904223;
		b ^= a >> 7;
	}
	return a ^ b;
}

/* `bench div64`: plain u64 `/` and `%` through libgcc __udivdi3/__umoddi3 (trapped before #33) */
static int div64(void)
{
	volatile u64 n = 0x123456789abcdef0ULL, d = 0x12345, m = ~0ULL, d2 = 0x100000001ULL;

	printf("div64 %llx r %llx, %llx\n", n / d, n % d, m / d2);
	return 0;
}

static int do_bench(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	volatile u32 sink;
	u32 i, sum = 0;
	u32 *p;

	if (argc == 2 && !strcmp(argv[1], "div64"))
		return div64();
	start();
	sink = cpu_loop(50000000);
	done("cpu_loop", 50000000, "Mops/s");

	memset((void *)BUF, 0x5a, SZ_16K);
	start();
	for (i = 0; i < 1024; i++)
		sum = crc32(sum, (void *)BUF, SZ_16K);
	done("crc_l1", (u64)1024 * SZ_16K, "MB/s");

	start();
	memset((void *)BUF, 0xa5, SZ_64M);
	done("mem_write", SZ_64M, "MB/s");

	start();
	for (p = (u32 *)BUF; p < (u32 *)(BUF + SZ_64M); p += 8)
		sum += p[0] + p[1] + p[2] + p[3] + p[4] + p[5] + p[6] + p[7];
	done("mem_read", SZ_64M, "MB/s");

	start();
	memcpy((void *)(BUF + SZ_64M), (void *)BUF, SZ_32M);
	done("memcpy", SZ_32M, "MB/s");

	printf("bench dline %u.000 B\n", 2 << ((read_c0_config1() >> 10) & 7));
	printf("cp0 config %08x config1 %08x config2 %08x config3 %08x config7 %08x\n",
	       read_c0_config(), read_c0_config1(), read_c0_config2(), read_c0_config3(),
	       read_c0_config7());

	start();	/* PrepareForStore: line allocated without a fill read */
	for (p = (u32 *)BUF; p < (u32 *)(BUF + SZ_64M); p += 8) {
		__asm__ __volatile__("pref 30, 0(%0)" : : "r"(p));
		p[0] = p[1] = p[2] = p[3] = p[4] = p[5] = p[6] = p[7] = 0x3c3c3c3c;
	}
	done("mem_write_pfs", SZ_64M, "MB/s");

	start();
	for (p = (u32 *)BUF_UC; p < (u32 *)(BUF_UC + SZ_16M); p += 8)
		p[0] = p[1] = p[2] = p[3] = p[4] = p[5] = p[6] = p[7] = 0x5a5a5a5a;
	done("mem_write_uc", SZ_16M, "MB/s");

	start();	/* prefetch 4 lines ahead: overlapping misses, if the core allows */
	for (p = (u32 *)BUF; p < (u32 *)(BUF + SZ_64M); p += 8) {
		__asm__ __volatile__("pref 0, 128(%0)" : : "r"(p));
		sum += p[0] + p[1] + p[2] + p[3] + p[4] + p[5] + p[6] + p[7];
	}
	done("mem_read_pf", SZ_64M, "MB/s");

	chain_build(BUF);
	flush_dcache_range(BUF, BUF + CHAIN_N * CHAIN_STRIDE);
	start();
	sum += chain_walk((u32 *)BUF, 1000000);
	done_ns("lat_c", 1000000);

	chain_build(BUF_UC);
	start();
	sum += chain_walk((u32 *)BUF_UC, 200000);
	done_ns("lat_uc", 200000);

	start();
	for (p = (u32 *)BUF_UC; p < (u32 *)(BUF_UC + SZ_16M); p += 8)
		sum += p[0] + p[1] + p[2] + p[3] + p[4] + p[5] + p[6] + p[7];
	done("mem_read_uc", SZ_16M, "MB/s");

	start();
	for (p = (u32 *)FLASH_UC; p < (u32 *)(FLASH_UC + SZ_4M); p += 8)
		sum += p[0] + p[1] + p[2] + p[3] + p[4] + p[5] + p[6] + p[7];
	done("flash_uc", SZ_4M, "MB/s");

	start();
	for (p = (u32 *)FLASH_C; p < (u32 *)(FLASH_C + SZ_4M); p += 8)
		sum += p[0] + p[1] + p[2] + p[3] + p[4] + p[5] + p[6] + p[7];
	done("flash_c", SZ_4M, "MB/s");

	sink = sum;
	(void)sink;
	return 0;
}

U_BOOT_CMD(bench, 2, 0, do_bench, "CPU / cache / DRAM / flash throughput",
	   "\n  one line per test: bench <name> <value> <unit>; scripts/bench.py compares runs\n"
	   "bench div64 - u64 divide/modulo self-check (libgcc helpers)");
