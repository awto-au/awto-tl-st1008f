// SPDX-License-Identifier: GPL-2.0+
/*
 * Copyright (c) 2014  TP-LINK Co., Ltd  (TP-LINK Co., Ltd R&D SMB Product Line)
 * `dt`: DRAM data/address-bus, fade, crosstalk and mtest-style tests, ported from the SDK U-Boot
 * 2011.12 dt_bus.c, dt_verify.c, dt_xtalk.c, dt_mtest.c (owner decision 2026-11-07, docs/DECISIONS.md).
 * Mainline port: uncached KSEG1 access, bounded runtime, scratch-range guard. Docs: docs/DRAM.md#dt-tests
 */

#include <command.h>
#include <console.h>
#include <time.h>
#include <vsprintf.h>
#include <asm/global_data.h>
#include <asm/io.h>
#include <linux/sizes.h>
#include <linux/delay.h>
#include <linux/log2.h>
#include <linux/kernel.h>
#include "dt_patterns.h"

DECLARE_GLOBAL_DATA_PTR;

#define DEF_START	0x08000000	/* above bench's 0x82000000..0x88000000 window */
#define LOW_MIN		0x02000000	/* below: vectors, kernel 0x80100000, TEXT_BASE, init stack */
#define LOAD_START	0x04f00000	/* ramload/TFTP window 0x84f00000 + 32 MiB (FASTBOOT_BUF_SIZE) */
#define LOAD_END	0x06f00000
#define REC_PAGE	0x0e000000	/* bootsel record, as memtest */
#define MAXLOG		16
#define WALK_WIN	SZ_256K		/* rotating-walk passes cover this much (96 fills) */

struct dt {
	const char *name, *what;	/* test; what is being waited for (timeout message) */
	ulong va;			/* KSEG1 address of the range start */
	u32 pa, len, t0, limit, errs, logged;
	bool abort;
};

static struct dt d;

static inline u32 rd(u32 off)
{
	return __raw_readl((void __iomem *)(d.va + off));
}

static inline void wr(u32 off, u32 v)
{
	__raw_writel(v, (void __iomem *)(d.va + off));
}

static inline u32 rotl(u32 x, int r)
{
	return r ? x << r | x >> (32 - r) : x;
}

/* every 4096 words: Ctrl-C, and the per-test runtime bound; true = stop */
static bool tick(u32 i)
{
	u32 el;

	if (d.abort)
		return true;
	if (i & 0xfff)
		return false;
	if (ctrlc()) {
		d.abort = true;
		printf("dt: %s interrupted\n", d.name);
		return true;
	}
	el = get_timer(d.t0);
	if (el > d.limit) {
		d.abort = true;
		printf("dt: TIMEOUT %s waiting for %s, limit %u ms, elapsed %u ms\n", d.name, d.what,
		       d.limit, el);
		return true;
	}
	return false;
}

static void err(const char *what, u32 pa, u32 want, u32 got)
{
	d.errs++;
	if (d.logged++ < MAXLOG)
		printf("dt: E %s %s pa %08x want %08x got %08x xor %08x\n", d.name, what, pa, want, got,
		       want ^ got);
}

/* word pattern for mode 1: alternating p/~p, second half complemented (dt_bus.c walk fill + p1 == ~p2 check) */
static u32 val(u32 i, u32 words, u32 p, int mode)
{
	u32 x = p;

	if (mode) {
		x = i & 1 ? ~p : p;
		if (i >= words / 2)
			x = ~x;
	}
	return x;
}

/* fill, then read back and compare */
static void pass(u32 off, u32 words, u32 p, int mode)
{
	u32 i, got, want;

	d.what = "fill";
	for (i = 0; i < words; i++) {
		if (tick(i))
			return;
		wr(off + 4 * i, val(i, words, p, mode));
	}
	d.what = "readback";
	for (i = 0; i < words; i++) {
		if (tick(i))
			return;
		want = val(i, words, p, mode);
		got = rd(off + 4 * i);
		if (got != want)
			err("data", d.pa + off + 4 * i, want, got);
	}
}

