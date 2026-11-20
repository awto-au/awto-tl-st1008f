// SPDX-License-Identifier: GPL-2.0-only
/* sfp_core: see sfp_core.h. Ported from awto-tl-st1008f uboot-port rtk_sfpmode.c / rtk_sfppower.c / cmd_rtk.c. */

#include <string.h>
#include "sfp_core.h"

#define A0_BYTES	96
#define BIT0		0x01u

/* bytes beyond len read as 0; the work buffer is always the 96 decoded bytes */
static void ext(const sfp_u8 *id, size_t len, sfp_u8 out[A0_BYTES])
{
	size_t n = len < A0_BYTES ? len : A0_BYTES;

	memcpy(out, id, n);
	memset(out + n, 0, A0_BYTES - n);
}

int sfp_unpad(sfp_u8 *id, size_t len)
{
	/* incl. lengths 14-19: GLC-SX-MM otherwise decodes as SMF 32 km / copper 32 m */
	static const sfp_u8 fields[] = { 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
					 37, 38, 39, 64, 65 };
	size_t i;
	int n = 0;

	if (len < 11)
		return 0;
	for (i = 3; i <= 10; i++)
		n += id[i] == 0x20;
	if (n < 4)
		return 0;
	for (i = 0; i < sizeof(fields); i++)
		if (fields[i] < len && id[fields[i]] == 0x20)
			id[fields[i]] = 0;
	if (len > 36)
		id[36] = 0;
	return 1;
}

/* sfp_strlen + exact compare of a space-padded EEPROM field */
static int field_is(const sfp_u8 *f, size_t n, const char *s)
{
	while (n && (f[n - 1] == ' ' || !f[n - 1]))
		n--;
	return n == strlen(s) && !memcmp(f, s, n);
}

int sfp_fixup(sfp_u8 *id, size_t len)
{
	if (len < 56)
		return 0;
	if (field_is(id + 20, 16, "FS") && field_is(id + 40, 16, "SFP-10G-T")) {	/* sfp_fixup_fs_10gt */
		id[2] = 0x22;	/* SFF8024_CONNECTOR_RJ45 */
		id[36] = 0x1c;	/* SFF8024_ECC_10GBASE_T_SR */
		return 1;
	}
	if (field_is(id + 20, 16, "OEM") && field_is(id + 40, 16, "SFP-10G-T")) {	/* sfp_fixup_rollball_cc */
		id[36] = 0x16;	/* SFF8024_ECC_10GBASE_T_SFI */
		return 1;
	}
	return 0;
}

static sfp_u8 sum(const sfp_u8 *p, size_t n)
{
	sfp_u8 s = 0;

	while (n--)
		s += *p++;
	return s;
}

int sfp_cc_base_ok(const sfp_u8 *id, size_t len)
{
	return len < 64 ? -1 : sum(id, 63) == id[63];
}

int sfp_cc_ext_ok(const sfp_u8 *id, size_t len)
{
	return len < 96 ? -1 : sum(id + 64, 31) == id[95];
}

const char *sfp_media_name(const sfp_u8 *buf, size_t len)
{
	sfp_u8 id[A0_BYTES];

	ext(buf, len, id);
	if (id[3] & 0x10) return "10GBASE-SR";
	if (id[3] & 0x20) return "10GBASE-LR";
	if (id[3] & 0x40) return "10GBASE-LRM";
	if (id[3] & 0x80) return "10GBASE-ER";
	if (id[8] & 0x04) return "SFP+ DAC (passive)";
	if (id[8] & 0x08) return "SFP+ DAC (active)";
	if (id[6] & 0x08) return "1000BASE-T";
	if (id[6] & 0x01) return "1000BASE-SX";
	if (id[6] & 0x02) return "1000BASE-LX";
	if (id[6] & 0x04) return "1000BASE-CX";
	if (id[6] & 0x40) return "100BASE-FX";
	return NULL;
}

