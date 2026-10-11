// SPDX-License-Identifier: GPL-2.0+
/*
 * RTL930x CPU-port NIC (switch port 28), polled DM_ETH driver (#80).
 * Register use and descriptor/CPU-tag layout: OpenWrt rtl838x_eth.c (GPL-2.0, B. Koblitz) RTL930x
 * paths + our 300-12; tag bits: Realtek SDK nic_rtl9300.h. Doc: docs/UBOOT-MAINLINE.md#ethernet.
 * Loop guard: TX = physical forward to the one `ethport` cage; RX from other ports is dropped.
 */

#include <command.h>
#include <cpu_func.h>
#include <dm.h>
#include <env.h>
#include <i2c.h>
#include <malloc.h>
#include <net.h>
#include <time.h>
#include <asm/io.h>
#include <linux/delay.h>
#include "rtk.h"

#define RST_GLB_CTRL_0		0x000c		/* bit 0 = chip reset: never set here */
#define  RST_NIC_Q		(BIT(1) | BIT(2))	/* SW_Q_RST, SW_NIC_RST (OpenWrt 93xx mask 0x6) */
#define L2_PORT_CTRL_CPU	(0x3268 + CPU_PORT * 64)	/* [1:0] TX/RX enable, [4] CRC check */
#define L2_UNKN_UC_FLD_PMSK	0x9064
#define L2_CPU_MAX_LEN		0xa3a0		/* [13:0] largest frame the switch hands to the CPU */
#define QM_RSN2CPUQID(i)	(0xa344 + (i) * 4)	/* 6 x 5-bit reason -> RX ring fields per reg */
#define QM_RSN2CPUQID_N		11
#define MAC_L2_ADDR		0xc714		/* hi [15:0] = mac[0..1], +4 = mac[2..5] */
#define MAC_FORCE_CPU		(0xca1c + CPU_PORT * 4)
#define  CPU_FORCE		0x217		/* link up, 1G: stock + OpenWrt value (DATASHEET-AUDIT.md) */
#define MAC_LINK_STS		0xcb10
#define RX_RING_SIZE_REG	0x7c60		/* [9:0] ring 0: frames before the queue manager calls it full */
#define RX_RING_CNTR		0x7c8c		/* write n: n more frames may be queued to ring 0 */
#define DMA_RX_BASE(r)		(0xdf00 + (r) * 4)
#define DMA_TX_BASE(r)		(0xe000 + (r) * 4)
#define DMA_INTR_MSK(i)		(0xe010 + (i) * 4)	/* RX_RUNOUT, RX_DONE, TX_DONE */
#define DMA_INTR_STS(i)		(0xe01c + (i) * 4)
#define DMA_IF_CTRL		0xe028
#define  DMA_RX_EN		BIT(4)
#define  DMA_TX_EN		BIT(5)
#define  DMA_TX_LOW_FETCH	BIT(2)		/* doorbell TX ring 0, self-clearing */
#define  DMA_FETCH_BUSY		GENMASK(3, 0)
#define NRX_RINGS		32
#define NTX_RINGS		2

#define OWN_HW			BIT(0)		/* ring entry = phys(header) | OWN | WRAP */
#define WRAP			BIT(1)
#define MORE			BIT(15)		/* header offset word: frame continues in the next */
#define RX_N			32		/* TFTP is lock-step; 32 covers a TCP window burst */
#define TX_N			4
#define BUF_SIZE		1664		/* 52 cache lines >= CPU max len */
#define CPU_MAX_LEN		1600		/* 1522 + slack; longer frames dropped by the switch */
#define FCS_LEN			4
#define TX_MIN			60		/* frame without FCS */
/* TX tag word 1: FWD_TYPE physical [11:8], BP_FLTR [3], BP_STP [2], BP_VLAN_EGR [1] */
#define TAG1_TX			(1 << 8 | BIT(3) | BIT(2) | BIT(1))

