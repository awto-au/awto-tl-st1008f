// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk`: dispatcher + i2c/pin/laser/sfp. Stock-named verbs: rtk_stock.c; extras: rtk_ours.c.
 * plus `rtk laser` and `rtk sfp`. Output strings match the stock loader where it has one
 * ("data 0x..", "OK") so the same scripts drive both.
 * Safety: module EEPROM (0x50) is never written; GPIO21 low = board reset (needs `force`).
 */

#include <command.h>
#include <dm.h>
#include <i2c.h>
#include <asm/gpio.h>
#include <linux/delay.h>
#include <display_options.h>
#include <vsprintf.h>
#include "rtk.h"
#include "sfp/sfp.h"

#define SFP_A0		0x50
#define SFP_A2		0x51
#define SFP_PHY		0x56	/* copper module PHY (SFF-8472 has no address; Linux sfp.c) */
#define GPIO_RESET	21

struct udevice *rtk_chip(int bus, int addr)
{
	struct udevice *dev;

	return i2c_get_chip_for_busnum(bus, addr, 1, &dev) ? NULL : dev;
}

/* `rtk i2c` device ids: 0-7 = cage EEPROM (0x50), 8 = laser expander; `i2c init` re-points an id */
#define NI2C_DEV	16

static struct { signed char bus; u8 addr; } i2c_map[NI2C_DEV] = {
	{ 0, SFP_A0 }, { 1, SFP_A0 }, { 2, SFP_A0 }, { 3, SFP_A0 }, { 4, SFP_A0 },
	{ 5, SFP_A0 }, { 6, SFP_A0 }, { 7, SFP_A0 }, { EXP_BUS, EXP_ADDR },
	[9 ... NI2C_DEV - 1] = { -1, 0 },
};

static struct udevice *rtk_i2c_dev(unsigned long id, bool *is_sfp)
{
	if (id >= NI2C_DEV || i2c_map[id].bus < 0)
		return NULL;
	*is_sfp = i2c_map[id].bus < NCAGES;
	return rtk_chip(i2c_map[id].bus, i2c_map[id].addr);
}

/* Buses are fixed by the device tree: `init` only maps the id to the cage/expander it names. */
static int rtk_i2c_init(int argc, char *const argv[])
{
	unsigned long id, chip, sda;

	if ((!strcmp(argv[3], "sw") && argc < 13) || (!strcmp(argv[3], "hw") && argc < 10)) {
		printf("i2c parameter error\n\n");
		return rtk_usage();
	}
	id = dectoul(argv[4], NULL);
	if (id >= NI2C_DEV)
		return 0;
	if (!strcmp(argv[3], "sw")) {	/* id sck_dev sck_pin sda_dev sda_pin type chipid ... */
		chip = dectoul(argv[10], NULL);
		sda = dectoul(argv[8], NULL);
		if (dectoul(argv[6], NULL) == 22 && sda == 23)
			i2c_map[id].bus = EXP_BUS, i2c_map[id].addr = chip;
		else if (sda < NCAGES)
			i2c_map[id].bus = sda, i2c_map[id].addr = chip;
	} else {			/* id intf sda_pin type chipid ... */
		chip = dectoul(argv[8], NULL);
		sda = dectoul(argv[6], NULL);
		if (sda < NCAGES)
			i2c_map[id].bus = sda, i2c_map[id].addr = chip;
	}
	return 0;
}