static void summary(const char *what, u32 e0, u32 t)
{
	if (d.abort)
		return;
	printf("dt: S %s %s pa %08x %u KiB errs %u %lu ms\n", d.name, what, d.pa, d.len >> 10,
	       d.errs - e0, get_timer(t));
}

static void t_databus(u32 n)
{
	u32 b, i, m, r, e0, t, win = min_t(u32, d.len, WALK_WIN);

	for (b = 0; b < n && !d.abort; b++) {
		for (i = 0; i < ARRAY_SIZE(dt_databus_pat) && !d.abort; i++) {
			char s[16];

			e0 = d.errs;
			t = get_timer(0);
			pass(0, d.len / 4, dt_databus_pat[i], 0);
			snprintf(s, sizeof(s), "pat %08x", dt_databus_pat[i]);
			summary(s, e0, t);
		}
		for (m = 0; m < ARRAY_SIZE(dt_walk_mask) && !d.abort; m++) {
			char s[16];

			e0 = d.errs;
			t = get_timer(0);
			for (r = 0; r < 32 && !d.abort; r++)
				pass(0, win / 4, rotl(dt_walk_mask[m], r), 1);
			snprintf(s, sizeof(s), "walk %x", dt_walk_mask[m]);
			summary(s, e0, t);
		}
	}
}

static void t_addrbus(u32 n)
{
	u32 b, i, off, toff, nw = d.len / 4, mask, anti, e0, t, tmp;

	for (b = 0; b < n && !d.abort; b++) {
		e0 = d.errs;
		t = get_timer(0);
		for (i = 0; i < ARRAY_SIZE(dt_pat20) && !d.abort; i++) {
			mask = dt_pat20[i];
			anti = ~mask;
			d.what = "address walk";
			for (off = 1; off < nw; off <<= 1)
				wr(4 * off, mask);
			wr(0, anti);		/* stuck high: offset 0 must not alias any bit */
			for (off = 1; off < nw; off <<= 1) {
				tmp = rd(4 * off);
				if (tmp != mask)
					err("addr stuck high", d.pa + 4 * off, mask, tmp);
			}
			wr(0, mask);
			for (toff = 1; toff < nw; toff <<= 1) {	/* stuck low or shorted */
				wr(4 * toff, anti);
				for (off = 1; off < nw; off <<= 1) {
					tmp = rd(4 * off);
					if (tmp != mask && off != toff)
						err("addr stuck low/short", d.pa + 4 * off, mask, tmp);
				}
				wr(4 * toff, mask);
			}
			if (tick(0))
				break;
		}
		summary("addr walk", e0, t);
	}
}

/* dt_xtalk.c data line: victim bit held while every other line toggles on alternate words */
static void xtalk_data(u32 level)
{
	u32 bit, i, w = d.len / 4, main, help, e0 = d.errs, t = get_timer(0), got, want;

	for (bit = 0; bit < 32 && !d.abort; bit++) {
		main = level ? 1u << bit : ~(1u << bit);
		help = level ? 0xffffffff : 0;
		d.what = "crosstalk fill";
		for (i = 0; i < w; i++) {
			if (tick(i))
				return;
			wr(4 * i, i & 1 ? help : main);
		}
		d.what = "crosstalk readback";
		for (i = 0; i < w; i++) {
			if (tick(i))
				return;
			want = i & 1 ? help : main;
			got = rd(4 * i);
			if (got != want)
				err("xtalk data", d.pa + 4 * i, want, got);
		}
	}
	summary(level ? "data lvl1" : "data lvl0", e0, t);
}

