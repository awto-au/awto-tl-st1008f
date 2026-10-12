/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * MEM (DDR3) clock change, copied to SRAM and I-cache locked by `clocks set mem` (docs/CLOCKS.md (b)).
 * Position independent, no stack, no cached access: I/O via KSEG1, state in the SRAM block (ddr_sram.h).
 * a0 = KSEG1 address of the block. v0 = status (DST_*). UART marks: M S P [R] X D then C (canary ok)
 * or F; R = MRS block done (DSF_MRS sets only). Probe: C, then the revert sequence S P [R] X D.
 */
#include <asm/regdef.h>
#include "ddr_sram.h"

#define DMCR_POLL	64	/* DTR latch / MRS: tMOD 12-24 clk; poll >= 50 ns -> 3.2 us >= 1.25 x 1 us */
#define PUTC_POLL	110	/* 1 us each: one char at 115200 = 87 us x 1.25; expiry drops the char */

	.set	noreorder
	.text
	.globl	otto_ddr_sram
	.globl	otto_ddr_sram_end
otto_ddr_sram:
	sw	s0, DP_SAVE + 0x00(a0)
	sw	s1, DP_SAVE + 0x04(a0)
	sw	s2, DP_SAVE + 0x08(a0)
	sw	s3, DP_SAVE + 0x0c(a0)
	sw	s4, DP_SAVE + 0x10(a0)
	sw	s5, DP_SAVE + 0x14(a0)
	sw	s6, DP_SAVE + 0x18(a0)
	sw	s7, DP_SAVE + 0x1c(a0)
	sw	ra, DP_SAVE + 0x20(a0)
	move	s0, a0
	lw	s1, DP_LOOPS_US(s0)
	lui	s3, 0xb800		/* SoC: MEM PLL MPCR0-6 at 0x234..0x24c */
	ori	s2, s3, 0x1000		/* DDR controller */
	ori	s4, s3, 0x2000		/* UART0 */
	move	s5, zero
	mfc0	s7, $16, 7		/* Config7: branch/return prediction off (as the CPU routine) */
	ori	t0, s7, 0xc
	mtc0	t0, $16, 7
	ehb
	sync				/* drain the write buffer */
	lw	t0, DP_METHOD(s0)	/* SRAM read: no SRAM write left in flight */
	li	a1, 'M'
	bal	putc
	 nop
	addiu	s6, s0, DP_NEW
	bal	change
	 nop
	move	s5, v0
	addiu	t0, v0, -1		/* DST_BUSY / DST_DTR_PRE: clock untouched, stop here */
	sltiu	t0, t0, 2
	bnez	t0, out
	 nop
	bal	canary
	 nop
	sw	v0, DP_CAN_BAD(s0)
	sw	v1, DP_CAN_OFF(s0)
	sw	a2, DP_CAN_VAL(s0)
	sw	a3, DP_CAN_XOR(s0)
	beqz	v0, 1f
	 nop
	ori	s5, s5, DST_CANARY
	li	a1, 'F'
	bal	putc
	 nop
3:	addiu	s6, s0, DP_OLD		/* revert to the set read before the change */
	bal	change
	 nop
	sw	v0, DP_REV_CODE(s0)
	bal	canary
	 nop
	bnez	v0, 2f
	 nop
	b	out
	 ori	s5, s5, DST_REV_OK
2:	b	out
	 ori	s5, s5, DST_REV_BAD
1:	li	a1, 'C'
	bal	putc
	 nop
	lw	t0, DP_PROBE(s0)	/* probe: measure only, always go back */
	beqz	t0, out
	 nop
	b	3b
	 ori	s5, s5, DST_PROBE
out:	sw	s5, DP_STATUS(s0)
	mtc0	s7, $16, 7
	ehb
	move	v0, s5
	move	a0, s0
	lw	s0, DP_SAVE + 0x00(a0)
	lw	s1, DP_SAVE + 0x04(a0)
	lw	s2, DP_SAVE + 0x08(a0)
	lw	s3, DP_SAVE + 0x0c(a0)
	lw	s4, DP_SAVE + 0x10(a0)
	lw	s5, DP_SAVE + 0x14(a0)
	lw	s6, DP_SAVE + 0x18(a0)
	lw	s7, DP_SAVE + 0x1c(a0)
	lw	ra, DP_SAVE + 0x20(a0)
	jr	ra
	 nop

