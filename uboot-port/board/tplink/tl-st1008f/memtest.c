// SPDX-License-Identifier: GPL-2.0+
/*
 * `memtest`: DRAM pattern test with an error map (#48 #103). One pass per pattern over low DRAM
 * (minus U-Boot) and the high bank, cached and uncached. Per failing word: address, want, got,
 * XOR and a re-read (re-read == got: stored wrong; else a read error). Host summary: scripts/memtest.py
 */

#include <command.h>
#include <console.h>
#include <cpu_func.h>
#include <time.h>
#include <vsprintf.h>
#include <asm/global_data.h>
#include <asm/io.h>
#include <linux/sizes.h>

DECLARE_GLOBAL_DATA_PTR;

u32 highmem_map_both(void);

#define LOW_START	SZ_64K		/* skip the exception-vector page */
#define REC_PAGE	0x0e000000	/* bootsel record (Linux reserves it too): skipped */
#define UBOOT_GAP	SZ_1M		/* stack below gd->start_addr_sp, then U-Boot to 256 MiB */
#define LINE		32

enum { T_ADDR, T_WALK1, T_WALK0, T_CHECK, T_ICHECK, T_RAND, T_N };
static const char *const tname[T_N] = { "addr", "walk1", "walk0", "check", "icheck", "rand" };

struct region {
	const char *name;
	u32 pa;			/* DRAM offset of va_uc/va_c */
	ulong va_uc, va_c;
	u32 size;
};

struct stats {
	u32 errs, sticky, logged;
	u32 bit[32], bank[8], rowb[16], colb[8];
	u32 xor_or, first, last;
};

static u32 maxlog = 16, seed = 0x1008f;

static inline u32 pat(int t, u32 pa, u32 *rs)
{
	u32 i = pa >> 2, x;

	switch (t) {
	case T_ADDR:	return pa;
	case T_WALK1:	return 1u << (i & 31);
	case T_WALK0:	return ~(1u << (i & 31));
	case T_CHECK:	return i & 1 ? 0xaaaaaaaa : 0x55555555;
	case T_ICHECK:	return i & 1 ? 0x55555555 : 0xaaaaaaaa;
	default:	/* xorshift32 */
		x = *rs;
		x ^= x << 13;
		x ^= x >> 17;
		x ^= x << 5;
		return *rs = x;
	}
}

/* assumed x16 decode (DCR 8 banks, 15 row, 10 col): col = pa[10:1], bank = pa[13:11], row = pa[28:14] */
static void note(struct stats *s, const struct region *r, const char *mode, int t, u32 pa,
		 u32 want, u32 got, u32 again)
{
	u32 x = want ^ got, m;

	s->errs++;
	s->sticky += again == got;
	s->xor_or |= x;
	for (m = x; m; m &= m - 1)
		s->bit[__builtin_ctz(m)]++;
	s->bank[(pa >> 11) & 7]++;
	s->rowb[(pa >> 25) & 15]++;
	s->colb[(pa >> 8) & 7]++;
	if (s->errs == 1)
		s->first = pa;
	s->last = pa;
	if (s->logged++ < maxlog)
		printf("memtest: E %s %s %s pa %08x want %08x got %08x xor %08x reread %08x\n",
		       r->name, mode, tname[t], pa, want, got, x, again);
}

static void counts(const char *what, const u32 *c, int n)
{
	int i;

	printf("memtest: %s", what);
	for (i = 0; i < n; i++)
		printf(" %u", c[i]);
	putc('\n');
}

