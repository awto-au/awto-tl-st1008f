// SPDX-License-Identifier: GPL-2.0+
/*
 * Stock stage-4 `rtk` verbs: network on|off, 10g, macsds set, port-isolation; plus `sdsdump`.
 * Sequence = stock loader (construct table 0x83fa3718, sds_mode_10gr_set 0x83f90f74, network_on
 * 0x83f199c4) and the Realtek SDK it is built from (rtk-dms1250, GPL-2.0: dal_longan_construct.c,
 * dal_longan_sds.c, phy_rtl9300.c, dal_longan_port.c). Doc: docs/RTK-COMMANDS.md#stage-4.
 */

#include <command.h>
#include <env.h>
#include <i2c.h>
#include <time.h>
#include <linux/delay.h>
#include <vsprintf.h>
#include "rtk.h"
#include "rtk_sds_tables.h"

/* SDK rt_serdesMode_t values (= `macsds set` list index) */
enum { M_DISABLE = 1, M_10GR = 2, M_SGMII = 8, M_1000BX = 10, M_100BX = 11, M_HISGMII = 23,
       M_2500BX = 26, M_END = 47 };
/* SDK rtk_port_10gMedia_t (stock `10g` media ids); SGMII is ours (copper modules, rtk_sfpmode.c) */
enum { MEDIA_NONE, MEDIA_10G, MEDIA_1G, MEDIA_2_5G, MEDIA_100M, MEDIA_DAC50, MEDIA_DAC100,
       MEDIA_DAC300, MEDIA_DAC500, MEDIA_SGMII = 15 };

#define MAC_FORCE(p)	(0xca1c + ((p) << 2))	/* bit0 force, bit1 link, [5:3] speed */
#define SMI_POLL_CTRL	0xca90			/* [27:0] SMI_POLL_MASK (OpenWrt mdio-realtek-otto) */
#define SMI_PRVTE_POLL	0xca10			/* [27:0] private polling mask */
#define ETHER_PMASK	0x0f110101		/* ports 0 8 16 20 24-27 (RTL9303_8XGE profile) */
#define ISO_CTRL	0xb340			/* table access: [17] exec, [16] write, [14:12] type */
#define ISO_DATA	0xb344			/* PORT_ISO_CTRL entry: [31:3] = ports 0-28 */
#define ISO_TYPE	6
/* rtl9300_init _rtl9300_smiMacType_init: XGE + SerDes media -> type 0 (link from SerDes, not SMI PHY).
 * Fields P3_P0 [1:0], P11_P8 [5:4], P19_P16 [9:8], P23_P20 [11:10], P24-P27 3 bits each [23:12] */
#define SMI_MAC_TYPE	0xca04
#define SMI_MAC_TYPE_M	0x00ffff33
/* CPU port force = stock value after its NIC probe (reg-diff, #51): link up, 1G; other bits SPEC */
#define CPU_FORCE	0x217
/* table op is a few switch-core cycles; 100 x 10 us = 1 ms names a dead engine (OpenWrt waits 10 ms) */
#define ISO_POLL_N	100
#define CLK_TRIES	20	/* stock CMU toggle retries (sds_mode_10gr_set); 3 x ready in a row ends it */

static bool constructed, net_on;
static u8 media[NPORTS];		/* stock port10gMedia[]; 0 = NONE until network on */
static bool admin[NPORTS];
static bool f100m[12];			/* SDK fiber100m_info.chage_flag */
static int io_err;

bool rtk_net_is_on(void)
{
	return net_on;
}

/* ---- SerDes field access: raw (hal_sds_field_*) and logical (dal_longan_sds_field_*) ---- */

static int dsds(unsigned int sds, unsigned int page)
{
	return sds == 3 && page < 4 ? 10 : sds;	/* drv_rtl9300_sds2XsgmSds_get */
}

static u16 rd(unsigned int sds, unsigned int page, unsigned int reg)
{
	u16 v = 0;

	if (rtk_sds_read(sds, page, reg, &v))
		io_err++;
	return v;
}

static void wr(unsigned int sds, unsigned int page, unsigned int reg, u16 v)
{
	if (rtk_sds_write(sds, page, reg, v))
		io_err++;
}

static void hfw(unsigned int sds, unsigned int page, unsigned int reg, int hi, int lo, u16 v)
{
	u16 m = GENMASK(hi, lo);

	wr(sds, page, reg, (rd(sds, page, reg) & ~m) | ((v << lo) & m));
}

static u16 hfr(unsigned int sds, unsigned int page, unsigned int reg, int hi, int lo)
{
	return (rd(sds, page, reg) & GENMASK(hi, lo)) >> lo;
}

