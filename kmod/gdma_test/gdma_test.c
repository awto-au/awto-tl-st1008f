// SPDX-License-Identifier: GPL-2.0
/* RTL9303 GDMA memcpy test (#62, #151): LX1 block at phys 0x1800a000, old Otto layout
 * (CTRL 0x00, IM 0x04, IS 0x08, SBP/SBL0 0x20/0x24, DBP/DBL0 0x60/0x64). Polled, one block. */
#include <linux/module.h>
#include <linux/io.h>
#include <linux/dma-mapping.h>
#include <linux/netdevice.h>
#include <linux/ktime.h>
#include <linux/slab.h>

static ulong base = 0x1800a000;
module_param(base, ulong, 0444);
static uint len = 4096;
module_param(len, uint, 0444);
static uint func;	/* CTRL[27:24]: 0 memcpy, 1 checksum, 3 memset */
module_param(func, uint, 0444);
static uint burst = 1;	/* CTRL[7:6] */
module_param(burst, uint, 0444);
static uint iters = 1;
module_param(iters, uint, 0444);

#define CTRL	0x00
#define IM	0x04
#define IS	0x08
#define ICVL	0x0c
#define SBP0	0x20
#define SBL0	0x24
#define DBP0	0x60
#define DBL0	0x64
#define EN	BIT(31)
#define POLL	BIT(30)
#define LDB	BIT(31)
#define COMP	BIT(31)

static int __init gdma_test_init(void)
{
	struct net_device *nd = dev_get_by_name(&init_net, "eth0");
	void __iomem *r;
	u8 *src, *dst;
	dma_addr_t s, d;
	ktime_t t0;
	u32 is = 0, v[5] = { 0 };
	uint i, bad = 0;
	s64 ns = 0;
	int it;

	if (!nd || !nd->dev.parent)
		return -ENODEV;
	r = ioremap(base, 0x40);
	src = kmalloc(len, GFP_KERNEL);
	dst = kmalloc(len, GFP_KERNEL);
	if (!r || !src || !dst)
		return -ENOMEM;
	for (i = 0; i < len; i++)
		src[i] = (i * 7 + 3) & 0xff;

	for (it = 0; it < iters; it++) {
		memset(dst, 0xaa, len);
		s = dma_map_single(nd->dev.parent, src, len, DMA_TO_DEVICE);
		d = dma_map_single(nd->dev.parent, dst, len, DMA_FROM_DEVICE);
		writel(0, r + CTRL);
		writel(EN, r + CTRL);
		writel(0, r + IM);
		writel(0xffffffff, r + IS);
		writel(0, r + ICVL);
		writel(s, r + SBP0);
		writel(len | LDB, r + SBL0);
		writel(d, r + DBP0);
		writel(len | LDB, r + DBL0);
		wmb();
		t0 = ktime_get();
		writel(EN | POLL | (func << 24) | (burst << 6), r + CTRL);
		/* 4 KiB at >= 40 MB/s is 100 us; 2 ms = 20x, names a stuck engine */
		do {
			is = readl(r + IS);
		} while (!(is & COMP) && ktime_us_delta(ktime_get(), t0) < 2000);
		ns = ktime_to_ns(ktime_sub(ktime_get(), t0));
		v[0] = readl(r + ICVL);
		v[1] = readl(r + 0x10);
		v[2] = readl(r + 0x14);
		v[3] = readl(r + 0x18);
		v[4] = readl(r + 0x1c);
		if (!(is & COMP))
			pr_err("gdma_test: timeout IS=%08x after %lld ns\n", is, ns);
		writel(0, r + CTRL);
		dma_unmap_single(nd->dev.parent, d, len, DMA_FROM_DEVICE);
		dma_unmap_single(nd->dev.parent, s, len, DMA_TO_DEVICE);
	}
	for (i = 0; i < len; i++)
		if (dst[i] != src[i])
			bad++;
	if (func == 1) {
		u32 sw = 0, swle = 0;

		for (i = 0; i + 1 < len; i += 2) {
			sw += (src[i] << 8) | src[i + 1];
			swle += (src[i + 1] << 8) | src[i];
		}
		pr_info("gdma_test: csum sw be16-sum %08x le16-sum %08x; hw ICVL %08x ICVR %08x +0x14 %08x +0x18 %08x +0x1c %08x\n",
			sw, swle, v[0], v[1], v[2], v[3], v[4]);
	}
	pr_info("gdma_test: base %lx func %u len %u burst %u iters %u: IS=%08x ICVL=%08x last %lld ns, %u/%u bytes differ, dst[0..3]=%02x%02x%02x%02x\n",
		base, func, len, burst, iters, is, v[0], ns, bad, len,
		dst[0], dst[1], dst[2], dst[3]);
	iounmap(r);
	kfree(src);
	kfree(dst);
	dev_put(nd);
	return -EAGAIN;	/* result in dmesg; never stays loaded */
}
module_init(gdma_test_init);
MODULE_LICENSE("GPL");
