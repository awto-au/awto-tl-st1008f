// SPDX-License-Identifier: GPL-2.0+
/*
 * `busscan`: read-only scan for undocumented devices (#77, docs/BUS-SCAN.md).
 * i2c: probe 0x08-0x77 only (no general call / reserved addresses), then 16 B from reg 0.
 * spi: RDID 0x9f + RDSR 0x05 on one chip select; the driver allows CS1 nothing else.
 */

#include <command.h>
#include <console.h>
#include <dm.h>
#include <i2c.h>
#include <spi.h>
#include <vsprintf.h>

#define I2C_LO		0x08
#define I2C_HI		0x77
#define FIRST_READ	16

static void hex(const u8 *b, int n)
{
	while (n--)
		printf(" %02x", *b++);
	printf("\n");
}

/* Output lines are parsed by scripts/bus_scan.py: "i2cN 0xAA ack|data ..|read FAIL e". */
static int scan_i2c(int busnum, uint hz, bool rd)
{
	struct udevice *bus, *dev;
	uint old;
	int a, ret, n = 0;
	u8 buf[FIRST_READ];

	if (uclass_get_device_by_seq(UCLASS_I2C, busnum, &bus)) {
		printf("busscan: no i2c bus %d\n", busnum);
		return CMD_RET_FAILURE;
	}
	old = dm_i2c_get_bus_speed(bus);
	if (hz)
		dm_i2c_set_bus_speed(bus, hz);
	printf("i2c%d scan 0x%02x-0x%02x at %u Hz (%s)\n", busnum, I2C_LO, I2C_HI,
	       dm_i2c_get_bus_speed(bus), bus->name);
	for (a = I2C_LO; a <= I2C_HI; a++) {
		if (ctrlc())
			break;
		if (dm_i2c_probe(bus, a, 0, &dev))
			continue;
		n++;
		printf("i2c%d 0x%02x ack\n", busnum, a);
		if (!rd)
			continue;
		ret = dm_i2c_read(dev, 0, buf, sizeof(buf));
		if (ret) {
			printf("i2c%d 0x%02x read FAIL %d\n", busnum, a, ret);
			continue;
		}
		printf("i2c%d 0x%02x data", busnum, a);
		hex(buf, sizeof(buf));
	}
	if (hz)
		dm_i2c_set_bus_speed(bus, old);
	printf("i2c%d done: %d found\n", busnum, n);
	return 0;
}

static int spi_cmd(struct spi_slave *s, u8 op, u8 *in, int n)
{
	int ret = spi_xfer(s, 8, &op, NULL, SPI_XFER_BEGIN);

	return ret ? ret : spi_xfer(s, n * 8, NULL, in, SPI_XFER_END);
}

/* Bus 0 = flash controller (CS0 = boot flash, CS1 = ball E1). All-ff / all-00 = no slave. */
static int scan_spi(int csn)
{
	struct udevice *bus;
	struct spi_slave *s;
	u8 id[5], sr;
	int ret;

	if (csn < 0 || csn > 1)
		return CMD_RET_USAGE;
	ret = _spi_get_bus_and_cs(0, csn, 1000000, SPI_MODE_0, "spi_generic_drv",
				  csn ? "busscan-cs1" : "busscan-cs0", &bus, &s);
	if (ret) {
		printf("spi cs%d: no device (%d)\n", csn, ret);
		return CMD_RET_FAILURE;
	}
	ret = spi_claim_bus(s);
	if (ret) {
		printf("spi cs%d: claim FAIL %d\n", csn, ret);
		return CMD_RET_FAILURE;
	}
	ret = spi_cmd(s, 0x9f, id, sizeof(id));
	if (ret)
		printf("spi cs%d rdid FAIL %d\n", csn, ret);
	else {
		printf("spi cs%d rdid", csn);
		hex(id, sizeof(id));
	}
	ret = spi_cmd(s, 0x05, &sr, 1);
	if (ret)
		printf("spi cs%d rdsr FAIL %d\n", csn, ret);
	else
		printf("spi cs%d rdsr %02x\n", csn, sr);
	spi_release_bus(s);
	return 0;
}

static int do_busscan(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	if (argc >= 3 && !strcmp(argv[1], "i2c"))
		return scan_i2c(dectoul(argv[2], NULL),
				argc >= 4 ? dectoul(argv[3], NULL) : 0,
				!(argc >= 5 && !strcmp(argv[4], "noread")));
	if (argc >= 3 && !strcmp(argv[1], "spi"))
		return scan_spi(dectoul(argv[2], NULL));
	return CMD_RET_USAGE;
}

U_BOOT_CMD(busscan, 5, 0, do_busscan, "read-only I2C/SPI device scan (#77)",
	   "i2c <bus> [hz|0 [noread]]\n"
	   "    - probe 0x08-0x77; 16 B from reg 0 per responder; hz = temporary bus speed\n"
	   "busscan spi <cs>\n"
	   "    - flash controller CS0/CS1: RDID 0x9f (5 B) + RDSR 0x05\n");
