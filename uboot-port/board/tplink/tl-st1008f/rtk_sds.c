// SPDX-License-Identifier: GPL-2.0+
/*
 * RTL930x SerDes indirect access (CMD 0x03b0, DATA 0x03b4) and SDS_MODE_SEL fields.
 * Layout from OpenWrt realtek mdio-realtek-otto-serdes.c / pcs-rtl-otto.c (GPL-2.0).
 */

#include <command.h>
#include <dm.h>
#include <linux/delay.h>
#include <linux/errno.h>
#include "rtk.h"

#define SDS_CMD		0x03b0
#define SDS_DATA	0x03b4
#define CMD_BUSY	BIT(0)
#define CMD_WRITE	BIT(1)
#define NSDS		12
#define NPAGES		64
/* Busy clears in tens of microseconds (OpenWrt polls at 30 us); 100 x 10 us = 1 ms cap. */
#define POLL_US		10
#define POLL_N		100

static int sds_io(unsigned int sds, unsigned int page, unsigned int reg, u32 op)
{
	int i;

	if (sds >= NSDS || page >= NPAGES || reg >= 32)
		return -EINVAL;
	sw_w(SDS_CMD, sds << 2 | page << 7 | reg << 13 | CMD_BUSY | op);
	for (i = 0; i < POLL_N; i++) {
		if (!(sw_r(SDS_CMD) & CMD_BUSY))
			return 0;
		udelay(POLL_US);
	}
	printf("rtk: SerDes %u page %u reg %u busy after %d us\n", sds, page, reg,
	       POLL_N * POLL_US);
	return -ETIMEDOUT;
}

int rtk_sds_read(unsigned int sds, unsigned int page, unsigned int reg, u16 *val)
{
	int ret = sds_io(sds, page, reg, 0);

	if (!ret)
		*val = sw_r(SDS_DATA) & 0xffff;
	return ret;
}

int rtk_sds_write(unsigned int sds, unsigned int page, unsigned int reg, u16 val)
{
	sw_w(SDS_DATA, val);
	return sds_io(sds, page, reg, CMD_WRITE);
}

int rtk_sds_mode(unsigned int sds)
{
	static const struct { u16 reg; u8 shift; } f[NSDS] = {
		{ 0x194, 0 }, { 0x194, 6 }, { 0x194, 12 }, { 0x194, 18 },
		{ 0x2a0, 0 }, { 0x2a0, 6 }, { 0x2a0, 12 }, { 0x2a0, 18 },
		{ 0x2a4, 0 }, { 0x2a4, 6 }, { 0x198, 0 }, { 0x198, 6 },
	};

	if (sds >= NSDS)
		return -1;
	return (sw_r(f[sds].reg) >> f[sds].shift) & 0x1f;
}
