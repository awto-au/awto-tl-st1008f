// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk spg`: RTL9303 Smart Packet Generator (#70). Registers, fields, sequence: docs/SPG.md.
 * Sequence: GPL SDK rtk-dms1250 rtdrv_netfilter_ext_9300.c (pktgen ioctls, _pkt_stream_offset_oper).
 * Safety: cage ports only, count mandatory + capped, lit ports refused, start blocks to done/limit.
 */

#include <command.h>
#include <console.h>
#include <dm.h>
#include <i2c.h>
#include <time.h>
#include <linux/math64.h>
#include <vsprintf.h>
#include "rtk.h"
#include "sfp/sfp.h"

#define SPG_GLB		0x7ab0			/* [2:1] GRP_TX_CMD, [0] SPG_MODE */
#define SPG_GRP		0x7ab4			/* [27:0] GRP_TX_PORT */
#define SPG_STS		0x7ab8			/* [27:0] TX_DONE_PORT */
#define SPG_IPG(p)	(0x328c + (p) * 0x40)	/* [19:0] IPG_LEN */
#define SPG_PP(p, o)	(0x67e4 + (p) * 0x60 + (o))
#define PP_CNT_H	0x00			/* frames to send, 0 = continuous */
#define PP_CNT_L	0x04
#define PP_DBG_H	0x08			/* frames sent */
#define PP_DBG_L	0x0c
#define PP_S(s, k)	(0x10 + (s) * 0x14 + (k) * 4)	/* stream s CTRL0..4 */
#define PP_INDEX	0x38			/* [27:16] S1 page index, [11:0] S0 */
#define PB_SEL		0xdcf0			/* [5:0] PB_INDEX = stream id (port * 2 + s) */
#define PB_DATA		0xdcf4
#define PB_CTRL		0xdcf8			/* [31] trig, [30] write, [15:8] cell, [7:0] byte */
#define PB_GIDX(i)	(0xdcfc + ((i) >> 1) * 4)	/* stream 2n [11:0], 2n+1 [27:16] */
#define MAC_FORCE(p)	(0xca1c + (p) * 4)	/* [0] force, [1] link, [5:3] speed */
#define MAC_LINK_STS	0xcb10
#define MAC_LINK_SPD(p)	(0xcb18 + ((p) >> 3) * 4)

enum { CMD_NOP, CMD_START, CMD_STOP, CMD_PAUSE };	/* STOP resets the sent counter, PAUSE holds it */
static const char *const cmd_name[] = { "nop", "start", "stop", "pause" };

#define PAGE_BASE	0x800		/* SDK page_base; 36 pages of 4 x 90 B cells per stream */
#define STREAM_PAGES	36
#define CELL_BYTES	90
#define LEN_MIN		64
#define LEN_MAX		1518		/* house LAN frame size; SDK limit is 36 x 360 B */
#define TBUF		1620		/* LEN_MAX rounded up to whole cells */
#define ETYPE		0x88b5		/* IEEE local experimental: the host capture filters on it */
#define CNT_CAP		100000
#define CNT_LIT_CAP	1000		/* with allow-lit */
#define RUN_MAX_US	10000000	/* refuse a start expected to block the console > 10 s */
#define LIMIT_FLOOR_US	1000		/* start/stop register writes; covers tiny counts */
#define RX_LIT		20		/* 2 uW in 0.1 uW units: a lit fibre is far above, dark reads ~0 */
#define PB_POLL_N	100		/* trig self-clear; the SDK never polls it */

static u16 ld_len[NPORTS][2], ld_min[NPORTS][2];	/* loaded since boot; 0 = not loaded */
static u8 tbuf[TBUF], rbuf[TBUF];

static int cage_of(int port)
{
	int i;

	for (i = 0; i < NCAGES; i++)
		if (rtk_cage_port[i] == port)
			return i + 1;
	return 0;
}

static void tx_cmd(u32 cmd)
{
	sw_rmw(SPG_GLB, GENMASK(2, 1), cmd << 1);
}

/* SDK: TX_CMD must be NOP before GRP_TX_PORT changes (a change runs the current command) */
static void grp_cmd(u32 grp, u32 cmd)
{
	tx_cmd(CMD_NOP);
	sw_w(SPG_GRP, grp);
	tx_cmd(cmd);
}

