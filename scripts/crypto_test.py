#!/usr/bin/env python3
"""crypto_test — RTL9303 crypto engine (IPSEC_* 0xb800c000) known-answer tests + throughput (#62).

- `gen-kat`: NIST/RFC vectors below, each checked against host hashlib/cryptography, written to
  uboot-port/board/tplink/tl-st1008f/rtk_crypto_kat.h (build input; rerun after editing VECTORS).
- `run [--lx N]` (default): at our U-Boot prompt (optionally after `clocks set lx N force`): `rtk crypto probe`, `rtk crypto test`, `rtk crypto bench`;
  parses `kat`/`cbench` lines -> tmp/crypto_test-<label>.json. Log tmp/logs/crypto_test.log.
- Run via `./dev.py crypto-test [run --label L | gen-kat]`. Docs: docs/CRYPTO.md.
"""

import argparse
import hashlib
import hmac
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/crypto_test.log"
HDR = ROOT / "uboot-port/board/tplink/tl-st1008f/rtk_crypto_kat.h"
PROMPT = r"\r?\nst1008f-mainline # "

H = bytes.fromhex
SP38A_PT = H("6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
             "30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710")
FIPS81_PT = b"Now is the time for all "

# (name, alg, mode, key, iv, input, expected, source). alg: aes/des/3des/md5/sha1/hmac-md5/hmac-sha1
VECTORS = [
    ("aes128-ecb", "aes", "ecb", H("000102030405060708090a0b0c0d0e0f"), b"",
     H("00112233445566778899aabbccddeeff"), H("69c4e0d86a7b0430d8cdb78070b4c55a"), "FIPS-197 C.1"),
    ("aes192-ecb", "aes", "ecb", H("000102030405060708090a0b0c0d0e0f1011121314151617"), b"",
     H("00112233445566778899aabbccddeeff"), H("dda97ca4864cdfe06eaf70a0ec0d7191"), "FIPS-197 C.2"),
    ("aes256-ecb", "aes", "ecb", H("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f"), b"",
     H("00112233445566778899aabbccddeeff"), H("8ea2b7ca516745bfeafc49904b496089"), "FIPS-197 C.3"),
    ("aes128-ecb4", "aes", "ecb", H("2b7e151628aed2a6abf7158809cf4f3c"), b"", SP38A_PT,
     H("3ad77bb40d7a3660a89ecaf32466ef97f5d3d58503b9699de785895a96fdbaaf"
       "43b1cd7f598ece23881b00e3ed0306887b0c785e27e8ad3f8223207104725dd4"), "SP800-38A F.1.1"),
    ("aes128-cbc", "aes", "cbc", H("2b7e151628aed2a6abf7158809cf4f3c"), H("000102030405060708090a0b0c0d0e0f"),
     SP38A_PT, H("7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"
                 "73bed6b8e3c1743b7116e69e222295163ff1caa1681fac09120eca307586e1a7"), "SP800-38A F.2.1"),
    ("aes192-cbc", "aes", "cbc", H("8e73b0f7da0e6452c810f32b809079e562f8ead2522c6b7b"),
     H("000102030405060708090a0b0c0d0e0f"), SP38A_PT,
     H("4f021db243bc633d7178183a9fa071e8b4d9ada9ad7dedf4e5e738763f69145a"
       "571b242012fb7ae07fa9baac3df102e008b0e27988598881d920a9e64f5615cd"), "SP800-38A F.2.3"),
    ("aes256-cbc", "aes", "cbc", H("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4"),
     H("000102030405060708090a0b0c0d0e0f"), SP38A_PT,
     H("f58c4c04d6e5f1ba779eabfb5f7bfbd69cfc4e967edb808d679f777bc6702c7d"
       "39f23369a9d9bacfa530e26304231461b2eb05e2c39be9fcda6c19078c6a9d1b"), "SP800-38A F.2.5"),
    ("aes128-ctr", "aes", "ctr", H("2b7e151628aed2a6abf7158809cf4f3c"), H("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"),
     SP38A_PT, H("874d6191b620e3261bef6864990db6ce9806f66b7970fdff8617187bb9fffdff"
                 "5ae4df3edbd5d35e5b4f09020db03eab1e031dda2fbe03d1792170a0f3009cee"), "SP800-38A F.5.1"),
    ("aes256-ctr", "aes", "ctr", H("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4"),
     H("f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"), SP38A_PT,
     H("601ec313775789a5b7a7f504bbf3d228f443e3ca4d62b59aca84e990cacaf5c5"
       "2b0930daa23de94ce87017ba2d84988ddfc9c58db67aada613c2dd08457941a6"), "SP800-38A F.5.5"),
    ("des-ecb", "des", "ecb", H("133457799bbcdff1"), b"", H("0123456789abcdef"), H("85e813540f0ab405"),
     "DES classic (Grabbe)"),
    ("des-ecb3", "des", "ecb", H("0123456789abcdef"), b"", FIPS81_PT,
     H("3fa40e8a984d48156a271787ab8883f9893d51ec4b563b53"), "FIPS 81 B.1"),
    ("des-cbc", "des", "cbc", H("0123456789abcdef"), H("1234567890abcdef"), FIPS81_PT,
     H("e5c7cdde872bf27c43e934008c389c0f683788499a7c05f6"), "FIPS 81 C.1"),
    ("3des-ecb", "3des", "ecb", H("0123456789abcdef23456789abcdef01456789abcdef0123"), b"",
     b"The qufck brown fox jump", H("a826fd8ce53b855fcce21c8112256fe668d5c05dd9b6b900"), "SP800-67 B.1"),
    ("3des-cbc", "3des", "cbc", H("0123456789abcdef23456789abcdef01456789abcdef0123"), H("1234567890abcdef"),
     b"The qufck brown fox jump", None, "SP800-67 B.1 key, CBC (host OpenSSL)"),
    ("md5-abc", "md5", "", b"", b"", b"abc", H("900150983cd24fb0d6963f7d28e17f72"), "RFC 1321 A.5"),
    ("md5-msg", "md5", "", b"", b"", b"message digest", H("f96b697d7cb7938d525a2f31aaf161d0"), "RFC 1321 A.5"),
    ("md5-80", "md5", "", b"", b"", b"1234567890" * 8, H("57edf4a22be3c955ac49da2e2107b67a"), "RFC 1321 A.5"),
    ("sha1-abc", "sha1", "", b"", b"", b"abc", H("a9993e364706816aba3e25717850c26c9cd0d89d"), "FIPS 180 A.1"),
    ("sha1-448", "sha1", "", b"", b"", b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq",
     H("84983e441c3bd26ebaae4aa1f95129e5e54670f1"), "FIPS 180 A.2"),
    ("hmac-md5-1", "hmac-md5", "", b"\x0b" * 16, b"", b"Hi There", H("9294727a3638bb1c13f48ef8158bfc9d"),
     "RFC 2202 2.1"),
    ("hmac-md5-2", "hmac-md5", "", b"Jefe", b"", b"what do ya want for nothing?",
     H("750c783e6ab0b503eaa86e310a5db738"), "RFC 2202 2.2"),
    ("hmac-md5-6", "hmac-md5", "", b"\xaa" * 80, b"", b"Test Using Larger Than Block-Size Key - Hash Key First",
     H("6b1ab7fe4bd7bf8f0b62e6ce61b9d0cd"), "RFC 2202 2.6"),
    ("hmac-sha1-1", "hmac-sha1", "", b"\x0b" * 20, b"", b"Hi There",
     H("b617318655057264e28bc0b6fb378c8ef146be00"), "RFC 2202 3.1"),
    ("hmac-sha1-2", "hmac-sha1", "", b"Jefe", b"", b"what do ya want for nothing?",
     H("effcdf6ae5eb2fa2d27416d5f184df9c259a7c79"), "RFC 2202 3.2"),
    ("hmac-sha1-6", "hmac-sha1", "", b"\xaa" * 80, b"", b"Test Using Larger Than Block-Size Key - Hash Key First",
     H("aa4ae5e15272d00e95705637ce8a3b55ed402112"), "RFC 2202 3.6"),
]


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def host(alg: str, mode: str, key: bytes, iv: bytes, data: bytes) -> bytes:
    if alg in ("md5", "sha1"):
        return hashlib.new(alg, data).digest()
    if alg.startswith("hmac-"):
        return hmac.new(key, data, alg[5:]).digest()
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.decrepit.ciphers.algorithms import TripleDES
    algo = algorithms.AES(key) if alg == "aes" else TripleDES(key * 3 if alg == "des" else key)
    m = {"ecb": lambda: modes.ECB(), "cbc": lambda: modes.CBC(iv), "ctr": lambda: modes.CTR(iv)}[mode]()
    e = Cipher(algo, m).encryptor()
    return e.update(data) + e.finalize()


