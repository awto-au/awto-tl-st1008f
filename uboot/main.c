/* awto u-boot — board entry. Standalone; grows into the full stock replacement.
 * Current stage: own CPU init (start.S) + own UART init + banner + echo CLI.
 * Roadmap (see README): clock/DDR SPL, SPI-NOR, env, SerDes/ASIC bring-up
 * (dumb-switch mode), network + TFTP, boot. */
#include "soc.h"
#include "uart.h"

static void banner(void)
{
	uart_puts("\n\n");
	uart_puts("================================\n");
	uart_puts(" awto u-boot (standalone) v0.0\n");
	uart_puts(" RTL9303 / MIPS32r2 BE\n");
	uart_puts(" no stock code; own init\n");
	uart_puts("================================\n");
}

/* Minimal interactive proof: echo typed characters. Confirms RX + TX work.
 * Replaced by a real command parser in a later stage. */
static void echo_cli(void)
{
	uart_puts("awto> ");
	for (;;) {
		int c = uart_getc();
		if (c < 0)
			continue;
		if (c == '\r' || c == '\n') {
			uart_puts("\nawto> ");
			continue;
		}
		uart_putc((char)c);
	}
}

void board_main(void)
{
	uart_init(SOC_LX_HZ, UART_BAUD);
	banner();
	uart_puts("stage: main (RAM bring-up harness)\n");
	uart_puts("baud=");
	uart_puthex(UART_BAUD);
	uart_puts("\n");
	uart_puts("stack=0x81f00000  uart0=");
	uart_puthex(UART0_BASE);
	uart_puts("\n");
	echo_cli();
}
