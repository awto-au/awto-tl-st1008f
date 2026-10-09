/* awto u-boot — RAM bring-up link map. Main stage at 0x81000000 (DDR; same spot
 * stock boota uses, so code exec there is known-good on this board). This is a
 * development harness only — the flash SPL/reset-vector image comes later. */
ENTRY(_start)
SECTIONS
{
	. = 0x81000000;
	.text : {
		KEEP(*(.text.start))
		*(.text*)
	}
	.rodata : { *(.rodata*) }
	.data   : { *(.data*) }
	. = ALIGN(16);
	__bss_start = .;
	.bss    : { *(.bss*) *(COMMON) }
	. = ALIGN(16);
	__bss_end = .;
	_end = .;
	/DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.comment) *(.note*) *(.pdr) }
}
