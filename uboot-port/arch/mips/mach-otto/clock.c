// SPDX-License-Identifier: GPL-2.0+
/*
 * RTL930x clock tree, read-only: rates decoded from the PLL registers on every call (CPU rate
 * measured on the alternate clock). TC5 1 MHz time base for CPU-clock-independent bounds.
 * Register map, formulas and sources: docs/CLOCKS.md. Also supplies the CP0 timer rate.
 */

#include <clk-uclass.h>
#include <dm.h>
#include <stdio.h>
#include <time.h>
#include <asm/io.h>
#include <asm/mipsregs.h>
#include <linux/bitfield.h>
#include <linux/bitops.h>
#include <linux/math64.h>
#include <mach/otto.h>

#define SW(off)		((void __iomem *)(0xbb000000 + (off)))
#define SOC(off)	((void __iomem *)(0xb8000000 + (off)))

#define PLL_CPU_CTRL0	SW(0xe208)	/* NCODE 11:4, SEL_DIV4 2, SEL_PREDIV 1:0 */
#define PLL_CPU_MISC	SW(0xe210)	/* DIVN2_CPU 6:4 */
#define PLL_SW_CTRL0	SW(0xe214)	/* same layout as CPU_CTRL0 */
#define PLL_SW_DIV	SW(0xe220)	/* DIVN2_SPI_NOR 16:13, DIVN2_LXB 12:9 */
#define SOC_SSR		SOC(0x0044)	/* ckse_ocp0 2 */
#define MEM_PLL2	SOC(0x023c)	/* PDIV 15:14 */
#define MEM_PLL3	SOC(0x0240)	/* NCODE 31:24 */
#define SPI_SFCR	SOC(0x1200)	/* SPI_CLK_DIV 31:29 */

static u32 rd(void __iomem *a)
{
	return __raw_readl(a);
}

#define TC5_DATA	SOC(0x3250)
#define TC5_CTRL	SOC(0x3258)
#define TC_EN		BIT(28)
#define TC_MODE_TIMER	BIT(24)	/* up-count to DATA, as Linux timer-rtl-otto's clocksource */

void otto_us_start(u32 lx_khz)
{
	__raw_writel(0, TC5_CTRL);
	__raw_writel(OTTO_TC_MASK, TC5_DATA);
	__raw_writel(TC_EN | TC_MODE_TIMER | (lx_khz / 1000), TC5_CTRL);	/* LX / divisor = 1 MHz */
}

u32 otto_us_now(void)
{
	return __raw_readl((void __iomem *)OTTO_TC5_CNT) & OTTO_TC_MASK;
}

u32 otto_us_since(u32 start)
{
	return (otto_us_now() - start) & OTTO_TC_MASK;
}

void otto_us_stop(void)
{
	__raw_writel(0, TC5_CTRL);
}

/* CPU on the alternate clock (no PLL lock): rate = 2 x CP0 Count over 1000 us of TC5, measured once
 * per alternate-clock episode. Bound: Count advance of 1.25 ms at 1.2 GHz (above any rate this SoC
 * runs); expiry = TC5 not counting -> log, caller keeps the PLL-decoded rate. */
#define ALT_WINDOW_US	1000
#define ALT_COUNT_MAX	750000
static u32 alt_khz __section(".data");

static u32 cpu_alt_khz(u32 lx_khz)
{
	u32 t0, c0, dc;

	if (alt_khz)
		return alt_khz;
	otto_us_start(lx_khz);
	t0 = otto_us_now();
	c0 = read_c0_count();
	while (otto_us_since(t0) < ALT_WINDOW_US) {
		dc = read_c0_count() - c0;
		if (dc > ALT_COUNT_MAX) {
			otto_us_stop();
			printf("clocks: CPU on the alternate clock; TC5 did not reach %u us within %u CP0 counts\n",
			       ALT_WINDOW_US, ALT_COUNT_MAX);
			return 0;
		}
	}
	dc = read_c0_count() - c0;
	alt_khz = (u32)div_u64((u64)dc * 2 * 1000, otto_us_since(t0));
	otto_us_stop();
	printf("clocks: CPU on the alternate clock, measured %u kHz\n", alt_khz);
	return alt_khz;
}

