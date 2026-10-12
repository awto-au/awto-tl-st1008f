/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * RTL9303 switch defaults core (#80, #83): the Realtek SDK "Chip Construct" and bootloader DAL init
 * writes, as generated RMW tables (rtl930x_sw_defaults.h, scripts/sw_defaults_gen.py).
 * Includer defines first: rtl930x_sw_rd(ctx, off), rtl930x_sw_wr(ctx, off, v). Edit only in shared/.
 */
#ifndef _RTL930X_SW_H
#define _RTL930X_SW_H

#include "rtl930x_sw_defaults.h"

#define RTL930X_SW_RST_GLB_CTRL_0	0x000c
#define  RTL930X_SW_RST_TRIGGERS	0x7f	/* [6:0] self-clearing resets incl. SW_CHIP_RST: never written as 1 */

/* rows whose purpose bit (RTL930X_SW_CPU/PERF/POLICY) is in `cats`; returns rows written */
static inline unsigned int rtl930x_sw_apply(void *ctx, const struct rtl930x_sw_rmw *t, unsigned int n,
					    unsigned int cats)
{
	unsigned int i, done = 0;
	u32 v;

	for (i = 0; i < n; i++) {
		if (!(t[i].cat & cats))
			continue;
		done++;
		v = rtl930x_sw_rd(ctx, t[i].off) & ~t[i].mask;
		if (t[i].off == RTL930X_SW_RST_GLB_CTRL_0)
			v &= ~RTL930X_SW_RST_TRIGGERS;
		rtl930x_sw_wr(ctx, t[i].off, v | t[i].val);
	}
	return done;
}

#define RTL930X_SW_APPLY(ctx, table, cats)	rtl930x_sw_apply(ctx, table, sizeof(table) / sizeof((table)[0]), cats)

#endif