/* NIC reset self-clear: SDK r9300_swQueRst_set waits a fixed 50 ms; x1.25. Expiry: start fails. */
#define NIC_RST_US		62500
/* OpenWrt rteth_nic_reset settle before and after the reset (no measurement exists); once per boot */
#define NIC_SETTLE_MS		100
/* A TX slot frees when the NIC has fetched it: Linux 17-23 us per packet incl. DMA
 * (DATASHEET-AUDIT.md); a full 4-deep ring = 4 x 23 us, x1.25 = 115 us. Expiry: frame dropped, logged. */
#define TX_SLOT_US		115

struct nic_hdr {			/* SoC layout, big endian, 32 bytes */
	u32 buf;
	u16 rsvd;
	u16 size;
	u16 off_more;
	u16 len;
	u16 tag[10];
};
_Static_assert(sizeof(struct nic_hdr) == 32, "NIC header layout");

struct nic_desc {			/* accessed through KSEG1 only */
	u32 rx_ring[RX_N];
	u32 tx_ring[TX_N];
	u32 null_ring[4];		/* rings we do not use: one CPU-owned entry */
	struct nic_hdr rx[RX_N];
	struct nic_hdr tx[TX_N];
	struct nic_hdr null;
};

struct rtl930x_eth_priv {
	volatile struct nic_desc *d;	/* uncached alias */
	u8 *rx_buf, *tx_buf;		/* cached */
	unsigned int rx_idx, tx_idx, port, cage;
	bool hw_ready, rx_any;
	ulong rx_other, rx_bad, tx_timeout;
	u16 last_tag0, last_tag7;	/* RX tag of the last frame: rx port [12:8], reason [5:0] */
};

static void nic_sync(void)
{
	__asm__ __volatile__("sync" ::: "memory");
}

static u32 phys(volatile const void *p)
{
	return virt_to_phys(p);
}

static int eth_cage(void)
{
	ulong c = env_get_ulong("ethport", 10, 1);

	return c >= 1 && c <= NCAGES ? c : -1;
}

/* laser of `cage` on, every other off (`rtk laser N`): one lit cage (CLAUDE.md cage loop) */
static int laser_only(int cage)
{
	struct udevice *dev = rtk_chip(EXP_BUS, EXP_ADDR);
	u8 out = 0xff & ~BIT(cage - 1), cfg = 0;

	if (!dev || dm_i2c_write(dev, EXP_OUT, &out, 1) || dm_i2c_write(dev, EXP_CFG, &cfg, 1))
		return -EIO;
	return 0;
}

static void rx_arm(struct rtl930x_eth_priv *p, unsigned int i)
{
	volatile struct nic_hdr *h = &p->d->rx[i];
	u8 *b = p->rx_buf + i * BUF_SIZE;

	invalidate_dcache_range((ulong)b, (ulong)b + BUF_SIZE);	/* drop lines the stack dirtied */
	h->buf = phys(b);
	h->size = BUF_SIZE;
	h->off_more = 0;
	h->len = 0;
	nic_sync();
	p->d->rx_ring[i] = phys(h) | OWN_HW | (i == RX_N - 1 ? WRAP : 0);
}

/* Stop DMA and the CPU port MAC: no frame lands in memory while U-Boot is not polling */
static void nic_quiesce(void)
{
	int i;

	sw_rmw(L2_PORT_CTRL_CPU, 3, 0);
	sw_rmw(DMA_IF_CTRL, DMA_RX_EN | DMA_TX_EN | DMA_FETCH_BUSY, 0);
	for (i = 0; i < 3; i++) {
		sw_w(DMA_INTR_MSK(i), 0);
		sw_w(DMA_INTR_STS(i), ~0U);
	}
}