static int do_rtk_i2c(int argc, char *const argv[])
{
	struct udevice *dev;
	bool is_sfp = false;
	unsigned long reg;
	u8 b;

	if (argc == 2) {
		printf("i2c parameter error\n\n");
		return rtk_usage();
	}
	if (!strcmp(argv[2], "init") && argc >= 4 && (!strcmp(argv[3], "sw") || !strcmp(argv[3], "hw")))
		return rtk_i2c_init(argc, argv);
	if (!strcmp(argv[2], "read")) {
		if (argc < 5) {
			printf("i2c parameter error\n\n");
			return rtk_usage();
		}
		dev = rtk_i2c_dev(dectoul(argv[3], NULL), &is_sfp);
		if (!dev)
			printf("FAIL (%d)\n", 0xf00f);	/* stock: no such device id */
		else if (dm_i2c_read(dev, dectoul(argv[4], NULL), &b, 1))
			printf("FAIL (-1)\n");
		else
			printf("data 0x%x\n", b);
		return 0;
	}
	if (!strcmp(argv[2], "write")) {
		if (argc < 6) {
			printf("i2c parameter error\n\n");
			return 1;
		}
		dev = rtk_i2c_dev(dectoul(argv[3], NULL), &is_sfp);
		if (dev && is_sfp) {
			printf("refused: module EEPROM is read-only here\n");
			return CMD_RET_FAILURE;
		}
		reg = dectoul(argv[4], NULL);
		b = dectoul(argv[5], NULL);
		if (!dev)
			printf("FAIL (%d)\n", 0xf00f);
		else if (dm_i2c_write(dev, reg, &b, 1))
			printf("FAIL (-1)\n");
		else
			printf("OK\n");
		return 0;
	}
	return rtk_usage();
}

int rtk_gpio_line(int pin, struct gpio_desc *d)
{
	char name[12];

	snprintf(name, sizeof(name), "gpio%d", pin);
	return dm_gpio_lookup_name(name, d);
}

#define NPINS	24	/* gpio0 DATA bits 0-23 */

/* Stock text: `pin%d:\t%d`. Reads do not claim the line (gpio-keys/i2c-gpio keep theirs). */
static int do_rtk_pin(bool set, int argc, char *const argv[])
{
	struct gpio_desc d;
	unsigned long pin, v = 0;

	if (argc < (set ? 4 : 3)) {
		printf(set ? "Usage: rtk pinSet <pinNum> <status> \n pinNum: 0~7, status: 0/1\n\n" :
		       "Usage: rtk pinGet <pinNum> \n pinNum: 0~7\n\n");
		return 1;
	}
	pin = dectoul(argv[2], NULL);
	if (set) {
		v = dectoul(argv[3], NULL);
		if (v > 1) {
			printf("The status (%d) is invalid.\n", (int)v);
			return 1;
		}
	}
	if (pin >= NPINS || rtk_gpio_line(pin, &d)) {
		printf("The pinNum (%d) is invalid.\n", (int)pin);
		return 1;
	}
	if (!set) {
		v = gpio_get_ops(d.dev)->get_value(d.dev, d.offset);
	} else {
		if (pin == GPIO_RESET && !v && (argc < 5 || strcmp(argv[4], "force"))) {
			printf("refused: GPIO21 low resets the board (add `force`)\n");
			return CMD_RET_FAILURE;
		}
		if (dm_gpio_request(&d, "rtk")) {
			printf("The pinNum (%d) is invalid.\n", (int)pin);
			return 1;
		}
		dm_gpio_set_dir_flags(&d, GPIOD_IS_OUT | (v ? GPIOD_IS_OUT_ACTIVE : 0));
		dm_gpio_free(d.dev, &d);
	}
	printf("pin%d:\t%d\n\n", (int)pin, (int)v);
	return 0;
}

/* Laser TX-disable: expander pin N = cage N+1, 1 = laser off. One-cage default (cage loop #19). */
static int do_rtk_laser(int argc, char *const argv[])
{
	struct udevice *dev = rtk_chip(EXP_BUS, EXP_ADDR);
	u8 out, cfg;
	int i, cage;

	if (!dev || dm_i2c_read(dev, EXP_OUT, &out, 1) || dm_i2c_read(dev, EXP_CFG, &cfg, 1)) {
		printf("laser expander not responding\n");
		return CMD_RET_FAILURE;
	}
	if (argc < 2 || !strcmp(argv[1], "status")) {
		for (i = 0; i < NCAGES; i++)	/* input pin = pulled high = laser off */
			printf("cage %d: %s\n", i + 1,
			       !(cfg & BIT(i)) && !(out & BIT(i)) ? "ON" : "off");
		return 0;
	}
	if (!strcmp(argv[1], "none")) {
		out = 0xff;
	} else if (!strcmp(argv[1], "all")) {
		if (argc < 3 || strcmp(argv[2], "force")) {
			printf("refused: all lasers on = cage-loop risk (add `force`)\n");
			return CMD_RET_FAILURE;
		}
		out = 0x00;
	} else {
		cage = dectoul(argv[1], NULL);
		if (cage < 1 || cage > NCAGES)
			return CMD_RET_USAGE;
		out = 0xff & ~BIT(cage - 1);
	}
	cfg = 0x00;
	if (dm_i2c_write(dev, EXP_OUT, &out, 1) || dm_i2c_write(dev, EXP_CFG, &cfg, 1)) {
		printf("FAIL\n");
		return CMD_RET_FAILURE;
	}
	printf("OK (out 0x%02x)\n", out);
	return 0;
}

