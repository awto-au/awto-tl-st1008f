// SPDX-License-Identifier: GPL-2.0-only
/*
 * Realtek RTL9300 I2C master (SFP cages). Register fields from Linux
 * drivers/i2c/busses/i2c-rtl9300.c. One U-Boot I2C bus per SDA channel (child node);
 * the master does register-addressed transfers of 1-16 data bytes.
 */

#include <dm.h>
#include <i2c.h>
#include <log.h>
#include <time.h>
#include <asm/io.h>
#include <dm/lists.h>
#include <linux/bitops.h>
#include <linux/delay.h>

#define CTRL1		0x0	/* MEM_ADDR 31:8, SDA_OUT_SEL 6:4, SCL_SEL 3, RWOP 2, FAIL 1, TRIG/BUSY 0 */
#define CTRL2		0x4	/* RD_MODE 15, DEV_ADDR 14:8, DATA_WIDTH 7:4, MEM_ADDR_WIDTH 3:2, SCL_FREQ 1:0 */
#define DATA0		0x8	/* 4 words, byte i at word i/4 bits (i%4)*8 */
#define GLB_CTRL	0x384	/* in the switch block: SDA_SEL 7:0 (one enable bit per SDA) */
#define MAX_LEN		16
/* Busy wait: 16 data bytes + addr/reg/restart ~= 20 bytes * 9 bits at 100 kHz = 1.8 ms.
 * 1.25x + 0.5 ms setup = 3 ms; expiry logs the channel, address and elapsed time. */
#define BUSY_TIMEOUT_US	3000

enum { FREQ_100K = 0, FREQ_400K = 1, FREQ_2M5 = 2, FREQ_50K = 3 };

struct rtl9300_i2c_priv {	/* parent: one master */
	void __iomem *mst;
	void __iomem *glb;
	int cur_sda;
};

struct rtl9300_i2c_chan {	/* child: one SDA line = one U-Boot I2C bus */
	u32 sda;
	u32 freq_sel;
};

static void rmw(void __iomem *reg, u32 mask, u32 val)
{
	__raw_writel((__raw_readl(reg) & ~mask) | (val & mask), reg);
}

static void chan_select(struct rtl9300_i2c_priv *p, struct rtl9300_i2c_chan *c)
{
	if (p->cur_sda == c->sda)
		return;
	rmw(p->mst + CTRL2, GENMASK(1, 0), c->freq_sel);
	rmw(p->mst + CTRL1, BIT(3), BIT(3));				/* SCL_SEL */
	rmw(p->glb, BIT(c->sda), BIT(c->sda));				/* SDA_SEL enable */
	rmw(p->mst + CTRL1, GENMASK(6, 4), c->sda << 4);		/* SDA_OUT_SEL */
	p->cur_sda = c->sda;
}

static int xfer_one(struct udevice *bus, u8 addr, u8 reg, u8 *buf, int len, bool wr)
{
	struct rtl9300_i2c_chan *c = dev_get_plat(bus);
	struct rtl9300_i2c_priv *p = dev_get_priv(dev_get_parent(bus));
	u32 w[4] = {};
	ulong t0;
	int i;

	chan_select(p, c);
	rmw(p->mst + CTRL2, GENMASK(15, 2),
	    (addr << 8) | ((len - 1) << 4) | (1 << 2));		/* RD_MODE 0, 8-bit reg addr */
	rmw(p->mst + CTRL1, GENMASK(31, 8) | BIT(2), (reg << 8) | (wr ? BIT(2) : 0));
	if (wr) {
		for (i = 0; i < len; i++)
			w[i / 4] |= buf[i] << ((i % 4) * 8);
		for (i = 0; i < 4; i++)
			__raw_writel(w[i], p->mst + DATA0 + 4 * i);
	}
	rmw(p->mst + CTRL1, BIT(0), BIT(0));				/* TRIG */
	t0 = timer_get_us();
	while (__raw_readl(p->mst + CTRL1) & BIT(0)) {
		if (timer_get_us() - t0 > BUSY_TIMEOUT_US) {
			log_err("rtl9300-i2c: SDA%u addr 0x%02x reg 0x%02x busy > %u us (%lu us)\n",
				c->sda, addr, reg, BUSY_TIMEOUT_US, timer_get_us() - t0);
			return -ETIMEDOUT;
		}
	}
	if (__raw_readl(p->mst + CTRL1) & BIT(1))			/* FAIL = no ACK */
		return -EREMOTEIO;
	if (!wr) {
		for (i = 0; i < 4; i++)
			w[i] = __raw_readl(p->mst + DATA0 + 4 * i);
		for (i = 0; i < len; i++)
			buf[i] = w[i / 4] >> ((i % 4) * 8);
	}
	return 0;
}

