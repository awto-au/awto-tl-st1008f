// SPDX-License-Identifier: GPL-2.0+
/* TP-Link TL-ST1008F v2: board hooks. */

#include <env.h>
#include <init.h>
#include <asm/io.h>

/* Stock bootcmd writes this before chainloading us from flash (#47); ramload does not */
#define CHAIN_MARK_ADDR	((void __iomem *)0xa0f80000)	/* KSEG1: below TEXT_BASE, above init stack */
#define CHAIN_MARK	0xa5a51008

int board_init(void)
{
	return 0;
}

/* chainloaded from flash: autoboot flash OpenWrt at the measured clocks; else stay at the prompt */
int board_late_init(void)
{
	if (__raw_readl(CHAIN_MARK_ADDR) != CHAIN_MARK)
		return 0;
	__raw_writel(0, CHAIN_MARK_ADDR);
	env_set("bootcmd", "clocks fast; bootm 0xb4300000");
	env_set("bootdelay", "1");
	return 0;
}