/* apply the set at s6; v0 = 0 or DST_*. Return address kept in t9 (leaves below never touch it). */
change:
	move	t9, ra
	bal	dmcr_idle
	 nop
	bnez	v0, fail_busy
	 nop
	lw	t0, DS_FLAGS(s6)
	andi	t0, t0, DSF_DTR_FIRST
	beqz	t0, 1f
	 nop
	bal	dtr_update		/* slower timings: valid at the old clock too */
	 nop
	bnez	v0, fail_pre
	 nop
1:	lw	t0, DP_METHOD(s0)
	bnez	t0, 2f
	 nop
	lw	t0, 0x40(s2)		/* MPMR0 PM_MODE 29:28 = 2: self-refresh (SPEC) */
	li	t1, 0xcfffffff
	and	t0, t0, t1
	lui	t1, 0x2000
	or	t0, t0, t1
	sw	t0, 0x40(s2)
	sync
	lw	t0, 0x40(s2)
	sw	t0, DP_MPMR0_SR(s0)
	b	3f
	 nop
2:	li	a1, 1			/* method 1: DMCR dis_dram_ref = 1 */
	bal	refresh
	 nop
	bnez	v0, fail_ref
	 nop
3:	li	a1, 1			/* SR entry settle (tCKSRE ~10 ns; 1 us = margin) */
	bal	delay
	 nop
	li	a1, 'S'
	bal	putc
	 nop
	lw	t0, 0x244(s3)		/* MEM PLL: SDK cg_mem_pll_init. MPCR4 clk_oe 5:0 = 0 */
	li	t1, ~0x3f
	and	t0, t0, t1
	sw	t0, 0x244(s3)
	sync
	li	a1, 200
	bal	delay
	 nop
	lw	t0, DS_MPCR0(s6)
	sw	t0, 0x234(s3)
	lw	t0, DS_MPCR1(s6)
	sw	t0, 0x238(s3)
	lw	t0, DS_MPCR2(s6)
	sw	t0, 0x23c(s3)
	lw	t0, DS_MPCR3(s6)
	sw	t0, 0x240(s3)
	sw	zero, 0x248(s3)		/* MPCR5/6 = 0 (SDK defaults) */
	sw	zero, 0x24c(s3)
	lw	t1, DS_NREG(s6)		/* PHY overrides while clk_oe = 0 (SDK writes DCSDCR so) */
	addiu	t2, s6, DS_REG
8:	beqz	t1, 9f
	 nop
	lw	t0, 0(t2)
	lw	t3, 4(t2)
	sw	t3, 0(t0)
	addiu	t2, t2, 8
	b	8b
	 addiu	t1, t1, -1
9:	sync
	li	a1, 5
	bal	delay
	 nop
	lw	t0, 0x244(s3)		/* clk_oe = 0x3f */
	ori	t0, t0, 0x3f
	sw	t0, 0x244(s3)
	sync
	li	a1, 200			/* SDK: no lock bit for the MEM PLL, fixed 200 us */
	bal	delay
	 nop
	li	a1, 'P'
	bal	putc
	 nop
	lw	t0, DS_FLAGS(s6)	/* CL/CWL/WR change (C allows it with method 1 only) */
	andi	t0, t0, DSF_MRS
	beqz	t0, 7f
	 nop
	bal	dtr_update		/* DTRs + latch; DMCR still holds MR3 0, refresh-off bit kept */
	 nop
	bnez	v0, fail_mrs
	 nop
	lw	t0, DS_FLAGS(s6)	/* SDK memctlc_ddr3_dll_reset: MR1 DLL off, MR1 on (MR1 0x0004) */
	andi	t0, t0, DSF_DLLZQ
	beqz	t0, 10f
	 nop
	li	a2, 0x00110005		/* MR_MODE_EN | MR1 | 0x0004 | DLL disable */
	bal	mrs
	 nop
	bnez	v0, fail_mrs
	 nop
	li	a2, 0x00110004
	bal	mrs
	 nop
	bnez	v0, fail_mrs
	 nop
