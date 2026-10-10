// SPDX-License-Identifier: GPL-2.0+
/*
 * Realtek Otto (RTL930x): minimal CPU glue for the RAM chainload (stage 0).
 * Stock U-Boot already ran clocks, DDR and caches; nothing is re-initialised.
 */

#include <init.h>
#include <time.h>
#include <vsprintf.h>
#include <asm/io.h>
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

/* Chip reset = switch-core 0x1b00000c write 1 (Linux rtl930x.dtsi syscon-reboot).
 * GPIO21 (external supervisor) is not used. Reset takes effect within ~1 us; if the
 * core is still running after 100 ms something is wrong: say so and return. */
#define OTTO_RST_GLB_CTRL	((void __iomem *)0xbb00000c)

void _machine_restart(void)
{
	ulong t0;

	puts("resetting (switch-core RST_GLB_CTRL)...\n");
	__raw_writel(1, OTTO_RST_GLB_CTRL);	/* native word, as the GPIO/I2C drivers */
	t0 = get_timer(0);
	while (get_timer(t0) < 100)
		;
	puts("reset: chip still running after 100 ms\n");
}
