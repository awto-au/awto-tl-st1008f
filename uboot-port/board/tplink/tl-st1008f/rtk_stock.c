// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk` verbs that exist on the stock loader, done with direct register access.
 * Output text matches stock; dispatch semantics follow the Realtek SDK 3.6.x
 * uboot_cmd.c (GPL-2.0, github.com/reyalo/Realtek rtk-dms1250); LED sequence from
 * the same tree (uboot_func.c rtk_swled_*), registers from swcore_rtl9300.h.
 * Doc: docs/RTK-COMMANDS.md. Flash writers (boardid/boardmodel set) are refused.
 */

#include <command.h>
#include <dm.h>
#include <env.h>
#include <linux/delay.h>
#include <vsprintf.h>
#include "rtk.h"

#define MAX_UNIT	6	/* stock accepts unit < 6 */
#define PORT_CTRL(p)	RTL9300_MAC_L2_PORT_CTRL(p)	/* MAC_L2_PORT_CTRL, bit0 RX_EN bit1 TX_EN */
#define LED_SW_EN(p)	RTL9300_LED_PORT_SW_EN_CTRL((p) >> 3)	/* 4 bits per port */
#define LED_SW_CTRL(p)	RTL9300_LED_PORT_SW_CTRL(p)	/* 3 bits per LED: copper 0-11, fibre 12-23 */
#define LED_ON		7
#define NLED		3	/* LEDs per port (docs/hardware.md) */
#define KEY_WAIT_MS	30000	/* "press any": stock waits forever; cap so LEDs are restored */

const u8 rtk_cage_port[NCAGES] = { 0, 8, 16, 20, 24, 25, 26, 27 };

static unsigned int g_unit;

bool rtk_port_exists(unsigned int port)
{
	int i;

	if (port == CPU_PORT)
		return true;
	for (i = 0; i < NCAGES; i++)
		if (rtk_cage_port[i] == port)
			return true;
	return false;
}

int rtk_usage(void)
{
	printf("Usage:\nrtk     - Realtek commands\n\n");
	return CMD_RET_FAILURE;
}

int rtk_not_yet(const char *what)
{
	printf("not yet: `%s` needs the switch/SerDes bring-up (stage 4)\n", what);
	return CMD_RET_FAILURE;
}

static bool unit_ok(void)
{
	if (g_unit < MAX_UNIT)
		return true;
	printf("\nUnit %u invalid unit id \n", g_unit);
	return false;
}

static unsigned long num(char *const argv[], int i)
{
	return dectoul(argv[i], NULL);
}

int rtk_unit(int argc, char *const argv[])
{
	unsigned long u;

	if (!strcmp(argv[2], "get")) {
		printf("unit: %u\n", g_unit);
		return 0;
	}
	if (argc < 4)
		return rtk_usage();
	u = num(argv, 3);
	if (u >= MAX_UNIT)
		printf("Invalid unit: %lu\n", u);	/* stock still applies it */
	printf("Change to unit: %lu\n", u);
	g_unit = u;
	return 0;
}

int rtk_port_admin(int argc, char *const argv[])
{
	bool en = !strcmp(argv[2], "enable");
	unsigned long port;

	if (argc < 4 || (!en && strcmp(argv[2], "disable")))
		return rtk_usage();
	port = num(argv, 3);
	printf("%s port (%d,%d)\n", en ? "Enable" : "Disable", g_unit, (int)port);
	if (rtk_port_exists(port))	/* stock fails silently for other ports */
		sw_rmw(PORT_CTRL(port), 3, en ? 3 : 0);
	return 0;
}

