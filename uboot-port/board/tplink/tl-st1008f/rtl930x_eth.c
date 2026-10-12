// SPDX-License-Identifier: GPL-2.0-only
/*
 * RTL930x CPU-port NIC (switch port 28): DM_ETH glue, polling, one-cage loop guard (#80, #83).
 * Hardware facts live in the shared core rtl930x_nic.h (same file as Linux 300-20; copied at build).
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

/* platform shim for the core: switch block in KSEG1, ctx unused */
static inline u32 rtl930x_nic_rd(void *ctx, u32 off)
{
	return sw_r(off);
}

static inline void rtl930x_nic_wr(void *ctx, u32 off, u32 v)
{
	sw_w(off, v);
}

#define rtl930x_nic_msleep	mdelay
#define rtl930x_nic_udelay	udelay
#include "rtl930x_nic.h"

#define MAC_LINK_STS		0xcb10
#define RX_N			32		/* ring 0: TFTP is lock-step; 32 covers a TCP window burst */
#define RXS			2		/* rings 1-31: traffic the queue manager sends there anyway (#80) */
#define NRX			RTL930X_NIC_RX_RINGS
#define RXT			(RX_N + (NRX - 1) * RXS)
#define TX_N			4
#define BUF_SIZE		1664		/* 52 cache lines >= CPU_MAX_LEN */
#define CPU_MAX_LEN		1600		/* 1522 + slack: one frame = one descriptor */
#define FCS_LEN			4
#define TX_MIN			60		/* frame without FCS */
#define TX_BYPASS		(RTL930X_NIC_TAG1_BP_FLTR | RTL930X_NIC_TAG1_BP_STP | \
				 RTL930X_NIC_TAG1_BP_VLAN_EGR)
/* A TX slot frees when the NIC has fetched it: Linux 17-23 us per packet incl. DMA
 * (DATASHEET-AUDIT.md); a full 4-deep ring = 4 x 23 us, x1.25 = 115 us. Expiry: frame dropped, logged. */
#define TX_SLOT_US		115
/* A doorbell written while the NIC is busy can be lost: the frame then waits for the next send
 * (host capture 2026-10-12: every TFTP stall was an ACK held 5 s). Re-ring after one frame time x1.25. */
#define TX_REKICK_US		29

struct nic_desc {			/* accessed through KSEG1 only */
	u32 rx_ring[RXT];		/* all 32 RX rings back to back: ring 0 RX_N, the rest RXS */
	u32 tx_ring[TX_N];
	u32 null_ring[4];		/* TX ring 1: one CPU-owned entry */
	struct rtl930x_nic_hdr rx[RXT];
	struct rtl930x_nic_hdr tx[TX_N];
	struct rtl930x_nic_hdr null;
};

