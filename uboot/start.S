# awto u-boot — reset/early entry (MIPS32r2 BE). Our own init; no stock code.
# CP0 Status cleared, stack set, .bss zeroed, then board_main().
#
# Build targets this at two link addresses (see link-*.ld):
#   - RAM bring-up harness: 0x81000000 (load via any loader during development)
#   - (future) flash SPL:   reset vector 0xbfc00000, doing DDR/PLL itself
.set noreorder
.set noat
.section .text.start,"ax"
.globl _start
_start:
	mtc0  $zero, $12, 0          # CP0_Status = 0: kernel mode, ints off, no BEV
	mtc0  $zero, $13, 0          # CP0_Cause = 0
	lui   $sp, 0x81f0            # stack at 0x81f00000 (inside 512 MB DDR)
	ori   $sp, $sp, 0x0

	# zero .bss
	la    $t0, __bss_start
	la    $t1, __bss_end
1:	sltu  $t2, $t0, $t1
	beq   $t2, $zero, 2f
	nop
	sw    $zero, 0($t0)
	b     1b
	addiu $t0, $t0, 4
2:
	jal   board_main
	nop
hang:
	b     hang
	nop
