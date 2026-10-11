// SPDX-License-Identifier: GPL-2.0+
/*
 * `clocks`: decode of the PLLs and DDR3 timing registers (docs/CLOCKS.md).
 * `clocks set cpu|mem ... force`: PLL changes run from SRAM with the code I-cache locked.
 * ft_board_setup(): writes the decoded rates into the kernel DTB (no Linux clock driver needed).
 */

#include <command.h>
#include <cpu_func.h>
#include <dm.h>
#include <ns16550.h>
#include <fdt_support.h>
#include <malloc.h>
#include <serial.h>
#include <time.h>
#include <asm/addrspace.h>
#include <asm/global_data.h>
#include <asm/io.h>
#include <asm/mipsregs.h>
#include <linux/bitfield.h>
#include <linux/kernel.h>
#include <linux/libfdt.h>
#include <mach/otto.h>
#include "ddr_sram.h"

DECLARE_GLOBAL_DATA_PTR;

#define R(a)	__raw_readl((void __iomem *)(a))
#define F(v, h, l)	((u32)FIELD_GET(GENMASK(h, l), v))

static void khz(const char *name, u32 v)
{
	if (v % 1000)
		printf("%s %u.%03u MHz", name, v / 1000, v % 1000);
	else
		printf("%s %u MHz", name, v / 1000);
}

/* clocks of n at mem_khz, in 0.1 ns */
static u32 dns(u32 n, u32 mem_khz)
{
	return n * 10000 / max(mem_khz / 1000, 1U);
}

/*
 * DRAM MR0/MR2 as DMCR words, derived from DTR0 by the stock SPL rule [BIN 0x9fc01120, SDK
 * _DTR_DDR3_MRS_setting]: CL = CAS_PHY 3:0 + 1, WR from tWR 27:24, CWL from 23:20; BL8, PD fast.
 * MR1 0x0004 (RZQ/6, RTT_NOM RZQ/4) and MR3 0 never change. -EINVAL outside the SPL's table.
 */
#define DMCR_MR(n)	((u32)BIT(20) | (n) << 16)
static int dram_mrs(u32 dtr0, u32 *mr0, u32 *mr2)
{
	u32 cas = F(dtr0, 3, 0), wr = F(dtr0, 27, 24), cwl = F(dtr0, 23, 20);
	static const u16 wr_code[16] = { [4] = 0x200, [5] = 0x400, [6] = 0x600, [7] = 0x800,
					 [8] = 0xa00, [9] = 0xa00, [11] = 0xc00 };

	if (cas < 4 || cas > 10 || !wr_code[wr] || cwl < 4 || cwl > 7)
		return -EINVAL;
	*mr0 = DMCR_MR(0) | 0x1000 | (cas - 3) << 4 | wr_code[wr];
	*mr2 = DMCR_MR(2) | (cwl - 4) << 3;
	return 0;
}

static void ddr(u32 mem_khz)
{
	u32 mcr = R(0xb8001000), dcr = R(0xb8001004), mr0, mr2, i;
	u32 d0 = R(0xb8001008), d1 = R(0xb800100c), d2 = R(0xb8001010);
	/* DTR fields hold clocks - 1 (Realtek DRAM gen2 memcntlr_setup.c; CWL matches JEDEC) */
	u32 cl = F(d0, 31, 28) + 1, wr = F(d0, 27, 24) + 1, cwl = F(d0, 23, 20) + 1;
	u32 rtp = F(d0, 19, 16) + 1, wtr = F(d0, 15, 12) + 1;
	u32 refi = (F(d0, 11, 8) + 1) << (F(d0, 7, 4) + 5);
	u32 rp = F(d1, 28, 24) + 1, rcd = F(d1, 20, 16) + 1, rrd = F(d1, 12, 8) + 1;
	u32 faw = F(d1, 4, 0) + 1, rfc = F(d2, 27, 20) + 1, ras = F(d2, 17, 12) + 1;
	u32 bits = (F(dcr, 29, 28) + 1) + F(dcr, 25, 24) + (F(dcr, 23, 20) + 11) +
		   (F(dcr, 19, 16) + 8);

	printf("dram DDR%u, %u banks x%u, %u row + %u col bits -> %u MiB (MCR %08x DCR %08x)\n",
	       F(mcr, 31, 28) + 1, 2 << F(dcr, 29, 28), 8 << F(dcr, 25, 24),
	       F(dcr, 23, 20) + 11, F(dcr, 19, 16) + 8, 1U << (bits - 20), mcr, dcr);
	printf("ddr3 clk: CL %u CWL %u tWR %u tRTP %u tWTR %u tRP %u tRCD %u tRRD %u tFAW %u "
	       "tRAS %u tRFC %u tREFI %u\n", cl, cwl, wr, rtp, wtr, rp, rcd, rrd, faw, ras, rfc, refi);
	printf("ddr3 ns:  CL %u.%u tRP %u.%u tRCD %u.%u tRAS %u.%u tRFC %u.%u tREFI %u.%u "
	       "(DTR0 %08x DTR1 %08x DTR2 %08x, CAS_PHY %u)\n",
	       dns(cl, mem_khz) / 10, dns(cl, mem_khz) % 10, dns(rp, mem_khz) / 10,
	       dns(rp, mem_khz) % 10, dns(rcd, mem_khz) / 10, dns(rcd, mem_khz) % 10,
	       dns(ras, mem_khz) / 10, dns(ras, mem_khz) % 10, dns(rfc, mem_khz) / 10,
	       dns(rfc, mem_khz) % 10, dns(refi, mem_khz) / 10, dns(refi, mem_khz) % 10,
	       d0, d1, d2, F(d0, 3, 0));
	if (!dram_mrs(d0, &mr0, &mr2))
		printf("ddr3 dram: CL %u CWL %u (MR0 %04x MR2 %04x from DTR0, stock SPL rule)\n",
		       F(d0, 3, 0) + 1, F(d0, 23, 20) + 1, mr0 & 0x3fff, mr2 & 0x3fff);
	printf("ddr3 ctl: DMCR %08x MPMR0 %08x MPMR1 %08x DACCR %08x DIDER %08x D3ZQCCR %08x\n",
	       R(0xb800101c), R(0xb8001040), R(0xb8001044), R(0xb8001500), R(0xb8001050),
	       R(0xb8001080));
	printf("ddr3 phy: DCSDCR0-3 %08x %08x %08x %08x DWDMOR %08x DWDQSOR %08x\n",
	       R(0xb80015b0), R(0xb80015b4), R(0xb80015b8), R(0xb80015bc), R(0xb80015c0),
	       R(0xb80015c4));
	/* read DQ delay: DACDQ_IDX_RR/FR 0xb8001510/50 + 4 x DQ, cur_tap 12:8 (memcntlr_reg.h) */
	printf("ddr3 dq: RR0 %08x FR0 %08x DCDQMR %08x; cur tap rise/fall DQ0-15:", R(0xb8001510),
	       R(0xb8001550), R(0xb8001590));
	for (i = 0; i < 16; i++)
		printf(" %u/%u", F(R(0xb8001510 + 4 * i), 12, 8), F(R(0xb8001550 + 4 * i), 12, 8));
	puts("\n");
	printf("mem pll: MPCR0-6 %08x %08x %08x %08x %08x %08x %08x\n", R(0xb8000234),
	       R(0xb8000238), R(0xb800023c), R(0xb8000240), R(0xb8000244), R(0xb8000248),
	       R(0xb800024c));
}