10:	lw	a2, DS_MR2(s6)		/* SDK order: MR2 (CWL), then MR0 (CL, WR) with DLL reset */
	bal	mrs
	 nop
	bnez	v0, fail_mrs
	 nop
	lw	a2, DS_MR0(s6)
	bal	mrs
	 ori	a2, a2, 0x100		/* MR0 A8 = DLL reset */
	bnez	v0, fail_mrs
	 nop
	lw	a1, DS_DLLK_US(s6)	/* tDLLK before the first read (canary) */
	bal	delay
	 nop
	lui	a2, 0x0013		/* MR_MODE_EN | MR3 0 last, as the stock SPL leaves DMCR: later */
	bal	mrs			/* DMCR rewrites (DTR latch, refresh toggle) re-issue only MR3 0 */
	 nop
	bnez	v0, fail_mrs
	 nop
	lw	t0, DS_FLAGS(s6)	/* ZQCL: D3ZQCCR 0xb8001080 bit 31, busy until done (tZQoper 512 clk < 1 us) */
	andi	t0, t0, DSF_DLLZQ
	beqz	t0, 11f
	 nop
	lw	t0, 0x80(s2)
	lui	t1, 0x8000
	or	t0, t0, t1
	sw	t0, 0x80(s2)
	sync
	li	t1, DMCR_POLL		/* >= 3.2 us of polls; expiry -> DST_MRS */
12:	lw	t0, 0x80(s2)
	bgez	t0, 11f
	 nop
	addiu	t1, t1, -1
	bnez	t1, 12b
	 nop
	b	fail_mrs
	 nop
11:	li	a1, 'R'
	bal	putc
	 nop
7:	lw	t0, DP_METHOD(s0)
	bnez	t0, 4f
	 nop
	lw	t0, 0x40(s2)		/* PM_MODE = 0: exit; DRAM DLL resets itself on SR exit (JEDEC) */
	li	t1, 0xcfffffff
	and	t0, t0, t1
	sw	t0, 0x40(s2)
	sync
	lw	t0, 0x40(s2)
	sw	t0, DP_MPMR0_EXIT(s0)
	b	5f
	 nop
4:	move	a1, zero		/* method 1: refresh back on */
	bal	refresh
	 nop
	bnez	v0, fail_ref
	 nop
5:	li	a1, 10			/* tXSDLL 512 clk = 0.8 us at 650 MHz */
	bal	delay
	 nop
	lw	t0, 0x500(s2)		/* DACCR: PHY FIFO pointer clear (SDK mc_dram_phy_reset) */
	li	t1, ~0x10
	and	t0, t0, t1
	sw	t0, 0x500(s2)
	sync
	ori	t0, t0, 0x10
	sw	t0, 0x500(s2)
	sync
	ori	t0, t0, 0x20
	sw	t0, 0x500(s2)
	sync
	li	a1, 'X'
	bal	putc
	 nop
	lw	t0, DS_FLAGS(s6)
	andi	t0, t0, DSF_DTR_FIRST | DSF_MRS	/* DTRs already written */
	bnez	t0, 6f
	 nop
	bal	dtr_update		/* faster timings: only once the clock is down */
	 nop
	bnez	v0, fail_post
	 nop
6:	li	a1, 'D'
	bal	putc
	 nop
	li	a1, 20			/* >= 2 refreshes (tREFI <= 7.8 us) at the new clock, then a */
	bal	delay			/* second PHY FIFO pointer clear before the first access (#101) */
	 nop
	lw	t0, 0x500(s2)
	li	t1, ~0x10
	and	t0, t0, t1
	sw	t0, 0x500(s2)
	sync
	ori	t0, t0, 0x10
	sw	t0, 0x500(s2)
	sync
	jr	t9
	 move	v0, zero
fail_busy:
	jr	t9
	 li	v0, DST_BUSY
fail_pre:
	jr	t9
	 li	v0, DST_DTR_PRE
fail_ref:
	jr	t9
	 li	v0, DST_REFRESH
fail_post:
	jr	t9
	 li	v0, DST_DTR_POST
fail_mrs:
	jr	t9
	 li	v0, DST_MRS

/* MRS: DMCR MR_MODE_EN 20 / MR_MODE 17:16 / MR_DATA 13:0 = a2, other bits (refresh-off 24) kept.
 * Busy poll >= 1 uncached read (>= 50 ns) covers tMRD 4 clk / tMOD 12 clk (18 ns at 650 MHz) */
mrs:
	lw	t0, 0x1c(s2)
	li	t1, 0xffecc000		/* ~0x00133fff */
	and	t0, t0, t1
	or	t0, t0, a2
	sw	t0, 0x1c(s2)
	sync
	b	dmcr_idle
	 nop