/* Supported shapes: [write reg][read N] (EEPROM read) and [write reg, data...] (write). */
static int rtl9300_i2c_xfer(struct udevice *bus, struct i2c_msg *msg, int nmsgs)
{
	u8 reg;
	int off, n, ret;

	if (nmsgs == 2 && !(msg[0].flags & I2C_M_RD) && msg[0].len == 1 &&
	    (msg[1].flags & I2C_M_RD)) {
		reg = msg[0].buf[0];
		for (off = 0; off < msg[1].len; off += n) {
			n = min_t(int, msg[1].len - off, MAX_LEN);
			ret = xfer_one(bus, msg[1].addr, reg + off, msg[1].buf + off, n, false);
			if (ret)
				return ret;
		}
		return 0;
	}
	if (nmsgs == 1 && !(msg[0].flags & I2C_M_RD) && msg[0].len >= 2 &&
	    msg[0].len - 1 <= MAX_LEN)
		return xfer_one(bus, msg[0].addr, msg[0].buf[0], msg[0].buf + 1,
				msg[0].len - 1, true);
	log_debug("rtl9300-i2c: unsupported transfer shape (%d msgs)\n", nmsgs);
	return -EOPNOTSUPP;
}

/* No zero-length transfers in this master: probe = 1-byte read of register 0. */
static int rtl9300_i2c_probe_chip(struct udevice *bus, u32 addr, u32 flags)
{
	u8 b;

	return xfer_one(bus, addr, 0, &b, 1, false);
}

static int rtl9300_i2c_chan_of_to_plat(struct udevice *bus)
{
	struct rtl9300_i2c_chan *c = dev_get_plat(bus);
	u32 hz = dev_read_u32_default(bus, "clock-frequency", 100000);

	c->sda = dev_read_u32_default(bus, "reg", 0);
	c->freq_sel = hz >= 2500000 ? FREQ_2M5 : hz >= 400000 ? FREQ_400K :
		      hz >= 100000 ? FREQ_100K : FREQ_50K;
	return 0;
}

static const struct dm_i2c_ops rtl9300_i2c_ops = {
	.xfer		= rtl9300_i2c_xfer,
	.probe_chip	= rtl9300_i2c_probe_chip,
};

U_BOOT_DRIVER(rtl9300_i2c_chan) = {
	.name		= "rtl9300-i2c-chan",
	.id		= UCLASS_I2C,
	.of_to_plat	= rtl9300_i2c_chan_of_to_plat,
	.plat_auto	= sizeof(struct rtl9300_i2c_chan),
	.ops		= &rtl9300_i2c_ops,
};

static int rtl9300_i2c_bind(struct udevice *dev)
{
	ofnode node;
	int ret;

	dev_for_each_subnode(node, dev) {
		ret = device_bind_driver_to_node(dev, "rtl9300-i2c-chan", ofnode_get_name(node),
						 node, NULL);
		if (ret)
			return ret;
	}
	return 0;
}

static int rtl9300_i2c_probe(struct udevice *dev)
{
	struct rtl9300_i2c_priv *p = dev_get_priv(dev);

	p->mst = dev_remap_addr(dev);
	if (!p->mst)
		return -EINVAL;
	p->glb = (void __iomem *)(((ulong)p->mst & ~0xffffUL) + GLB_CTRL);
	p->cur_sda = -1;
	rmw(p->mst + CTRL2, BIT(15), 0);				/* standard read format */
	return 0;
}

static const struct udevice_id rtl9300_i2c_ids[] = {
	{ .compatible = "realtek,rtl9301-i2c" },
	{ }
};

U_BOOT_DRIVER(rtl9300_i2c) = {
	.name		= "rtl9300-i2c",
	.id		= UCLASS_NOP,
	.of_match	= rtl9300_i2c_ids,
	.bind		= rtl9300_i2c_bind,
	.probe		= rtl9300_i2c_probe,
	.priv_auto	= sizeof(struct rtl9300_i2c_priv),
};