extern char otto_cpu_pll_sram[], otto_cpu_pll_sram_end[];
extern char otto_ddr_sram[], otto_ddr_sram_end[];
#define SRAM_RUN	0x9f004000	/* KSEG0 SRAM, clear of the SPL globals 0x9f000b70..bbc */
#define SRAM_CODE_MAX	0x800
#define SRAM_PARAM	0xbf004800	/* KSEG1 SRAM after the code: DDR routine block */
#define SRAMSAR0	0xb8004000	/* SRAM window; stock 0x1f000001 = bus 0x1f000000, enabled */
#define UMSAR0		0xb8001300	/* matching unmapped-memory window; `highmem map` clears both */
#define SRAM_WIN	0x1f000001
#define UART_LSR	0xb8002014
#define LSR_TEMT	BIT(6)
#define TEMT_POLL	100000	/* 16-byte FIFO at 115200 = 1.4 ms; bound only names a stuck UART */

struct sram_win {
	u32 sram, um;
	ulong size;
};

/* map SRAM (stock window; `highmem map` clears it), copy code, I fetch-and-lock its lines */
static void *sram_load(struct sram_win *w, const char *start, const char *end)
{
	ulong a;

	w->size = end - start;
	w->sram = R(SRAMSAR0);
	w->um = R(UMSAR0);
	__raw_writel(SRAM_WIN, (void __iomem *)UMSAR0);
	__raw_writel(SRAM_WIN, (void __iomem *)SRAMSAR0);
	__asm__ __volatile__("sync");
	memcpy((void *)SRAM_RUN, start, w->size);
	flush_cache(SRAM_RUN, w->size);
	for (a = SRAM_RUN; a < SRAM_RUN + w->size; a += 32)
		__asm__ __volatile__("cache 0x1c, 0(%0)" : : "r"(a));
	return (void *)SRAM_RUN;
}

static void sram_unload(const struct sram_win *w)
{
	flush_cache(SRAM_RUN, w->size);	/* hit-invalidate also unlocks */
	__raw_writel(w->sram, (void __iomem *)SRAMSAR0);
	__raw_writel(w->um, (void __iomem *)UMSAR0);
	__asm__ __volatile__("sync");
}

static void uart_drain(void)
{
	u32 i;

	for (i = 0; i < TEMT_POLL && !(__raw_readb((void __iomem *)UART_LSR) & LSR_TEMT); i++)
		;
}

/* docs/CLOCKS.md (a): run the stock sequence from SRAM with the lines locked in the I-cache */
static int cpu_set(u32 e208, u32 e210, u32 relock)
{
	u32 (*fn)(u32, u32, u32);
	struct sram_win w;
	u32 left;

	printf("clocks: write 0xbb00e208=0x%08x 0xbb00e210=0x%08x, relock %s\n", e208, e210,
	       relock ? "e220 bit 17" : "e200 bit 30");
	fn = sram_load(&w, otto_cpu_pll_sram, otto_cpu_pll_sram_end);
	uart_drain();
	left = fn(e208, e210, relock);
	sram_unload(&w);
	if (!left) {
		puts("clocks: CPU PLL did not lock in 100000 polls; CPU left on the alternate clock\n");
		return CMD_RET_FAILURE;
	}
	printf("clocks: locked after %u polls\n", 100000 - left);
	return 0;
}

