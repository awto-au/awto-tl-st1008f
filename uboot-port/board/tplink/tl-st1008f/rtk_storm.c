// SPDX-License-Identifier: GPL-2.0+
/*
 * Storm control + loop guard (#111): defaults at `rtk network on`, `rtk storm`, `rtk loopdetect`.
 * Core shared with the Linux patch: shared/rtl930x-storm (copied at build). Doc: docs/STORM-PROTECTION.md.
 */

#include <command.h>
#include <env.h>
#include <vsprintf.h>
#include <linux/delay.h>
#include "rtk.h"

static inline u32 rtl930x_storm_rd(void *ctx, u32 off)
{
	return sw_r(off);
}

static inline void rtl930x_storm_wr(void *ctx, u32 off, u32 v)
{
	sw_w(off, v);
}

#include "rtl930x_storm.h"

#define TBL_CTRL	RTL9300_TBL_ACCESS_CTRL_0	/* EXEC 17, CMD 16 (0 = read), TBL 15:12, ADDR 11:0 */
#define TBL_DATA	RTL9300_TBL_ACCESS_DATA_0(0)
#define ISO_TYPE	6				/* PORT_ISO_CTRL: [31:3] = ports 0-28 */
#define TBL_POLL_N	100				/* 100 x 10 us = 1 ms, as rtk_net.c iso_set */

static u32 storm_ports(void)
{
	u32 m = 0;
	int i;

	for (i = 0; i < NCAGES; i++)
		m |= BIT(rtk_cage_port[i]);
	return m;
}

/* env rtk_storm: unset = defaults, "off" = meters off, "<bc>,<mc>,<uc>" pps (0 = that meter off) */
void rtk_storm_defaults(void)
{
	const char *e = env_get("rtk_storm");
	u32 v[3] = { RTL930X_STORM_BC_PPS, RTL930X_STORM_MC_PPS, RTL930X_STORM_UC_PPS };
	char *s;
	int i;

	if (e && !strcmp(e, "off")) {
		v[0] = v[1] = v[2] = 0;
	} else if (e) {
		for (i = 0, s = (char *)e; i < 3 && *s; i++) {
			v[i] = simple_strtoul(s, &s, 10);
			if (*s == ',')
				s++;
		}
	}
	rtl930x_storm_defaults(NULL, storm_ports(), CPU_PORT, v[0], v[1], v[2]);
	printf("rtk: storm control bc/mc/uc %u/%u/%u pps per port, loop-probe trap on (env rtk_storm=%s)\n",
	       v[0], v[1], v[2], e ?: "default");
}

static int iso_get(int port, u32 *pmask)
{
	int i;

	sw_w(TBL_CTRL, BIT(17) | ISO_TYPE << 12 | port);
	for (i = 0; i < TBL_POLL_N; i++) {
		if (!(sw_r(TBL_CTRL) & BIT(17))) {
			*pmask = sw_r(TBL_DATA) >> 3;
			return 0;
		}
		udelay(10);
	}
	printf("rtk: isolation table read port %d busy after %d us\n", port, TBL_POLL_N * 10);
	return -1;
}

static void storm_show(bool clear)
{
	u32 ex[RTL930X_STORM_T_N], pps, burst;
	int c, t, port;

	for (t = 0; t < RTL930X_STORM_T_N; t++)
		ex[t] = rtl930x_storm_exceed(NULL, t, clear);
	printf("STORM_CTRL 0x%08x (bypass bpdu %d rma %d rtkpkt %d), mode 0x%08x (bit = bps), drops %u (cleared)\n",
	       sw_r(RTL930X_STORM_CTRL), !!(sw_r(RTL930X_STORM_CTRL) & RTL930X_STORM_ADMIT_BPDU),
	       !!(sw_r(RTL930X_STORM_CTRL) & RTL930X_STORM_ADMIT_RMA),
	       !!(sw_r(RTL930X_STORM_CTRL) & RTL930X_STORM_ADMIT_RTKPKT), sw_r(RTL930X_STORM_PORT_CTRL),
	       sw_r(RTL930X_STORM_DROP_CNTR) & 0xffff);
	for (c = 0; c <= NCAGES; c++) {
		port = c < NCAGES ? rtk_cage_port[c] : CPU_PORT;	/* CPU: no unknown-unicast meter */
		if (c < NCAGES)
			printf("cage %d (port %2d):", c + 1, port);
		else
			printf("cpu    (port %2d):", port);
		for (t = 0; t < RTL930X_STORM_T_N; t++) {
			if (rtl930x_storm_get(NULL, port, t, &pps, &burst))
				printf(" %s %u pps/%u", rtl930x_storm_names[t], pps, burst);
			else
				printf(" %s off", rtl930x_storm_names[t]);
			if (ex[t] & BIT(port))
				printf(" EXCEEDED");
		}
		printf("\n");
	}
}

/* `rtk storm [show | clear | on | off | <bc> <mc> <uc>]` */
int rtk_storm(int argc, char *const argv[])
{
	if (argc <= 2 || !strcmp(argv[2], "show")) {
		storm_show(false);
	} else if (!strcmp(argv[2], "clear")) {
		storm_show(true);
	} else if (!strcmp(argv[2], "on")) {
		rtk_storm_defaults();
	} else if (!strcmp(argv[2], "off")) {
		rtl930x_storm_defaults(NULL, storm_ports(), CPU_PORT, 0, 0, 0);
		printf("rtk: storm control off (until the next `rtk storm on` / network on)\n");
	} else if (argc == 5) {
		rtl930x_storm_defaults(NULL, storm_ports(), CPU_PORT, dectoul(argv[2], NULL), dectoul(argv[3], NULL),
				       dectoul(argv[4], NULL));
		storm_show(false);
	} else {
		return CMD_RET_USAGE;
	}
	return 0;
}

/* `rtk loopdetect`: can any cage forward to another cage (iso table), probe trap, ports disabled */
int rtk_loopdetect(int argc, char *const argv[])
{
	u32 cages = 0, m;
	int c, open = 0;

	for (c = 0; c < NCAGES; c++)
		cages |= BIT(rtk_cage_port[c]);
	printf("loop-probe trap (RLDP_RLPP_CTRL 0x%x): %s\n", sw_r(RTL930X_RLDP_CTRL),
	       (sw_r(RTL930X_RLDP_CTRL) & 3) == RTL930X_RLDP_TRAP_CPU ? "to CPU" : "OFF (forwarded)");
	for (c = 0; c < NCAGES; c++) {
		if (iso_get(rtk_cage_port[c], &m))
			return CMD_RET_FAILURE;
		m &= cages & ~BIT(rtk_cage_port[c]);
		open += !!m;
		printf("cage %d (port %2d): forwards to cages 0x%07x%s, mac tx/rx %s\n", c + 1,
		       rtk_cage_port[c], m, m ? " (LOOP POSSIBLE)" : "",
		       (sw_r(RTL930X_MAC_L2_PORT_CTRL(rtk_cage_port[c])) & RTL930X_MAC_TXRX_EN) == RTL930X_MAC_TXRX_EN ?
		       "on" : "OFF");
	}
	printf("%s\n", open ? "cage-to-cage forwarding open: cabled loops storm; `rtk linkcheck` probes them" :
	       "guard: every cage forwards to the CPU only, no cage loop can form in U-Boot");
	return 0;
}
