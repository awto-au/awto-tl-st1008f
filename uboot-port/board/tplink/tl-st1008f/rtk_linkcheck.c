// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk linkcheck`: which cages are live and which are looped, before anything bridges (#97, #19).
 * 1. All lasers off: per fitted cage DDM RX power, soft RX_LOS, MAC link, copper PHY link.
 *    Light with our lasers off = a powered far end. No RX_LOS pin is wired on this board.
 * 2. One laser at a time: RX rising on another cage = passive cage-to-cage cable.
 * 3. Loop probe: per live cage, one broadcast out that cage; seen on another cage = loop.
 * Lasers restored after. Output parsed by scripts/linkcheck.py.
 */

#include <command.h>
#include <dm.h>
#include <i2c.h>
#include <linux/delay.h>
#include "rtk.h"
#include "sfp/sfp.h"

#define MAC_LINK_STS	0xcb10
#define A0		0x50
#define A2		0x51
#define PHY		0x56
#define RX_LIVE		50	/* 0.1 uW units: 5 uW = -23 dBm; a dark SR reads 0.1 uW */
/* DDM ADC refresh after a laser change: SFF-8472 sets none; module datasheets give <= 100 ms.
 * x1.25. Too short = a loop reads dark (missed), never a false loop. */
#define SETTLE_MS	125
/* Probe frame back through an external switch: 2 store-and-forward hops ~30 us at 1G; a Linux
 * software bridge adds < 1 ms. 10 ms bound; expiry = no loop seen on that cage. */
#define LOOP_WAIT_MS	10

struct lc {
	bool pres, ddm, copper, live;
	int rx, los, mac, phy;	/* rx 0.1 uW (-1 none); los/mac/phy 1/0, -1 = n/a */
	char pn[17];
};

static int lasers(u8 out)
{
	struct udevice *dev = rtk_chip(EXP_BUS, EXP_ADDR);
	u8 cfg = 0;

	if (!dev || dm_i2c_write(dev, EXP_OUT, &out, 1) || dm_i2c_write(dev, EXP_CFG, &cfg, 1))
		return -EIO;
	return 0;
}

static bool mac_up(int cage)
{
	sw_r(MAC_LINK_STS);	/* latched low: second read = now */
	return sw_r(MAC_LINK_STS) & BIT(rtk_cage_port[cage - 1]);
}

/* A2 RX power + soft RX_LOS; -1 when the module has no DDM or A2 does not answer */
static void ddm_rx(int cage, const u8 *id, struct lc *c)
{
	struct udevice *dev = rtk_chip(cage - 1, A2);
	struct sff_diags sd;
	u8 a2[128];

	c->rx = -1;
	c->los = -1;
	if (!c->ddm || !dev || dm_i2c_read(dev, 0, a2, sizeof(a2)))
		return;
	sff8472_diags(id, a2, &sd);
	c->rx = sd.rx_power[MCURR];
	if (id[93] & 0x10)	/* A0 93 bit 4: soft RX_LOS implemented; A2 110 bit 1 = state */
		c->los = !!(a2[110] & 0x02);
}

/* One PHY byte: up to 5 tries 1 ms apart; the module MCU NACKs while busy (as cmd_rtk.c phy_byte) */
static int phy_byte(struct udevice *dev, int r, u8 *b)
{
	int tries;

	for (tries = 0; dm_i2c_read(dev, r, b, 1); tries++) {
		if (tries == 4)
			return -EIO;
		mdelay(1);
	}
	return 0;
}

/* Copper module PHY BMSR link (reg 1 bit 2, latched low: read twice). 16-bit = MSB then LSB
 * byte reads of one reg; ID1 0x4101 = pointer off by one, one extra byte realigns (cmd_rtk.c). */
static int phy_link(int cage)
{
	struct udevice *dev = rtk_chip(cage - 1, PHY);
	u8 hi, lo;
	int i;

	if (!dev || phy_byte(dev, 2, &hi) || phy_byte(dev, 2, &lo))
		return -1;
	if (hi == 0x41 && lo == 0x01 && phy_byte(dev, 2, &hi))
		return -1;
	for (i = 0; i < 2; i++)
		if (phy_byte(dev, 1, &hi) || phy_byte(dev, 1, &lo))
			return -1;
	return !!(lo & 0x04);
}

static void scan(struct lc *c, bool ids)
{
	u8 id[96];
	int n, i;

	for (n = 1; n <= NCAGES; n++, c++) {
		if (ids) {
			memset(c, 0, sizeof(*c));
			c->pres = !(__raw_readl((void __iomem *)GPIO_DAT) & BIT(n - 1));
			c->phy = -1;
			if (!c->pres || rtk_sfp_read_id(n, id)) {
				c->rx = c->los = -1;
				continue;
			}
			memcpy(c->pn, id + 40, 16);
			for (i = 15; i >= 0 && (c->pn[i] == ' ' || !c->pn[i]); i--)
				c->pn[i] = 0;
			c->ddm = id[92] & 0x40;
			/* 1000BASE-T bit, RJ45 connector, or 10GBASE-T ext. compliance (0x16/0x1c):
			 * no laser, TX-disable often ignored; SFP-10G-T fakes DDM (RX 0, LOS 1) */
			c->copper = (id[6] & 0x08) || id[2] == 0x22 || id[36] == 0x16 || id[36] == 0x1c;
		} else if (!c->pres || !c->ddm) {
			continue;
		} else {
			rtk_sfp_read_id(n, id);
		}
		ddm_rx(n, id, c);
		c->mac = mac_up(n);
		if (ids && c->copper && (id[6] & 0x08))	/* 88E1111 at 0x56; AQR113C (RollBall) not read */
			c->phy = phy_link(n);
	}
}