static const struct { const char *name; u32 id; } profiles[] = {
	{ "RTL9301_2x8214QF_4XGE", 9300001 }, { "RTL9301_3x8218B_4XGE", 9300002 },
	{ "RTL9301_8218B_4XGE", 9300003 }, { "RTL9301_8218B_4XGE_CASCADE", 9300004 },
	{ "RTL9301_2x8214QF_4XGE_CASCADE", 9300005 },
	{ "RTL9301_14QF_4XGE_18B_4XGE_CASCADE", 9300006 },
	{ "RTL9301_3x8218D_4XGE", 9300007 }, { "RTL9301_6x8214QF_4XGE", 9300008 },
	{ "RTL9301_2x8214FC_4x8214QF_4XGE", 9300009 },
	{ "RTL9301_6x8218D_2x8295R_CASCADE", 9300010 },
	{ "RTL9301_2x8218B_4x8218D_2x8295R_CASCADE", 9300011 },
	{ "RTL9302B_2x8218D_2xCUST1_4xGE", 9300012 }, { "RTL9302C_4xCUST1", 9300013 },
	{ "RTL9303_2xCUST1", 9300014 }, { "RTL9303_8XGE", 9300015 },
	{ "RTL9303_8X2_5G", 9300022 }, { "RTL9303_8X8226", 9300020 },
	{ "RTL9302DE_2XRTL8284", 9300016 }, { "RTL9302C_2xRTL8284_2XGE", 9300017 },
	{ "RTL9302C_4xRTL8284_4XGE", 9300018 }, { "RTL9302B_2x8218D_2x8284_4xGE", 9300019 },
	{ "RTL9301_3x8218D_2x8226CARD_2XGE", 9300021 }, { "RTL9301_3x8218E_4XGE", 9300023 },
	{ "RTL9303_2X8254L_DEMO", 9300024 }, { "RTL9303_6x8254L_6xSPI", 9300025 },
};

int rtk_show(int argc, char *const argv[])
{
	int i;

	if (strcmp(argv[2], "hw_profile_list"))
		return rtk_usage();
	for (i = 0; i < ARRAY_SIZE(profiles); i++) {
		if (!i)
			printf("      Available profiles are:\n");
		printf("        %s (%d)\n", profiles[i].name, profiles[i].id);
	}
	printf("      (uboot: setenv boardmodel 'YOUR_HARDWARE_PROFILE_NAME')\n");
	return 0;
}

/* 8XGE has no combo ports: message only */
int rtk_comboport(int argc, char *const argv[])
{
	if (argc == 2)
		return rtk_usage();
	if (!strcmp(argv[2], "copper"))
		printf("ComboPort: Copper mode\n");
	else if (!strcmp(argv[2], "fiber"))
		printf("ComboPort: Fiber mode\n");
	else
		return rtk_usage();
	return 0;
}

/* RTL8231 is not fitted: the stock SDK rejects the device, so every verb fails the same way */
int rtk_ext(int argc, char *const argv[])
{
	const char *v = argv[1];

	if (!strcmp(v, "ext-devInit")) {
		if (argc == 2) {
			printf("Usage: rtk ext-devInit <devAddress> \n unit ID \n devAddress: 0~31\n\n");
			return 1;
		}
		printf("The generalCtrl GPIO device init failed.\n");
		return 1;
	}
	if (!strcmp(v, "ext-pinGet")) {
		if (argc == 2) {
			printf("Usage: rtk ext-pinGet <pinNum> \n pinNum: 0~36\n\n");
			return 1;
		}
		printf("The pinNum (%d) is invalid.\n", (int)num(argv, 2));
		return 1;
	}
	if (argc < 4) {
		printf("Usage: rtk ext-pinSet <pinNum> <status> \n pinNum: 0~36, status: 0/1\n\n");
		return 1;
	}
	if (num(argv, 3) > 1) {
		printf("The status (%d) is invalid.\n", (int)num(argv, 3));
		return 1;
	}
	printf("The pinNum (%d) is invalid.\n", (int)num(argv, 2));
	return 1;
}

/* No external PHYs: reads return 0, writes are accepted (what stock shows on this board). */
/* No PHY on this board (8 SFP cages, no copper PHY): phyreg/phymmd keep stock's text, then say so */
static int no_phy(void)
{
	printf("note: no PHY on TL-ST1008F: nothing read or written (value shown is a placeholder)\n");
	return 1;
}

int rtk_phyreg(int argc, char *const argv[])
{
	const char *v = argv[2];

	if (!strcmp(v, "dump-top"))
		return no_phy();
	if (!strcmp(v, "get") && argc >= 6) {
		printf("Get Unit %u Port %02d page %02d reg %02d", g_unit, (int)num(argv, 3),
		       (int)num(argv, 4), (int)num(argv, 5));
		if (unit_ok())
			printf("  val: 0x%04X \n", 0);
		return no_phy();
	}
	if (!strcmp(v, "set") && argc >= 7) {
		printf("Set Unit %u Port %02d page %02d reg %02d val: 0x%04X", g_unit,
		       (int)num(argv, 3), (int)num(argv, 4), (int)num(argv, 5), (u16)num(argv, 6));
		if (unit_ok())
			printf(" \n");
		return no_phy();
	}
	if (!strcmp(v, "setbymask") && argc >= 7) {
		printf("Set Unit %u PortMask %08x page %02d reg %02d val: 0x%04X \n", g_unit,
		       (u32)num(argv, 3), (int)num(argv, 4), (int)num(argv, 5), (u16)num(argv, 6));
		return no_phy();
	}
	return rtk_usage();
}

