/* SPDX-License-Identifier: GPL-2.0-only */
/* Glue for rtl930x_sds_rxcal.c (extracted Linux RX calibration, #83). Hand-written; gen_sds_rxcal.py never touches it.
 * Includer provides before this header: u8/u16/u32, BIT, GENMASK, FIELD_GET/FIELD_PREP, abs, ENOTSUPP,
 * msleep(ms), usleep_range(min, max), printf. Doc: docs/SDS-TOOLS.md (RX calibration).
 */
#ifndef RTL930X_SDS_RXCAL_STUB_H
#define RTL930X_SDS_RXCAL_STUB_H

#include "rtl930x_sds_rxcal_defs.h"

#ifndef FIELD_MAX
#define FIELD_MAX(mask)		((mask) >> __builtin_ctzl(mask))
#endif
#ifndef max
#define max(a, b)		((a) > (b) ? (a) : (b))
#endif

/* dev_dbg is silent; dev_err goes to the console. First argument (device) is ignored. */
#define dev_dbg(dev, fmt, ...)	do { (void)(dev); } while (0)
#ifndef fallthrough
#define fallthrough		__attribute__((__fallthrough__))
#endif
#define dev_err(dev, fmt, ...)	printf("sdscal: " fmt, ##__VA_ARGS__)

struct device;
struct rtpcs_serdes;

struct rtpcs_sds_ops {
	int (*read)(struct rtpcs_serdes *sds, enum rtpcs_page page, int regnum, int bithigh, int bitlow);
	int (*write)(struct rtpcs_serdes *sds, enum rtpcs_page page, int regnum, int bithigh, int bitlow, u16 value);
	int (*write_mask)(struct rtpcs_serdes *sds, enum rtpcs_page page, int regnum, u16 mask, u16 value);
	int (*xsg_write_mask)(struct rtpcs_serdes *sds, enum rtpcs_page page, int regnum, u16 mask, u16 value);
	int (*get_xsgmii_link)(struct rtpcs_serdes *sds);
};

struct rtpcs_ctrl {
	struct device *dev;
	struct rtpcs_serdes *serdes;	/* indexed by SerDes id; only the even partner is read */
};

struct rtpcs_serdes {
	struct rtpcs_ctrl *ctrl;
	const struct rtpcs_sds_ops *ops;
	enum rtpcs_sds_mode hw_mode;
	enum rtpcs_sds_usxgmii_submode usxgmii_submode;
	enum rtpcs_sds_attachment attachment;
	u8 id;
	u8 rxcal_tries;
};

#endif
