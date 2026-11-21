// SPDX-License-Identifier: GPL-2.0
/*
 * SFF-8472 digital diagnostics (DDM/DOM) scaling for sfp_core: no I/O, integer fixed point only.
 * Origin: ethtool sfpdiag.c (ethtool 7.1, 6b7b16e), Aurelien Guillaume <aurelien@iwi.me> (C) 2012,
 * loosely based on DOM patches from Robert Olsson (C) 2009 and SFF-8472.
 * Changes vs upstream: doubles replaced by integer fixed point (soft-float for the Rx polynomial);
 * A2 passed as its own buffer; Rx external-cal polynomial per SFF-8472 (upstream omits r^2..r^4
 * and Rx_PWR(4)); wider integer fields (no u16 wrap); output left to the caller.
 */

#include "sfp_core.h"

/* A0 offsets for the DOM checks (decimal, as in the SFF spec) */
#define A0_DOM			92
#define A0_OPTIONS		93
#define A0_DOM_EXTCAL		(1 << 4)
#define A0_DOM_IMPL		(1 << 6)
#define A0_DOM_PWRT		(1 << 3)
#define A0_OPTIONS_AW		(1 << 7)

/* A2 offsets: live value, then high/low alarm and high/low warning thresholds */
#define A2_TEMP			96
#define A2_TEMP_HALRM		0
#define A2_TEMP_LALRM		2
#define A2_TEMP_HWARN		4
#define A2_TEMP_LWARN		6
#define A2_VCC			98
#define A2_VCC_HALRM		8
#define A2_VCC_LALRM		10
#define A2_VCC_HWARN		12
#define A2_VCC_LWARN		14
#define A2_BIAS			100
#define A2_BIAS_HALRM		16
#define A2_BIAS_LALRM		18
#define A2_BIAS_HWARN		20
#define A2_BIAS_LWARN		22
#define A2_TX_PWR		102
#define A2_TX_PWR_HALRM		24
#define A2_TX_PWR_LALRM		26
#define A2_TX_PWR_HWARN		28
#define A2_TX_PWR_LWARN		30
#define A2_RX_PWR		104
#define A2_RX_PWR_HALRM		32
#define A2_RX_PWR_LALRM		34
#define A2_RX_PWR_HWARN		36
#define A2_RX_PWR_LWARN		38

/* 32-bit big-endian IEEE-754 calibration constants */
#define A2_CAL_RXPWR4		56
#define A2_CAL_RXPWR3		60
#define A2_CAL_RXPWR2		64
#define A2_CAL_RXPWR1		68
#define A2_CAL_RXPWR0		72
/* 16-bit calibration constants: slope 8.8 unsigned, offset signed */
#define A2_CAL_TXI_SLP		76
#define A2_CAL_TXI_OFF		78
#define A2_CAL_TXPWR_SLP	80
#define A2_CAL_TXPWR_OFF	82
#define A2_CAL_T_SLP		84
#define A2_CAL_T_OFF		86
#define A2_CAL_V_SLP		88
#define A2_CAL_V_OFF		90

typedef unsigned long long u64_;
typedef long long s64_;

#define A2_U16(o)	((unsigned int)(a2[o] << 8 | a2[(o) + 1]))
#define A2_SLP(o)	A2_U16(o)
#define A2_OFF(o)	((short)A2_U16(o))
#define A2_TEMPV(o)	((short)A2_U16(o))

/* Minimal soft float for the Rx polynomial: value = (neg ? -1 : 1) * m * 2^e, m normalised. */
struct sf {
	int neg;
	unsigned int m;
	int e;
};

static struct sf sf_norm(int neg, u64_ mag, int e)
{
	struct sf r = { neg, 0, 0 };

	if (!mag)
		return r;
	while (mag >> 32) {
		mag >>= 1;
		e++;
	}
	while (!(mag & 0x80000000u)) {
		mag <<= 1;
		e--;
	}
	r.m = (unsigned int)mag;
	r.e = e;
	return r;
}

static struct sf sf_from_u32(unsigned int v)
{
	return sf_norm(0, v, 0);
}

/* IEEE-754 binary32 bits; denormals, inf and NaN read as zero. */
static struct sf sf_from_f32(unsigned int b)
{
	unsigned int ex = (b >> 23) & 0xff;

	if (!ex || ex == 0xff)
		return sf_norm(0, 0, 0);
	return sf_norm(b >> 31, (b & 0x7fffff) | 0x800000, (int)ex - 150);
}

static struct sf sf_mul(struct sf a, struct sf b)
{
	if (!a.m || !b.m)
		return sf_norm(0, 0, 0);
	return sf_norm(a.neg ^ b.neg, (u64_)a.m * b.m, a.e + b.e);
}

static struct sf sf_add(struct sf a, struct sf b)
{
	struct sf t;
	int d;
	s64_ x;

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
	x = a.neg ? -(s64_)a.m : (s64_)a.m;
	if (d < 32)
		x += b.neg ? -(s64_)(b.m >> d) : (s64_)(b.m >> d);
	return sf_norm(x < 0, x < 0 ? -x : x, a.e);
}

/* Truncating conversion to u32; negative reads as 0, overflow saturates. */
static unsigned int sf_to_u32(struct sf a)
{
	if (a.neg || !a.m)
		return 0;
	if (a.e >= 1)
		return 0xffffffffu;
	if (a.e <= -32)
		return 0;
	return a.m >> -a.e;
}

static unsigned int be32(const sfp_u8 *p)
{
	return (unsigned int)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
}

/* Formula 1: raw * slope(8.8) + offset, truncating like the upstream double cast. */
static unsigned int cal_u(unsigned int raw, unsigned int slp, int off)
{
	s64_ v = (s64_)((u64_)raw * slp >> 8) + off;

	return v < 0 ? 0 : v > 0xffffffffLL ? 0xffffffffu : (unsigned int)v;
}