#define PLL_E200	0xbb00e200	/* bit 17 LXB_CLK_SEL: 1 = LX on the alternate clock */
#define PLL_E220	0xbb00e220	/* [12:9] DIVN2_LXB: LX = sw vco / (2 x (code + 2)) */

/* docs/CLOCKS.md "LX at runtime": switch LX, then hand the console its new clock at once */
static int lx_set(u32 code)
{
	struct ns16550_plat *plat;
	struct otto_clocks c;
	struct udevice *dev;
	u32 i;

	if (code < 2 || code > 5) {	/* 5 = 175 MHz stock; 2 = 306 MHz */
		puts("clocks: lx code 2..5 only\n");
		return CMD_RET_USAGE;
	}
	if (uclass_get_device(UCLASS_SERIAL, 0, &dev))
		return CMD_RET_FAILURE;
	plat = dev_get_plat(dev);
	printf("clocks: 0xbb00e220[12:9] = %u via LXB_CLK_SEL; console follows\n", code);
	for (i = 0; i < TEMT_POLL && !(__raw_readb((void __iomem *)UART_LSR) & LSR_TEMT); i++)
		;
	__raw_writel(R(PLL_E200) | BIT(17), (void __iomem *)PLL_E200);
	__raw_writel((R(PLL_E220) & ~GENMASK(12, 9)) | (code << 9), (void __iomem *)PLL_E220);
	__raw_writel(R(PLL_E200) & ~BIT(17), (void __iomem *)PLL_E200);
	__asm__ __volatile__("sync");
	otto_clocks_read(&c);
	plat->clock = c.lx_khz * 1000;
	serial_setbrg();
	printf("clocks: lx now %u kHz, uart clock updated\n", c.lx_khz);
	return 0;
}

/*
 * MEM bins: PLL rows = Realtek SDK cg_mem.c (same as the stock SPL table); DTR0/1 + DTR2 base =
 * stock SPL DTR table. 650: no PLL row anywhere -> 600 row with NCODE 50 (SPEC).
 * 675-800: `scripts/clock_calc.py ddr-bin` (DRAM datasheet + SDK formulas; 600 PLL row, SPEC).
 */
static const struct mem_bin {
	u16 mhz;
	u32 mpcr[4], dtr0, dtr1, dtr2;
} mem_bins[] = {
	{ 800, { 0x0000007f, 0x400001ef, 0x26a33860, 0x3e0f0000 }, 0xbb755b3a, 0x0b0b051f, 0x0001b000 },
	{ 775, { 0x0000007f, 0x400001ef, 0x26a33860, 0x3c0f0000 }, 0xbb755a3a, 0x0a0a051e, 0x0001a000 },
	{ 750, { 0x0000007f, 0x400001ef, 0x26a33860, 0x3a0f0000 }, 0xbb755a3a, 0x0a0a051d, 0x00019000 },
	{ 725, { 0x0000007f, 0x400001ef, 0x26a33860, 0x380f0000 }, 0xbb755a3a, 0x0a0a051c, 0x00018000 },
	{ 700, { 0x0000007f, 0x400001ef, 0x26a33860, 0x360f0000 }, 0xbb75593a, 0x0909051b, 0x00017000 },
	{ 675, { 0x0000007f, 0x400001ef, 0x26a33860, 0x340f0000 }, 0xbb75593a, 0x0909051a, 0x00016000 },
	{ 650, { 0x0000007f, 0x400001ef, 0x26a33860, 0x320f0000 }, 0x99655838, 0x0909061f, 0x00019000 },
	{ 600, { 0x0000007f, 0x400001ef, 0x26a33860, 0x2e0f0000 }, 0x99644838, 0x0808061f, 0x00016000 },
	{ 550, { 0x000c607f, 0x4000018f, 0x26a33840, 0x2a0f0000 }, 0x98644738, 0x0808051e, 0x00014000 },
	{ 500, { 0x000c607f, 0x4000018f, 0x26a23740, 0x260f0000 }, 0x77533d26, 0x0707031b, 0x00013000 },
	{ 450, { 0x0008407f, 0x4000018f, 0x26a23720, 0x220f0000 }, 0x67533d26, 0x07070418, 0x00011000 },
	{ 400, { 0x0000007f, 0x400001ef, 0x26622520, 0x1e0f0000 }, 0x56433b25, 0x05050315, 0x0000f000 },
	{ 350, { 0x0008407f, 0x4000018f, 0x26222520, 0x1a0f0000 }, 0x55422925, 0x05050312, 0x0000d000 },
	{ 300, { 0x0008407f, 0x4000018f, 0x26222520, 0x160f0000 }, 0x55422825, 0x05050210, 0x0000b000 },
};

#define CANARY_WORDS	1024