static void sfp_str(const char *tag, const u8 *p, int n)
{
	int e = n;

	while (e > 0 && (p[e - 1] == ' ' || !p[e - 1]))
		e--;
	printf("  %s %.*s\n", tag, e, p);
}

/* Block read at the bus default (100 kHz); on failure retry at 50 kHz, then single bytes.
 * MCU-emulated EEPROMs (copper modules) clock-stretch; this master cannot follow at 100 kHz
 * (GLC-T: block reads clean at 50 kHz). The bus is restored to 100 kHz afterwards. */
static int sfp_read(struct udevice *dev, u8 reg, u8 *buf, int len, int *mode)
{
	struct udevice *bus = dev_get_parent(dev);
	int i, ret;

	*mode = 0;
	if (!dm_i2c_read(dev, reg, buf, len))
		return 0;
	/* the module MCU stays busy after the failed transfer: a 50 kHz read straight away
	 * failed on all three Cisco modules, the same read on an idle bus works. 20 ms gap. */
	mdelay(20);
	dm_i2c_set_bus_speed(bus, 50000);
	ret = dm_i2c_read(dev, reg, buf, len);
	dm_i2c_set_bus_speed(bus, 100000);
	if (!ret) {
		*mode = 1;
		return 0;
	}
	*mode = 2;
	for (i = 0; i < len; i++) {
		int tries;

		/* MCU busy after the failed block read: up to 5 x 1 ms per byte (bounded 5 ms) */
		for (tries = 0; dm_i2c_read(dev, reg + i, buf + i, 1); tries++) {
			if (tries == 4) {
				printf("  byte 0x%02x: no ACK after 5 tries\n", reg + i);
				return -EIO;
			}
			mdelay(1);
		}
	}
	return 0;
}

/* Some old Cisco EEPROMs pad unused BINARY fields with ASCII spaces (0x20): GLC-SX-MM has
 * 0x20 in bytes 3-5/7-13, OUI 37-39 and options 64-65, plus a stray 0x01 in byte 36.
 * Detect (>=4 of the 8 compliance bytes == 0x20), treat the 0x20 as 0 and drop byte 36. */
static bool sfp_space_padded(u8 *id)
{
	/* incl. lengths 14-19: GLC-SX-MM otherwise decodes as SMF 32 km / copper 32 m */
	static const u8 fields[] = { 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
				     37, 38, 39, 64, 65 };
	int i, n = 0;

	for (i = 3; i <= 10; i++)
		n += id[i] == 0x20;
	if (n < 4)
		return false;
	for (i = 0; i < ARRAY_SIZE(fields); i++)
		if (id[fields[i]] == 0x20)
			id[fields[i]] = 0;
	id[36] = 0;
	return true;
}

int rtk_sfp_read_id(int cage, u8 *id)
{
	struct udevice *a0 = rtk_chip(cage - 1, SFP_A0);
	int mode;

	if (!a0 || sfp_read(a0, 0, id, 96, &mode))
		return -1;
	sfp_space_padded(id);
	return 0;
}

static u8 sfp_csum(const u8 *p, int n)
{
	u8 s = 0;

	while (n--)
		s += *p++;
	return s;
}

