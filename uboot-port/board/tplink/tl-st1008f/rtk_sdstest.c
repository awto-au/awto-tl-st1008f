// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk sds`: SerDes test tools (#74). Sequences from Realtek SDK dal_longan_sds.c (GPL-2.0):
 * symErr_get, linkSts_get, 10gRxIdle_get, testMode_set, loopback_set (SDK 3.8), eyeParam_get/set,
 * eyeMonitor_start. Registers + measured results: docs/SDS-TOOLS.md.
 * Test modes save the registers they touch and restore them on exit and on Ctrl-C.
 */

#include <command.h>
#include <console.h>
#include <time.h>
#include <vsprintf.h>
#include <linux/delay.h>
#include "rtk.h"

#define MAC_LINK_STS	0xcb10		/* bit per SDK port, latched low */
#define MODE_10GR	0x1a
#define EYE_N		64		/* SDK RTK_EYE_MON_X_MAX / Y_MAX */
#define BITS_PER_MS	10312500ULL	/* 10GBASE-R line rate */
/* PRBS sample period: the 16-bit checker counter saturates at 0xffff (802.3 3.43); 100 ms keeps a
 * dark-RX run countable. Ctrl-C is polled every 10 ms. */
#define PRBS_SAMPLE_MS	100
#define PRBS_MAX_MS	600000		/* 10 min cap on one run */

static int io_err;

/* logical id: SerDes 3 pages 0-3 live in SerDes 10 (drv_rtl9300_sds2XsgmSds_get) */
static unsigned int lsds(unsigned int sds, unsigned int page)
{
	return sds == 3 && page < 4 ? 10 : sds;
}

static u16 rd(unsigned int sds, unsigned int page, unsigned int reg)
{
	u16 v = 0;

	if (rtk_sds_read(lsds(sds, page), page, reg, &v))
		io_err++;
	return v;
}

static void wr(unsigned int sds, unsigned int page, unsigned int reg, u16 v)
{
	if (rtk_sds_write(lsds(sds, page), page, reg, v))
		io_err++;
}

static u16 fr(unsigned int sds, unsigned int page, unsigned int reg, int hi, int lo)
{
	return (rd(sds, page, reg) & GENMASK(hi, lo)) >> lo;
}

static void fw(unsigned int sds, unsigned int page, unsigned int reg, int hi, int lo, u16 v)
{
	u16 m = GENMASK(hi, lo);

	wr(sds, page, reg, (rd(sds, page, reg) & ~m) | ((v << lo) & m));
}

/* ---- target parsing: `3` = cage 3, `s4` = SerDes 4 ---- */

static int parse_sds(const char *s)
{
	unsigned long n;

	if (*s == 's') {
		n = dectoul(s + 1, NULL);
		return n >= 2 && n <= 9 ? (int)n : -1;
	}
	n = dectoul(s, NULL);
	return n >= 1 && n <= NCAGES ? rtk_cage_sds(n) : -1;
}

static int sds_cage(int sds)
{
	return sds - 1;
}

static bool mac_link(int sds)
{
	int port = rtk_cage_port[sds_cage(sds) - 1];

	sw_r(MAC_LINK_STS);
	return sw_r(MAC_LINK_STS) & BIT(port);
}

/* 10GR PCS receive link (5/0 bit 12 = 3.32.12, read twice: latched low) */
static bool pcs_link(int sds)
{
	fr(sds, 5, 0, 12, 12);
	return fr(sds, 5, 0, 12, 12);
}

/* debug-out 0x35 on the even SerDes of the pair: 0x1f/0x14 bit 0/1 = RX idle, bit 4/5 = CMU ready */
static void dbg35(int sds, bool *idle, bool *cmu)
{
	int l0 = sds & ~1, odd = sds & 1;
	u16 v;

	wr(l0, 0x1f, 2, 0x35);
	v = rd(l0, 0x1f, 0x14);
	*idle = v & BIT(odd);
	*cmu = v & BIT(4 + odd);
}

static const char *mode_name(int m)
{
	switch (m) {
	case 0x02: return "SGMII";
	case 0x04: return "1000BASE-X";
	case 0x05: return "100BASE-X";
	case 0x16: return "2500BASE-X";
	case 0x12: return "HISGMII";
	case 0x1a: return "10GBASE-R";
	case 0x1f: return "off";
	default: return "?";
	}
}