/* write back + invalidate every D-cache line (index op over KSEG0, Config1 geometry) */
static void dcache_wbinv_all(void)
{
	u32 c1 = read_c0_config1(), dl = (c1 >> 10) & 7;
	ulong a, line = 2 << dl, end = KSEG0 + line * (64 << ((c1 >> 13) & 7)) * (((c1 >> 7) & 7) + 1);

	if (!dl)
		return;
	for (a = KSEG0; a < end; a += line)
		__asm__ __volatile__("cache 0x01, 0(%0)" : : "r"(a));
	__asm__ __volatile__("sync");
}

static void dp_set(u32 off, u32 v)
{
	__raw_writel(v, (void __iomem *)(SRAM_PARAM + off));
}

static u32 dp_get(u32 off)
{
	return R(SRAM_PARAM + off);
}

/* `clocks set mem` request: bin + experiment overrides (docs/CLOCKS.md (b), #48 #49 #56) */
struct mem_req {
	u32 mhz, method, probe, cl11, dtr0, mpcr_set, mpcr[3], nreg, reg[DS_REG_MAX][2];
};

/* PHY registers an override may touch: DIDER + DDPDR0/1, DACCR .. DWDQSOR */
static bool phy_reg_ok(u32 a)
{
	return !(a & 3) && ((a >= 0xb8001050 && a <= 0xb8001058) || (a >= 0xb8001500 && a <= 0xb80015c4));
}

static void put_set(u32 base, const u32 *mpcr, u32 d0, u32 d1, u32 d2, u32 flags, u32 mhz,
		    const struct mem_req *q, bool old)
{
	u32 mr0 = 0, mr2 = 0;
	int i;

	dp_set(base + DS_NREG, q->nreg);	/* old set: the values read now = revert */
	for (i = 0; i < q->nreg; i++) {
		dp_set(base + DS_REG + 8 * i, q->reg[i][0]);
		dp_set(base + DS_REG + 8 * i + 4, old ? R(q->reg[i][0]) : q->reg[i][1]);
	}
	dram_mrs(d0, &mr0, &mr2);	/* checked by the caller when DSF_MRS is set */
	for (i = 0; i < 4; i++)
		dp_set(base + DS_MPCR0 + 4 * i, mpcr[i]);
	dp_set(base + DS_DTR0, d0);
	dp_set(base + DS_DTR1, d1);
	dp_set(base + DS_DTR2, d2);
	dp_set(base + DS_FLAGS, flags);
	dp_set(base + DS_MR0, mr0);
	dp_set(base + DS_MR2, mr2);
	dp_set(base + DS_DLLK_US, DIV_ROUND_UP(512 * 125, max(mhz, 1U) * 100));	/* tDLLK x 1.25 */
}

/* docs/CLOCKS.md (b): DDR3 self-refresh, MEM PLL, DTRs, from SRAM; DRAM contents kept */
/* CL 11 / CWL 8 / WR 12 fields of the 675-800 bins: DTR0 CL 31:28, tWR 27:24, CWL 23:20, CAS_PHY 3:0 */
#define DTR0_CLW_MASK	0xfff0000f
#define DTR0_CL11	0xbb70000a

