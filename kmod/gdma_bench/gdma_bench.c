// SPDX-License-Identifier: GPL-2.0
/* Benchmark + verify client for the rtl9300_gdma dmaengine provider (#62, #151).
 * For each size: ITERS transfers through dmaengine (map, prep, submit, wait, unmap) vs a CPU memcpy of the same
 * buffers; every GDMA result is compared byte for byte. Result lines in dmesg; module never stays loaded. */
#include <linux/module.h>
#include <linux/dmaengine.h>
#include <linux/dma-mapping.h>
#include <linux/ktime.h>
#include <linux/math64.h>
#include <linux/slab.h>
#include <linux/string.h>

static uint iters = 200;
module_param(iters, uint, 0444);
static uint chidx;	/* 0 = first channel returned by the core */
module_param(chidx, uint, 0444);

static bool filter(struct dma_chan *c, void *p)
{
	return true;
}

static int __init bench_init(void)
{
	static const uint sizes[] = { 64, 256, 1400, 4096, 8191, 16000, 32000, 65000 };
	struct dma_chan *ch;
	dma_cap_mask_t mask;
	struct device *dev;
	uint s, i, k;

	dma_cap_zero(mask);
	dma_cap_set(DMA_MEMCPY, mask);
	ch = dma_request_channel(mask, filter, NULL);
	if (!ch) {
		pr_err("gdma_bench: no memcpy channel (load rtl9300_gdma first)\n");
		return -ENODEV;
	}
	dev = ch->device->dev;
	for (s = 0; s < ARRAY_SIZE(sizes); s++) {
		uint len = sizes[s], bad = 0, fails = 0;
		u8 *src = kmalloc(len, GFP_KERNEL), *dst = kmalloc(len, GFP_KERNEL), *cpu = kmalloc(len, GFP_KERNEL);
		ktime_t t0, t1;
		s64 dma_ns, cpu_ns, xfer_ns = 0;

		if (!src || !dst || !cpu)
			break;
		for (i = 0; i < len; i++)
			src[i] = (i * 13 + s) & 0xff;
		t0 = ktime_get();
		for (k = 0; k < iters; k++) {
			dma_addr_t sa, da;
			struct dma_async_tx_descriptor *tx;
			dma_cookie_t ck;

			memset(dst, 0xaa, len);
			sa = dma_map_single(dev, src, len, DMA_TO_DEVICE);
			da = dma_map_single(dev, dst, len, DMA_FROM_DEVICE);
			t1 = ktime_get();
			tx = dmaengine_prep_dma_memcpy(ch, da, sa, len, 0);
			if (!tx) {
				fails++;
			} else {
				ck = dmaengine_submit(tx);
				dma_async_issue_pending(ch);
				if (dma_sync_wait(ch, ck) != DMA_COMPLETE)
					fails++;
			}
			xfer_ns += ktime_to_ns(ktime_sub(ktime_get(), t1));
			dma_unmap_single(dev, da, len, DMA_FROM_DEVICE);
			dma_unmap_single(dev, sa, len, DMA_TO_DEVICE);
			if (memcmp(src, dst, len))
				bad++;
		}
		dma_ns = ktime_to_ns(ktime_sub(ktime_get(), t0));
		t0 = ktime_get();
		for (k = 0; k < iters; k++)
			memcpy(cpu, src, len);
		cpu_ns = ktime_to_ns(ktime_sub(ktime_get(), t0));
		pr_info("gdma_bench: len %5u iters %u: gdma %lld ns/xfer (%lld MB/s) cpu memcpy %lld ns (%lld MB/s) bad %u fails %u xfer %lld ns\n",
			len, iters, div_s64(dma_ns, iters), div64_s64((s64)len * iters * 1000, max_t(s64, dma_ns, 1)),
			div_s64(cpu_ns, iters), div64_s64((s64)len * iters * 1000, max_t(s64, cpu_ns, 1)), bad, fails, div_s64(xfer_ns, iters));
		kfree(src);
		kfree(dst);
		kfree(cpu);
	}
	dma_release_channel(ch);
	return -EAGAIN;
}
module_init(bench_init);
MODULE_DESCRIPTION("Benchmark client for the RTL9300 GDMA dmaengine provider");
MODULE_LICENSE("GPL");
