/* SPDX-License-Identifier: GPL-2.0+ */
/* TP-Link TL-ST1008F v2 (RTL9303), stage 0 RAM chainload. */

#ifndef __CONFIG_TPLINK_TL_ST1008F_H__
#define __CONFIG_TPLINK_TL_ST1008F_H__

#define CFG_SYS_SDRAM_BASE	0x80000000 /* KSEG0 */
/* Init stack top 0x80f00000: below TEXT_BASE 0x81000000, above kernel load 0x80100000 */
#define CFG_SYS_INIT_SP_OFFSET	0x00f00000

#endif
