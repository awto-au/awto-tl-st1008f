// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk led`: the 24 port LEDs as a 3x8 matrix under software control; snake, boot indicator,
 * error latch. Registers: RTL9300 LED app note V1.0 Tables 1-20..1-22 (SW LED control).
 * Doc: docs/RTK-COMMANDS.md#port-leds. Touches LED registers 0xcc00-0xccd0 only.
 */

#include <bootm.h>
#include <command.h>
#include <console.h>
#include <cyclic.h>
#include <env.h>
#include <time.h>
#include <linux/delay.h>
#include <linux/string.h>
#include <vsprintf.h>
#include "rtk.h"

#define LED_GLB		RTL9300_LED_GLB_CTRL	/* [1:0] 1 = serial LED engine on */
#define LED_SW_LOAD	RTL9300_SW_LED_LOAD	/* bit 0: latch all SW registers (self-clear) */
#define LED_SW_EN(p)	RTL9300_LED_PORT_SW_EN_CTRL((p) >> 3)	/* 4 bits/port, bit n = LED n */
#define LED_SW_CTRL(p)	RTL9300_LED_PORT_SW_CTRL(p)	/* 3 bits/LED: copper [11:0], fibre [23:12] */
#define LED_FIRST	LED_GLB
#define LED_NREG	((LED_SW_CTRL(CPU_PORT) - LED_FIRST) / 4 + 1)
#define LED_LOAD_IDX	((LED_SW_LOAD - LED_FIRST) / 4)

enum { M_OFF, M_B32, M_B64, M_B128, M_B256, M_B512, M_B1024, M_ON };	/* SW_*_LEDn_MODE */
#define ROWS		3
#define COLS		NCAGES
#define RING		(2 * COLS + 2)	/* perimeter of the 3x8 matrix */
#define SNAKE_MS	60		/* step: 18-cell ring in ~1.1 s = one lap per 1 s countdown */
#define SNAKE_MIN_MS	10
/* boot snake self-stop if `led boot-end` never comes (countdown aborted): bootdelay x 1.25 */
#define BOOT_WIN_PCT	125

/* matrix -> hardware; SPEC until checked on the front panel. Env led_cols / led_rows override. */
static u8 col_cage[COLS] = { 1, 2, 3, 4, 5, 6, 7, 8 };
static u8 row_led[ROWS] = { 0, 1, 2 };
static u8 fb[ROWS][COLS];

static u32 start_snap[LED_NREG];
enum { L_NONE, L_FALLBACK, L_ERROR };	/* latch kinds; error outranks fallback */
static const char *const latch_name[] = { "off", "fallback", "error" };
static bool start_ok, boot_active, boot_touched;
static int latch;
static char err_why[40];
static struct cyclic_info boot_cyc;
static ulong boot_t0, boot_win_ms;
static int boot_pos;

static void snapshot(u32 *s)
{
	int i;

	for (i = 0; i < LED_NREG; i++)
		s[i] = sw_r(LED_FIRST + i * 4);
}

static void load(void)
{
	sw_w(LED_SW_LOAD, 1);
}

/* GLB last: a snapshot with the engine off stays dark until every field is back */
static void restore(const u32 *s)
{
	int i;

	for (i = LED_NREG - 1; i >= 0; i--)
		if (i != LED_LOAD_IDX)
			sw_w(LED_FIRST + i * 4, s[i]);
	load();
}

/* engine off before `rtk network on`: run only its LED register config (no SerDes, no lasers) */
static void engine_prep(void)
{
	if ((sw_r(LED_GLB) & 3) != 1)
		rtk_led_config();
}

static void map_load(void)
{
	const char *c = env_get("led_cols"), *r = env_get("led_rows");
	int i;

	if (c && strlen(c) == COLS)
		for (i = 0; i < COLS; i++)
			if (c[i] >= '1' && c[i] <= '8')
				col_cage[i] = c[i] - '0';
	if (r && strlen(r) == ROWS)
		for (i = 0; i < ROWS; i++)
			if (r[i] >= '0' && r[i] <= '2')
				row_led[i] = r[i] - '0';
}

static u32 field(int led, int mode)
{
	return (u32)mode << (3 * led) | (u32)mode << (12 + 3 * led);
}

/* one LED, hardware index; copper + fibre field (the engine picks by port media) */
static void led_put(int cage, int led, int mode)
{
	int p = rtk_cage_port[cage - 1];

	sw_rmw(LED_SW_CTRL(p), field(led, 7), field(led, mode));
	sw_rmw(LED_SW_EN(p), 0xfU << ((p & 7) * 4), 0xfU << ((p & 7) * 4));
}

static void fb_fill(int mode)
{
	memset(fb, mode, sizeof(fb));
}

