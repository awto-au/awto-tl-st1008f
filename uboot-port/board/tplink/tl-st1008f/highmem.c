// SPDX-License-Identifier: GPL-2.0+
/*
 * RAM above 256 MiB (#32). DRAM size and zone-3 remap from OpenWrt realtek 300-02
 * (board-realtek.c, GPL-2.0): bus 0x20000000.. -> DRAM 0x10000000... U-Boot runs unmapped
 * (KSEG0/1 reach only bus 0x0-0x1fffffff), so `highmem map` adds one wired TLB entry.
 */

#include <command.h>
#include <console.h>
#include <vsprintf.h>
#include <asm/io.h>
#include <asm/mipsregs.h>
#include <linux/sizes.h>

#define SOC(off)	((void __iomem *)(0xb8000000 + (off)))
#define DRAM_CONFIG	SOC(0x1004)
#define UMSAR(n)	SOC(0x1300 + 0x10 * (n))
#define SRAMSAR(n)	SOC(0x4000 + 0x10 * (n))
#define O0DOR2		SOC(0x4220)	/* zone 3 offset */
#define O0DMAR2		SOC(0x4224)	/* zone 3 max address */

#define HM_BUS		0x20000000	/* zone 3 base as the CPU/Linux sees it */
#define HM_VA		0xc0000000	/* KSEG2 window, one TLB pair of 256 MiB pages */
#define PM_256M		0x1fffe000
#define ELO_UNCACHED	((2 << 3) | BIT(2) | BIT(1) | BIT(0))	/* C=2, D, V, G */

static bool mapped;

/* DCR bank/row/col fields -> log2 size (OpenWrt realtek_get_system_memory) */
static u32 dram_size(void)
{
	u32 dcr = __raw_readl(DRAM_CONFIG);
	u32 bits = ((dcr >> 28) & 3) + ((dcr >> 24) & 3) + ((dcr >> 20) & 0xf) +
		   ((dcr >> 16) & 0xf) + 20;

	return bits > 31 ? 0 : 1u << bits;
}

static u32 high_size(void)
{
	u32 total = dram_size();

	return total > SZ_256M ? total - SZ_256M : 0;
}

static int do_info(void)
{
	int i;

	printf("DCR 0x%08x -> %u MiB (high bank %u MiB at bus 0x%08x)\n",
	       __raw_readl(DRAM_CONFIG), dram_size() >> 20, high_size() >> 20, HM_BUS);
	printf("zone3 O0DOR2 0x%08x O0DMAR2 0x%08x\n", __raw_readl(O0DOR2), __raw_readl(O0DMAR2));
	for (i = 0; i < 4; i++)
		printf("UMSAR%d 0x%08x SRAMSAR%d 0x%08x\n", i, __raw_readl(UMSAR(i)), i,
		       __raw_readl(SRAMSAR(i)));
	printf("window: %s\n", mapped ? "0xc0000000 (uncached)" : "not mapped");
	return 0;
}

static int do_map(void)
{
	u32 size = high_size(), lo1 = 0;
	int i, n = ((read_c0_config1() >> 25) & 0x3f) + 1;

	if (!size) {
		puts("highmem: DRAM <= 256 MiB, nothing to map\n");
		return 1;
	}
	for (i = 0; i < 4; i++) {
		__raw_writel(0, UMSAR(i));
		__raw_writel(0, SRAMSAR(i));
	}
	__raw_writel(0x70000000, O0DOR2);
	__raw_writel(0x7fffffff, O0DMAR2);
	__asm__ __volatile__("sync");

	/* park every entry on a unique unmapped KSEG0 VPN: stock may leave entries behind */
	for (i = 0; i < n; i++)
		write_one_tlb(i, 0, 0x80000000 + (i << 14), 0, 0);
	if (size > SZ_256M)
		lo1 = ((HM_BUS + SZ_256M) >> 12 << 6) | ELO_UNCACHED;
	write_one_tlb(0, PM_256M, HM_VA, (HM_BUS >> 12 << 6) | ELO_UNCACHED, lo1);
	write_c0_wired(1);
	write_c0_pagemask(0);
	__asm__ __volatile__("ehb");
	mapped = true;
	printf("highmem: %u MiB at 0x%08x (uncached), %d TLB entries\n", size >> 20, HM_VA, n);
	return 0;
}

/* Writes to the high bank must not show up in the low bank (aliasing = bus not remapped) */
static int alias_check(u32 size)
{
	u32 step = SZ_16M, off, bad = 0;

	for (off = 0; off < size; off += step) {
		u32 low = __raw_readl((void __iomem *)(0xa0000000 + off + 0x100));

		__raw_writel(0x5a5a0000 | (off >> 24), (void __iomem *)(HM_VA + off + 0x100));
		if (__raw_readl((void __iomem *)(0xa0000000 + off + 0x100)) != low) {
			printf("alias: high +0x%08x changed low bank\n", off);
			bad++;
		}
	}
	for (off = 0; off < size; off += step)
		if (__raw_readl((void __iomem *)(HM_VA + off + 0x100)) != (0x5a5a0000 | (off >> 24))) {
			printf("alias: high +0x%08x marker lost\n", off);
			bad++;
		}
	printf("alias check: %s\n", bad ? "FAIL" : "ok");
	return bad;
}

/* word = address ^ pattern, two passes (pattern and ~pattern); dot per 16 MiB */
static int pattern_test(u32 size)
{
	static const u32 pat[] = { 0x00000000, 0xffffffff };
	u32 p, off, errs = 0;

	for (p = 0; p < ARRAY_SIZE(pat); p++) {
		for (off = 0; off < size; off += 4) {
			__raw_writel(off ^ pat[p], (void __iomem *)(HM_VA + off));
			if (!(off & (SZ_16M - 1)) && ctrlc())
				return -1;
		}
		for (off = 0; off < size; off += 4) {
			u32 v = __raw_readl((void __iomem *)(HM_VA + off));

			if (v != (off ^ pat[p]) && errs++ < 8)
				printf("\nmismatch +0x%08x: 0x%08x want 0x%08x\n", off, v, off ^ pat[p]);
			if (!(off & (SZ_16M - 1)))
				putc('.');
		}
	}
	printf("\npattern test %u MiB: %u errors\n", size >> 20, errs);
	return errs;
}

static int do_highmem(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	u32 size = high_size();

	if (argc < 2 || !strcmp(argv[1], "info"))
		return do_info();
	if (!strcmp(argv[1], "map"))
		return do_map() ? CMD_RET_FAILURE : 0;
	if (!strcmp(argv[1], "test")) {
		if (argc > 2)
			size = min_t(u32, size, hextoul(argv[2], NULL));
		if (!mapped && do_map())
			return CMD_RET_FAILURE;
		if (alias_check(size))
			return CMD_RET_FAILURE;
		return pattern_test(size) ? CMD_RET_FAILURE : 0;
	}
	return CMD_RET_USAGE;
}

U_BOOT_CMD(highmem, 3, 0, do_highmem, "RAM above 256 MiB (zone-3 remap + TLB window)",
	   "[info]       - DRAM size, zone registers, window\n"
	   "highmem map          - remap zone 3, map high bank at 0xc0000000 (uncached)\n"
	   "highmem test [bytes] - map, alias check, address^pattern test (default: whole bank)");
