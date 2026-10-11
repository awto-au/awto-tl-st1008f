// SPDX-License-Identifier: GPL-2.0+
/* TP-Link TL-ST1008F v2: board hooks. */

#include <command.h>
#include <env.h>
#include <init.h>
#include <asm/io.h>
#include <linux/delay.h>
#include "rtk.h"

/* Stock bootcmd writes this before chainloading us from flash (#47); ramload does not */
#define CHAIN_MARK_ADDR	((void __iomem *)0xa0f80000)	/* KSEG1: below TEXT_BASE, above init stack */
#define CHAIN_MARK	0xa5a51008
#define BOOTCMD_M1	"clocks fast; bootm 0xb4300000"
#define MODE_SETTLE_MS	30	/* stock rtk.ko settle before each pin read (docs/hardware.md) */

static const char *const mode_name[] = { "normal", "easy", "recovery" };

/*
 * Boot policy from the mode switch (#8, #46). Pins 18/19 decide (one-hot; pin 17 measured
 * high at M2/M3 under OpenWrt). 18 low = M2, 19 low = M3, both high = M1. Both low or an unstable read
 * = invalid: 0 (callers treat it as M1). *pins = DATA bits 17-19 of the first read.
 */
int st1008f_boot_mode(u32 *pins)
{
	u32 a = (__raw_readl((void __iomem *)GPIO_DAT) >> 17) & 7, b;

	mdelay(MODE_SETTLE_MS);
	b = (__raw_readl((void __iomem *)GPIO_DAT) >> 17) & 7;
	if (pins)
		*pins = a;
	if (a != b)
		return 0;
	switch (a & 6) {	/* bit 1 = pin 18, bit 2 = pin 19 */
	case 6: return 1;
	case 4: return 2;
	case 2: return 3;
	default: return 0;
	}
}

const char *st1008f_mode_name(int mode)
{
	return mode >= 1 && mode <= 3 ? mode_name[mode - 1] : "invalid";
}

int board_init(void)
{
	return 0;
}

/* boot_mode from the switch; chainloaded from flash + M1: autoboot flash OpenWrt, else prompt */
int board_late_init(void)
{
	bool chained = __raw_readl(CHAIN_MARK_ADDR) == CHAIN_MARK;
	u32 pins;
	int mode = st1008f_boot_mode(&pins);
	char m[3] = { 'M', '0' + (mode ? mode : 1), 0 };

	if (chained)
		__raw_writel(0, CHAIN_MARK_ADDR);
	if (!mode)
		printf("Mode:  invalid, pins 17/18/19 = %u/%u/%u -> M1\n", pins & 1, (pins >> 1) & 1,
		       (pins >> 2) & 1);
	else
		printf("Mode:  M%d %s, pins 17/18/19 = %u/%u/%u\n", mode, mode_name[mode - 1],
		       pins & 1, (pins >> 1) & 1, (pins >> 2) & 1);
	env_set("boot_mode", m);
	env_set("bootcmd_m1", BOOTCMD_M1);
	/* #25 boot table, opt-in (adds ~9 s): `setenv rtk_boot_net 1` (RAM env unless saved) */
	if (env_get_yesno("rtk_boot_net") == 1)
		run_command("rtk network on; rtk port", 0);
	if (!chained)
		return 0;
	if (mode >= 2) {	/* M2 DHCP/netconsole, M3 TFTP recovery: both need Ethernet */
		printf("Mode:  M%d needs Ethernet (stage 4, #46): no autoboot; `run bootcmd_m1` boots OpenWrt\n",
		       mode);
		return 0;
	}
	env_set("bootcmd", BOOTCMD_M1);
	env_set("bootdelay", "1");
	return 0;
}
