// SPDX-License-Identifier: GPL-2.0+
/*
 * Realtek Otto (RTL930x): minimal CPU glue for the RAM chainload (stage 0).
 * Stock U-Boot already ran clocks, DDR and caches; nothing is re-initialised.
 */

#include <init.h>
#include <vsprintf.h>
#include <asm/global_data.h>
#include <asm/mipsregs.h>
#include <linux/sizes.h>

DECLARE_GLOBAL_DATA_PTR;

/* Second 256 MiB bank is not linearly mapped; fixed size, no probing. */
int dram_init(void)
{
	gd->ram_size = SZ_256M;

	return 0;
}

int board_early_init_f(void)
{
	/* start.S leaves ERL set; clear it so the exception vectors work. */
	write_c0_status(read_c0_status() & ~ST0_ERL);

	return 0;
}

/* GPIO21 low = board reset (stock rtk.ko); deliberately not driven. */
void _machine_restart(void)
{
	puts("reset: not implemented (stage 0)\n");
}