/* dt_xtalk.c address line: two bytes whose addresses differ in every bit but one, written alternately */
static void xtalk_addr(u32 level)
{
	u32 plen = 1u << ilog2(d.len), bit, k, o1, o2, e0 = d.errs, t = get_timer(0);
	u8 v1, v2, g1, g2;

	d.what = "address crosstalk";
	for (bit = 0; bit < ilog2(plen) && !d.abort; bit++) {
		o1 = level ? 1u << bit : ~(1u << bit) & (plen - 1);
		o2 = level ? plen - 1 : 0;
		if (o1 == o2)
			continue;
		for (k = 0; k < 64; k++) {
			v1 = k & 1 ? 0xaa : 0x55;
			v2 = ~v1;
			__raw_writeb(v1, (void __iomem *)(d.va + o1));
			__raw_writeb(v2, (void __iomem *)(d.va + o2));
			g1 = __raw_readb((void __iomem *)(d.va + o1));
			g2 = __raw_readb((void __iomem *)(d.va + o2));
			if (g1 != v1)
				err("xtalk addr", d.pa + o1, v1, g1);
			if (g2 != v2)
				err("xtalk addr", d.pa + o2, v2, g2);
		}
		if (tick(0))
			return;
	}
	summary(level ? "addr lvl1" : "addr lvl0", e0, t);
}

static void t_xtalk(u32 n)
{
	u32 b;

	for (b = 0; b < n && !d.abort; b++) {
		xtalk_data(0);
		xtalk_data(1);
		xtalk_addr(0);
		xtalk_addr(1);
	}
}

/* dt_mtest.c dram_mtest_quick: incrementing/decrementing sequence from a pattern */
static void mtest_quick(u32 pattern, u32 iter)
{
	u32 i, w = d.len / 4, v, incr = 1, got, e0 = d.errs, t = get_timer(0);
	char s[24];

	if (iter & 1) {
		incr = -1;
		pattern = pattern & 0x80000000 ? -pattern : ~pattern;
	}
	d.what = "mtest fill";
	for (i = 0, v = pattern; i < w; i++, v += incr) {
		if (tick(i))
			return;
		wr(4 * i, v);
	}
	d.what = "mtest readback";
	for (i = 0, v = pattern; i < w; i++, v += incr) {
		if (tick(i))
			return;
		got = rd(4 * i);
		if (got != v)
			err("mtest", d.pa + 4 * i, v, got);
	}
	snprintf(s, sizeof(s), "quick %08x", pattern);
	summary(s, e0, t);
}

/* dt_mtest.c dram_mtest_alt: data line, address line (Barr), integrity; parking word = last word */
static void mtest_alt(void)
{
	u32 nw = d.len / 4 - 1, park = 4 * nw, i, v, off, toff, tmp, got, e0 = d.errs, t = get_timer(0);
	const u32 mask = 0xaaaaaaaa, anti = 0x55555555;

	d.what = "mtest data line";
	for (i = 0; i < ARRAY_SIZE(dt_bitpat); i++)
		for (v = dt_bitpat[i]; v; v <<= 1) {
			wr(0, v);
			wr(park, ~v);	/* change the bus state so a floating bus does not read back OK */
			got = rd(0);
			if (got != v)
				err("mtest dataline", d.pa, v, got);
			wr(0, ~v);
			wr(park, v);
			got = rd(0);
			if (got != ~v)
				err("mtest dataline", d.pa, ~v, got);
		}
	d.what = "mtest address line";
	for (off = 1; off < nw; off <<= 1)
		wr(4 * off, mask);
	wr(0, anti);
	for (off = 1; off < nw; off <<= 1) {
		tmp = rd(4 * off);
		if (tmp != mask)
			err("mtest addr high", d.pa + 4 * off, mask, tmp);
	}
	wr(0, mask);
	for (toff = 1; toff < nw; toff <<= 1) {
		wr(4 * toff, anti);
		for (off = 1; off < nw; off <<= 1) {
			tmp = rd(4 * off);
			if (tmp != mask && off != toff)
				err("mtest addr low/short", d.pa + 4 * off, mask, tmp);
		}
		wr(4 * toff, mask);
	}
	d.what = "mtest integrity fill";
	for (i = 0; i <= nw; i++) {
		if (tick(i))
			return;
		wr(4 * i, i + 1);
	}
	d.what = "mtest integrity invert";
	for (i = 0; i <= nw; i++) {
		if (tick(i))
			return;
		tmp = rd(4 * i);
		if (tmp != i + 1)
			err("mtest integrity", d.pa + 4 * i, i + 1, tmp);
		wr(4 * i, ~(i + 1));
	}
	d.what = "mtest integrity check";
	for (i = 0; i <= nw; i++) {
		if (tick(i))
			return;
		tmp = rd(4 * i);
		if (tmp != ~(i + 1))
			err("mtest integrity", d.pa + 4 * i, ~(i + 1), tmp);
	}
	summary("alt", e0, t);
}