unsigned int sfp_support_mask(const sfp_u8 *buf, size_t len, int *phy)
{
	sfp_u8 id[A0_BYTES];
	unsigned int br_nom = 0, br_min = 0, br_max = 0, itf = 0;
	int passive, active;
	sfp_u8 ecc;

	ext(buf, len, id);
	passive = id[8] & 0x04;
	active = id[8] & 0x08;
	ecc = id[36];
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
	*phy = 0;
	if (id[3] & 0xf0)			/* 10G SR/LR/LRM/ER */
		itf |= SFP_IFBIT(SFP_IF_10GR);
	if (id[6] & 0x07)			/* 1000BASE-SX/LX/CX */
		itf |= SFP_IFBIT(SFP_IF_1000BX);
	*phy = (id[6] & 0x08) != 0;		/* 1000BASE-T */
	if (*phy)
		itf |= SFP_IFBIT(SFP_IF_1000BX) | SFP_IFBIT(SFP_IF_SGMII);
	if ((id[6] & 0xc0) && br_min <= 1300 && br_max >= 1200)	/* PX / BX10 */
		itf |= SFP_IFBIT(SFP_IF_1000BX);
	if (id[6] & 0x30)			/* 100BASE-FX/LX */
		itf |= SFP_IFBIT(SFP_IF_100BX);
	if ((id[6] & 0xc0) && br_nom == 100)
		itf |= SFP_IFBIT(SFP_IF_100BX);
	if ((passive || active) && br_nom) {
		if (br_min <= 12000 && br_max >= 10300)
			itf |= SFP_IFBIT(SFP_IF_10GR);
		if (br_min <= 3200 && br_max >= 3100)
			itf |= SFP_IFBIT(SFP_IF_2500BX);
		if (br_min <= 1300 && br_max >= 1200)
			itf |= SFP_IFBIT(SFP_IF_1000BX);
	}
	if ((passive && (id[60] & BIT0)) || (active && (id[60] & 3)))	/* SFF-8431 app E / limiting */
		itf |= SFP_IFBIT(SFP_IF_10GR);
	if (ecc == 0x16 || ecc == 0x1c) {	/* 10GBASE-T SFI / SR */
		itf |= SFP_IFBIT(SFP_IF_10GR);
		*phy = 1;
	} else if (ecc == 0x1e) {		/* 2.5GBASE-T */
		itf |= SFP_IFBIT(SFP_IF_2500BX);
		*phy = 1;
	}
	if (id[10] & (0x01 | 0x04 | 0x10)) {	/* FC 100/200/400 MBytes/s */
		if (id[12] >= 31)
			itf |= SFP_IFBIT(SFP_IF_2500BX);
		if (id[12] >= 12)
			itf |= SFP_IFBIT(SFP_IF_1000BX);
	}
	if (!itf && br_nom) {			/* bitrate only (e.g. non-compliant BiDi) */
		if (br_min <= 1300 && br_max >= 1200)
			itf |= SFP_IFBIT(SFP_IF_1000BX);
		if (br_min <= 3200 && br_max >= 2500)
			itf |= SFP_IFBIT(SFP_IF_2500BX);
	}
	return itf;
}

/* Linux sfp_quirks[] entries with a .support hook; fixup-only quirks change no interface */
static const struct { const char *vendor, *part; unsigned int set; int only; } quirks[] = {
	{ "ALCATELLUCENT", "G010SP", SFP_IFBIT(SFP_IF_2500BX) },
	{ "ALCATELLUCENT", "3FE46541AA", SFP_IFBIT(SFP_IF_2500BX) },
	{ "FS", "GPON-ONU-34-20BI", SFP_IFBIT(SFP_IF_2500BX) },
	{ "HG GENUINE", "MXPD-483II", SFP_IFBIT(SFP_IF_2500BX) },
	{ "HUAWEI", "MA5671A", SFP_IFBIT(SFP_IF_2500BX) },
	{ "Hisense-Leox", "LXT-010S-H", SFP_IFBIT(SFP_IF_2500BX) },
	{ "Hisense", "ZNID-GPON-2311NA", SFP_IFBIT(SFP_IF_2500BX) },
	{ "HSGQ", "HSGQ-XPON-Stick", SFP_IFBIT(SFP_IF_2500BX) },
	{ "Lantech", "8330-262D-E", SFP_IFBIT(SFP_IF_2500BX) },
	{ "Lantech", "8330-265D", SFP_IFBIT(SFP_IF_2500BX) },
	{ "UBNT", "UF-INSTANT", SFP_IFBIT(SFP_IF_1000BX), 1 },
	{ "OEM", "SFP-2.5G-T", SFP_IFBIT(SFP_IF_2500BX) },
	{ "OEM", "SFP-2.5G-BX10-D", SFP_IFBIT(SFP_IF_2500BX) },
	{ "OEM", "SFP-2.5G-BX10-U", SFP_IFBIT(SFP_IF_2500BX) },
	{ "OEM", "SFP-2.5G-LH03-B", SFP_IFBIT(SFP_IF_2500BX) },
	{ "OEM", "SFP-2.5G-LH20-A", SFP_IFBIT(SFP_IF_2500BX) },
	{ "ZOERAX", "SFP-2.5G-T", SFP_IFBIT(SFP_IF_2500BX) },
};

