/* udpcheck: receiver for udpblast PATTERN=1; counts packets whose filler does not match their sequence number
 * (payload corruption / stale cache lines). usage: udpcheck PORT SECONDS EXPECT_LEN; prints "good N bad M". */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <netinet/in.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>

int main(int argc, char **argv)
{
	if (argc < 4) {
		fprintf(stderr, "usage: %s PORT SECONDS EXPECT_LEN\n", argv[0]);
		return 2;
	}
	int s = socket(AF_INET, SOCK_DGRAM, 0), len = atoi(argv[3]), sz = 8 << 20;
	double secs = atof(argv[2]);
	struct sockaddr_in a = { .sin_family = AF_INET, .sin_port = htons(atoi(argv[1])) };
	static char buf[1600];
	unsigned long good = 0, bad = 0, badfirst = 0;
	struct timeval tv = { 0, 200000 };	/* wake every 200 ms to check the deadline */
	struct timespec t0, t;

	setsockopt(s, SOL_SOCKET, SO_RCVBUF, &sz, sizeof(sz));
	setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
	if (bind(s, (struct sockaddr *)&a, sizeof(a))) {
		perror("bind");
		return 1;
	}
	puts("ready");
	fflush(stdout);
	clock_gettime(CLOCK_MONOTONIC, &t0);
	for (;;) {
		int n = recv(s, buf, sizeof(buf), 0);

		clock_gettime(CLOCK_MONOTONIC, &t);
		if ((t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9 >= secs)
			break;
		if (n < 0)
			continue;
		uint64_t seq;
		uint32_t h, eh;

		memcpy(&seq, buf, 8);
		memcpy(&h, buf + 8, 4);
		eh = (uint32_t)(seq * 2654435761u) >> 16;
		int ok = n == len && h == eh;

		for (int j = 12; ok && j < n; j++)
			ok = buf[j] == (char)(h + j * 13);
		if (ok)
			good++;
		else {
			if (!bad++)
				badfirst = seq;
			if (bad <= 3)
				fprintf(stderr, "bad: len %d seq %lu\n", n, (unsigned long)seq);
		}
	}
	printf("good %lu bad %lu firstbad %lu\n", good, bad, badfirst);
	return bad != 0;
}
