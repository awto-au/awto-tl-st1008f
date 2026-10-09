/* awto boot payload link map. Load+run at 0x81000000 (same spot stock `boota`
 * copies images to, so code execution there is proven on this board). */
ENTRY(_start)
SECTIONS
{
	. = 0x81000000;
	.text : {
		*(.text.start)
		*(.text*)
	}
	.rodata : { *(.rodata*) }
	.data   : { *(.data*) }
	. = ALIGN(16);
	.bss    : { *(.bss*) *(COMMON) }
	_end = .;
	/DISCARD/ : { *(.MIPS.abiflags) *(.reginfo) *(.comment) *(.note*) }
}
