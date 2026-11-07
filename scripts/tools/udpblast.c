/* udpblast: plain UDP sender for forwarding tests (scripts/zc_bench.py): no handshake, so NAT'd flows are fine.
 * usage: udpblast SRC_IP DST_IP DPORT PAYLOAD_BYTES SECONDS FLOWS [PATTERN]
 * PATTERN=1: every packet carries a sequence number and a filler derived from it (checked by udpcheck.c).
 * FLOWS sockets with source ports 40000.. sending in batches (sendmmsg); prints packets sent. */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <stdint.h>
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
	struct iovec iov[BATCH];
	static char pbuf[BATCH][1500];
	int pat = argc > 7 && atoi(argv[7]);
	uint64_t seq = 0;
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
	for (int i = 0; i < BATCH; i++) {
		iov[i] = (struct iovec){ pat ? pbuf[i] : buf, len };
		msgs[i].msg_hdr = (struct msghdr){ .msg_iov = &iov[i], .msg_iovlen = 1 };
	}
	clock_gettime(CLOCK_MONOTONIC, &t0);
	for (unsigned long n = 0;; n++) {
		if (pat && len >= 16)
			for (int i = 0; i < BATCH; i++) {
				uint32_t h = (uint32_t)(++seq * 2654435761u) >> 16;

				memcpy(pbuf[i], &seq, 8);
				memcpy(pbuf[i] + 8, &h, 4);
				for (int j = 12; j < len; j++)
					pbuf[i][j] = (char)(h + j * 13);
			}
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