static void fb_out(void)
{
	int r, c;

	for (c = 0; c < COLS; c++)
		for (r = 0; r < ROWS; r++)
			led_put(col_cage[c], row_led[r], fb[r][c]);
	load();
}

static void ring_cell(int i, int *r, int *c)
{
	i %= RING;
	if (i < COLS) {
		*r = 0, *c = i;
	} else if (i == COLS) {
		*r = 1, *c = COLS - 1;
	} else if (i < 2 * COLS + 1) {
		*r = 2, *c = 2 * COLS - i;
	} else {
		*r = 1, *c = 0;
	}
}

/* head on, tail 32 ms then 64 ms blink (no brightness control: blink reads as dimmer) */
static void snake_frame(int pos)
{
	static const u8 tail[] = { M_ON, M_B32, M_B64 };
	int i, r, c;

	fb_fill(M_OFF);
	for (i = ARRAY_SIZE(tail) - 1; i >= 0; i--) {
		ring_cell(pos + RING - i, &r, &c);
		fb[r][c] = tail[i];
	}
	fb_out();
}

/* hardware-held patterns: keep showing with the CPU stopped */
enum { PAT_BOOTING, PAT_ERROR, PAT_PANIC, PAT_FALLBACK };

static void pattern(int which)
{
	int r, c;

	engine_prep();
	for (r = 0; r < ROWS; r++)
		for (c = 0; c < COLS; c++)
			fb[r][c] = which == PAT_ERROR ? M_B128 :
				   which == PAT_PANIC ? ((r + c) & 1 ? M_B64 : M_ON) :
				   which == PAT_FALLBACK ? (r == 0 ? M_ON : r == 2 ? M_B256 : M_OFF) :
				   r == 0 ? M_B1024 : M_OFF;
	fb_out();
}

static void boot_stop(void)
{
	if (CONFIG_IS_ENABLED(CYCLIC))
		cyclic_unregister(&boot_cyc);
	boot_active = false;
}

void rtk_led_snapshot(void)
{
	if (!start_ok)
		snapshot(start_snap);
	start_ok = true;
}

static void latch_set(int kind, const char *why)
{
	rtk_led_snapshot();
	boot_stop();
	if (kind < latch)
		return;
	if (kind > latch)
		printf("led: %s latched (%s): `rtk led clear` or `rtk led hw` to release\n",
		       latch_name[kind], why);
	latch = kind;
	strlcpy(err_why, why, sizeof(err_why));
	env_set("led_error", err_why);
	pattern(kind == L_ERROR ? PAT_ERROR : PAT_FALLBACK);
}

void rtk_led_error(const char *why)
{
	latch_set(L_ERROR, why);
}

/* bootsel chose recovery by itself (unconfirmed boots, bad primary image, primary bootm failed) */
void rtk_led_fallback(const char *why)
{
	latch_set(L_FALLBACK, why);
}

static void boot_step(struct cyclic_info *c)
{
	if (get_timer(boot_t0) > boot_win_ms) {	/* countdown aborted: prompt, LEDs as found */
		boot_stop();
		restore(start_snap);
		return;
	}
	snake_frame(boot_pos++);
}

/* board_late_init: snapshot = LEDs as stock left them; snake only during the autoboot countdown */
void rtk_led_boot_start(int bootdelay_s)
{
	const char *m = env_get("led_boot");

	rtk_led_snapshot();
	if (!CONFIG_IS_ENABLED(CYCLIC) || bootdelay_s <= 0 || latch || (m && !strcmp(m, "off")))
		return;
	map_load();
	engine_prep();
	boot_t0 = get_timer(0);
	boot_win_ms = bootdelay_s * 10 * BOOT_WIN_PCT;
	boot_pos = 0;
	boot_active = boot_touched = true;
	cyclic_register(&boot_cyc, boot_step, SNAKE_MS * 1000, "led-snake");
}

/* first command of bootcmd and board_preboot_os: stop the snake, leave LEDs for the OS */
static void boot_end(void)
{
	const char *m = env_get("led_boot");

	if (!boot_active)
		return;
	boot_stop();
	if (latch)
		return;
	if (m && !strcmp(m, "latch"))
		pattern(PAT_BOOTING);	/* cleared by Linux (st1008f-leds `clear`) once userspace is up */
	else if (boot_touched)
		restore(start_snap);
}

void board_preboot_os(void)
{
	boot_end();
}

static int busy(void)
{
	if (!latch)
		return 0;
	printf("led: %s latched (%s): `rtk led clear` first\n", latch_name[latch], err_why);
	return 1;
}

static void unlatch(void)
{
	latch = L_NONE;
	env_set("led_error", NULL);
}