struct rtl930x_eth_priv {
	volatile struct nic_desc *d;	/* uncached alias */
	u8 *rx_buf, *tx_buf;		/* cached */
	unsigned int rx_idx[NRX], tx_idx, port, cage;
	int rx_pend;			/* flat RX slot handed to the stack, -1 = none */
	ulong rx_ring_frames[NRX];
	bool hw_ready, rx_any;
	u32 dma_if_ctrl;		/* doorbell base from rtl930x_nic_enable() */
	ulong rx_other, rx_bad, tx_timeout, tx_rekick;
	struct rtl930x_nic_rx_tag last;	/* tag of the last RX frame */
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

static unsigned int ring_first(int r)
{
	return r ? RX_N + (r - 1) * RXS : 0;
}

static unsigned int ring_len(int r)
{
	return r ? RXS : RX_N;
}

static void rx_arm(struct rtl930x_eth_priv *p, int r, unsigned int slot)
{
	unsigned int i = ring_first(r) + slot;
	volatile struct rtl930x_nic_hdr *h = &p->d->rx[i];
	u8 *b = p->rx_buf + i * BUF_SIZE;

	invalidate_dcache_range((ulong)b, (ulong)b + BUF_SIZE);	/* drop lines the stack dirtied */
	h->buf = phys(b);
	h->size = BUF_SIZE;
	h->off_more = 0;
	h->len = 0;
	nic_sync();
	p->d->rx_ring[i] = phys(h) | RTL930X_NIC_OWN | (slot == ring_len(r) - 1 ? RTL930X_NIC_WRAP : 0);
}

/* Stop DMA and the CPU port MAC: no frame lands in memory while U-Boot is not polling */
static void nic_quiesce(void)
{
	rtl930x_nic_stop(NULL);
	rtl930x_nic_irq_off(NULL);
}

/* Once per boot: reset NIC + CPU queues (stock left its own rings armed), then our rings */
static int nic_setup(struct rtl930x_eth_priv *p)
{
	volatile struct nic_desc *d = p->d;
	int i, r, us;

	nic_quiesce();
	us = rtl930x_nic_reset(NULL, 1);
	if (us < 0) {
		printf("rtl930x-eth: NIC reset not done after %d us (0x%08x)\n", RTL930X_NIC_RST_US,
		       sw_r(RTL930X_NIC_RST_GLB_CTRL_0));
		return us;
	}
	printf("rtl930x-eth: NIC reset %d us\n", us);
	rtl930x_nic_reason_map(NULL, 1);	/* every trap reason -> ring 0 */
	d->null.buf = 0;
	d->null.size = 0;
	d->null_ring[0] = phys(&d->null) | RTL930X_NIC_WRAP;	/* CPU-owned: the NIC never writes */
	/* no HOL limit (0) on any ring, as the SDK nic.c: limit 32 stuck the counter and RX (#80).
	 * Every ring armed: a runout on any one (once a CPU-owned null ring) stalled all RX (#80). */
	for (r = 0; r < NRX; r++) {
		rtl930x_nic_rx_ring_size(NULL, r, 0);
		for (i = 0; i < ring_len(r); i++)
			rx_arm(p, r, i);
		p->rx_idx[r] = 0;
	}
	p->rx_pend = -1;
	for (i = 0; i < TX_N; i++)
		d->tx_ring[i] = phys(&d->tx[i]) | (i == TX_N - 1 ? RTL930X_NIC_WRAP : 0);
	nic_sync();
	for (r = 0; r < NRX; r++)
		rtl930x_nic_ring_base(NULL, false, r, phys(&d->rx_ring[ring_first(r)]));
	rtl930x_nic_ring_base(NULL, true, 0, phys(d->tx_ring));
	rtl930x_nic_ring_base(NULL, true, 1, phys(d->null_ring));
	p->tx_idx = 0;
	rtl930x_nic_max_len(NULL, CPU_MAX_LEN);
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
		if (!rtk_net_is_on() && (sw_r(RTL930X_NIC_MAC_FORCE) & 3) != 3) {
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
	p->dma_if_ctrl = rtl930x_nic_enable(NULL);
	return 0;
}

static int rtl930x_eth_send(struct udevice *dev, void *packet, int length)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);
	unsigned int i = p->tx_idx;
	volatile struct rtl930x_nic_hdr *h = &p->d->tx[i];
	u8 *b = p->tx_buf + i * BUF_SIZE;
	int len = max(length, TX_MIN) + FCS_LEN;
	ulong t0 = timer_get_us(), dt, next;

