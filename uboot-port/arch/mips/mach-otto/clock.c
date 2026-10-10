// SPDX-License-Identifier: GPL-2.0+
/*
 * RTL930x clock tree, read-only: rates decoded from the PLL registers on every call.
 * Register map, formulas and sources: docs/CLOCKS.md. Also supplies the CP0 timer rate.
 */

#include <clk-uclass.h>
#include <dm.h>
#include <time.h>
#include <asm/io.h>
#include <linux/bitfield.h>
#include <linux/bitops.h>
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

/* 34Kc CP0 Count runs at CPU/2. Re-read each call so a PLL change is seen at once. */
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
