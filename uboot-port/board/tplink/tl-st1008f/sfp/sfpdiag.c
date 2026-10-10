// SPDX-License-Identifier: GPL-2.0
/*
 * SFF-8472 optics diagnostics, ported from ethtool sfpdiag.c (ethtool 7.1, 6b7b16e).
 * Aurelien Guillaume <aurelien@iwi.me> (C) 2012
 *   loosely based on DOM patches from Robert Olsson <robert@herjulf.se> (C) 2009
 *   and SFF-8472 (ftp://ftp.seagate.com/pub/sff/SFF-8472.PDF).
 * Port: output via U-Boot printf, JSON dropped, doubles replaced by integer fixed point.
 * Changes vs upstream: A2 passed as its own buffer; Rx external-cal polynomial per
 * SFF-8472 (upstream omits r^2..r^4 and Rx_PWR(4)); wider integer fields (no u16 wrap).
 */

#include "sfp.h"

/* Offsets in decimal, for direct comparison with the SFF specs */

/* A0-based EEPROM offsets for DOM support checks */
#define SFF_A0_DOM                        92
#define SFF_A0_OPTIONS                    93
#define SFF_A0_COMP                       94

/* EEPROM bit values for various registers */
#define SFF_A0_DOM_EXTCAL                 (1 << 4)
#define SFF_A0_DOM_INTCAL                 (1 << 5)
#define SFF_A0_DOM_IMPL                   (1 << 6)
#define SFF_A0_DOM_PWRT                   (1 << 3)

#define SFF_A0_OPTIONS_AW                 (1 << 7)

/* A2-based offsets for DOM */
#define SFF_A2_TEMP                       96
#define SFF_A2_TEMP_HALRM                 0
#define SFF_A2_TEMP_LALRM                 2
#define SFF_A2_TEMP_HWARN                 4
#define SFF_A2_TEMP_LWARN                 6

#define SFF_A2_VCC                        98
#define SFF_A2_VCC_HALRM                  8
#define SFF_A2_VCC_LALRM                  10
#define SFF_A2_VCC_HWARN                  12
#define SFF_A2_VCC_LWARN                  14

#define SFF_A2_BIAS                       100
#define SFF_A2_BIAS_HALRM                 16
#define SFF_A2_BIAS_LALRM                 18
#define SFF_A2_BIAS_HWARN                 20
#define SFF_A2_BIAS_LWARN                 22

#define SFF_A2_TX_PWR                     102
#define SFF_A2_TX_PWR_HALRM               24
#define SFF_A2_TX_PWR_LALRM               26
#define SFF_A2_TX_PWR_HWARN               28
#define SFF_A2_TX_PWR_LWARN               30

#define SFF_A2_RX_PWR                     104
#define SFF_A2_RX_PWR_HALRM               32
#define SFF_A2_RX_PWR_LALRM               34
#define SFF_A2_RX_PWR_HWARN               36
#define SFF_A2_RX_PWR_LWARN               38

#define SFF_A2_ALRM_FLG                   112
#define SFF_A2_WARN_FLG                   116

/* 32-bit big-endian IEEE-754 calibration constants */
#define SFF_A2_CAL_RXPWR4                 56
#define SFF_A2_CAL_RXPWR3                 60
#define SFF_A2_CAL_RXPWR2                 64
#define SFF_A2_CAL_RXPWR1                 68
#define SFF_A2_CAL_RXPWR0                 72

/* 16-bit calibration constants: slope 8.8 unsigned, offset signed */
#define SFF_A2_CAL_TXI_SLP                76
#define SFF_A2_CAL_TXI_OFF                78
#define SFF_A2_CAL_TXPWR_SLP              80
#define SFF_A2_CAL_TXPWR_OFF              82
#define SFF_A2_CAL_T_SLP                  84
#define SFF_A2_CAL_T_OFF                  86
#define SFF_A2_CAL_V_SLP                  88
#define SFF_A2_CAL_V_OFF                  90

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

/* Most common case: 16-bit unsigned integer in a certain unit */
#define A2_U16(offset)		(a2[offset] << 8 | a2[(offset) + 1])
/* Calibration slope: unsigned 8.8 fixed point (0.0 .. 255.996) */
#define A2_SLP(offset)		((u32)A2_U16(offset))
/* Calibration offset: signed integer */
#define A2_OFF(offset)		((s16)A2_U16(offset))
/* 2-byte temperature: signed, 1/256 C per LSB */
#define A2_TEMP(offset)		((s16)A2_U16(offset))

