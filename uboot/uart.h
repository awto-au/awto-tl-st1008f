#ifndef AWTO_UART_H
#define AWTO_UART_H
#include <stdint.h>
void uart_init(uint32_t lx_hz, uint32_t baud);
void uart_putc(char c);
void uart_puts(const char *s);
void uart_puthex(uint32_t v);
int uart_getc(void); /* -1 if no char */
#endif
