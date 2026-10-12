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

#if !IS_ENABLED(CONFIG_AUTOBOOT_KEYED) || !IS_ENABLED(CONFIG_BOOT_RETRY)
#error "owner #46/#105: ESC-only autoboot stop and the prompt idle reset are not optional"
#endif

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
/* clocks fast (< 1 s) + bootm -> kernel wdt probe (~9 s: flash read + LZMA at stock SPI) = 10 s, x1.25 + rounding */
#define BOOT_WDT_MS	13000

/* led boot-end before the clock switch; led fallback/error only run when a bootm returned (#9).
 * bootargs: Linux reads st1008f.mode (switch position) + st1008f.boot (image) (docs/DEFAULT-BOOT.md) */
#define ARGS(img)	"setenv bootargs st1008f.mode=m%d st1008f.boot=" img "; "
/* `bootsel fast` arms the wdt, then `clocks fast` (#101): a hang in the clock change resets the SoC
 * and the next boot skips the overclock. Legacy (upstream kernel, no keep-running wdt patch) disarms
 * before bootm; primary/fallback keep it through bootm -> kernel wdt, re-armed for the fallback bootm. */
/* Prompt after a failed autoboot: reset after BOOT_IDLE_S without console input (RESET_TO_RETRY).
 * Set by bootcmd itself, so a stop-string prompt never times out. 300 s = time for someone at the
 * console to start typing; not a hardware wait. Expiry = reset -> attempt count -> fallback (#105). */
#define BOOT_IDLE	"setenv bootretry 300; "
#define BOOT_PRIMARY	BOOT_IDLE "rtk led boot-end; bootsel fast; " ARGS("primary") "bootm 0xb4300000; " \
			"bootsel wdt on; rtk led fallback bootm-primary; " ARGS("fallback") "bootm 0xb5900000; " \
			"bootsel wdt off; rtk led error bootm"
#define BOOT_FALLBACK	BOOT_IDLE "rtk led boot-end; bootsel fast; " ARGS("fallback") "bootm 0xb5900000; " \
			"bootsel wdt off; rtk led error bootm"
#define BOOT_LEGACY	BOOT_IDLE "rtk led boot-end; bootsel fast; bootsel wdt off; " ARGS("legacy") \
			"bootm 0xb4300000; rtk led error bootm"

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
char *st1008f_stock_env(const char *var, char *out, int len)
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

/* `bootsel fast` record: REC+3 = magic while the turbo change runs. Still set at the next boot = that
 * change never finished (watchdog reset) -> this boot stays at stock clocks; the one after retries */
#define REC_CLK		(REC + 3)
#define REC_CLK_MAGIC	0xc10cfa57

/* Turbo profile (#46): stock env `st1008f_turbo=cpu=1100,ddr=650,lx=175` (MHz, any subset; missing
 * = stock). sram/spi accepted at their stock values only. Applied in M3 only. */
#define TURBO_VAR	"st1008f_turbo"
#define TURBO_MAX	64	/* value incl. NUL; longer = refused */

struct turbo {
	u32 cpu, ddr, lx;
};

/* NULL = parsed; else why not. Bounded: <= 63 chars, values <= 4 digits */
static const char *turbo_parse(char *s, struct turbo *t)
{
	char *kv, *v, *end;
	u32 n;

	memset(t, 0, sizeof(*t));
	if (strlen(s) >= TURBO_MAX - 1)
		return "too long";
	while ((kv = strsep(&s, ","))) {
		v = strchr(kv, '=');
		if (!v)
			return "item without '='";
		*v++ = 0;
		n = simple_strtoul(v, &end, 10);
		if (end == v || *end || end - v > 4)
			return "value not a decimal MHz";
		if (!strcmp(kv, "cpu"))
			t->cpu = n;
		else if (!strcmp(kv, "ddr"))
			t->ddr = n;
		else if (!strcmp(kv, "lx"))
			t->lx = n;
		else if (!strcmp(kv, "sram") ? n != 250 : !strcmp(kv, "spi") ? n != 25 : 1)
			return "unknown key, or sram/spi not at stock (250 / 25: SRAM 500 not in this build, SPI #50)";
	}
	return NULL;
}

static void wdt_on(u32 ms);