static void dfw(unsigned int sds, unsigned int page, unsigned int reg, int hi, int lo, u16 v)
{
	hfw(dsds(sds, page), page, reg, hi, lo, v);
}

static u16 dfr(unsigned int sds, unsigned int page, unsigned int reg, int hi, int lo)
{
	return hfr(dsds(sds, page), page, reg, hi, lo);
}

static int sds_port(unsigned int sds)
{
	return sds >= 2 && sds <= 9 ? rtk_cage_port[sds - 2] : -1;
}

static int port_sds(unsigned int port)
{
	int i;

	for (i = 0; i < NCAGES; i++)
		if (rtk_cage_port[i] == port)
			return rtk_cage_sds(i + 1);
	return -1;
}

/* ---- MAC force link (_dal_longan_port_macForceLink_set) ---- */

static int media_spd(int port)
{
	switch (media[port]) {
	case MEDIA_1G: case MEDIA_SGMII: return 2;
	case MEDIA_100M: return 1;
	case MEDIA_2_5G: return 5;
	default: return 4;	/* 10G */
	}
}

static void force_link(int port, bool en, bool up)
{
	u32 v = sw_r(MAC_FORCE(port)) & ~3;

	sw_w(MAC_FORCE(port), v | (en ? 1 : 0) | (up ? 2 : 0));
	if (en)
		sw_rmw(MAC_FORCE(port), 7 << 3, media_spd(port) << 3);
}

/* ---- CMU clock-ready wait + 10GR FSM check (shared by the stock and the SDK force path) ---- */

static bool clk_ready(unsigned int sds, unsigned int l0, int mode, int first_ms, bool dal)
{
	int bit = l0 == sds ? 4 : 5, hi, lo, i;
	u16 r0, r1, r2, keep, lnk = 0;
	ulong t0 = get_timer(0);

	for (i = 0; i < CLK_TRIES; i++) {
		mdelay(first_ms);
		wr(l0, 0x1f, 2, 0x35);			/* debug-out select: CMU status */
		r0 = hfr(l0, 0x1f, 0x14, bit, bit);
		mdelay(10);
		r1 = hfr(l0, 0x1f, 0x14, bit, bit);
		mdelay(10);
		r2 = hfr(l0, 0x1f, 0x14, bit, bit);
		if (r0 && r1 && r2) {
			if (mode != M_10GR)
				return true;
			/* 10GR: AFE loopback, FSM reset, read block lock twice, restore */
			keep = hfr(sds, 6, 1, 2, 2);
			hfw(sds, 6, 1, 2, 2, 1);
			hfw(sds, 6, 2, 12, 12, 1);
			mdelay(10);
			hfw(sds, 6, 2, 12, 12, 0);
			mdelay(10);
			lnk = hfr(sds, 5, 0, 12, 12);
			lnk = hfr(sds, 5, 0, 12, 12);
			hfw(sds, 6, 1, 2, 2, keep);
			hfw(sds, 6, 2, 12, 12, 1);
			mdelay(10);
			hfw(sds, 6, 2, 12, 12, 0);
			mdelay(10);
			if (lnk)
				return true;
		}
		hi = mode == M_10GR ? 3 : 1;
		lo = hi - 1;
		if (dal) {
			dfw(l0, 0x21, 0xb, hi, lo, 2);
			mdelay(10);
			dfw(l0, 0x21, 0xb, hi, lo, 3);
		} else {
			hfw(l0, 0x21, 0xb, hi, lo, 2);
			mdelay(10);
			hfw(l0, 0x21, 0xb, hi, lo, 3);
		}
	}
	printf("rtk: SerDes %u: CMU not ready after %d tries (%lu ms)\n", sds, CLK_TRIES,
	       get_timer(t0));
	rtk_led_error("sds-cmu");
	return false;
}