static bool link_guard(int sds, bool force, const char *what)
{
	bool up = mac_link(sds) || (rtk_sds_mode(sds) == MODE_10GR && pcs_link(sds));

	if (up && !force) {
		printf("refused: cage %d link is up; %s drops it (add `force`)\n", sds_cage(sds), what);
		return false;
	}
	if (up)
		printf("cage %d: link up, forced: link drops during %s\n", sds_cage(sds), what);
	return true;
}

/* ---- status / error counters ---- */

struct symerr { u16 blk_lock, hiber, ber, blk_err; u32 ch0; bool tenG; };

/* symErr_get: 10GR 5/1 = 3.33 (clear on read); 1000BX ch0 = 1/3[15:8] << 16 | 1/2 */
static void symerr_read(int sds, struct symerr *e)
{
	u16 v;

	memset(e, 0, sizeof(*e));
	e->tenG = rtk_sds_mode(sds) == MODE_10GR;
	if (e->tenG) {
		v = rd(sds, 5, 1);
		e->blk_lock = v >> 15 & 1;
		e->hiber = v >> 14 & 1;
		e->ber = v >> 8 & 0x3f;
		e->blk_err = v & 0xff;
	} else {
		fw(sds, 1, 24, 2, 0, 0);
		e->ch0 = (u32)fr(sds, 1, 3, 15, 8) << 16 | rd(sds, 1, 2);
	}
}

static void symerr_clear(int sds)
{
	struct symerr e;

	if (rtk_sds_mode(sds) == MODE_10GR) {
		symerr_read(sds, &e);	/* clear on read */
		return;
	}
	fw(sds, 1, 24, 2, 0, 0);
	fw(sds, 1, 3, 15, 8, 0);
	wr(sds, 1, 2, 0);
}

static void symerr_print(int sds, const struct symerr *e)
{
	if (e->tenG)
		printf("errcnt cage %d: blk_err %u ber %u latched: blk_lock %u hi_ber %u\n", sds_cage(sds),
		       e->blk_err, e->ber, e->blk_lock, e->hiber);
	else
		printf("errcnt cage %d: sym_err %u\n", sds_cage(sds), e->ch0);
}

static void status_one(int sds)
{
	int m = rtk_sds_mode(sds);
	bool idle, cmu;
	u16 tp = rd(sds, 5, 0xa);

	dbg35(sds, &idle, &cmu);
	printf("cage %d sds %d: mode %s (0x%02x), cmu %s, rx %s", sds_cage(sds), sds, mode_name(m), m,
	       cmu ? "ready" : "NOT-ready", idle ? "idle (no signal)" : "signal");
	if (m == MODE_10GR) {
		/* 4/1 bit 2 = 3.1.2 receive link, latched low: 0 = dropped since last read */
		printf(", pcs %s (latched %u)", pcs_link(sds) ? "up" : "down", fr(sds, 4, 1, 2, 2));
	} else if (m != 0x1f) {
		printf(", link 0x%03x (latched 0x%03x)", fr(sds, 1, 29, 8, 0), fr(sds, 1, 30, 8, 0));
	}
	printf(", mac %s, lb %s, prbs %s\n", mac_link(sds) ? "up" : "down",
	       fr(sds, 6, 1, 2, 2) ? "near" : "off",
	       tp & 0x00c0 ? "9" : tp & 0x0030 ? "31" : tp & 0x000a ? "square" : "off");
}

static int do_status(int argc, char *const argv[])
{
	int s;

	if (argc > 3 && strcmp(argv[3], "all")) {
		s = parse_sds(argv[3]);
		if (s < 0)
			return CMD_RET_USAGE;
		status_one(s);
		return 0;
	}
	for (s = 2; s <= 9; s++)
		status_one(s);
	return 0;
}

static int do_errcnt(int argc, char *const argv[])
{
	struct symerr e;
	int s, lo = 2, hi = 9;
	bool clr = argc > 4 && !strcmp(argv[4], "clear");

	if (argc > 3 && strcmp(argv[3], "all")) {
		lo = hi = parse_sds(argv[3]);
		if (lo < 0)
			return CMD_RET_USAGE;
	}
	for (s = lo; s <= hi; s++) {
		if (clr) {
			symerr_clear(s);
			printf("errcnt cage %d: cleared\n", sds_cage(s));
			continue;
		}
		symerr_read(s, &e);
		symerr_print(s, &e);
	}
	return 0;
}

