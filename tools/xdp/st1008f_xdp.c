// SPDX-License-Identifier: GPL-2.0
/*
 * st1008f-xdp: attach a minimal XDP program that drops frames from one source MAC and passes everything
 * else (#140, docs/NAT.md). Measures the XDP floor on eth0 with the nat-bench rxdrop flood. No libbpf:
 * the program is a few hand-written BPF instructions, loaded with bpf(2) and attached by BPF_LINK_CREATE.
 *
 *   st1008f-xdp IFNAME MAC skb|drv    attach, stay attached until SIGTERM/SIGINT (link fd closes)
 */
#include <errno.h>
#include <linux/bpf.h>
#include <linux/if_link.h>
#include <net/if.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>

#define INSN(c, d, s, o, i) ((struct bpf_insn){ .code = (c), .dst_reg = (d), .src_reg = (s), .off = (o), .imm = (i) })
#define LDX(sz, d, s, o)    INSN(BPF_LDX | BPF_MEM | (sz), d, s, o, 0)
#define MOV_REG(d, s)       INSN(BPF_ALU64 | BPF_MOV | BPF_X, d, s, 0, 0)
#define ADD_IMM(d, i)       INSN(BPF_ALU64 | BPF_ADD | BPF_K, d, 0, 0, i)
#define MOV_IMM(d, i)       INSN(BPF_ALU64 | BPF_MOV | BPF_K, d, 0, 0, i)
#define JGT_REG(d, s, o)    INSN(BPF_JMP | BPF_JGT | BPF_X, d, s, o, 0)
#define JNE_IMM(d, i, o)    INSN(BPF_JMP | BPF_JNE | BPF_K, d, 0, o, i)
#define EXIT()              INSN(BPF_JMP | BPF_EXIT, 0, 0, 0, 0)

static volatile sig_atomic_t stop;
static void on_sig(int s) { (void)s; stop = 1; }

static long bpf(int cmd, union bpf_attr *a) { return syscall(__NR_bpf, cmd, a, sizeof(*a)); }

int main(int argc, char **argv)
{
	unsigned int m[6], ifindex, hi, lo;
	static char log[65536];
	union bpf_attr a;
	int prog, link;

	if (argc != 4 || sscanf(argv[2], "%x:%x:%x:%x:%x:%x", &m[0], &m[1], &m[2], &m[3], &m[4], &m[5]) != 6 ||
	    (strcmp(argv[3], "skb") && strcmp(argv[3], "drv"))) {
		fprintf(stderr, "usage: %s IFNAME SRC_MAC skb|drv\n", argv[0]);
		return 2;
	}
	ifindex = if_nametoindex(argv[1]);
	if (!ifindex) {
		perror(argv[1]);
		return 1;
	}
	/* big-endian MIPS: a u32 load of bytes 6..9 is m0 m1 m2 m3, a u16 load of 10..11 is m4 m5 */
	hi = m[0] << 24 | m[1] << 16 | m[2] << 8 | m[3];
	lo = m[4] << 8 | m[5];

	struct bpf_insn insn[] = {
		LDX(BPF_W, 2, 1, 0),		/* r2 = ctx->data */
		LDX(BPF_W, 3, 1, 4),		/* r3 = ctx->data_end */
		MOV_REG(4, 2),
		ADD_IMM(4, 12),
		JGT_REG(4, 3, 6),		/* < 12 bytes: pass */
		LDX(BPF_W, 5, 2, 6),		/* source MAC bytes 0-3 */
		JNE_IMM(5, (int)hi, 4),
		LDX(BPF_H, 5, 2, 10),		/* source MAC bytes 4-5 */
		JNE_IMM(5, (int)lo, 2),
		MOV_IMM(0, XDP_DROP),
		EXIT(),
		MOV_IMM(0, XDP_PASS),		/* pass: */
		EXIT(),
	};

	memset(&a, 0, sizeof(a));
	a.prog_type = BPF_PROG_TYPE_XDP;
	a.insns = (unsigned long)insn;
	a.insn_cnt = sizeof(insn) / sizeof(insn[0]);
	a.license = (unsigned long)"GPL";
	a.log_buf = (unsigned long)log;
	a.log_size = sizeof(log);
	a.log_level = 1;
	prog = bpf(BPF_PROG_LOAD, &a);
	if (prog < 0) {
		fprintf(stderr, "BPF_PROG_LOAD: %s\n%s\n", strerror(errno), log);
		return 1;
	}

	memset(&a, 0, sizeof(a));
	a.link_create.prog_fd = prog;
	a.link_create.target_ifindex = ifindex;
	a.link_create.attach_type = BPF_XDP;
	a.link_create.flags = strcmp(argv[3], "drv") ? XDP_FLAGS_SKB_MODE : XDP_FLAGS_DRV_MODE;
	link = bpf(BPF_LINK_CREATE, &a);
	if (link < 0) {
		fprintf(stderr, "BPF_LINK_CREATE %s %s: %s\n", argv[1], argv[3], strerror(errno));
		return 1;
	}
	printf("ATTACHED %s %s drop src %s\n", argv[1], argv[3], argv[2]);
	fflush(stdout);
	signal(SIGTERM, on_sig);
	signal(SIGINT, on_sig);
	while (!stop)
		pause();
	close(link);	/* detaches */
	printf("DETACHED %s\n", argv[1]);
	return 0;
}