static u64 sent(int p)
{
	u32 h, l;

	do {
		h = sw_r(SPG_PP(p, PP_DBG_H));
		l = sw_r(SPG_PP(p, PP_DBG_L));
	} while (h != sw_r(SPG_PP(p, PP_DBG_H)));
	return (u64)h << 32 | l;
}

static bool link_up(int p)
{
	sw_r(MAC_LINK_STS);	/* latched low: second read = now */
	return sw_r(MAC_LINK_STS) & BIT(p);
}

/* Mb/s from the MAC speed code (link status if up, else the forced/media speed), 0 = unknown */
static unsigned int port_mbps(int p)
{
	static const u16 mbps[8] = { 10, 100, 1000, 10000, 10000, 2500, 5000, 0 };
	u32 code = link_up(p) ? (sw_r(MAC_LINK_SPD(p)) >> ((p & 7) * 4)) & 0xf :
				(sw_r(MAC_FORCE(p)) >> 3) & 7;

	return code < 8 ? mbps[code] : 0;
}

/* 1 = light or a peer is possible on this cage (fail-safe: unknown = lit), 0 = dark */
static int cage_lit(int cage, char *why, int n)
{
	struct udevice *exp = rtk_chip(EXP_BUS, EXP_ADDR);
	u8 out, cfg, id[96], a2[128];
	struct sff_diags sd;
	int port = rtk_cage_port[cage - 1], b = cage - 1;

	if (!exp || dm_i2c_read(exp, EXP_OUT, &out, 1) || dm_i2c_read(exp, EXP_CFG, &cfg, 1))
		return snprintf(why, n, "laser expander unreadable"), 1;
	if (!(cfg & BIT(b)) && !(out & BIT(b)))
		return snprintf(why, n, "laser ON"), 1;
	if (link_up(port))
		return snprintf(why, n, "MAC link up"), 1;
	if (rtk_sfp_present(cage) == 0)
		return snprintf(why, n, "empty cage"), 0;
	if (rtk_sfp_read_id(cage, id))
		return snprintf(why, n, "module EEPROM unreadable"), 1;
	if (id[6] & 0x08)
		return snprintf(why, n, "copper module: ignores TX-disable"), 1;
	if (id[8] & 0x0c)
		return snprintf(why, n, "DAC: electrical, no TX-disable"), 1;
	if (!(id[92] & 0x40))
		return snprintf(why, n, "no DDM: RX light unknown"), 1;
	if (rtk_sfp_read_a2(cage, a2))
		return snprintf(why, n, "A2 unreadable"), 1;
	sff8472_diags(id, a2, &sd);
	if (sd.rx_power[MCURR] >= RX_LIT)
		return snprintf(why, n, "RX light %u.%04u mW", sd.rx_power[MCURR] / 10000,
				sd.rx_power[MCURR] % 10000), 1;
	if ((id[93] & 0x40) && !(a2[110] & 0x02))
		return snprintf(why, n, "RX_LOS clear"), 1;
	return snprintf(why, n, "laser off, rx %u.%04u mW", sd.rx_power[MCURR] / 10000,
			sd.rx_power[MCURR] % 10000), 0;
}

static void spg_enable(void)
{
	int i, p;

	if (!(sw_r(SPG_GLB) & 1)) {
		sw_rmw(SPG_GLB, 1, 1);
		printf("spg: SPG_MODE on\n");
	}
	for (i = 0; i < NCAGES; i++) {	/* SDK sets all 28 ports; only cage ports exist here */
		p = rtk_cage_port[i];
		sw_w(SPG_PP(p, PP_INDEX), (PAGE_BASE + (p * 2 + 1) * STREAM_PAGES) << 16 |
		     (PAGE_BASE + p * 2 * STREAM_PAGES));
	}
}

/* One PB word (SDK _dal_longan_packetGen_buf_oper, EXT_SRAM_PKT_TEST path). 1 = trig stuck. */
static int pb_word(u32 cell, u32 byte, bool wr, u32 *v)
{
	u32 c = byte | cell << 8 | (wr ? BIT(30) : 0);
	int i;

	sw_w(PB_CTRL, c);
	if (wr)
		sw_w(PB_DATA, *v);
	sw_w(PB_CTRL, c | BIT(31));
	for (i = 0; i < PB_POLL_N && (sw_r(PB_CTRL) & BIT(31)); i++)
		;
	if (!wr)
		*v = sw_r(PB_DATA);
	return i == PB_POLL_N;
}

