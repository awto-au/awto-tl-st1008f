// SPDX-License-Identifier: GPL-2.0+
/*
 * Default boot (#73, docs/DEFAULT-BOOT.md): primary = OpenWrt on 7.3 in `firmware`, fallback =
 * OpenWrt initramfs in `recovery`. Chained boot only. No flash writes: stock env is read, the
 * attempt counter lives in reserved RAM, the SoC watchdog covers bootm -> kernel watchdog.
 */

#include <command.h>
#include <env.h>
#include <image.h>
#include <malloc.h>
#include <u-boot/crc.h>
#include <asm/io.h>
#include <asm/unaligned.h>
#include <linux/bitfield.h>
#include <linux/kernel.h>
#include <mach/otto.h>
#include "rtk.h"

#define FLASH		0xb4000000UL	/* mmio window, KSEG1 */
#define PRIMARY_OFF	0x0300000	/* `firmware`, 22 MiB after the split */
#define PRIMARY_SIZE	0x1600000
#define FALLBACK_OFF	0x1900000	/* `recovery`, 7 MiB */
#define FALLBACK_SIZE	0x0700000
#define STOCK_ENV_OFF	0x00e0000	/* `u-boot-env`; Linux nvmem reads the MAC from it */
#define STOCK_ENV_SIZE	0x10000
#define FLAG_VAR	"st1008f_boot"	/* primary | fallback | prompt */
#define RTK_MAGIC	0x93030000

/* phys 0x0e000000: reserved-memory (no-map) in both kernels' DTS; above bootm and below U-Boot */
#define REC		((u32 __iomem *)0xae000000)
#define REC_MAGIC	0x5b007ec0
#define MAX_ATTEMPTS	2	/* primary boots not confirmed by Linux before the fallback */

#define WDT		0xb8003260UL	/* SoC watchdog (Linux realtek_otto_wdt) */
#define WDT_CNTR_PING	BIT(31)
#define WDT_INTR_ALL	(BIT(31) | BIT(30))
#define WDT_EN		BIT(31)
#define WDT_PRESCALE	GENMASK(30, 29)
#define WDT_PHASE1	GENMASK(26, 22)
#define WDT_PHASE2	GENMASK(19, 15)
#define WDT_TICKS_MAX	33	/* phase1 32 + phase2 1 */
/* bootm -> kernel wdt probe: ~9 s expected (flash read + LZMA at stock SPI), x1.25 + rounding */
#define BOOT_WDT_MS	12000

#define BOOT_PRIMARY	"clocks fast; bootsel wdt on; bootm 0xb4300000; bootsel wdt off; bootm 0xb5900000"
#define BOOT_FALLBACK	"clocks fast; bootsel wdt on; bootm 0xb5900000; bootsel wdt off"
#define BOOT_LEGACY	"clocks fast; bootm 0xb4300000"

/* uImage header in flash: magic (std or Realtek), header CRC, payload fits the slot */
static bool slot_ok(ulong off, ulong size, char *name)
{
	struct legacy_img_hdr h;
	u32 magic, hcrc;

	memcpy(&h, (void *)(FLASH + off), sizeof(h));
	magic = be32_to_cpu(h.ih_magic);
	hcrc = be32_to_cpu(h.ih_hcrc);
	h.ih_hcrc = 0;
	if ((magic != IH_MAGIC && magic != RTK_MAGIC) || crc32(0, (u8 *)&h, sizeof(h)) != hcrc ||
	    sizeof(h) + be32_to_cpu(h.ih_size) > size)
		return false;
	if (name)
		strlcpy(name, (char *)h.ih_name, IH_NMLEN + 1);
	return true;
}

/* Value of `var` in the stock env (CRC-checked copy), or NULL */
static char *stock_env(const char *var, char *out, int len)
{
	u8 *e = malloc(STOCK_ENV_SIZE);
	u32 crc, want;
	char *p, *ret = NULL;
	int n = strlen(var);

	if (!e)
		return NULL;
	memcpy(e, (void *)(FLASH + STOCK_ENV_OFF), STOCK_ENV_SIZE);
	crc = crc32(0, e + 4, STOCK_ENV_SIZE - 4);
	want = get_unaligned_be32(e);
	if (crc == want || crc == get_unaligned_le32(e)) {
		e[STOCK_ENV_SIZE - 1] = 0;
		for (p = (char *)e + 4; *p; p += strlen(p) + 1)
			if (!strncmp(p, var, n) && p[n] == '=') {
				strlcpy(out, p + n + 1, len);
				ret = out;
				break;
			}
	}
	free(e);
	return ret;
}

static bool rec_valid(void)
{
	return __raw_readl(REC) == REC_MAGIC && __raw_readl(REC + 2) == ~__raw_readl(REC + 1);
}

static u32 rec_attempts(void)
{
	return rec_valid() ? __raw_readl(REC + 1) : 0;	/* invalid = cold boot */
}

static void rec_set(u32 attempts)
{
	__raw_writel(attempts, REC + 1);
	__raw_writel(~attempts, REC + 2);
	__raw_writel(REC_MAGIC, REC);
}

static void wdt_on(u32 ms)
{
	struct otto_clocks c;
	u32 p, tick = 0, total = 0;

	otto_clocks_read(&c);
	for (p = 0; p <= 3; p++) {	/* smallest prescale that fits, as the Linux driver */
		tick = DIV_ROUND_CLOSEST(1U << (25 + p), c.lx_khz);
		total = max(2U, DIV_ROUND_UP(ms, tick));
		if (total <= WDT_TICKS_MAX)
			break;
	}
	if (p > 3) {
		p = 3;
		total = WDT_TICKS_MAX;
		printf("wdt: %u ms over the maximum, clamped\n", ms);
	}
	__raw_writel(WDT_INTR_ALL, (void __iomem *)(WDT + 4));
	__raw_writel(WDT_CNTR_PING, (void __iomem *)WDT);
	/* phase2 = 1 tick, reset mode 0 = SoC */
	__raw_writel(WDT_EN | FIELD_PREP(WDT_PRESCALE, p) | FIELD_PREP(WDT_PHASE1, total - 2),
		     (void __iomem *)(WDT + 8));
	printf("wdt: on, %u ms (prescale %u, %u x %u ms ticks at lx %u kHz), SoC reset on expiry\n",
	       total * tick, p, total, tick, c.lx_khz);
}

static void wdt_off(void)
{
	__raw_writel(0, (void __iomem *)(WDT + 8));
	__raw_writel(WDT_INTR_ALL, (void __iomem *)(WDT + 4));
}

enum { SEL_LEGACY, SEL_PROMPT, SEL_PRIMARY, SEL_FALLBACK };
static const char *const sel_name[] = { "legacy", "prompt", "primary", "fallback" };

/* Decision for a chained boot at mode switch position `mode` (1-3); `why` gets the reason */
static int decide(int mode, char *why, int len, bool count)
{
	char flag[16] = "";
	u32 n;

	if (!slot_ok(FALLBACK_OFF, FALLBACK_SIZE, NULL)) {
		snprintf(why, len, "no image in recovery slot: single-image boot as before");
		return mode == 3 ? SEL_PROMPT : SEL_LEGACY;
	}
	if (mode == 3) {
		snprintf(why, len, "mode switch M3");
		return SEL_FALLBACK;
	}
	stock_env(FLAG_VAR, flag, sizeof(flag));
	if (!strcmp(flag, "prompt") || !strcmp(flag, "fallback")) {
		snprintf(why, len, "stock env %s=%s", FLAG_VAR, flag);
		return strcmp(flag, "prompt") ? SEL_FALLBACK : SEL_PROMPT;
	}
	if (!slot_ok(PRIMARY_OFF, PRIMARY_SIZE, NULL)) {
		snprintf(why, len, "primary uImage header bad");
		return SEL_FALLBACK;
	}
	n = rec_attempts();
	if (n >= MAX_ATTEMPTS) {
		snprintf(why, len, "%u primary boots not confirmed by Linux", n);
		return SEL_FALLBACK;
	}
	if (count)
		rec_set(n + 1);
	snprintf(why, len, "attempt %u/%u%s", n + 1, MAX_ATTEMPTS, n ? "" : " (cold boot or confirmed)");
	return SEL_PRIMARY;
}

/* board_late_init, chained boot at M1/M3/invalid: set bootcmd + bootdelay */
int st1008f_bootsel(int mode)
{
	char why[96];
	int s = decide(mode, why, sizeof(why), true);

	printf("Boot:  %s (%s)\n", sel_name[s], why);
	if (s == SEL_PROMPT)
		return 0;
	env_set("bootcmd", s == SEL_LEGACY ? BOOT_LEGACY : s == SEL_PRIMARY ? BOOT_PRIMARY : BOOT_FALLBACK);
	env_set("bootdelay", "1");
	return 0;
}

static int do_bootsel(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	char name[IH_NMLEN + 1], why[96], f[16];
	int mode, s;

	if (argc == 3 && !strcmp(argv[1], "wdt")) {
		if (!strcmp(argv[2], "off"))
			wdt_off();
		else
			wdt_on(!strcmp(argv[2], "on") ? BOOT_WDT_MS : dectoul(argv[2], NULL));
		return 0;
	}
	if (argc == 2 && !strcmp(argv[1], "clear")) {
		rec_set(0);
		return 0;
	}
	if (argc != 1)
		return CMD_RET_USAGE;
	printf("primary  0x%07x: %s\n", PRIMARY_OFF,
	       slot_ok(PRIMARY_OFF, PRIMARY_SIZE, name) ? name : "no valid uImage");
	printf("fallback 0x%07x: %s\n", FALLBACK_OFF,
	       slot_ok(FALLBACK_OFF, FALLBACK_SIZE, name) ? name : "no valid uImage");
	printf("stock env %s: %s\n", FLAG_VAR, stock_env(FLAG_VAR, f, sizeof(f)) ?: "(unset)");
	printf("record: %s, attempts %u (max %u)\n", rec_valid() ? "valid" : "invalid", rec_attempts(),
	       MAX_ATTEMPTS);
	printf("wdt ctrl: %08x\n", __raw_readl((void __iomem *)(WDT + 8)));
	mode = st1008f_boot_mode(NULL);
	s = mode == 2 ? SEL_PROMPT : decide(mode ? mode : 1, why, sizeof(why), false);
	printf("chained boot now: M%d -> %s (%s)\n", mode ? mode : 1, sel_name[s],
	       mode == 2 ? "M2 easy mode" : why);
	return 0;
}

U_BOOT_CMD(bootsel, 3, 0, do_bootsel, "default-boot selection (#73, docs/DEFAULT-BOOT.md)",
	   "          - slots, stock env flag, attempt record, decision (read-only)\n"
	   "bootsel clear      - attempt record = 0 (RAM)\n"
	   "bootsel wdt on|off|<ms> - SoC watchdog, SoC reset on expiry (on = boot value)");
