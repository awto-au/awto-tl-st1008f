// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk` extras with no stock equivalent: port status, mode switch, on-die temperature.
 * Registers: docs/hardware.md (mode switch, thermal), OpenWrt realtek-thermal.c (GPL-2.0).
 * Read-only except `rtk temp`, which enables the thermal meter (RMW of two bits/fields).
 */

#include <command.h>
#include <dm.h>
#include <i2c.h>
#include <linux/delay.h>
#include <vsprintf.h>
#include "rtk.h"

#define EXP_BUS		8
#define EXP_ADDR	0x38
#define MAC_LINK_STS	RTL9300_MAC_LINK_STS		/* bit per SDK port */
#define MAC_LINK_SPD(p)	RTL9300_MAC_LINK_SPD_STS((p) >> 3)	/* 4 bits per port (OpenWrt pcs-rtl-otto) */
#define LED_SW_EN(p)	RTL9300_LED_PORT_SW_EN_CTRL((p) >> 3)

#define TM_CTRL1	RTL9300_THERMAL_METER_CTRL_1	/* 31:16 SAMPLE_DLY */
#define TM_CTRL2	RTL9300_THERMAL_METER_CTRL_2	/* bit 16 TM_ENABLE */
#define TM_RESULT0	RTL9300_THERMAL_METER_RESULT_0	/* DATA_VALID 24, TEMP_OUT 22:16 (raw) */
/* raw -> 0.01 degC: Realtek SDK dal_longan_switch_thermalTemp_get (#13) */
#define TM_CENTI(raw)	((int)(raw) * 129 - 1000)
#define TM_RESULT1	RTL9300_THERMAL_METER_RESULT_1	/* 14:8 TEMP_MAX, 6:0 TEMP_MIN since enable */
#define TM_SAMPLE_DLY	0x0800	/* value OpenWrt uses: "makes get_temp succeed more often" */
/* No measured settling time yet (#13): 100 x 1 ms is a cap, expiry is logged. */
#define TM_POLL_N	100

struct sds_name { u8 mode; const char *name; };
static const struct sds_name sds_names[] = {
	{ 0x02, "SGMII" }, { 0x04, "1000BASE-X" }, { 0x05, "100BASE-X" }, { 0x06, "QSGMII" },
	{ 0x0d, "USXGMII" }, { 0x10, "XSGMII" }, { 0x16, "2500BASE-X" }, { 0x1a, "10GBASE-R" },
	{ 0x1f, "off" },
};

static const char *sds_mode_name(int mode)
{
	int i;

	for (i = 0; i < ARRAY_SIZE(sds_names); i++)
		if (sds_names[i].mode == mode)
			return sds_names[i].name;
	return "?";
}

/* cage line: presence, module PN, laser, SerDes mode/signal, MAC link, LED owner */
static void port_line(int cage, const u8 *exp)
{
	int port = rtk_cage_port[cage - 1], sds = rtk_cage_sds(cage), mode;
	bool pres = !(__raw_readl((void __iomem *)GPIO_DAT) & BIT(cage - 1));
	static const char *const spd_name[16] = { "10M", "100M", "1G", "10G", "10G", "2.5G", "5G",
						  [7 ... 15] = "?" };
	struct udevice *dev;
	const char *why;
	u16 sig;
	char pn[17] = "";
	int i, itf;
	u32 lnk;

	printf("cage %d (port %d, sds %d): ", cage, port, sds);
	if (!pres) {
		printf("empty");
	} else {
		dev = rtk_chip(cage - 1, 0x50);
		if (dev && !dm_i2c_read(dev, 40, (u8 *)pn, 16)) {
			for (i = 15; i >= 0 && (pn[i] == ' ' || !pn[i]); i--)
				pn[i] = 0;
			printf("%s", pn);
		} else {
			printf("module (EEPROM unreadable)");
		}
	}
	if (exp)
		printf(", laser %s", !(exp[1] & BIT(cage - 1)) && !(exp[3] & BIT(cage - 1)) ?
		       "ON" : "off");
	mode = rtk_sds_mode(sds);
	printf(", sds %s (0x%02x)", sds_mode_name(mode), mode);
	/* PCS link, latched low: 10GR page 5 reg 0 bit 12; else 1G block BMSR (page 2, sds 3 -> 10) */
	if (mode == 0x1a ? !rtk_sds_read(sds, 5, 0, &sig) && !rtk_sds_read(sds, 5, 0, &sig) :
	    !rtk_sds_read(sds == 3 ? 10 : sds, 2, 1, &sig) && !rtk_sds_read(sds == 3 ? 10 : sds, 2, 1, &sig))
		printf(", pcs %s", sig & (mode == 0x1a ? 0x1000 : 0x4) ? "up" : "down");
	sw_r(MAC_LINK_STS);	/* latched low (OpenWrt reads twice): second read = now */
	lnk = sw_r(MAC_LINK_STS) & BIT(port);
	printf(", mac %s", lnk ? "up" : "down");
	if (lnk)
		printf(" %s", spd_name[(sw_r(MAC_LINK_SPD(port)) >> ((port & 7) * 4)) & 0xf]);
	printf(", media %s", rtk_media_name(port));
	itf = pres ? rtk_sfp_iface(cage, &why) : -1;
	if (itf >= 0)
		printf(", sfp->%s", rtk_if_name[itf]);
	printf(", led %s\n", (sw_r(LED_SW_EN(port)) >> ((port & 7) * 4)) & 0xf ? "sw" : "hw");
}