/* Once per boot: reset NIC + CPU queues (stock left its own rings armed), then our rings */
static int nic_setup(struct rtl930x_eth_priv *p)
{
	volatile struct nic_desc *d = p->d;
	ulong t0;
	u32 v;
	int i;

	nic_quiesce();
	mdelay(NIC_SETTLE_MS);
	sw_w(RST_GLB_CTRL_0, (sw_r(RST_GLB_CTRL_0) & ~BIT(0)) | RST_NIC_Q);
	t0 = timer_get_us();
	while (sw_r(RST_GLB_CTRL_0) & RST_NIC_Q) {
		if (timer_get_us() - t0 > NIC_RST_US) {
			printf("rtl930x-eth: NIC reset not done after %d us (0x%08x)\n", NIC_RST_US,
			       sw_r(RST_GLB_CTRL_0));
			return -ETIMEDOUT;
		}
	}
	printf("rtl930x-eth: NIC reset %lu us\n", timer_get_us() - t0);
	mdelay(NIC_SETTLE_MS);
	v = sw_r(RX_RING_CNTR);			/* OpenWrt: write back = clear ring counters */
	sw_w(RX_RING_CNTR, v);
	sw_rmw(RX_RING_SIZE_REG, 0x3ff, RX_N);	/* 1 frame = 1 descriptor (CPU_MAX_LEN < BUF_SIZE) */
	for (i = 0; i < QM_RSN2CPUQID_N; i++)	/* every trap reason -> ring 0 */
		sw_rmw(QM_RSN2CPUQID(i), GENMASK(29, 0), 0);

	d->null.buf = 0;
	d->null.size = 0;
	d->null_ring[0] = phys(&d->null) | WRAP;	/* CPU-owned: the NIC never writes */
	for (i = 0; i < RX_N; i++)
		rx_arm(p, i);
	for (i = 0; i < TX_N; i++)
		d->tx_ring[i] = phys(&d->tx[i]) | (i == TX_N - 1 ? WRAP : 0);
	nic_sync();
	sw_w(DMA_RX_BASE(0), phys(d->rx_ring));
	for (i = 1; i < NRX_RINGS; i++)
		sw_w(DMA_RX_BASE(i), phys(d->null_ring));
	sw_w(DMA_TX_BASE(0), phys(d->tx_ring));
	sw_w(DMA_TX_BASE(1), phys(d->null_ring));
	p->rx_idx = 0;
	p->tx_idx = 0;
	sw_rmw(L2_CPU_MAX_LEN, GENMASK(13, 0), CPU_MAX_LEN);
	sw_rmw(L2_UNKN_UC_FLD_PMSK, 0, BIT(CPU_PORT));	/* unknown unicast reaches the CPU */
	sw_w(MAC_FORCE_CPU, CPU_FORCE);
	return 0;
}

static int rtl930x_eth_start(struct udevice *dev)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);
	char *on[] = { "rtk", "network", "on", NULL };
	int cage = eth_cage(), ret;

	if (cage < 0) {
		printf("rtl930x-eth: env ethport must be a cage 1-%d\n", NCAGES);
		return -EINVAL;
	}
	if (!p->hw_ready) {
		/* stock `rtk network on` forces the CPU port link (MAC_FORCE 0x217); else run ours */
		if (!rtk_net_is_on() && (sw_r(MAC_FORCE_CPU) & 3) != 3) {
			printf("rtl930x-eth: switch not set up, running `rtk network on`\n");
			rtk_network(3, on);
		}
		ret = nic_setup(p);
		if (ret)
			return ret;
		p->hw_ready = true;
	}
	rtk_iso_guard();	/* every start: stock network on does not isolate the cages */
	p->rx_any = env_get_yesno("ethrxany") == 1;	/* debug: accept frames from every cage */
	if (cage != p->cage) {
		if (laser_only(cage))
			printf("rtl930x-eth: laser expander not responding (cage %d laser unchanged)\n", cage);
		p->cage = cage;
		p->port = rtk_cage_port[cage - 1];
		sw_r(MAC_LINK_STS);		/* latched low: second read = now */
		printf("rtl930x-eth: cage %d (port %u) only, link %s\n", cage, p->port,
		       sw_r(MAC_LINK_STS) & BIT(p->port) ? "up" : "down");
	}
	sw_rmw(DMA_IF_CTRL, DMA_FETCH_BUSY, DMA_RX_EN | DMA_TX_EN);
	sw_rmw(L2_PORT_CTRL_CPU, 0, 3 | BIT(4));
	return 0;
}