/* "Turn On Serdes" per SerDes: stock sds_mode_10gr_set (raw writes, LC 10.3125G + ring 1.25G) */
static void construct_force(unsigned int sds, int mode)
{
	unsigned int l0 = sds & ~1;
	bool even = l0 == sds;

	hfw(sds, 0x20, 0, 7, 6, 3);		/* force power down */
	hfw(sds, 0x1f, 9, 6, 6, 1);		/* force mode on */
	hfw(sds, 0x1f, 9, 11, 7, 0x1f);		/* mode off */
	if (mode == M_DISABLE)
		return;
	hfw(l0, 0x20, 0x12, 3, 0, 0xf);		/* LC + ring enable */
	hfw(l0, 0x20, 0x12, even ? 5 : 7, even ? 4 : 6, 1);
	hfw(sds, 0x20, 0, 5, 4, 3);
	hfw(l0, 0x20, 0x12, 11, 8, 5);		/* LC 10.3125G */
	hfw(l0, 0x20, 0x12, 15, 12, 1);		/* ring 1.25G */
	hfw(l0, 0x21, 0xb, 3, 0, 0xf);
	hfw(l0, 0x20, 0x12, even ? 5 : 7, even ? 4 : 6, mode == M_10GR ? 3 : 1);
	hfw(sds, 0x1f, 9, 6, 6, 1);
	hfw(sds, 0x1f, 9, 11, 7, mode == M_1000BX ? 4 : mode == M_100BX ? 5 : 0x1a);
	if (mode == M_100BX) {
		hfw(sds, 2, 0, 12, 12, 0);
		hfw(sds, 2, 0, 6, 6, 0);
		hfw(sds, 2, 0, 13, 13, 1);
	}
	clk_ready(sds, l0, mode, 200, false);
	hfw(sds, 0x20, 0, 7, 6, 0);		/* release power down */
	hfw(sds, 0x2e, 0x15, 4, 4, 1);		/* RX reset */
	mdelay(5);
	hfw(sds, 0x2e, 0x15, 4, 4, 0);
}

/* ---- SDK dal_longan_sds_mode_set / _dal_longan_sds_10gSdsMode_force ---- */

static int hw_mode(unsigned int sds)
{
	int v = dfr(sds, 0x1f, 9, 11, 7);

	if (!v)
		v = (rtk_sds_mode(sds) & 0x1f);	/* MAC SDS_MODE_SEL */
	switch (v) {
	case 0x02: return M_SGMII;
	case 0x04: return M_1000BX;
	case 0x05: return M_100BX;
	case 0x12: return M_HISGMII;
	case 0x16: return M_2500BX;
	case 0x1a: return M_10GR;
	default: return M_DISABLE;
	}
}

static bool is_1000(int m)
{
	return m == M_1000BX || m == M_SGMII || m == M_100BX;
}

/* _dal_longan_sds_pll_cfg: every SerDes here has profile mode 10GR; 0xf00d = chip not supported */
static int pll_cfg(unsigned int sds, int mode, bool *lc)
{
	unsigned int l0 = sds & ~1;

	*lc = mode == M_10GR;
	if (is_1000(mode) && hfr(l0, 0x20, 18, 15, 8) == 0x35)
		return 0xf00d;
	if ((mode == M_2500BX || mode == M_HISGMII) && is_1000(hw_mode(sds ^ 1)))
		return 0xf00d;
	return 0;
}

static int sdk_force(unsigned int sds, int mode)
{
	unsigned int l0 = sds & ~1;
	bool even = l0 == sds, lc;
	int val, lcv, ret;

	switch (mode) {
	case M_DISABLE: val = 0x1f; lcv = 0; break;
	case M_10GR: val = 0x1a; lcv = 5; break;
	case M_1000BX: val = 4; lcv = 1; break;
	case M_SGMII: val = 2; lcv = 1; break;
	case M_HISGMII: val = 0x12; lcv = 3; break;
	case M_2500BX: val = 0x16; lcv = 3; break;
	case M_100BX: val = 5; lcv = 1; break;
	default: return -1;	/* RT_ERR_FAILED */
	}
	ret = pll_cfg(sds, mode, &lc);
	if (ret)
		return ret;
	dfw(sds, 0x20, 0, 7, 6, 3);
	dfw(sds, 0x1f, 9, 6, 6, 1);
	dfw(sds, 0x1f, 9, 11, 7, 0x1f);
	if (mode == M_DISABLE) {
		if (f100m[sds]) {
			dfw(sds, 2, 0, 12, 12, 1);
			dfw(sds, 2, 0, 6, 6, 1);
			dfw(sds, 2, 0, 13, 13, 0);
			f100m[sds] = false;
		}
		return 0;
	}
	dfw(l0, 0x20, 18, even ? 5 : 7, even ? 4 : 6, 1);
	dfw(sds, 0x20, 0, 5, 4, 3);
	if (lc)
		dfw(l0, 0x20, 18, 11, 8, lcv);
	else
		dfw(l0, 0x20, 18, 15, 12, lcv);
	dfw(l0, 0x20, 18, even ? 5 : 7, even ? 4 : 6, lc ? 3 : 1);
	if (lc)
		dfw(l0, 0x20, 18, 1, 0, 3);	/* LC enable */
	else
		dfw(l0, 0x20, 18, 3, 2, 3);	/* ring enable */
	dfw(sds, 0x1f, 9, 6, 6, 1);
	dfw(sds, 0x1f, 9, 11, 7, val);
	if (mode == M_100BX) {
		dfw(sds, 2, 0, 12, 12, 0);
		dfw(sds, 2, 0, 6, 6, 0);
		dfw(sds, 2, 0, 13, 13, 1);
		f100m[sds] = true;
	}
	clk_ready(sds, l0, mode, 150, true);
	dfw(sds, 0x20, 0, 7, 6, 0);
	dfw(sds, 0x2e, 0x15, 4, 4, 1);
	mdelay(5);
	dfw(sds, 0x2e, 0x15, 4, 4, 0);
	return 0;
}

