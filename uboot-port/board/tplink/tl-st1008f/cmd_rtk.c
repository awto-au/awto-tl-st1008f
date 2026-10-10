// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk`: stock-loader-compatible command surface (subset) on top of our DM drivers,
 * plus `rtk laser` and `rtk sfp`. Output strings match the stock loader where it has one
 * ("data 0x..", "OK") so the same scripts drive both.
 * Safety: module EEPROM (0x50) is never written; GPIO21 low = board reset (needs `force`).
 */

#include <command.h>
#include <dm.h>
#include <i2c.h>
#include <asm/gpio.h>
#include <linux/delay.h>
#include <vsprintf.h>

#define NCAGES		8
#define EXP_BUS		8	/* i2c alias of the laser expander bus */
#define EXP_ADDR	0x38
#define EXP_OUT		1	/* TCA9534A: 0 in, 1 out, 2 polarity, 3 config (1 = input) */
#define EXP_CFG		3
#define SFP_A0		0x50
#define SFP_A2		0x51
#define GPIO_RESET	21

static struct udevice *chip(int bus, int addr)
{
	struct udevice *dev;

	return i2c_get_chip_for_busnum(bus, addr, 1, &dev) ? NULL : dev;
}

/* stock `rtk i2c` device ids: 0-7 = cage EEPROM (0x50), 8 = laser expander */
static struct udevice *rtk_i2c_dev(int id, bool *is_sfp)
{
	*is_sfp = id < NCAGES;
	if (id >= 0 && id < NCAGES)
		return chip(id, SFP_A0);
	if (id == 8)
		return chip(EXP_BUS, EXP_ADDR);
	return NULL;
}

static int do_rtk_i2c(int argc, char *const argv[])
{
	struct udevice *dev;
	bool is_sfp;
	u8 b;

	if (argc >= 2 && !strcmp(argv[1], "init")) {
		printf("OK (buses come from the device tree; `init` is a no-op here)\n");
		return 0;
	}
	if (argc < 4)
		return CMD_RET_USAGE;
	dev = rtk_i2c_dev(dectoul(argv[2], NULL), &is_sfp);
	if (!dev) {
		printf("FAIL (-1)\n");
		return CMD_RET_FAILURE;
	}
	if (!strcmp(argv[1], "read")) {
		if (dm_i2c_read(dev, simple_strtoul(argv[3], NULL, 0), &b, 1)) {
			printf("FAIL (-1)\n");
			return CMD_RET_FAILURE;
		}
		printf("data 0x%x\n", b);
		return 0;
	}
	if (!strcmp(argv[1], "write") && argc >= 5) {
		if (is_sfp) {
			printf("refused: module EEPROM is read-only here\n");
			return CMD_RET_FAILURE;
		}
		b = simple_strtoul(argv[4], NULL, 0);
		if (dm_i2c_write(dev, simple_strtoul(argv[3], NULL, 0), &b, 1)) {
			printf("FAIL (-1)\n");
			return CMD_RET_FAILURE;
		}
		printf("OK\n");
		return 0;
	}
	return CMD_RET_USAGE;
}

static int gpio_line(int pin, struct gpio_desc *d)
{
	char name[12];

	snprintf(name, sizeof(name), "gpio%d", pin);
	return dm_gpio_lookup_name(name, d);
}

static int do_rtk_pin(bool set, int argc, char *const argv[])
{
	struct gpio_desc d;
	int pin, v;

	if (argc < (set ? 3 : 2))
		return CMD_RET_USAGE;
	pin = dectoul(argv[1], NULL);
	if (!set) {	/* read without claiming: lines owned by gpio-keys/i2c-gpio stay readable */
		if (gpio_line(pin, &d)) {
			printf("FAIL (-1)\n");
			return CMD_RET_FAILURE;
		}
		printf("data 0x%x\n", gpio_get_ops(d.dev)->get_value(d.dev, d.offset));
		return 0;
	}
	if (gpio_line(pin, &d) || dm_gpio_request(&d, "rtk")) {
		printf("FAIL (-1)\n");
		return CMD_RET_FAILURE;
	}
	if (set) {
		v = dectoul(argv[2], NULL);
		if (pin == GPIO_RESET && !v && (argc < 4 || strcmp(argv[3], "force"))) {
			printf("refused: GPIO21 low resets the board (add `force`)\n");
			dm_gpio_free(d.dev, &d);
			return CMD_RET_FAILURE;
		}
		dm_gpio_set_dir_flags(&d, GPIOD_IS_OUT | (v ? GPIOD_IS_OUT_ACTIVE : 0));
		printf("OK\n");
	} else {
		printf("data 0x%x\n", dm_gpio_get_value(&d));
	}
	dm_gpio_free(d.dev, &d);
	return 0;
}