/* Media from SFF-8472 compliance bytes 3-10 (first match wins). */
static const char *sfp_media(const u8 *id)
{
	if (id[3] & 0x10) return "10GBASE-SR";
	if (id[3] & 0x20) return "10GBASE-LR";
	if (id[3] & 0x40) return "10GBASE-LRM";
	if (id[3] & 0x80) return "10GBASE-ER";
	if (id[8] & 0x04) return "SFP+ DAC (passive)";
	if (id[8] & 0x08) return "SFP+ DAC (active)";
	if (id[6] & 0x08) return "1000BASE-T";
	if (id[6] & 0x01) return "1000BASE-SX";
	if (id[6] & 0x02) return "1000BASE-LX";
	if (id[6] & 0x04) return "1000BASE-CX";
	if (id[6] & 0x40) return "100BASE-FX";
	return NULL;
}

/* No compliance code set: describe what the module does declare (rate, wavelength, reach). */
static void sfp_media_print(const u8 *id)
{
	const char *m = sfp_media(id);
	unsigned int nm = id[60] << 8 | id[61];

	if (m) {
		printf("%s", m);
		return;
	}
	printf("no compliance code (%s, %u nm", id[12] >= 100 ? "10G-class" :
	       id[12] >= 10 ? "1G-class" : "rate?", nm);
	if (id[14])
		printf(", SMF %u km", id[14]);
	else if (id[16] || id[17])
		printf(", MMF %u/%u m", id[16] * 10, id[17] * 10);
	printf(")");
}

/* MOD-DEF0 (module present) = gpio0 line cage-1, active low; read without claiming. */
static int sfp_present(int cage)
{
	struct gpio_desc d;

	if (rtk_gpio_line(cage - 1, &d))
		return -1;
	return !gpio_get_ops(d.dev)->get_value(d.dev, d.offset);
}

int rtk_sfp_present(int cage)
{
	return sfp_present(cage);
}

/* A2 (0x51) bytes 0-127 with the same read fallbacks as A0 */
int rtk_sfp_read_a2(int cage, u8 *a2)
{
	struct udevice *dev = rtk_chip(cage - 1, SFP_A2);
	int mode;

	return !dev || sfp_read(dev, 0, a2, 128, &mode) ? -1 : 0;
}

/* Facts the generic decode gets wrong or omits for known module families. */
static void sfp_notes(const u8 *id)
{
	if ((id[6] & 0x08) && id[2] != 0x22)
		printf("  note  1000BASE-T copper module but connector byte is 0x%02x (not RJ45 0x22)\n",
		       id[2]);
}

static void pr_fix(const char *tag, bool neg, u32 v, u32 div, int digits)
{
	printf("%s %s%u.%0*u", tag, neg ? "-" : "", v / div, digits, v % div);
}

/* Compact one-line DDM summary (parsed by scripts/uboot_mainline_test.py). */
static void sfp_ddm_line(const u8 *a0, const u8 *a2)
{
	struct sff_diags sd;
	s32 t;

	sff8472_diags(a0, a2, &sd);
	t = sd.sfp_temp[MCURR];
	printf("  ddm   %s cal: ", sd.calibrated_ext ? "external" : "internal");
	pr_fix("temp", t < 0, (t < 0 ? -t : t) * 100 / 256, 100, 2);
	pr_fix(" C, vcc", false, sd.sfp_voltage[MCURR], 10000, 4);
	pr_fix(" V, bias", false, sd.bias_cur[MCURR] * 2, 1000, 3);
	pr_fix(" mA, tx", false, sd.tx_power[MCURR], 10000, 4);
	pr_fix(" mW, rx", false, sd.rx_power[MCURR], 10000, 4);
	printf(" mW\n");
}