static int mem_set(const struct mem_req *q)
{
	static const u16 trfc_ns[] = { 90, 110, 160, 260, 350 };	/* 512 Mbit .. 8 Gbit die */
	const struct mem_bin *b = NULL;
	struct otto_clocks c;
	struct sram_win w;
	u32 (*fn)(u32);
	u32 old_mpcr[4], d0 = R(0xb8001008), d1 = R(0xb800100c), d2 = R(0xb8001010);
	u32 dcr = R(0xb8001004), cur, die, dtr2, up, st, i, seed, bad = 0, *buf, *can;
	u32 mr0, mr2, omr0, omr2, flags, mhz = q->mhz, method = q->method, ndtr0, mpcr[4], rev;
	ulong t0;

	for (i = 0; i < ARRAY_SIZE(mem_bins); i++)
		if (mem_bins[i].mhz == mhz)
			b = &mem_bins[i];
	if (!b) {
		/* above 800: CL 13 / CWL 9 are outside the SPL/SDK MR tables and the SoC's 800 MHz rating */
		printf("clocks: no bin for %u MHz (800 775 750 725 700 675 650 600 550 500 450 400 350 300)\n",
		       mhz);
		return CMD_RET_FAILURE;
	}
	ndtr0 = q->dtr0 ? q->dtr0 : q->cl11 ? (b->dtr0 & ~DTR0_CLW_MASK) | DTR0_CL11 : b->dtr0;
	memcpy(mpcr, b->mpcr, sizeof(mpcr));
	if (q->mpcr_set)
		memcpy(mpcr, q->mpcr, sizeof(q->mpcr));	/* MPCR0-2; NCODE (MPCR3) from the bin */
	/* DRAM CL/CWL/WR (MR0/MR2) change -> MRS + DLL reset in the routine; refresh-off method only */
	if (dram_mrs(ndtr0, &mr0, &mr2) || dram_mrs(d0, &omr0, &omr2)) {
		printf("clocks: DTR0 %08x / live %08x outside the SPL MR table\n", ndtr0, d0);
		return CMD_RET_FAILURE;
	}
	flags = (mr0 != omr0 || mr2 != omr2) ? DSF_MRS : 0;
	if (flags && !method) {
		printf("clocks: %u MHz changes MR0/MR2 (MRS): nosr method only\n", mhz);
		return CMD_RET_FAILURE;
	}
	/* one x16 die: size bits as in `clocks`; tRFC by die size (SPL rule, docs/CLOCKS.md) */
	die = (F(dcr, 29, 28) + 1) + F(dcr, 25, 24) + (F(dcr, 23, 20) + 11) + (F(dcr, 19, 16) + 8) +
	      3 - 20;	/* log2 Mbit */
	if (F(dcr, 25, 24) != 1 || die < 9 || die > 13) {
		printf("clocks: DCR %08x is not one x16 die of 512 Mbit..8 Gbit\n", dcr);
		return CMD_RET_FAILURE;
	}
	if (mhz * trfc_ns[die - 9] / 1000 + 5 > 255) {	/* DTR2 tRFC 27:20 */
		printf("clocks: tRFC for %u MHz does not fit DTR2\n", mhz);
		return CMD_RET_FAILURE;
	}
	dtr2 = ((mhz * trfc_ns[die - 9] / 1000 + 5) << 20) | b->dtr2;
	otto_clocks_read(&c);
	cur = c.mem_khz / 1000;
	/* CMUCR_OC0/LX* SE_DRAM = (bus clock <= MEM) (SDK cg_mem.c): must not change, not written */
	if ((c.cpu_khz / 1000 > cur) != (c.cpu_khz / 1000 > mhz) ||
	    (c.lx_khz / 1000 > cur) != (c.lx_khz / 1000 > mhz)) {
		puts("clocks: MEM would cross the CPU or LX clock (SE_DRAM bits): not supported\n");
		return CMD_RET_FAILURE;
	}
	if (otto_ddr_sram_end - otto_ddr_sram > SRAM_CODE_MAX)
		return CMD_RET_FAILURE;
	buf = malloc(CANARY_WORDS * 4 + 32);
	if (!buf)
		return CMD_RET_FAILURE;
	can = PTR_ALIGN(buf, 32);
	flush_dcache_range((ulong)can, (ulong)(can + CANARY_WORDS));
	can = (u32 *)CKSEG1ADDR(can);
	seed = 0x5aa5c33c ^ (u32)timer_get_us();
	for (i = 0; i < CANARY_WORDS; i++)
		can[i] = (4 * i) ^ seed;
	for (i = 0; i < 4; i++)
		old_mpcr[i] = R(0xb8000234 + 4 * i);
	up = mhz > cur;

	printf("clocks: mem %u -> %u MHz, %s; DTR %s the clock change\n", cur, mhz,
	       method ? "refresh off (DMCR bit 24)" : "self-refresh (MPMR0 PM_MODE 2, SPEC)",
	       flags ? "after (refresh still off)" : up ? "before" : "after");
	if (flags)
		printf("clocks: MRS after the PLL: DMCR MR2 %08x -> %08x, MR0 %08x -> %08x + DLL reset "
		       "(0x100), %u us tDLLK, MR3 %08x; same back on revert\n", omr2, mr2, omr0, mr0,
		       DIV_ROUND_UP(512 * 125, mhz * 100), DMCR_MR(3));
	printf("clocks: write 0xb8001008 DTR0 %08x -> %08x%s\n", d0, ndtr0,
	       q->dtr0 ? " (override)" : q->cl11 ? " (cl11)" : "");
	printf("clocks: write 0xb800100c DTR1 %08x -> %08x\n", d1, b->dtr1);
	printf("clocks: write 0xb8001010 DTR2 %08x -> %08x\n", d2, dtr2);
	printf("clocks: write 0xb800101c DMCR %08x (rewrite: DTR latch), poll bit 31\n", R(0xb800101c));
	if (method)
		puts("clocks: write 0xb800101c DMCR bit 24 = 1 (refresh off), = 0 after the PLL\n");
	else
		printf("clocks: write 0xb8001040 MPMR0 %08x PM_MODE 29:28 = 2, = 0 after the PLL\n",
		       R(0xb8001040));
	printf("clocks: write 0xb8000244 MPCR4 %08x clk_oe 5:0 = 0, 200 us\n", R(0xb8000244));
	for (i = 0; i < 4; i++)
		printf("clocks: write 0x%08x MPCR%u %08x -> %08x%s\n", 0xb8000234 + 4 * i, i,
		       old_mpcr[i], mpcr[i], q->mpcr_set && i < 3 ? " (override)" :
		       mhz >= 650 ? " (SPEC)" : "");
	printf("clocks: write 0xb8000248/24c MPCR5/6 %08x %08x -> 0\n", R(0xb8000248), R(0xb800024c));
	for (i = 0; i < q->nreg; i++)
		printf("clocks: write 0x%08x %08x -> %08x (override, clk_oe = 0)\n", q->reg[i][0],
		       R(q->reg[i][0]), q->reg[i][1]);
	puts("clocks: 5 us, clk_oe = 0x3f, 200 us\n");
	printf("clocks: write 0xb8001500 DACCR %08x bit 4 0 -> 1, bit 5 = 1 (PHY FIFO pointer clear)\n",
	       R(0xb8001500));
	printf("clocks: canary %u words at %p, revert to the current set on mismatch%s\n",
	       CANARY_WORDS, can, q->probe ? " and after it (probe)" : "");

	fn = sram_load(&w, otto_ddr_sram, otto_ddr_sram_end);
	put_set(DP_NEW, mpcr, ndtr0, b->dtr1, dtr2, flags ?: up ? DSF_DTR_FIRST : 0, mhz, q, false);
	put_set(DP_OLD, old_mpcr, d0, d1, d2, flags ?: up ? 0 : DSF_DTR_FIRST, cur, q, true);
	dp_set(DP_METHOD, method);
	dp_set(DP_LOOPS_US, DIV_ROUND_UP(c.cpu_khz, 2000));	/* 2 cycles per loop */
	dp_set(DP_CAN_ADDR, (u32)(ulong)can);
	dp_set(DP_CAN_WORDS, CANARY_WORDS);
	dp_set(DP_CAN_SEED, seed);
	for (i = DP_STATUS; i < DP_SAVE; i += 4)
		dp_set(i, 0);
	dp_set(DP_PROBE, q->probe);
	uart_drain();
	t0 = timer_get_us();
	dcache_wbinv_all();	/* last: no dirty line may be evicted into a DRAM in self-refresh */
	st = fn(SRAM_PARAM);
	t0 = timer_get_us() - t0;
	printf("\nclocks: routine %lu us, status 0x%02x, DMCR polls left %u, MPMR0 in SR %08x exit %08x\n",
	       t0, st, dp_get(DP_DMCR_POLLS), dp_get(DP_MPMR0_SR), dp_get(DP_MPMR0_EXIT));
	/* one parseable line per attempt (scripts/mem_tap_sweep.py) */
	if (st & (DST_CANARY | DST_PROBE))
		printf("clocks: canary %u bad at the new clock, xor %08x, first +0x%x = %08x want %08x, "
		       "revert code %u\n", dp_get(DP_CAN_BAD), dp_get(DP_CAN_XOR), dp_get(DP_CAN_OFF),
		       dp_get(DP_CAN_VAL), dp_get(DP_CAN_OFF) ^ seed, dp_get(DP_REV_CODE));
	rev = dp_get(DP_REV_CODE);
	sram_unload(&w);
	for (i = 0; i < CANARY_WORDS; i++)
		bad += can[i] != ((4 * i) ^ seed);
	free(buf);
	otto_clocks_read(&c);
	printf("clocks: mem now %u kHz, DTR0 %08x DTR1 %08x DTR2 %08x, canary %u bad\n", c.mem_khz,
	       R(0xb8001008), R(0xb800100c), R(0xb8001010), bad);
	if (q->probe) {
		/* probe passes when it is back on the old set with good data; the result is the count */
		st = (st & ~(DST_CANARY | DST_PROBE | DST_REV_OK)) | rev;
		printf("clocks: probe %s\n", st || bad ? "FAIL (not back cleanly)" : "OK");
		return st || bad ? CMD_RET_FAILURE : 0;
	}
	if (st || bad) {
		printf("clocks: mem set FAIL (%s)\n",
		       (st & DST_CODE) == DST_BUSY ? "controller busy, nothing changed" :
		       (st & DST_CODE) == DST_DTR_PRE ? "DTR latch timeout, clock unchanged" :
		       (st & DST_CODE) == DST_REFRESH ? "refresh toggle timeout" :
		       (st & DST_CODE) == DST_DTR_POST ? "DTR latch timeout after the change" :
		       (st & DST_CODE) == DST_MRS ? "DTR latch / MRS timeout after the change" :
		       st & DST_REV_OK ? "data bad at the new clock, reverted" :
		       st & DST_REV_BAD ? "data bad, revert did not help" : "canary bad");
		return CMD_RET_FAILURE;
	}
	puts("clocks: mem set OK\n");
	return 0;
}