/* Template at offset 0. Cell = 90 B: bytes 0-1 at index 88 (low 16 bits), then 4 B per word at
 * index 84, 80, .. 0 (SDK idxArry). Returns words moved; *stuck counts trig non-clears. */
static int pb_io(int sid, u8 *buf, int len, bool wr, int *stuck)
{
	int cell, i, j, k = 0, nb, words = 0;
	u32 v;

	sw_w(PB_SEL, sid);
	v = PAGE_BASE + sid * STREAM_PAGES;
	sw_rmw(PB_GIDX(sid), sid & 1 ? 0x0fff0000 : 0x0fff, sid & 1 ? v << 16 : v);
	for (cell = 0; k < len; cell++) {
		for (i = 0; i < CELL_BYTES && k < len; i += 4) {
			nb = i ? 4 : 2;
			v = 0;
			if (wr)
				for (j = 0; j < nb; j++)
					v |= (u32)buf[k + j] << ((nb - 1 - j) * 8);
			*stuck += pb_word(cell, i ? 88 - i : 88, wr, &v);
			if (!wr)
				for (j = 0; j < nb; j++)
					buf[k + j] = v >> ((nb - 1 - j) * 8);
			k += nb;
			words++;
		}
	}
	return words;
}

static int parse_mac(const char *s, u8 *m)
{
	char *e;
	int i;

	for (i = 0; i < 6; i++) {
		m[i] = hextoul(s, &e);
		if (e == s || e - s > 2 || *e != (i < 5 ? ':' : '\0'))
			return -1;
		s = e + 1;
	}
	return 0;
}

static bool is_cage_port(unsigned long p)
{
	return p < NPORTS && cage_of(p);
}

static int bad_port(unsigned long p)
{
	printf("spg: port %lu refused: cage ports only (cage 1-8 = port 0 8 16 20 24 25 26 27)\n", p);
	return CMD_RET_FAILURE;
}

static bool busy(void)
{
	return (sw_r(SPG_GRP) & GENMASK(27, 0)) && ((sw_r(SPG_GLB) >> 1) & 3) == CMD_START;
}

static int spg_status(void)
{
	u32 g = sw_r(SPG_GLB), c0;
	char why[48];
	int i, p, s, lit;

	printf("spg: SPG_GLB 0x%08x (mode %s, tx_cmd %s), TX_GRP 0x%07x, TX_DONE 0x%07x, PB_SEL %u, "
	       "PB_CTRL 0x%08x\n", g, g & 1 ? "on" : "off", cmd_name[(g >> 1) & 3],
	       sw_r(SPG_GRP) & 0x0fffffff, sw_r(SPG_STS) & 0x0fffffff, sw_r(PB_SEL) & 0x3f,
	       sw_r(PB_CTRL));
	for (i = 0; i < NCAGES; i++) {
		p = rtk_cage_port[i];
		lit = cage_lit(i + 1, why, sizeof(why));
		printf("cage %d port %2d: sent %llu, cnt %u:%u, ipg %u, index 0x%08x, link %s, %s (%s)\n",
		       i + 1, p, (unsigned long long)sent(p), sw_r(SPG_PP(p, PP_CNT_H)),
		       sw_r(SPG_PP(p, PP_CNT_L)), sw_r(SPG_IPG(p)) & 0xfffff,
		       sw_r(SPG_PP(p, PP_INDEX)), link_up(p) ? "up" : "down", lit ? "LIT" : "dark", why);
		for (s = 0; s < 2; s++) {
			c0 = sw_r(SPG_PP(p, PP_S(s, 0)));
			printf("  s%d: ctrl0 0x%08x (badcrc %u, len_type %u), pktcnt %u, len %u-%u, "
			       "ctrl3 0x%08x, ctrl4 0x%08x%s\n", s, c0, (c0 >> 13) & 1, (c0 >> 7) & 3,
			       sw_r(SPG_PP(p, PP_S(s, 1))), (sw_r(SPG_PP(p, PP_S(s, 2))) >> 16) & 0x3fff,
			       sw_r(SPG_PP(p, PP_S(s, 2))) & 0x3fff, sw_r(SPG_PP(p, PP_S(s, 3))),
			       sw_r(SPG_PP(p, PP_S(s, 4))), ld_len[p][s] ? ", loaded" : "");
		}
	}
	return 0;
}