def c_bytes(b: bytes) -> str:
    return "{" + ", ".join(f"0x{x:02x}" for x in b) + "}" if b else "{0}"


def gen_kat() -> int:
    ids = {"aes": "KAT_AES", "des": "KAT_DES", "3des": "KAT_3DES", "md5": "KAT_MD5", "sha1": "KAT_SHA1",
           "hmac-md5": "KAT_HMAC_MD5", "hmac-sha1": "KAT_HMAC_SHA1"}
    md = {"": "KAT_NONE", "ecb": "KAT_ECB", "cbc": "KAT_CBC", "ctr": "KAT_CTR"}
    rows, bad = [], 0
    for name, alg, mode, key, iv, data, exp, src in VECTORS:
        got = host(alg, mode, key, iv, data)
        if exp is not None and got != exp:
            log(f"VECTOR MISMATCH {name} ({src}): published {exp.hex()} host {got.hex()}")
            bad += 1
        exp = got if exp is None else exp
        rows.append(f'\t{{"{name}", {ids[alg]}, {md[mode]}, {len(key)}, {len(iv)}, {len(data)}, {len(exp)},\n'
                    f'\t (const u8[]){c_bytes(key)},\n\t (const u8[]){c_bytes(iv)},\n'
                    f'\t (const u8[]){c_bytes(data)},\n\t (const u8[]){c_bytes(exp)}}}, /* {src} */')
    if bad:
        return 1
    HDR.write_text("/* SPDX-License-Identifier: GPL-2.0+ */\n"
                   "/* Generated by scripts/crypto_test.py gen-kat: NIST/RFC vectors, host-verified. Do not edit. */\n"
                   + "static const struct kat kats[] = {\n" + "\n".join(rows) + "\n};\n")
    log(f"gen-kat: {len(rows)} vectors verified against host libs -> {HDR.relative_to(ROOT)}")
    return 0


