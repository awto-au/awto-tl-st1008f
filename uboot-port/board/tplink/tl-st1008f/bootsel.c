// SPDX-License-Identifier: GPL-2.0+
/*
 * Default boot (#73, #117, docs/DEFAULT-BOOT.md#ab-slots): A/B slots. Linux writes `bootstate`
 * (good + trial slot); a trial slot gets MAX_ATTEMPTS unconfirmed boots, then the good slot boots.
 * No flash writes here: stock env + bootstate are read, the attempt counter lives in reserved RAM,
 * the SoC watchdog covers bootm -> kernel watchdog.
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
#define SLOT_A_OFF	0x0300000	/* `firmware_a`; stock boota boots it too */
#define SLOT_B_OFF	0x1180000	/* `firmware_b` */
#define SLOT_SIZE	0x0e80000	/* 14.5 MiB each */
#define BOOTSTATE_OFF	0x02f0000	/* `bootstate`: "S1AB g=a t=b c=<crc32 of 12 bytes>" */
#define STOCK_ENV_OFF	0x00e0000	/* `u-boot-env`; Linux nvmem reads the MAC from it */
#define STOCK_ENV_SIZE	0x10000
#define FLAG_VAR	"st1008f_boot"	/* prompt | good (ignore a trial slot) */
#define RTK_MAGIC	0x93030000

/* phys 0x0e000000: reserved-memory (no-map) in both kernels' DTS; above bootm and below U-Boot */
#define REC		((u32 __iomem *)0xae000000)
#define REC_MAGIC	0x5b007ec0
#define MAX_ATTEMPTS	2	/* trial boots not confirmed by Linux before the good slot */

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
 * bootargs: Linux reads st1008f.mode (switch position), st1008f.slot (a|b: which slot it splits, 300-33)
 * and st1008f.boot (good | trial | legacy) (docs/DEFAULT-BOOT.md) */
#define ARGS		"setenv bootargs st1008f.mode=m%d st1008f.slot=%c st1008f.boot=%s; "
/* Failed-autoboot prompt: waits for a person to start typing, expected <= 240 s (owner OK 2026-10-13),
 * x1.25 = 300 s; expiry = reset (RESET_TO_RETRY) -> attempt count -> good slot (#105). Set by bootcmd
 * itself, so an ESC prompt never times out. */
#define BOOT_IDLE	"setenv bootretry 300; "
/* `bootsel fast` arms the wdt, then `clocks fast` (#101). Legacy (no bootstate: image may lack the
 * kernel wdt handover) disarms before bootm; good/trial keep it through bootm -> kernel wdt. */
#define BOOT_HEAD	BOOT_IDLE "rtk led boot-end; bootsel fast; "
#define BOOT_TAIL	"bootsel wdt off; rtk led error bootm"

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

/* Turbo profile (#46): stock env `st1008f_turbo=cpu=1100,ddr=650,lx=175,sram=500` (MHz, any subset;
 * missing = keep/stock); spi accepted at stock 25 only (#50). Autoboot applies it in M3 only; the
 * `turbo` command in any mode. */
#define TURBO_VAR	"st1008f_turbo"
#define TURBO_MAX	64	/* value incl. NUL; longer = refused */

/* NULL = parsed; else why not. Bounded: <= 63 chars, values <= 4 digits */
static const char *turbo_parse(char *s, struct otto_turbo *t)
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
		else if (!strcmp(kv, "sram"))
			t->sram = n;
		else if (strcmp(kv, "spi") || n != 25)
			return "unknown key, or spi not at stock 25 (#50: Linux reads flash)";
	}
	return NULL;
}

/* Parse + check `s` (destroyed); NULL = ready to apply */
static const char *turbo_get(char *s, struct otto_turbo *t)
{
	return turbo_parse(s, t) ?: otto_turbo_check(t);
}

/* Apply; CPU still off its PLL after the revert = unknown clock: reset (`rec` = boot record kept) */
static int turbo_run(const struct otto_turbo *t)
{
	struct otto_clocks c;
	int ret = otto_turbo(t);

	otto_clocks_read(&c);
	if (!c.cpu_on_pll) {
		puts("turbo: CPU not on its PLL after the change and the revert: reset\n");
		do_reset(NULL, 0, 0, NULL);
	}
	return ret;
}

static void wdt_on(u32 ms);

/* M3: turbo profile from the stock env; M1/M2/invalid: stock clocks (#46). A failure never stops the boot. */
static int clk_fast(void)
{
	char val[TURBO_MAX] = "", raw[TURBO_MAX];
	int mode = st1008f_boot_mode(NULL);
	struct otto_turbo t;
	const char *why;
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
	why = turbo_get(val, &t);
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
	printf("bootsel: M3: turbo cpu %u ddr %u lx %u sram %u (0 = keep)\n", t.cpu, t.ddr, t.lx, t.sram);
	/* KSEG1: in DRAM before the change; a reset in turbo_run keeps it -> next boot stock. If the
	 * reset returns, the wdt armed above expires */
	__raw_writel(REC_CLK_MAGIC, REC_CLK);
	ret = turbo_run(&t);
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

enum { SEL_LEGACY, SEL_PROMPT, SEL_GOOD, SEL_TRIAL };
static const char *fb_auto;	/* good slot chosen by a fault (not the owner flag): LED latch tag */
static const char *const sel_name[] = { "legacy", "prompt", "good", "trial" };

static ulong slot_off(char slot)
{
	return slot == 'b' ? SLOT_B_OFF : SLOT_A_OFF;
}

/* bootstate written by Linux (st1008f-slot): good + trial ('-' = none); false = no valid record */
static bool bootstate(char *good, char *trial)
{
	const char *r = (const char *)(FLASH + BOOTSTATE_OFF);
	char hex[9];

	if (memcmp(r, "S1AB g=", 7) || memcmp(r + 8, " t=", 3) || memcmp(r + 12, " c=", 3))
		return false;
	if ((r[7] != 'a' && r[7] != 'b') || (r[11] != 'a' && r[11] != 'b' && r[11] != '-'))
		return false;
	memcpy(hex, r + 15, 8);
	hex[8] = 0;
	if (hextoul(hex, NULL) != crc32(0, (const u8 *)r, 12))
		return false;
	*good = r[7];
	*trial = r[11] == r[7] ? '-' : r[11];
	return true;
}

/* Slot decision for a chained boot; the mode switch picks clocks only (#46: M3 = turbo), not the
 * slot. `why` = reason; *slot = the slot to boot, *other = the inline fallback ('-' = none) */
static int decide(char *slot, char *other, char *why, int len, bool count)
{
	char flag[16] = "", good, trial;
	u32 n;

	*slot = 'a';
	*other = '-';
	st1008f_stock_env(FLAG_VAR, flag, sizeof(flag));
	if (!strcmp(flag, "prompt")) {
		snprintf(why, len, "stock env %s=prompt", FLAG_VAR);
		return SEL_PROMPT;
	}
	if (!bootstate(&good, &trial)) {
		snprintf(why, len, "no bootstate record: slot a as before A/B");
		return SEL_LEGACY;
	}
	*slot = good;
	if (!slot_ok(slot_off(good), SLOT_SIZE, NULL) && slot_ok(slot_off(good ^ 'a' ^ 'b'), SLOT_SIZE, NULL)) {
		*slot = good ^ 'a' ^ 'b';	/* a <-> b */
		snprintf(why, len, "good slot %c uImage header bad", good);
		fb_auto = "good-bad";
		return SEL_GOOD;
	}
	if (trial == '-' || !strcmp(flag, "good")) {
		snprintf(why, len, "slot %c good%s", good, trial == '-' ? "" : " (stock env flag: trial ignored)");
		return SEL_GOOD;
	}
	if (!slot_ok(slot_off(trial), SLOT_SIZE, NULL)) {
		snprintf(why, len, "trial slot %c uImage header bad", trial);
		fb_auto = "trial-bad";
		return SEL_GOOD;
	}
	n = rec_attempts();
	if (n >= MAX_ATTEMPTS) {
		snprintf(why, len, "%u trial boots of slot %c not confirmed by Linux", n, trial);
		fb_auto = "unconfirmed";
		return SEL_GOOD;
	}
	if (count)
		rec_set(n + 1);
	*slot = trial;
	*other = good;
	snprintf(why, len, "trial slot %c attempt %u/%u, fallback slot %c", trial, n + 1, MAX_ATTEMPTS, good);
	return SEL_TRIAL;
}

/* board_late_init, chained boot (mode 1-3, invalid passed as 1): set bootcmd, bootargs, bootdelay */
int st1008f_bootsel(int mode)
{
	char why[96], cmd[512], slot, other;
	int s = decide(&slot, &other, why, sizeof(why), true), n;

	printf("Boot:  %s (%s)\n", sel_name[s], why);
	if (fb_auto)
		rtk_led_fallback(fb_auto);
	if (s == SEL_PROMPT)
		return 0;
	n = snprintf(cmd, sizeof(cmd), BOOT_HEAD);
	if (s == SEL_LEGACY)
		n += snprintf(cmd + n, sizeof(cmd) - n, "bootsel wdt off; ");
	n += snprintf(cmd + n, sizeof(cmd) - n, ARGS "bootm 0x%08lx; ", mode, slot, sel_name[s],
		      FLASH + slot_off(slot));
	if (other != '-')	/* trial image did not start: the good slot, watchdog re-armed */
		n += snprintf(cmd + n, sizeof(cmd) - n, "bootsel wdt on; rtk led fallback bootm-trial; "
			      ARGS "bootm 0x%08lx; ", mode, other, "good", FLASH + slot_off(other));
	snprintf(cmd + n, sizeof(cmd) - n, BOOT_TAIL);
	env_set("bootcmd", cmd);
	/* owner #46: 2 s window, ESC only (CONFIG_AUTOBOOT_STOP_STR); no env key may replace it */
	env_set("bootdelay", "2");
	env_set("bootstopkey", NULL);
	env_set("bootdelaykey", NULL);
	return 0;
}

static int do_bootsel(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	char name[IH_NMLEN + 1], why[96], f[16], good, trial, slot, other;
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
	printf("slot a 0x%07x: %s\n", SLOT_A_OFF, slot_ok(SLOT_A_OFF, SLOT_SIZE, name) ? name : "no valid uImage");
	printf("slot b 0x%07x: %s\n", SLOT_B_OFF, slot_ok(SLOT_B_OFF, SLOT_SIZE, name) ? name : "no valid uImage");
	if (bootstate(&good, &trial))
		printf("bootstate: good %c, trial %c\n", good, trial);
	else
		puts("bootstate: none\n");
	printf("stock env %s: %s\n", FLAG_VAR, st1008f_stock_env(FLAG_VAR, f, sizeof(f)) ?: "(unset)");
	printf("record: %s, attempts %u (max %u)\n", rec_valid() ? "valid" : "invalid", rec_attempts(),
	       MAX_ATTEMPTS);
	printf("wdt ctrl: %08x\n", __raw_readl((void __iomem *)(WDT + 8)));
	mode = st1008f_boot_mode(NULL) ?: 1;
	s = decide(&slot, &other, why, sizeof(why), false);
	printf("chained boot now: M%d -> %s, slot %c (%s)\n", mode, sel_name[s], slot, why);
	return 0;
}

U_BOOT_CMD(bootsel, 3, 0, do_bootsel, "A/B slot selection (#117, docs/DEFAULT-BOOT.md)",
	   "          - slots, bootstate, stock env flag, attempt record, decision (read-only)\n"
	   "bootsel clear      - attempt record = 0 (RAM)\n"
	   "bootsel fast       - `clocks fast`, skipped once after a boot whose change never finished\n"
	   "bootsel wdt on|off|<ms> - SoC watchdog, SoC reset on expiry (on = boot value)");

/* `turbo` at the prompt, any mode (#46): stored profile, `show`, or ad-hoc key=value args (env untouched) */
static int do_turbo(struct cmd_tbl *cmdtp, int flag, int argc, char *const argv[])
{
	char val[TURBO_MAX] = "", raw[TURBO_MAX] = "";
	struct otto_turbo t, l;
	const char *why;
	int i;

	if (argc == 2 && !strcmp(argv[1], "show")) {
		otto_turbo_live(&l);
		printf("turbo: " TURBO_VAR "=%s\n", st1008f_stock_env(TURBO_VAR, val, sizeof(val)) ?: "(unset = stock)");
		printf("turbo: live cpu %u mem %u lx %u sram %u MHz (stock 800 600 175 250)\n", l.cpu, l.ddr, l.lx,
		       l.sram);
		return 0;
	}
	if (argc == 1) {
		if (!st1008f_stock_env(TURBO_VAR, val, sizeof(val))) {
			puts("turbo: no " TURBO_VAR " in the stock env (or env CRC bad): nothing changed\n");
			return CMD_RET_FAILURE;
		}
	} else {
		for (i = 1; i < argc; i++) {	/* `turbo cpu=1400 ddr=662` = "cpu=1400,ddr=662" */
			if (strlen(val) + strlen(argv[i]) + 2 > sizeof(val)) {
				puts("turbo: profile too long\n");
				return CMD_RET_USAGE;
			}
			if (i > 1)
				strcat(val, ",");
			strcat(val, argv[i]);
		}
	}
	strlcpy(raw, val, sizeof(raw));
	why = turbo_get(val, &t);
	if (why) {
		printf("turbo: %s: %s: nothing changed\n", raw, why);
		return CMD_RET_FAILURE;
	}
	return turbo_run(&t) ? CMD_RET_FAILURE : 0;
}

U_BOOT_CMD(turbo, 8, 0, do_turbo, "clock profile now, any mode (#46, docs/DEFAULT-BOOT.md)",
	   "            - apply the stored " TURBO_VAR " profile\n"
	   "turbo show       - stored profile + live clocks\n"
	   "turbo cpu=N [ddr=N] [lx=N] [sram=N] - apply ad hoc (MHz; env untouched); FAIL = reverted");
