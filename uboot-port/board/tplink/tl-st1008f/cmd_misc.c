// SPDX-License-Identifier: GPL-2.0+
/*
 * `flshow`: stock flash partition table, printed from docs/stock-flash-layout.json (read-only,
 * no flash access). Stock text from artifacts/uboot-flshow.txt; ours adds the A/B split of the
 * two RUNTIME slots (docs/DEFAULT-BOOT.md#ab-slots).
 */

#include <command.h>
#include <vsprintf.h>

static const struct {
	const char *name;
	u32 size, start;
} part[] = {
	{ "LOADER",    0xe0000,  0x000000 }, { "BDINFO",    0x10000,  0x0e0000 },
	{ "SYSINFO",   0x10000,  0x0f0000 }, { "JFFS2_CFG", 0x100000, 0x100000 },
	{ "JFFS2_LOG", 0x100000, 0x200000 }, { "RUNTIME1",  0xe80000, 0x300000 },
	{ "RUNTIME2",  0xe80000, 0x1180000 },
};

static int do_flshow(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	int i;

	printf("=============== FLASH Partition Layout ===============\n"
	       "Index  Name       Size       Address\n"
	       "------------------------------------------------------\n");
	for (i = 0; i < ARRAY_SIZE(part); i++)
		printf(" %d     %-10s 0x%-8x 0x%08x-0x%08x\n", i, part[i].name, part[i].size,
		       0xb4000000 + part[i].start, 0xb4000000 + part[i].start + part[i].size - 1);
	printf("======================================================\n"
	       "(table only, flash not read; LOADER 0x0-0xdffff is never written by this U-Boot)\n");
	return 0;
}

U_BOOT_CMD(flshow, 1, 1, do_flshow, "show the stock flash partition layout", "");