static void t_mtest(u32 n)
{
	u32 b, j;

	for (b = 0; b < n && !d.abort; b++) {
		for (j = 0; j < ARRAY_SIZE(dt_pat20) && !d.abort; j++)
			mtest_quick(dt_pat20[j], b);
		if (!d.abort)
			mtest_alt();
	}
}

/* dt_verify.c fade: fill, wait with no accesses, read back; ones then zeros (n = rounds, ms = wait) */
static u32 fade_ms = 1000;

static void t_fade(u32 n)
{
	static const u32 pat[2] = { 0xffffffff, 0 };
	u32 b, k, i, w = d.len / 4, got, e0, t, w0;

	for (b = 0; b < n && !d.abort; b++)
		for (k = 0; k < 2 && !d.abort; k++) {
			e0 = d.errs;
			t = get_timer(0);
			d.what = "fade fill";
			for (i = 0; i < w; i++) {
				if (tick(i))
					return;
				wr(4 * i, pat[k]);
			}
			d.what = "retention delay";
			for (w0 = get_timer(0); get_timer(w0) < fade_ms;) {
				if (tick(0))
					return;
				udelay(1000);	/* 1 ms poll granularity for the Ctrl-C/limit check */
			}
			d.what = "fade readback";
			for (i = 0; i < w; i++) {
				if (tick(i))
					return;
				got = rd(4 * i);
				if (got != pat[k])
					err("fade", d.pa + 4 * i, pat[k], got);
			}
			summary(k ? "zeros" : "ones", e0, t);
		}
}

struct dtest {
	const char *name;
	void (*fn)(u32 n);
	u32 len, n;		/* default length, default bursts */
	u32 base_ms, mib_ms;	/* runtime limit = (base_ms + mib_ms * MiB) * n; fade adds 2 * ms * n */
};

/*
 * Limit = 1.25x estimate from docs/DRAM.md bench (uncached store 430 MB/s, read 60 MB/s = ~22 ms per
 * MiB fill+readback): databus 8 fixed + 96 walk passes, mtest 20 patterns + alt, xtalk 64 fills.
 * Not yet measured with dt itself: `max=` overrides, expiry prints the limit and elapsed time.
 */
static const struct dtest tests[] = {
	{ "databus", t_databus, SZ_1M, 1, 800, 200 },
	{ "addrbus", t_addrbus, SZ_64M, 1, 500, 0 },
	{ "fade", t_fade, SZ_1M, 1, 400, 100 },
	{ "xtalk", t_xtalk, SZ_256K, 1, 300, 1500 },
	{ "mtest", t_mtest, SZ_1M, 2, 300, 700 },
};

static bool range_ok(u32 pa, u32 len)
{
	u32 top = (gd->start_addr_sp - SZ_1M) & ~(SZ_1M - 1) & 0x1fffffff;

	if (len < SZ_4K || (pa | len) & 3 || pa < LOW_MIN || pa + len < pa || pa + len > top) {
		printf("dt: range %08x+%x refused: need 4 KiB.. within %08x..%08x (U-Boot from %08x)\n", pa, len,
		       LOW_MIN, top, (u32)gd->start_addr_sp & 0x1fffffff);
		return false;
	}
	if (pa < LOAD_END && pa + len > LOAD_START) {
		printf("dt: range %08x+%x refused: overlaps ramload window %08x..%08x\n", pa, len, LOAD_START,
		       LOAD_END);
		return false;
	}
	if (pa < REC_PAGE + SZ_4K && pa + len > REC_PAGE) {
		printf("dt: range %08x+%x refused: overlaps bootsel record %08x\n", pa, len, REC_PAGE);
		return false;
	}
	return true;
}

