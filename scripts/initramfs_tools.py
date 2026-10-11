#!/usr/bin/env python3
"""NAT/switch test userspace for the mainline initramfs: nft, iperf3, ethtool, tc, ip (#16).

- Pinned OpenWrt 24.10.7 packages (mips_24kc = the 24.10 realtek/rtl930x arch, musl, dynamic),
  dependency closure resolved from the feed Packages indexes; sha256 from the index / sha256sums.
- No libc in the host cross toolchain (mips64-linux-gnu-gcc is kernel-only), so no source build.
- Missing .ipk -> `playwrong --pdf URL -o PATH` (any file through the shared browser).
- Store: sources/openwrt-24.10.7-ipk/ (gitignored; manifest in sources/README.md).
- staged_files() -> {path in initramfs: (bytes, mode)}; consumed by mainline_initramfs.py.
- Log: tmp/logs/initramfs_tools.log
"""
import gzip
import hashlib
import io
import subprocess
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "tmp/logs/initramfs_tools.log"
STORE = ROOT / "sources/openwrt-24.10.7-ipk"
BASE_URL = "https://downloads.openwrt.org/releases/24.10.7/"
PKGS = [
    ("targets/realtek/rtl930x/packages/libc_1.2.5-r4_mips_24kc.ipk", "fbb67eb9e3f9321cf842280ecd133d085b51ca2dcb36e0148e4114fc2bc480d7"),
    ("targets/realtek/rtl930x/packages/libgcc1_13.3.0-r4_mips_24kc.ipk", "e9217bf9b15c12b31b070d4632566afda4182fbbac6dad31664b3013f0dac6df"),
    ("targets/realtek/rtl930x/packages/libatomic1_13.3.0-r4_mips_24kc.ipk", "6f7d487d9a0cffaf0886a30e0720aa50fff8bbe1d2f1a0e8ac5e9f98f5629964"),
    ("packages/mips_24kc/base/libmnl0_1.0.5-r1_mips_24kc.ipk", "82767c6cc785ab50cc8491feeee03f114f7bd7bb9afcd6a09089d7d3f147c362"),
    ("packages/mips_24kc/base/libnftnl11_1.2.8-r1_mips_24kc.ipk", "98255d2e71018dd35296c511ad34264e69ce70bba34d4fc40b07ae3c052e1133"),
    ("packages/mips_24kc/base/nftables-nojson_1.1.1-r1_mips_24kc.ipk", "abf823217fb6971409300dcee9ef4cbe6402aadea9850eacfed3a30fabbcbe50"),
    ("packages/mips_24kc/base/zlib_1.3.1-r1_mips_24kc.ipk", "135ca4f7237db673b20ec0243da04d70007df56bb2a4148bd49c581088cb33ca"),
    ("packages/mips_24kc/base/libelf1_0.192-r1_mips_24kc.ipk", "9f2e414d11e5922f803ba23007b5b1d23604cccdb43e9d4a8e2fd2ce0d9a1453"),
    ("packages/mips_24kc/base/libbpf1_1.5.0-r1_mips_24kc.ipk", "59350e5bc2c4c438090800222b0af89f23e5f50ca2dedfd021ff64fcec5590e9"),
    ("packages/mips_24kc/base/libnl-tiny1_2025.03.19~c0df580a-r1_mips_24kc.ipk", "b181e711cac0cfce6cf7237c93622edd9b102c5578c6a49f10a2966329c530d9"),
    ("packages/mips_24kc/base/tc-tiny_6.11.0-r1_mips_24kc.ipk", "9fc8dc37df9269d54af3919739859b21116efe9ad6c2bb28057a893967a69476"),
    ("packages/mips_24kc/base/ip-full_6.11.0-r1_mips_24kc.ipk", "5faf0998ceb6f9b023a3fa676671c23a9f783b5ffbe1bd6cbf86106f75448565"),
    ("packages/mips_24kc/base/ethtool_6.11-r1_mips_24kc.ipk", "6b7835c164b7e43a0a2c9f44370f221f9c2aba9f5ded7bebf9d514c5a2cfedef"),
    ("packages/mips_24kc/packages/libiperf3_3.17.1-r4_mips_24kc.ipk", "1051a5629345ca45e29297e40583780fbae600db0a6637654069b5e6c6f9a46a"),
    ("packages/mips_24kc/packages/iperf3_3.17.1-r4_mips_24kc.ipk", "f46e8bd239a8cf11d32517032ac95d95fb48fb52d929fc53902074e003c761fd"),
]
SKIP = ("etc/", "lib/upgrade/", "usr/lib/opkg/")  # OpenWrt init/config glue: not used here


def log(msg: str) -> None:
    print(msg)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}\n")


def fetch(rel: str, sha: str) -> bytes:
    path = STORE / Path(rel).name
    if not path.exists():
        STORE.mkdir(parents=True, exist_ok=True)
        log(f"download {BASE_URL + rel}")
        r = subprocess.run(["playwrong", "--pdf", BASE_URL + rel, "-o", str(path)],
                           capture_output=True, text=True)
        if not path.exists():  # rc is 1 for any non-PDF; the sha256 below is the check
            raise SystemExit(f"playwrong download failed: {rel}\n{r.stdout[-500:]}{r.stderr[-500:]}")
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != sha:
        raise SystemExit(f"{path}: sha256 mismatch (bad download? delete it and re-run)")
    return data


def ipk_data(ipk: bytes) -> tarfile.TarFile:
    """OpenWrt 24.10 .ipk = tar.gz holding data.tar.gz."""
    outer = tarfile.open(fileobj=io.BytesIO(ipk), mode="r:gz")
    member = next(m for m in outer.getmembers() if m.name.lstrip("./") == "data.tar.gz")
    return tarfile.open(fileobj=io.BytesIO(gzip.decompress(outer.extractfile(member).read())))


def staged_files() -> dict[str, tuple[str, bytes | str, int]]:
    """path -> ("file", bytes, mode) | ("link", target, 0)."""
    out = {}
    for rel, sha in PKGS:
        tf = ipk_data(fetch(rel, sha))
        for m in tf.getmembers():
            name = m.name.lstrip("./")
            if not name or name.startswith(SKIP) or m.isdir():
                continue
            if m.issym():
                out[name] = ("link", m.linkname, 0)
            elif m.isfile():
                out[name] = ("file", tf.extractfile(m).read(), m.mode & 0o777)
    log(f"staged {len(out)} entries from {len(PKGS)} OpenWrt 24.10.7 packages")
    return out


if __name__ == "__main__":
    for k, v in sorted(staged_files().items()):
        print(f"{v[0]:4} {k}" + (f" -> {v[1]}" if v[0] == "link" else f" {len(v[1])} B"))
