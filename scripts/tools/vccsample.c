/* vccsample — SFP DDM Vcc (3.3 V cage rail) of every cage at a fixed period, on the box (#186).
 * usage: vccsample [period_ms=10] [secs=0 (forever)] [dip_mv=30] [slow=p1,..]
 * slow cages (e.g. a 10G-T module, ~9 ms per read) are read once per second, not every tick.
 * line per second: S up=S n=N late=L sweep_max_us=U <cage>=min/max/changes ...
 * line per dip:     DIP up=S <cage> mv=V base=B  (below the previous second's mean by >= dip_mv)
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <fcntl.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define MAXC 8

static double now_s(clockid_t c)
{
	struct timespec t;
	clock_gettime(c, &t);
	return t.tv_sec + t.tv_nsec / 1e9;
}

int main(int argc, char **argv)
{
	int period_ms = argc > 1 ? atoi(argv[1]) : 10, secs = argc > 2 ? atoi(argv[2]) : 0;
	int dip = argc > 3 ? atoi(argv[3]) : 30;
	char name[MAXC][32], path[300], buf[32];
	int fd[MAXC], slow[MAXC], nc = 0;
	const char *slowlist = argc > 4 ? argv[4] : "";
	DIR *d = opendir("/sys/class/hwmon");
	struct dirent *e;

	while (d && (e = readdir(d)) && nc < MAXC) {
		if (e->d_name[0] == '.')
			continue;
		snprintf(path, sizeof(path), "/sys/class/hwmon/%s/name", e->d_name);
		int f = open(path, O_RDONLY), n = f < 0 ? 0 : read(f, buf, sizeof(buf) - 1);
		if (f >= 0)
			close(f);
		buf[n > 0 ? n - 1 : 0] = 0;
		if (strncmp(buf, "sfp_p", 5))
			continue;
		snprintf(path, sizeof(path), "/sys/class/hwmon/%s/in0_input", e->d_name);
		if ((fd[nc] = open(path, O_RDONLY)) < 0)
			continue;
		snprintf(name[nc], 32, "%s", buf + 4);
		slow[nc] = strstr(slowlist, name[nc]) != NULL;
		nc++;
	}
	if (!nc) {
		fprintf(stderr, "no sfp hwmon with in0_input\n");
		return 2;
	}
	struct sched_param sp = { .sched_priority = 1 };
	sched_setscheduler(0, SCHED_FIFO, &sp); /* regular ticks; sleeps between sweeps */

	int mn[MAXC], mx[MAXC], ch[MAXC], prev[MAXC], cnt[MAXC], n = 0, late = 0, dips = 0;
	double sum[MAXC], base[MAXC], sweep_max = 0, t_end = secs ? now_s(CLOCK_MONOTONIC) + secs : 0;
	for (int i = 0; i < nc; i++)
		mn[i] = 1 << 30, mx[i] = ch[i] = prev[i] = cnt[i] = 0, sum[i] = base[i] = 0;
	struct timespec next;
	clock_gettime(CLOCK_MONOTONIC, &next);
	long sec_mark = next.tv_sec;
	int first = 1;
	setvbuf(stdout, NULL, _IOLBF, 0);

	for (;;) {
		double t0 = now_s(CLOCK_MONOTONIC);
		for (int i = 0; i < nc; i++) {
			if (slow[i] && n && !first)
				continue;
			int r = pread(fd[i], buf, sizeof(buf) - 1, 0);
			if (r <= 0)
				continue;
			buf[r] = 0;
			int v = atoi(buf);
			mn[i] = v < mn[i] ? v : mn[i];
			mx[i] = v > mx[i] ? v : mx[i];
			ch[i] += !first && v != prev[i];
			prev[i] = v;
			sum[i] += v;
			cnt[i]++;
			if (base[i] > 0 && v <= base[i] - dip && dips++ < 20)
				printf("DIP up=%.3f %s mv=%d base=%.0f\n", now_s(CLOCK_BOOTTIME), name[i], v, base[i]);
		}
		double sw = now_s(CLOCK_MONOTONIC) - t0;
		sweep_max = sw > sweep_max ? sw : sweep_max;
		n++;
		first = 0;
		next.tv_nsec += period_ms * 1000000L;
		while (next.tv_nsec >= 1000000000L)
			next.tv_nsec -= 1000000000L, next.tv_sec++;
		struct timespec cur;
		clock_gettime(CLOCK_MONOTONIC, &cur);
		if (cur.tv_sec > next.tv_sec || (cur.tv_sec == next.tv_sec && cur.tv_nsec > next.tv_nsec)) {
			late++;
			next = cur; /* missed the slot: restart the grid, count it */
		}
		if (cur.tv_sec != sec_mark) {
			printf("S up=%.1f n=%d late=%d sweep_max_us=%.0f", now_s(CLOCK_BOOTTIME), n, late, sweep_max * 1e6);
			for (int i = 0; i < nc; i++) {
				printf(" %s=%d/%d/%d", name[i], mn[i], mx[i], ch[i]);
				base[i] = cnt[i] ? sum[i] / cnt[i] : base[i];
				mn[i] = 1 << 30, mx[i] = ch[i] = cnt[i] = 0, sum[i] = 0;
			}
			printf("\n");
			first = 1;
			n = late = dips = 0;
			sweep_max = 0;
			sec_mark = cur.tv_sec;
			if (t_end && now_s(CLOCK_MONOTONIC) >= t_end)
				return 0;
		}
		clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
	}
}