static int rtl930x_eth_send(struct udevice *dev, void *packet, int length)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);
	unsigned int i = p->tx_idx;
	volatile struct nic_hdr *h = &p->d->tx[i];
	u8 *b = p->tx_buf + i * BUF_SIZE;
	int len = max(length, TX_MIN) + FCS_LEN;
	ulong t0 = timer_get_us();

	if (length > BUF_SIZE - FCS_LEN)
		return -EMSGSIZE;
	while (p->d->tx_ring[i] & OWN_HW) {
		if (timer_get_us() - t0 > TX_SLOT_US) {
			p->tx_timeout++;
			printf("rtl930x-eth: TX slot %u still owned by the NIC after %d us\n", i, TX_SLOT_US);
			return -ETIMEDOUT;
		}
	}
	memcpy(b, packet, length);
	memset(b + length, 0, len - length);	/* pad + empty FCS field */
	flush_dcache_range((ulong)b, (ulong)b + ALIGN(len, ARCH_DMA_MINALIGN));
	h->buf = phys(b);
	h->size = BUF_SIZE;
	h->off_more = 0;
	h->len = len;
	h->tag[0] = 0x8000;			/* CPUTAGIF */
	h->tag[1] = TAG1_TX;
	h->tag[2] = 0;
	h->tag[3] = 0;
	h->tag[4] = 0;
	h->tag[5] = 0;				/* DPM ports 32-55 */
	h->tag[6] = BIT(p->port) >> 16;		/* DPM ports 0-31: the mgmt port only */
	h->tag[7] = BIT(p->port) & 0xffff;
	h->tag[8] = 0;
	h->tag[9] = 0;
	nic_sync();
	p->d->tx_ring[i] = phys(h) | OWN_HW | (i == TX_N - 1 ? WRAP : 0);
	nic_sync();
	sw_w(DMA_IF_CTRL, (sw_r(DMA_IF_CTRL) & ~DMA_FETCH_BUSY) | DMA_TX_LOW_FETCH);
	p->tx_idx = (i + 1) % TX_N;
	return 0;
}

/* Give the slot back and let the queue manager count it free again */
static void rx_release(struct rtl930x_eth_priv *p)
{
	rx_arm(p, p->rx_idx);
	nic_sync();
	sw_w(RX_RING_CNTR, 1);
	p->rx_idx = (p->rx_idx + 1) % RX_N;
}

static int rtl930x_eth_recv(struct udevice *dev, int flags, uchar **packetp)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);
	volatile struct nic_hdr *h;
	unsigned int n, len;
	u8 *b;

	for (n = 0; n < RX_N; n++) {
		if (p->d->rx_ring[p->rx_idx] & OWN_HW)
			return -EAGAIN;
		h = &p->d->rx[p->rx_idx];
		len = h->len;
		p->last_tag0 = h->tag[0];
		p->last_tag7 = h->tag[7];
		if (h->off_more & MORE || len < ETH_HLEN + FCS_LEN || len > BUF_SIZE) {
			p->rx_bad++;
		} else if (!p->rx_any && ((h->tag[0] >> 8) & 0x1f) != p->port) {
			p->rx_other++;		/* isolated cages still reach the CPU: not ours */
		} else {
			b = p->rx_buf + p->rx_idx * BUF_SIZE;
			invalidate_dcache_range((ulong)b, (ulong)b + BUF_SIZE);
			*packetp = b;
			return len - FCS_LEN;
		}
		rx_release(p);
	}
	return -EAGAIN;
}

static int rtl930x_eth_free_pkt(struct udevice *dev, uchar *packet, int length)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);

	if (packet == p->rx_buf + p->rx_idx * BUF_SIZE)
		rx_release(p);
	return 0;
}

/* Let queued TX frames be fetched first: netconsole sends one frame and halts at once */
static void rtl930x_eth_stop(struct udevice *dev)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);
	ulong t0 = timer_get_us();
	unsigned int i;

	if (!p->hw_ready)
		return;
	for (i = 0; i < TX_N; i++)
		while (p->d->tx_ring[i] & OWN_HW && timer_get_us() - t0 <= TX_SLOT_US)
			;
	for (i = 0; i < TX_N; i++)
		if (p->d->tx_ring[i] & OWN_HW) {
			p->tx_timeout++;
			printf("rtl930x-eth: stop: TX slot %u not fetched after %d us\n", i, TX_SLOT_US);
		}
	nic_quiesce();
}