static int sfp_one(int cage, bool full)
{
	struct udevice *a0 = rtk_chip(cage - 1, SFP_A0), *a2 = rtk_chip(cage - 1, SFP_A2);
	static const char *const plevel[] = { "1 (1.0 W)", "2 (1.5 W)", "3 (2.0 W)", "3 (2.0 W)" };
	static const char *const rmode[] = { "", " [50 kHz: module clock-stretches]",
					     " [byte-wise: module clock-stretches]" };
	u8 id[96], dm[128];
	int mode, pres = sfp_present(cage);
	bool cc_base, cc_ext, padded, ddm_ok = false;

	if (!a0 || sfp_read(a0, 0, id, sizeof(id), &mode)) {
		printf("cage %d: no EEPROM answer, MOD-DEF0 %s%s\n", cage,
		       pres ? "says PRESENT" : "absent", pres ? "  <-- mismatch (#29)" : "");
		return 0;
	}
	/* checksums over the raw bytes, before any space-padding fix-up */
	cc_base = sfp_csum(id, 63) == id[63];
	cc_ext = sfp_csum(id + 64, 31) == id[95];
	padded = sfp_space_padded(id);
	printf("cage %d: ", cage);
	sfp_media_print(id);
	if (id[12])
		printf(", %d00 Mbd", id[12]);
	else
		printf(", rate not declared");
	printf(", %u nm, MOD-DEF0 %s%s%s\n", id[60] << 8 | id[61],
	       pres ? "present" : "ABSENT", pres ? "" : "  <-- mismatch", rmode[mode]);
	sfp_str("vendor", id + 20, 16);
	sfp_str("pn    ", id + 40, 16);
	sfp_str("rev   ", id + 56, 4);
	sfp_str("sn    ", id + 68, 16);
	sfp_str("date  ", id + 84, 6);
	printf("  eeprom CC_BASE %s, CC_EXT %s%s; compliance %02x %02x %02x %02x %02x %02x %02x %02x\n",
	       cc_base ? "ok" : "BAD", cc_ext ? "ok" : "BAD",
	       padded ? ", NON-COMPLIANT (0x20 padding in binary fields, treated as 0)" : "",
	       id[3], id[4], id[5], id[6], id[7], id[8], id[9], id[10]);
	/* SFF-8472 byte 64: bit 1 = power level 2 declared, bit 5 = level 3 (Linux sfp.c) */
	printf("  power level %s declared\n",
	       plevel[(id[64] & 0x02 ? 1 : 0) | (id[64] & 0x20 ? 2 : 0)]);
	sfp_notes(id);
	if (!(id[92] & 0x40)) {
		printf("  ddm   not implemented (A0 byte 92 = 0x%02x)\n", id[92]);
		goto decode;
	}
	/* brief + internal calibration needs only the live bytes 96-105; keep the old 10 B read */
	memset(dm, 0, sizeof(dm));
	if (!a2 || (full || (id[92] & 0x10) ? sfp_read(a2, 0, dm, sizeof(dm), &mode) :
						sfp_read(a2, 96, dm + 96, 10, &mode))) {
		printf("  ddm   declared but A2 (0x51) did not answer\n");
		goto decode;
	}
	ddm_ok = true;
	sfp_ddm_line(id, dm);
decode:
	if (!full)
		return 0;
	printf("--- ethtool decode ---\n");
	sff8079_show_all(id);
	if (ddm_ok)
		sff8472_show_all(id, dm);
	return 0;
}

/* `rtk sfp <cage> raw`: A0 and A2 low pages as read (128 B each), no decode. */
static int sfp_raw(int cage)
{
	struct udevice *dev;
	u8 buf[128];
	int mode, a;

	for (a = SFP_A0; a <= SFP_A2; a++) {
		dev = rtk_chip(cage - 1, a);
		if (!dev || sfp_read(dev, 0, buf, sizeof(buf), &mode)) {
			printf("cage %d: 0x%02x no answer\n", cage, a);
			continue;
		}
		printf("cage %d: I2C address 0x%02x\n", cage, a);
		print_buffer(0, buf, 1, sizeof(buf), 16);
	}
	return 0;
}

/* One PHY byte: up to 5 tries 1 ms apart (module busy after a NACK, as sfp_read; bounded 5 ms) */
static int phy_byte(struct udevice *dev, int r, u8 *b, int *retries)
{
	int tries;

	for (tries = 0; dm_i2c_read(dev, r, b, 1); tries++) {
		if (tries == 4)
			return -EIO;
		mdelay(1);
		(*retries)++;
	}
	return 0;
}