/* `clocks fast` = CPU 1000 MHz (/3) only. SPI 122.5 MHz is U-Boot-only: Linux reads flash
 * through the PIO path and got SQUASHFS errors with it (#50) */
#define FAST_E208	0x3a8
#define FAST_E210	0x6b439e13

/* DRAM controller prefetch, MCR 23 ip_ref / 22 dp_ref; Realtek enables with 0 then 1 (#52) */
#define MCR_REG		0xb8001000
#define MCR_PREF	(BIT(23) | BIT(22))

#define SFCR_REG	0xb8001200	/* [31:29] D: SPI = NOR / 2(D + 1) */
#define FAST_SFCR_D	0
#define FAST_NOR_CODE	4	/* e220[16:13]: NOR = 2450 / 2(code + 2) = 204.2 MHz */
#define FAST_MEM_MHZ	650	/* runtime change with refresh paused (nosr); self-refresh mode hangs (#39) */
#define DTR0_REG	0xb8001008
#define DMCR_REG	0xb800101c
/* tREFI = (t + 1) << (unit + 5) clk: t 8, unit 4 = 4608 clk = 7.09 us at 650 MHz (stock unit 3) */
#define DTR0_REFI	((8 << 8) | (4 << 4))

static int refi_set(void)
{
	u32 i;

	__raw_writel((R(DTR0_REG) & ~0xff0) | DTR0_REFI, (void __iomem *)DTR0_REG);
	__raw_writel(R(DMCR_REG), (void __iomem *)DMCR_REG);	/* rewrite = latch DTRs (SDK) */
	for (i = 0; i < 64 && (R(DMCR_REG) & BIT(31)); i++)	/* latch ~1 us; 64 polls >= 3.2 us */
		;
	if (R(DMCR_REG) & BIT(31)) {
		puts("clocks: DTR latch still busy after 64 polls\n");
		return CMD_RET_FAILURE;
	}
	return 0;
}

