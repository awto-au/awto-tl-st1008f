// SPDX-License-Identifier: GPL-2.0
/* RTL9303 GDMA as a dmaengine memcpy provider (#62, #151).
 * Blocks (phys): LX1 0x1800a000, LX2 0x18018000; old Otto layout measured on sw2 (docs/HIDDEN-FEATURES.md):
 * CTRL 0x00 (EN 31, POLL 30, func 27:24, burst 7:6), IS 0x08 (bit 31 done), SBP/SBL i at 0x20+8i / 0x24+8i,
 * DBP/DBL i at 0x60+8i / 0x64+8i, length 12:0, bit 31 = last block. 8 blocks per transfer, <= 8191 B each.
 * One transfer at a time per block, polled by a kthread (no IRQ yet).
 */
#include <linux/module.h>
#include <linux/io.h>
#include <linux/kthread.h>
#include <linux/dmaengine.h>
#include <linux/dma-mapping.h>
#include <linux/platform_device.h>
#include <linux/slab.h>
#include "dmaengine.h"

#define CTRL		0x00
#define IM		0x04
#define IS		0x08
#define ICVL		0x0c
#define SBP(i)		(0x20 + 8 * (i))
#define SBL(i)		(0x24 + 8 * (i))
#define DBP(i)		(0x60 + 8 * (i))
#define DBL(i)		(0x64 + 8 * (i))
#define EN		BIT(31)
#define POLL		BIT(30)
#define LDB		BIT(31)
#define COMP		BIT(31)
#define IS_ERR_MASK	(BIT(26) | BIT(25) | BIT(24) | BIT(21) | BIT(20))
#define BLK_MAX		8191
#define NBLK		8

static uint burst = 3;	/* CTRL[7:6]; 4 KiB: 0 47 us, 1 28 us, 2 18 us, 3 14 us (sw2, picks) */
module_param(burst, uint, 0444);
static ulong bases[2] = { 0x1800a000, 0x18018000 };

struct gdma_desc {
	struct dma_async_tx_descriptor tx;
	struct list_head node;
	dma_addr_t src, dst;
	size_t len;
};

struct gdma_chan {
	struct dma_chan chan;
	void __iomem *base;
	spinlock_t lock;
	struct list_head pending;
	wait_queue_head_t wq;
	struct task_struct *th;
	u64 xfers, errs;
};

struct gdma_dev {
	struct dma_device dd;
	struct gdma_chan ch[2];
};

static struct platform_device *pdev;
static struct gdma_dev *gd;

static dma_cookie_t gdma_submit(struct dma_async_tx_descriptor *tx)
{
	struct gdma_chan *c = container_of(tx->chan, struct gdma_chan, chan);
	struct gdma_desc *d = container_of(tx, struct gdma_desc, tx);
	dma_cookie_t cookie;
	unsigned long fl;

	spin_lock_irqsave(&c->lock, fl);
	cookie = dma_cookie_assign(tx);
	list_add_tail(&d->node, &c->pending);
	spin_unlock_irqrestore(&c->lock, fl);
	return cookie;
}

static struct dma_async_tx_descriptor *gdma_prep_memcpy(struct dma_chan *ch, dma_addr_t dst, dma_addr_t src,
							 size_t len, unsigned long flags)
{
	struct gdma_desc *d;

	if (!len || len > (size_t)BLK_MAX * NBLK)
		return NULL;
	d = kzalloc(sizeof(*d), GFP_NOWAIT);
	if (!d)
		return NULL;
	dma_async_tx_descriptor_init(&d->tx, ch);
	d->tx.tx_submit = gdma_submit;
	d->tx.flags = flags;
	d->src = src;
	d->dst = dst;
	d->len = len;
	return &d->tx;
}

static void gdma_issue_pending(struct dma_chan *ch)
{
	struct gdma_chan *c = container_of(ch, struct gdma_chan, chan);

	wake_up(&c->wq);
}

static enum dma_status gdma_tx_status(struct dma_chan *ch, dma_cookie_t cookie, struct dma_tx_state *st)
{
	return dma_cookie_status(ch, cookie, st);
}

static int gdma_alloc(struct dma_chan *ch) { return 1; }
static void gdma_free(struct dma_chan *ch) { }
static int gdma_terminate(struct dma_chan *ch) { return 0; }

