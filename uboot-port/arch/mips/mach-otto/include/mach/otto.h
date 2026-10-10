/* SPDX-License-Identifier: GPL-2.0+ */
/* Realtek Otto (RTL930x) register bases, KSEG1. Facts from RE: docs/hardware.md, docs/CLOCKS.md. */
#ifndef __MACH_OTTO_H
#define __MACH_OTTO_H

#include <linux/types.h>

#define OTTO_UART0_BASE		0xb8002000
#define OTTO_TIMER_BASE		0xb8003200
#define OTTO_GPIO_BASE		0xb8003300

/* Clock ids of the "realtek,rtl9300-clock" provider: 0-2 = OpenWrt dt-bindings rtl83xx-clk.h */
#define OTTO_CLK_CPU		0
#define OTTO_CLK_MEM		1
#define OTTO_CLK_LXB		2
#define OTTO_CLK_SPI		3	/* ours: SPI-NOR SCK */

/* Rates decoded from the PLL registers (docs/CLOCKS.md). Nothing is cached or hard-coded. */
struct otto_clocks {
	u32 cpu_vco_khz;	/* CPU CMU VCO, 0xbb00e208 */
	u32 sw_vco_khz;		/* SW CMU VCO, 0xbb00e214: feeds LX, NOR, switch core */
	u32 cpu_khz;		/* = OCP0 */
	u32 lx_khz;
	u32 nor_khz;		/* SPI-NOR controller input */
	u32 spi_khz;		/* SPI SCK = nor / SFCR divider */
	u32 mem_khz;		/* DDR clock (data rate x2) */
	bool cpu_on_pll;	/* SSR.ckse_ocp0: 0 = CPU on the alternate clock, rate unknown */
};

void otto_clocks_read(struct otto_clocks *c);
ulong otto_cpu_hz(void);
ulong otto_lx_hz(void);
ulong otto_spi_hz(void);

#endif