/* ---- near-end (AFE) loopback: 6/1 bit 2 FP_TGR1_CFG_AFE_LPK (10GR), 0/0 bit 4 SP_CFG_DIG_LPK ---- */

static struct { bool on; u16 r6_1, r0_0; } lb_save[10];

/* FSM reset (6/2 bit 12) + RX reset (0x2e/0x15 bit 4): stock CMU check / SDK rx_rst order */
static void rx_resync(int sds)
{
	fw(sds, 6, 2, 12, 12, 1);
	mdelay(10);
	fw(sds, 6, 2, 12, 12, 0);
	fw(sds, 0x2e, 0x15, 4, 4, 1);
	mdelay(5);
	fw(sds, 0x2e, 0x15, 4, 4, 0);
	mdelay(10);
}

static void lb_near(int sds, bool on)
{
	if (on && !lb_save[sds].on) {
		lb_save[sds].r6_1 = rd(sds, 6, 1);
		lb_save[sds].r0_0 = rd(sds, 0, 0);
		lb_save[sds].on = true;
		fw(sds, 0, 0, 4, 4, 1);
		fw(sds, 6, 1, 2, 2, 1);
	} else if (!on && lb_save[sds].on) {
		fw(sds, 6, 1, 2, 2, lb_save[sds].r6_1 >> 2 & 1);
		fw(sds, 0, 0, 4, 4, lb_save[sds].r0_0 >> 4 & 1);
		lb_save[sds].on = false;
	} else {
		return;
	}
	rx_resync(sds);
}

static int do_loopback(int argc, char *const argv[])
{
	int s = argc > 4 ? parse_sds(argv[3]) : -1;
	bool force = argc > 5 && !strcmp(argv[5], "force");

	if (s < 0)
		return CMD_RET_USAGE;
	if (!strcmp(argv[4], "far")) {
		printf("refused: no far-end (remote) loopback control for RTL930x in SDK 3.7/3.8 or stock rtk.ko\n");
		return CMD_RET_FAILURE;
	}
	if (!strcmp(argv[4], "off")) {
		lb_near(s, false);
		printf("loopback cage %d: off (registers restored)\n", sds_cage(s));
		return 0;
	}
	if (strcmp(argv[4], "near"))
		return CMD_RET_USAGE;
	if (!lb_save[s].on && !link_guard(s, force, "loopback"))
		return CMD_RET_FAILURE;
	lb_near(s, true);
	printf("loopback cage %d: near (AFE TX->RX); `rtk sds loopback %d off` restores\n", sds_cage(s),
	       sds_cage(s));
	return 0;
}

/* ---- PRBS generator + checker (10GR PCS, 5/0xa = 3.42 test-pattern ctrl, 5/0xb = 3.43 errors) ---- */

struct prbs_save { u16 p5a, p60, p6e, p6f; };
/* 6/0xe, 6/0xf after `rtk network on` (all 10GR cages); SDK testDis_set writes 0 instead */
#define R6E_RESET	0x015a
#define R6F_RESET	0x5a5a
#define PAT_MISMATCH	1

static void prbs_set(int sds, int pat)
{
	if (!pat) {		/* _dal_longan_sds_testDis_set, but 6/0xe + 6/0xf back to reset values */
		fw(sds, 5, 0xa, 7, 4, 0);
		fw(sds, 5, 0xa, 3, 3, 0);
		fw(sds, 5, 0xa, 1, 1, 0);
		fw(sds, 6, 0, 14, 8, 0);
		fw(sds, 6, 0, 7, 4, 0);
		wr(sds, 6, 0xe, R6E_RESET);
		wr(sds, 6, 0xf, R6F_RESET);
		return;
	}
	fw(sds, 5, 0xa, 13, 4, 0);
	fw(sds, 5, 0xa, 1, 1, 0);
	if (pat == 9)
		fw(sds, 5, 0xa, 7, 6, 3);
	else if (pat == 31)
		fw(sds, 5, 0xa, 5, 4, 3);
	else			/* checker self-test: bits 7 + 4 = PRBS31 out, PRBS9 checked (saturates) */
		fw(sds, 5, 0xa, 7, 4, 9);
	fw(sds, 6, 0, 12, 8, 2);
	fw(sds, 6, 0, 14, 13, 3);
	fw(sds, 6, 0xe, 8, 0, 2);
	wr(sds, 6, 0xf, 2);
}