/* dal_longan_sds_rxCaliRegDefault_init -> _dal_longan_sds_rxCali_a_start_1d1 (serdes params) */
static void rxcal_defaults(unsigned int sds, bool fiber10g)
{
	static const struct { u8 page, reg, hi, lo; u16 v; } t[] = {
		{ 0x2e, 0x1e, 15, 15, 1 }, { 0x2e, 0x01, 14, 14, 0 }, { 0x2e, 0x1c, 10, 5, 0x20 },
		{ 0x2f, 0x02, 0, 0, 1 },					/* FGCAL */
		{ 0x2e, 0x1e, 14, 11, 0 }, { 0x2e, 0x01, 15, 15, 1 }, { 0x2e, 0x02, 11, 11, 1 },
		{ 0x2e, 0x1c, 4, 0, 0 }, { 0x2e, 0x1d, 15, 11, 0 }, { 0x2e, 0x1d, 10, 6, 0 },
		{ 0x2e, 0x1d, 5, 1, 0 }, { 0x2e, 0x02, 10, 6, 0 }, { 0x2e, 0x11, 4, 0, 0 },
		{ 0x2f, 0x00, 3, 0, 0xf }, { 0x2e, 0x04, 6, 6, 1 }, { 0x2e, 0x04, 7, 7, 1 },	/* DCVS */
		{ 0x2e, 0x16, 14, 8, 0x20 }, { 0x2e, 0x03, 13, 8, 0x0a }, { 0x2e, 0x00, 13, 13, 0 },
		{ 0x2f, 0x03, 5, 0, 0x1f }, { 0x2e, 0x09, 11, 6, 0 }, { 0x2e, 0x09, 5, 0, 0 },	/* DFE */
		{ 0x2e, 0x0a, 5, 0, 0 }, { 0x2f, 0x01, 5, 0, 0 }, { 0x2f, 0x12, 5, 0, 0 },
		{ 0x2e, 0x0a, 11, 6, 0 }, { 0x2e, 0x06, 5, 0, 0 }, { 0x2f, 0x01, 5, 0, 0 },
		{ 0x2e, 0x13, 5, 3, 7 }, { 0x2e, 0x13, 2, 0, 7 }, { 0x2f, 0x0b, 5, 3, 1 },	/* Vth */
		{ 0x2e, 0x0f, 13, 7, 0x7f },						/* 1.1.2 */
		{ 0x2e, 0x17, 7, 7, 0 }, { 0x2e, 0x17, 6, 2, 0 }, { 0x2e, 0x0c, 8, 8, 0 },
		{ 0x2e, 0x0b, 4, 4, 1 }, { 0x2e, 0x12, 14, 14, 0 }, { 0x2f, 0x02, 15, 15, 0 },
		{ 0x2e, 0x0f, 15, 14, 3 },						/* 1.1.4 */
	};
	int i;

	wr(sds, 6, 0, 0);
	for (i = 0; i < ARRAY_SIZE(t); i++)
		hfw(sds, t[i].page, t[i].reg, t[i].hi, t[i].lo, t[i].v);
	if (fiber10g) {
		hfw(sds, 0x2e, 0x03, 13, 8, 0x1f);
		hfw(sds, 0x2e, 0x00, 13, 13, 1);
		hfw(sds, 0x2e, 0x16, 14, 8, 0);
	}
	hfw(sds, 0x2e, 0x16, 3, 2, 2);
	hfw(sds, 0x2e, 0x0f, 6, 0, 0x5f);
	hfw(sds, 0x2f, 0x05, 7, 2, 0x1f);
}

static int sds_mode_set(unsigned int sds, int mode)
{
	int port = sds_port(sds);
	u32 keep = sw_r(MAC_FORCE(port)) & 3;

	force_link(port, true, false);
	mdelay(20);
	sdk_force(sds, M_DISABLE);
	force_link(port, keep & 1, keep & 2);
	rxcal_defaults(sds, media[port] == MEDIA_10G);
	return mode == M_DISABLE ? 0 : sdk_force(sds, mode);
}

/* ---- phy_9300_10gMedia_set / phy_9300_enable_set ---- */

