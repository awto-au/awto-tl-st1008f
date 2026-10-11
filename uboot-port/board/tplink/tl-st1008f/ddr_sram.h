/* SPDX-License-Identifier: GPL-2.0+ */
/* Parameter block shared by `clocks set mem` (clocks.c) and the SRAM routine (ddr_sram.S). */
#ifndef __TL_ST1008F_DDR_SRAM_H
#define __TL_ST1008F_DDR_SRAM_H

/* one register set: MEM PLL MPCR0-3, DTR0-2, flags */
#define DS_MPCR0	0x00
#define DS_MPCR1	0x04
#define DS_MPCR2	0x08
#define DS_MPCR3	0x0c
#define DS_DTR0		0x10
#define DS_DTR1		0x14
#define DS_DTR2		0x18
#define DS_FLAGS	0x1c
#define  DSF_DTR_FIRST	1	/* new DTR fields >= old: apply before the clock change */
#define DS_SIZE		0x20

/* block: set at 0x00 (target), set at 0x20 (current = revert target) */
#define DP_NEW		0x00
#define DP_OLD		0x20
#define DP_METHOD	0x40	/* 0 = self-refresh (MPMR0 PM_MODE 2), 1 = refresh off (DMCR bit 24) */
#define DP_LOOPS_US	0x44	/* delay loop iterations per us (2 CPU cycles each) */
#define DP_CAN_ADDR	0x48	/* canary: KSEG1 DRAM address, words, seed (word = offset ^ seed) */
#define DP_CAN_WORDS	0x4c
#define DP_CAN_SEED	0x50
#define DP_STATUS	0x54	/* out: = v0 */
#define DP_DMCR_POLLS	0x58	/* out: polls left in the last DMCR busy wait */
#define DP_MPMR0_SR	0x5c	/* out: MPMR0 read back after the entry write */
#define DP_MPMR0_EXIT	0x60	/* out: MPMR0 read back after the exit write */
#define DP_CAN_BAD	0x64	/* out: canary mismatches at the new clock */
#define DP_CAN_OFF	0x68	/* out: first bad byte offset */
#define DP_CAN_VAL	0x6c	/* out: first bad value */
#define DP_REV_CODE	0x70	/* out: change code of the revert */
#define DP_SAVE		0x80	/* s0-s7, ra */
#define DP_SIZE		0xa4

/* v0 / DP_STATUS */
#define DST_BUSY	1	/* DMCR busy before start: nothing written */
#define DST_DTR_PRE	2	/* DTR update did not finish before the change: PLL untouched */
#define DST_REFRESH	3	/* method 1: DMCR busy after the refresh toggle */
#define DST_DTR_POST	4	/* DTR update did not finish after the change */
#define DST_CODE	0x0f
#define DST_CANARY	0x10	/* canary mismatch at the new clock: reverted to the old set */
#define DST_REV_OK	0x20	/* revert: canary good again */
#define DST_REV_BAD	0x40	/* revert: canary still bad */

#endif
