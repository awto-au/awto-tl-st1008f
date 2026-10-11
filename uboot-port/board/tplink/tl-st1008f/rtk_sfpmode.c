// SPDX-License-Identifier: GPL-2.0+
/*
 * SerDes interface for an SFP module, chosen the way Linux does: sfp_module_parse_support() and the
 * support quirks of sfp_quirks[] (drivers/net/phy/sfp-bus.c, sfp.c, Linux 7.3, GPL-2.0), then the
 * first entry of phylink_sfp_interface_preference[] that the RTL9303 SerDes can run.
 * Modules with a PHY (1000BASE-T) get SGMII, as phylink does once it finds the PHY.
 */

#include <linux/string.h>
#include "rtk.h"

const char *const rtk_if_name[] = { "none", "100base-x", "1000base-x", "sgmii", "2500base-x",
				    "10gbase-r" };

enum { IF_100BX = BIT(RTK_IF_100BX), IF_1000BX = BIT(RTK_IF_1000BX), IF_SGMII = BIT(RTK_IF_SGMII),
       IF_2500BX = BIT(RTK_IF_2500BX), IF_10GR = BIT(RTK_IF_10GR) };

/* sfp_quirks[] entries with a .support hook; fixup-only quirks change no interface */
static const struct { const char *vendor, *part; u8 set, only; } quirks[] = {
	{ "ALCATELLUCENT", "G010SP", IF_2500BX }, { "ALCATELLUCENT", "3FE46541AA", IF_2500BX },
	{ "FS", "GPON-ONU-34-20BI", IF_2500BX }, { "HG GENUINE", "MXPD-483II", IF_2500BX },
	{ "HUAWEI", "MA5671A", IF_2500BX }, { "Hisense-Leox", "LXT-010S-H", IF_2500BX },
	{ "Hisense", "ZNID-GPON-2311NA", IF_2500BX }, { "HSGQ", "HSGQ-XPON-Stick", IF_2500BX },
	{ "Lantech", "8330-262D-E", IF_2500BX }, { "Lantech", "8330-265D", IF_2500BX },
	{ "UBNT", "UF-INSTANT", IF_1000BX, 1 },
	{ "OEM", "SFP-2.5G-T", IF_2500BX }, { "OEM", "SFP-2.5G-BX10-D", IF_2500BX },
	{ "OEM", "SFP-2.5G-BX10-U", IF_2500BX }, { "OEM", "SFP-2.5G-LH03-B", IF_2500BX },
	{ "OEM", "SFP-2.5G-LH20-A", IF_2500BX }, { "ZOERAX", "SFP-2.5G-T", IF_2500BX },
};

/* sfp_strlen + exact compare of a space-padded EEPROM field */
static bool field_is(const u8 *f, int n, const char *s)
{
	while (n && (f[n - 1] == ' ' || !f[n - 1]))
		n--;
	return n == strlen(s) && !memcmp(f, s, n);
}

static u8 parse_support(const u8 *id, bool *phy)
{
	unsigned int br_nom = 0, br_min = 0, br_max = 0;
	bool passive = id[8] & BIT(2), active = id[8] & BIT(3);
	u8 itf = 0, ecc = id[36];

	if (id[12] && id[12] != 255) {
		br_nom = id[12] * 100;
		br_min = br_nom - id[12] * id[67];
		br_max = br_nom + id[12] * id[66];
	} else if (id[12] == 255 && id[66]) {
		br_nom = 250 * id[66];
		br_max = br_nom + br_nom * id[67] / 100;
		br_min = br_nom - br_nom * id[67] / 100;
	}
	if (id[12] && br_min == br_max && passive)
		br_min = 0;
	if (id[3] & 0xf0)			/* 10G SR/LR/LRM/ER */
		itf |= IF_10GR;
	if (id[6] & 0x07)			/* 1000BASE-SX/LX/CX */
		itf |= IF_1000BX;
	*phy = id[6] & BIT(3);			/* 1000BASE-T */
	if (*phy)
		itf |= IF_1000BX | IF_SGMII;
	if ((id[6] & 0xc0) && br_min <= 1300 && br_max >= 1200)	/* PX / BX10 */
		itf |= IF_1000BX;
	if (id[6] & 0x30)			/* 100BASE-FX/LX */
		itf |= IF_100BX;
	if ((id[6] & 0xc0) && br_nom == 100)
		itf |= IF_100BX;
	if ((passive || active) && br_nom) {
		if (br_min <= 12000 && br_max >= 10300)
			itf |= IF_10GR;
		if (br_min <= 3200 && br_max >= 3100)
			itf |= IF_2500BX;
		if (br_min <= 1300 && br_max >= 1200)
			itf |= IF_1000BX;
	}
	if ((passive && (id[60] & BIT(0))) || (active && (id[60] & 3)))	/* SFF-8431 app E / limiting */
		itf |= IF_10GR;
	if (ecc == 0x16 || ecc == 0x1c)		/* 10GBASE-T SFI / SR */
		itf |= IF_10GR, *phy = true;
	else if (ecc == 0x1e)			/* 2.5GBASE-T */
		itf |= IF_2500BX, *phy = true;
	if (id[10] & (BIT(0) | BIT(2) | BIT(4))) {	/* FC 100/200/400 MBytes/s */
		if (id[12] >= 31)
			itf |= IF_2500BX;
		if (id[12] >= 12)
			itf |= IF_1000BX;
	}
	if (!itf && br_nom) {			/* bitrate only (e.g. non-compliant BiDi) */
		if (br_min <= 1300 && br_max >= 1200)
			itf |= IF_1000BX;
		if (br_min <= 3200 && br_max >= 2500)
			itf |= IF_2500BX;
	}
	return itf;
}

int rtk_sfp_iface(int cage, const char **why)
{
	static const u8 pref[] = { RTK_IF_10GR, RTK_IF_2500BX, RTK_IF_SGMII, RTK_IF_1000BX,
				   RTK_IF_100BX };
	u8 id[96], itf;
	bool phy;
	int i;

	*why = "eeprom";
	if (rtk_sfp_read_id(cage, id))
		return -1;
	itf = parse_support(id, &phy);
	for (i = 0; i < ARRAY_SIZE(quirks); i++) {
		if (!field_is(id + 20, 16, quirks[i].vendor) || !field_is(id + 40, 16, quirks[i].part))
			continue;
		itf = quirks[i].only ? quirks[i].set : itf | quirks[i].set;
		*why = "quirk";
	}
	if (!phy)
		itf &= ~IF_SGMII;
	for (i = 0; i < ARRAY_SIZE(pref); i++)
		if (itf & BIT(pref[i]))
			return pref[i];
	return RTK_IF_NA;
}