static int do_prbs(int argc, char *const argv[])
{
	int s = argc > 4 ? parse_sds(argv[3]) : -1, pat, i;
	ulong ms = 1000, t0, el, next;
	bool near = false, force = false, verbose = false, aborted = false;
	struct prbs_save sv;
	u32 total = 0, sat = 0, nz = 0, samples = 0;
	u16 c, first = 0;

	if (s < 0)
		return CMD_RET_USAGE;
	if (!strcmp(argv[4], "off")) {
		prbs_set(s, 0);
		printf("prbs cage %d: off\n", sds_cage(s));
		return 0;
	}
	pat = !strcmp(argv[4], "mismatch") ? PAT_MISMATCH : dectoul(argv[4], NULL);
	if (pat != 9 && pat != 31 && pat != PAT_MISMATCH)
		return CMD_RET_USAGE;
	for (i = 5; i < argc; i++) {
		if (!strcmp(argv[i], "near"))
			near = true;
		else if (!strcmp(argv[i], "force"))
			force = true;
		else if (!strcmp(argv[i], "v"))
			verbose = true;
		else
			ms = dectoul(argv[i], NULL);
	}
	if (rtk_sds_mode(s) != MODE_10GR) {
		printf("refused: cage %d is not 10GBASE-R (PRBS checker is in the 10GR PCS)\n", sds_cage(s));
		return CMD_RET_FAILURE;
	}
	if (!ms || ms > PRBS_MAX_MS) {
		printf("refused: duration 1..%d ms\n", PRBS_MAX_MS);
		return CMD_RET_FAILURE;
	}
	if (!lb_save[s].on && !link_guard(s, force, "PRBS"))
		return CMD_RET_FAILURE;
	sv.p5a = rd(s, 5, 0xa);
	sv.p60 = rd(s, 6, 0);
	sv.p6e = rd(s, 6, 0xe);
	sv.p6f = rd(s, 6, 0xf);
	if (near)
		lb_near(s, true);
	prbs_set(s, pat);
	mdelay(10);		/* checker sync: PRBS31 locks in 31 bits; 10 ms = margin for the PI/CDR */
	first = rd(s, 5, 0xb);	/* discard: counts from before the pattern started */
	t0 = get_timer(0);
	next = PRBS_SAMPLE_MS;
	for (;;) {
		el = get_timer(t0);
		if (ctrlc()) {
			aborted = true;
			break;
		}
		if (el >= next || el >= ms) {
			c = rd(s, 5, 0xb);
			samples++;
			total += c;
			nz += c != 0;
			sat += c == 0xffff;
			if (verbose)
				printf("  %5lu ms: 0x%04x\n", el, c);
			next += PRBS_SAMPLE_MS;
			if (el >= ms)
				break;
		}
		mdelay(10);
	}
	el = get_timer(t0);
	/* restore: pattern regs as found, then loopback (if this run turned it on) */
	wr(s, 5, 0xa, sv.p5a);
	wr(s, 6, 0, sv.p60);
	wr(s, 6, 0xe, sv.p6e);
	wr(s, 6, 0xf, sv.p6f);
	if (near)
		lb_near(s, false);
	else
		rx_resync(s);
	symerr_clear(s);
	printf(pat == PAT_MISMATCH ? "prbs31-vs-9 (self-test) " : "prbs%d ", pat);
	printf("cage %d%s: %u errors in %lu ms (%llu Mbit), %u/%u samples nonzero, %u saturated, "
	       "pre-start 0x%04x%s%s\n", sds_cage(s), near ? " near-loopback" : "", total, el,
	       BITS_PER_MS * el / 1000000, nz, samples, sat, first, aborted ? ", ABORTED (Ctrl-C)" : "",
	       io_err ? ", SerDes IO errors" : "");
	return aborted ? CMD_RET_FAILURE : 0;
}

