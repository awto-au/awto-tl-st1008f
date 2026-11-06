/* udpblast: plain UDP sender for forwarding tests (scripts/zc_bench.py): no handshake, so NAT'd flows are fine.
 * usage: udpblast SRC_IP DST_IP DPORT PAYLOAD_BYTES SECONDS FLOWS
 * FLOWS sockets with source ports 40000.. sending in batches (sendmmsg); prints packets sent. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>

#define BATCH 32

int main(int argc, char **argv)
{
	if (argc < 7) {
		fprintf(stderr, "usage: %s SRC DST DPORT LEN SECS FLOWS\n", argv[0]);
		return 2;
	}
	int len = atoi(argv[4]), flows = atoi(argv[6]), s[64];
	double secs = atof(argv[5]);
	struct sockaddr_in src = { .sin_family = AF_INET }, dst = { .sin_family = AF_INET, .sin_port = htons(atoi(argv[3])) };
	static char buf[1500];
	struct mmsghdr msgs[BATCH];
	struct iovec iov = { buf, len };
	unsigned long sent = 0;
	struct timespec t0, t;

	inet_pton(AF_INET, argv[1], &src.sin_addr);
	inet_pton(AF_INET, argv[2], &dst.sin_addr);
	if (flows > 64)
		flows = 64;
	for (int i = 0; i < flows; i++) {
		src.sin_port = htons(40000 + i);
		s[i] = socket(AF_INET, SOCK_DGRAM, 0);
		if (bind(s[i], (struct sockaddr *)&src, sizeof(src)) || connect(s[i], (struct sockaddr *)&dst, sizeof(dst))) {
			perror("socket");
			return 1;
		}
		int sz = 4 << 20;
		setsockopt(s[i], SOL_SOCKET, SO_SNDBUF, &sz, sizeof(sz));
	}
	memset(buf, 0x55, sizeof(buf));
	for (int i = 0; i < BATCH; i++)
		msgs[i].msg_hdr = (struct msghdr){ .msg_iov = &iov, .msg_iovlen = 1 };
	clock_gettime(CLOCK_MONOTONIC, &t0);
	for (unsigned long n = 0;; n++) {
		int r = sendmmsg(s[n % flows], msgs, BATCH, 0);

		if (r > 0)
			sent += r;
		if ((n & 63) == 0) {
			clock_gettime(CLOCK_MONOTONIC, &t);
			if ((t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9 >= secs)
				break;
		}
	}
	printf("sent %lu\n", sent);
	return 0;
}
