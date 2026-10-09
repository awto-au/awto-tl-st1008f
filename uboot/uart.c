/* awto u-boot — UART0 driver. Full init from the clock, so it does NOT rely on
 * any prior (stock) configuration. 16550-style; all reg data in bits 31:24. */
#include "soc.h"
#include "uart.h"

static inline void ur_wr(uint32_t off, uint8_t v)
{
	MMIO(UART0_BASE + off) = (uint32_t)v << 24;
}
static inline uint32_t ur_rd(uint32_t off)
{
	return MMIO(UART0_BASE + off);
}

void uart_init(uint32_t lx_hz, uint32_t baud)
{
	uint32_t div = lx_hz / (baud * 16u);
	if (div)
		div -= 1u;
	ur_wr(U_LCR, 0x80);            /* DLAB = 1 */
	ur_wr(U_THR, div & 0xff);      /* DLL */
	ur_wr(U_IER, (div >> 8) & 0xff); /* DLM */
	ur_wr(U_LCR, 0x03);            /* 8N1, DLAB = 0 */
	ur_wr(U_FCR, 0xc1);            /* FIFO enable + reset */
	ur_wr(U_MCR, 0x43);
}

void uart_putc(char c)
{
	while (!(ur_rd(U_LSR) & LSR_THRE))
		;
	ur_wr(U_THR, (uint8_t)c);
}

void uart_puts(const char *s)
{
	for (; *s; s++) {
		if (*s == '\n')
			uart_putc('\r');
		uart_putc(*s);
	}
}

void uart_puthex(uint32_t v)
{
	static const char h[] = "0123456789abcdef";
	uart_puts("0x");
	for (int i = 28; i >= 0; i -= 4)
		uart_putc(h[(v >> i) & 0xf]);
}

int uart_getc(void)
{
	if (ur_rd(U_LSR) & LSR_DR)
		return (int)((ur_rd(U_THR) >> 24) & 0xff);
	return -1;
}
