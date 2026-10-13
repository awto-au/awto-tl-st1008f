/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * RTL9303 storm control + loop-probe trap defaults (#111), shared by our U-Boot and Linux patch.
 * Registers: Realtek SDK swcore_rtl9300.h, dal_longan_rate.c, dal_longan_trap.c (GPL-2.0).
 * Includer defines first: rtl930x_storm_rd(ctx, off), rtl930x_storm_wr(ctx, off, v). Edit only in shared/.
 * Facts + chosen limits: docs/STORM-PROTECTION.md.
 */
#ifndef _RTL930X_STORM_H
#define _RTL930X_STORM_H

/* STORM_CTRL ADMIT_*: frame type bypasses the meters (STP, LACP/LLDP and our loop probes get through) */
#define RTL930X_STORM_CTRL		0x8a60
#define  RTL930X_STORM_ADMIT_RMA	(1u << 3)
#define  RTL930X_STORM_ADMIT_BPDU	(1u << 2)
#define  RTL930X_STORM_ADMIT_RTKPKT	(1u << 1)
#define  RTL930X_STORM_ADMIT		(RTL930X_STORM_ADMIT_RMA | RTL930X_STORM_ADMIT_BPDU | RTL930X_STORM_ADMIT_RTKPKT)
#define RTL930X_STORM_PORT_CTRL		0x8a6c	/* MODE, bit per port: 0 = pps, 1 = 16 kbps units */
/* 64-bit per port: word +0 = TYPE[25] EN[24] RATE[23:0], word +4 = BURST[15:0] (packets in pps mode) */
#define RTL930X_STORM_UC		0x8a70
#define RTL930X_STORM_MC		0x8b60
#define RTL930X_STORM_BC		0x8c50
#define  RTL930X_STORM_TYPE_ALL		(1u << 25)	/* UC/MC: 0 = unknown only, 1 = known + unknown */
#define  RTL930X_STORM_EN		(1u << 24)
#define  RTL930X_STORM_RATE		0x00ffffffu
#define  RTL930X_STORM_BURST		0x0000ffffu
/* bit per port: bucket reset at LB_RST, EXCEED flag at LB_RST + 4 (1 = over the rate, write 1 to clear) */
#define RTL930X_STORM_UC_LB_RST		0x8b58
#define RTL930X_STORM_MC_LB_RST		0x8c48
#define RTL930X_STORM_BC_LB_RST		0x8d38
/* RLDP_RLPP_TRAP[1:0]: 0 forward, 1 trap to CPU, 2 trap to master CPU (ethertype 0x8899) */
#define RTL930X_RLDP_CTRL		0xa250
#define  RTL930X_RLDP_TRAP_CPU		1u
#define RTL930X_MAC_L2_PORT_CTRL(p)	(0x3268 + 64 * (p))	/* TX_EN 1, RX_EN 0 */
#define  RTL930X_MAC_TXRX_EN		3u
#define RTL930X_STORM_DROP_CNTR		0xb6a8	/* drop reason 60 STORM_CONTROL: 16 bit, clear on read */

/* Loop probe: Realtek ethertype + RLDP protocol byte, so the RLDP trap returns it to the CPU */
#define RTL930X_LOOP_ETHERTYPE		0x8899
#define RTL930X_LOOP_PROTO_RLDP		0x03

enum rtl930x_storm_type { RTL930X_STORM_T_BC, RTL930X_STORM_T_MC, RTL930X_STORM_T_UC, RTL930X_STORM_T_N };

static const char *const rtl930x_storm_names[RTL930X_STORM_T_N] = { "broadcast", "multicast", "unknown-unicast" };

/* Defaults per ingress port, pps; burst = 100 ms worth. Why these numbers: docs/STORM-PROTECTION.md#limits */
#define RTL930X_STORM_BC_PPS		10000
#define RTL930X_STORM_MC_PPS		20000
#define RTL930X_STORM_UC_PPS		20000

static inline u32 rtl930x_storm_base(int t)
{
	return t == RTL930X_STORM_T_BC ? RTL930X_STORM_BC : t == RTL930X_STORM_T_MC ? RTL930X_STORM_MC : RTL930X_STORM_UC;
}

static inline u32 rtl930x_storm_rst(int t)
{
	return t == RTL930X_STORM_T_BC ? RTL930X_STORM_BC_LB_RST :
	       t == RTL930X_STORM_T_MC ? RTL930X_STORM_MC_LB_RST : RTL930X_STORM_UC_LB_RST;
}

/* pps -> RATE: SDK "LONGAN SS-528" correction, rate x 1000 / 1014 rounded */
static inline u32 rtl930x_storm_pps_to_hw(u32 pps)
{
	return pps / 1014 * 1000 + ((pps % 1014) * 1000 + 507) / 1014;
}

static inline u32 rtl930x_storm_hw_to_pps(u32 hw)
{
	return hw / 1000 * 1014 + ((hw % 1000) * 1014 + 500) / 1000;
}

/* one meter: pps 0 = off; port 0-28 (28 = CPU) */
static inline void rtl930x_storm_set(void *ctx, int port, int t, u32 pps)
{
	u32 off = rtl930x_storm_base(t) + 8 * port, burst = pps / 10;
	u32 hi = rtl930x_storm_rd(ctx, off) & ~(RTL930X_STORM_EN | RTL930X_STORM_RATE | RTL930X_STORM_TYPE_ALL);

	if (pps > RTL930X_STORM_RATE)
		pps = RTL930X_STORM_RATE;
	if (burst > RTL930X_STORM_BURST)
		burst = RTL930X_STORM_BURST;
	if (pps)
		hi |= RTL930X_STORM_EN | rtl930x_storm_pps_to_hw(pps);
	else
		hi |= RTL930X_STORM_RATE;	/* reset value 0xfffff..: rate field unused while off */
	if (t == RTL930X_STORM_T_MC)
		hi |= RTL930X_STORM_TYPE_ALL;	/* every multicast; UC stays unknown-only (DLF) */
	rtl930x_storm_wr(ctx, off + 4, (rtl930x_storm_rd(ctx, off + 4) & ~RTL930X_STORM_BURST) | (burst ? burst : 1));
	rtl930x_storm_wr(ctx, off, hi);
	rtl930x_storm_wr(ctx, rtl930x_storm_rst(t), 1u << port);	/* bucket reset (SDK writes it after every change) */
}

/* readback: 1 if enabled; *pps = rate as pps, *burst packets */
static inline int rtl930x_storm_get(void *ctx, int port, int t, u32 *pps, u32 *burst)
{
	u32 off = rtl930x_storm_base(t) + 8 * port, hi = rtl930x_storm_rd(ctx, off);

	*pps = rtl930x_storm_hw_to_pps(hi & RTL930X_STORM_RATE);
	*burst = rtl930x_storm_rd(ctx, off + 4) & RTL930X_STORM_BURST;
	return !!(hi & RTL930X_STORM_EN);
}

/* EXCEED flags of one type (bit per port); clear = write the bits back */
static inline u32 rtl930x_storm_exceed(void *ctx, int t, int clear)
{
	u32 v = rtl930x_storm_rd(ctx, rtl930x_storm_rst(t) + 4);

	if (clear && v)
		rtl930x_storm_wr(ctx, rtl930x_storm_rst(t) + 4, v);
	return v;
}

/* defaults on the front ports in `pmask` + the CPU port: pps mode, BC/MC/UC meters, STP/RMA/probe
 * bypass, RLDP trap. CPU port: BC/MC only; its tagged TX may count as unknown unicast (NAT path). */
static inline void rtl930x_storm_defaults(void *ctx, u32 pmask, int cpu, u32 bc, u32 mc, u32 uc)
{
	const u32 pps[RTL930X_STORM_T_N] = { bc, mc, uc };
	int p, t;

	pmask |= 1u << cpu;

	rtl930x_storm_wr(ctx, RTL930X_STORM_CTRL, rtl930x_storm_rd(ctx, RTL930X_STORM_CTRL) | RTL930X_STORM_ADMIT);
	rtl930x_storm_wr(ctx, RTL930X_STORM_PORT_CTRL, rtl930x_storm_rd(ctx, RTL930X_STORM_PORT_CTRL) & ~pmask);
	for (p = 0; p < 29; p++)
		if (pmask & (1u << p))
			for (t = 0; t < RTL930X_STORM_T_N; t++)
				rtl930x_storm_set(ctx, p, t, p == cpu && t == RTL930X_STORM_T_UC ? 0 : pps[t]);
	rtl930x_storm_wr(ctx, RTL930X_RLDP_CTRL, (rtl930x_storm_rd(ctx, RTL930X_RLDP_CTRL) & ~3u) | RTL930X_RLDP_TRAP_CPU);
}

#endif