/* Copper module PHY (88E1111 at 0x56): 16-bit regs as two 1-byte reads of the same reg, MSB
 * then LSB (Linux mdio-i2c SMBus path); a 2-byte block read gets the LSB as 0xff (#33).
 * ID1 read back as 0x4101 = PHY byte pointer off by one: one extra byte read re-aligns it. */
static int sfp_phy(int cage, int only)
{
	static const u8 regs[] = { 0x00, 0x01, 0x02, 0x03, 0x11 };	/* BMCR BMSR ID1 ID2 PSSR */
	struct udevice *dev = rtk_chip(cage - 1, SFP_PHY);
	int i, r, n = only >= 0 ? 1 : ARRAY_SIZE(regs), retries = 0;
	u8 hi, lo;

	if (!dev || phy_byte(dev, 2, &hi, &retries) || phy_byte(dev, 2, &lo, &retries)) {
		printf("cage %d: phy 0x%02x: no answer\n", cage, SFP_PHY);
		return CMD_RET_FAILURE;
	}
	if (hi == 0x41 && lo == 0x01) {
		printf("cage %d: phy ID1 read as 0x4101: byte order realigned\n", cage);
		if (phy_byte(dev, 2, &hi, &retries))
			return CMD_RET_FAILURE;
	}
	for (i = 0; i < n; i++) {
		r = only >= 0 ? only : regs[i];
		if (phy_byte(dev, r, &hi, &retries) || phy_byte(dev, r, &lo, &retries)) {
			printf("cage %d: phy 0x%02x reg 0x%02x: no answer\n", cage, SFP_PHY, r);
			return CMD_RET_FAILURE;
		}
		printf("cage %d: phy 0x%02x reg 0x%02x = 0x%04x\n", cage, SFP_PHY, r, hi << 8 | lo);
	}
	if (retries)
		printf("cage %d: phy %d byte retries\n", cage, retries);
	return 0;
}

static int do_rtk_sfp(int argc, char *const argv[])
{
	int c;

	if (argc >= 3 && !strcmp(argv[2], "phy"))
		return sfp_phy(dectoul(argv[1], NULL), argc >= 4 ? (int)hextoul(argv[3], NULL) : -1);
	if (argc >= 3 && !strcmp(argv[2], "raw"))
		return sfp_raw(dectoul(argv[1], NULL));
	if (argc >= 3 && !strcmp(argv[2], "mode")) {
		const char *why;
		int itf = rtk_sfp_iface(dectoul(argv[1], NULL), &why);

		if (itf < 0)
			printf("cage %s: no module EEPROM\n", argv[1]);
		else
			printf("cage %s: linux interface %s (%s)\n", argv[1], rtk_if_name[itf], why);
		return 0;
	}
	if (argc >= 2)
		return sfp_one(dectoul(argv[1], NULL), !(argc >= 3 && !strcmp(argv[2], "brief")));
	for (c = 1; c <= NCAGES; c++)	/* all cages: summary only (the full decode is ~5 KB per cage) */
		sfp_one(c, false);
	return 0;
}

static bool is(char *const argv[], int i, const char *s)
{
	return !strcmp(argv[i], s);
}

