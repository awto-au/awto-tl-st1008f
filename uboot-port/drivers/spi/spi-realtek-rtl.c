// SPDX-License-Identifier: GPL-2.0-only
/*
 * Realtek RTL83xx/93xx SPI-NOR controller, READ-ONLY U-Boot port.
 * Register model from Linux drivers/spi/spi-realtek-rtl.c (Bert Vermeulen).
 *
 * Read-only by construction: only the opcodes in opcode_ok() reach the flash, and WREN is
 * only ever sent as part of WREAR (extended address register, volatile). Anything else
 * (program, erase, WRSR) is refused; one aimed at 0x0-0xFFFFF (stock LOADER + env) names #81.
 * The controller state is restored on release_bus so
 * the memory-mapped window (0xb4000000) keeps working after `sf` use.
 * CS1 (ball E1, nothing known attached): ID/status/SFDP reads only (`busscan spi 1`, #77).
 */

#include <clk.h>
#include <dm.h>
#include <spi.h>
#include <errno.h>
#include <log.h>
#include <time.h>
#include <asm/io.h>
#include <linux/bitops.h>
#include <linux/kernel.h>
#include <asm/unaligned.h>

#define SFCR		0x00
#define SFCR_RBO	BIT(28)	/* read byte order: first byte in bits 31:24 */
#define SFCR_WBO	BIT(27)
#define SFCSR		0x08
#define SFCSR_CSB0	BIT(31)	/* active low */
#define SFCSR_CSB1	BIT(30)
#define SFCSR_LEN	GENMASK(29, 28)	/* 0 = 1 byte, 3 = 4 bytes (only these are used) */
#define SFCSR_RDY	BIT(27)
#define SFDR		0x0c

/* Opcodes (W25Q256 datasheet table of instructions) */
#define OP_WRDI		0x04
#define OP_RDSR		0x05
#define OP_WREN		0x06
#define OP_RDSR3	0x15
#define OP_READ		0x03
#define OP_RDSR2	0x35
#define OP_RDSFDP	0x5a
#define OP_FAST_READ	0x0b
#define OP_RDID		0x9f
#define OP_WREAR	0xc5
#define OP_RDEAR	0xc8
#define OP_EN4B		0xb7	/* volatile mode bit; stock leaves the flash in 4-byte mode */
#define OP_READ_4B	0x13
#define OP_FAST_READ_4B	0x0c

/* #81 gate: stock LOADER 0x0-0xDFFFF + env 0xE0000-0xFFFFF; our U-Boot never writes the env */
#define STOCK_END	0x100000

/* RDY wait: one 4-byte word = 32 SCK x1.25, SCK from the clock provider (docs/CLOCKS.md),
 * +1 us for timer_get_us() granularity. Set per claim_bus; expiry logs limit and elapsed. */
#define RDY_SCK_X1000	(32 * 1250)

struct rtl_spi_priv {
	void __iomem *base;
	u32 saved_sfcr;
	u32 saved_sfcsr;
	bool wren;	/* WREN swallowed, waiting to see if WREAR follows */
	bool deny;	/* current CS transaction refused: swallow its remaining transfers */
	struct clk sck;
	ulong rdy_us;
};

static u32 rd(struct rtl_spi_priv *p, int reg)
{
	return __raw_readl(p->base + reg);
}

static void wr(struct rtl_spi_priv *p, int reg, u32 val)
{
	__raw_writel(val, p->base + reg);
}

static void cs(struct rtl_spi_priv *p, int csn, bool assert)
{
	u32 b = csn ? SFCSR_CSB1 : SFCSR_CSB0, v = rd(p, SFCSR);

	wr(p, SFCSR, assert ? v & ~b : v | b);
}

static int wait_ready(struct rtl_spi_priv *p)
{
	ulong t0 = timer_get_us();

	while (!(rd(p, SFCSR) & SFCSR_RDY)) {
		if (timer_get_us() - t0 > p->rdy_us) {
			printf("spi-realtek-rtl: RDY timeout, limit %lu us, elapsed %lu us\n",
			       p->rdy_us, timer_get_us() - t0);
			return -ETIMEDOUT;
		}
	}
	return 0;
}

