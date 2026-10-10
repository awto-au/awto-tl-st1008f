// SPDX-License-Identifier: GPL-2.0
/*
 * Common SFF-8024 / SFF-8472 helpers, ported from ethtool (7.1, 6b7b16e)
 * sff-common.c and module-common.c.
 * Copyright 2010 Solarflare Communications Inc.
 * Aurelien Guillaume <aurelien@iwi.me> (C) 2012
 * Copyright (C) 2014 Cumulus networks Inc.
 * Vidya Sagar Ravipati <vidya@cumulusnetworks.com>
 * Port: output via U-Boot printf, JSON dropped, doubles replaced by fixed point.
 */

#include "sfp.h"

#define  MODULE_ID_OFFSET				0x00
#define  MODULE_ID_UNKNOWN				0x00
#define  MODULE_ID_GBIC				0x01
#define  MODULE_ID_SOLDERED_MODULE		0x02
#define  MODULE_ID_SFP					0x03
#define  MODULE_ID_300_PIN_XBI			0x04
#define  MODULE_ID_XENPAK				0x05
#define  MODULE_ID_XFP					0x06
#define  MODULE_ID_XFF					0x07
#define  MODULE_ID_XFP_E				0x08
#define  MODULE_ID_XPAK				0x09
#define  MODULE_ID_X2					0x0A
#define  MODULE_ID_DWDM_SFP			0x0B
#define  MODULE_ID_QSFP				0x0C
#define  MODULE_ID_QSFP_PLUS			0x0D
#define  MODULE_ID_CXP					0x0E
#define  MODULE_ID_HD4X				0x0F
#define  MODULE_ID_HD8X				0x10
#define  MODULE_ID_QSFP28				0x11
#define  MODULE_ID_CXP2				0x12
#define  MODULE_ID_CDFP				0x13
#define  MODULE_ID_HD4X_FANOUT			0x14
#define  MODULE_ID_HD8X_FANOUT			0x15
#define  MODULE_ID_CDFP_S3				0x16
#define  MODULE_ID_MICRO_QSFP			0x17
#define  MODULE_ID_QSFP_DD				0x18
#define  MODULE_ID_OSFP				0x19
#define  MODULE_ID_DSFP				0x1B
#define  MODULE_ID_QSFP_PLUS_CMIS			0x1E
#define  MODULE_ID_SFP_DD_CMIS				0x1F
#define  MODULE_ID_SFP_PLUS_CMIS			0x20
#define  MODULE_ID_LAST				MODULE_ID_SFP_PLUS_CMIS
#define  MODULE_ID_UNALLOCATED_LAST	0x7F
#define  MODULE_ID_VENDOR_START		0x80
#define  MODULE_ID_VENDOR_LAST			0xFF

#define  MODULE_CTOR_UNKNOWN			0x00
#define  MODULE_CTOR_SC				0x01
#define  MODULE_CTOR_FC_STYLE_1		0x02
#define  MODULE_CTOR_FC_STYLE_2		0x03
#define  MODULE_CTOR_BNC_TNC			0x04
#define  MODULE_CTOR_FC_COAX			0x05
#define  MODULE_CTOR_FIBER_JACK		0x06
#define  MODULE_CTOR_LC				0x07
#define  MODULE_CTOR_MT_RJ				0x08
#define  MODULE_CTOR_MU				0x09
#define  MODULE_CTOR_SG				0x0A
#define  MODULE_CTOR_OPT_PT			0x0B
#define  MODULE_CTOR_MPO				0x0C
#define  MODULE_CTOR_MPO_2				0x0D
/* 0E-1Fh --- Reserved */
#define  MODULE_CTOR_HSDC_II			0x20
#define  MODULE_CTOR_COPPER_PT			0x21
#define  MODULE_CTOR_RJ45				0x22
#define  MODULE_CTOR_NO_SEPARABLE		0x23
#define  MODULE_CTOR_MXC_2x16			0x24
#define  MODULE_CTOR_CS_OPTICAL		0x25
#define  MODULE_CTOR_CS_OPTICAL_MINI		0x26
#define  MODULE_CTOR_MPO_2X12			0x27
#define  MODULE_CTOR_MPO_1X16			0x28
#define  MODULE_CTOR_LAST			MODULE_CTOR_MPO_1X16