/* Dispatch order and argument checks follow the stock `rtk` (SDK uboot_cmd.c, GPL-2.0). */
static int do_rtk(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	static const char *const media[] = { "none", "fiber10g", "fiber1g", "dac50cm", "dac100cm",
					     "dac300cm" };
	int i;

	if (argc < 2)
		return rtk_usage();
	if (is(argv, 1, "init") || is(argv, 1, "rtcore-init"))
		return rtk_not_yet(argv[1]);
	if (is(argv, 1, "network"))
		return argc > 2 && (is(argv, 2, "on") || is(argv, 2, "off")) ?
		       rtk_network(argc, argv) : rtk_usage();
	if (is(argv, 1, "unit"))
		return argc > 2 && (is(argv, 2, "get") || is(argv, 2, "set")) ?
		       rtk_unit(argc, argv) : rtk_usage();
	if (is(argv, 1, "port")) {
		if (argc == 2 || is(argv, 2, "status"))
			return rtk_port_status(argc, argv);
		return rtk_port_admin(argc, argv);
	}
	if (is(argv, 1, "show"))
		return argc > 2 ? rtk_show(argc, argv) : rtk_usage();
	if (is(argv, 1, "comboport"))
		return rtk_comboport(argc, argv);
	if (is(argv, 1, "port-isolation"))
		return argc > 2 && (is(argv, 2, "on") || is(argv, 2, "off")) ?
		       rtk_port_isolation(argc, argv) : rtk_usage();
	if (is(argv, 1, "pinGet"))
		return do_rtk_pin(false, argc, argv);
	if (is(argv, 1, "pinSet"))
		return do_rtk_pin(true, argc, argv);
	if (!strncmp(argv[1], "ext-", 4) && (is(argv, 1, "ext-devInit") || is(argv, 1, "ext-pinGet") ||
					      is(argv, 1, "ext-pinSet")))
		return rtk_ext(argc, argv);
	if (is(argv, 1, "i2c"))
		return do_rtk_i2c(argc, argv);
	if (is(argv, 1, "ledtest"))
		return rtk_ledtest(argc, argv);
	if (is(argv, 1, "phyreg"))
		return argc > 2 ? rtk_phyreg(argc, argv) : rtk_usage();
	if (is(argv, 1, "phymmd"))
		return argc > 2 ? rtk_phymmd(argc, argv) : rtk_usage();
	if (is(argv, 1, "sdsreg"))
		return rtk_sdsreg(argc, argv);	/* stock: bare `rtk sdsreg` = parameter error + usage */
	if (is(argv, 1, "macsds"))
		return rtk_macsds(argc, argv);
	if (is(argv, 1, "phytestmode")) {
		if (argc == 2) {
			printf("Usage: testmode <mode> <port> <channel>\n channel: 1=A,2=B,3=C,4=D,0=None\n\n");
			return 1;
		}
		printf("refused: no PHY on this board\n");
		return 1;
	}
	if (is(argv, 1, "boardid") || is(argv, 1, "boardmodel"))
		return rtk_board(argc, argv);
	if (is(argv, 1, "10g")) {
		if (argc > 3)
			for (i = 0; i < ARRAY_SIZE(media); i++)
				if (is(argv, 3, media[i]))
					return rtk_10g(argc, argv);
		return rtk_usage();
	}
	if (is(argv, 1, "send"))
		return rtk_not_yet("send");
	/* ---- not on the stock loader ---- */
	if (is(argv, 1, "laser"))
		return do_rtk_laser(argc - 1, argv + 1);
	if (is(argv, 1, "sfp"))
		return do_rtk_sfp(argc - 1, argv + 1);
	if (is(argv, 1, "mode"))
		return rtk_mode(argc, argv);
	if (is(argv, 1, "temp"))
		return rtk_temp(argc, argv);
	if (is(argv, 1, "spg"))
		return rtk_spg(argc, argv);
	if (is(argv, 1, "sdsdump"))
		return rtk_sdsdump(argc, argv);
	if (is(argv, 1, "help-ours"))
		return rtk_ours_help();
	return rtk_usage();
}

/* Stock `help rtk` text verbatim (typos included), then our section; rtk_parity drops the
 * section before comparing with stock. */
