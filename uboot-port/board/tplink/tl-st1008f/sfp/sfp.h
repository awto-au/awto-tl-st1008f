/* SPDX-License-Identifier: GPL-2.0 */
/*
 * SFF-8079 / SFF-8472 decoder, U-Boot port of ethtool (7.1, 6b7b16e) sfpid.c, sfpdiag.c,
 * sff-common.[ch], module-common.[ch]. Copyright 2010 Solarflare Communications Inc.,
 * Aurelien Guillaume 2012, Cumulus Networks 2014, ethtool contributors; GPL-2.0.
 * Port: output via printf, JSON dropped, doubles replaced by integer fixed point.
 */

#ifndef SFP_H__
#define SFP_H__

#include <linux/types.h>
#include <linux/string.h>
#include <stdio.h>
#include <vsprintf.h>
#include <linux/bitops.h>
#include <linux/kernel.h>

#define SFF_MAX_DESC_LEN	120

/* A0 (0x50) bytes 0..95 are enough for the ID decode and the DDM flags (bytes 92..93). */
void sff8079_show_all(const u8 *a0);
/* A2 (0x51) bytes 0..119; call only if A0 byte 92 bit 6 (DDM implemented) is set. */
void sff8472_show_all(const u8 *a0, const u8 *a2);

/* Shared with sfpid.c / sfpdiag.c */
#define ETH_MODULE_SFF_8472	0x2
#define ETH_MODULE_SFF_8636	0x3
#define OFFSET_TO_U16(offset)	(id[offset] << 8 | id[(offset) + 1])

#define LWARN 0
#define HWARN 1
#define LALRM 2
#define HALRM 3
#define MCURR 4

/* Calibrated readings: temp 1/256 C, vcc 0.1 mV, bias 2 uA, power 0.1 uW */
struct sff_diags {
	u8 supports_dom;
	u8 supports_alarms;
	u8 rx_power_type;	/* 0 = OMA, else average power */
	u8 calibrated_ext;
	u32 sfp_voltage[5];
	s32 sfp_temp[5];
	u32 bias_cur[5];
	u32 tx_power[5];
	u32 rx_power[5];
};

/* Parsed (and, if externally calibrated, calibrated) readings. */
void sff8472_diags(const u8 *a0, const u8 *a2, struct sff_diags *sd);
void sff_print_any_hex_field(const char *field_name, u8 value, const char *desc);
void sff8024_show_encoding(const u8 *id, int encoding_offset, int sff_type);
void module_print_any_uint(const char *fn, int value, const char *unit);
void module_print_any_bool(const char *fn, bool value, const char *str_value);
void module_print_any_array_string_entry(const char *fn, const char *value);
void module_show_value_with_unit(const u8 *id, unsigned int reg, const char *name,
				 unsigned int mult, const char *unit);
void module_show_ascii(const u8 *id, unsigned int first_reg, unsigned int last_reg,
		       const char *name);
void module_show_oui(const u8 *id, int id_offset);
void module_show_identifier(const u8 *id, int id_offset);
void module_show_connector(const u8 *id, int ctor_offset);
void sff_show_dom_mod_lvl_monitors(const struct sff_diags *sd);
void sff_show_thresholds(const struct sff_diags *sd);
void sff_print_pwr(const char *name, u32 pwr);
void sff_print_bias(const char *name, u32 bias);
void sff_print_temp(const char *name, s32 temp);
void sff_print_vcc(const char *name, u32 vcc);

#endif /* SFP_H__ */