def run(label: str, lx: int | None) -> int:
    sys.path.insert(0, str(ROOT / "scripts"))
    from st1008_ramload import Console
    con, res = Console(), {"label": label, "lx": lx, "kat": {}, "bench": [], "probe": ""}
    out = ROOT / f"tmp/crypto_test-{label}.json"
    if lx is not None:  # engine clock check (#62); `clocks` prints ~10 lines, 1 s names a hang
        _, txt = con.run(f"clocks set lx {lx} force", PROMPT, 1, f"clocks set lx {lx}")
        res["clocks"] = txt
    # probe: 6 lines at 115200 = ~40 ms (measured < 0.1 s); 1 s names a hang
    _, txt = con.run("rtk crypto probe", PROMPT, 1, "crypto probe")
    res["probe"] = txt
    present = "crypto: present" in txt
    log(f"probe: {'present' if present else 'ABSENT/unknown'}")
    if present:
        # KATs: measured 0.1 s (50 jobs <= 7 us + ~30 lines at 115200); 1 s names a hang
        _, txt = con.run("rtk crypto test", PROMPT, 1, "crypto test")
        for m in re.finditer(r"^kat (\S+) (PASS|FAIL)(.*)$", txt, re.M):
            res["kat"][m.group(1)] = {"result": m.group(2), "detail": m.group(3).strip()}
        # bench: 3.3 s measured at CPU 1000 (software AES dominates); x1000/800 (stock CPU) x1.25 = 5.2 s
        _, txt = con.run("rtk crypto bench", PROMPT, 5.2, "crypto bench")
        res["bench"] = [m.group(0) for m in re.finditer(r"^cbench .*$", txt, re.M)]
    out.write_text(json.dumps(res, indent=1))
    npass = sum(v["result"] == "PASS" for v in res["kat"].values())
    log(f"KAT: {npass}/{len(res['kat'])} PASS")
    for k, v in res["kat"].items():
        log(f"  {k:14s} {v['result']} {v['detail']}")
    for b in res["bench"]:
        log(f"  {b}")
    log(f"saved {out.relative_to(ROOT)}")
    return 0 if present and res["kat"] and npass == len(res["kat"]) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", nargs="?", default="run", choices=["run", "gen-kat"])
    ap.add_argument("--label", default=time.strftime("%Y%m%d-%H%M%S"))
    ap.add_argument("--lx", type=int, choices=range(2, 6), help="run `clocks set lx N force` first (5 = stock 175 MHz)")
    a = ap.parse_args()
    return gen_kat() if a.action == "gen-kat" else run(a.label, a.lx)


if __name__ == "__main__":
    sys.exit(main())
