/* SPDX-License-Identifier: GPL-2.0+ */
/* Realtek Otto (RTL930x) register bases, KSEG1. Facts from RE: docs/hardware.md. */
#ifndef __MACH_OTTO_H
#define __MACH_OTTO_H

#define OTTO_UART0_BASE		0xb8002000
#define OTTO_TIMER_BASE		0xb8003200
#define OTTO_GPIO_BASE		0xb8003300

#define OTTO_CPU_HZ		800000000
#define OTTO_LX_HZ		175000000

#endif