static int media_set(int port, int m)
{
	int sds = port_sds(port), ret, sel;

	if (sds < 0)
		return port == CPU_PORT ? 0xf030 : 0xf003;	/* no PHY driver / no such port */
	media[port] = m;
	if (!admin[port])
		return 0;
	sel = m == MEDIA_1G || m == MEDIA_SGMII ? 2 : m == MEDIA_100M || m == MEDIA_2_5G ? 1 : 0;
	if (sel)	/* BMCR speed select (bits 6, 13) */
		dfw(sds, 2, 0, 13, 13, sel & 1), dfw(sds, 2, 0, 6, 6, sel >> 1);
	switch (m) {
	case MEDIA_NONE:
		ret = sds_mode_set(sds, M_DISABLE);
		mdelay(50);
		return ret;
	case MEDIA_10G:
		ret = sds_mode_set(sds, M_10GR);
		break;
	case MEDIA_DAC50 ... MEDIA_DAC500:
		ret = sds_mode_set(sds, M_10GR);
		if (!ret)
			dfw(sds, 6, 13, 6, 6, 0);	/* CFG_LINKDW_SEL: DAC */
		mdelay(50);
		return ret;
	case MEDIA_1G:
		ret = sds_mode_set(sds, M_1000BX);
		break;
	case MEDIA_SGMII:
		ret = sds_mode_set(sds, M_SGMII);
		break;
	case MEDIA_100M:
		ret = sds_mode_set(sds, M_100BX);
		break;
	case MEDIA_2_5G:
		ret = sds_mode_set(sds, M_2500BX);
		break;
	default:
		return 0xf001;
	}
	if (ret)
		return ret;
	dfw(sds, 6, 13, 6, 6, 1);	/* CFG_LINKDW_SEL: fibre */
	mdelay(50);
	force_link(port, false, false);
	return 0;
}

static void phy_enable(int port, bool on)
{
	int sds = port_sds(port);

	if (sds < 0)
		return;
	dfw(sds, 2, 0, 11, 11, !on);	/* 1G block BMCR power down */
	dfw(sds, 4, 0, 11, 11, !on);	/* 10G block */
	admin[port] = on;
	if (on) {
		media_set(port, media[port]);
	} else {
		force_link(port, true, false);
		sds_mode_set(sds, M_DISABLE);
	}
}

/* ---- port LEDs: stock mac_led_config 0x83f6f768 (SDK rtl9300_led_config + SW-control tail) ---- */

#define LED_GLB		0xcc00			/* [26:25] stack, [22] active, [3:2] pwr-on blink, [1:0] mode */
#define LED_NUM(p)	(0xcc04 + ((p) >> 4) * 4)	/* 2 bits/port: LEDs per port - 1 */
#define LED_SET(s, i)	(0xcc28 - (s) * 8 - ((i) >> 1) * 4)	/* SETs_0 = LED1:LED0, SETs_1 = LED3:LED2 */
#define LED_COPR_SEL(p)	(0xcc2c + ((p) >> 4) * 4)	/* 2 bits/port: copper LED set */
#define LED_FIB_SEL(p)	(0xcc34 + ((p) >> 4) * 4)
#define LED_COPR_MASK	0xcc3c
#define LED_FIB_MASK	0xcc40
#define LED_COMBO_MASK	0xcc44
#define LED_SW_LOAD	0xcc48
#define LED_SW_EN(p)	(0xcc4c + ((p) >> 3) * 4)	/* 4 bits/port */
#define LED_SW_CTRL(p)	(0xcc5c + (p) * 4)		/* fibre LED0-3 modes [23:12] */

/* Values: stock RTL9303_8XGE profile (scripts/stock_led_profile.py): 3 LEDs, set 0 copper + fibre,
 * single set, serial, led_active 0 -> GLB[22] = 1. Fields: stock reg table 0x83fa9ad8 idx 0x16-0x27. */