/* load <port> <stream> <len_start> <len_end> <da> <sa> [zero|incr|decr|0xPATTERN] [badcrc] */
static int spg_load(int argc, char *const argv[])
{
	unsigned long p, s, ls, le, pat = 0;
	const char *pn = "incr";
	bool badcrc = false;
	u8 da[6], sa[6];
	int i, mode = 1, words, stuck = 0, sid;

	if (argc < 9)
		return CMD_RET_USAGE;
	p = dectoul(argv[3], NULL);
	s = dectoul(argv[4], NULL);
	ls = dectoul(argv[5], NULL);
	le = dectoul(argv[6], NULL);
	if (!is_cage_port(p))
		return bad_port(p);
	if (s > 1 || ls < LEN_MIN || le > LEN_MAX || ls > le) {
		printf("spg: stream 0|1, %d <= len_start <= len_end <= %d (incl. FCS)\n", LEN_MIN, LEN_MAX);
		return CMD_RET_FAILURE;
	}
	if (parse_mac(argv[7], da) || parse_mac(argv[8], sa)) {
		printf("spg: MAC format aa:bb:cc:dd:ee:ff\n");
		return CMD_RET_FAILURE;
	}
	if ((da[0] & 1) || (sa[0] & 1)) {
		printf("spg: refused: group DA floods the far switch, group SA is invalid\n");
		return CMD_RET_FAILURE;
	}
	for (i = 9; i < argc; i++) {
		if (!strcmp(argv[i], "badcrc"))
			badcrc = true;
		else if (!strcmp(argv[i], "zero") || !strcmp(argv[i], "incr") || !strcmp(argv[i], "decr"))
			pn = argv[i], mode = pn[0] == 'z' ? 0 : pn[0] == 'i' ? 1 : 2;
		else if (!strncmp(argv[i], "0x", 2))
			pn = argv[i], mode = 3, pat = hextoul(argv[i], NULL);
		else
			return CMD_RET_USAGE;
	}
	if (busy()) {
		printf("spg: generator running: rtk spg stop first\n");
		return CMD_RET_FAILURE;
	}
	spg_enable();
	sw_w(SPG_PP(p, PP_S(s, 0)), (badcrc ? BIT(13) : 0) | (ls != le ? 2 : 0) << 7);
	sw_w(SPG_PP(p, PP_S(s, 1)), 0);	/* stream frame count: set by start */
	sw_w(SPG_PP(p, PP_S(s, 2)), ls << 16 | le);
	sw_w(SPG_PP(p, PP_S(s, 3)), 0);
	sw_w(SPG_PP(p, PP_S(s, 4)), 0);
	memset(tbuf, 0, sizeof(tbuf));
	memcpy(tbuf, da, 6);
	memcpy(tbuf + 6, sa, 6);
	tbuf[12] = ETYPE >> 8;
	tbuf[13] = ETYPE & 0xff;
	for (i = 14; i < le; i++)
		tbuf[i] = mode == 1 ? i - 14 : mode == 2 ? 0xff - (i - 14) :
			  mode == 3 ? pat >> ((3 - (i - 14) % 4) * 8) : 0;
	sid = p * 2 + s;
	words = pb_io(sid, tbuf, le, true, &stuck);
	memset(rbuf, 0, sizeof(rbuf));
	pb_io(sid, rbuf, le, false, &stuck);
	for (i = 0; i < le && rbuf[i] == tbuf[i]; i++)
		;
	printf("spg: loaded port %lu (cage %d) stream %lu: len %lu-%lu (%s), DA %pM SA %pM type 0x%04x, "
	       "payload %s, fcs %s; stream id %d page 0x%03x\n", p, cage_of(p), s, ls, le,
	       ls == le ? "fixed" : "incr", da, sa, ETYPE, pn, badcrc ? "BAD" : "good", sid,
	       PAGE_BASE + sid * STREAM_PAGES);
	if (i < le) {
		printf("spg: verify FAIL at byte %d: wrote 0x%02x read 0x%02x (%d words, %d trig stuck)\n",
		       i, tbuf[i], rbuf[i], words, stuck);
		ld_len[p][s] = 0;
		return CMD_RET_FAILURE;
	}
	printf("spg: verify ok (%d words, trig %s)\n", words,
	       stuck ? "did not self-clear" : "self-clears");
	ld_len[p][s] = le;
	ld_min[p][s] = ls;
	return 0;
}