/* VCO = ref x (NCODE + 2) x 2 / 2^PREDIV; ref 25 MHz, x4 with SEL_DIV4 (stock preloader math) */
static u32 cmu_vco_khz(u32 ctrl0)
{
	u32 ref = (ctrl0 & BIT(2)) ? 100000 : 25000;

	return ref * (FIELD_GET(GENMASK(11, 4), ctrl0) + 2) * 2 >> (ctrl0 & 3);
}

void otto_clocks_read(struct otto_clocks *c)
{
	u32 div = rd(PLL_SW_DIV);
	u32 mem2 = rd(MEM_PLL2);

	c->cpu_vco_khz = cmu_vco_khz(rd(PLL_CPU_CTRL0));
	c->cpu_khz = c->cpu_vco_khz / (FIELD_GET(GENMASK(6, 4), rd(PLL_CPU_MISC)) + 2);
	c->cpu_on_pll = rd(SOC_SSR) & BIT(2);
	c->sw_vco_khz = cmu_vco_khz(rd(PLL_SW_CTRL0));
	c->lx_khz = c->sw_vco_khz / (2 * (FIELD_GET(GENMASK(12, 9), div) + 2));
	if (c->cpu_on_pll)
		alt_khz = 0;
	else
		c->cpu_khz = cpu_alt_khz(c->lx_khz) ?: c->cpu_khz;
	c->nor_khz = c->sw_vco_khz / (2 * (FIELD_GET(GENMASK(16, 13), div) + 2));
	c->spi_khz = c->nor_khz / (2 * (FIELD_GET(GENMASK(31, 29), rd(SPI_SFCR)) + 1));
	c->mem_khz = 25000 * (FIELD_GET(GENMASK(31, 24), rd(MEM_PLL3)) + 2) /
		     (2 << FIELD_GET(GENMASK(15, 14), mem2));
}

ulong otto_cpu_hz(void)
{
	struct otto_clocks c;

	otto_clocks_read(&c);
	return c.cpu_khz * 1000UL;
}

ulong otto_lx_hz(void)
{
	struct otto_clocks c;

	otto_clocks_read(&c);
	return c.lx_khz * 1000UL;
}

ulong otto_spi_hz(void)
{
	struct otto_clocks c;

	otto_clocks_read(&c);
	return c.spi_khz * 1000UL;
}

/* 34Kc CP0 Count runs at CPU/2. Re-read each call so a PLL change (or the alternate clock) is seen at once. */
ulong notrace get_tbclk(void)
{
	return otto_cpu_hz() / 2;
}

static ulong otto_clk_get_rate(struct clk *clk)
{
	struct otto_clocks c;

	otto_clocks_read(&c);
	switch (clk->id) {
	case OTTO_CLK_CPU:
		return c.cpu_khz * 1000UL;
	case OTTO_CLK_MEM:
		return c.mem_khz * 1000UL;
	case OTTO_CLK_LXB:
		return c.lx_khz * 1000UL;
	case OTTO_CLK_SPI:
		return c.spi_khz * 1000UL;
	}
	return -EINVAL;
}

static const struct clk_ops otto_clk_ops = {
	.get_rate = otto_clk_get_rate,
};

static const struct udevice_id otto_clk_ids[] = {
	{ .compatible = "realtek,rtl9300-clock" },
	{ }
};

U_BOOT_DRIVER(otto_clk) = {
	.name		= "otto_clk",
	.id		= UCLASS_CLK,
	.of_match	= otto_clk_ids,
	.ops		= &otto_clk_ops,
	.flags		= DM_FLAG_PRE_RELOC,	/* console needs LX before relocation */
};