int rtk_port_status(int argc, char *const argv[])
{
	struct udevice *dev = rtk_chip(EXP_BUS, EXP_ADDR);
	u8 exp[4] = { 0 };
	bool have = dev && !dm_i2c_read(dev, 1, &exp[1], 1) && !dm_i2c_read(dev, 3, &exp[3], 1);
	int c;

	if (argc > 3 || (argc == 3 && strcmp(argv[2], "status")))
		return CMD_RET_USAGE;
	for (c = 1; c <= NCAGES; c++)
		port_line(c, have ? exp : NULL);
	if (!have)
		printf("laser expander not responding\n");
	rtk_sfp_power_sum(false);
	return 0;
}

int rtk_mode(int argc, char *const argv[])
{
	static const char *const name[] = { "M1, 1G mode", "M2, split: cages 1-4 1G, 5-8 2.5G",
					    "M3, 2.5G mode" };
	u32 v = (__raw_readl((void __iomem *)GPIO_DAT) >> 17) & 7;	/* pins 17,18,19; active low */
	int pat = v == 6 ? 1 : v == 5 ? 2 : 3;	/* (p17,p18,p19) = 0/1/1, 1/0/1, else (stock decode) */

	printf("mode: pins 17/18/19 = %u/%u/%u -> pattern %d (%s)\n", v & 1, (v >> 1) & 1,
	       (v >> 2) & 1, pat, name[pat - 1]);
	pat = st1008f_boot_mode(NULL);
	printf("boot policy: %sM%d %s (pins 18/19; #46)\n", pat ? "" : "invalid -> ", pat ? pat : 1,
	       st1008f_mode_name(pat ? pat : 1));
	return 0;
}

int rtk_temp(int argc, char *const argv[])
{
	u32 r;
	int i;

	if (!(sw_r(TM_CTRL2) & BIT(16))) {
		sw_rmw(TM_CTRL1, 0xffff0000, TM_SAMPLE_DLY << 16);
		sw_rmw(TM_CTRL2, BIT(16), BIT(16));
		printf("thermal meter was off: enabled\n");
	}
	for (i = 0; i < TM_POLL_N; i++) {
		r = sw_r(TM_RESULT0);
		if (r & BIT(24))
			break;
		mdelay(1);
	}
	if (i == TM_POLL_N) {
		printf("temp: no valid sample after %d ms\n", TM_POLL_N);
		return CMD_RET_FAILURE;
	}
	{
		int t = TM_CENTI((r >> 16) & 0xff);
		int lo = TM_CENTI(sw_r(TM_RESULT1) & 0x7f), hi = TM_CENTI((sw_r(TM_RESULT1) >> 8) & 0x7f);

		printf("temp: %d.%d C (raw %u; since enable: min %d, max %d C)\n", t / 100, (t % 100) / 10,
		       (r >> 16) & 0xff, lo / 100, hi / 100);
	}
	return 0;
}

int rtk_ours_help(void)
{
	printf("rtk commands not on the stock loader:\n"
	       "  rtk laser [status|<cage>|none|all force]   TX enable (one cage by default)\n"
	       "  rtk sfp [cage [raw|brief|mode]]            module EEPROM/DDM decode, Linux interface\n"
	       "  rtk sfp power                              declared power per cage, total vs budget\n"
	       "  rtk sfp <cage> phy [reg]                   copper module PHY (0x56) registers\n"
	       "  rtk port [status]                          per cage: module, laser, SerDes, link, LED\n"
	       "  rtk sdsdump [sds|all]                      SerDes register dump (reg_diff.py)\n"
	       "  rtk sds status|errcnt|prbs|loopback|eye|txeye  SerDes test tools (#74)\n"
	       "  rtk led [show|snake|set|all|hw|clear|error] port LEDs (3x8 matrix), error latch\n"
	       "  rtk mode                                   M1/M2/M3 switch position\n"
	       "  rtk temp                                   on-die temperature (enables the meter)\n"
	       "  rtk crypto probe|test|bench                SoC crypto engine (#62)\n"
	       "  rtk linkcheck [noprobe]                    live links + cage loops before bridging (#97)\n"
	       "  rtk spg status|load|start|stop [off]       packet generator, capped bursts (#70)\n");
	return 0;
}
