#!/usr/bin/env python3
"""Check the l3.c IPv6 host-table hash fold against the GPL SDK formulas (#59).

- SDK: `_dal_longan_l3_hostHash0_ret()` / `_dal_longan_l3_hostHash1_ret()` (dal_longan_l3.c),
  transcribed row by row below.
- l3.c (300-17): `otto_l3_930x_hash6()` = IPv4 hash of the low 32 bits XOR bit i at i % 9 for
  every bit i >= 32.
- Random + edge addresses, both algorithms. Host only, no hardware. Log: tmp/logs/l3_hash6_check.log
"""
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/l3_hash6_check.log"


def bx(v, lsb, n):
    """HASH_BIT_EXTRACT(v, lsb, n)"""
    return (v >> lsb) & ((1 << n) - 1)


def sdk_hash(o, alg):
    """o = 16 address octets, network order"""
    r = [0] * 16
    r[0] = bx(o[0], 6, 2)
    r[1] = bx(o[0], 0, 6) << 3 | bx(o[1], 5, 3)
    r[2] = bx(o[1], 0, 5) << 4 | bx(o[2], 4, 4)
    r[3] = bx(o[2], 0, 4) << 5 | bx(o[3], 3, 5)
    r[4] = bx(o[3], 0, 3) << 6 | bx(o[4], 2, 6)
    r[5] = bx(o[4], 0, 2) << 7 | bx(o[5], 1, 7)
    r[6] = bx(o[5], 0, 1) << 8 | bx(o[6], 0, 8)
    r[7] = bx(o[7], 0, 8) << 1 | bx(o[8], 7, 1)
    r[8] = bx(o[8], 0, 7) << 2 | bx(o[9], 6, 2)
    r[9] = bx(o[9], 0, 6) << 3 | bx(o[10], 5, 3)
    r[10] = bx(o[10], 0, 5) << 4 | bx(o[11], 4, 4)
    if alg == 0:
        r[11] = bx(o[11], 0, 4) << 5 | bx(o[12], 3, 5)
        r[12] = bx(o[12], 0, 3) << 6 | bx(o[13], 2, 6)
        r[13] = bx(o[13], 0, 2) << 7 | bx(o[14], 1, 7)
        r[14] = bx(o[14], 0, 1) << 8 | bx(o[15], 0, 8)
        h = 0
        for x in r[:15]:
            h ^= x
        return h
    r[11] = bx(o[11], 0, 4) << 5
    r[12] = bx(o[12], 3, 5)
    r[13] = bx(o[12], 0, 3) << 6 | bx(o[13], 2, 6)
    r[14] = bx(o[13], 0, 2) << 7 | bx(o[14], 1, 7)
    r[15] = bx(o[14], 0, 1) << 8 | bx(o[15], 0, 8)
    s = r[12] + r[13] + r[14]
    s1 = (s & 0x1FF) + ((s & (0x1FF << 9)) >> 9)
    pre = (s1 & 0x1FF) + ((s1 & (0x1FF << 9)) >> 9)
    h = 0
    for x in r[:12]:
        h ^= x
    return h ^ pre ^ r[15]


def l3c_hash4(ip, alg):
    """otto_l3_930x_hash4(ip, alg, false)"""
    rows = [bx(ip, 27, 5), bx(ip, 18, 9), bx(ip, 9, 9), bx(ip, 0, 9)]
    if not alg:
        return rows[0] ^ rows[1] ^ rows[2] ^ rows[3]
    s0 = rows[0] + rows[1] + rows[2]
    s1 = (s0 & 0x1FF) + ((s0 & (0x1FF << 9)) >> 9)
    ph = (s1 & 0x1FF) + ((s1 & (0x1FF << 9)) >> 9)
    return ph ^ rows[3]


def l3c_hash6(addr, alg):
    """otto_l3_930x_hash6()"""
    h = l3c_hash4(addr & 0xFFFFFFFF, alg)
    for w in range(3):
        v = (addr >> (32 * (3 - w))) & 0xFFFFFFFF
        base = 32 * (3 - w)
        for j in range(32):
            if v >> j & 1:
                h ^= 1 << ((base + j) % 9)
    return h


def main():
    LOG.parent.mkdir(parents=True, exist_ok=True)
    rnd = random.Random(59)
    addrs = [0, (1 << 128) - 1, 1, 1 << 127, 0x20010DB8000000000000000000000001]
    addrs += [1 << b for b in range(128)]
    addrs += [rnd.getrandbits(128) for _ in range(200000)]
    bad = 0
    for a in addrs:
        o = a.to_bytes(16, "big")
        for alg in (0, 1):
            # find_slot() masks to 9 bits, the SDK takes it modulo the 512-row height
            if (sdk_hash(o, alg) & 0x1FF) != (l3c_hash6(a, alg) & 0x1FF):
                bad += 1
                if bad < 10:
                    print(f"MISMATCH alg {alg} {a:032x}")
    msg = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {len(addrs)} addresses x 2 algorithms, {bad} mismatches"
    print(msg)
    with LOG.open("a") as f:
        f.write(msg + "\n")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