static void set_len(struct rtl_spi_priv *p, int n)
{
	u32 v = rd(p, SFCSR) & ~SFCSR_LEN;

	wr(p, SFCSR, n == 4 ? v | SFCSR_LEN : v);
}

static int send(struct rtl_spi_priv *p, const u8 *buf, int len)
{
	int ret;

	while (len) {
		int n = len >= 4 ? 4 : 1;

		ret = wait_ready(p);
		if (ret)
			return ret;
		set_len(p, n);
		wr(p, SFDR, n == 4 ? get_unaligned_be32(buf) : (u32)buf[0] << 24);
		buf += n;
		len -= n;
	}
	return wait_ready(p);	/* last word must be on the wire before CS drops */
}

static int recv(struct rtl_spi_priv *p, u8 *buf, int len)
{
	int ret;

	while (len) {
		int n = len >= 4 ? 4 : 1;

		ret = wait_ready(p);
		if (ret)
			return ret;
		set_len(p, n);
		if (n == 4)
			put_unaligned_be32(rd(p, SFDR), buf);
		else
			buf[0] = rd(p, SFDR) >> 24;
		buf += n;
		len -= n;
	}
	return 0;
}

static bool opcode_ok(u8 op)
{
	switch (op) {
	case OP_RDID: case OP_RDSR: case OP_RDSR2: case OP_RDSR3: case OP_READ:
	case OP_FAST_READ: case OP_RDSFDP: case OP_RDEAR: case OP_WRDI:
	case OP_EN4B: case OP_READ_4B: case OP_FAST_READ_4B:	/* EX4B 0xe9 stays refused: mmio needs 4B */
		return true;
	default:
		return false;
	}
}

/*
 * Program/erase start from the opcode+address buffer (spi-mem: one BEGIN xfer, 3 or 4 address
 * bytes; EAR only adds high bits). -1 = whole-chip/protection op or odd shape (counts as stock),
 * -2 = not a write.
 */
static long write_addr(u8 op, const u8 *b, int len)
{
	switch (op) {
	case 0x02: case 0x20: case 0x52: case 0xd8:	/* PP, SE 4K, BE 32K, BE 64K */
	case 0x12: case 0x21: case 0x5c: case 0xdc:	/* 4-byte-address forms */
		if (len == 4)
			return b[1] << 16 | b[2] << 8 | b[3];
		if (len == 5)
			return (long)get_unaligned_be32(b + 1);
		return -1;
	case 0xc7: case 0x60:				/* chip erase */
	case 0x01: case 0x31: case 0x11:		/* WRSR1/2/3: block-protect bits */
	case 0x98: case 0x7e: case 0x39: case 0x36:	/* global/individual block unlock/lock */
		return -1;
	default:
		return -2;
	}
}

/* CS1: unknown slave, so no mode-changing opcodes (EN4B, WREN/WREAR, WRDI) either */
static bool opcode_ok_cs1(u8 op)
{
	return op == OP_RDID || op == OP_RDSR || op == OP_RDSR2 || op == OP_RDSR3 || op == OP_RDSFDP;
}

static int rtl_spi_release_bus(struct udevice *dev);

static int rtl_spi_claim_bus(struct udevice *dev)
{
	struct rtl_spi_priv *p = dev_get_priv(dev->parent);
	int ret;

	p->rdy_us = DIV_ROUND_UP(RDY_SCK_X1000, max(clk_get_rate(&p->sck) / 1000, 1UL)) + 1;
	p->saved_sfcr = rd(p, SFCR);
	p->saved_sfcsr = rd(p, SFCSR);
	wr(p, SFCR, p->saved_sfcr | SFCR_RBO | SFCR_WBO);
	wr(p, SFCSR, p->saved_sfcsr | SFCSR_CSB0 | SFCSR_CSB1);
	/* p->wren survives: spi-mem claims/releases per op, WREN and WREAR are separate ops */
	p->deny = false;
	ret = wait_ready(p);
	if (ret)
		rtl_spi_release_bus(dev);
	return ret;
}

static int rtl_spi_release_bus(struct udevice *dev)
{
	struct rtl_spi_priv *p = dev_get_priv(dev->parent);

	/* Back to the stock state so the memory-mapped read window works again */
	wr(p, SFCSR, p->saved_sfcsr);
	wr(p, SFCR, p->saved_sfcr);
	return 0;
}

