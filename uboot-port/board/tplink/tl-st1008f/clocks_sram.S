/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * CPU PLL change, copied to SRAM and I-cache locked by `clocks set cpu` (docs/CLOCKS.md (a)).
 * Position independent: absolute I/O addresses, local branches only, no stack.
 * a0 = 0xbb00e208 value, a1 = 0xbb00e210 value, a2 = relock: 0 = e200 bit 30, 1 = e220 bit 17,
 * a3 = 0xb80040f8 value for the new rate (written once the CPU is back on the PLL)
 * v0 = lock-poll iterations left; 0 = no lock: CPU left on the alternate clock (not the PLL)
 */
#include <asm/regdef.h>

	.set	noreorder
	.text
	.globl	otto_cpu_pll_sram
	.globl	otto_cpu_pll_sram_end
otto_cpu_pll_sram:
	mfc0	t8, $16, 7		/* Config7: branch/return prediction off (stock, OpenWrt 839x) */
	ori	t0, t8, 0xc
	mtc0	t0, $16, 7
	ehb
	lui	t1, 0xb800		/* SSR 0xb8000044 bit 2 = 0: CPU to the alternate clock */
	lw	t0, 0x44(t1)
	li	t2, ~4
	and	t0, t0, t2
	sw	t0, 0x44(t1)
	sync
	lui	t3, 0xbb00
	ori	t3, t3, 0xe200
	sw	a0, 0x08(t3)		/* NCODE first: DIVN2 first could briefly select a higher rate */
	sync
	sw	a1, 0x10(t3)
	sync
	bnez	a2, 1f
	 nop
	lui	t2, 0x4000		/* e200 bit 30 */
	b	2f
	 addiu	t4, t3, 0x00
1:	lui	t2, 0x0002		/* e220 bit 17 */
	addiu	t4, t3, 0x20
2:	lw	t0, 0(t4)		/* relock trigger 0 -> 1 */
	nor	t5, t2, zero
	and	t0, t0, t5
	sw	t0, 0(t4)
	sync
	or	t0, t0, t2
	sw	t0, 0(t4)
	sync
	li	v0, 100000		/* lock poll bound; PLL lock is tens of us (SPEC), expiry -> v0 = 0 */
3:	lw	t0, 0(t3)		/* e200 bit 15 CPU_PLL_READY */
	andi	t0, t0, 0x8000
	bnez	t0, 4f
	 nop
	addiu	v0, v0, -1
	bnez	v0, 3b
	 nop
	b	6f			/* no lock: stay on the alternate clock */
	 nop
4:	lw	t0, 0x44(t1)		/* SSR bit 2 = 1: CPU back on the PLL */
	ori	t0, t0, 4
	sw	t0, 0x44(t1)
	sync
	sw	a3, 0x40f8(t1)		/* CPU/2 class register, as stock after a CPU change (#101) */
	sync
	li	t0, 10000		/* stock settle spin */
5:	addiu	t0, t0, -1
	bnez	t0, 5b
	 nop
6:	mtc0	t8, $16, 7
	ehb
	jr	ra
	 nop
otto_cpu_pll_sram_end:
