// SPDX-License-Identifier: GPL-2.0
/*
 * st1008f-stx: helpers for st1008f-selftest (#108) that BusyBox sh cannot do.
 * - peek ADDR...: 32-bit reads through /dev/mem (KSEG1 or physical addresses), read-only.
 * - mem: userspace DRAM pattern pass over free RAM, error map as U-Boot memtest.c.
 * - slot DEV: CRC check of our U-Boot chain slot (scripts/uboot_chain_image.py format); crc FILE.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>

#define PAGE		4096u
#define MIB		(1024u * 1024u)
#define HIGH_PHYS	0x20000000u	/* zone 3: DRAM 256-512 MiB (300-21, docs/DRAM.md) */
#define HIGH_DRAM	0x10000000u

static double now(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

/* ---- peek ---- */
static int peek(int argc, char **argv)
{
	int fd = open("/dev/mem", O_RDONLY | O_SYNC), i, rc = 0;

	if (fd < 0) {
		printf("peek: /dev/mem: %s\n", strerror(errno));
		return 2;
	}
	for (i = 0; i < argc; i++) {
		uint32_t a = strtoul(argv[i], NULL, 0), pa = a & 0x1fffffff;
		volatile uint32_t *m = mmap(NULL, PAGE, PROT_READ, MAP_SHARED, fd, pa & ~(PAGE - 1));

		if (m == MAP_FAILED) {
			printf("0x%08x ERR %s\n", a, strerror(errno));
			rc = 1;
			continue;
		}
		printf("0x%08x 0x%08x\n", a, m[(pa & (PAGE - 1)) / 4]);
		munmap((void *)m, PAGE);
	}
	close(fd);
	return rc;
}

/* ---- slot ---- */
static uint32_t crc_tab[256];

static uint32_t crc32z(uint32_t crc, const uint8_t *p, size_t n)
{
	uint32_t c, k;

	if (!crc_tab[1])
		for (k = 0; k < 256; k++) {
			c = k;
			for (int j = 0; j < 8; j++)
				c = c & 1 ? 0xedb88320u ^ (c >> 1) : c >> 1;
			crc_tab[k] = c;
		}
	crc = ~crc;
	while (n--)
		crc = crc_tab[(crc ^ *p++) & 0xff] ^ (crc >> 8);
	return ~crc;
}

static uint32_t be32(const uint8_t *p)
{
	return (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3];
}

#define SLOT	0x80000u
#define TRAILER	(SLOT - 0x40)
static const uint8_t slot_magic[16] = { 'S', 'T', '1', '0', '0', '8', 'F', '-', 'U', 'B', 'O', 'O', 'T', 0, 1, 0 };

static int slot(const char *dev)
{
	uint8_t *b = malloc(SLOT), *t;
	uint32_t want, got, size, icrc;
	size_t n = 0;
	ssize_t r;
	int fd = open(dev, O_RDONLY);

	if (fd < 0 || !b) {
		printf("slot: FAIL open %s: %s\n", dev, strerror(errno));
		return 2;
	}
	while (n < SLOT && (r = read(fd, b + n, SLOT - n)) > 0)
		n += r;
	close(fd);
	if (n < SLOT) {
		printf("slot: FAIL short read %zu B < %u\n", n, SLOT);
		return 1;
	}
	want = be32(b + SLOT - 4);
	got = crc32z(0, b, SLOT - 4);
	if (got != want) {
		printf("slot: FAIL slot CRC32 %08x != trailer %08x (no chain image or corrupt)\n", got, want);
		return 1;
	}
	t = b + TRAILER;
	if (memcmp(t, slot_magic, 16)) {
		printf("slot: FAIL trailer magic\n");
		return 1;
	}
	size = be32(t + 16);
	icrc = be32(t + 20);
	if (size > TRAILER || crc32z(0, b, size) != icrc) {
		printf("slot: FAIL image size %u / CRC %08x inconsistent\n", size, icrc);
		return 1;
	}
	t[24 + 31] = 0;
	printf("slot: PASS slot CRC32 %08x, image %u B CRC32 %08x, %s\n", want, size, icrc,
	       (char *)t + 24);
	return 0;
}

/* ---- mem: patterns and decode as uboot-port/.../memtest.c ---- */
enum { T_RAND, T_ADDR, T_WALK1, T_WALK0, T_CHECK, T_ICHECK, T_N };
static const char *const tname[T_N] = { "rand", "addr", "walk1", "walk0", "check", "icheck" };

struct stats {
	uint32_t errs, sticky, logged, xor_or;
	uint32_t bit[32], bank[8], rowb[16], colb[8];
};

static uint64_t *pfn;	/* pagemap entry per page of the buffer */
static uint32_t maxlog = 16, seed = 0x1008f;
static long inject = -1;	/* error-path self-check: flip bit 3 of word N after the write pass */

static inline uint32_t pat(int t, uintptr_t va, uint32_t *rs)
{
	uint32_t i = va >> 2, x;

	switch (t) {
	case T_ADDR:	return (uint32_t)va;
	case T_WALK1:	return 1u << (i & 31);
	case T_WALK0:	return ~(1u << (i & 31));
	case T_CHECK:	return i & 1 ? 0xaaaaaaaa : 0x55555555;
	case T_ICHECK:	return i & 1 ? 0x55555555 : 0xaaaaaaaa;
	default:
		x = *rs;
		x ^= x << 13;
		x ^= x >> 17;
		x ^= x << 5;
		return *rs = x;
	}
}

/* DRAM offset of byte `off` of the buffer; ~0 if the page is not present */
static uint32_t dram_of(size_t off)
{
	uint64_t e = pfn[off / PAGE];
	uint32_t pa;

	if (!(e >> 63))
		return ~0u;
	pa = (uint32_t)((e & ((1ull << 55) - 1)) * PAGE + off % PAGE);
	return pa >= HIGH_PHYS ? pa - HIGH_PHYS + HIGH_DRAM : pa;
}

static void note(struct stats *s, int t, size_t off, uint32_t want, uint32_t got, uint32_t again)
{
	uint32_t x = want ^ got, d = dram_of(off), m;

	s->errs++;
	s->sticky += again == got;
	s->xor_or |= x;
	for (m = x; m; m &= m - 1)
		s->bit[__builtin_ctz(m)]++;
	if (d != ~0u) {	/* assumed x16 decode, as memtest.c */
		s->bank[(d >> 11) & 7]++;
		s->rowb[(d >> 25) & 15]++;
		s->colb[(d >> 8) & 7]++;
	}
	if (s->logged++ < maxlog)
		printf("mem: E %s %s dram %08x want %08x got %08x xor %08x reread %08x\n",
		       d == ~0u ? "?" : d >= HIGH_DRAM ? "high" : "low", tname[t], d, want, got, x, again);
}

static void counts(const char *what, const uint32_t *c, int n)
{
	printf("mem: %s", what);
	for (int i = 0; i < n; i++)
		printf(" %u", c[i]);
	putchar('\n');
}

/* one pattern over words start.. (wrapping), write then read; reads miss the 32 KiB D-cache */
#define CHUNK	(4 * MIB / 4)	/* words between deadline checks */

/* the write stops at half the time left before `end` (the read takes about as long), then the written
 * part is checked; *words = words tested */
static uint32_t run(volatile uint32_t *buf, size_t bytes, int t, size_t start, double end, size_t *words)
{
	struct stats s = { 0 };
	uint32_t rs = seed ^ (t << 24);
	size_t i, j, n = bytes / 4, w;
	double t0 = now(), wend = t0 + (end - t0) / 2;

	for (i = 0, j = start; i < n; i++, j = j + 1 < n ? j + 1 : 0) {
		if (!(i % CHUNK) && i && now() > wend)
			break;
		buf[j] = pat(t, (uintptr_t)&buf[j], &rs);
	}
	w = i;
	*words = w;
	if (inject >= 0 && (size_t)inject < n)
		buf[inject] ^= 8;
	rs = seed ^ (t << 24);
	for (i = 0, j = start; i < w; i++, j = j + 1 < n ? j + 1 : 0) {
		uint32_t want = pat(t, (uintptr_t)&buf[j], &rs), got = buf[j];

		if (got != want)
			note(&s, t, j * 4, want, got, buf[j]);
	}
	printf("mem: S %s %zu MiB from %zu MiB %.0f ms errs %u sticky %u xor %08x\n", tname[t], w * 4 / MIB,
	       start * 4 / MIB, (now() - t0) * 1e3, s.errs, s.sticky, s.xor_or);
	if (s.errs) {
		counts("bits0..31", s.bit, 32);
		counts("bank", s.bank, 8);
		counts("row/2048", s.rowb, 16);
		counts("col/128", s.colb, 8);
	}
	fflush(stdout);
	return s.errs;
}

static size_t max_sz(size_t a, size_t b)
{
	return a > b ? a : b;
}

static long meminfo_kb(const char *key)
{
	char line[128];
	long v = -1;
	FILE *f = fopen("/proc/meminfo", "r");

	if (!f)
		return -1;
	while (fgets(line, sizeof(line), f))
		if (!strncmp(line, key, strlen(key)) && line[strlen(key)] == ':') {
			v = atol(line + strlen(key) + 1);
			break;
		}
	fclose(f);
	return v;
}

static int mem(int argc, char **argv)
{
	double secs = 8, t0 = now();
	long reserve = 64, cap = 0, avail = meminfo_kb("MemAvailable");
	size_t bytes, pages, i, low = 0, high = 0, miss = 0, cov = 0, sec, w[T_N] = { 0 };
	uint32_t errs = 0;
	int t, m, ntests = T_N, fd, cut = 0;
	volatile uint32_t *buf;
	FILE *f;

	for (i = 0; i < (size_t)argc; i++) {
		if (!strncmp(argv[i], "secs=", 5))
			secs = atof(argv[i] + 5);
		else if (!strncmp(argv[i], "reserve=", 8))
			reserve = atol(argv[i] + 8);
		else if (!strncmp(argv[i], "mib=", 4))
			cap = atol(argv[i] + 4);
		else if (!strncmp(argv[i], "log=", 4))
			maxlog = atol(argv[i] + 4);
		else if (!strncmp(argv[i], "seed=", 5))
			seed = strtoul(argv[i] + 5, NULL, 16);
		else if (!strncmp(argv[i], "inject=", 7))
			inject = atol(argv[i] + 7);
		else if (!strncmp(argv[i], "tests=", 6))
			ntests = atoi(argv[i] + 6);
		else {
			printf("mem: usage: mem [secs=S] [reserve=MiB] [mib=N] [log=N] [seed=HEX] [tests=1-6]\n");
			return 2;
		}
	}
	if (ntests < 1 || ntests > T_N)
		ntests = T_N;
	/* an OOM during the test kills the test, not a service */
	f = fopen("/proc/self/oom_score_adj", "w");
	if (f) {
		fputs("1000", f);
		fclose(f);
	}
	if (avail < 0) {
		printf("mem: FAIL no MemAvailable in /proc/meminfo\n");
		return 2;
	}
	bytes = (avail / 1024 > reserve ? avail / 1024 - reserve : 0) * MIB;
	if (cap && bytes > (size_t)cap * MIB)
		bytes = (size_t)cap * MIB;
	if (bytes < 16 * MIB) {
		printf("mem: FAIL only %ld KiB available (reserve %ld MiB)\n", avail, reserve);
		return 2;
	}
	buf = mmap(NULL, bytes, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	if (buf == MAP_FAILED) {
		printf("mem: FAIL mmap %zu MiB: %s\n", bytes / MIB, strerror(errno));
		return 2;
	}
	pages = bytes / PAGE;
	for (i = 0; i < pages; i++) {	/* fault pages in before pagemap; at most 1/4 of the budget */
		if (!(i % 1024) && i && now() - t0 > secs / 4) {
			printf("mem: page-in slow: region cut to %zu MiB\n", i * PAGE / MIB);
			pages = i;
			bytes = pages * PAGE;
			break;
		}
		buf[i * (PAGE / 4)] = 0;
	}
	pfn = calloc(pages, sizeof(*pfn));
	fd = open("/proc/self/pagemap", O_RDONLY);
	if (!pfn || fd < 0 || pread(fd, pfn, pages * 8, (uintptr_t)buf / PAGE * 8) != (ssize_t)(pages * 8))
		printf("mem: pagemap unreadable (%s): no DRAM addresses\n", strerror(errno));
	if (fd >= 0)
		close(fd);
	for (i = 0; i < pages; i++) {
		uint32_t d = dram_of(i * PAGE);

		if (d == ~0u)
			miss++;
		else if (d >= HIGH_DRAM)
			high++;
		else
			low++;
	}
	sec = bytes / 4 / ntests;	/* words per pattern's start sector */
	printf("mem: %zu MiB of MemAvailable %ld MiB (reserve %ld): low %zu MiB, high %zu MiB, "
	       "no pfn %zu pages; budget %.1f s, seed %08x\n", bytes / MIB, avail / 1024, reserve,
	       low * PAGE / MIB, high * PAGE / MIB, miss, secs, seed);
	/* every pattern runs: equal share of the time left, each from its own offset, so the patterns
	 * together cover the buffer when one pass per pattern does not fit (#108) */
	for (t = 0; t < ntests; t++) {
		errs += run(buf, bytes, t, sec * t, now() + (t0 + secs - now()) / (ntests - t), &w[t]);
		cut += w[t] < bytes / 4;
	}
	for (m = 0; m < ntests; m++) {	/* union: arc t covers a prefix of sector m */
		size_t best = 0;

		for (t = 0; t < ntests; t++) {
			size_t lead = (size_t)((m - t + ntests) % ntests) * sec;
			size_t c = w[t] > lead ? w[t] - lead : 0;

			best = max_sz(best, c < sec ? c : sec);
		}
		cov += best;
	}
	printf("mem: done errs %u tests %d/%d (%d cut to their time share) covered %zu of %zu MiB low %zu MiB "
	       "high %zu MiB %.0f ms\n", errs, ntests, ntests, cut, (cov * 4 + MIB / 2) / MIB, bytes / MIB, low * PAGE / MIB,
	       high * PAGE / MIB, (now() - t0) * 1e3);
	return errs ? 1 : 0;
}

/* crc FILE: zlib CRC32 of the whole file / mtd device */
static int crc(const char *path)
{
	static uint8_t b[65536];
	uint32_t c = 0;
	size_t total = 0;
	ssize_t r;
	int fd = open(path, O_RDONLY);

	if (fd < 0) {
		printf("crc: FAIL open %s: %s\n", path, strerror(errno));
		return 2;
	}
	while ((r = read(fd, b, sizeof(b))) > 0) {
		c = crc32z(c, b, r);
		total += r;
	}
	close(fd);
	if (r < 0) {
		printf("crc: FAIL read %s at %zu: %s\n", path, total, strerror(errno));
		return 1;
	}
	printf("crc32 %08x size %zu\n", c, total);
	return 0;
}

int main(int argc, char **argv)
{
	setvbuf(stdout, NULL, _IOLBF, 0);
	if (argc == 3 && !strcmp(argv[1], "crc"))
		return crc(argv[2]);
	if (argc >= 2 && !strcmp(argv[1], "peek"))
		return peek(argc - 2, argv + 2);
	if (argc >= 2 && !strcmp(argv[1], "mem"))
		return mem(argc - 2, argv + 2);
	if (argc == 3 && !strcmp(argv[1], "slot"))
		return slot(argv[2]);
	fprintf(stderr, "usage: st1008f-stx peek ADDR... | mem [k=v...] | slot /dev/mtdN | crc FILE\n");
	return 2;
}
