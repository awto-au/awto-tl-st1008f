/* SPDX-License-Identifier: GPL-2.0+ */
/* TP-Link TL-ST1008F v2 (RTL9303), stage 0 RAM chainload. */

#ifndef __CONFIG_TPLINK_TL_ST1008F_H__
#define __CONFIG_TPLINK_TL_ST1008F_H__

#define CFG_SYS_SDRAM_BASE	0x80000000 /* KSEG0 */
/* Init stack top 0x80f00000: below TEXT_BASE 0x81000000, above kernel load 0x80100000 */
#define CFG_SYS_INIT_SP_OFFSET	0x00f00000
/* UART clock = LX 175 MHz / 16 = 10.9375 MBd / divisor. High rates are the exact divisor
 * rates (div 6..1) so error is 0 on our side; the host adapter rounds to its own grid. */
#define CFG_SYS_BAUDRATE_TABLE	{ 9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600, \
				  1822916, 2187500, 2734375, 3645833, 5468750, 10937500 }
/* boardmodel: stock default, `rtk boardmodel` reads it; led_boot: rtk_led.c boot snake.
 * Net (#80): ethport = mgmt cage; IPs = st1008f-1-mgmt / TFTP host (awto-dan ip-registry.toml). */
#define CFG_EXTRA_ENV_SETTINGS	"boardmodel=RTL9303_8XGE\0" "led_boot=snake\0" \
				"ethport=1\0" "autoload=no\0" "ipaddr=192.168.25.56\0" \
				"netmask=255.255.255.0\0" "gatewayip=192.168.25.254\0" \
				"serverip=192.168.25.30\0"

#endif