	if (length > BUF_SIZE - FCS_LEN)
		return -EMSGSIZE;
	while (p->d->tx_ring[i] & RTL930X_NIC_OWN) {
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
	rtl930x_nic_tx_tag((u16 *)h->tag, p->port, -1, TX_BYPASS);
	nic_sync();
	p->d->tx_ring[i] = phys(h) | RTL930X_NIC_OWN | (i == TX_N - 1 ? RTL930X_NIC_WRAP : 0);
	nic_sync();
	sw_w(RTL930X_NIC_DMA_IF_CTRL, rtl930x_nic_tx_kick_val(p->dma_if_ctrl, 0));
	p->tx_idx = (i + 1) % TX_N;
	t0 = timer_get_us();
	next = TX_REKICK_US;
	while (p->d->tx_ring[i] & RTL930X_NIC_OWN) {	/* fetched = sent on; else ring again */
		dt = timer_get_us() - t0;
		if (dt > TX_SLOT_US) {
			p->tx_timeout++;
			printf("rtl930x-eth: TX slot %u not fetched after %d us\n", i, TX_SLOT_US);
			return -ETIMEDOUT;
		}
		if (dt >= next) {
			next += TX_REKICK_US;
			p->tx_rekick++;
			sw_w(RTL930X_NIC_DMA_IF_CTRL, rtl930x_nic_tx_kick_val(p->dma_if_ctrl, 0));
		}
	}
	return 0;
}

/* Give the slot back to the NIC and the queue manager; lift a runout on that ring (SDK nic.c) */
static void rx_release(struct rtl930x_eth_priv *p, int r)
{
	rx_arm(p, r, p->rx_idx[r]);
	nic_sync();
	rtl930x_nic_rx_release(NULL, r, 1);	/* the 10-bit counter saturates at 0x3ff otherwise (#80) */
	if (sw_r(RTL930X_NIC_DMA_INTR_STS) & BIT(r))
		sw_w(RTL930X_NIC_DMA_INTR_STS, BIT(r));
	p->rx_idx[r] = (p->rx_idx[r] + 1) % ring_len(r);
}

static int rtl930x_eth_recv(struct udevice *dev, int flags, uchar **packetp)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);
	volatile struct rtl930x_nic_hdr *h;
	unsigned int n, len, f;
	int r;
	u8 *b;

	for (r = NRX - 1; r >= 0; r--) {	/* higher ring = higher priority, as the NIC */
		for (n = 0; n < ring_len(r); n++) {
			f = ring_first(r) + p->rx_idx[r];
			if (p->d->rx_ring[f] & RTL930X_NIC_OWN)
				break;
			h = &p->d->rx[f];
			len = h->len;
			p->rx_ring_frames[r]++;
			rtl930x_nic_rx_tag((const u16 *)h->tag, &p->last);
			if (h->off_more & RTL930X_NIC_MORE || len < ETH_HLEN + FCS_LEN || len > BUF_SIZE) {
				p->rx_bad++;
			} else if (!p->rx_any && p->last.port != p->port) {
				p->rx_other++;		/* isolated cages still reach the CPU: not ours */
			} else {
				b = p->rx_buf + f * BUF_SIZE;
				invalidate_dcache_range((ulong)b, (ulong)b + BUF_SIZE);
				*packetp = b;
				p->rx_pend = r;
				return len - FCS_LEN;
			}
			rx_release(p, r);
		}
	}
	return -EAGAIN;
}

static int rtl930x_eth_free_pkt(struct udevice *dev, uchar *packet, int length)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);

	if (p->rx_pend >= 0) {
		rx_release(p, p->rx_pend);
		p->rx_pend = -1;
	}
	return 0;
}

/* TX fetched first (netconsole halts right after a frame); then only the CPU port MAC stops.
 * DMA keeps running: switching it off between commands desynced the RX ring (#80). remove() stops it. */
static void rtl930x_eth_stop(struct udevice *dev)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);
	ulong t0 = timer_get_us();
	unsigned int i;

	if (!p->hw_ready)
		return;
	for (i = 0; i < TX_N; i++)
		while (p->d->tx_ring[i] & RTL930X_NIC_OWN && timer_get_us() - t0 <= TX_SLOT_US)
			;
	for (i = 0; i < TX_N; i++)
		if (p->d->tx_ring[i] & RTL930X_NIC_OWN) {
			p->tx_timeout++;
			printf("rtl930x-eth: stop: TX slot %u not fetched after %d us\n", i, TX_SLOT_US);
		}
	rtl930x_nic_rmw(NULL, RTL930X_NIC_L2_PORT_CTRL, 3, 0);
}

/* before the OS (bootm: DM_FLAG_ACTIVE_DMA): no DMA into memory the kernel reuses */
static int rtl930x_eth_remove(struct udevice *dev)
{
	struct rtl930x_eth_priv *p = dev_get_priv(dev);

	if (p->hw_ready)
		nic_quiesce();
	return 0;
}

static int rtl930x_eth_write_hwaddr(struct udevice *dev)
{
	rtl930x_nic_set_mac(NULL, ((struct eth_pdata *)dev_get_plat(dev))->enetaddr);
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

	p->rx_buf = memalign(ARCH_DMA_MINALIGN, RXT * BUF_SIZE);
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
	.remove		= rtl930x_eth_remove,
	.ops		= &rtl930x_eth_ops,
	.priv_auto	= sizeof(struct rtl930x_eth_priv),
	.plat_auto	= sizeof(struct eth_pdata),
	.flags		= DM_FLAG_ACTIVE_DMA,
};

/* `clocks set mem`: no NIC DMA into DRAM while it changes clock (stock's rings after its network
 * on, or ours between commands); register-only, safe when the NIC was never set up. The next eth
 * start enables it again (#101) */
