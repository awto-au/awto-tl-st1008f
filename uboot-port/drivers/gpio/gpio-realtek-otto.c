// SPDX-License-Identifier: GPL-2.0+
/*
 * Realtek Otto (RTL930x) GPIO, data path only (no IRQ).
 * Register layout from Linux drivers/gpio/gpio-realtek-otto.c (Sander Vanheule):
 * RTL9300 = "ports reversed": one native 32-bit word per register, bit n = line n.
 */

#include <dm.h>
#include <asm/gpio.h>
#include <asm/io.h>
#include <linux/bitops.h>

#define OTTO_GPIO_DIR	0x08	/* 1 = output */
#define OTTO_GPIO_DATA	0x0c

struct otto_gpio_priv {
	void __iomem *base;
};

static u32 otto_rd(struct udevice *dev, unsigned int reg)
{
	struct otto_gpio_priv *p = dev_get_priv(dev);

	return __raw_readl(p->base + reg);
}

static void otto_rmw(struct udevice *dev, unsigned int reg, u32 bit, bool set)
{
	struct otto_gpio_priv *p = dev_get_priv(dev);
	u32 v = __raw_readl(p->base + reg);

	__raw_writel(set ? v | bit : v & ~bit, p->base + reg);
}

static int otto_get_value(struct udevice *dev, unsigned int off)
{
	return !!(otto_rd(dev, OTTO_GPIO_DATA) & BIT(off));
}

static int otto_set_value(struct udevice *dev, unsigned int off, int val)
{
	otto_rmw(dev, OTTO_GPIO_DATA, BIT(off), val);
	return 0;
}

static int otto_direction_input(struct udevice *dev, unsigned int off)
{
	otto_rmw(dev, OTTO_GPIO_DIR, BIT(off), false);
	return 0;
}

static int otto_direction_output(struct udevice *dev, unsigned int off, int val)
{
	otto_set_value(dev, off, val);	/* data first: no glitch when the pin turns output */
	otto_rmw(dev, OTTO_GPIO_DIR, BIT(off), true);
	return 0;
}

static int otto_get_function(struct udevice *dev, unsigned int off)
{
	return otto_rd(dev, OTTO_GPIO_DIR) & BIT(off) ? GPIOF_OUTPUT : GPIOF_INPUT;
}

static const struct dm_gpio_ops otto_gpio_ops = {
	.get_value		= otto_get_value,
	.set_value		= otto_set_value,
	.direction_input	= otto_direction_input,
	.direction_output	= otto_direction_output,
	.get_function		= otto_get_function,
};

static int otto_gpio_probe(struct udevice *dev)
{
	struct gpio_dev_priv *uc = dev_get_uclass_priv(dev);
	struct otto_gpio_priv *p = dev_get_priv(dev);

	p->base = dev_remap_addr(dev);
	if (!p->base)
		return -EINVAL;
	uc->gpio_count = dev_read_u32_default(dev, "ngpios", 24);
	uc->bank_name = dev_read_string(dev, "gpio-bank-name") ?: "gpio";
	return 0;
}

static const struct udevice_id otto_gpio_ids[] = {
	{ .compatible = "realtek,rtl9300-gpio" },
	{ }
};

U_BOOT_DRIVER(gpio_realtek_otto) = {
	.name		= "gpio-realtek-otto",
	.id		= UCLASS_GPIO,
	.of_match	= otto_gpio_ids,
	.ops		= &otto_gpio_ops,
	.probe		= otto_gpio_probe,
	.priv_auto	= sizeof(struct otto_gpio_priv),
};