#define  MODULE_CTOR_NO_SEP_QSFP_DD		0x6F
#define  MODULE_CTOR_UNALLOCATED_LAST		0x7F
#define  MODULE_CTOR_VENDOR_START		0x80
#define  MODULE_CTOR_VENDOR_LAST		0xFF


/* ENCODING Values */
#define  SFF8024_ENCODING_UNSPEC		0x00
#define  SFF8024_ENCODING_8B10B			0x01
#define  SFF8024_ENCODING_4B5B			0x02
#define  SFF8024_ENCODING_NRZ			0x03
/*
 * Value: 04h
 * SFF-8472      - Manchester
 * SFF-8436/8636 - SONET Scrambled
 */
#define  SFF8024_ENCODING_4h			0x04
/*
 * Value: 05h
 * SFF-8472      - SONET Scrambled
 * SFF-8436/8636 - 64B/66B
 */
#define  SFF8024_ENCODING_5h			0x05
/*
 * Value: 06h
 * SFF-8472      - 64B/66B
 * SFF-8436/8636 - Manchester
 */
#define  SFF8024_ENCODING_6h			0x06
#define  SFF8024_ENCODING_256B			0x07
#define  SFF8024_ENCODING_PAM4			0x08


void sff_print_any_hex_field(const char *field_name, u8 value, const char *desc)
{
	printf("\t%-41s : 0x%02x", field_name, value);
	if (desc)
		printf(" (%s)", desc);
	printf("\n");
}

void module_print_any_uint(const char *fn, int value, const char *unit)
{
	printf("\t%-41s : %u%s\n", fn, value, unit ? unit : "");
}

void module_print_any_bool(const char *fn, bool value, const char *str_value)
{
	printf("\t%-41s : %s\n", fn, str_value);
}

void module_print_any_array_string_entry(const char *fn, const char *value)
{
	printf("\t%-41s : %s\n", fn, value);
}

void module_show_value_with_unit(const u8 *id, unsigned int reg, const char *name,
				 unsigned int mult, const char *unit)
{
	module_print_any_uint(name, id[reg] * mult, unit);
}

void module_show_ascii(const u8 *id, unsigned int first_reg, unsigned int last_reg,
		       const char *name)
{
	unsigned int reg, val;

	printf("\t%-41s : ", name);
	while (first_reg <= last_reg && id[last_reg] == ' ')
		last_reg--;
	for (reg = first_reg; reg <= last_reg; reg++) {
		val = id[reg];
		putc((val >= 32 && val <= 126) ? val : '_');
	}
	printf("\n");
}

void module_show_oui(const u8 *id, int id_offset)
{
	printf("\t%-41s : %02x:%02x:%02x\n", "Vendor OUI", id[id_offset],
	       id[id_offset + 1], id[id_offset + 2]);
}

/* Fixed-point output: v / div with `digits` decimals; neg = value below zero. */
static void pr_fix(bool neg, u32 v, u32 div, int digits)
{
	u32 frac = v % div;

	printf("%s%u.%0*u", neg ? "-" : "", v / div, digits, frac);
}