/* returns 0 ok, -ETIMEDOUT, -EIO */
static int gdma_run(struct gdma_chan *c, struct gdma_desc *d)
{
	void __iomem *r = c->base;
	size_t off = 0;
	int i, n = DIV_ROUND_UP(d->len, BLK_MAX);
	u32 is;
	ktime_t t0;
	/* worst measured 11.5 ns/B (burst 0, 87 MB/s) x1.25 = 15 ns/B + 100 us setup margin */
	s64 limit_us = 100 + d->len * 15 / 1000;

	writel(0, r + CTRL);
	writel(EN, r + CTRL);
	writel(0, r + IM);
	writel(0xffffffff, r + IS);
	for (i = 0; i < n; i++) {
		size_t l = min_t(size_t, d->len - off, BLK_MAX);

		writel(d->src + off, r + SBP(i));
		writel(l | (i == n - 1 ? LDB : 0), r + SBL(i));
		writel(d->dst + off, r + DBP(i));
		writel(l | (i == n - 1 ? LDB : 0), r + DBL(i));
		off += l;
	}
	wmb();
	t0 = ktime_get();
	writel(EN | POLL | ((burst & 3) << 6), r + CTRL);
	do {
		is = readl(r + IS);
	} while (!(is & COMP) && ktime_us_delta(ktime_get(), t0) < limit_us);
	writel(0, r + CTRL);
	if (!(is & COMP)) {
		pr_err("rtl9300_gdma: timeout len %zu after %lld us, IS=%08x\n", d->len, limit_us, is);
		return -ETIMEDOUT;
	}
	return (is & IS_ERR_MASK) ? -EIO : 0;
}

static int gdma_thread(void *arg)
{
	struct gdma_chan *c = arg;

	while (!kthread_should_stop()) {
		struct gdma_desc *d = NULL;
		unsigned long fl;
		int rc;

		wait_event_interruptible(c->wq, kthread_should_stop() || !list_empty_careful(&c->pending));
		spin_lock_irqsave(&c->lock, fl);
		if (!list_empty(&c->pending)) {
			d = list_first_entry(&c->pending, struct gdma_desc, node);
			list_del(&d->node);
		}
		spin_unlock_irqrestore(&c->lock, fl);
		if (!d)
			continue;
		rc = gdma_run(c, d);
		c->xfers++;
		if (rc)
			c->errs++;
		spin_lock_irqsave(&c->lock, fl);
		dma_cookie_complete(&d->tx);
		spin_unlock_irqrestore(&c->lock, fl);
		dmaengine_desc_get_callback_invoke(&d->tx, NULL);
		kfree(d);
	}
	return 0;
}

static int __init gdma_init(void)
{
	int i, rc;

	pdev = platform_device_register_simple("rtl9300-gdma", -1, NULL, 0);
	if (IS_ERR(pdev))
		return PTR_ERR(pdev);
	dma_coerce_mask_and_coherent(&pdev->dev, DMA_BIT_MASK(32));
	gd = kzalloc(sizeof(*gd), GFP_KERNEL);
	if (!gd)
		return -ENOMEM;
	gd->dd.dev = &pdev->dev;
	dma_cap_set(DMA_MEMCPY, gd->dd.cap_mask);
	gd->dd.device_alloc_chan_resources = gdma_alloc;
	gd->dd.device_free_chan_resources = gdma_free;
	gd->dd.device_prep_dma_memcpy = gdma_prep_memcpy;
	gd->dd.device_issue_pending = gdma_issue_pending;
	gd->dd.device_tx_status = gdma_tx_status;
	gd->dd.device_terminate_all = gdma_terminate;
	gd->dd.src_addr_widths = BIT(DMA_SLAVE_BUSWIDTH_1_BYTE);
	gd->dd.dst_addr_widths = BIT(DMA_SLAVE_BUSWIDTH_1_BYTE);
	gd->dd.directions = BIT(DMA_MEM_TO_MEM);
	gd->dd.residue_granularity = DMA_RESIDUE_GRANULARITY_DESCRIPTOR;
	gd->dd.copy_align = DMAENGINE_ALIGN_4_BYTES;
	INIT_LIST_HEAD(&gd->dd.channels);
	for (i = 0; i < 2; i++) {
		struct gdma_chan *c = &gd->ch[i];

		c->base = ioremap(bases[i], 0x100);
		spin_lock_init(&c->lock);
		INIT_LIST_HEAD(&c->pending);
		init_waitqueue_head(&c->wq);
		c->chan.device = &gd->dd;
		dma_cookie_init(&c->chan);
		list_add_tail(&c->chan.device_node, &gd->dd.channels);
		c->th = kthread_run(gdma_thread, c, "gdma%d", i);
	}
	rc = dma_async_device_register(&gd->dd);
	pr_info("rtl9300_gdma: registered 2 memcpy channels (LX1, LX2), burst %u, rc %d\n", burst, rc);
	return rc;
}

static void __exit gdma_exit(void)
{
	int i;

	dma_async_device_unregister(&gd->dd);
	for (i = 0; i < 2; i++) {
		kthread_stop(gd->ch[i].th);
		pr_info("rtl9300_gdma: ch%d %llu transfers, %llu errors\n", i, gd->ch[i].xfers, gd->ch[i].errs);
		iounmap(gd->ch[i].base);
	}
	kfree(gd);
	platform_device_unregister(pdev);
}
module_init(gdma_init);
module_exit(gdma_exit);
MODULE_LICENSE("GPL");