static int cal_s(int raw, unsigned int slp, int off)
{
	unsigned int mag = (unsigned int)((u64_)(raw < 0 ? -raw : raw) * slp >> 8);

	return (raw < 0 ? -(int)mag : (int)mag) + off;
}

/* Formula 2: Rx_PWR = c4*r^4 + c3*r^3 + c2*r^2 + c1*r + c0 */
static unsigned int cal_rx(const sfp_u8 *a2, unsigned int raw)
{
	struct sf r = sf_from_u32(raw), p = r;
	struct sf acc = sf_from_f32(be32(a2 + A2_CAL_RXPWR0));
	static const sfp_u8 c[] = { A2_CAL_RXPWR1, A2_CAL_RXPWR2, A2_CAL_RXPWR3, A2_CAL_RXPWR4 };
	int i;

	for (i = 0; i < 4; i++) {
		acc = sf_add(acc, sf_mul(sf_from_f32(be32(a2 + c[i])), p));
		p = sf_mul(p, r);
	}
	return sf_to_u32(acc);
}

static void ddm_parse(const sfp_u8 *a2, struct sfp_ddm *d)
{
	d->bias[SFP_DDM_CURR] = A2_U16(A2_BIAS);
	d->bias[SFP_DDM_HALRM] = A2_U16(A2_BIAS_HALRM);
	d->bias[SFP_DDM_LALRM] = A2_U16(A2_BIAS_LALRM);
	d->bias[SFP_DDM_HWARN] = A2_U16(A2_BIAS_HWARN);
	d->bias[SFP_DDM_LWARN] = A2_U16(A2_BIAS_LWARN);

	d->vcc[SFP_DDM_CURR] = A2_U16(A2_VCC);
	d->vcc[SFP_DDM_HALRM] = A2_U16(A2_VCC_HALRM);
	d->vcc[SFP_DDM_LALRM] = A2_U16(A2_VCC_LALRM);
	d->vcc[SFP_DDM_HWARN] = A2_U16(A2_VCC_HWARN);
	d->vcc[SFP_DDM_LWARN] = A2_U16(A2_VCC_LWARN);

	d->tx_power[SFP_DDM_CURR] = A2_U16(A2_TX_PWR);
	d->tx_power[SFP_DDM_HALRM] = A2_U16(A2_TX_PWR_HALRM);
	d->tx_power[SFP_DDM_LALRM] = A2_U16(A2_TX_PWR_LALRM);
	d->tx_power[SFP_DDM_HWARN] = A2_U16(A2_TX_PWR_HWARN);
	d->tx_power[SFP_DDM_LWARN] = A2_U16(A2_TX_PWR_LWARN);

	d->rx_power[SFP_DDM_CURR] = A2_U16(A2_RX_PWR);
	d->rx_power[SFP_DDM_HALRM] = A2_U16(A2_RX_PWR_HALRM);
	d->rx_power[SFP_DDM_LALRM] = A2_U16(A2_RX_PWR_LALRM);
	d->rx_power[SFP_DDM_HWARN] = A2_U16(A2_RX_PWR_HWARN);
	d->rx_power[SFP_DDM_LWARN] = A2_U16(A2_RX_PWR_LWARN);

	d->temp[SFP_DDM_CURR] = A2_TEMPV(A2_TEMP);
	d->temp[SFP_DDM_HALRM] = A2_TEMPV(A2_TEMP_HALRM);
	d->temp[SFP_DDM_LALRM] = A2_TEMPV(A2_TEMP_LALRM);
	d->temp[SFP_DDM_HWARN] = A2_TEMPV(A2_TEMP_HWARN);
	d->temp[SFP_DDM_LWARN] = A2_TEMPV(A2_TEMP_LWARN);
}

/* External calibration applies to the live values and the thresholds alike. */
static void ddm_calibrate(const sfp_u8 *a2, struct sfp_ddm *d)
{
	int i;

	for (i = 0; i < 5; i++) {
		d->bias[i] = cal_u(d->bias[i], A2_SLP(A2_CAL_TXI_SLP), A2_OFF(A2_CAL_TXI_OFF));
		d->tx_power[i] = cal_u(d->tx_power[i], A2_SLP(A2_CAL_TXPWR_SLP), A2_OFF(A2_CAL_TXPWR_OFF));
		d->vcc[i] = cal_u(d->vcc[i], A2_SLP(A2_CAL_V_SLP), A2_OFF(A2_CAL_V_OFF));
		d->temp[i] = cal_s(d->temp[i], A2_SLP(A2_CAL_T_SLP), A2_OFF(A2_CAL_T_OFF));
		d->rx_power[i] = cal_rx(a2, d->rx_power[i]);
	}
}

int sfp_ddm_decode(const sfp_u8 *a0, size_t a0_len, const sfp_u8 *a2, size_t a2_len, struct sfp_ddm *d)
{
	size_t i;

	for (i = 0; i < sizeof(*d); i++)
		((sfp_u8 *)d)[i] = 0;
	if (a0_len < A0_OPTIONS + 1 || !(a0[A0_DOM] & A0_DOM_IMPL))
		return 0;
	d->supports_dom = 1;
	d->supports_alarms = !!(a0[A0_OPTIONS] & A0_OPTIONS_AW);
	d->calibrated_ext = !!(a0[A0_DOM] & A0_DOM_EXTCAL);
	d->rx_power_type = !!(a0[A0_DOM] & A0_DOM_PWRT);
	if (a2_len < SFP_DDM_A2_LEN)
		return 0;
	ddm_parse(a2, d);
	if (d->calibrated_ext)
		ddm_calibrate(a2, d);
	return 1;
}
