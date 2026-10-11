/* SPDX-License-Identifier: GPL-2.0+ */
/* Parameter block shared by `clocks set mem` (clocks.c) and the SRAM routine (ddr_sram.S). */
#ifndef __TL_ST1008F_DDR_SRAM_H
#define __TL_ST1008F_DDR_SRAM_H

/* one register set: MEM PLL MPCR0-3, DTR0-2, flags, MRS words */
#define DS_MPCR0	0x00
#define DS_MPCR1	0x04
#define DS_MPCR2	0x08
#define DS_MPCR3	0x0c
#define DS_DTR0		0x10
#define DS_DTR1		0x14
#define DS_DTR2		0x18
#define DS_FLAGS	0x1c
#define  DSF_DTR_FIRST	1	/* new DTR fields >= old: apply before the clock change */
#define  DSF_MRS	2	/* after the PLL, refresh still off: DTRs, MR2, MR0 + DLL reset, MR3 */
#define DS_MR0		0x20	/* DMCR word: MR_MODE_EN | MR0 data (no DLL reset bit) */
#define DS_MR2		0x24	/* DMCR word: MR_MODE_EN | 2 << 16 | MR2 data */
#define DS_DLLK_US	0x28	/* wait after the DLL reset: tDLLK 512 clk x 1.25 at this set's clock */
#define DS_NREG		0x2c	/* PHY register overrides, written while clk_oe = 0 (0..DS_REG_MAX) */
#define DS_REG		0x30	/* pairs: KSEG1 address, value */
#define  DS_REG_MAX	36	/* 32 = DACDQ RR/FR for `dqshift` + CLI `reg` entries */
#define DS_SIZE		(DS_REG + 8 * DS_REG_MAX)

/* block: target set, current set (= revert target), then scalars */
#define DP_NEW		0x00
#define DP_OLD		DS_SIZE
#define DP_B		(2 * DS_SIZE)
#define DP_METHOD	(DP_B + 0x00)	/* 0 = self-refresh (MPMR0 PM_MODE 2), 1 = refresh off (DMCR 24) */
#define DP_LOOPS_US	(DP_B + 0x04)	/* delay loop iterations per us (2 CPU cycles each) */
#define DP_CAN_ADDR	(DP_B + 0x08)	/* canary: KSEG1 address, words, seed (word = offset ^ seed) */
#define DP_CAN_WORDS	(DP_B + 0x0c)
#define DP_CAN_SEED	(DP_B + 0x10)
#define DP_STATUS	(DP_B + 0x14)	/* out: = v0 */
#define DP_DMCR_POLLS	(DP_B + 0x18)	/* out: polls left in the last DMCR busy wait */
#define DP_MPMR0_SR	(DP_B + 0x1c)	/* out: MPMR0 read back after the entry write */
#define DP_MPMR0_EXIT	(DP_B + 0x20)	/* out: MPMR0 read back after the exit write */
#define DP_CAN_BAD	(DP_B + 0x24)	/* out: canary mismatches at the new clock */
#define DP_CAN_OFF	(DP_B + 0x28)	/* out: first bad byte offset */
#define DP_CAN_VAL	(DP_B + 0x2c)	/* out: first bad value */
#define DP_REV_CODE	(DP_B + 0x30)	/* out: change code of the revert */
#define DP_PROBE	(DP_B + 0x34)	/* in: 1 = revert after the canary even when it is good */
#define DP_CAN_XOR	(DP_B + 0x38)	/* out: OR of (read ^ expected) over the canary at the new clock */
#define DP_SAVE		(DP_B + 0x40)	/* s0-s7, ra */
#define DP_SIZE		(DP_SAVE + 0x24)

/* v0 / DP_STATUS */
#define DST_BUSY	1	/* DMCR busy before start: nothing written */
#define DST_DTR_PRE	2	/* DTR update did not finish before the change: PLL untouched */
#define DST_REFRESH	3	/* method 1: DMCR busy after the refresh toggle */
#define DST_DTR_POST	4	/* DTR update did not finish after the change */
#define DST_MRS		5	/* DMCR busy after a DTR latch / MRS in the DSF_MRS block */
#define DST_CODE	0x0f
#define DST_CANARY	0x10	/* canary mismatch at the new clock: reverted to the old set */
#define DST_REV_OK	0x20	/* revert: canary good again */
#define DST_REV_BAD	0x40	/* revert: canary still bad */
#define DST_PROBE	0x80	/* probe: canary good at the new clock, reverted anyway */

#endif
