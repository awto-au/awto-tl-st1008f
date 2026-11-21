// SPDX-License-Identifier: GPL-2.0
/*
 * SFF-8472 optics diagnostics printing, ported from ethtool sfpdiag.c (ethtool 7.1, 6b7b16e).
 * Aurelien Guillaume <aurelien@iwi.me> (C) 2012; SFF-8472.
 * The DDM scaling (incl. external calibration) lives in sfp_ddm.c (awto-sfp-core); this file prints.
 */

#include "sfp.h"
#include "../sfp_core.h"

#define SFF_A2_ALRM_FLG                   112
#define SFF_A2_WARN_FLG                   116

static const struct sff8472_aw_flags {
	const char *str;        /* Human-readable string, null at the end */
	int offset;             /* A2-relative address offset */
	u8 value;               /* Alarm is on if (offset & value) != 0. */
} sff8472_aw_flags[] = {
	{ "Laser bias current high alarm",   SFF_A2_ALRM_FLG, (1 << 3) },
	{ "Laser bias current low alarm",    SFF_A2_ALRM_FLG, (1 << 2) },
	{ "Laser bias current high warning", SFF_A2_WARN_FLG, (1 << 3) },
	{ "Laser bias current low warning",  SFF_A2_WARN_FLG, (1 << 2) },

	{ "Laser output power high alarm",   SFF_A2_ALRM_FLG, (1 << 1) },
	{ "Laser output power low alarm",    SFF_A2_ALRM_FLG, (1 << 0) },
	{ "Laser output power high warning", SFF_A2_WARN_FLG, (1 << 1) },
	{ "Laser output power low warning",  SFF_A2_WARN_FLG, (1 << 0) },

	{ "Module temperature high alarm",   SFF_A2_ALRM_FLG, (1 << 7) },
	{ "Module temperature low alarm",    SFF_A2_ALRM_FLG, (1 << 6) },
	{ "Module temperature high warning", SFF_A2_WARN_FLG, (1 << 7) },
	{ "Module temperature low warning",  SFF_A2_WARN_FLG, (1 << 6) },

	{ "Module voltage high alarm",   SFF_A2_ALRM_FLG, (1 << 5) },
	{ "Module voltage low alarm",    SFF_A2_ALRM_FLG, (1 << 4) },
	{ "Module voltage high warning", SFF_A2_WARN_FLG, (1 << 5) },
	{ "Module voltage low warning",  SFF_A2_WARN_FLG, (1 << 4) },

	{ "Laser rx power high alarm",   SFF_A2_ALRM_FLG + 1, (1 << 7) },
	{ "Laser rx power low alarm",    SFF_A2_ALRM_FLG + 1, (1 << 6) },
	{ "Laser rx power high warning", SFF_A2_WARN_FLG + 1, (1 << 7) },
	{ "Laser rx power low warning",  SFF_A2_WARN_FLG + 1, (1 << 6) },

	{ NULL, 0, 0 },
};

/* Readings as the printing helpers want them; same array order as struct sfp_ddm (LWARN..MCURR). */
void sff8472_diags(const u8 *id, const u8 *a2, struct sff_diags *sd)
{
	struct sfp_ddm d;

	sfp_ddm_decode(id, 96, a2, SFP_DDM_A2_LEN, &d);
	sd->supports_dom = d.supports_dom;
	sd->supports_alarms = d.supports_alarms;
	sd->rx_power_type = d.rx_power_type;
	sd->calibrated_ext = d.calibrated_ext;
	memcpy(sd->sfp_voltage, d.vcc, sizeof(sd->sfp_voltage));
	memcpy(sd->sfp_temp, d.temp, sizeof(sd->sfp_temp));
	memcpy(sd->bias_cur, d.bias, sizeof(sd->bias_cur));
	memcpy(sd->tx_power, d.tx_power, sizeof(sd->tx_power));
	memcpy(sd->rx_power, d.rx_power, sizeof(sd->rx_power));
}

void sff8472_show_all(const u8 *id, const u8 *a2)
{
	const char *rx_power_type_string;
	struct sff_diags sd = {0};
	int i;

	sff8472_diags(id, a2, &sd);

	module_print_any_bool("Optical diagnostics support", sd.supports_dom,
			      sd.supports_dom ? "Yes" : "No");

	if (!sd.supports_dom)
		return;

	sff_print_bias("Laser bias current", sd.bias_cur[MCURR]);
	sff_print_pwr("Laser output power", sd.tx_power[MCURR]);

	if (!sd.rx_power_type)
		rx_power_type_string = "Receiver signal OMA";
	else
		rx_power_type_string = "Receiver signal average optical power";

	sff_print_pwr(rx_power_type_string, sd.rx_power[MCURR]);

	sff_show_dom_mod_lvl_monitors(&sd);

	module_print_any_bool("Alarm/warning flags implemented", sd.supports_alarms,
			      sd.supports_alarms ? "Yes" : "No");

	if (sd.supports_alarms) {
		for (i = 0; sff8472_aw_flags[i].str; ++i) {
			bool value;

			value = a2[sff8472_aw_flags[i].offset] & sff8472_aw_flags[i].value;
			module_print_any_bool(sff8472_aw_flags[i].str, value,
					      value ? "On" : "Off");
		}
		sff_show_thresholds(&sd);
	}
}
