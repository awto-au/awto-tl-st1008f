# SoC crypto engine (RTL9303)

Issues #62 (engine), #78 (Linux offload). Run: `./dev.py crypto-test` at our U-Boot prompt (`rtk crypto probe|test|bench`). Code: `uboot-port/board/tplink/tl-st1008f/rtk_crypto.c`.

## Identity

- Block `IPSEC_CRYPTO` at `0xb800c000` (KSEG1), clock gate `IP_EN_CTRL` `0xb8000600` bit 10 `EN_IPSEC` (set at reset), IRQ GIMR bit 22 `SECURITY_IE` [SOC `rtl9300_soc_reg.h`].
- Same 4 registers and fields as the RTL865xC/RTL8686 "crypto engine" in the SDK test tree (`uboot-xgs1210/arch/otto/cpu/rlx5281/rtl8686/rtk_soc/test/crypto/crypto/`): `IPSSDAR`, `IPSDDAR`, `IPSCSR`, `IPSCTR`. Driver logic below follows `rtl865xc_ipsecEngine.c` and `rtl865xc_authEngine.c`.
- RTL8380 and RTL9310 SDK maps carry the same block (`0xc000`); not described in the RTL9303 datasheet beyond Fig. 1 "Crypto Engine".

## Registers

| Off | Name | Fields |
|---|---|---|
| `0x0` | IPSSDAR | source descriptor ring base (physical) |
| `0x4` | IPSDDAR | destination descriptor ring base (physical) |
| `0x8` | IPSCSR | 15 SDUE, 14 SDLE, 13 DDUE, 12 DDOK, 11 DABF (W1C), 8 DBGS, 1 POLL (kick), 0 SRST |
| `0xc` | IPSCTR | 15-11 IRQ enables, 8 LBKM, 7 SAWB, 6 CKE, 5:3 DMBS, 2:0 SMBS (burst 16 << n B, n = 0-3) |

- SDUE / SDLE: source descriptor unavailable / length error. DDUE / DDOK: destination unavailable / done. DABF: data address buffer error.
- SAWB = result written back to the source buffers; CKE = clock enable.

## Descriptors (big-endian words)

Source, 16 B:

| Word | Bits |
|---|---|
| 0 | 31 OWN, 30 EOR, 29 FS, 27:26 MS, 25:23 KAM, 22:21 AESKL, 20 3DES, 19 CBC, 18 CTR, 17 HMAC, 16 MD5, 13:0 SBL |
| 1 | 23:16 A2EO, 13:0 ENL |
| 2 | 23:16 APL |
| 3 | buffer physical address |

- MS: 0 cipher, 1 hash, 2 hash-then-decrypt, 3 encrypt-then-hash.
- KAM: AES/DES 7 = encrypt, 0 = decrypt; 3DES 5 = encrypt, 2 = decrypt.
- AESKL: 0 = DES/3DES, 1/2/3 = AES-128/192/256.
- SBL = this buffer's length; ENL = cipher length; A2EO = auth-only prefix (4-B aligned); APL = hash padding length. All 14-bit: max 16383 B per job.

Destination, 32 B: word 0 = 31 OWN, 30 EOR, 13:0 DBL; word 1 = buffer address; word 2 reserved; words 3-7 = ICV (digest, byte order as output).

## Job layout

- Cipher: `[key FS + mode bits] [IV] [data...]`; destination = the data buffer (in place).
- Hash / HMAC: `[ipad||opad 128 B, FS + MS 1] [data...] [padding APL B]`; padding = `0x80`, zeros, bit length (SHA1 BE, MD5 LE; HMAC counts +64 B). Digest in destination ICV.
- Keys longer than 64 B for HMAC are hashed on the CPU first (SDK).
- 3DES decrypt: key array (K3, K2, K1).
- AES decrypt: key array = last round key(s) of the encrypt schedule: 128 = round 10; 192 = round 12 + last 8 B of round 11; 256 = round 14 + round 13 (SDK `cryptoCmd.c`).
- Sequence: SRST, ring bases, `IPSCTR` = SAWB | CKE | burst, clear W1C; per job write destination then source descriptors (OWN word last), clear W1C, set POLL, poll DDOK (SDLE/DABF/DDUE = error).
- Limits: AES ENL multiple of 16, ≤ 16368; DES ≤ 16376, multiple of 8; hash len + APL ≤ 16383 (HMAC < 16320). No hash continuation: one job = one message.

