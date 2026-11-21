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

/* ---- DDM / DOM scaling (sfp_ddm.c; origin ethtool sfpdiag.c, GPL-2.0) ---- */

/* Array index for the live value and the four thresholds. */
#define SFP_DDM_LWARN	0
#define SFP_DDM_HWARN	1
#define SFP_DDM_LALRM	2
#define SFP_DDM_HALRM	3
#define SFP_DDM_CURR	4
#define SFP_DDM_A2_LEN	120	/* A2h bytes 0-119 are read */

/* Calibrated readings (internal calibration: as the module reports, external: slope/offset/polynomial applied).
 * Units: temp 1/256 C, vcc 0.1 mV, bias 2 uA, powers 0.1 uW. */
struct sfp_ddm {
	sfp_u8 supports_dom, supports_alarms;
	sfp_u8 rx_power_type;		/* 0 = OMA, else average power */
	sfp_u8 calibrated_ext;
	unsigned int vcc[5];
	int temp[5];
	unsigned int bias[5], tx_power[5], rx_power[5];
};

/* a0 needs bytes 0-93 (DOM flags 92-93), a2 bytes 0-119. Returns 1 if the module implements DDM and `d` is
 * filled, 0 if not (d->supports_dom tells "module has none" from "a2 too short", and the rest is zero). */
int sfp_ddm_decode(const sfp_u8 *a0, size_t a0_len, const sfp_u8 *a2, size_t a2_len, struct sfp_ddm *d);

/* Soft TX_DISABLE (A2h byte 110 bit 6, SFF-8472 status/control): Linux sfp.c can leave it set across a warm
 * reboot (UNVR #345), which keeps the laser dark. Pure helpers; the backend does the I2C access
 * (read A2h 110, and if sfp_soft_tx_disable_value() differs, write it back; a missing A2h is a normal result). */
#define SFP_A2_STATUS_CTRL	110
#define SFP_A2_SOFT_TX_DISABLE	0x40
int sfp_soft_tx_disable_set(sfp_u8 a2_110);	/* 1 if the soft TX_DISABLE bit is set */
sfp_u8 sfp_soft_tx_disable_value(sfp_u8 a2_110);	/* the byte to write: bit 6 cleared, nothing else changed */

/* ---- Copper-module PHY (sfp_phy.c) ---- */

#define SFP_E_IO	5	/* returned negated */
#define SFP_E_TIMEOUT	110

enum sfp_phy_id { SFP_PHY_NONE, SFP_PHY_OTHER, SFP_PHY_88E1111, SFP_PHY_AQR113C };

/* Backend access to the module PHY: 16-bit clause-22 registers, return 0 on success. The backend owns bus
 * retries and byte order; delay_ms is a plain wait. */
struct sfp_phy_ops {
	int (*rd)(void *ctx, int reg, unsigned short *v);
	int (*wr)(void *ctx, int reg, unsigned short v);
	void (*delay_ms)(void *ctx, unsigned int ms);
	void *ctx;
};

/* Read the PHY ID registers (re-aligns a byte-pointer-off-by-one ID1 read). SFP_PHY_NONE if nothing answers. */
enum sfp_phy_id sfp_phy_identify(const struct sfp_phy_ops *o);
const char *sfp_phy_name(enum sfp_phy_id id);

/* Run the SGMII init table for `id`. Returns 1 if done, 0 if there is nothing to do for this PHY (none, other,
 * or a firmware-managed AQR113C), -SFP_E_IO on a register access failure, -SFP_E_TIMEOUT if the soft reset
 * does not clear in 600 ms. */
int sfp_phy_init(const struct sfp_phy_ops *o, enum sfp_phy_id id);

#endif
