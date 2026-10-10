/* RTL9303 SoC register map (MIPS32r2 BE). From static RE of the stock loader
 * (docs/UBOOT-FUNCMAP.md, docs/UBOOT-REFERENCE.md, docs/hardware.md, tmp/re/).
 * This is OUR map — no stock code is used, only the hardware register layout.
 */
#ifndef AWTO_SOC_H
#define AWTO_SOC_H
#include <stdint.h>

#define MMIO(a) (*(volatile uint32_t *)(a))

/* --- UART0 @ 0xb8002000 (KSEG1 uncached). 32-bit regs, data in bits 31:24.
 * LSR status bits sit in the top byte too (THRE=0x20000000, DR=0x01000000). */
#define UART0_BASE 0xb8002000u
#define UART1_BASE 0xb8002100u
#define U_THR 0x00 /* =RBR =DLL(when DLAB) */
#define U_IER 0x04 /* =DLM(when DLAB) */
#define U_FCR 0x08
#define U_LCR 0x0c
#define U_MCR 0x10
#define U_LSR 0x14
#define LSR_THRE 0x20000000u
#define LSR_DR   0x01000000u
/* Baud: div = lx_hz/(baud*16) - 1; LCR=0x03 (8N1), FCR=0xc1, MCR=0x43. */

/* --- GPIO block @ 0xb8003300 (RTL9300 gpio0) --- */
#define GPIO_BASE 0xb8003300u
#define GPIO_PINEN 0x00  /* pin enable (0x00ffffff for 24 pins) */
#define GPIO_DIR   0x08  /* 1 = output */
#define GPIO_DAT   0x0c  /* read = level, write = latch */
/* GPIO21 = watchdog toggle (keep output-high); 22/23 = i2c-gpio SCL/SDA to the
 * TCA9534A @0x38 (per-cage tx-disable). 17/18/19 = 3-pos mode switch (input). */

/* --- Timer @ 0xb8003200; PLLs @ 0xbb00e200 (CPU/OCP), 0xb8000234 (mem);
 * DDR3 controller @ 0xb8001000; SPI-NOR SFCR @ 0xb8001200, read window
 * 0xb4000000. Implemented as driver stages are written (see README). --- */
#define TIMER_BASE 0xb8003200u
#define DDR_BASE   0xb8001000u
#define SPIF_BASE  0xb8001200u
#define FLASH_WIN  0xb4000000u

/* LX (peripheral/UART) clock. Stock default = 175 MHz. Our clock stage will set
 * and export this; until then the UART driver uses it to program the divisor so
 * we do not depend on any prior (stock) UART setup. */
#define SOC_LX_HZ 175000000u

/* Console baud — overridable at build time (-DUART_BAUD=N). The divisor formula
 * supports any rate the LX clock allows; the host adapter/daemon must match. */
#ifndef UART_BAUD
#define UART_BAUD 115200u
#endif

#endif