/* ---- TX eye parameters (eyeParam_get/set): page by mode, pre 1[15:11], main 7[8:4], post 6[4:0] ---- */

static int txeye_page(int sds)
{
	switch (rtk_sds_mode(sds)) {
	case 0x02: case 0x04: case 0x05: return 0x25;
	case 0x12: case 0x16: return 0x29;
	case MODE_10GR: return 0x2f;
	default: return -1;
	}
}

static struct { bool saved; u16 r1, r6, r7; } tx_save[10];

static int do_txeye(int argc, char *const argv[])
{
	int s = argc > 3 ? parse_sds(argv[3]) : -1, p;
	ulong pre, mn, post;

	if (s < 0)
		return CMD_RET_USAGE;
	p = txeye_page(s);
	if (p < 0) {
		printf("cage %d: SerDes off, no TX eye page\n", sds_cage(s));
		return CMD_RET_FAILURE;
	}
	if (argc > 4 && !strcmp(argv[4], "restore")) {
		if (tx_save[s].saved) {
			wr(s, p, 1, tx_save[s].r1);
			wr(s, p, 6, tx_save[s].r6);
			wr(s, p, 7, tx_save[s].r7);
			tx_save[s].saved = false;
		}
	} else if (argc > 6) {
		pre = dectoul(argv[4], NULL);
		mn = dectoul(argv[5], NULL);
		post = dectoul(argv[6], NULL);
		if (pre > 31 || mn > 31 || post > 31) {
			printf("refused: pre/main/post are 5-bit (0..31)\n");
			return CMD_RET_FAILURE;
		}
		if (!tx_save[s].saved) {
			tx_save[s].r1 = rd(s, p, 1);
			tx_save[s].r6 = rd(s, p, 6);
			tx_save[s].r7 = rd(s, p, 7);
			tx_save[s].saved = true;
		}
		fw(s, p, 1, 15, 11, pre);
		fw(s, p, 7, 0, 0, pre != 0);
		fw(s, p, 7, 8, 4, mn);
		fw(s, p, 6, 4, 0, post);
		fw(s, p, 7, 3, 3, post != 0);
	} else if (argc > 4) {
		return CMD_RET_USAGE;
	}
	printf("txeye cage %d (page 0x%02x): pre %u (en %u) main %u post %u (en %u) impedance %u%s\n",
	       sds_cage(s), p, fr(s, p, 1, 15, 11), fr(s, p, 7, 0, 0), fr(s, p, 7, 8, 4),
	       fr(s, p, 6, 4, 0), fr(s, p, 7, 3, 3), fr(s, p, 0x18, 15, 12),
	       tx_save[s].saved ? " [changed; `restore` reverts]" : "");
	return 0;
}

/* ---- RX eye monitor (eyeMonitor_start): page 0x2e, PI = x (0-63), Vref = y (0-63) ---- */

/* Point value: bits 15:14 = 3 when valid, 13:0 = 7 samples of 2 bits: bit 1 = mismatch at this
 * (phase, Vref), bit 0 = half (1 lower, 0 upper). Decode = SDK dal_mango_sds_eyeMonInfo_update
 * (RTL931x; same format here): 128 rows, upper row 64 + y, lower row 63 - y. */
#define EYE_ROWS	(2 * EYE_N)
#define EYE_TRIES	8	/* re-reads until valid; first read of a scan returned 0 */
#define EYE_CHK_OFST	10	/* SDK RTK_EYE_MON_YAXIS_CHK_OFST: width measured at rows 64 +- 10 */

static const u8 eye_regs[] = { 0x00, 0x03, 0x07, 0x08, 0x0a, 0x1a, 0x1b };
static u16 eye_raw[EYE_N][EYE_N];	/* [y][x], frame 0 */
static u8 eye_hit[EYE_ROWS][EYE_N];	/* mismatches summed over frames (<= 7 x 16) */
static int eye_invalid;

static void eye_pi(int sds, int x)
{
	static const u8 en[] = { 0x9, 0xc, 0x6, 0x3 };
	u16 st = x / 16 % 2 ? (u16)(0xffff0000UL >> (x % 16)) : (u16)(0xffffU >> (x % 16));

	fw(sds, 0x2e, 0x1a, 9, 6, en[x / 16]);
	wr(sds, 0x2e, 0x1b, st);
}