static int run_test(const struct dtest *t, u32 pa, u32 len, u32 n, u32 max_ms)
{
	u32 mib = DIV_ROUND_UP(len, SZ_1M);

	if (!range_ok(pa, len))
		return CMD_RET_FAILURE;
	memset(&d, 0, sizeof(d));
	d.name = t->name;
	d.pa = pa;
	d.len = len;
	d.va = KSEG1ADDR(pa);
	d.limit = max_ms ?: (t->base_ms + t->mib_ms * mib + (t->fn == t_fade ? 2 * fade_ms : 0)) * n;
	printf("dt: %s pa %08x..%08x (%u KiB) n %u limit %u ms\n", t->name, pa, pa + len, len >> 10, n,
	       d.limit);
	d.t0 = get_timer(0);
	t->fn(n);
	printf("dt: done %s %u errors, %lu ms%s\n", t->name, d.errs, get_timer(d.t0),
	       d.abort ? " (aborted)" : "");
	return d.errs || d.abort ? CMD_RET_FAILURE : 0;
}

static int do_dt(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	const struct dtest *t = NULL;
	u32 pa = DEF_START, len = 0, n = 0, max_ms = 0, pos = 0;
	bool all;
	int i, rc = 0;

	if (argc < 2)
		return CMD_RET_USAGE;
	all = !strcmp(argv[1], "all");
	for (i = 0; i < ARRAY_SIZE(tests); i++)
		if (!strcmp(argv[1], tests[i].name))
			t = &tests[i];
	if (!t && !all)
		return CMD_RET_USAGE;
	fade_ms = 1000;
	for (i = 2; i < argc; i++) {
		if (!strncmp(argv[i], "n=", 2))
			n = dectoul(argv[i] + 2, NULL);
		else if (!strncmp(argv[i], "ms=", 3))
			fade_ms = dectoul(argv[i] + 3, NULL);
		else if (!strncmp(argv[i], "max=", 4))
			max_ms = dectoul(argv[i] + 4, NULL);
		else if (!all && pos == 0 && ++pos)
			pa = hextoul(argv[i], NULL) & 0x1fffffff;	/* KSEG0/1 address or DRAM offset */
		else if (!all && pos == 1 && ++pos)
			len = hextoul(argv[i], NULL);
		else
			return CMD_RET_USAGE;
	}
	if (fade_ms > 60000) {
		puts("dt: ms= above 60000 refused (fade wait limit)\n");
		return CMD_RET_FAILURE;
	}
	if (!all)
		return run_test(t, pa, len ?: t->len, n ?: t->n, max_ms);
	for (i = 0; i < ARRAY_SIZE(tests); i++)
		if (run_test(&tests[i], DEF_START, tests[i].len, n ?: tests[i].n, max_ms))
			rc = CMD_RET_FAILURE;
	printf("dt: all %s\n", rc ? "FAIL" : "pass");
	return rc;
}

U_BOOT_CMD(dt, 7, 0, do_dt, "DRAM bus/fade/crosstalk/pattern tests (SDK dt_*, #151)",
	   "databus|addrbus|fade|xtalk|mtest [START [LEN]] [n=N] [ms=N] [max=MS]\n"
	   "dt all [n=N] [ms=N] [max=MS]\n"
	   "  START/LEN hex, default 08000000 (DRAM offset or KSEG address), uncached; refuses < 02000000,\n"
	   "  the ramload window 04f00000..06f00000, the bootsel page 0e000000 and U-Boot's own top;\n"
	   "  n = bursts, ms = fade wait (default 1000, max 60000), max = runtime limit in ms (default per test)");
