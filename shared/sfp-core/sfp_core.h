/* SPDX-License-Identifier: GPL-2.0-only */
/*
 * sfp_core: chip-independent SFP module logic for U-Boot ports (awto-sfp-core).
 *
 * Pure functions on an EEPROM buffer: no I/O, no allocation, no libc beyond memcmp/strlen.
 * Every function takes (buf, len): bytes beyond len read as 0 ("not declared"), so a short read
 * (e.g. A0h bytes 0-11) works and a full A0h page (0-95) gives the full decode.
 * Origin: decode rules follow Linux drivers/net/phy/sfp.c / sfp-bus.c (GPL-2.0); st1008f rtk_sfpmode.c.
 */
#ifndef SFP_CORE_H
#define SFP_CORE_H

#include <stddef.h>

typedef unsigned char sfp_u8;

/* SerDes interface a module can run; the consumer says which of these its chip supports. */
enum sfp_if { SFP_IF_NA, SFP_IF_100BX, SFP_IF_1000BX, SFP_IF_SGMII, SFP_IF_2500BX, SFP_IF_10GR };
#define SFP_IFBIT(i) (1u << (i))

/* Repair space-padded binary fields (e.g. Cisco GLC-SX-MM pads bytes 3-19, 37-39, 64-65 with 0x20).
 * Returns 1 if the buffer was padded and has been fixed in place, 0 if left alone. Needs len >= 11. */
int sfp_unpad(sfp_u8 *id, size_t len);

/* Linux sfp_quirks[] fixups that rewrite the ID before classification (sfp_fixup_fs_10gt, sfp_fixup_rollball_cc):
 * FS "SFP-10G-T" claims SR but is RJ45 10GBASE-T (connector 0x22, ecc 0x1c); OEM "SFP-10G-T" has a zero ecc (set 0x16).
 * Call on a copy, after sfp_unpad, before the classify/power calls. Returns 1 if bytes were changed. Needs len >= 56. */
int sfp_fixup(sfp_u8 *id, size_t len);

/* SFF-8472 checksums: 1 = ok, 0 = wrong, -1 = not enough bytes (CC_BASE needs 64, CC_EXT needs 96). */
int sfp_cc_base_ok(const sfp_u8 *id, size_t len);
int sfp_cc_ext_ok(const sfp_u8 *id, size_t len);

/* Name of the first compliance code set in bytes 3-10, NULL if none ("10GBASE-SR", "SFP+ DAC (passive)", ...). */
const char *sfp_media_name(const sfp_u8 *id, size_t len);

/* Interfaces the module can run, as a mask of SFP_IFBIT(): Linux sfp_module_parse_support().
 * *phy = module carries a PHY (1000BASE-T, 10GBASE-T, 2.5GBASE-T): SGMII is then usable. */
unsigned int sfp_support_mask(const sfp_u8 *id, size_t len, int *phy);

/* Apply the vendor+PN quirk table (Linux sfp_quirks[] .support hooks); *why = "quirk" if one matched. */
unsigned int sfp_quirk_mask(const sfp_u8 *id, size_t len, unsigned int mask, const char **why);

/* Best interface: first of 10GR, 2500BX, SGMII, 1000BX, 100BX that is in `mask` and in `chip_supported`
 * (SGMII only if phy). Returns an enum sfp_if, SFP_IF_NA if none. */
int sfp_pick_if(unsigned int mask, unsigned int chip_supported, int phy);

/* Power the module draws, mW: declared level (A0h byte 64) or the copper table for BASE-T modules,
 * whichever is larger. *why = "declared" or "copper table". */
int sfp_power_mw(const sfp_u8 *id, size_t len, const char **why);

/* Copy a space-padded ASCII field (vendor 20-35, PN 40-55, rev 56-59, SN 68-83, date 84-91) into out[n+1],
 * trailing spaces and NULs trimmed, non-printable bytes as '?'. Returns the length. */
size_t sfp_field(const sfp_u8 *id, size_t len, size_t off, size_t n, char *out);

#endif
