/* memtest: userspace RAM pattern test with physical addresses (#186, cause 3). Usage: memtest MB SECS_PER_PATTERN
 * Fill MB with a pattern, re-read for SECS (finds stored flips and read-side errors), report every mismatch with virtual + physical address.
 * Build: scripts/build_memtest.py (static musl, BE MIPS). */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <time.h>
#include <sys/mman.h>

static int pm = -1;
static uint64_t phys(void *va)
{
	uint64_t e = 0;
	if (pm >= 0 && pread(pm, &e, 8, ((uintptr_t)va >> 12) * 8) == 8 && (e >> 63))
		return ((e & ((1ULL << 55) - 1)) << 12) | ((uintptr_t)va & 0xfff);
	return 0;
}

static uint32_t pat(int kind, size_t i)
{
	switch (kind) {
	case 0: return 0x00000000;
	case 1: return 0xffffffff;
	case 2: return (i & 1) ? 0x55555555 : 0xaaaaaaaa;
	default: return (uint32_t)(i * 0x9e3779b1u) ^ 0x5a5a1234u;
	}
}

int main(int argc, char **argv)
{
	size_t mb = argc > 1 ? atoi(argv[1]) : 256, secs = argc > 2 ? atoi(argv[2]) : 30;
	size_t n = mb << 18; /* uint32 words */
	volatile uint32_t *m = mmap(NULL, mb << 20, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
	long bad = 0;
	pm = open("/proc/self/pagemap", O_RDONLY);
	if (m == MAP_FAILED) { perror("mmap"); return 1; }
	for (int kind = 0; kind < 4; kind++) {
		time_t t0;
		long pass = 0;
		for (size_t i = 0; i < n; i++)
			m[i] = pat(kind, i);
		t0 = time(NULL);
		do {
			for (size_t i = 0; i < n; i++) {
				uint32_t v = m[i], e = pat(kind, i);
				if (v != e) {
					bad++;
					printf("MISMATCH pattern %d pass %ld va %p pa 0x%llx exp %08x got %08x xor %08x\n", kind, pass,
					       (void *)(m + i), (unsigned long long)phys((void *)(m + i)), e, v, e ^ v);
					fflush(stdout);
					m[i] = e; /* repair: a repeat at the same place shows a weak cell */
				}
			}
			pass++;
		} while (time(NULL) - t0 < (time_t)secs);
		printf("pattern %d: %ld passes of %zu MB, mismatches so far %ld\n", kind, pass, mb, bad);
		fflush(stdout);
	}
	printf("DONE mismatches %ld\n", bad);
	return bad != 0;
}
