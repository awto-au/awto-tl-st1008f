// SPDX-License-Identifier: GPL-2.0-only
/*
 * fastsample: sample the CPU-port NIC counters 100 times a second and send each sample as one UDP datagram to the dev host (#186).
 * Per sample (text): seq t_us eth0 rx_packets rx_dropped rx_errors rx_fifo_errors tx_packets, eth0 IRQ count cpu0 cpu1,
 * rteth ring0_frames ring1_frames (debugfs rxq). A crash loses at most the last period; the host receiver (fastsample_rx.py) keeps the rest.
 * Build: scripts/build_fastsample.py (static musl, BE MIPS). Usage: fastsample HOST PORT [PERIOD_US=10000]
 */
#include <arpa/inet.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

static int fd_open(const char *p)
{
	return open(p, O_RDONLY);
}

static long rd_num(int fd)
{
	char b[32];
	ssize_t n = pread(fd, b, sizeof(b) - 1, 0);

	if (n <= 0)
		return -1;
	b[n] = 0;
	return strtol(b, NULL, 10);
}

int main(int argc, char **argv)
{
	static const char *const st[] = { "rx_packets", "rx_dropped", "rx_errors", "rx_fifo_errors", "tx_packets" };
	int fs[5], fi, fq, s, i;
	long period_us = argc > 3 ? atol(argv[3]) : 10000;
	struct sockaddr_in to = { .sin_family = AF_INET, .sin_port = htons(atoi(argc > 2 ? argv[2] : "6677")) };
	struct timespec next;
	unsigned long seq = 0;
	char path[96], buf[4096], out[256];

	if (argc < 3 || !inet_aton(argv[1], &to.sin_addr))
		return 2;
	for (i = 0; i < 5; i++) {
		snprintf(path, sizeof(path), "/sys/class/net/eth0/statistics/%s", st[i]);
		fs[i] = fd_open(path);
	}
	fi = fd_open("/proc/interrupts");
	fq = fd_open("/sys/kernel/debug/rteth/rxq");
	s = socket(AF_INET, SOCK_DGRAM, 0);
	clock_gettime(CLOCK_MONOTONIC, &next);
	for (;;) {
		long v[5], irq0 = -1, irq1 = -1, r0 = -1, r1 = -1;
		struct timespec now;
		ssize_t n;
		char *p;

		for (i = 0; i < 5; i++)
			v[i] = rd_num(fs[i]);
		n = pread(fi, buf, sizeof(buf) - 1, 0);
		if (n > 0) {
			buf[n] = 0;
			for (p = buf; (p = strstr(p, " eth0")); p++) {	// "24:  581871  0  realtek-rtl-intc 24 eth0": the line holding the eth0 name
				char *l = p;

				while (l > buf && l[-1] != '\n')
					l--;
				sscanf(l, "%*d: %ld %ld", &irq0, &irq1);
				break;
			}
		}
		n = pread(fq, buf, sizeof(buf) - 1, 0);
		if (n > 0) {
			buf[n] = 0;
			if ((p = strstr(buf, "ring0_frames ")))
				r0 = strtol(p + 13, NULL, 10);
			if ((p = strstr(buf, "ring1_frames ")))
				r1 = strtol(p + 13, NULL, 10);
		}
		clock_gettime(CLOCK_MONOTONIC, &now);
		n = snprintf(out, sizeof(out), "%lu %lld %ld %ld %ld %ld %ld %ld %ld %ld %ld\n", seq++,
			     (long long)now.tv_sec * 1000000LL + now.tv_nsec / 1000, v[0], v[1], v[2], v[3], v[4], irq0, irq1, r0, r1);
		sendto(s, out, n, MSG_DONTWAIT, (struct sockaddr *)&to, sizeof(to));
		next.tv_nsec += period_us * 1000L;
		while (next.tv_nsec >= 1000000000L) {
			next.tv_nsec -= 1000000000L;
			next.tv_sec++;
		}
		clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &next, NULL);
	}
}
