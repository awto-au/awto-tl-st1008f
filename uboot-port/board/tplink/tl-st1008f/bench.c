// SPDX-License-Identifier: GPL-2.0+
/*
 * `bench`: CPU, cache, DRAM and flash throughput, one line per test: `bench <name> <value> <unit>`.
 * Compared across clock settings by scripts/bench.py (docs/CLOCKS.md). Timed with CP0 ticks.
 */

#include <command.h>
#include <div64.h>
#include <time.h>
#include <u-boot/crc.h>
#include <vsprintf.h>
#include <asm/io.h>
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

	do_div(per_s, ticks ? (u32)ticks : 1);	/* do_div: no __udivdi3 (#33); runs < 8.6 s */
	do_div(per_s, 1000);			/* thousandths of a mega-unit */
	milli = (u32)per_s;

	printf("bench %s %u.%03u %s\n", name, milli / 1000, milli % 1000, unit);
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

static int do_bench(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	volatile u32 sink;
	u32 i, sum = 0;
	u32 *p;

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

U_BOOT_CMD(bench, 1, 0, do_bench, "CPU / cache / DRAM / flash throughput",
	   "\n  one line per test: bench <name> <value> <unit>; scripts/bench.py compares runs");