/* dBm in 1/100 from a power in 0.1 uW: 10*log10(p/10000). log2 by bitwise squaring, Q16. */
static s32 pwr_to_cdbm(u32 p)
{
	u32 x, frac = 0;
	int ip, i;
	s32 l10;

	ip = fls(p) - 1;
	x = ip >= 16 ? p >> (ip - 16) : p << (16 - ip);	/* Q16 mantissa in [1,2) */
	for (i = 0; i < 16; i++) {
		x = (u32)(((u64)x * x) >> 16);
		frac <<= 1;
		if (x >= 0x20000) {
			x >>= 1;
			frac |= 1;
		}
	}
	/* log10(p) in Q16 = log2(p) * 19728 >> 16 (log10(2) in Q16, error < 1e-4 dB) */
	l10 = (s32)(((u64)((ip << 16) | frac) * 19728) >> 16);
	return ((l10 * 1000) >> 16) - 4000;
}

void sff_print_pwr(const char *name, u32 pwr)
{
	s32 c;

	printf("\t%-41s : ", name);
	pr_fix(false, pwr, 10000, 4);
	if (!pwr) {
		printf(" mW / -inf dBm\n");
		return;
	}
	c = pwr_to_cdbm(pwr);
	printf(" mW / ");
	pr_fix(c < 0, c < 0 ? -c : c, 100, 2);
	printf(" dBm\n");
}

void sff_print_bias(const char *name, u32 bias)
{
	printf("\t%-41s : ", name);
	pr_fix(false, bias * 2, 1000, 3);
	printf(" mA\n");
}

void sff_print_temp(const char *name, s32 temp)
{
	bool neg = temp < 0;
	u32 a = neg ? -temp : temp;
	s32 c = (a * 100 + 128) / 256;		/* 1/100 C, rounded */
	s32 f = (neg ? -c : c) * 9 / 5 + 3200;	/* 1/100 F */

	printf("\t%-41s : ", name);
	pr_fix(neg, c, 100, 2);
	printf(" degrees C / ");
	pr_fix(f < 0, f < 0 ? -f : f, 100, 2);
	printf(" degrees F\n");
}

void sff_print_vcc(const char *name, u32 vcc)
{
	printf("\t%-41s : ", name);
	pr_fix(false, vcc, 10000, 4);
	printf(" V\n");
}

void sff_show_dom_mod_lvl_monitors(const struct sff_diags *sd)
{
	sff_print_temp("Module temperature", sd->sfp_temp[MCURR]);
	sff_print_vcc("Module voltage", sd->sfp_voltage[MCURR]);
}

void sff_show_thresholds(const struct sff_diags *sd)
{
	sff_print_bias("Laser bias current high alarm threshold", sd->bias_cur[HALRM]);
	sff_print_bias("Laser bias current low alarm threshold", sd->bias_cur[LALRM]);
	sff_print_bias("Laser bias current high warning threshold", sd->bias_cur[HWARN]);
	sff_print_bias("Laser bias current low warning threshold", sd->bias_cur[LWARN]);

	sff_print_pwr("Laser output power high alarm threshold", sd->tx_power[HALRM]);
	sff_print_pwr("Laser output power low alarm threshold", sd->tx_power[LALRM]);
	sff_print_pwr("Laser output power high warning threshold", sd->tx_power[HWARN]);
	sff_print_pwr("Laser output power low warning threshold", sd->tx_power[LWARN]);

	sff_print_temp("Module temperature high alarm threshold", sd->sfp_temp[HALRM]);
	sff_print_temp("Module temperature low alarm threshold", sd->sfp_temp[LALRM]);
	sff_print_temp("Module temperature high warning threshold", sd->sfp_temp[HWARN]);
	sff_print_temp("Module temperature low warning threshold", sd->sfp_temp[LWARN]);

	sff_print_vcc("Module voltage high alarm threshold", sd->sfp_voltage[HALRM]);
	sff_print_vcc("Module voltage low alarm threshold", sd->sfp_voltage[LALRM]);
	sff_print_vcc("Module voltage high warning threshold", sd->sfp_voltage[HWARN]);
	sff_print_vcc("Module voltage low warning threshold", sd->sfp_voltage[LWARN]);

	sff_print_pwr("Laser rx power high alarm threshold", sd->rx_power[HALRM]);
	sff_print_pwr("Laser rx power low alarm threshold", sd->rx_power[LALRM]);
	sff_print_pwr("Laser rx power high warning threshold", sd->rx_power[HWARN]);
	sff_print_pwr("Laser rx power low warning threshold", sd->rx_power[LWARN]);
}

