/* st1008f-trace: 1 line per tick to stdout, so the host knows the last thing a unit did before it died (#144)
 * usage: st1008f-trace INTERVAL_MS LABEL     (run one per VPE with taskset: the label names the CPU)
 * line:  T cpu=L seq=N up=S dt=MS temp=mC load=1m busy=B0/B1 memavail=kB stage=<last selftest log line>
 *   dt  = real ms since the previous tick of this process: a stall before a hang shows as dt >> INTERVAL
 *   busy = % non-idle per VPE over the last tick (/proc/stat), temp = cpu-thermal zone
 * No sleep(1): clock_nanosleep to an absolute time keeps the cadence without drift.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static void rd(const char *path, char *buf, size_t n)
{
	FILE *f = fopen(path, "r");

	buf[0] = 0;
	if (f) {
		if (!fgets(buf, n, f))
			buf[0] = 0;
		fclose(f);
	}
	buf[strcspn(buf, "\r\n")] = 0;
}

static void cpus(unsigned long long idle[2], unsigned long long tot[2])
{
	FILE *f = fopen("/proc/stat", "r");
	char line[256];

	idle[0] = idle[1] = tot[0] = tot[1] = 0;
	while (f && fgets(line, sizeof(line), f)) {
		unsigned long long v[8] = { 0 };
		int c;

		if (strncmp(line, "cpu", 3) || line[3] < '0' || line[3] > '1')
			continue;
		c = line[3] - '0';
		sscanf(line + 4, "%llu %llu %llu %llu %llu %llu %llu %llu", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7]);
		idle[c] = v[3] + v[4];
		for (int i = 0; i < 8; i++)
			tot[c] += v[i];
	}
	if (f)
		fclose(f);
}

static void stage(char *out, size_t n)
{
	FILE *f = fopen("/tmp/st1008f-selftest.log", "r");
	char line[160];

	out[0] = 0;
	while (f && fgets(line, sizeof(line), f))
		snprintf(out, n, "%s", line);
	if (f)
		fclose(f);
	out[strcspn(out, "\r\n")] = 0;
	for (char *p = out; *p; p++)
		if (*p == ' ' || *p == '\t')
			*p = '_';
}

int main(int argc, char **argv)
{
	long ms = argc > 1 ? atol(argv[1]) : 1000;
	const char *label = argc > 2 ? argv[2] : "?";
	struct timespec next, prev;
	unsigned long long i0[2], t0[2], i1[2], t1[2];
	unsigned seq = 0;

	clock_gettime(CLOCK_MONOTONIC, &next);
	prev = next;
	cpus(i0, t0);
	for (;;) {
		char up[64], temp[32], load[64], mem[128], st[100];
		struct timespec now;
		long dt;
		int b[2];

		next.tv_nsec += ms * 1000000L;
		while (next.tv_nsec >= 1000000000L) {
			next.tv_nsec -= 1000000000L;
			next.tv_sec++;
		}
		clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
		clock_gettime(CLOCK_MONOTONIC, &now);
		dt = (now.tv_sec - prev.tv_sec) * 1000 + (now.tv_nsec - prev.tv_nsec) / 1000000;
		prev = now;
		cpus(i1, t1);
		for (int c = 0; c < 2; c++) {
			unsigned long long dt_t = t1[c] - t0[c], di = i1[c] - i0[c];

			b[c] = dt_t ? (int)(100 - 100 * di / dt_t) : 0;
			i0[c] = i1[c];
			t0[c] = t1[c];
		}
		rd("/proc/uptime", up, sizeof(up));
		up[strcspn(up, " ")] = 0;
		rd("/sys/class/thermal/thermal_zone0/temp", temp, sizeof(temp));
		rd("/proc/loadavg", load, sizeof(load));
		load[strcspn(load, " ")] = 0;
		mem[0] = 0;
		{
			FILE *f = fopen("/proc/meminfo", "r");
			char l[128];

			while (f && fgets(l, sizeof(l), f))
				if (!strncmp(l, "MemAvailable:", 13)) {
					snprintf(mem, sizeof(mem), "%ld", atol(l + 13));
					break;
				}
			if (f)
				fclose(f);
		}
		stage(st, sizeof(st));
		printf("T cpu=%s seq=%u up=%s dt=%ld temp=%s load=%s busy=%d/%d memavail=%s stage=%s\n",
		       label, seq++, up, dt, temp, load, b[0], b[1], mem, st);
		fflush(stdout);
	}
}