unsigned int sfp_quirk_mask(const sfp_u8 *buf, size_t len, unsigned int mask, const char **why)
{
	sfp_u8 id[A0_BYTES];
	size_t i;

	ext(buf, len, id);
	*why = "eeprom";
	for (i = 0; i < sizeof(quirks) / sizeof(quirks[0]); i++) {
		if (!field_is(id + 20, 16, quirks[i].vendor) || !field_is(id + 40, 16, quirks[i].part))
			continue;
		mask = quirks[i].only ? quirks[i].set : mask | quirks[i].set;
		*why = "quirk";
	}
	return mask;
}

int sfp_pick_if(unsigned int mask, unsigned int chip_supported, int phy)
{
	static const sfp_u8 pref[] = { SFP_IF_10GR, SFP_IF_2500BX, SFP_IF_SGMII, SFP_IF_1000BX, SFP_IF_100BX };
	size_t i;

	if (!phy)
		mask &= ~SFP_IFBIT(SFP_IF_SGMII);
	for (i = 0; i < sizeof(pref); i++)
		if ((mask & chip_supported) & SFP_IFBIT(pref[i]))
			return pref[i];
	return SFP_IF_NA;
}

/* Copper modules cannot declare > 2.0 W; FS datasheet maxima. */
#define CU_1G_MW	1200	/* SFP-GE-T: 350 mA x 3.47 V */
#define CU_2G5_MW	2000	/* SFP-2.5G-T: "< 2 W" */
#define CU_10G_MW	3000	/* SFP-10G-T-30: 3.0 W max (also used for 5GBASE-T) */

int sfp_power_mw(const sfp_u8 *buf, size_t len, const char **why)
{
	sfp_u8 id[A0_BYTES];
	int mw, cu = 0;
	sfp_u8 ecc;

	ext(buf, len, id);
	/* byte 64 bit 1 = level 2 (1.5 W), bit 5 = level 3 (2.0 W); SFF-8472 / Linux sfp.c */
	mw = id[64] & 0x20 ? 2000 : id[64] & 0x02 ? 1500 : 1000;
	ecc = id[36];
	*why = "declared";
	if (ecc == 0x16 || ecc == 0x1c || ecc == 0x1d)		/* 10GBASE-T SFI/SR, 5GBASE-T */
		cu = CU_10G_MW;
	else if (ecc == 0x1e)					/* 2.5GBASE-T */
		cu = CU_2G5_MW;
	else if (id[2] == 0x22)					/* RJ45: size by nominal rate */
		cu = id[12] >= 100 ? CU_10G_MW : id[12] >= 25 ? CU_2G5_MW : CU_1G_MW;
	else if (id[6] & 0x08)					/* 1000BASE-T */
		cu = CU_1G_MW;
	if (cu > mw) {
		*why = "copper table";
		mw = cu;
	}
	return mw;
}

size_t sfp_field(const sfp_u8 *buf, size_t len, size_t off, size_t n, char *out)
{
	size_t i, k;

	for (i = 0; i < n; i++) {
		sfp_u8 c = off + i < len ? buf[off + i] : 0;

		out[i] = c >= 0x20 && c < 0x7f ? (char)c : (c ? '?' : ' ');
	}
	for (k = n; k && out[k - 1] == ' '; k--)
		;
	out[k] = 0;
	return k;
}