U_BOOT_CMD(rtk, 16, 0, do_rtk, "rtk     - Realtek commands\n",
	   "rtk network on\n"
	   "        - Enable the networking function\n"
	   "rtk netowkr off\n"
	   "        - Disable the networking function\n"
	   "rtk testmode [mode] [port]\n"
	   "        - Set default value for specific testing\n"
	   "rtk ext-devInit [deviceAddress]\n"
	   "        - set RTL8231 MDC address\n"
	   "rtk ext-pinGet [pinNum]\n"
	   "        - get external 8231 GPIO pin status\n"
	   "rtk ext-pinSet [pinNum] [status]\n"
	   "        - set external 8231 GPIO pin status\n"
	   "rtk i2c init sw [i2c_dev_id] [sck_dev] [sck_pin] [sda_dev] [sda_pin] [8/16 access type] [chipid] [delay] [rtl8231_address (for Ext-GPIO only)] [read_type 0~1]\n"
	   "        - create a i2c group and init\n"
	   "rtk i2c init hw [i2c_dev_id] [intf_id 0~1 for HW] [sda_pin] [8/16 access type] [chipid] [freq 0~3] [read_type 0~1]\n"
	   "        - create a i2c group and init\n"
	   "rtk i2c read [i2c_dev_id] [reg]\n"
	   "rtk i2c write [i2c_dev_id] [reg] [data]\n"
	   "rtk pinGet [pinNum]\n"
	   "        - get internal GPIO pin status\n"
	   "rtk pinSet [pinNum] [status]\n"
	   "        - set internal GPIO pin status\n"
	   "rtk ledtest [port] [led_index]\n"
	   "        - led test\n"
	   "rtk show hw_profile_list\n"
	   "        - show the current all supported hw_profile list\n"
	   "rtk phytestmode mode port channel\n"
	   "        - Set PHY into test mode; channel: 1=A,2=B,3=C,4=D,0=None\n"
	   "rtk boardid\n"
	   "        - Get board model id\n"
	   "rtk boardid id\n"
	   "        - Set board model id\n"
	   "rtk boardmodel\n"
	   "        - Get board model\n"
	   "rtk boardmode <str>model\n"
	   "        - Set board model\n"
	   "rtk 10g PORT [none | fiber10g | fiber1g | fiber100m | dac50cm | dac100cm | dac300cm]        - Set 10g port media\n"
	   "rtk phyreg get [port] [page] [reg]\n"
	   "rtk phyreg set [port] [page] [reg] [data]\n"
	   "        - Get/Set PHY register\n"
	   "rtk phymmd get [port] [addr] [reg]\n"
	   "rtk phymmd set [port] [addr] [reg] [data]\n"
	   "        - Get/Set PHY mmd register\n"
	   "rtk sdsreg get [sdsId] [page] [reg]\n"
	   "rtk sdsreg set [sdsId] [page] [reg] [data]\n"
	   "        - Get/Set MAC serdes register\n"
	   "rtk macsds set [sdsId] [sds_mode]\n"
	   "        - Set MAC serdes mode\n"
	   "rtk unit get\n"
	   "rtk unit set [unit]\n"
	   "        - Get/set unit ID\n"
	   "--- TL-ST1008F additions (not in stock help) ---\n"
	   "rtk laser [status | <cage> | none | all force]\n"
	   "        - SFP TX enable via the TCA9534A; one cage at a time unless forced\n"
	   "rtk sfp [cage [raw | brief | phy [reg] | mode]]\n"
	   "        - module EEPROM + DDM: presence, checksums, ethtool-style decode;\n"
	   "          phy: copper module PHY (0x56) regs 0-3, 0x11;\n"
	   "          mode = SerDes interface Linux would pick (network on uses it; rtk_media=stock: 10G)\n"
	   "rtk port [status]\n"
	   "        - per cage: module PN, laser, SerDes mode, PCS link, MAC link + speed, media, LED\n"
	   "rtk sdsdump [sds | all]\n"
	   "        - SerDes 2-9 pages 0-7, 0x1f-0x2f (for reg_diff.py)\n"
	   "rtk mode\n"
	   "        - M1/M2/M3 front switch position (GPIO 17-19)\n"
	   "rtk temp\n"
	   "        - on-die temperature (enables the thermal meter if off)\n"
	   "rtk spg status | load .. | start .. | stop [off]\n"
	   "        - Smart Packet Generator, capped bursts on dark cage ports (#70; rtk spg = usage)\n"
	   "rtk help-ours\n"
	   "        - one-line list of the above\n"
	   "hidden stock verbs (work here, absent from stock help): port enable|disable <port>,\n"
	   "  comboport copper|fiber, phyreg dump-top|setbymask, port-isolation on|off;\n"
	   "  init, rtcore-init, send = not yet (need the Ethernet stage)\n"
	   "see also: highmem (RAM above 256 MiB), sf (read-only flash)\n");