/* one pattern, one mapping: write all, (flush), read all. Returns -1 on Ctrl-C */
static int run(const struct region *r, bool cached, int t, struct stats *tot)
{
	ulong va = cached ? r->va_c : r->va_uc, off;
	const char *mode = cached ? "cached" : "uncached";
	struct stats s = { 0 };
	u32 rs = seed ^ r->pa ^ (t << 24), start = get_timer(0);

	for (off = 0; off < r->size; off += 4) {
		if (r->pa + off == REC_PAGE) {
			off += SZ_4K - 4;
			continue;
		}
		__raw_writel(pat(t, r->pa + off, &rs), (void __iomem *)(va + off));
		if (!(off & (SZ_16M - 1)) && (get_timer(0), ctrlc()))	/* get_timer: count wrap tracking */
			return -1;
	}
	if (cached)
		flush_dcache_range(va, va + r->size);	/* write back + invalidate: reads come from DRAM */
	rs = seed ^ r->pa ^ (t << 24);
	for (off = 0; off < r->size; off += 4) {
		u32 pa = r->pa + off, want, got, again;

		if (pa == REC_PAGE) {
			off += SZ_4K - 4;
			continue;
		}
		if (!(off & (SZ_16M - 1)))
			get_timer(0);
		want = pat(t, pa, &rs);
		got = __raw_readl((void __iomem *)(va + off));
		if (got == want)
			continue;
		if (cached)
			invalidate_dcache_range((va + off) & ~(LINE - 1), ((va + off) & ~(LINE - 1)) + LINE);
		again = __raw_readl((void __iomem *)(va + off));
		note(&s, r, mode, t, pa, want, got, again);
	}
	printf("memtest: S %s %s %s %u MiB %lu ms errs %u sticky %u xor %08x first %08x last %08x\n",
	       r->name, mode, tname[t], r->size >> 20, get_timer(start), s.errs, s.sticky, s.xor_or,
	       s.first, s.last);
	if (s.errs) {
		counts("bits31..0", s.bit, 32);	/* printed bit 0 first; host reorders */
		counts("bank", s.bank, 8);
		counts("row/2048", s.rowb, 16);
		counts("col/128", s.colb, 8);
	}
	tot->errs += s.errs;
	return 0;
}

static int do_memtest(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	struct region reg[2];
	struct stats tot = { 0 };
	u32 low_end = (gd->start_addr_sp - UBOOT_GAP) & ~(SZ_1M - 1) & 0x1fffffff, hs;
	int n = 0, i, t, c, which = 3, modes = 3, start = get_timer(0);
	bool quick = false;

	for (i = 1; i < argc; i++) {
		if (!strcmp(argv[i], "low"))
			which = 1;
		else if (!strcmp(argv[i], "high"))
			which = 2;
		else if (!strcmp(argv[i], "cached"))
			modes = 2;
		else if (!strcmp(argv[i], "uncached"))
			modes = 1;
		else if (!strncmp(argv[i], "log=", 4))
			maxlog = dectoul(argv[i] + 4, NULL);
		else if (!strncmp(argv[i], "seed=", 5))
			seed = hextoul(argv[i] + 5, NULL);
		else if (!strncmp(argv[i], "mib=", 4))	/* quick runs: first N MiB of each region */
			hs = dectoul(argv[i] + 4, NULL) << 20, low_end = min(low_end, LOW_START + hs), quick = true;
		else
			return CMD_RET_USAGE;
	}
	if (which & 1)
		reg[n++] = (struct region){ "low", LOW_START, KSEG1ADDR(LOW_START), KSEG0ADDR(LOW_START),
					    low_end - LOW_START };
	if (which & 2) {
		hs = highmem_map_both();
		if (!hs) {
			puts("memtest: high bank not mappable\n");
			return CMD_RET_FAILURE;
		}
		if (quick)	/* mib= also bounds the high bank */
			hs = min(hs, low_end - LOW_START);
		reg[n++] = (struct region){ "high", SZ_256M, 0xc0000000, 0xd0000000, hs };
	}
	printf("memtest: low %08x..%08x (U-Boot from %08x), high %s, seed %08x\n", LOW_START, low_end,
	       (u32)gd->start_addr_sp & 0x1fffffff, which & 2 ? "256 MiB" : "skipped", seed);
	for (i = 0; i < n; i++)
		for (c = 0; c < 2; c++) {
			if (!(modes & (1 << c)))
				continue;
			for (t = 0; t < T_N; t++)
				if (run(&reg[i], c, t, &tot) < 0) {
					puts("memtest: interrupted\n");
					return CMD_RET_FAILURE;
				}
		}
	printf("memtest: done %u errors, %lu ms\n", tot.errs, get_timer(start));
	return tot.errs ? CMD_RET_FAILURE : 0;
}

U_BOOT_CMD(memtest, 6, 0, do_memtest, "DRAM pattern test with error map (#48 #103)",
	   "[low|high] [cached|uncached] [log=N] [seed=HEX] [mib=N]\n"
	   "  patterns addr, walk1, walk0, check, icheck, rand; one pass each; default all regions, both modes");
