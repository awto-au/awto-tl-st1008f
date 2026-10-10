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

/* Block read; on failure fall back to single bytes. MCU-emulated EEPROMs (10GBASE-T copper)
 * clock-stretch on multi-byte reads, which this master cannot follow; single bytes work. */
static int sfp_read(struct udevice *dev, u8 reg, u8 *buf, int len, bool *bytewise)
{
	int i;

	*bytewise = false;
	if (!dm_i2c_read(dev, reg, buf, len))
		return 0;
	*bytewise = true;
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

static int sfp_one(int cage)
{
	struct udevice *a0 = chip(cage - 1, SFP_A0), *a2 = chip(cage - 1, SFP_A2);
	static const char *const plevel[] = { "1 (1.0 W)", "2 (1.5 W)", "3 (2.0 W)", "3 (2.0 W)" };
	u8 id[96], dm[10];
	bool slow;
	int t;

	if (!a0 || sfp_read(a0, 0, id, sizeof(id), &slow)) {
		printf("cage %d: empty\n", cage);
		return 0;
	}
	printf("cage %d: id 0x%02x, %d00 Mbd, %u nm%s\n", cage, id[0], id[12],
	       id[60] << 8 | id[61], slow ? " (byte-wise reads: module clock-stretches)" : "");
	sfp_str("vendor", id + 20, 16);
	sfp_str("pn    ", id + 40, 16);
	sfp_str("date  ", id + 84, 6);
	/* SFF-8472 byte 64: bit 1 = power level 2 declared, bit 5 = level 3 (Linux sfp.c) */
	printf("  power level %s declared\n",
	       plevel[(id[64] & 0x02 ? 1 : 0) | (id[64] & 0x20 ? 2 : 0)]);
	if (!(id[92] & 0x40) || !a2 || dm_i2c_read(a2, 96, dm, sizeof(dm))) {
		printf("  ddm   not implemented\n");
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