static int fast_set(void)
{
	struct mem_req q = { .mhz = FAST_MEM_MHZ, .method = 1 };
	int ret = cpu_set(FAST_E208, FAST_E210, 0);

	if (!ret)
		ret = mem_set(&q);
	if (!ret)
		ret = refi_set();
	if (ret)
		return ret;
	__raw_writel(R(MCR_REG) & ~MCR_PREF, (void __iomem *)MCR_REG);
	__raw_writel(R(MCR_REG) | MCR_PREF, (void __iomem *)MCR_REG);
	/* SPI 102.1 MHz: fastest Linux reads bit-exact; 122.5 corrupts (#50) */
	__raw_writel((R(SFCR_REG) & ~GENMASK(31, 29)) | (FAST_SFCR_D << 29), (void __iomem *)SFCR_REG);
	__raw_writel((R(PLL_E220) & ~GENMASK(16, 13)) | (FAST_NOR_CODE << 13), (void __iomem *)PLL_E220);
	__asm__ __volatile__("sync");
	printf("clocks: fast = cpu 1000 MHz, mem %u MHz, tREFI 4608 clk, dram prefetch on (MCR %08x), "
	       "spi 102.1 MHz\n", FAST_MEM_MHZ, R(MCR_REG));
	return 0;
}

#define CLI_REG_MAX	4	/* command line < 240 chars (console) */

/* <MHz> [nosr] [probe] [cl11] [dtr0 <hex>] [mpcr <m0> <m1> <m2>] [dqshift <n>] [reg <a> <v>]... */
static int mem_cmd(int n, char *const v[])
{
	struct mem_req q = { .mhz = dectoul(v[0], NULL) };
	int i, dqs = 0, shift = 0;

	for (i = 1; i < n; i++) {
		if (!strcmp(v[i], "nosr")) {
			q.method = 1;
		} else if (!strcmp(v[i], "probe")) {
			q.probe = 1;
		} else if (!strcmp(v[i], "cl11")) {
			q.cl11 = 1;
		} else if (!strcmp(v[i], "dtr0") && i + 1 < n) {
			q.dtr0 = hextoul(v[++i], NULL);
		} else if (!strcmp(v[i], "mpcr") && i + 3 < n) {
			q.mpcr_set = 1;
			q.mpcr[0] = hextoul(v[++i], NULL);
			q.mpcr[1] = hextoul(v[++i], NULL);
			q.mpcr[2] = hextoul(v[++i], NULL);
		} else if (!strcmp(v[i], "dqshift") && i + 1 < n && !dqs) {
			dqs = 1;
			shift = simple_strtol(v[++i], NULL, 10);
		} else if (!strcmp(v[i], "reg") && i + 2 < n && q.nreg < CLI_REG_MAX) {
			q.reg[q.nreg][0] = hextoul(v[++i], NULL);
			q.reg[q.nreg][1] = hextoul(v[++i], NULL);
			if (!phy_reg_ok(q.reg[q.nreg][0])) {
				printf("clocks: reg %08x: PHY overrides only (b8001050..58, b8001500..15c4)\n",
				       q.reg[q.nreg][0]);
				return CMD_RET_FAILURE;
			}
			q.nreg++;
		} else {
			printf("clocks: mem option '%s' unknown or incomplete (max %u reg)\n", v[i],
			       CLI_REG_MAX);
			return CMD_RET_USAGE;
		}
	}
	/* dqshift: every DQ's trained read tap (DACDQ_IDX_RR/FR cur_tap 12:8) + shift, clamped 0..31 */
	for (i = 0; dqs && i < 32; i++) {
		u32 a = (i < 16 ? 0xb8001510 : 0xb8001550) + 4 * (i % 16), r = R(a);
		int t = clamp((int)F(r, 12, 8) + shift, 0, 31);

		q.reg[q.nreg][0] = a;
		q.reg[q.nreg++][1] = (r & ~GENMASK(12, 8)) | t << 8;
	}
	return mem_set(&q);
}