static int mode_arg(const char *s)
{
	if (!strcmp(s, "on"))
		return M_ON;
	if (!strcmp(s, "off"))
		return M_OFF;
	if (!strcmp(s, "blink"))
		return M_B512;
	if (s[0] >= '0' && s[0] <= '7' && !s[1])
		return s[0] - '0';
	return -1;
}

static int snake_cmd(int argc, char *const argv[])
{
	ulong ms = argc > 3 ? dectoul(argv[3], NULL) : SNAKE_MS;
	ulong loops = argc > 4 ? dectoul(argv[4], NULL) : 0, n, t;
	u32 save[LED_NREG];

	if (ms < SNAKE_MIN_MS)
		ms = SNAKE_MIN_MS;
	boot_stop();
	snapshot(save);
	map_load();
	engine_prep();
	printf("snake: %lu ms/step, %s; Ctrl-C stops\n", ms, loops ? "counted laps" : "until Ctrl-C");
	for (n = 0; !loops || n < loops * RING; n++) {
		snake_frame(n);
		for (t = 0; t < ms; t += 10) {
			if (ctrlc())
				goto out;
			mdelay(min(10UL, ms - t));
		}
	}
out:
	clear_ctrlc();
	restore(save);
	return 0;
}

static void show(void)
{
	int r, c, p;
	u32 v;

	printf("engine %s, latch %s%s%s%s, led_boot=%s\n",
	       (sw_r(LED_GLB) & 3) == 1 ? "serial" : "off", latch_name[latch], latch ? " (" : "",
	       latch ? err_why : "", latch ? ")" : "", env_get("led_boot") ?: "snake");
	printf("row/led ");
	for (c = 0; c < COLS; c++)
		printf(" c%u", col_cage[c]);
	printf("   (mode 0 off, 1-6 blink 32..1024 ms, 7 on; - = hw)\n");
	for (r = 0; r < ROWS; r++) {
		printf("%d/led%d  ", r, row_led[r]);
		for (c = 0; c < COLS; c++) {
			p = rtk_cage_port[col_cage[c] - 1];
			v = sw_r(LED_SW_CTRL(p)) >> (12 + 3 * row_led[r]) & 7;
			if (!(sw_r(LED_SW_EN(p)) >> ((p & 7) * 4) & BIT(row_led[r])))
				printf("  -");
			else
				printf("  %u", v);
		}
		printf("\n");
	}
}

int rtk_led(int argc, char *const argv[])
{
	const char *v = argc > 2 ? argv[2] : "show";
	int c, l, m, p;

	map_load();
	if (!strcmp(v, "show")) {
		show();
		return 0;
	}
	if (!strcmp(v, "boot-end")) {
		boot_end();
		return 0;
	}
	if (!strcmp(v, "error") || !strcmp(v, "fallback")) {
		latch_set(v[0] == 'e' ? L_ERROR : L_FALLBACK, argc > 3 ? argv[3] : "manual");
		return 0;
	}
	if (!strcmp(v, "hw")) {	/* link/activity from the hardware engine (LED set 0) */
		boot_stop();
		unlatch();
		engine_prep();
		for (c = 0; c < NCAGES; c++) {
			p = rtk_cage_port[c];
			sw_rmw(LED_SW_EN(p), 0xfU << ((p & 7) * 4), 0);
		}
		load();
		return 0;
	}
	if (!strcmp(v, "clear")) {
		boot_stop();
		unlatch();
		if (start_ok)
			restore(start_snap);
		return 0;
	}
	if (busy())
		return CMD_RET_FAILURE;
	boot_stop();
	if (!strcmp(v, "snake"))
		return snake_cmd(argc, argv);
	if (!strcmp(v, "pattern") && argc == 4) {
		m = !strcmp(argv[3], "booting") ? PAT_BOOTING : !strcmp(argv[3], "error") ? PAT_ERROR :
		    !strcmp(argv[3], "panic") ? PAT_PANIC :
		    !strcmp(argv[3], "fallback") ? PAT_FALLBACK : -1;
		if (m < 0)
			return CMD_RET_USAGE;
		pattern(m);
		return 0;
	}
	if (!strcmp(v, "all") && argc == 4 && (m = mode_arg(argv[3])) >= 0) {
		engine_prep();
		fb_fill(m);
		fb_out();
		return 0;
	}
	if (!strcmp(v, "set") && argc == 6 && (m = mode_arg(argv[5])) >= 0) {
		c = dectoul(argv[3], NULL);
		l = dectoul(argv[4], NULL);
		if (c < 1 || c > NCAGES || l < 0 || l >= ROWS)
			return CMD_RET_USAGE;
		engine_prep();
		led_put(c, l, m);
		load();
		return 0;
	}
	return CMD_RET_USAGE;
}
