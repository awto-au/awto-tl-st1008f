/* SPDX-License-Identifier: GPL-2.0+ */
/* Shared bits of the `rtk` command (cmd_rtk*.c, rtk_*.c). */

#ifndef __RTK_H
#define __RTK_H

#include <linux/bitops.h>
#include <asm/io.h>
#include <linux/types.h>

#define NCAGES		8
#define SW_BASE		0xbb000000UL	/* switch core, KSEG1 */
#define GPIO_DAT	0xb800330cUL	/* gpio0 DATA */
#define NPORTS		29		/* SDK ports 0-27 + CPU 28 */
#define CPU_PORT	28

static inline u32 sw_r(u32 off)
{
	return __raw_readl((void __iomem *)(SW_BASE + off));
}

static inline void sw_w(u32 off, u32 v)
{
	__raw_writel(v, (void __iomem *)(SW_BASE + off));
}

static inline void sw_rmw(u32 off, u32 mask, u32 set)
{
	sw_w(off, (sw_r(off) & ~mask) | set);
}

/* cage 1..8 <-> SDK port / SerDes id (docs/hardware.md port table) */
extern const u8 rtk_cage_port[NCAGES];
static inline int rtk_cage_sds(int cage)
{
	return cage + 1;
}

/* SDK port exists (cage ports + CPU port) */
bool rtk_port_exists(unsigned int port);

struct udevice;
struct gpio_desc;
struct udevice *rtk_chip(int bus, int addr);

#define EXP_BUS		8	/* i2c alias of the laser expander bus */
#define EXP_ADDR	0x38
#define EXP_OUT		1	/* TCA9534A: 0 in, 1 out, 2 polarity, 3 config (1 = input) */
#define EXP_CFG		3
int rtk_gpio_line(int pin, struct gpio_desc *d);

/* stock `Usage:` block, returns CMD_RET_FAILURE */
int rtk_usage(void);

/* rtk_sds.c: SerDes indirect access (RTL930x), 0 = ok */
int rtk_sds_read(unsigned int sds, unsigned int page, unsigned int reg, u16 *val);
int rtk_sds_write(unsigned int sds, unsigned int page, unsigned int reg, u16 val);
int rtk_sds_mode(unsigned int sds);	/* SDS_MODE_SEL field, -1 if sds has none */

/* rtk_stock.c: stock-named verbs; each returns the stock return value */
int rtk_unit(int argc, char *const argv[]);
int rtk_port_admin(int argc, char *const argv[]);
int rtk_show(int argc, char *const argv[]);
int rtk_comboport(int argc, char *const argv[]);
int rtk_ext(int argc, char *const argv[]);
int rtk_phyreg(int argc, char *const argv[]);
int rtk_phymmd(int argc, char *const argv[]);
int rtk_sdsreg(int argc, char *const argv[]);
int rtk_macsds(int argc, char *const argv[]);
int rtk_board(int argc, char *const argv[]);
int rtk_ledtest(int argc, char *const argv[]);
int rtk_not_yet(const char *what);

void rtk_mac_mode_set(unsigned int sds, u32 val);	/* SDS_MODE_SEL field */

/* rtk_net.c: stock stage-4 verbs (network, 10g, macsds, port-isolation) */
int rtk_network(int argc, char *const argv[]);
int rtk_10g(int argc, char *const argv[]);
int rtk_macsds_apply(unsigned int sds, unsigned int mode);
int rtk_port_isolation(int argc, char *const argv[]);
int rtk_sdsdump(int argc, char *const argv[]);
bool rtk_net_is_on(void);
const char *rtk_media_name(int port);

/* rtk_sfpmode.c: SerDes interface Linux would pick for the module (sfp-bus.c, sfp.c quirks) */
enum rtk_if { RTK_IF_NA, RTK_IF_100BX, RTK_IF_1000BX, RTK_IF_SGMII, RTK_IF_2500BX, RTK_IF_10GR };
extern const char *const rtk_if_name[];
int rtk_sfp_iface(int cage, const char **why);	/* enum rtk_if, -1 = no module / unreadable */

/* cmd_rtk.c: A0 bytes 0-95 with the read fallbacks and the Cisco space-padding fix-up */
int rtk_sfp_read_id(int cage, u8 *id);

/* rtk_ours.c: commands that do not exist on the stock loader */
int rtk_port_status(int argc, char *const argv[]);
int rtk_mode(int argc, char *const argv[]);
int rtk_temp(int argc, char *const argv[]);
int rtk_ours_help(void);

/* rtk_sdstest.c: `rtk sds` SerDes test tools (#74) */
int rtk_sds_cmd(int argc, char *const argv[]);

/* board.c: mode switch boot policy (#46); 1-3 = M1-M3, 0 = invalid (treated as M1) */
int st1008f_boot_mode(u32 *pins);
const char *st1008f_mode_name(int mode);

/* bootsel.c: chained-boot selection primary/fallback (#73); sets bootcmd */
int st1008f_bootsel(int mode);

#endif
