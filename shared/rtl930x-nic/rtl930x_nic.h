/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * RTL930x CPU-port NIC core, shared verbatim by U-Boot (rtl930x_eth.c) and Linux (rtl838x_eth.c, 300-18).
 * Edit only shared/rtl930x-nic/ in awto-tl-st1008f; build scripts copy it (docs/UBOOT-MAINLINE.md#ethernet-80).
 * Includer defines first: rtl930x_nic_rd(ctx, off), rtl930x_nic_wr(ctx, off, v), rtl930x_nic_msleep(ms),
 * rtl930x_nic_udelay(us). Offsets are from the switch block (0xbb000000). Sources: OpenWrt rtl838x_eth.c
 * (GPL-2.0, B. Koblitz), Realtek SDK nic_rtl9300.{c,h}.
 */
#ifndef _RTL930X_NIC_H
#define _RTL930X_NIC_H

#define RTL930X_NIC_CPU_PORT		28
#define RTL930X_NIC_RST_GLB_CTRL_0	0x000c	/* bit 0 = chip reset: never set */
#define  RTL930X_NIC_RST_NIC_Q		(BIT(1) | BIT(2))	/* SW_Q_RST, SW_NIC_RST */
#define RTL930X_NIC_L2_PORT_CTRL	(0x3268 + RTL930X_NIC_CPU_PORT * 64)	/* [1:0] TX/RX, [4] CRC */
#define RTL930X_NIC_L2_PORT_MAX_LEN	(0x326c + RTL930X_NIC_CPU_PORT * 64)	/* frames from the CPU */
#define RTL930X_NIC_L2_UNKN_UC_FLD_PMSK	0x9064
#define RTL930X_NIC_L2_CPU_MAX_LEN	0xa3a0	/* [13:0] largest frame the switch hands to the CPU */
#define RTL930X_NIC_QM_RSN2CPUQID	0xa344	/* 5-bit reason/flag -> RX ring fields, 6 per reg */
#define RTL930X_NIC_QM_RSN2CPUQID_N	11
#define RTL930X_NIC_MAC_L2_ADDR		0xc714	/* hi [15:0] = mac[0..1], +4 = mac[2..5] */
#define RTL930X_NIC_MAC_FORCE		(0xca1c + RTL930X_NIC_CPU_PORT * 4)
#define  RTL930X_NIC_CPU_FORCE		0x217	/* link up, 1G: stock + OpenWrt */
#define RTL930X_NIC_RX_RING_SIZE	0x7c60	/* 10 bits per ring, 3 per reg */
#define RTL930X_NIC_RX_RING_CNTR	0x7c8c	/* write n: n more frames may be queued */
#define RTL930X_NIC_DMA_RX_BASE		0xdf00	/* + 4 * ring, 32 rings */
#define RTL930X_NIC_DMA_TX_BASE		0xe000	/* + 4 * ring, 2 rings */
#define RTL930X_NIC_DMA_INTR_MSK	0xe010	/* RX_RUNOUT, RX_DONE, TX_DONE */
#define RTL930X_NIC_DMA_INTR_STS	0xe01c
#define RTL930X_NIC_DMA_IF_CTRL		0xe028
#define  RTL930X_NIC_DMA_TRUNC_EN	BIT(6)
#define  RTL930X_NIC_DMA_RXTX_EN	(BIT(4) | BIT(5))
#define  RTL930X_NIC_DMA_FETCH_BUSY	GENMASK(3, 0)	/* TX_*_FETCH (self-clearing), TX_*_BUSY */
#define RTL930X_NIC_RX_RINGS		32
#define RTL930X_NIC_TX_RINGS		2

/* ring entry = phys(header) | OWN | WRAP */
#define RTL930X_NIC_OWN			BIT(0)
#define RTL930X_NIC_WRAP		BIT(1)
#define RTL930X_NIC_MORE		BIT(15)	/* off_more: frame continues in the next descriptor */

struct rtl930x_nic_hdr {		/* SoC layout, big endian */
	u32 buf;
	u16 rsvd;
	u16 size;
	u16 off_more;
	u16 len;			/* with FCS */
	u16 tag[10];			/* CPU tag */
};
_Static_assert(sizeof(struct rtl930x_nic_hdr) == 32, "RTL930x NIC header layout");

/* TX tag word 1 (SDK nic_9300_cpuTag_t tx): FWD_TYPE [11:8], BP_FLTR [3], BP_STP [2], BP_VLAN_EGR [1] */
#define RTL930X_NIC_TAG1_FWD_PHYSICAL	(1 << 8)
#define RTL930X_NIC_TAG1_BP_FLTR	BIT(3)
#define RTL930X_NIC_TAG1_BP_STP		BIT(2)
#define RTL930X_NIC_TAG1_BP_VLAN_EGR	BIT(1)

/* TX: CPUTAGIF, physical forward to `port` only; prio >= 0 sets AS_QID + QID */
static inline void rtl930x_nic_tx_tag(u16 *tag, unsigned int port, int prio, u16 bypass)
{
	tag[0] = 0x8000;
	tag[1] = RTL930X_NIC_TAG1_FWD_PHYSICAL | bypass;
	tag[2] = prio >= 0 ? (BIT(5) | (prio & 0x1f)) << 8 : 0;
	tag[3] = 0;
	tag[4] = 0;
	tag[5] = 0;			/* DPM ports 32-55 */
	tag[6] = BIT(port) >> 16;	/* DPM ports 0-31 */
	tag[7] = BIT(port) & 0xffff;
	tag[8] = 0;
	tag[9] = 0;
}

struct rtl930x_nic_rx_tag {
	u8 port, queue, reason;
	bool crc_error, l2_offloaded;
};

static inline void rtl930x_nic_rx_tag(const u16 *tag, struct rtl930x_nic_rx_tag *t)
{
	t->port = (tag[0] >> 8) & 0x3f;
	t->queue = (tag[2] >> 11) & 0x1f;
	t->reason = tag[7] & 0x3f;
	t->crc_error = tag[1] & BIT(6);
	t->l2_offloaded = !((t->reason >= 19 && t->reason <= 28) || t->reason == 55);
}

static inline void rtl930x_nic_rmw(void *ctx, u32 off, u32 clr, u32 set)
{
	rtl930x_nic_wr(ctx, off, (rtl930x_nic_rd(ctx, off) & ~clr) | set);
}

/* RX/TX DMA and the CPU port MAC off; no delay */
static inline void rtl930x_nic_stop(void *ctx)
{
	rtl930x_nic_rmw(ctx, RTL930X_NIC_L2_PORT_CTRL, 3, 0);
	rtl930x_nic_rmw(ctx, RTL930X_NIC_DMA_IF_CTRL, RTL930X_NIC_DMA_RXTX_EN | RTL930X_NIC_DMA_FETCH_BUSY, 0);
}

static inline void rtl930x_nic_link_down(void *ctx)
{
	rtl930x_nic_rmw(ctx, RTL930X_NIC_MAC_FORCE, 3, 0);
}

static inline void rtl930x_nic_irq_off(void *ctx)
{
	int i;

	for (i = 0; i < 3; i++) {
		rtl930x_nic_wr(ctx, RTL930X_NIC_DMA_INTR_MSK + i * 4, 0);
		rtl930x_nic_wr(ctx, RTL930X_NIC_DMA_INTR_STS + i * 4, ~0U);
	}
}

/* Self-clear: SDK r9300_swQueRst_set waits a fixed 50 ms; x1.25. Settle: OpenWrt rteth_nic_reset. */
#define RTL930X_NIC_RST_US		62500
#define RTL930X_NIC_SETTLE_MS		100

/* NIC + CPU queue reset, then RX ring counters 0..nrings-1 cleared. Returns us taken or -ETIMEDOUT. */
static inline int rtl930x_nic_reset(void *ctx, int nrings)
{
	int us = 0, ring;

	rtl930x_nic_rmw(ctx, RTL930X_NIC_L2_PORT_CTRL, 3, 0);
	rtl930x_nic_msleep(RTL930X_NIC_SETTLE_MS);
	rtl930x_nic_rmw(ctx, RTL930X_NIC_RST_GLB_CTRL_0, BIT(0), RTL930X_NIC_RST_NIC_Q);
	while (rtl930x_nic_rd(ctx, RTL930X_NIC_RST_GLB_CTRL_0) & RTL930X_NIC_RST_NIC_Q) {
		if (us >= RTL930X_NIC_RST_US)
			return -ETIMEDOUT;
		rtl930x_nic_udelay(10);
		us += 10;
	}
	rtl930x_nic_msleep(RTL930X_NIC_SETTLE_MS);
	for (ring = 0; ring < nrings; ring += 3)	/* write back = clear (3 counters per reg) */
		rtl930x_nic_wr(ctx, RTL930X_NIC_RX_RING_CNTR + ring / 3 * 4,
			       rtl930x_nic_rd(ctx, RTL930X_NIC_RX_RING_CNTR + ring / 3 * 4));
	return us;
}

/* frames the queue manager may queue to `ring` before it calls the ring full (no RX runout) */
static inline void rtl930x_nic_rx_ring_size(void *ctx, int ring, u32 cnt)
{
	int shift = (ring % 3) * 10;

	rtl930x_nic_rmw(ctx, RTL930X_NIC_RX_RING_SIZE + ring / 3 * 4, 0x3ff << shift, cnt << shift);
}

/* `n` frames of `ring` handed back to the NIC */
static inline void rtl930x_nic_rx_release(void *ctx, int ring, u32 n)
{
	rtl930x_nic_wr(ctx, RTL930X_NIC_RX_RING_CNTR + ring / 3 * 4, n << ((ring % 3) * 10));
}

/* every trap reason and flag -> ring (reason % nrings) */
static inline void rtl930x_nic_reason_map(void *ctx, int nrings)
{
	int reason, reg, shift;

	for (reason = 0; reason < RTL930X_NIC_QM_RSN2CPUQID_N * 6; reason++) {
		reg = RTL930X_NIC_QM_RSN2CPUQID + reason / 6 * 4;
		shift = reason % 6 * 5;
		rtl930x_nic_rmw(ctx, reg, 0x1f << shift, (reason % nrings) << shift);
	}
}

static inline void rtl930x_nic_ring_base(void *ctx, bool tx, int ring, u32 phys)
{
	rtl930x_nic_wr(ctx, (tx ? RTL930X_NIC_DMA_TX_BASE : RTL930X_NIC_DMA_RX_BASE) + ring * 4, phys);
}

/* largest frame to and from the CPU (with FCS); RX truncation off */
static inline void rtl930x_nic_max_len(void *ctx, u32 len)
{
	rtl930x_nic_rmw(ctx, RTL930X_NIC_L2_CPU_MAX_LEN, GENMASK(13, 0), len);
	rtl930x_nic_rmw(ctx, RTL930X_NIC_L2_PORT_MAX_LEN, GENMASK(27, 0), len << 14 | len);
	rtl930x_nic_rmw(ctx, RTL930X_NIC_DMA_IF_CTRL, RTL930X_NIC_DMA_TRUNC_EN, 0);
}

/* DMA on, CPU port MAC on + CRC check, unknown unicast floods to the CPU, CPU link forced.
 * Returns DMA_IF_CTRL without the fetch/busy bits, the base for rtl930x_nic_tx_kick_val(). */
static inline u32 rtl930x_nic_enable(void *ctx)
{
	u32 v;

	rtl930x_nic_rmw(ctx, RTL930X_NIC_DMA_IF_CTRL, 0, RTL930X_NIC_DMA_RXTX_EN);
	v = rtl930x_nic_rd(ctx, RTL930X_NIC_DMA_IF_CTRL) & ~RTL930X_NIC_DMA_FETCH_BUSY;
	rtl930x_nic_rmw(ctx, RTL930X_NIC_L2_PORT_CTRL, 0, 3 | BIT(4));
	rtl930x_nic_rmw(ctx, RTL930X_NIC_L2_UNKN_UC_FLD_PMSK, 0, BIT(RTL930X_NIC_CPU_PORT));
	rtl930x_nic_wr(ctx, RTL930X_NIC_MAC_FORCE, RTL930X_NIC_CPU_FORCE);
	return v;
}

/* doorbell: TX_LOW_FETCH (ring 0) / TX_HIGH_FETCH (ring 1); one write, no poll (SDK r9300_nicTxFetch_set) */
static inline u32 rtl930x_nic_tx_kick_val(u32 dma_if_ctrl, int ring)
{
	return dma_if_ctrl | (ring ? BIT(3) : BIT(2));
}

static inline void rtl930x_nic_set_mac(void *ctx, const u8 *m)
{
	rtl930x_nic_wr(ctx, RTL930X_NIC_MAC_L2_ADDR, m[0] << 8 | m[1]);
	rtl930x_nic_wr(ctx, RTL930X_NIC_MAC_L2_ADDR + 4, m[2] << 24 | m[3] << 16 | m[4] << 8 | m[5]);
}

#endif
