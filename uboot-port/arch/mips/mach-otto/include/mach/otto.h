/* SPDX-License-Identifier: GPL-2.0+ */
/* Realtek Otto (RTL930x) register bases, KSEG1. Facts from RE: docs/hardware.md, docs/CLOCKS.md. */
#ifndef __MACH_OTTO_H
#define __MACH_OTTO_H

#define OTTO_UART0_BASE		0xb8002000
#define OTTO_TIMER_BASE		0xb8003200
#define OTTO_GPIO_BASE		0xb8003300

/* SoC timer 5 (DATA +0, CNT +4, CTRL +8; SDK rtl9300_soc_reg.h): 1 MHz up-count from LX for time
 * bounds that must not depend on the CPU clock. Linux re-programs the timers it uses (TC0/TC1). */
#define OTTO_TC5_CNT		(OTTO_TIMER_BASE + 0x54)
#define OTTO_TC_MASK		0x0fffffff
/* CPU PLL lock bound in clocks_sram.S. No datasheet lock time: assume 200 us worst (SPEC), x1.25 */
#define OTTO_CPU_LOCK_US	250

/* Clock ids of the "realtek,rtl9300-clock" provider: 0-2 = OpenWrt dt-bindings rtl83xx-clk.h */
#define OTTO_CLK_CPU		0
#define OTTO_CLK_MEM		1
#define OTTO_CLK_LXB		2
#define OTTO_CLK_SPI		3	/* ours: SPI-NOR SCK */

#ifndef __ASSEMBLY__
#include <linux/types.h>

/* Rates decoded from the PLL registers (docs/CLOCKS.md). Nothing is hard-coded. */
struct otto_clocks {
	u32 cpu_vco_khz;	/* CPU CMU VCO, 0xbb00e208 */
	u32 sw_vco_khz;		/* SW CMU VCO, 0xbb00e214: feeds LX, NOR, switch core */
	u32 cpu_khz;		/* = OCP0; measured when !cpu_on_pll */
	u32 lx_khz;
	u32 nor_khz;		/* SPI-NOR controller input */
	u32 spi_khz;		/* SPI SCK = nor / SFCR divider */
	u32 mem_khz;		/* DDR clock (data rate x2) */
	bool cpu_on_pll;	/* SSR.ckse_ocp0: 0 = CPU on the alternate clock */
};

void otto_clocks_read(struct otto_clocks *c);
ulong otto_cpu_hz(void);
ulong otto_lx_hz(void);
ulong otto_spi_hz(void);
void otto_us_start(u32 lx_khz);
u32 otto_us_now(void);
u32 otto_us_since(u32 start);
void otto_us_stop(void);
#endif

#endif