- Completion: DDOK can be set before the destination descriptor's OWN write-back (measured: bench jobs read OWN = 1 after DDOK). Done = DDOK and OWN = 0.
- DMA burst (SMBS/DMBS 16-128 B) does not change throughput: the engine is compute-bound.

## Measured (2026-10-12)

Conditions: our U-Boot via `./dev.py ramload uboot-mainline` (CPU 1000 MHz, LX 175 MHz); `./dev.py crypto-test run`, raw output in `tmp/crypto_test-<label>.json`.

- Presence: `IP_EN_CTRL` = `0x40000f88` (EN_IPSEC 1). Power-up values (stock boot, then ours): IPSSDAR `9fc0ffb0`, IPSDDAR `9fc0ffe0`, IPSCSR 0, IPSCTR `000010d2` (CKE, SAWB, 64 B bursts, DDOK IE). Ring registers read back as written; after a job they hold the next descriptor address.
- KAT: 25/25 PASS (vectors in `scripts/crypto_test.py`): AES-128/192/256 ECB (FIPS-197), AES-128 ECB 4 blocks, AES-128/192/256 CBC, AES-128/256 CTR (SP800-38A), DES ECB/CBC (FIPS 81), 3DES ECB/CBC (SP800-67), MD5 x3 (RFC 1321), SHA1 x2 (FIPS 180), HMAC-MD5 x3, HMAC-SHA1 x3 (RFC 2202, incl. 80-byte key). Each cipher vector checked both ways (encrypt, then decrypt the published ciphertext).
- Small jobs (16-80 B): 1-7 us kick to done.
- CTR: full 128-bit big-endian counter increment per block matches SP800-38A.

1 MiB, 16368-B jobs (hash: 16192-B messages). `eng` = kick-to-done time only; `hw` adds CPU setup and cache ops; `sw` = U-Boot software on the 1 GHz CPU. LX cyc/B = LX clock / eng rate.

| Algorithm | eng MB/s | hw MB/s | sw MB/s | LX cyc/B |
|---|---|---|---|---|
| AES-128-CBC enc | 29.38 | 28.94 | 3.85 | 5.96 |
| AES-128-CBC dec | 28.19 | 27.70 | 3.33 | 6.21 |
| AES-256-CBC enc | 23.46 | 23.18 | 2.78 | 7.46 |
| AES-128-ECB / CTR | 29.38 | 28.94 | 4.00 / 3.79 | 5.96 |
| DES-CBC | 43.55 | 42.58 | - | 4.02 |
| 3DES-CBC | 21.82 | 21.57 | - | 8.02 |
| MD5 | 56.59 | 53.66 | 61.69 | 3.09 |
| SHA1 | 45.50 | 43.58 | 56.04 | 3.85 |
| HMAC-SHA1 | 44.95 | 42.57 | 54.98 | - |

- Longest job: 3DES 750 us per 16368 B; AES-128 557 us; SHA1 356 us.
- Engine clock = LX: at LX 204.17 MHz (`--lx 4`) every rate scales by 1.166 (= 204.17 / 175): AES-128 34.27, 3DES 25.46, SHA1 53.06, MD5 66.00 MB/s.
- U-Boot software AES is the byte-oriented reference implementation; it is not a proxy for Linux/OpenSSL AES.
- Job timeout in `rtk_crypto.c`: 8 LX cycles/B (3DES) + 4096 cycles at LX 133 MHz x1.25 = 1.27 ms for 16368 B.

## Linux driver: value

- Ceiling at stock LX: AES-128 ~29 MB/s (~235 Mbit/s), 3DES 22 MB/s, SHA1 45 MB/s; single engine, synchronous rings, 16 KiB max per job.
- Hashing: the 1 GHz CPU is faster (U-Boot software MD5/SHA1 beats the engine). No SHA-2.
- No GCM, ChaCha20/Poly1305 or SHA-256: WireGuard, TLS 1.3 and modern IPsec suites cannot use it. Fits only AES-CBC/CTR + HMAC-SHA1 IPsec (combined MS 2/3 modes, untested).
- Gain is CPU offload for AES only; whether it is faster than Linux software AES on this core is not measured (#78).