/* argv[3] is ignored by stock (scripts pass 0); port/addr/reg/data start at argv[4] */
int rtk_phymmd(int argc, char *const argv[])
{
	bool set = argc > 2 && !strcmp(argv[2], "set");

	if (argc < 6 || (set && argc < 8)) {	/* set reads data from argv[7] */
		printf("phymmd parameter error\n\n");
		return rtk_usage();
	}
	if (!set && strcmp(argv[2], "get"))
		return rtk_usage();
	if (set)
		printf("Set Unit %u Port %02u mmd-address %02u mmd-reg %02u val: 0x%04X", g_unit,
		       (u32)num(argv, 4), (u32)num(argv, 5), (u32)num(argv, 6), (u16)num(argv, 7));
	else
		printf("Get Unit %u Port %02d mmd-address %02d mmd-reg %02d", g_unit,
		       (int)num(argv, 4), (int)num(argv, 5), (int)num(argv, 6));
	if (unit_ok())
		printf(set ? " \n" : "  val: 0x%04X \n", 0);
	return no_phy();
}

int rtk_sdsreg(int argc, char *const argv[])
{
	bool set = argc > 2 && !strcmp(argv[2], "set");
	unsigned int sds, page, reg;
	u16 v;
	int ret;

	/* reads argv[4..6] (+7 for set): one argument short dereferenced NULL (#74) */
	if (argc < 7 || (set && argc < 8)) {
		printf("sdsreg parameter error\n\n");
		return rtk_usage();
	}
	if (!set && strcmp(argv[2], "get"))
		return rtk_usage();
	sds = num(argv, 4);
	page = num(argv, 5);
	reg = num(argv, 6);
	if (set)
		printf("Set unit %u sds %02d page %02d reg %02d val: 0x%04X", g_unit, sds, page,
		       reg, (u16)num(argv, 7));
	else
		printf("Get unit %u sds %02d page %02d reg %02d", g_unit, sds, page, reg);
	if (!unit_ok())
		return 1;
	if (set) {
		ret = rtk_sds_write(sds, page, reg, num(argv, 7));
		printf(ret ? "    Failed!! 0x%x\n" : " \n", 0xf00c);
	} else {
		ret = rtk_sds_read(sds, page, reg, &v);
		if (ret)
			printf("    Failed!! 0x%x \n", 0xf00c);
		else
			printf("  val: 0x%04X \n", v);
	}
	return 1;
}

static const char *const sds_modes[] = {
	"none", "disable", "10gr", "rxaui", "rxaui_lite", "rxauisgmii_auto",
	"rxaui1000bx_auto", "rsgmii_plus", "sgmii", "qsgmii", "1000bx_fiber", "100bx_fiber",
	"1000bx100bx_auto", "10gr1000bx_auto", "10grsgmii_auto", "xaui", "rmii", "smii",
	"sssmii", "rsgmii", "xsmii", "xsgmii", "qhsgmii", "hisgmii", "hisgmii_5g",
	"dual_hisgmii", "2500base_x", "rxaui_plus", "usxgmii_10gsxgmii", "usxgmii_10gdxgmii",
	"usxgmii_10gqxgmii", "usxgmii_5gsxgmii", "usxgmii_5gdxgmii", "usxgmii_2_5gsxgmii",
};
#define SDS_MODE_LISTED	44	/* stock prints 44 rows: 34 names, 10 blank */

static void sds_mode_list(void)
{
	int i;

	printf("mode options are:\n");
	for (i = 0; i < SDS_MODE_LISTED; i++)
		printf("  %s\n", i < ARRAY_SIZE(sds_modes) ? sds_modes[i] : "");
}