static int do_clocks(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	struct otto_clocks c;
	u32 e208 = R(0xbb00e208), e210 = R(0xbb00e210), e214 = R(0xbb00e214), e220 = R(0xbb00e220);
	u32 div;

	if (argc == 2 && !strcmp(argv[1], "fast"))
		return fast_set() ? CMD_RET_FAILURE : 0;
	if (argc > 1) {
		if (argc < 5 || strcmp(argv[1], "set") || strcmp(argv[argc - 1], "force"))
			return CMD_RET_USAGE;
		if (!strcmp(argv[2], "mem"))
			return mem_cmd(argc - 4, argv + 3);
		/* clocks set cpu <e208> <e210> [relock 0|1] force  (values: scripts/clock_calc.py) */
		if (argc == 5 && !strcmp(argv[2], "lx"))
			return lx_set(dectoul(argv[3], NULL));
		if (argc < 6 || strcmp(argv[2], "cpu"))
			return CMD_RET_USAGE;
		return cpu_set(hextoul(argv[3], NULL), hextoul(argv[4], NULL),
			       argc > 6 ? hextoul(argv[5], NULL) : 0);
	}
	otto_clocks_read(&c);
	khz("cpu", c.cpu_khz);
	khz(" (ocp0; vco", c.cpu_vco_khz);
	printf(" = 25 MHz x%s(%u + 2) x 2 / %u, / (%u + 2)); src %s\n",
	       (e208 & BIT(2)) ? "4 x " : "", F(e208, 11, 4), 1 << (e208 & 3), F(e210, 6, 4),
	       c.cpu_on_pll ? "pll" : "ALT (SSR.ckse_ocp0 = 0, rate unknown)");
	khz("timer", c.cpu_khz / 2);
	printf(" (CP0 Count = cpu / 2)\n");
	khz("lx", c.lx_khz);
	khz(" (sw vco", c.sw_vco_khz);
	printf(" = 25 MHz x%s(%u + 2) x 2 / %u, / 2(%u + 2))\n", (e214 & BIT(2)) ? "4 x " : "",
	       F(e214, 11, 4), 1 << (e214 & 3), F(e220, 12, 9));
	khz("spi", c.spi_khz);
	khz(" (nor", c.nor_khz);
	printf(" = sw vco / 2(%u + 2), / SFCR %u)\n", F(e220, 16, 13),
	       2 * (F(R(0xb8001200), 31, 29) + 1));
	div = DIV_ROUND_CLOSEST(c.lx_khz * 1000, 16 * gd->baudrate);
	printf("uart %u baud: divisor %u -> %u baud (lx / 16 / divisor)\n", gd->baudrate, div,
	       c.lx_khz * 1000 / (16 * max(div, 1U)));
	khz("mem", c.mem_khz);
	printf(" (DDR%u-%u; 25 MHz x (%u + 2) / 2 / %u)\n", F(R(0xb8001000), 31, 28) + 1,
	       2 * c.mem_khz / 1000, F(R(0xb8000240), 31, 24), 1 << F(R(0xb800023c), 15, 14));
	ddr(c.mem_khz);
	return 0;
}

U_BOOT_CMD(clocks, 24, 0, do_clocks, "show CPU/LX/SPI/MEM clocks and DDR3 timings; set CPU/MEM PLL",
	   "\n  rates decoded from the PLL registers; docs/CLOCKS.md\n"
	   "clocks fast  - CPU 1000 MHz, DDR 650 MHz, tREFI 7.1 us, DRAM controller prefetch (SPI left alone)\n"
	   "clocks set cpu <e208> <e210> [relock 0|1] force\n"
	   "  - CPU PLL from SRAM (stock sequence); relock 0 = e200 bit 30 (default), 1 = e220 bit 17\n"
	   "clocks set lx <code 2..5> force  - LX = 2450 / (2 x (code + 2)) MHz; 5 = stock 175\n"
	   "clocks set mem <MHz> [nosr] force\n"
	   "  - DDR3 clock to a bin (800..675 step 25: CL 11 CWL 8 via MRS, nosr only; 650 600 550 ...),\n"
	   "    DRAM kept: self-refresh (nosr: refresh off), MEM PLL, DTRs [, MRS + DLL reset], from\n"
	   "    SRAM; reverts if a canary reads back wrong\n"
	   "  experiment options (before force): probe (always revert, report canary), cl11\n"
	   "    (CL 11 / CWL 8 / WR 12 at this clock), dtr0 <hex>, mpcr <m0> <m1> <m2>,\n"
	   "    dqshift <n> (all 32 DQ read taps + n),\n"
	   "    reg <PHY addr> <val> (up to 4; DIDER/DDPDR, DACCR..DWDQSOR; written with clk_oe = 0)");

/* Kernel DTB gets the live rates: OpenWrt rtl930x.dtsi uses fixed clocks + /cpus/frequency */
static void fdt_set_rate(void *blob, const char *path, const char *prop, u32 hz)
{
	int off = fdt_path_offset(blob, path);

	if (off >= 0 && fdt_getprop(blob, off, prop, NULL))
		fdt_setprop_u32(blob, off, prop, hz);
}

int ft_board_setup(void *blob, struct bd_info *bd)
{
	struct otto_clocks c;
	int off;

	otto_clocks_read(&c);
	fdt_set_rate(blob, "/cpus", "frequency", c.cpu_khz * 1000);	/* CP0 timer = this / 2 */
	fdt_set_rate(blob, "/cpu-clock", "clock-frequency", c.cpu_khz * 1000);
	fdt_set_rate(blob, "/lx_clk", "clock-frequency", c.lx_khz * 1000);
	fdt_for_each_node_by_compatible(off, blob, -1, "ns16550a")
		if (fdt_getprop(blob, off, "clock-frequency", NULL))
			fdt_setprop_u32(blob, off, "clock-frequency", c.lx_khz * 1000);
	printf("fdt: clocks cpu %u kHz, lx %u kHz\n", c.cpu_khz, c.lx_khz);
	return 0;
}