void rtk_led_config(void)
{
	static const u16 set0[4] = { 0xa01, 0xa08, 0xba0, 0xffff };	/* LED3 = HWP_LED_END, masked */
	int c, p, s, i, sh;

	sw_rmw(LED_GLB, GENMASK(26, 25), 0);		/* f6f52c: stack sync off (no cascade) */
	sw_w(LED_COPR_MASK, 0);				/* f6ee1c */
	sw_w(LED_FIB_MASK, 0);
	sw_w(LED_COMBO_MASK, 0);
	for (c = 0; c < NCAGES; c++) {			/* f6ee70: 3 LEDs -> 2 */
		p = rtk_cage_port[c];
		sh = (p & 15) * 2;
		sw_rmw(LED_NUM(p), 3U << sh, 2U << sh);
	}
	for (c = 0; c < NCAGES; c++) {			/* f6f080: masks + set select */
		p = rtk_cage_port[c];
		sh = (p & 15) * 2;
		sw_rmw(LED_COPR_MASK, BIT(p), BIT(p));
		sw_rmw(LED_FIB_MASK, BIT(p), BIT(p));
		sw_rmw(LED_COMBO_MASK, BIT(p), BIT(p));
		sw_rmw(LED_COPR_SEL(p), 3U << sh, 0);
		sw_rmw(LED_FIB_SEL(p), 3U << sh, 0);
	}
	for (s = 0; s < 4; s++)				/* f6f2b4: sets 1-3 unused = 0 */
		for (i = 0; i < 4; i++)
			sw_rmw(LED_SET(s, i), 0xffffU << (i & 1) * 16,
			       (u32)(s ? 0 : set0[i]) << (i & 1) * 16);
	sw_rmw(LED_GLB, BIT(22), BIT(22));		/* f6ef9c: active, no pwr-on blink, serial */
	sw_rmw(LED_GLB, GENMASK(3, 2), 0);
	sw_rmw(LED_GLB, GENMASK(1, 0), 1);
	for (c = 0; c < NCAGES; c++) {			/* f6f57c: SW control, fibre modes 0, load */
		p = rtk_cage_port[c];
		sh = (p & 7) * 4;
		sw_rmw(LED_SW_CTRL(p), GENMASK(23, 12), 0);
		sw_rmw(LED_SW_EN(p), 0xfU << sh, 0xfU << sh);
		sw_rmw(LED_SW_LOAD, BIT(0), BIT(0));
	}
}

/* stock mac_park_tx_disable 0x83f6f710 (end of mac_led_config): expander cfg 0xff, out 0xff = all lasers off */
static void park_tx_disable(void)
{
	struct udevice *dev = rtk_chip(EXP_BUS, EXP_ADDR);
	u8 v = 0xff;

	if (!dev || dm_i2c_write(dev, EXP_CFG, &v, 1) || dm_i2c_write(dev, EXP_OUT, &v, 1)) {
		printf("laser expander not responding: lasers not parked\n");
		rtk_led_error("laser-park");
	}
}

/* ---- chip construct (dal_longan_construct table, stock 0x83fa3718) ---- */

static void construct(void)
{
	static const char *const rtcore[] = {
		"RTCORE Driver Module Initialize", "  IOAL init", "  Hardware-profile probe (RTL9303_8XGE)",
		"  Hardware-profile init", "  GPIO probe (unit 0): (found)", "  GPIO Init",
		"  SPI init (unit 0) (type3)", "    SPI Master init", "  I2C probe (unit 0)",
		"  I2C init (unit 0)", "  I2C device init (unit 0)", "  I2C device init (unit 0)",
		"  I2C device init (unit 0)", "  I2C device init (unit 0)", "  I2C device init (unit 0)",
		"  I2C device init (unit 0)", "  I2C device init (unit 0)", "  I2C device init (unit 0)",
		"  I2C device init (unit 0)", "  SFP insert init (unit 0)", "  NIC probe (unit 0)",
		"  Loader RTNIC Driver Module Initialize", "  IOAL init", "RTK Driver Module Initialize",
		"  MAC probe (unit 0)", "    Chip 9303 (found)", "  MAC init (unit 0)",
		"  SMI protocol probe (unit 0)", "  PHY probe (unit 0)", "  Chip Construct (unit 0)",
		"    Chip Construct",
	};
	unsigned int s, i, n;
	const struct sds_cfg *t;

	for (i = 0; i < ARRAY_SIZE(rtcore); i++) {	/* stock banner; RTCORE/L2 defaults not run */
		printf("%s\n", rtcore[i]);
		if (!strcmp(rtcore[i], "  NIC probe (unit 0)"))
			sw_w(MAC_FORCE(CPU_PORT), CPU_FORCE);
		if (!strcmp(rtcore[i], "  MAC init (unit 0)")) {	/* stock mac_driver_init order */
			rtk_led_config();
			park_tx_disable();
			sw_rmw(SMI_MAC_TYPE, SMI_MAC_TYPE_M, 0);
		}
	}
	printf("    Disable PHY Polling\n");
	sw_rmw(SMI_POLL_CTRL, 0x0fffffff, 0);
	mdelay(3);
	printf("    PHY Reset\n");			/* no PHY on this board */
	printf("    MAC Construct\n");		/* polarity normal (profile), raw page 6/0 */
	for (s = 2; s <= 9; s++) {
		hfw(s, 6, 2, 13, 13, 0);
		hfw(s, 0, 0, 9, 9, 0);
		hfw(s, 6, 2, 14, 14, 0);
		hfw(s, 0, 0, 8, 8, 0);
	}
	printf("    Turn Off Serdes\n");
	for (s = 0; s < 12; s++)
		rtk_mac_mode_set(s, 0x1f);
	printf("    Serdes Construct\n");
	for (s = 2; s <= 9; s++) {
		t = s & 1 ? sds_10gr_odd : sds_10gr_even;
		n = s & 1 ? ARRAY_SIZE(sds_10gr_odd) : ARRAY_SIZE(sds_10gr_even);
		for (i = 0; i < n; i++)
			wr(dsds(s, t[i].page), t[i].page, t[i].reg, t[i].data);
		hfw(s, 0x1f, 0xb, 1, 1, 1);	/* mac_default_10gmedia_fiber */
	}
	printf("    PHY Construct\n");
	printf("    Turn On Serdes\n");
	for (s = 2; s <= 9; s++)
		construct_force(s, M_10GR);
	printf("    Mac_Polling_PHY Config\n");
	sw_rmw(SMI_PRVTE_POLL, 0x0fffffff, 0);
	printf("    Enable PHY Polling\n");
	sw_rmw(SMI_POLL_CTRL, 0x0fffffff, ETHER_PMASK);
	printf("    Misc\n");
	printf("  PHY init (unit 0)\n");
	for (s = 2; s <= 9; s++)
		dfw(s, 0, 4, 2, 2, 1);		/* phy_9300_init: fiberNwayForceLink */
	printf("  Mgmt_dev init (unit 0) \n");
	constructed = true;
}