/* DTR0-2 from s6, latched by rewriting DMCR (SDK memctl.c), then wait not busy */
dtr_update:
	lw	t0, DS_DTR0(s6)
	sw	t0, 0x08(s2)
	lw	t0, DS_DTR1(s6)
	sw	t0, 0x0c(s2)
	lw	t0, DS_DTR2(s6)
	sw	t0, 0x10(s2)
	sync
	lw	t0, 0x1c(s2)
	sw	t0, 0x1c(s2)
	sync
	b	dmcr_idle
	 nop

/* DMCR dis_dram_ref (bit 24) = a1 */
refresh:
	lw	t0, 0x1c(s2)
	lui	t1, 0x0100
	nor	t1, t1, zero
	and	t0, t0, t1
	sll	t1, a1, 24
	or	t0, t0, t1
	sw	t0, 0x1c(s2)
	sync
	b	dmcr_idle
	 nop

/* v0 = 0 once DMCR bit 31 (DTR_UP_BUSY/MRS_BUSY) is 0, 1 after DMCR_POLL polls */
dmcr_idle:
	move	t1, s1			/* SDK: >= 10 MEM clocks before the busy bit is valid; 1 us */
0:	bnez	t1, 0b
	 addiu	t1, t1, -1
	li	t1, DMCR_POLL
1:	lw	t0, 0x1c(s2)
	bgez	t0, 2f
	 nop
	addiu	t1, t1, -1
	bnez	t1, 1b
	 nop
	sw	t1, DP_DMCR_POLLS(s0)
	jr	ra
	 li	v0, 1
2:	sw	t1, DP_DMCR_POLLS(s0)
	jr	ra
	 move	v0, zero

/* v0 = canary mismatches; v1 = first bad offset, a2 = its value, a3 = OR of (read ^ expected) */
canary:
	lw	t0, DP_CAN_ADDR(s0)
	lw	t1, DP_CAN_WORDS(s0)
	lw	t2, DP_CAN_SEED(s0)
	move	v0, zero
	move	t3, zero
	li	v1, -1
	move	a2, zero
	move	a3, zero
1:	beqz	t1, 4f
	 nop
	lw	t4, 0(t0)
	xor	t5, t3, t2
	bne	t4, t5, 3f
	 nop
2:	addiu	t0, t0, 4
	addiu	t3, t3, 4
	b	1b
	 addiu	t1, t1, -1
3:	xor	t6, t4, t5
	or	a3, a3, t6
	bnez	v0, 2b
	 addiu	v0, v0, 1
	move	v1, t3
	b	2b
	 move	a2, t4
	/* burst pass: the same words through KSEG0, each line invalidated then refilled (8-beat
	 * line fill, as code and stack refills after the return); a wrong word adds to v0 (#101) */
4:	lw	t0, DP_CAN_ADDR(s0)
	lui	t6, 0x2000
	subu	t0, t0, t6		/* KSEG1 -> KSEG0 alias */
	lw	t1, DP_CAN_WORDS(s0)
	move	t3, zero
	move	t7, zero
5:	beqz	t1, 8f
	 nop
	andi	t6, t3, 31
	bnez	t6, 6f
	 nop
	cache	0x11, 0(t0)		/* Hit_Invalidate_D: next load refills the line */
6:	lw	t4, 0(t0)
	xor	t5, t3, t2
	beq	t4, t5, 7f
	 nop
	addiu	t7, t7, 1
	or	a3, a3, t4
7:	addiu	t0, t0, 4
	addiu	t3, t3, 4
	b	5b
	 addiu	t1, t1, -1
8:	sw	t7, DP_CAN_BURST(s0)
	jr	ra
	 addu	v0, v0, t7

/* a1 us; loop = 2 instructions >= 2 CPU cycles, so the delay is never shorter */
delay:
	mul	t0, a1, s1
1:	bnez	t0, 1b
	 addiu	t0, t0, -1
	jr	ra
	 nop

/* a1 = char to UART0 THR once LSR.THRE (bit 5) */
putc:
	li	t1, PUTC_POLL
1:	lbu	t0, 0x14(s4)
	andi	t0, t0, 0x20
	bnez	t0, 3f
	 nop
	move	t2, s1
2:	bnez	t2, 2b
	 addiu	t2, t2, -1
	addiu	t1, t1, -1
	bnez	t1, 1b
	 nop
	jr	ra
	 nop
3:	sb	a1, 0(s4)
	jr	ra
	 nop
otto_ddr_sram_end:
