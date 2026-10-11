// SPDX-License-Identifier: GPL-2.0+
/*
 * `rtk crypto probe|test|bench`: SoC crypto engine (IPSEC_* 0xb800c000, RTL865xC-class), #62.
 * Descriptors and sequence: Realtek SDK rtl865xc_ipsecEngine.c / rtl865xc_authEngine.c (docs/CRYPTO.md).
 */

#include <command.h>
#include <cpu_func.h>
#include <div64.h>
#include <time.h>
#include <uboot_aes.h>
#include <asm/io.h>
#include <linux/delay.h>
#include <linux/sizes.h>
#include <linux/string.h>
#include <u-boot/md5.h>
#include <u-boot/sha1.h>
#include "rtk.h"

#define IP_EN_CTRL	0xb8000600
#define IP_EN_IPSEC	BIT(10)
#define IPS		0xb800c000
#define IPSSDAR		0x0
#define IPSDDAR		0x4
#define IPSCSR		0x8
#define IPSCTR		0xc
#define CSR_SDUE	BIT(15)
#define CSR_SDLE	BIT(14)
#define CSR_DDUE	BIT(13)
#define CSR_DDOK	BIT(12)
#define CSR_DABF	BIT(11)
#define CSR_PEND	0xf800
#define CSR_POLL	BIT(1)
#define CSR_SRST	BIT(0)
#define CTR_SAWB	BIT(7)
#define CTR_CKE		BIT(6)

/* source descriptor word 0 (BE bitfields of rtl865xc_crypto_source_t, MSB first) */
#define D_OWN		BIT(31)
#define D_EOR		BIT(30)
#define D_FS		BIT(29)
#define D_MS(x)		((x) << 26)	/* 0 crypto, 1 auth, 2 auth+dec, 3 enc+auth */
#define D_KAM(x)	((x) << 23)	/* 7 enc, 0 dec (AES/DES); 5 enc, 2 dec (3DES) */
#define D_AESKL(x)	((x) << 21)	/* 0 DES, 1/2/3 = AES-128/192/256 */
#define D_3DES		BIT(20)
#define D_CBC		BIT(19)
#define D_CTR		BIT(18)
#define D_HMAC		BIT(17)
#define D_MD5		BIT(16)

struct sdesc { u32 w0, w1, w2, addr; };			/* w1: a2eo<<16 | enl; w2: apl<<16 */
struct ddesc { u32 w0, addr, rsv, icv[5]; };		/* w0: own, eor, dbl[13:0] */

/* DMA scratch: KSEG0 0x83000000.., below SYS_LOAD_ADDR 0x84f00000; bench.c also scribbles here */
#define MEM		0x83000000UL
#define UC(a)		((a) | 0x20000000UL)
#define PHYS(a)		((u32)(a) & 0x1fffffff)
#define NSRC		16
#define NDST		4
#define SRING		((volatile struct sdesc *)UC(MEM))
#define DRING		((volatile struct ddesc *)UC(MEM + 0x400))
#define KEYB		((u8 *)UC(MEM + 0x1000))	/* 32 B key array */
#define IVB		((u8 *)UC(MEM + 0x1040))	/* 16 B IV array */
#define PADB		((u8 *)UC(MEM + 0x1080))	/* 128 B ipad || opad */
#define APLB		((u8 *)UC(MEM + 0x1100))	/* <= 128 B hash padding */
#define BUF		(MEM + 0x100000)		/* 1 MiB + guard: engine (in place) */
#define REF		(MEM + 0x200000)		/* 1 MiB: software result */
#define ORIG		(MEM + 0x300000)		/* 1 MiB: plaintext */
#define CHUNK		16368		/* max enl (14 bits) that is a multiple of 16 */
#define HCHUNK		16192		/* HMAC: len + apl < 0x3fc0 (SDK limit) */

/*
 * Job timeout: worst-case 32 LX cycles/B (SPEC: 3DES-class engine) + 4096 cycles setup, at the
 * slowest LX the SPL accepts (133 MHz, docs/CLOCKS.md), x1.25. Measured per-job times: docs/CRYPTO.md.
 */
#define LX_MIN_MHZ	133
#define JOB_US(b)	(((b) * 32 + 4096) / LX_MIN_MHZ * 5 / 4)

enum { KAT_AES, KAT_DES, KAT_3DES, KAT_MD5, KAT_SHA1, KAT_HMAC_MD5, KAT_HMAC_SHA1 };
enum { KAT_NONE, KAT_ECB, KAT_CBC, KAT_CTR };

struct kat {
	const char *name;
	int alg, mode, klen, ivlen, len, olen;
	const u8 *key, *iv, *in, *out;
};

#include "rtk_crypto_kat.h"

static int src_i, dst_i, burst = 3;	/* burst code: 16 << n bytes; 3 = 128 B, map max */
static int hash_layout;			/* 0: SDK authEngine dst (dbl 0); 1: ipsecEngine dst */
static u64 job_ticks;

static u32 ir(u32 off) { return __raw_readl((void __iomem *)(IPS + off)); }
static void iw(u32 off, u32 v) { __raw_writel(v, (void __iomem *)(IPS + off)); }

static u64 us_to_ticks(u32 us)
{
	u64 t = (u64)us * get_tbclk();

	do_div(t, 1000000);
	return t;
}

static u32 ticks_to_us(u64 t)
{
	t *= 1000000;
	do_div(t, (u32)get_tbclk());
	return (u32)t;
}

static void eng_init(void)
{
	int i;

	iw(IPSCSR, ir(IPSCSR) | CSR_SRST);
	udelay(10);	/* SDK: "delay a while after software reset", no figure; 10 us = 1750 LX cycles */
	for (i = 0; i < NSRC; i++)
		SRING[i].w0 = SRING[i].w1 = SRING[i].w2 = SRING[i].addr = 0;
	for (i = 0; i < NDST; i++)
		memset((void *)&DRING[i], 0, sizeof(struct ddesc));
	SRING[NSRC - 1].w0 = D_EOR;
	DRING[NDST - 1].w0 = D_EOR;
	iw(IPSSDAR, PHYS(SRING));
	iw(IPSDDAR, PHYS(DRING));
	iw(IPSCTR, CTR_SAWB | CTR_CKE | burst << 3 | burst);
	iw(IPSCSR, CSR_PEND);	/* write 1 to clear */
	src_i = dst_i = 0;
}

static int put_src(u32 w0, u32 w1, u32 w2, u32 addr)
{
	volatile struct sdesc *d = &SRING[src_i];

	if (d->w0 & D_OWN) {
		printf("crypto: src desc %d still engine-owned\n", src_i);
		return -1;
	}
	d->w1 = w1;
	d->w2 = w2;
	d->addr = addr;
	d->w0 = w0 | D_OWN | (src_i == NSRC - 1 ? D_EOR : 0);	/* own last */
	src_i = (src_i + 1) % NSRC;
	return 0;
}

static volatile struct ddesc *put_dst(u32 dbl, u32 addr)
{
	volatile struct ddesc *d = &DRING[dst_i];

	d->addr = addr;
	d->rsv = 0;
	d->w0 = D_OWN | (dst_i == NDST - 1 ? D_EOR : 0) | dbl;
	dst_i = (dst_i + 1) % NDST;
	return d;
}

/* kick and poll; bytes = DMA volume, sets the timeout */
static int eng_run(const char *what, u32 bytes, volatile struct ddesc *d)
{
	u64 t0, lim = us_to_ticks(JOB_US(bytes));
	u32 v;

	__asm__ __volatile__("sync" ::: "memory");
	iw(IPSCSR, CSR_PEND);
	t0 = get_ticks();
	iw(IPSCSR, CSR_POLL);
	while (!((v = ir(IPSCSR)) & (CSR_DDOK | CSR_SDLE | CSR_DABF | CSR_DDUE))) {
		if (get_ticks() - t0 > lim) {
			printf("crypto: %s TIMEOUT limit %u us elapsed %u us CSR %08x dst.w0 %08x\n", what,
			       JOB_US(bytes), ticks_to_us(get_ticks() - t0), v, d->w0);
			eng_init();
			return -1;
		}
	}
	job_ticks = get_ticks() - t0;
	if (v & (CSR_SDLE | CSR_DABF | CSR_DDUE) || d->w0 & D_OWN) {
		printf("crypto: %s error CSR %08x dst.w0 %08x\n", what, v, d->w0);
		eng_init();
		return -1;
	}
	iw(IPSCSR, CSR_PEND);
	return 0;
}

/* AES/DES/3DES in place on KSEG0 `data`; AES decrypt takes the last round key(s) (SDK cryptoCmd.c) */
static int eng_cipher(int alg, int mode, bool enc, const u8 *key, int klen, const u8 *iv, ulong data, u32 len)
{
	u8 exp[AES256_EXPAND_KEY_LENGTH];
	int ivlen = alg == KAT_AES ? 16 : 8, kl = klen;
	u32 w0 = D_MS(0);

	if (!len || len > (alg == KAT_AES ? CHUNK : 16376) || len % ivlen)
		return -1;
	if (alg == KAT_AES) {
		if (mode == KAT_CTR)
			enc = true;	/* CTR: keystream = encrypt */
		w0 |= D_AESKL(klen / 8 - 1) | D_KAM(enc ? 7 : 0);
		if (!enc) {
			aes_expand_key((u8 *)key, klen, exp);
			memcpy(KEYB, exp + 16 * (klen / 4 + 6), 16);
			if (klen == 24)
				memcpy(KEYB + 16, exp + 184, 8);
			if (klen == 32)
				memcpy(KEYB + 16, exp + 208, 16);
		} else {
			memcpy(KEYB, key, klen);
		}
	} else if (alg == KAT_3DES) {
		w0 |= D_3DES | D_KAM(enc ? 5 : 2);
		kl = 24;
		memcpy(KEYB, key + (enc ? 0 : 16), 8);	/* decrypt: (K3, K2, K1) */
		memcpy(KEYB + 8, key + 8, 8);
		memcpy(KEYB + 16, key + (enc ? 16 : 0), 8);
	} else {
		w0 |= D_KAM(enc ? 7 : 0);
		kl = 8;
		memcpy(KEYB, key, 8);
	}
	w0 |= mode == KAT_CBC ? D_CBC : mode == KAT_CTR ? D_CTR : 0;
	if (iv)
		memcpy(IVB, iv, ivlen);
	else
		memset(IVB, 0, ivlen);
	flush_dcache_range(data, data + len);
	{
		volatile struct ddesc *d = put_dst(len, PHYS(data));

		if (put_src(w0 | D_FS | kl, len, 0, PHYS(KEYB)) || put_src(ivlen, len, 0, PHYS(IVB)) ||
		    put_src(len, len, 0, PHYS(data)))
			return -1;
		if (eng_run("cipher", len * 2, d))
			return -1;
	}
	invalidate_dcache_range(data, data + len);
	return 0;
}

static void sw_hash(bool sha1, const u8 *p, u32 len, u8 *out)
{
	if (sha1) {
		sha1_context c;

		sha1_starts(&c);
		sha1_update(&c, p, len);
		sha1_finish(&c, out);
	} else {
		MD5Context c;

		MD5Init(&c);
		MD5Update(&c, p, len);
		MD5Final(out, &c);
	}
}

/* MD5/SHA1 (+HMAC) of KSEG0 `data`: PAD (fs) + data + padding descriptors; digest from dst ICV */
static int eng_hash(bool sha1, bool hmac, const u8 *key, int klen, ulong data, u32 len, u8 *dig)
{
	u32 icv[5];
	u8 hk[20];
	u32 apl = ALIGN(len, 64) - len, w0 = D_MS(1) | (hmac ? D_HMAC : 0) | (sha1 ? 0 : D_MD5);
	u64 bits;
	int i;
	volatile struct ddesc *d;

	if (apl <= 8)
		apl += 64;
	if (len + apl > (hmac ? 0x3fbf : 0x3fff))
		return -1;
	memset(PADB, 0, 128);
	if (hmac) {
		if (klen > 64) {	/* RFC 2104: long key = H(key), on the CPU as in the SDK */
			sw_hash(sha1, key, klen, hk);
			key = hk;
			klen = sha1 ? 20 : 16;
		}
		memset(PADB, 0x36, 64);
		memset(PADB + 64, 0x5c, 64);
		for (i = 0; i < klen; i++) {
			PADB[i] ^= key[i];
			PADB[64 + i] ^= key[i];
		}
	}
	memset(APLB, 0, apl);
	APLB[0] = 0x80;
	bits = (u64)(len + (hmac ? 64 : 0)) << 3;
	for (i = 0; i < 8; i++)
		APLB[sha1 ? apl - 1 - i : apl - 8 + i] = bits >> (8 * i);
	flush_dcache_range(data, data + len + apl);
	d = hash_layout ? put_dst(len + apl, PHYS(data)) : put_dst(0, 0);
	if (put_src(w0 | D_FS | 128, len, apl << 16, PHYS(PADB)) || put_src(len, len, apl << 16, PHYS(data)) ||
	    put_src(w0 | apl, len, apl << 16, PHYS(APLB)))
		return -1;
	if (eng_run("hash", len + apl + 128, d))
		return -1;
	invalidate_dcache_range(data, data + ALIGN(len + apl, 32));
	for (i = 0; i < 5; i++)
		icv[i] = d->icv[i];
	memcpy(dig, icv, sha1 ? 20 : 16);
	return 0;
}

static void hex(const u8 *p, int n)
{
	while (n--)
		printf("%02x", *p++);
}

static int kat_one(const struct kat *k)
{
	u8 out[64], dig[20];
	bool hash = k->alg >= KAT_MD5, sha1 = k->alg == KAT_SHA1 || k->alg == KAT_HMAC_SHA1;
	const char *fail = NULL;
	u32 us_e = 0, us_d = 0;

	memcpy((void *)BUF, k->in, k->len);
	if (hash) {
		if (eng_hash(sha1, k->alg >= KAT_HMAC_MD5, k->key, k->klen, BUF, k->len, dig))
			fail = "engine error";
		else if (memcmp(dig, k->out, k->olen))
			fail = "digest";
		memcpy(out, dig, k->olen);
		us_e = ticks_to_us(job_ticks);
	} else {
		if (eng_cipher(k->alg, k->mode, true, k->key, k->klen, k->ivlen ? k->iv : NULL, BUF, k->len))
			fail = "engine error (enc)";
		memcpy(out, (void *)BUF, k->len);
		us_e = ticks_to_us(job_ticks);
		if (!fail && memcmp(out, k->out, k->olen))
			fail = "ciphertext";
		/* decrypt the published ciphertext back to the plaintext */
		memcpy((void *)BUF, k->out, k->len);
		if (!fail && eng_cipher(k->alg, k->mode, false, k->key, k->klen, k->ivlen ? k->iv : NULL,
					BUF, k->len))
			fail = "engine error (dec)";
		us_d = ticks_to_us(job_ticks);
		if (!fail && memcmp((void *)BUF, k->in, k->len))
			fail = "decrypt";
	}
	printf("kat %s %s %u us", k->name, fail ? "FAIL" : "PASS", us_e);
	if (!hash)
		printf(" dec %u us", us_d);
	if (fail) {
		printf(" (%s) got ", fail);
		hex(fail[0] == 'd' && fail[1] == 'e' ? (u8 *)BUF : out, k->olen > 32 ? 32 : k->olen);
	}
	printf("\n");
	return !fail;
}

static int crypto_probe(void)
{
	u32 ip = __raw_readl((void __iomem *)IP_EN_CTRL);
	u32 sd = ir(IPSSDAR), dd = ir(IPSDDAR), cs = ir(IPSCSR), ct = ir(IPSCTR);
	bool rsv = (cs & 0xffff06fc) || (ct & 0xffff0600);

	printf("IP_EN_CTRL %08x EN_IPSEC %u\n", ip, !!(ip & IP_EN_IPSEC));
	printf("IPSSDAR %08x IPSDDAR %08x IPSCSR %08x IPSCTR %08x\n", sd, dd, cs, ct);
	printf("CSR: SDUE %u SDLE %u DDUE %u DDOK %u DABF %u POLL %u SRST %u\n", !!(cs & CSR_SDUE),
	       !!(cs & CSR_SDLE), !!(cs & CSR_DDUE), !!(cs & CSR_DDOK), !!(cs & CSR_DABF), !!(cs & CSR_POLL),
	       !!(cs & CSR_SRST));
	printf("CTR: IE %02x LBKM %u SAWB %u CKE %u DMBS %u B SMBS %u B\n", ct >> 11 & 0x1f, !!(ct & BIT(8)),
	       !!(ct & CTR_SAWB), !!(ct & CTR_CKE), 16 << (ct >> 3 & 7), 16 << (ct & 7));
	if (!(ip & IP_EN_IPSEC) || (!sd && !dd && !cs && !ct) || rsv || ct == 0xffffffff)
		printf("crypto: absent or gated (reserved bits %s)\n", rsv ? "set" : "clear");
	else
		printf("crypto: present (registers decode; `rtk crypto test` confirms)\n");
	return 0;
}

static int crypto_test(void)
{
	int i, n = ARRAY_SIZE(kats), pass = 0, layout;

	eng_init();
	if (ir(IPSSDAR) != PHYS(SRING) || ir(IPSDDAR) != PHYS(DRING)) {
		printf("crypto: ring registers did not take: SDAR %08x DDAR %08x\n", ir(IPSSDAR), ir(IPSDDAR));
		return CMD_RET_FAILURE;
	}
	printf("crypto: engine reset, rings at %08x/%08x, CTR %08x\n", PHYS(SRING), PHYS(DRING), ir(IPSCTR));
	for (i = 0; i < n; i++) {
		if (kats[i].alg >= KAT_MD5 && (!i || kats[i - 1].alg < KAT_MD5)) {
			for (layout = 0; layout < 2; layout++) {	/* first hash: find the dst layout */
				hash_layout = layout;
				printf("hash dst layout %d: ", layout);
				if (kat_one(&kats[i]))
					break;
			}
			if (layout == 2)
				hash_layout = 0;
			pass += layout < 2;
			continue;
		}
		pass += kat_one(&kats[i]);
	}
	printf("kat total %d pass %d (hash dst layout %d)\n", n, pass, hash_layout);
	return pass == n ? 0 : CMD_RET_FAILURE;
}

/* MB/s with 3 decimals from bytes and CP0 ticks */
static void mbs(const char *tag, u32 bytes, u64 ticks)
{
	u64 v = (u64)bytes * get_tbclk();

	do_div(v, ticks ? (u32)ticks : 1);
	do_div(v, 1000);
	printf(" %s %u.%03u MB/s", tag, (u32)v / 1000, (u32)v % 1000);
}

static void fill(ulong p, u32 len)
{
	u32 i;

	for (i = 0; i < len; i++)
		((u8 *)p)[i] = (i * 7 + (i >> 8)) & 0xff;
}

static void ctr_add(u8 *ctr, u32 n)
{
	int i;

	for (i = 15; i >= 0 && n; i--, n >>= 8) {
		u32 s = ctr[i] + (n & 0xff);

		ctr[i] = s;
		n += s & 0x100;
	}
}

/* 1 MiB AES on the engine (CHUNK jobs, chained IV/counter) vs U-Boot software; 0 = outputs match */
static int bench_aes(const char *name, int mode, bool enc, int klen)
{
	static const u8 key[32] = { 0x60, 0x3d, 0xeb, 0x10, 0x15, 0xca, 0x71, 0xbe, 0x2b, 0x73, 0xae, 0xf0,
				    0x85, 0x7d, 0x77, 0x81, 0x1f, 0x35, 0x2c, 0x07, 0x3b, 0x61, 0x08, 0xd7,
				    0x2d, 0x98, 0x10, 0xa3, 0x09, 0x14, 0xdf, 0xf4 };
	u8 exp[AES256_EXPAND_KEY_LENGTH], iv[16], ks[16];
	u32 off, n, i, j;
	u64 t0, th, ts;
	int bad;

	fill(ORIG, SZ_1M);
	memcpy((void *)BUF, (void *)ORIG, SZ_1M);
	memset(iv, 0xa5, 16);
	t0 = get_ticks();
	for (off = 0; off < SZ_1M; off += n) {
		n = min_t(u32, CHUNK, SZ_1M - off);
		if (eng_cipher(KAT_AES, mode, enc, key, klen, iv, BUF + off, n)) {
			printf("cbench %s hw error at %u\n", name, off);
			return -1;
		}
		if (mode == KAT_CBC)	/* next IV = last ciphertext block */
			memcpy(iv, (u8 *)(enc ? BUF : ORIG) + off + n - 16, 16);
		if (mode == KAT_CTR)
			ctr_add(iv, n / 16);
	}
	th = get_ticks() - t0;

	memset(iv, 0xa5, 16);
	aes_expand_key((u8 *)key, klen, exp);
	t0 = get_ticks();
	if (mode == KAT_CBC && enc)
		aes_cbc_encrypt_blocks(klen, exp, iv, (u8 *)ORIG, (u8 *)REF, SZ_1M / 16);
	else if (mode == KAT_CBC)
		aes_cbc_decrypt_blocks(klen, exp, iv, (u8 *)ORIG, (u8 *)REF, SZ_1M / 16);
	else
		for (i = 0; i < SZ_1M; i += 16) {
			if (mode == KAT_ECB) {
				if (enc)
					aes_encrypt(klen, (u8 *)ORIG + i, exp, (u8 *)REF + i);
				else
					aes_decrypt(klen, (u8 *)ORIG + i, exp, (u8 *)REF + i);
				continue;
			}
			aes_encrypt(klen, iv, exp, ks);
			for (j = 0; j < 16; j++)
				((u8 *)REF)[i + j] = ((u8 *)ORIG)[i + j] ^ ks[j];
			ctr_add(iv, 1);
		}
	ts = get_ticks() - t0;
	bad = memcmp((void *)BUF, (void *)REF, SZ_1M);
	printf("cbench %s", name);
	mbs("hw", SZ_1M, th);
	mbs("sw", SZ_1M, ts);
	printf(" job %u us verify %s\n", ticks_to_us(job_ticks), bad ? "MISMATCH" : "ok");
	return bad;
}

/* 1 MiB DES/3DES CBC: engine encrypt then decrypt must return the plaintext (no U-Boot DES) */
static int bench_des(const char *name, int alg)
{
	static const u8 key[24] = { 0x01, 0x23, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef, 0x23, 0x45, 0x67, 0x89,
				    0xab, 0xcd, 0xef, 0x01, 0x45, 0x67, 0x89, 0xab, 0xcd, 0xef, 0x01, 0x23 };
	u8 iv[8], prev[8];
	u32 off, n;
	u64 t0, te = 0, td = 0;
	int pass, bad;

	fill(ORIG, SZ_1M);
	memcpy((void *)BUF, (void *)ORIG, SZ_1M);
	for (pass = 0; pass < 2; pass++) {
		memset(iv, 0x5a, 8);
		t0 = get_ticks();
		for (off = 0; off < SZ_1M; off += n) {
			n = min_t(u32, CHUNK, SZ_1M - off);
			memcpy(prev, (u8 *)BUF + off + n - 8, 8);
			if (eng_cipher(alg, KAT_CBC, !pass, key, 24, iv, BUF + off, n)) {
				printf("cbench %s hw error at %u\n", name, off);
				return -1;
			}
			memcpy(iv, pass ? prev : (u8 *)BUF + off + n - 8, 8);
		}
		td = get_ticks() - t0;
		if (!pass)
			te = td;
	}
	bad = memcmp((void *)BUF, (void *)ORIG, SZ_1M);
	printf("cbench %s", name);
	mbs("hw", SZ_1M, te);
	mbs("hw-dec", SZ_1M, td);
	printf(" sw - job %u us verify %s\n", ticks_to_us(job_ticks), bad ? "MISMATCH" : "roundtrip ok");
	return bad;
}

/* MD5/SHA1/HMAC over 1 MiB in HCHUNK messages (engine has no hash continuation) vs software */
static int bench_hash(const char *name, bool sha1, bool hmac)
{
	static const u8 key[20] = "rtl9303-crypto-key!";
	u8 dh[20], ds[20], k[128], tmp[20];
	u32 off, n, bad = 0, i, dl = sha1 ? 20 : 16;
	u64 t0, th = 0, ts = 0;

	fill(ORIG, SZ_1M);
	for (off = 0; off < SZ_1M; off += n) {
		n = min_t(u32, HCHUNK, SZ_1M - off);
		memcpy((void *)BUF, (u8 *)ORIG + off, n);
		t0 = get_ticks();
		if (eng_hash(sha1, hmac, key, sizeof(key), BUF, n, dh)) {
			printf("cbench %s hw error at %u\n", name, off);
			return -1;
		}
		th += get_ticks() - t0;
		t0 = get_ticks();
		if (hmac) {	/* H(K^opad || H(K^ipad || m)) */
			memset(k, 0, 128);
			for (i = 0; i < 64; i++) {
				k[i] = (i < sizeof(key) ? key[i] : 0) ^ 0x36;
				k[64 + i] = (i < sizeof(key) ? key[i] : 0) ^ 0x5c;
			}
			if (sha1) {
				sha1_context c;

				sha1_starts(&c);
				sha1_update(&c, k, 64);
				sha1_update(&c, (u8 *)ORIG + off, n);
				sha1_finish(&c, tmp);
				sha1_starts(&c);
				sha1_update(&c, k + 64, 64);
				sha1_update(&c, tmp, 20);
				sha1_finish(&c, ds);
			} else {
				MD5Context c;

				MD5Init(&c);
				MD5Update(&c, k, 64);
				MD5Update(&c, (u8 *)ORIG + off, n);
				MD5Final(tmp, &c);
				MD5Init(&c);
				MD5Update(&c, k + 64, 64);
				MD5Update(&c, tmp, 16);
				MD5Final(ds, &c);
			}
		} else {
			sw_hash(sha1, (u8 *)ORIG + off, n, ds);
		}
		ts += get_ticks() - t0;
		bad += !!memcmp(dh, ds, dl);
	}
	printf("cbench %s", name);
	mbs("hw", SZ_1M, th);
	mbs("sw", SZ_1M, ts);
	printf(" job %u us verify %s\n", ticks_to_us(job_ticks), bad ? "MISMATCH" : "ok");
	return bad;
}

static int crypto_bench(void)
{
	char name[32];
	int bad = 0;

	for (burst = 0; burst <= 3; burst++) {	/* DMA burst sweep; 3 (128 B) stays */
		eng_init();
		snprintf(name, sizeof(name), "aes128-cbc-enc-b%u", 16 << burst);
		bad |= bench_aes(name, KAT_CBC, true, 16);
	}
	burst = 3;
	eng_init();
	bad |= bench_aes("aes128-cbc-dec", KAT_CBC, false, 16);
	bad |= bench_aes("aes256-cbc-enc", KAT_CBC, true, 32);
	bad |= bench_aes("aes128-ecb-enc", KAT_ECB, true, 16);
	bad |= bench_aes("aes128-ctr", KAT_CTR, true, 16);
	bad |= bench_des("des-cbc", KAT_DES);
	bad |= bench_des("3des-cbc", KAT_3DES);
	bad |= bench_hash("md5", false, false);
	bad |= bench_hash("sha1", true, false);
	bad |= bench_hash("hmac-sha1", true, true);
	return bad ? CMD_RET_FAILURE : 0;
}

int rtk_crypto(int argc, char *const argv[])
{
	if (argc >= 3 && !strcmp(argv[2], "probe"))
		return crypto_probe();
	if (!(__raw_readl((void __iomem *)IP_EN_CTRL) & IP_EN_IPSEC)) {
		printf("crypto: IP_EN_CTRL EN_IPSEC = 0 (gated); not touching the block\n");
		return CMD_RET_FAILURE;
	}
	if (argc >= 3 && !strcmp(argv[2], "test"))
		return crypto_test();
	if (argc >= 3 && !strcmp(argv[2], "bench"))
		return crypto_bench();
	printf("rtk crypto probe | test | bench\n");
	return CMD_RET_USAGE;
}