static int rtl930x_eth_write_hwaddr(struct udevice *dev)
{
	u8 *m = ((struct eth_pdata *)dev_get_plat(dev))->enetaddr;

	sw_w(MAC_L2_ADDR, m[0] << 8 | m[1]);
	sw_w(MAC_L2_ADDR + 4, m[2] << 24 | m[3] << 16 | m[4] << 8 | m[5]);
	return 0;
}

/* MAC = stock env `ethaddr` (flash u-boot-env), the one Linux nvmem uses */
static int rtl930x_eth_read_rom_hwaddr(struct udevice *dev)
{
	struct eth_pdata *pd = dev_get_plat(dev);
	char s[24];

	if (!st1008f_stock_env("ethaddr", s, sizeof(s)))
		return -ENOENT;
	string_to_enetaddr(s, pd->enetaddr);
	return is_valid_ethaddr(pd->enetaddr) ? 0 : -EINVAL;
}

static int rtl930x_eth_probe(struct udevice *dev)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);
	void *d = memalign(ARCH_DMA_MINALIGN, ALIGN(sizeof(struct nic_desc), ARCH_DMA_MINALIGN));

	p->rx_buf = memalign(ARCH_DMA_MINALIGN, RX_N * BUF_SIZE);
	p->tx_buf = memalign(ARCH_DMA_MINALIGN, TX_N * BUF_SIZE);
	if (!d || !p->rx_buf || !p->tx_buf)
		return -ENOMEM;
	memset(d, 0, sizeof(struct nic_desc));
	flush_dcache_range((ulong)d, (ulong)d + ALIGN(sizeof(struct nic_desc), ARCH_DMA_MINALIGN));
	p->d = (volatile struct nic_desc *)CKSEG1ADDR((ulong)d);
	nic_quiesce();	/* stock's NIC may still DMA into its own rings */
	return 0;
}

static const struct eth_ops rtl930x_eth_ops = {
	.start			= rtl930x_eth_start,
	.send			= rtl930x_eth_send,
	.recv			= rtl930x_eth_recv,
	.free_pkt		= rtl930x_eth_free_pkt,
	.stop			= rtl930x_eth_stop,
	.write_hwaddr		= rtl930x_eth_write_hwaddr,
	.read_rom_hwaddr	= rtl930x_eth_read_rom_hwaddr,
};

static const struct udevice_id rtl930x_eth_ids[] = {
	{ .compatible = "realtek,rtl9301-eth" },
	{ }
};

U_BOOT_DRIVER(rtl930x_eth) = {
	.name		= "rtl930x_eth",
	.id		= UCLASS_ETH,
	.of_match	= rtl930x_eth_ids,
	.probe		= rtl930x_eth_probe,
	.ops		= &rtl930x_eth_ops,
	.priv_auto	= sizeof(struct rtl930x_eth_priv),
	.plat_auto	= sizeof(struct eth_pdata),
};

static int do_ethstat(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	struct udevice *dev;
	struct rtl930x_eth_priv *p;

	if (uclass_first_device_err(UCLASS_ETH, &dev))
		return CMD_RET_FAILURE;
	p = dev_get_priv(dev);
	printf("cage %u port %u, rx idx %u, tx idx %u, rx other-port %lu, rx bad %lu, tx timeout %lu\n",
	       p->cage, p->port, p->rx_idx, p->tx_idx, p->rx_other, p->rx_bad, p->tx_timeout);
	printf("last RX tag: rx port %u, reason %u\n", (p->last_tag0 >> 8) & 0x1f, p->last_tag7 & 0x3f);
	printf("DMA_IF_CTRL 0x%08x, RX_RING_CNTR 0x%08x, CPU port L2 0x%08x force 0x%08x\n",
	       sw_r(DMA_IF_CTRL), sw_r(RX_RING_CNTR), sw_r(L2_PORT_CTRL_CPU), sw_r(MAC_FORCE_CPU));
	return 0;
}

U_BOOT_CMD(ethstat, 1, 0, do_ethstat, "rtl930x-eth: ring indices, drop counters, NIC registers", "");