/* start <port> <stream> <count> [ipg] [allow-lit] [force-link] */
static int spg_start(int argc, char *const argv[])
{
	unsigned long p, s, count, ipg, t0, el = 0, limit;
	bool allow = false, force = false, have_ipg = false;
	u32 sts0, fsave = 0, mbps, wire, gap;
	u64 exp_us, c = 0, fps;
	const char *res;
	char why[48], *e;
	int i, lit, n;

	if (argc < 6)
		return CMD_RET_USAGE;
	p = dectoul(argv[3], NULL);
	s = dectoul(argv[4], NULL);
	if (!is_cage_port(p))
		return bad_port(p);
	if (s > 1)
		return CMD_RET_USAGE;
	count = simple_strtoul(argv[5], &e, 10);
	if (*e || e == argv[5] || !count) {
		printf("spg: count must be 1-%d (0 = continuous on this hardware: refused)\n", CNT_CAP);
		return CMD_RET_FAILURE;
	}
	ipg = sw_r(SPG_IPG(p)) & 0xfffff;
	for (i = 6; i < argc; i++) {
		if (!strcmp(argv[i], "allow-lit")) {
			allow = true;
		} else if (!strcmp(argv[i], "force-link")) {
			force = true;
		} else {
			ipg = simple_strtoul(argv[i], &e, 0);
			if (*e || ipg > 0xfffff)
				return CMD_RET_USAGE;
			have_ipg = true;
		}
	}
	if (count > CNT_CAP) {
		printf("spg: count %lu over the cap %d: refused\n", count, CNT_CAP);
		return CMD_RET_FAILURE;
	}
	if (!ld_len[p][s]) {
		printf("spg: port %lu stream %lu not loaded since boot: rtk spg load first\n", p, s);
		return CMD_RET_FAILURE;
	}
	if (busy()) {
		printf("spg: generator running: rtk spg stop first\n");
		return CMD_RET_FAILURE;
	}
	lit = cage_lit(cage_of(p), why, sizeof(why));
	if (lit && !allow) {
		printf("spg: port %lu (cage %d) LIT (%s): refused; allow-lit permits count <= %d\n", p,
		       cage_of(p), why, CNT_LIT_CAP);
		return CMD_RET_FAILURE;
	}
	if (lit && count > CNT_LIT_CAP) {
		printf("spg: port %lu (cage %d) LIT (%s): allow-lit caps count at %d: refused\n", p,
		       cage_of(p), why, CNT_LIT_CAP);
		return CMD_RET_FAILURE;
	}
	if (lit && force) {
		printf("spg: force-link is for dark ports only: refused\n");
		return CMD_RET_FAILURE;
	}
	mbps = port_mbps(p);
	if (!mbps) {
		printf("spg: port %lu speed code unknown: refused\n", p);
		return CMD_RET_FAILURE;
	}
	/* worst case = longest frame; IPG_LEN taken as byte times (SPEC, docs/SPG.md), 12 minimum */
	gap = ipg > 12 ? ipg : 12;
	wire = ld_len[p][s] + 8 + gap;
	exp_us = div_u64((u64)count * wire * 8, mbps);
	if (exp_us > RUN_MAX_US) {
		printf("spg: expected run %llu us over %d us: refused\n", (unsigned long long)exp_us,
		       RUN_MAX_US);
		return CMD_RET_FAILURE;
	}
	limit = exp_us * 5 / 4 > LIMIT_FLOOR_US ? exp_us * 5 / 4 : LIMIT_FLOOR_US;
	fps = div_u64((u64)mbps * 1000000, wire * 8);
	printf("spg: plan port %lu (cage %d) stream %lu: %lu frames, len %u-%u, ipg %lu%s, %u Mb/s link%s"
	       " -> %llu fps, %llu Mb/s; expect %llu us, auto-stop at TX_DONE or %lu us (1.25x, floor"
	       " %d us); %s (%s)\n", p, cage_of(p), s, count, ld_min[p][s], ld_len[p][s], ipg,
	       have_ipg ? "" : " (register)", mbps, force ? " (forced up)" : link_up(p) ? "" : " (DOWN)",
	       (unsigned long long)fps, (unsigned long long)div_u64(fps * ld_len[p][s] * 8, 1000000),
	       (unsigned long long)exp_us, limit, LIMIT_FLOOR_US, lit ? "LIT, allow-lit" : "dark", why);
	if (have_ipg)
		sw_rmw(SPG_IPG(p), 0xfffff, ipg);
	sw_w(SPG_PP(p, PP_CNT_H), 0);
	sw_w(SPG_PP(p, PP_CNT_L), count);
	sw_w(SPG_PP(p, PP_S(s, 1)), count);
	sw_w(SPG_PP(p, PP_S(s ^ 1, 1)), 0);	/* other stream off (SDK ring test) */
	if (force) {
		fsave = sw_r(MAC_FORCE(p));
		sw_w(MAC_FORCE(p), fsave | 3);
	}
	grp_cmd(BIT(p), CMD_STOP);	/* reset the sent counter */
	sts0 = sw_r(SPG_STS);
	if (sent(p))
		printf("spg: sent counter %llu after stop (expected 0)\n", (unsigned long long)sent(p));
	t0 = timer_get_us();
	grp_cmd(BIT(p), CMD_START);
	for (n = 0;; n++) {
		c = sent(p);
		el = timer_get_us() - t0;
		if (c > count) {
			res = "OVERRUN";
			break;
		}
		if ((sw_r(SPG_STS) & BIT(p)) && !(sts0 & BIT(p))) {
			res = c == count ? "DONE" : "EARLY";
			break;
		}
		if (el > limit) {	/* done bit already latched before start, or no TX_DONE */
			res = c == count ? "COUNT" : "TIMEOUT";
			break;
		}
		if (!(n & 0x3ff) && ctrlc()) {
			res = "ABORT";
			break;
		}
	}
	grp_cmd(BIT(p), CMD_PAUSE);	/* stop, hold the counter */
	grp_cmd(0, CMD_NOP);
	if (force)
		sw_w(MAC_FORCE(p), fsave);
	c = sent(p);
	if (!strcmp(res, "EARLY") && c == count)	/* TX_DONE seen before the counter settled */
		res = "DONE";
	printf("spg: result %s sent %llu of %lu, tx_done 0x%07x (before 0x%07x), elapsed %lu us "
	       "(expected %llu, limit %lu)\n", res, (unsigned long long)c, count,
	       sw_r(SPG_STS) & 0x0fffffff, sts0 & 0x0fffffff, el, (unsigned long long)exp_us, limit);
	if (!strcmp(res, "TIMEOUT") && !link_up(p) && !force)
		printf("spg: MAC link down: a dark port may need force-link\n");
	return (!strcmp(res, "DONE") || !strcmp(res, "COUNT")) && c == count ? 0 : CMD_RET_FAILURE;
}