/* Minimal soft float for the Rx polynomial: value = (neg ? -1 : 1) * m * 2^e, m normalised. */
struct sf {
	bool neg;
	u32 m;
	int e;
};

static struct sf sf_norm(bool neg, u64 mag, int e)
{
	struct sf r = { neg, 0, 0 };

	if (!mag)
		return r;
	while (mag >> 32) {
		mag >>= 1;
		e++;
	}
	while (!(mag & 0x80000000)) {
		mag <<= 1;
		e--;
	}
	r.m = mag;
	r.e = e;
	return r;
}

static struct sf sf_from_u32(u32 v)
{
	return sf_norm(false, v, 0);
}

/* IEEE-754 binary32 bits; denormals, inf and NaN read as zero. */
static struct sf sf_from_f32(u32 b)
{
	u32 ex = (b >> 23) & 0xff;

	if (!ex || ex == 0xff)
		return sf_norm(false, 0, 0);
	return sf_norm(b >> 31, (b & 0x7fffff) | 0x800000, ex - 150);
}

static struct sf sf_mul(struct sf a, struct sf b)
{
	if (!a.m || !b.m)
		return sf_norm(false, 0, 0);
	return sf_norm(a.neg ^ b.neg, (u64)a.m * b.m, a.e + b.e);
}

static struct sf sf_add(struct sf a, struct sf b)
{
	struct sf t;
	int d;
	s64 x;

	if (!a.m)
		return b;
	if (!b.m)
		return a;
	if (a.e < b.e) {
		t = a;
		a = b;
		b = t;
	}
	d = a.e - b.e;
	x = a.neg ? -(s64)a.m : (s64)a.m;
	if (d < 32)
		x += b.neg ? -(s64)(b.m >> d) : (s64)(b.m >> d);
	return sf_norm(x < 0, x < 0 ? -x : x, a.e);
}

/* Truncating conversion to u32; negative reads as 0, overflow saturates. */
static u32 sf_to_u32(struct sf a)
{
	if (a.neg || !a.m)
		return 0;
	if (a.e >= 1)
		return 0xffffffff;
	if (a.e <= -32)
		return 0;
	return a.m >> -a.e;
}

static u32 be32(const u8 *p)
{
	return p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
}

/* Formula 1: raw * slope(8.8) + offset, truncating like the upstream double cast. */
static u32 cal_u(u32 raw, u32 slp, s32 off)
{
	s64 v = (s64)((u64)raw * slp >> 8) + off;

	return v < 0 ? 0 : v > 0xffffffff ? 0xffffffff : v;
}

static s32 cal_s(s32 raw, u32 slp, s32 off)
{
	u32 mag = (u64)(raw < 0 ? -raw : raw) * slp >> 8;

	return (raw < 0 ? -(s32)mag : (s32)mag) + off;
}

/* Formula 2: Rx_PWR = c4*r^4 + c3*r^3 + c2*r^2 + c1*r + c0 */
static u32 cal_rx(const u8 *a2, u32 raw)
{
	struct sf r = sf_from_u32(raw), p = r;
	struct sf acc = sf_from_f32(be32(a2 + SFF_A2_CAL_RXPWR0));
	static const u8 c[] = { SFF_A2_CAL_RXPWR1, SFF_A2_CAL_RXPWR2,
				SFF_A2_CAL_RXPWR3, SFF_A2_CAL_RXPWR4 };
	int i;

	for (i = 0; i < 4; i++) {
		acc = sf_add(acc, sf_mul(sf_from_f32(be32(a2 + c[i])), p));
		p = sf_mul(p, r);
	}
	return sf_to_u32(acc);
}