int rtk_macsds(int argc, char *const argv[])
{
	int i;

	if (argc < 4 || strcmp(argv[2], "set"))
		return rtk_usage();
	if (argc < 5) {
		printf("macsds parameter error %u\n\n", argc);
		sds_mode_list();
		return rtk_usage();
	}
	for (i = 0; i < ARRAY_SIZE(sds_modes); i++)
		if (!strcmp(argv[4], sds_modes[i]))
			break;
	if (i == ARRAY_SIZE(sds_modes)) {
		printf("sdsmode error\n");
		sds_mode_list();
		return rtk_usage();
	}
	printf("sds=%u mode=%s\n", (u32)num(argv, 3), argv[4]);
	return rtk_macsds_apply(num(argv, 3), i);
}

int rtk_board(int argc, char *const argv[])
{
	bool id = !strcmp(argv[1], "boardid");
	const char *v;

	if (argc == 3) {
		printf("refused: stock does setenv + a 64 KiB flash erase/write of the env sector\n");
		return CMD_RET_FAILURE;
	}
	v = env_get(id ? "boardid" : "boardmodel");
	printf(id ? "Board Model ID: %s\n" : "Board Model: %s\n", v ? v : "<NULL>");
	return 1;
}

/* ---- ledtest: software LED control (disables the HW LED engine per port while running) ---- */

static u32 led_en_save[4];
static u32 led_ctrl_save[NPORTS];

static void led_out(int idx, int only_port)
{
	int i, p;
	u32 f;

	for (i = 0; i < NCAGES; i++) {
		p = rtk_cage_port[i];
		f = (only_port < 0 || only_port == p) ? LED_ON : 0;
		/* write copper and fibre field: stock picks one by LED layout (not known here) */
		sw_rmw(LED_SW_CTRL(p), 7 << (3 * idx) | 7 << (12 + 3 * idx),
		       f << (3 * idx) | f << (12 + 3 * idx));
	}
	mdelay(300);	/* stock settle after each pattern */
}

static void led_init(void)
{
	int i, p;

	for (i = 0; i < 4; i++)
		led_en_save[i] = sw_r(RTL9300_LED_PORT_SW_EN_CTRL(i));
	for (i = 0; i < NCAGES; i++) {
		p = rtk_cage_port[i];
		led_ctrl_save[p] = sw_r(LED_SW_CTRL(p));
		sw_w(LED_SW_CTRL(p), 0);
		sw_rmw(LED_SW_EN(p), 0xf << ((p & 7) * 4), LED_ON << ((p & 7) * 4));
	}
}

static void led_restore(void)
{
	int i, p;

	for (i = 0; i < NCAGES; i++) {
		p = rtk_cage_port[i];
		sw_w(LED_SW_CTRL(p), led_ctrl_save[p]);
	}
	for (i = 0; i < 4; i++)
		sw_w(RTL9300_LED_PORT_SW_EN_CTRL(i), led_en_save[i]);
}

int rtk_ledtest(int argc, char *const argv[])
{
	int i, p, idx, t;

	if (argc == 2) {
		led_init();
		printf("\n all led on \n");
		led_out(0, -1);
		mdelay(200);
		printf("\n all led off \n");
		for (i = 0; i < NCAGES; i++)
			sw_w(LED_SW_CTRL(rtk_cage_port[i]), 0);
		printf("\n walking one \n");
		for (i = 0; i < NCAGES; i++) {
			p = rtk_cage_port[i];
			for (idx = 0; idx < NLED; idx++) {
				led_out(idx, p);
				sw_w(LED_SW_CTRL(p), 0);
			}
		}
		printf("\n all led off \n");
		led_restore();
		return 0;
	}
	if (argc != 4) {
		printf("Usage: rtk ledtest [port] [led_index]\n\n");
		return 1;
	}
	p = num(argv, 2);
	idx = num(argv, 3);
	if (!rtk_port_exists(p)) {
		printf("The port (%d) is invalid.\n", p);
		return 0;
	}
	if (idx < 0 || idx > NLED) {
		printf("The led index (%d) is invalid.\n", idx);
		return 0;
	}
	if (p == CPU_PORT)
		return 0;
	led_init();
	led_out(idx, p);
	printf("\n press any to end.\n");
	for (t = 0; t < KEY_WAIT_MS / 10 && !tstc(); t++)
		mdelay(10);
	if (tstc())
		getchar();
	else
		printf("ledtest: no key in %d ms, restoring\n", KEY_WAIT_MS);
	led_restore();
	return 0;
}
