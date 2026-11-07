/* SPDX-License-Identifier: GPL-2.0+ */
/*
 * Copyright (c) 2014  TP-LINK Co., Ltd  (TP-LINK Co., Ltd R&D SMB Product Line)
 * Pattern tables from the SDK U-Boot 2011.12 dt_bus.c / dt_mtest.c (owner decision 2026-11-07,
 * docs/DECISIONS.md). Used by cmd_dt.c.
 */
#ifndef ST1008F_DT_PATTERNS_H
#define ST1008F_DT_PATTERNS_H

/* dt_bus.c dram_32bit_databus_patterns */
static const u32 dt_databus_pat[] = {
	0xFFFFFFFF, 0x00000000, 0xAAAAAAAA, 0x55555555,
	0xCCCCCCCC, 0x33333333, 0xDDDDDDDD, 0x22222222,
};

/* dt_bus.c dram_databus_walks_pattern */
static const u32 dt_walk_mask[] = { 0x00000001, 0x00000003, 0x00000007 };

/* dt_bus.c dram_addrbus_patterns == dt_mtest.c dram_mtest_patterns */
static const u32 dt_pat20[] = {
	0x00000000, 0xffffffff, 0x55555555, 0xaaaaaaaa, 0x01234567,
	0x76543210, 0x89abcdef, 0xfedcba98, 0xA5A5A5A5, 0x5A5A5A5A,
	0xF0F0F0F0, 0x0F0F0F0F, 0xFF00FF00, 0x00FF00FF, 0x0000FFFF,
	0xFFFF0000, 0x00FFFF00, 0xFF0000FF, 0x5A5AA5A5, 0xA5A55A5A,
};

/* dt_mtest.c dram_mtest_alt bitpattern */
static const u32 dt_bitpat[] = {
	0x00000001, 0x00000003, 0x00000007, 0x0000000F,
	0x00000005, 0x00000015, 0x00000055, 0xaaaaaaaa,
};

#endif
