// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk dss`: die speed sensor (SDK preloader dss.c dss_test(); sequence proven on sw2 from Linux,
 * scripts/dss_probe.py, #68 #38 #151). Read-only apart from the sensor's own CTRL words, always zeroed after.
 * CTRL: data_in[25:6] wire_sel[5] ro_sel[4:2] dss_en[1] dss_rst_n[0]. DATA: ready[30], count_out[19:0].
 */

#include <command.h>
#include <asm/io.h>
#include <vsprintf.h>
#include "rtk.h"

#define DSS0_CTRL	0xb8000250
#define DSS1_CTRL	0xb800025c
#define DSS0_DATA	0xb8000260
#define DSS1_DATA	0xb8000268
#define DSS_READY	BIT(30)
#define DSS_POLL_N	4096	/* SDK bound (0x1000 reads); sw2 Linux needed tens of reads */

static inline u32 rd(ulong a)
{
	return __raw_readl((void __iomem *)a);
}

static inline void wr(ulong a, u32 v)
{
	__raw_writel(v, (void __iomem *)a);
}

int rtk_dss(int argc, char *const argv[])
{
	u32 ctrl, d0, d1;
	int ws, ro, n, bad = 0;

	printf("dss: wire ro  polls  count0  count1   (DSS0 0x%08x, DSS1 0x%08x)\n", rd(DSS0_DATA),
	       rd(DSS1_DATA));
	for (ws = 0; ws < 2; ws++) {
		for (ro = 1; ro <= 5; ro++) {
			wr(DSS1_CTRL, 0);
			wr(DSS1_CTRL, 0);
			wr(DSS1_DATA, 0);
			ctrl = 0xfffU << 6 | ws << 5 | ro << 2 | 3;
			wr(DSS0_CTRL, ctrl);
			wr(DSS1_CTRL, ctrl);
			for (n = 1; n <= DSS_POLL_N; n++)
				if (rd(DSS1_DATA) & DSS_READY)
					break;
			d0 = rd(DSS0_DATA);
			d1 = rd(DSS1_DATA);
			if (n > DSS_POLL_N) {
				printf("dss: ws %d ro %d: not ready after %d polls (DSS1 0x%08x)\n", ws, ro,
				       DSS_POLL_N, d1);
				bad++;
				continue;
			}
			printf("dss: %4d %2d %6d %7u %7u\n", ws, ro, n, d0 & 0xfffff, d1 & 0xfffff);
		}
	}
	wr(DSS0_CTRL, 0);
	wr(DSS1_CTRL, 0);
	printf("dss: done, CTRL words zeroed, %d not ready\n", bad);
	return bad ? CMD_RET_FAILURE : 0;
}