/* Laser TX-disable: expander pin N = cage N+1, 1 = laser off. One-cage default (cage loop #19). */
static int do_rtk_laser(int argc, char *const argv[])
{
	struct udevice *dev = chip(EXP_BUS, EXP_ADDR);
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
 * 0x20 in compliance bytes 3-5/7-10, rate byte 12 and options byte 64. Detect (>=4 of the
 * 8 compliance bytes == 0x20) and treat those 0x20 bytes as 0 before decoding. */
static bool sfp_space_padded(u8 *id)
{
	int i, n = 0;

	for (i = 3; i <= 10; i++)
		n += id[i] == 0x20;
	if (n < 4)
		return false;
	for (i = 3; i <= 10; i++)
		if (id[i] == 0x20)
			id[i] = 0;
	if (id[12] == 0x20)
		id[12] = 0;
	if (id[64] == 0x20)
		id[64] = 0;
	return true;
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

	if (gpio_line(cage - 1, &d))
		return -1;
	return !gpio_get_ops(d.dev)->get_value(d.dev, d.offset);
}

static int sfp_one(int cage)
{
	struct udevice *a0 = chip(cage - 1, SFP_A0), *a2 = chip(cage - 1, SFP_A2);
	static const char *const plevel[] = { "1 (1.0 W)", "2 (1.5 W)", "3 (2.0 W)", "3 (2.0 W)" };
	static const char *const rmode[] = { "", " [50 kHz: module clock-stretches]",
					     " [byte-wise: module clock-stretches]" };
	u8 id[96], dm[10];
	int t, mode, pres = sfp_present(cage);
	bool cc_base, cc_ext, padded;

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
	if (!(id[92] & 0x40)) {
		printf("  ddm   not implemented (A0 byte 92 = 0x%02x)\n", id[92]);
		return 0;
	}
	if (!a2 || sfp_read(a2, 96, dm, sizeof(dm), &mode)) {
		printf("  ddm   declared but A2 (0x51) did not answer\n");
		return 0;
	}
	t = (s16)(dm[0] << 8 | dm[1]);		/* 1/256 C, internal calibration (byte 92 bit 5) */
	printf("  ddm   %s cal: temp %d.%02u C, vcc %u.%04u V, bias %u.%03u mA, tx %u.%04u mW, rx %u.%04u mW\n",
	       id[92] & 0x10 ? "external" : "internal",
	       t / 256, (unsigned int)(abs(t) % 256) * 100 / 256,
	       (dm[2] << 8 | dm[3]) / 10000, (dm[2] << 8 | dm[3]) % 10000,
	       (dm[4] << 8 | dm[5]) * 2 / 1000, (dm[4] << 8 | dm[5]) * 2 % 1000,
	       (dm[6] << 8 | dm[7]) / 10000, (dm[6] << 8 | dm[7]) % 10000,
	       (dm[8] << 8 | dm[9]) / 10000, (dm[8] << 8 | dm[9]) % 10000);
	return 0;
}

static int do_rtk_sfp(int argc, char *const argv[])
{
	int c;

	if (argc >= 2)
		return sfp_one(dectoul(argv[1], NULL));
	for (c = 1; c <= NCAGES; c++)
		sfp_one(c);
	return 0;
}

static int do_rtk(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	if (argc < 2)
		return CMD_RET_USAGE;
	if (!strcmp(argv[1], "i2c"))
		return do_rtk_i2c(argc - 1, argv + 1);
	if (!strcmp(argv[1], "pinGet"))
		return do_rtk_pin(false, argc - 1, argv + 1);
	if (!strcmp(argv[1], "pinSet"))
		return do_rtk_pin(true, argc - 1, argv + 1);
	if (!strcmp(argv[1], "laser"))
		return do_rtk_laser(argc - 1, argv + 1);
	if (!strcmp(argv[1], "sfp"))
		return do_rtk_sfp(argc - 1, argv + 1);
	if (!strcmp(argv[1], "network")) {
		printf("not yet: no RTL930x ethernet driver in this U-Boot (stage 4)\n");
		return CMD_RET_FAILURE;
	}
	if (!strcmp(argv[1], "boardmodel")) {
		printf("%s\n", ofnode_read_string(ofnode_root(), "model"));
		return 0;
	}
	return CMD_RET_USAGE;
}

U_BOOT_CMD(rtk, 6, 0, do_rtk, "Realtek board commands (stock-compatible subset)",
	   "i2c read <dev> <reg>          - dev 0-7 = cage EEPROM 0x50, 8 = laser expander\n"
	   "rtk i2c write <dev> <reg> <data>  - expander only (module EEPROM refused)\n"
	   "rtk pinGet <pin> | rtk pinSet <pin> <0|1> [force]\n"
	   "rtk laser [status|<cage>|none|all force]  - TX enable, one cage by default\n"
	   "rtk sfp [cage]               - module ID + live DDM\n"
	   "rtk boardmodel | rtk network on (not yet)");
