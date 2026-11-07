// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk send` (hidden stock verb): CPU-sent test frame. Stock sends one fixed 74 B `pkt_content` with
 * NetSendPacket, then polls RX 80 times; its bytes and any arguments are unknown (docs/RTK-COMMANDS.md).
 * Ours: documented minimal version, same size, SPG safety guards (rtk_spg.c, docs/SPG.md).
 */

#include <command.h>
#include <env.h>
#include <vsprintf.h>
#include "rtk.h"

#define SEND_LEN	74		/* stock frame size */
#define SEND_CAP	1000		/* dark cage */
#define SEND_LIT_CAP	100		/* allow-lit */
#define SEND_MAX_MS	1000		/* CPU TX ~ tens of us per frame; 1000 frames << 1 s; expiry = stop + log */
#define SEND_RX_MS	10		/* RX poll after the burst, as loop probe (rtk_linkcheck.c) */
#define ETYPE		0x88b5		/* IEEE local experimental, as rtk spg */

/* rtk send [cage] [count] [allow-lit]: cage default env ethport, count default 1 */
int rtk_send(int argc, char *const argv[])
{
	static const u8 da[6] = { 0x02, 0x53, 0x45, 0x4e, 0x44, 0x00 };	/* unicast, locally administered */
	u8 f[SEND_LEN] = { 0 };
	unsigned long cage = env_get_ulong("ethport", 10, 1), count = 1, cap;
	bool allow = false;
	char why[48], *e;
	u32 sent, rx;
	int i, lit, ret, n = 0;

	if (!rtk_net_is_on()) {
		printf("send: run `rtk network on` first\n");
		return CMD_RET_FAILURE;
	}
	for (i = 2; i < argc; i++) {
		if (!strcmp(argv[i], "allow-lit")) {
			allow = true;
			continue;
		}
		if (n++ == 0) {
			cage = simple_strtoul(argv[i], &e, 10);
		} else if (n == 2) {
			count = simple_strtoul(argv[i], &e, 10);
		} else {
			return CMD_RET_USAGE;
		}
		if (*e)
			return CMD_RET_USAGE;
	}
	if (cage < 1 || cage > NCAGES) {
		printf("send: cage 1-%d\n", NCAGES);
		return CMD_RET_FAILURE;
	}
	lit = rtk_cage_lit(cage, why, sizeof(why));
	cap = lit ? SEND_LIT_CAP : SEND_CAP;
	if (lit && !allow) {
		printf("send: cage %lu LIT (%s): refused; allow-lit permits count <= %d\n", cage, why,
		       SEND_LIT_CAP);
		return CMD_RET_FAILURE;
	}
	if (!count || count > cap) {
		printf("send: count 1-%lu on a %s cage\n", cap, lit ? "lit" : "dark");
		return CMD_RET_FAILURE;
	}
	memcpy(f, da, 6);
	f[12] = ETYPE >> 8;
	f[13] = ETYPE & 0xff;
	for (i = 18; i < SEND_LEN; i++)
		f[i] = i - 18;
	printf("send: cage %lu (%s, %s): %lu x %d B, DA %pM, type 0x%04x, seq at byte 14, limit %d ms\n",
	       cage, lit ? "LIT, allow-lit" : "dark", why, count, SEND_LEN, f, ETYPE, SEND_MAX_MS);
	ret = rtl930x_eth_send_frames(cage, f, SEND_LEN, count, SEND_MAX_MS, SEND_RX_MS, &sent, &rx);
	printf("send: sent %u of %lu, rx %u in %d ms%s\n", sent, count, rx, SEND_RX_MS,
	       ret ? " (error)" : sent < count ? " (stopped: time limit or Ctrl-C)" : "");
	return ret || sent != count ? CMD_RET_FAILURE : 0;
}