static int spg_stop(int argc, char *const argv[])
{
	grp_cmd(sw_r(SPG_GRP) & 0x0fffffff, CMD_PAUSE);
	grp_cmd(0, CMD_NOP);
	if (argc > 3 && !strcmp(argv[3], "off")) {
		sw_rmw(SPG_GLB, 1, 0);
		printf("spg: SPG_MODE off\n");
	}
	printf("spg: stopped, SPG_GLB 0x%08x TX_GRP 0x%07x\n", sw_r(SPG_GLB), sw_r(SPG_GRP));
	return 0;
}

int rtk_spg(int argc, char *const argv[])
{
	int ret = CMD_RET_USAGE;

	if (argc >= 3 && !rtk_net_is_on()) {
		printf("spg: run `rtk network on` first\n");
		return CMD_RET_FAILURE;
	}
	if (argc >= 3 && !strcmp(argv[2], "status"))
		ret = spg_status();
	else if (argc >= 3 && !strcmp(argv[2], "load"))
		ret = spg_load(argc, argv);
	else if (argc >= 3 && !strcmp(argv[2], "start"))
		ret = spg_start(argc, argv);
	else if (argc >= 3 && !strcmp(argv[2], "stop"))
		ret = spg_stop(argc, argv);
	if (ret == CMD_RET_USAGE) {
		printf("rtk spg status\n"
		       "rtk spg load <port> <stream> <len_start> <len_end> <da> <sa> [zero|incr|decr|0xPAT]"
		       " [badcrc]\n"
		       "rtk spg start <port> <stream> <count> [ipg] [allow-lit] [force-link]\n"
		       "rtk spg stop [off]\n"
		       "  port = SDK cage port 0 8 16 20 24-27; count 1-%d (allow-lit: <= %d, lit cages);\n"
		       "  start blocks until TX_DONE or 1.25x the expected time; Ctrl-C stops\n",
		       CNT_CAP, CNT_LIT_CAP);
		return CMD_RET_FAILURE;
	}
	return ret;
}