void rtl930x_eth_quiesce(void)
{
	nic_quiesce();
}

/* `rtk linkcheck` loop probe (#97): one broadcast out `cage` (physical forward), then every RX
 * frame carrying `magic` for wait_ms; *hits = SDK ports it came back on. Lasers: `cage` only. */
int rtl930x_eth_loop_probe(int cage, const u8 *magic, int mlen, unsigned int wait_ms, u32 *hits)
{
	struct udevice *dev;
	struct rtl930x_eth_priv *p;
	u8 f[TX_MIN];
	uchar *pkt;
	char old[8] = "";
	bool any;
	ulong t0;
	int len, ret;

	*hits = 0;
	if (uclass_first_device_err(UCLASS_ETH, &dev))
		return -ENODEV;
	p = dev_get_priv(dev);
	if (env_get("ethport"))
		strlcpy(old, env_get("ethport"), sizeof(old));
	env_set_ulong("ethport", cage);
	ret = rtl930x_eth_start(dev);
	env_set("ethport", old[0] ? old : NULL);
	if (ret)
		return ret;
	memset(f, 0, sizeof(f));
	memset(f, 0xff, 6);
	memcpy(f + 6, ((struct eth_pdata *)dev_get_plat(dev))->enetaddr, 6);
	f[12] = 0x88;		/* 0x88b5: IEEE local experimental ethertype */
	f[13] = 0xb5;
	memcpy(f + 14, magic, min(mlen, TX_MIN - 14));
	any = p->rx_any;
	p->rx_any = true;
	while ((len = rtl930x_eth_recv(dev, 0, &pkt)) > 0)	/* drain: only frames after our send count */
		rtl930x_eth_free_pkt(dev, pkt, len);
	ret = rtl930x_eth_send(dev, f, sizeof(f));
	t0 = get_timer(0);
	while (!ret && get_timer(t0) < wait_ms) {
		len = rtl930x_eth_recv(dev, 0, &pkt);
		if (len <= 0)
			continue;
		if (len >= 14 + mlen && pkt[12] == 0x88 && pkt[13] == 0xb5 && !memcmp(pkt + 14, magic, mlen))
			*hits |= BIT(p->last.port);
		rtl930x_eth_free_pkt(dev, pkt, len);
	}
	p->rx_any = any;
	return ret;
}

static int do_ethstat(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	struct udevice *dev;
	struct rtl930x_eth_priv *p;
	int r;

	if (uclass_first_device_err(UCLASS_ETH, &dev))
		return CMD_RET_FAILURE;
	p = dev_get_priv(dev);

	printf("cage %u port %u, rx idx %u, tx idx %u, rx other-port %lu, rx bad %lu, tx timeout %lu\n",
	       p->cage, p->port, p->rx_idx[0], p->tx_idx, p->rx_other, p->rx_bad, p->tx_timeout);
	printf("tx re-kicks %lu\n", p->tx_rekick);
	printf("rx frames per ring:");
	for (r = 0; r < NRX; r++)
		if (p->rx_ring_frames[r])
			printf(" %d:%lu", r, p->rx_ring_frames[r]);
	printf("\n");
	printf("last RX tag: rx port %u, reason %u, queue %u\n", p->last.port, p->last.reason, p->last.queue);
	/* switch-side drops: STAT_PORT_E_DROP_CNTR2[28][0], STAT_PORT_MIB_CNTR[0].DOT1DTPPORTINDISCARDS */
	printf("switch drops: CPU queue 0 egress %u, port 0 ingress %u\n", sw_r(0xbd64), sw_r(0x06a8));
	printf("RX runout 0x%08x, DMA_IF_CTRL 0x%08x, RX_RING_CNTR 0x%08x, CPU port L2 0x%08x force 0x%08x\n",
	       sw_r(RTL930X_NIC_DMA_INTR_STS), sw_r(RTL930X_NIC_DMA_IF_CTRL), sw_r(RTL930X_NIC_RX_RING_CNTR),
	       sw_r(RTL930X_NIC_L2_PORT_CTRL), sw_r(RTL930X_NIC_MAC_FORCE));
	return 0;
}

U_BOOT_CMD(ethstat, 1, 0, do_ethstat, "rtl930x-eth: ring indices, drop counters, NIC registers", "");