static int rtl_spi_xfer(struct udevice *dev, unsigned int bitlen, const void *dout,
			void *din, unsigned long flags)
{
	struct rtl_spi_priv *p = dev_get_priv(dev->parent);
	int len = bitlen / 8, ret = 0, csn = spi_chip_select(dev);

	if (bitlen % 8 || (dout && din) || csn < 0 || csn > 1)
		return -EINVAL;

	if (flags & SPI_XFER_BEGIN) {
		u8 op = dout ? *(const u8 *)dout : 0;

		if (!len || !dout)
			return -EINVAL;
		p->deny = false;
		if (csn && !opcode_ok_cs1(op)) {
			printf("refused: CS1 is ID/status reads only (opcode 0x%02x)\n", op);
			p->deny = !(flags & SPI_XFER_END);
			return -EPERM;
		}
		if (op == OP_WREN) {
			p->wren = true;	/* held back; only released for WREAR */
			return 0;
		}
		if (op == OP_WREAR && p->wren) {
			u8 wren = OP_WREN;

			cs(p, csn, true);
			ret = send(p, &wren, 1);
			cs(p, csn, false);
			if (ret)
				return ret;
		} else if (!opcode_ok(op)) {
			long a = write_addr(op, dout, len);

			if (a == -1)
				printf("refused (#81): opcode 0x%02x (chip erase/protection) covers stock LOADER+env 0x0-0x%x\n",
				       op, STOCK_END - 1);
			else if (a >= 0 && a < STOCK_END)
				printf("refused (#81): 0x%lx is in stock LOADER+env 0x0-0x%x (opcode 0x%02x)\n",
				       a, STOCK_END - 1, op);
			printf("refused: no flash writes (opcode 0x%02x)\n", op);
			p->wren = false;
			p->deny = !(flags & SPI_XFER_END);
			return -EPERM;
		}
		p->wren = false;
		cs(p, csn, true);
	} else if (p->deny) {
		p->deny = !(flags & SPI_XFER_END);
		return -EPERM;
	}

	if (dout)
		ret = send(p, dout, len);
	else if (din)
		ret = recv(p, din, len);

	if ((flags & SPI_XFER_END) || ret)
		cs(p, csn, false);
	return ret;
}

/* Clock divider is inherited from stock; nothing to set (`clocks` shows the rate) */
static int rtl_spi_set_speed(struct udevice *bus, uint speed)
{
	return 0;
}

static int rtl_spi_set_mode(struct udevice *bus, uint mode)
{
	return 0;
}

static int rtl_spi_probe(struct udevice *bus)
{
	struct rtl_spi_priv *p = dev_get_priv(bus);
	fdt_addr_t addr = dev_read_addr(bus);

	if (addr == FDT_ADDR_T_NONE)
		return -EINVAL;
	p->base = map_physmem(addr, 0x100, MAP_NOCACHE);
	return clk_get_by_index(bus, 0, &p->sck);	/* SCK rate for the RDY wait */
}

static const struct dm_spi_ops rtl_spi_ops = {
	.claim_bus	= rtl_spi_claim_bus,
	.release_bus	= rtl_spi_release_bus,
	.xfer		= rtl_spi_xfer,
	.set_speed	= rtl_spi_set_speed,
	.set_mode	= rtl_spi_set_mode,
};

static const struct udevice_id rtl_spi_ids[] = {
	{ .compatible = "realtek,rtl8380-spi" },
	{ .compatible = "realtek,rtl8382-spi" },
	{ .compatible = "realtek,rtl8391-spi" },
	{ .compatible = "realtek,rtl8392-spi" },
	{ .compatible = "realtek,rtl8393-spi" },
	{ }
};

U_BOOT_DRIVER(realtek_rtl_spi) = {
	.name		= "realtek_rtl_spi",
	.id		= UCLASS_SPI,
	.of_match	= rtl_spi_ids,
	.ops		= &rtl_spi_ops,
	.priv_auto	= sizeof(struct rtl_spi_priv),
	.probe		= rtl_spi_probe,
};