static u16 eye_point(int sds, int y)
{
	int i;
	u16 v = 0;

	fw(sds, 0x2e, 0x1a, 5, 0, y);		/* ref (Vref) */
	wr(sds, 0x1f, 2, 0x37);			/* debug-out: eye monitor */
	for (i = 0; i < EYE_TRIES; i++) {
		fw(sds, 0x2e, 0, 0, 0, 1);	/* MDIO clock pulse latches one sample */
		fw(sds, 0x2e, 0, 0, 0, 0);
		v = rd(sds, 0x1f, 0x14);
		if (v >> 14 == 3)
			return v;
	}
	eye_invalid++;
	return 0;
}

static void eye_add(int x, int y, u16 v)
{
	int i, c;

	for (i = 0; i < 7; i++) {
		c = v >> (2 * i) & 3;
		if (c & 2)
			eye_hit[c & 1 ? EYE_N - 1 - y : EYE_N + y][x]++;
	}
}

/* SDK eyeMonitorInfo_get: height = longest clean run down any column, width = longest clean
 * run across rows 64 +- 10 */
static void eye_hw(int *h, int *w, int *hx, int *wc)
{
	static const u8 wrow[] = { EYE_N - EYE_CHK_OFST, EYE_N + EYE_CHK_OFST };
	int x, r, i, run;

	*h = *w = *hx = 0;
	for (x = 0; x < EYE_N; x++)
		for (r = 0, run = 0; r < EYE_ROWS; r++) {
			run = eye_hit[r][x] ? 0 : run + 1;
			if (run > *h)
				*h = run, *hx = x;
		}
	for (i = 0; i < ARRAY_SIZE(wrow); i++)
		for (x = 0, run = 0; x < EYE_N; x++) {
			run = eye_hit[wrow[i]][x] ? 0 : run + 1;
			if (run > *w)
				*w = run;
		}
	/* ours: centre rows 63 + 64 (Vref offset 0), where the crossings close the eye */
	for (x = 0, run = 0, *wc = 0; x < EYE_N; x++) {
		run = eye_hit[EYE_N - 1][x] || eye_hit[EYE_N][x] ? 0 : run + 1;
		if (run > *wc)
			*wc = run;
	}
}

/* 64 lines (2 rows each, top = upper half), 64 columns; ' ' clean, '.' <= 1 hit/frame, '+' <= 4, '#' more */
static void eye_draw(int frames)
{
	int l, x, n;

	printf("     x=0%*s63\n", EYE_N - 3, "");
	for (l = 0; l < EYE_N; l++) {
		printf(l == EYE_N / 2 - 1 ? "  0 |" : "    |");
		for (x = 0; x < EYE_N; x++) {
			n = eye_hit[EYE_ROWS - 1 - 2 * l][x] + eye_hit[EYE_ROWS - 2 - 2 * l][x];
			putc(!n ? ' ' : n <= frames ? '.' : n <= 4 * frames ? '+' : '#');
		}
		printf("|\n");
	}
}

