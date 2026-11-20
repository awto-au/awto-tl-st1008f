// SPDX-License-Identifier: GPL-2.0+
/*
 * SerDes interface for an SFP module, chosen the way Linux does: sfp_module_parse_support() and the
 * support quirks of sfp_quirks[] (drivers/net/phy/sfp-bus.c, sfp.c, Linux 7.3, GPL-2.0), then the
 * first entry of phylink_sfp_interface_preference[] that the RTL9303 SerDes can run.
 * Modules with a PHY (1000BASE-T) get SGMII, as phylink does once it finds the PHY.
 */

#include "rtk.h"
#include "sfp_core.h"

const char *const rtk_if_name[] = { "none", "100base-x", "1000base-x", "sgmii", "2500base-x",
				    "10gbase-r" };

/* sfp_core and the board share the interface numbering */
_Static_assert((int)RTK_IF_NA == (int)SFP_IF_NA && (int)RTK_IF_100BX == (int)SFP_IF_100BX &&
	       (int)RTK_IF_1000BX == (int)SFP_IF_1000BX && (int)RTK_IF_SGMII == (int)SFP_IF_SGMII &&
	       (int)RTK_IF_2500BX == (int)SFP_IF_2500BX && (int)RTK_IF_10GR == (int)SFP_IF_10GR,
	       "enum rtk_if != enum sfp_if");

int rtk_sfp_iface(int cage, const char **why)
{
	/* every SerDes interface of sfp_core is one the RTL9303 can run */
	static const unsigned int chip = SFP_IFBIT(SFP_IF_100BX) | SFP_IFBIT(SFP_IF_1000BX) | SFP_IFBIT(SFP_IF_SGMII) |
					 SFP_IFBIT(SFP_IF_2500BX) | SFP_IFBIT(SFP_IF_10GR);
	u8 id[96];
	unsigned int mask;
	int phy;

	*why = "eeprom";
	if (rtk_sfp_read_id(cage, id))	/* unpadded + fixups applied */
		return -1;
	mask = sfp_support_mask(id, sizeof(id), &phy);
	mask = sfp_quirk_mask(id, sizeof(id), mask, why);
	return sfp_pick_if(mask, chip, phy);
}
