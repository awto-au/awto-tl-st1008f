// SPDX-License-Identifier: GPL-2.0-only
/*
 * Copper-module PHY init for sfp_core: register tables plus one small sequencer; the PHY is reached only
 * through struct sfp_phy_ops (16-bit clause-22 registers), so every repo supplies its own bus access.
 * Origin: Linux drivers/net/phy/marvell.c (m88e1111_config_init_sgmii, genphy_soft_reset, config_aneg)
 * as run by sfp.c for a GLC-T style module; st1008f cmd_rtk.c rtk_sfp_copper_phy_init().
 */

#include "sfp_core.h"

#define PHY_BMCR		0
#define PHY_ANAR		4
#define PHY_1000CTRL		9
#define PHY_ID1			2
#define PHY_ID2			3
#define BMCR_RESET		0x8000
#define BMCR_ANE_RESTART	0x1200	/* AN enable + restart; speed/duplex bits clear */
/* selector + sym/asym pause, no 10/100: Linux sfp advertises 1000baseT/Full only for these modules */
#define ANAR_1000TX_ONLY	0x0c01
#define CTRL_1000_FULL		0x0200

#define M1111_EXT_SR		0x1b	/* HWCFG mode: Linux MII_M1111_PHY_EXT_SR */
#define M1111_MODE_MASK		0xf
#define M1111_MODE_SGMII_NO_CLK	0x4
#define M1111_FIBER_COPPER_RES	0x2000
#define M1111_FIBER_COPPER_AUTO	0x8000
#define M1111_PAGE		0x16	/* page select; 0 = copper */

/* Linux PHY_RESET_TIMEOUT = 600 ms (88E1111 clears BMCR reset in < 1 ms); expiry: SFP_E_TIMEOUT, no AN restart.
 * Poll period 5 ms: one register read over the module's I2C costs ~1-2 ms. */
#define RESET_CAP_MS		600
#define RESET_POLL_MS		5

enum step_op { OP_WR, OP_RMW, OP_WAIT_CLEAR, OP_END };

struct phy_step {
	enum step_op op;
	unsigned char reg;
	unsigned short mask;	/* RMW: bits cleared; WAIT_CLEAR: bits that must read 0 */
	unsigned short val;	/* WR: value; RMW: bits set */
};

/* 88E1111 for a host SerDes in SGMII: the module powers up in 1000BASE-X with autoneg off (BMCR 0x0140),
 * so without this no SGMII link forms. */
static const struct phy_step m88e1111_sgmii[] = {
	{ OP_RMW, M1111_EXT_SR, M1111_MODE_MASK | M1111_FIBER_COPPER_AUTO | M1111_FIBER_COPPER_RES,
	  M1111_MODE_SGMII_NO_CLK | M1111_FIBER_COPPER_AUTO },
	{ OP_WR, M1111_PAGE, 0, 0 },
	{ OP_WR, PHY_BMCR, 0, BMCR_RESET },
	{ OP_WAIT_CLEAR, PHY_BMCR, BMCR_RESET, 0 },
	{ OP_WR, PHY_ANAR, 0, ANAR_1000TX_ONLY },
	{ OP_WR, PHY_1000CTRL, 0, CTRL_1000_FULL },
	{ OP_WR, PHY_BMCR, 0, BMCR_ANE_RESTART },
	{ OP_END, 0, 0, 0 },
};

struct phy_entry {
	enum sfp_phy_id id;
	const char *name;
	unsigned short id1, id2, id2_mask;
	const struct phy_step *seq;	/* NULL: identified, nothing to do from the bootloader */
};

static const struct phy_entry phys[] = {
	{ SFP_PHY_88E1111, "88E1111", 0x0141, 0x0cc0, 0xfff0, m88e1111_sgmii },
	/* AQR113C (id 0x31c3 0x1c12 on MMD 1) sits behind the RollBall clause-45 protocol, not clause-22 at 0x56;
	 * its autoneg is firmware-managed and Linux's aquantia driver does the host side: no table here (#127). */
	{ SFP_PHY_AQR113C, "AQR113C", 0x31c3, 0x1c12, 0xffff, 0 },
};

const char *sfp_phy_name(enum sfp_phy_id id)
{
	unsigned int i;

	for (i = 0; i < sizeof(phys) / sizeof(phys[0]); i++)
		if (phys[i].id == id)
			return phys[i].name;
	return id == SFP_PHY_OTHER ? "unknown PHY" : "none";
}

static const struct phy_entry *lookup(enum sfp_phy_id id)
{
	unsigned int i;

	for (i = 0; i < sizeof(phys) / sizeof(phys[0]); i++)
		if (phys[i].id == id)
			return &phys[i];
	return 0;
}

enum sfp_phy_id sfp_phy_identify(const struct sfp_phy_ops *o)
{
	unsigned short id1, id2;
	unsigned int i;

	if (o->rd(o->ctx, PHY_ID1, &id1) || o->rd(o->ctx, PHY_ID2, &id2))
		return SFP_PHY_NONE;	/* no PHY answer: a fibre or MCU-only module */
	/* byte pointer off by one (ID1 reads 0x4101): one extra read re-aligns it (st1008f #33) */
	if (id1 == 0x4101 && o->rd(o->ctx, PHY_ID1, &id1))
		return SFP_PHY_NONE;
	for (i = 0; i < sizeof(phys) / sizeof(phys[0]); i++)
		if (id1 == phys[i].id1 && (id2 & phys[i].id2_mask) == phys[i].id2)
			return phys[i].id;
	return SFP_PHY_OTHER;
}

int sfp_phy_init(const struct sfp_phy_ops *o, enum sfp_phy_id id)
{
	const struct phy_entry *e = lookup(id);
	const struct phy_step *s;
	unsigned short v;
	unsigned int ms;

	if (!e || !e->seq)
		return 0;
	for (s = e->seq; s->op != OP_END; s++) {
		switch (s->op) {
		case OP_WR:
			if (o->wr(o->ctx, s->reg, s->val))
				return -SFP_E_IO;
			break;
		case OP_RMW:
			if (o->rd(o->ctx, s->reg, &v) || o->wr(o->ctx, s->reg, (v & ~s->mask) | s->val))
				return -SFP_E_IO;
			break;
		case OP_WAIT_CLEAR:
			for (ms = 0;; ms += RESET_POLL_MS) {
				if (o->rd(o->ctx, s->reg, &v))
					return -SFP_E_IO;
				if (!(v & s->mask))
					break;
				if (ms >= RESET_CAP_MS)
					return -SFP_E_TIMEOUT;
				o->delay_ms(o->ctx, RESET_POLL_MS);
			}
			break;
		default:
			break;
		}
	}
	return 1;
}