void module_show_identifier(const u8 *id, int id_offset)
{
	char id_description[SFF_MAX_DESC_LEN];

	switch (id[id_offset]) {
	case MODULE_ID_UNKNOWN:
		strncpy(id_description,
			"no module present, unknown, or unspecified",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_GBIC:
		strncpy(id_description, "GBIC", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_SOLDERED_MODULE:
		strncpy(id_description,
			"module soldered to motherboard", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_SFP:
		strncpy(id_description, "SFP", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_300_PIN_XBI:
		strncpy(id_description, "300 pin XBI", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_XENPAK:
		strncpy(id_description, "XENPAK", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_XFP:
		strncpy(id_description, "XFP", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_XFF:
		strncpy(id_description, "XFF", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_XFP_E:
		strncpy(id_description, "XFP-E", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_XPAK:
		strncpy(id_description, "XPAK", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_X2:
		strncpy(id_description, "X2", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_DWDM_SFP:
		strncpy(id_description, "DWDM-SFP", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_QSFP:
		strncpy(id_description, "QSFP", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_QSFP_PLUS:
		strncpy(id_description, "QSFP+", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_CXP:
		strncpy(id_description, "CXP", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_HD4X:
		strncpy(id_description, "Shielded Mini Multilane HD 4X",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_HD8X:
		strncpy(id_description, "Shielded Mini Multilane HD 8X",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_QSFP28:
		strncpy(id_description, "QSFP28", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_CXP2:
		strncpy(id_description, "CXP2/CXP28", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_CDFP:
		strncpy(id_description, "CDFP Style 1/Style 2",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_HD4X_FANOUT:
		strncpy(id_description,
			"Shielded Mini Multilane HD 4X Fanout Cable",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_HD8X_FANOUT:
		strncpy(id_description,
			"Shielded Mini Multilane HD 8X Fanout Cable",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_CDFP_S3:
		strncpy(id_description, "CDFP Style 3", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_MICRO_QSFP:
		strncpy(id_description, "microQSFP", SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_QSFP_DD:
		strncpy(id_description,
			"QSFP-DD Double Density 8X Pluggable Transceiver (INF-8628)",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_OSFP:
		strncpy(id_description, "OSFP 8X Pluggable Transceiver",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_DSFP:
		strncpy(id_description,
			"DSFP Dual Small Form Factor Pluggable Transceiver",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_QSFP_PLUS_CMIS:
		strncpy(id_description,
			"QSFP+ or later with Common Management Interface Specification (CMIS)",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_SFP_DD_CMIS:
		strncpy(id_description,
			"SFP-DD Double Density 2X Pluggable Transceiver with Common Management Interface Specification (CMIS)",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_ID_SFP_PLUS_CMIS:
		strncpy(id_description,
			"SFP+ and later with Common Management Interface Specification (CMIS)",
			SFF_MAX_DESC_LEN);
		break;
	default:
		strncpy(id_description, "reserved or unknown",
			SFF_MAX_DESC_LEN);
		break;
	}

	sff_print_any_hex_field("Identifier", id[id_offset],
				id_description);
}

void module_show_connector(const u8 *id, int ctor_offset)
{
	char ctor_description[SFF_MAX_DESC_LEN];

	switch (id[ctor_offset]) {
	case  MODULE_CTOR_UNKNOWN:
		strncpy(ctor_description, "unknown or unspecified",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_SC:
		strncpy(ctor_description, "SC", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_FC_STYLE_1:
		strncpy(ctor_description, "Fibre Channel Style 1 copper",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_FC_STYLE_2:
		strncpy(ctor_description, "Fibre Channel Style 2 copper",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_BNC_TNC:
		strncpy(ctor_description, "BNC/TNC", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_FC_COAX:
		strncpy(ctor_description, "Fibre Channel coaxial headers",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_FIBER_JACK:
		strncpy(ctor_description, "FibreJack", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_LC:
		strncpy(ctor_description, "LC", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_MT_RJ:
		strncpy(ctor_description, "MT-RJ", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_MU:
		strncpy(ctor_description, "MU", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_SG:
		strncpy(ctor_description, "SG", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_OPT_PT:
		strncpy(ctor_description, "Optical pigtail",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_MPO:
		strncpy(ctor_description, "MPO Parallel Optic",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_MPO_2:
		strncpy(ctor_description, "MPO Parallel Optic - 2x16",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_HSDC_II:
		strncpy(ctor_description, "HSSDC II", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_COPPER_PT:
		strncpy(ctor_description, "Copper pigtail",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_RJ45:
		strncpy(ctor_description, "RJ45", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_NO_SEPARABLE:
		strncpy(ctor_description, "No separable connector",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_MXC_2x16:
		strncpy(ctor_description, "MXC 2x16", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_CS_OPTICAL:
		strncpy(ctor_description, "CS optical connector",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_CS_OPTICAL_MINI:
		strncpy(ctor_description, "Mini CS optical connector",
			SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_MPO_2X12:
		strncpy(ctor_description, "MPO 2x12", SFF_MAX_DESC_LEN);
		break;
	case MODULE_CTOR_MPO_1X16:
		strncpy(ctor_description, "MPO 1x16", SFF_MAX_DESC_LEN);
		break;
	default:
		strncpy(ctor_description, "reserved or unknown",
			SFF_MAX_DESC_LEN);
		break;
	}

	sff_print_any_hex_field("Connector", id[ctor_offset],
				ctor_description);
}


void sff8024_show_encoding(const u8 *id, int encoding_offset, int sff_type)
{
	char encoding_desc[64];

	switch (id[encoding_offset]) {
	case SFF8024_ENCODING_UNSPEC:
		strncpy(encoding_desc, "unspecified", 64);
		break;
	case SFF8024_ENCODING_8B10B:
		strncpy(encoding_desc, "8B/10B", 64);
		break;
	case SFF8024_ENCODING_4B5B:
		strncpy(encoding_desc, "4B/5B", 64);
		break;
	case SFF8024_ENCODING_NRZ:
		strncpy(encoding_desc, "NRZ", 64);
		break;
	case SFF8024_ENCODING_4h:
		if (sff_type == ETH_MODULE_SFF_8472)
			strncpy(encoding_desc, "Manchester", 64);
		else if (sff_type == ETH_MODULE_SFF_8636)
			strncpy(encoding_desc, "SONET Scrambled", 64);
		break;
	case SFF8024_ENCODING_5h:
		if (sff_type == ETH_MODULE_SFF_8472)
			strncpy(encoding_desc, "SONET Scrambled", 64);
		else if (sff_type == ETH_MODULE_SFF_8636)
			strncpy(encoding_desc, "64B/66B", 64);
		break;
	case SFF8024_ENCODING_6h:
		if (sff_type == ETH_MODULE_SFF_8472)
			strncpy(encoding_desc, "64B/66B", 64);
		else if (sff_type == ETH_MODULE_SFF_8636)
			strncpy(encoding_desc, "Manchester", 64);
		break;
	case SFF8024_ENCODING_256B:
		strncpy(encoding_desc,
			"256B/257B (transcoded FEC-enabled data)", 64);
		break;
	case SFF8024_ENCODING_PAM4:
		strncpy(encoding_desc, "PAM4", 64);
		break;
	default:
		strncpy(encoding_desc, "reserved or unknown", 64);
		break;
	}

	sff_print_any_hex_field("Encoding", id[encoding_offset],
				encoding_desc);
}