static void sff8472_dom_parse(const u8 *a2, struct sff_diags *sd)
{
	sd->bias_cur[MCURR] = A2_U16(SFF_A2_BIAS);
	sd->bias_cur[HALRM] = A2_U16(SFF_A2_BIAS_HALRM);
	sd->bias_cur[LALRM] = A2_U16(SFF_A2_BIAS_LALRM);
	sd->bias_cur[HWARN] = A2_U16(SFF_A2_BIAS_HWARN);
	sd->bias_cur[LWARN] = A2_U16(SFF_A2_BIAS_LWARN);

	sd->sfp_voltage[MCURR] = A2_U16(SFF_A2_VCC);
	sd->sfp_voltage[HALRM] = A2_U16(SFF_A2_VCC_HALRM);
	sd->sfp_voltage[LALRM] = A2_U16(SFF_A2_VCC_LALRM);
	sd->sfp_voltage[HWARN] = A2_U16(SFF_A2_VCC_HWARN);
	sd->sfp_voltage[LWARN] = A2_U16(SFF_A2_VCC_LWARN);

	sd->tx_power[MCURR] = A2_U16(SFF_A2_TX_PWR);
	sd->tx_power[HALRM] = A2_U16(SFF_A2_TX_PWR_HALRM);
	sd->tx_power[LALRM] = A2_U16(SFF_A2_TX_PWR_LALRM);
	sd->tx_power[HWARN] = A2_U16(SFF_A2_TX_PWR_HWARN);
	sd->tx_power[LWARN] = A2_U16(SFF_A2_TX_PWR_LWARN);

	sd->rx_power[MCURR] = A2_U16(SFF_A2_RX_PWR);
	sd->rx_power[HALRM] = A2_U16(SFF_A2_RX_PWR_HALRM);
	sd->rx_power[LALRM] = A2_U16(SFF_A2_RX_PWR_LALRM);
	sd->rx_power[HWARN] = A2_U16(SFF_A2_RX_PWR_HWARN);
	sd->rx_power[LWARN] = A2_U16(SFF_A2_RX_PWR_LWARN);

	sd->sfp_temp[MCURR] = A2_TEMP(SFF_A2_TEMP);
	sd->sfp_temp[HALRM] = A2_TEMP(SFF_A2_TEMP_HALRM);
	sd->sfp_temp[LALRM] = A2_TEMP(SFF_A2_TEMP_LALRM);
	sd->sfp_temp[HWARN] = A2_TEMP(SFF_A2_TEMP_HWARN);
	sd->sfp_temp[LWARN] = A2_TEMP(SFF_A2_TEMP_LWARN);
}

static void sff8472_calibration(const u8 *a2, struct sff_diags *sd)
{
	unsigned int i;

	/* Calibration applies to all values (thresholds and current) */
	for (i = 0; i < ARRAY_SIZE(sd->bias_cur); ++i) {
		sd->bias_cur[i] = cal_u(sd->bias_cur[i], A2_SLP(SFF_A2_CAL_TXI_SLP),
					A2_OFF(SFF_A2_CAL_TXI_OFF));
		sd->tx_power[i] = cal_u(sd->tx_power[i], A2_SLP(SFF_A2_CAL_TXPWR_SLP),
					A2_OFF(SFF_A2_CAL_TXPWR_OFF));
		sd->sfp_voltage[i] = cal_u(sd->sfp_voltage[i], A2_SLP(SFF_A2_CAL_V_SLP),
					   A2_OFF(SFF_A2_CAL_V_OFF));
		sd->sfp_temp[i] = cal_s(sd->sfp_temp[i], A2_SLP(SFF_A2_CAL_T_SLP),
					A2_OFF(SFF_A2_CAL_T_OFF));
		sd->rx_power[i] = cal_rx(a2, sd->rx_power[i]);
	}
}

void sff8472_diags(const u8 *id, const u8 *a2, struct sff_diags *sd)
{
	memset(sd, 0, sizeof(*sd));
	sd->supports_dom = !!(id[SFF_A0_DOM] & SFF_A0_DOM_IMPL);
	sd->supports_alarms = !!(id[SFF_A0_OPTIONS] & SFF_A0_OPTIONS_AW);
	sd->calibrated_ext = !!(id[SFF_A0_DOM] & SFF_A0_DOM_EXTCAL);
	sd->rx_power_type = !!(id[SFF_A0_DOM] & SFF_A0_DOM_PWRT);

	sff8472_dom_parse(a2, sd);

	/* Externally calibrated: compensate the stored readings. */
	if (sd->calibrated_ext)
		sff8472_calibration(a2, sd);
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
