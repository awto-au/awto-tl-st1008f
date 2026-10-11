// SPDX-License-Identifier: GPL-2.0+
/*
 * SFP power budget (#30): sum what every fitted module declares, warn over the board budget.
 * No per-cage limits and no blocking: warn only. Rules + sources: docs/hardware.md "SFP power".
 * Same rules as the Linux mode-switch driver (openwrt/patches/300-06, st_power_mw()).
 */

#include <dm.h>
#include <env.h>
#include <asm/gpio.h>
#include <vsprintf.h>
#include "rtk.h"

#define BOARD_INPUT_MW	24000	/* PSU 12 V 2 A */
#define SFP_BUDGET_MW	15000	/* (24 W input - 6 W measured board) x ~0.85 regulator, as declared module W (#30) */

/* Copper modules cannot declare > 2.0 W; FS datasheet maxima (sources/README.md). */
#define CU_1G_MW	1200	/* SFP-GE-T: 350 mA x 3.47 V */
#define CU_2G5_MW	2000	/* SFP-2.5G-T: "< 2 W" */
#define CU_10G_MW	3000	/* SFP-10G-T-30: 3.0 W max (also used for 5GBASE-T) */

int rtk_sfp_power_mw(const u8 *id, const char **why)
{
	/* byte 64 bit 1 = level 2 (1.5 W), bit 5 = level 3 (2.0 W); SFF-8472 / Linux sfp.c */
	int mw = id[64] & 0x20 ? 2000 : id[64] & 0x02 ? 1500 : 1000, cu = 0;
	u8 ecc = id[36];

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

int rtk_sfp_budget_mw(void)
{
	return env_get_ulong("sfp_budget_mw", 10, SFP_BUDGET_MW);
}

/* MOD-DEF0 low = present; it can read present on an empty cage (#29), so the EEPROM decides. */
static bool cage_maybe_present(int cage)
{
	struct gpio_desc d;

	return rtk_gpio_line(cage - 1, &d) || !gpio_get_ops(d.dev)->get_value(d.dev, d.offset);
}

static void pr_w(int mw)
{
	printf("%d.%d W", mw / 1000, mw % 1000 / 100);
}

int rtk_sfp_power_sum(bool verbose)
{
	int c, mw, total = 0, n = 0, budget = rtk_sfp_budget_mw();
	const char *why;
	u8 id[96];

	for (c = 1; c <= NCAGES; c++) {
		if (!cage_maybe_present(c) || rtk_sfp_read_id(c, id)) {
			if (verbose)
				printf("cage %d: -\n", c);
			continue;
		}
		mw = rtk_sfp_power_mw(id, &why);
		total += mw;
		n++;
		if (verbose) {
			printf("cage %d: ", c);
			pr_w(mw);
			printf(" (%s, A0 byte 64 0x%02x)\n", why, id[64]);
		}
	}
	printf("rtk: SFP power ");
	pr_w(total);
	printf(" declared by %d module%s, budget ", n, n == 1 ? "" : "s");
	pr_w(budget);
	printf(" (env sfp_budget_mw)\n");
	if (total > budget) {
		printf("rtk: WARNING: SFP declared total ");
		pr_w(total);
		printf(" > budget ");
		pr_w(budget);
		printf(" (board input %d W) (#30)\n", BOARD_INPUT_MW / 1000);
	}
	return total;
}