/* ---- port isolation table (LONGAN_PORT_ISO_CTRLt) ---- */

static int iso_set(int port, u32 pmask)
{
	int i;

	sw_w(ISO_DATA, pmask << 3);
	sw_w(ISO_CTRL, BIT(17) | BIT(16) | ISO_TYPE << 12 | port);
	for (i = 0; i < ISO_POLL_N; i++) {
		if (!(sw_r(ISO_CTRL) & BIT(17)))
			return 0;
		udelay(10);
	}
	printf("rtk: isolation table write port %d busy after %d us\n", port, ISO_POLL_N * 10);
	rtk_led_error("iso-table");
	return 0xf011;	/* RT_ERR_TIMEOUT? SPEC */
}

/* our loop guard: front ports forward to nothing but the CPU port (cage loop #19) */
static void iso_guard(void)
{
	int i;

	for (i = 0; i < NCAGES; i++)
		iso_set(rtk_cage_port[i], BIT(CPU_PORT));
}

/* ---- media per cage: Linux sfp_select_interface, unless env rtk_media=stock ---- */

static int cage_media(int cage)
{
	const char *why, *e = env_get("rtk_media");
	int itf;

	if (e && !strcmp(e, "stock"))
		return MEDIA_10G;
	itf = rtk_sfp_iface(cage, &why);
	switch (itf) {
	case RTK_IF_1000BX: return MEDIA_1G;
	case RTK_IF_SGMII: return MEDIA_SGMII;
	case RTK_IF_2500BX: return MEDIA_2_5G;
	case RTK_IF_100BX: return MEDIA_100M;
	default: return MEDIA_10G;	/* 10GR, empty cage, unreadable: stock default */
	}
}

static const char *const media_names[] = {
	"none", "fiber10g", "fiber1g", "fiber2.5g", "fiber100m", "dac50cm", "dac100cm", "dac300cm",
	"dac500cm",
};

const char *rtk_media_name(int port)
{
	if (port < 0 || port >= NPORTS || !net_on)
		return "-";
	if (media[port] == MEDIA_SGMII)
		return "sgmii";
	return media[port] < ARRAY_SIZE(media_names) ? media_names[media[port]] : "?";
}

/* ---- verbs ---- */

static void network_on(void)
{
	int c, port, m, ret;
	ulong t0 = get_timer(0);

	io_err = 0;
	if (!constructed)
		construct();
	printf("Please wait for PHY init-time ...\n\n");
	for (c = 1; c <= NCAGES; c++) {
		port = rtk_cage_port[c - 1];
		phy_enable(port, true);
		m = cage_media(c);
		ret = media_set(port, m);
		if (ret)	/* e.g. 0xf00d: 1G next to a 2.5G pair partner (shared ring PLL) */
			printf("rtk: cage %d media %d: FAIL (0x%x)\n", c, m, ret);
	}
	printf("Err:0x%x:FAIL (0x%x)\n", 0xf030, 0xf030);	/* stock: CPU port has no PHY driver */
	iso_guard();
	net_on = true;
	mdelay(2000);	/* stock: link-status settle */
	if (io_err) {
		printf("rtk: %d SerDes access errors during network on (%lu ms)\n", io_err,
		       get_timer(t0));
		rtk_led_error("sds-io");
	}
}

