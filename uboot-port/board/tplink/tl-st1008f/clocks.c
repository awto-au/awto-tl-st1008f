// SPDX-License-Identifier: GPL-2.0+
/*
 * `clocks`: read-only decode of the PLLs and DDR3 timing registers (docs/CLOCKS.md).
 * ft_board_setup(): writes the decoded rates into the kernel DTB (no Linux clock driver needed).
 * No register is written here; clock changes are documented procedures, not commands.
 */

#include <command.h>
#include <fdt_support.h>
#include <serial.h>
#include <asm/global_data.h>
#include <asm/io.h>
#include <linux/bitfield.h>
#include <linux/kernel.h>
#include <linux/libfdt.h>
#include <mach/otto.h>

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

static void ddr(u32 mem_khz)
{
	u32 mcr = R(0xb8001000), dcr = R(0xb8001004);
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
}

static int do_clocks(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	struct otto_clocks c;
	u32 e208 = R(0xbb00e208), e210 = R(0xbb00e210), e214 = R(0xbb00e214), e220 = R(0xbb00e220);
	u32 div;

	if (argc > 1) {
		printf("clocks: read-only; change procedures are in docs/CLOCKS.md\n");
		return CMD_RET_USAGE;
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

U_BOOT_CMD(clocks, 1, 0, do_clocks, "show CPU/LX/SPI/MEM clocks and DDR3 timings (read-only)",
	   "\n  rates decoded from the PLL registers; docs/CLOCKS.md");

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
