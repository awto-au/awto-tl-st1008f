/* st1008f-mtprobe: synthetic load for the second VPE (docs/NAT-HISTORY.md, scripts/mt_interference.py)
 * usage: st1008f-mtprobe MODE SECONDS   MODE = spin | small | chase | stream | sram
 *   spin   ALU only (xorshift), no memory
 *   small  dependent loads inside N KiB, default 8 (L1 resident; third argument = KiB)
 *   chase  dependent loads over 8 MiB, random order (every load a DRAM miss, one at a time)
 *   stream copy 4 MiB buffers (DRAM bandwidth)
 *   sram   dependent reads over the on-chip SRAM (64 KiB at 0x1f000000, /dev/mem, uncached, read only)
 * prints: MODE rate=<value> unit  (higher = the probe got more of the core)
 */
#include <fcntl.h>
#include <stdint.h>
#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static double now(void)
{
	struct timespec t;

	clock_gettime(CLOCK_MONOTONIC, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

static uint32_t *perm(size_t words)
{
	uint32_t *p = malloc(words * 4);
	uint32_t x = 0x1008f;

	for (size_t i = 0; i < words; i++)
		p[i] = i;
	for (size_t i = words - 1; i > 0; i--) { /* Sattolo: one cycle through every slot */
		x ^= x << 13; x ^= x >> 17; x ^= x << 5;
		size_t j = x % i, t = p[i];

		p[i] = p[j];
		p[j] = t;
	}
	return p;
}

int main(int argc, char **argv)
{
	const char *mode = argc > 1 ? argv[1] : "spin";
	double secs = argc > 2 ? atof(argv[2]) : 10, t0 = now(), t;
	uint64_t n = 0;
	volatile uint32_t sink = 0;

	if (!strcmp(mode, "spin")) {
		uint32_t x = 1;

		do {
			for (int i = 0; i < 100000; i++) {
				x ^= x << 13; x ^= x >> 17; x ^= x << 5;
			}
			n += 100000;
		} while ((t = now()) - t0 < secs);
		sink = x;
		printf("spin rate=%.1f Miter/s\n", n / (t - t0) / 1e6);
	} else if (!strcmp(mode, "small") || !strcmp(mode, "chase")) {
		size_t words = !strcmp(mode, "small") ? (argc > 3 ? atoi(argv[3]) : 8) * 256 : 2 * 1024 * 1024;
		uint32_t *p = perm(words), i = 0;

		do {
			for (int k = 0; k < 20000; k++)
				i = p[i];
			n += 20000;
		} while ((t = now()) - t0 < secs);
		sink = i;
		printf("%s rate=%.2f Mload/s (%.0f ns each)\n", mode, n / (t - t0) / 1e6, (t - t0) / n * 1e9);
	} else if (!strcmp(mode, "sram")) {
		int fd = open("/dev/mem", O_RDONLY | O_SYNC);
		volatile uint32_t *m = fd < 0 ? MAP_FAILED : mmap(0, 65536, PROT_READ, MAP_SHARED, fd, 0x1f000000);
		uint32_t i = 0;

		if (m == MAP_FAILED) {
			perror("sram");
			return 1;
		}
		do {
			for (int k = 0; k < 5000; k++)
				i = (i * 1103515245u + 12345u + m[i & 0x3fff]) & 0xffffffffu;
			n += 5000;
		} while ((t = now()) - t0 < secs);
		sink = i;
		printf("sram rate=%.2f Mload/s (%.0f ns each)\n", n / (t - t0) / 1e6, (t - t0) / n * 1e9);
	} else if (!strcmp(mode, "stream")) {
		size_t sz = 4 << 20;
		char *a = malloc(sz), *b = malloc(sz);

		memset(a, 1, sz);
		do {
			memcpy(b, a, sz);
			memcpy(a, b, sz);
			n += 2;
		} while ((t = now()) - t0 < secs);
		sink = a[7] + b[9];
		printf("stream rate=%.1f MB/s copied\n", n * (double)sz / (t - t0) / 1e6);
	} else {
		fprintf(stderr, "mode?\n");
		return 2;
	}
	return 0;
}