int rtk_network(int argc, char *const argv[])
{
	int c;

	if (!strcmp(argv[2], "on")) {
		printf("Enable network\n");
		network_on();
		return 0;
	}
	printf("Disable network\n");
	if (!constructed)
		return 0;	/* stock: no unit probed yet, nothing to do */
	for (c = 1; c <= NCAGES; c++)
		phy_enable(rtk_cage_port[c - 1], false);
	net_on = false;
	return 0;
}

/* `rtk 10g <port> <media>`: argv[3] already validated against the stock media list */
int rtk_10g(int argc, char *const argv[])
{
	unsigned long port = dectoul(argv[2], NULL);
	int m, ret;

	for (m = 0; m < ARRAY_SIZE(media_names); m++)
		if (!strcmp(argv[3], media_names[m]))
			break;
	if (!constructed) {
		printf("FAIL (0x%x)\n", 0xf002);	/* stock before network on: unit not probed */
		return 0;
	}
	if (port >= NPORTS || !rtk_port_exists(port)) {
		printf("FAIL (0x%x)\n", 0xf003);
		return 0;
	}
	ret = media_set(port, m);
	if (ret)
		printf("FAIL (0x%x)\n", ret);
	return 0;
}

/* `macsds set` after the stock text: dal_longan_sds_macSds_set = SDK force, no MAC/rx-cal steps */
int rtk_macsds_apply(unsigned int sds, unsigned int mode)
{
	int ret;

	if (!constructed) {
		printf("Chip not supported\n");	/* SPEC: stock before network on, unverified */
		return 1;
	}
	printf("unit %u sds %u mode %u\n", 0, sds, mode);
	if (sds < 2 || sds > 9)
		ret = 0xf00c;
	else if (mode >= M_END)
		ret = 0xf001;
	else
		ret = sdk_force(sds, mode);
	if (ret)
		printf("FAIL (0x%x)\n", ret);
	return 1;
}

/* stock pairs consecutive ports (0<->8, 16<->20, 24<->25, 26<->27); off = all ports incl. CPU */
int rtk_port_isolation(int argc, char *const argv[])
{
	u32 all = 0;
	int i, a, b, ret;

	for (i = 0; i < NCAGES; i++)
		all |= BIT(rtk_cage_port[i]);
	all |= BIT(CPU_PORT);
	if (!strcmp(argv[2], "off")) {
		for (i = 0; i < NCAGES; i++) {
			ret = iso_set(rtk_cage_port[i], all);
			if (ret)
				printf("isolation disable fail(%d): source=%u, destination=ALL\n", ret,
				       rtk_cage_port[i]);
		}
		return 0;
	}
	printf("\nUnit %u\n", 0);
	for (i = 0; i + 1 < NCAGES; i += 2) {
		a = rtk_cage_port[i];
		b = rtk_cage_port[i + 1];
		printf("isolation: %2u <--> %2u\n", a, b);
		ret = iso_set(a, BIT(b));
		if (ret)
			printf("isolation fail(%d): source=%u, destination=%u\n", ret, a, b);
		ret = iso_set(b, BIT(a));
		if (ret)
			printf("isolation fail(%d): source=%u, destination=%u\n", ret, b, a);
	}
	return 0;
}

/* `rtk sdsdump [sds|all]`: pages 0-7 and 0x1f-0x2f, one line per page (parsed by reg_diff.py) */
int rtk_sdsdump(int argc, char *const argv[])
{
	static const u8 pages[] = { 0, 1, 2, 3, 4, 5, 6, 7, 0x1f, 0x20, 0x21, 0x22, 0x23, 0x24,
				    0x25, 0x26, 0x27, 0x28, 0x29, 0x2a, 0x2b, 0x2c, 0x2d, 0x2e, 0x2f };
	unsigned int s, lo = 2, hi = 9, p, r;
	u16 v;

	if (argc > 2 && strcmp(argv[2], "all"))
		lo = hi = dectoul(argv[2], NULL);
	if (hi > 11)
		return CMD_RET_USAGE;
	for (s = lo; s <= hi; s++) {
		for (p = 0; p < ARRAY_SIZE(pages); p++) {
			printf("sds %u page 0x%02x:", s, pages[p]);
			for (r = 0; r < 32; r++) {
				if (rtk_sds_read(s, pages[p], r, &v))
					printf(" ----");
				else
					printf(" %04x", v);
			}
			printf("\n");
		}
	}
	return 0;
}
