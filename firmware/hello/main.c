/* awto boot payload — minimal UART hello.
 * RTL9303 UART0 @ 0xb8002000 (KSEG1 uncached), 32-bit regs, data in bits 31:24.
 * THR +0x00, LSR +0x14 (THRE = 0x20000000). Baud already set by the SPL (115200).
 * Proves: toolchain, SPL->payload handoff at 0x81000000, and the console.
 */
#include <stdint.h>

#define UART_THR (*(volatile uint32_t *)0xb8002000u)
#define UART_LSR (*(volatile uint32_t *)0xb8002014u)
#define LSR_THRE 0x20000000u

static void uputc(char c)
{
	while (!(UART_LSR & LSR_THRE))
		;
	UART_THR = (uint32_t)(unsigned char)c << 24;
}

static void uputs(const char *s)
{
	for (; *s; s++) {
		if (*s == '\n')
			uputc('\r');
		uputc(*s);
	}
}

void main(void)
{
	uputs("\n");
	uputs("=== awto boot payload ===\n");
	uputs("hello from our code at 0x81000000\n");
	uputs("SPL->payload handoff OK; UART0 @ 0xb8002000 works.\n");
	uputs("next: ASIC init (dumb-switch) / grow into U-Boot.\n");
}