static int do_eye(int argc, char *const argv[])
{
	int s = argc > 3 ? parse_sds(argv[3]) : -1, i, x, y, f, frames = 1, h, w, hx, wc;
	u16 save[ARRAY_SIZE(eye_regs)], dbg, v;
	bool raw = false, settle = true, aborted = false, before, after, idle, cmu;
	ulong t0;

	if (s < 0)
		return CMD_RET_USAGE;
	for (i = 4; i < argc; i++) {
		if (!strcmp(argv[i], "raw"))
			raw = true;
		else if (!strcmp(argv[i], "nosettle"))
			settle = false;
		else
			frames = dectoul(argv[i], NULL);
	}
	if (frames < 1 || frames > 16)		/* SDK RTK_EYE_MON_FRAME_MAX */
		return CMD_RET_USAGE;
	dbg35(s, &idle, &cmu);
	before = pcs_link(s);
	for (i = 0; i < ARRAY_SIZE(eye_regs); i++)
		save[i] = rd(s, 0x2e, eye_regs[i]);
	dbg = rd(s, 0x1f, 2);
	memset(eye_hit, 0, sizeof(eye_hit));
	eye_invalid = 0;
	t0 = get_timer(0);
	/* _dal_longan_sds_eye_scan_enable(1, 0, 1, 1, 1): scan_en toggled 1-0-1 */
	fw(s, 0x2e, 8, 14, 14, 1);
	fw(s, 0x2e, 8, 14, 14, 0);
	fw(s, 0x2e, 8, 14, 14, 1);
	fw(s, 0x2e, 8, 15, 15, 0);		/* ck_sel */
	fw(s, 0x2e, 7, 15, 14, 1);		/* rsel */
	fw(s, 0x2e, 0xa, 13, 12, 1);		/* bias_adj */
	fw(s, 0x2e, 3, 15, 14, 1);		/* pi_adj */
	for (x = 0; x < EYE_N && !aborted; x++) {
		eye_pi(s, x);
		if (settle)			/* first sample after a PI step + Vref 63->0 is stale */
			eye_point(s, 0);
		for (y = 0; y < EYE_N; y++)
			for (f = 0; f < frames; f++) {
				v = eye_point(s, y);
				if (!f)
					eye_raw[y][x] = v;
				eye_add(x, y, v);
			}
		aborted = ctrlc();
	}
	for (i = 0; i < ARRAY_SIZE(eye_regs); i++)
		wr(s, 0x2e, eye_regs[i], save[i]);
	wr(s, 0x1f, 2, dbg);
	after = pcs_link(s);
	printf("eye cage %d sds %d: %d x %d, %d frame(s), %lu ms, pcs %s -> %s, %d invalid%s%s\n",
	       sds_cage(s), s, EYE_N, EYE_N, frames, get_timer(t0), before ? "up" : "down",
	       after ? "up" : "down", eye_invalid, aborted ? ", ABORTED (Ctrl-C)" : "",
	       io_err ? ", SerDes IO errors" : "");
	if (aborted)
		return CMD_RET_FAILURE;
	if (idle)	/* no input: the comparators never disagree, the map reads all-open */
		printf("eye cage %d: RX idle (no signal): map below is not an eye\n", sds_cage(s));
	if (raw)
		for (y = 0; y < EYE_N; y++) {
			printf("y%02d", y);
			for (x = 0; x < EYE_N; x++)
				printf(" %x", eye_raw[y][x]);
			printf("\n");
		}
	else
		eye_draw(frames);
	eye_hw(&h, &w, &hx, &wc);
	printf("eye cage %d: height %d/%d rows (at x %d), width %d/%d PI steps (SDK rows 64+-%d), "
	       "centre width %d\n", sds_cage(s), h, EYE_ROWS, hx, w, EYE_N, EYE_CHK_OFST, wc);
	return 0;
}

int rtk_sds_cmd(int argc, char *const argv[])
{
	const char *v = argc > 2 ? argv[2] : "";
	int ret;

	if (!rtk_net_is_on()) {
		printf("rtk sds: run `rtk network on` first (SerDes not configured)\n");
		return CMD_RET_FAILURE;
	}
	io_err = 0;
	if (!strcmp(v, "status"))
		ret = do_status(argc, argv);
	else if (!strcmp(v, "errcnt"))
		ret = do_errcnt(argc, argv);
	else if (!strcmp(v, "prbs"))
		ret = do_prbs(argc, argv);
	else if (!strcmp(v, "loopback"))
		ret = do_loopback(argc, argv);
	else if (!strcmp(v, "eye"))
		ret = do_eye(argc, argv);
	else if (!strcmp(v, "txeye"))
		ret = do_txeye(argc, argv);
	else
		ret = CMD_RET_USAGE;
	if (ret == CMD_RET_USAGE)
		printf("usage: rtk sds status|errcnt [<cage>|s<sds>|all] [clear]\n"
		       "       rtk sds prbs <cage> 9|31|mismatch [ms] [near] [force] [v] | prbs <cage> off\n"
		       "       rtk sds loopback <cage> near|off [force]\n"
		       "       rtk sds eye <cage> [frames] [raw] [nosettle]\n"
		       "       rtk sds txeye <cage> [<pre> <main> <post> | restore]\n");
	if (io_err)
		printf("rtk sds: %d SerDes access errors\n", io_err);
	return ret == CMD_RET_USAGE ? CMD_RET_FAILURE : ret;
}