/* M3: turbo profile from the stock env; M1/M2/invalid: stock clocks (#46). A failure never stops the boot. */
static int clk_fast(void)
{
	char val[TURBO_MAX] = "", raw[TURBO_MAX];
	int mode = st1008f_boot_mode(NULL);
	struct otto_clocks c;
	const char *why;
	struct turbo t;
	int ret;

	wdt_on(BOOT_WDT_MS);	/* every path: covers bootm -> kernel wdt probe */
	if (mode != 3) {
		printf("bootsel: M%d: stock clocks (turbo profile only in M3)\n", mode ?: 1);
		return 0;
	}
	if (!st1008f_stock_env(TURBO_VAR, val, sizeof(val))) {
		puts("bootsel: M3: no " TURBO_VAR " in the stock env (or env CRC bad): stock clocks\n");
		return 0;
	}
	strlcpy(raw, val, sizeof(raw));
	why = turbo_parse(val, &t);
	if (!why)
		why = otto_turbo_check(t.cpu, t.ddr, t.lx);
	if (why) {
		printf("bootsel: M3: " TURBO_VAR "=%s: %s: stock clocks\n", raw, why);
		rtk_led_fallback("turbo");
		return 0;
	}
	if (__raw_readl(REC_CLK) == REC_CLK_MAGIC) {
		__raw_writel(0, REC_CLK);
		puts("clocks: the last turbo change did not finish (reset during the change): stock clocks this boot\n");
		rtk_led_fallback("clocks");
		return 0;
	}
	printf("bootsel: M3: turbo cpu %u ddr %u lx %u (0 = stock)\n", t.cpu, t.ddr, t.lx);
	__raw_writel(REC_CLK_MAGIC, REC_CLK);	/* KSEG1: in DRAM before the change starts */
	ret = otto_turbo(t.cpu, t.ddr, t.lx);
	otto_clocks_read(&c);
	if (!c.cpu_on_pll) {
		/* no lock, restore failed too: REC_CLK stays set so the next boot skips the overclock;
		 * if the reset returns, the wdt armed above expires */
		puts("bootsel: CPU not on its PLL after the turbo change: reset\n");
		do_reset(NULL, 0, 0, NULL);
	}
	__raw_writel(0, REC_CLK);
	wdt_on(BOOT_WDT_MS);	/* again at the new LX: covers bootm -> kernel wdt probe */
	if (ret) {
		puts("bootsel: turbo change failed, booting at the clocks it left (CPU on its PLL)\n");
		rtk_led_fallback("clocks");
	}
	return ret;
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
static const char *fb_auto;	/* fallback chosen by a fault (not the owner flag): LED latch tag */
static const char *const sel_name[] = { "legacy", "prompt", "primary", "fallback" };

/* Image decision for a chained boot; the mode switch picks clocks only (#46: M3 = turbo), not the
 * image. `why` = reason */
static int decide(int mode, char *why, int len, bool count)
{
	char flag[16] = "";
	u32 n;

	if (!slot_ok(FALLBACK_OFF, FALLBACK_SIZE, NULL)) {
		snprintf(why, len, "no image in recovery slot: single-image boot as before");
		return SEL_LEGACY;
	}
	st1008f_stock_env(FLAG_VAR, flag, sizeof(flag));
	if (!strcmp(flag, "prompt") || !strcmp(flag, "fallback")) {
		snprintf(why, len, "stock env %s=%s", FLAG_VAR, flag);
		return strcmp(flag, "prompt") ? SEL_FALLBACK : SEL_PROMPT;
	}
	if (!slot_ok(PRIMARY_OFF, PRIMARY_SIZE, NULL)) {
		snprintf(why, len, "primary uImage header bad");
		fb_auto = "primary-bad";
		return SEL_FALLBACK;
	}
	n = rec_attempts();
	if (n >= MAX_ATTEMPTS) {
		snprintf(why, len, "%u primary boots not confirmed by Linux", n);
		fb_auto = "unconfirmed";
		return SEL_FALLBACK;
	}
	if (count)
		rec_set(n + 1);
	snprintf(why, len, "attempt %u/%u%s", n + 1, MAX_ATTEMPTS, n ? "" : " (cold boot or confirmed)");
	return SEL_PRIMARY;
}

/* board_late_init, chained boot (mode 1-3, invalid passed as 1): set bootcmd, bootargs, bootdelay */
int st1008f_bootsel(int mode)
{
	char why[96], cmd[384];
	int s = decide(mode, why, sizeof(why), true);

	printf("Boot:  %s (%s)\n", sel_name[s], why);
	if (fb_auto)
		rtk_led_fallback(fb_auto);
	if (s == SEL_PROMPT)
		return 0;
	if (s == SEL_PRIMARY)
		snprintf(cmd, sizeof(cmd), BOOT_PRIMARY, mode, mode);
	else
		snprintf(cmd, sizeof(cmd), s == SEL_LEGACY ? BOOT_LEGACY : BOOT_FALLBACK, mode);
	env_set("bootcmd", cmd);
	/* owner #46: 2 s window, ESC only (CONFIG_AUTOBOOT_STOP_STR); no env key may replace it */
	env_set("bootdelay", "2");
	env_set("bootstopkey", NULL);
	env_set("bootdelaykey", NULL);
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
	if (argc == 2 && !strcmp(argv[1], "fast"))
		return clk_fast() ? CMD_RET_FAILURE : 0;
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
	printf("stock env %s: %s\n", FLAG_VAR, st1008f_stock_env(FLAG_VAR, f, sizeof(f)) ?: "(unset)");
	printf("record: %s, attempts %u (max %u)\n", rec_valid() ? "valid" : "invalid", rec_attempts(),
	       MAX_ATTEMPTS);
	printf("wdt ctrl: %08x\n", __raw_readl((void __iomem *)(WDT + 8)));
	mode = st1008f_boot_mode(NULL) ?: 1;
	s = decide(mode, why, sizeof(why), false);
	printf("chained boot now: M%d -> %s (%s), bootargs st1008f.mode=m%d\n", mode, sel_name[s], why, mode);
	return 0;
}

U_BOOT_CMD(bootsel, 3, 0, do_bootsel, "default-boot selection (#73, docs/DEFAULT-BOOT.md)",
	   "          - slots, stock env flag, attempt record, decision (read-only)\n"
	   "bootsel clear      - attempt record = 0 (RAM)\n"
	   "bootsel fast       - `clocks fast`, skipped once after a boot whose change never finished\n"
	   "bootsel wdt on|off|<ms> - SoC watchdog, SoC reset on expiry (on = boot value)");