static void pr_rx(int rx)
{
	if (rx < 0)
		printf("-");
	else
		printf("%d.%d uW", rx / 10, rx % 10);
}

int rtk_linkcheck(int argc, char *const argv[])
{
	static const char magic[] = "ST1008F-LINKCHECK";
	struct udevice *exp = rtk_chip(EXP_BUS, EXP_ADDR);
	struct lc a[NCAGES], b[NCAGES];
	bool probe = !(argc > 1 && !strcmp(argv[1], "noprobe"));
	char *on[] = { "rtk", "network", "on", NULL };
	u8 out0, cfg0, mg[sizeof(magic) + 1];
	int n, m, live = 0, loops = 0;
	u32 hits;

	if (!exp || dm_i2c_read(exp, EXP_OUT, &out0, 1) || dm_i2c_read(exp, EXP_CFG, &cfg0, 1)) {
		printf("linkcheck: laser expander not responding\n");
		return CMD_RET_FAILURE;
	}
	if (!rtk_net_is_on())
		rtk_network(3, on);	/* MAC link and the NIC need the switch set up */
	rtk_iso_guard();		/* cages forward to the CPU only: the probe cannot loop in the ASIC */
	if (lasers(0xff))
		goto exp_fail;
	mdelay(SETTLE_MS);
	scan(a, true);
	for (n = 1; n <= NCAGES; n++) {
		struct lc *c = &a[n - 1];

		if (!c->pres)
			continue;
		/* copper PHY unreadable: TX-disable is often ignored, so a link cannot be ruled out */
		c->live = c->phy == 1 || (c->copper && c->phy < 0) ||
			  (!c->copper && (c->rx >= RX_LIVE || c->los == 0)) || c->mac == 1;
		live += c->live;
		printf("linkcheck cage %d: %s, rx ", n, c->pn[0] ? c->pn : "?");
		pr_rx(c->rx);
		printf(", los %s, mac %s, phy %s, live %s\n", c->los < 0 ? "-" : c->los ? "1" : "0",
		       c->mac ? "up" : "down", c->phy < 0 ? "-" : c->phy ? "up" : "down",
		       c->live ? "YES" : "no");
	}
	for (n = 1; n <= NCAGES; n++) {	/* passive cable: our own light comes back on another cage */
		if (!a[n - 1].pres || a[n - 1].copper)
			continue;
		if (lasers(0xff & ~BIT(n - 1)))
			goto exp_fail;
		mdelay(SETTLE_MS);
		memcpy(b, a, sizeof(b));
		scan(b, false);
		for (m = 1; m <= NCAGES; m++) {
			if (m == n || !b[m - 1].pres || b[m - 1].rx < RX_LIVE || a[m - 1].rx >= RX_LIVE)
				continue;
			loops++;
			printf("linkcheck loop %d->%d: passive (cage %d light at cage %d: ", n, m, n, m);
			pr_rx(b[m - 1].rx);
			printf(")\n");
		}
	}
	for (n = 1; probe && n <= NCAGES; n++) {	/* frame loop through the far-end network */
		if (!a[n - 1].live)
			continue;
		snprintf((char *)mg, sizeof(mg), "%s%d", magic, n);
		if (lasers(0xff & ~BIT(n - 1)))	/* probe start skips the laser when n is already ethport */
			goto exp_fail;
		if (rtl930x_eth_loop_probe(n, mg, sizeof(mg), LOOP_WAIT_MS, &hits)) {
			printf("linkcheck probe %d: send failed\n", n);
			continue;
		}
		hits &= ~BIT(rtk_cage_port[n - 1]);
		for (m = 1; m <= NCAGES; m++)
			if (hits & BIT(rtk_cage_port[m - 1])) {
				loops++;
				printf("linkcheck loop %d->%d: frame (probe out cage %d came back on cage %d)\n",
				       n, m, n, m);
			}
	}
	if (dm_i2c_write(exp, EXP_OUT, &out0, 1) || dm_i2c_write(exp, EXP_CFG, &cfg0, 1))
		goto exp_fail;
	printf("linkcheck verdict: live %d, loops %d, probe %s => %s\n", live, loops, probe ? "on" : "off",
	       loops ? "LOOP" : live > 1 ? "MULTI" : "OK");
	return loops ? CMD_RET_FAILURE : 0;
exp_fail:
	printf("linkcheck: laser expander write failed; lasers unknown\n");
	return CMD_RET_FAILURE;
}
