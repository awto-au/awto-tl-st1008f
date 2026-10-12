#!/usr/bin/env python3
"""build_openwrt — local OpenWrt buildroot (main, realtek/rtl930x, TL-ST1008F v2 only) + our kernel work (#73).

- Tree: tmp/openwrt-build (shallow clone of OpenWrt main; `--update` re-pulls). Separate from tmp/openwrt.
- Overlay, re-applied every run on a reset tree (idempotent; reset = git checkout + delete what we added):
  - `--kernel 6.18` (default, step 1): our patches backported to OpenWrt's 6.18 -> patches-6.18/
    (KERNEL_PATCHES: as-is from openwrt/patches/, or rebased copies from openwrt/backport-6.18/kernel/)
    + openwrt/backport-6.18/openwrt-tree.patch (DTS mode-switch + dirmap, kernel config) via `git apply`.
  - `--kernel 7.3` (step 2): OpenWrt "testing kernel" = our mainline 7.3 port (KERNEL_TESTING_PATCHVER):
    generic/kernel-7.3 (v7.3-rc6, tarball from tmp/linux-v7.3 git), realtek patches-7.3 + files-7.3
    (the set scripts/mainline_build_check.py builds, files/patches from tmp/openwrt @ OWRT_COMMIT),
    generic/pending-7.3 (700/701), rtl930x/config-7.3 (openwrt/kernel-7.3/), DTS = mainline/ DTS.
- Phases: disk check -> clone -> overlay -> .config -> download -> make; outputs ->
  tmp/tftp/openwrt-ours-initramfs.bin (7.3) / openwrt-ours-6.18-initramfs.bin (Realtek magic, stock bootm)
  + *-std.bin (std magic, mainline U-Boot bootm).
- Disk: aborts below MIN_FREE_GB before each phase and while make runs (log line + #73 comment).
- Everything at nice 19 / ionice idle. Log: tmp/logs/build_openwrt.log (make output: build_openwrt-make.log).

Usage: build_openwrt.py [--kernel 6.18|7.3] [--kernel-only] [--jobs N] [--update] [--no-overlay] [--default-boot]
                        [--prepare-only] [--regen-config] [--no-comment]
"""

import argparse
import collections
import gzip
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TREE = ROOT / "tmp/openwrt-build"
OURS = ROOT / "openwrt/patches"
BACKPORT = ROOT / "openwrt/backport-6.18"
K73 = ROOT / "openwrt/kernel-7.3"
TFTP = ROOT / "tmp/tftp"
LOG = ROOT / "tmp/logs/build_openwrt.log"
MAKE_LOG = ROOT / "tmp/logs/build_openwrt-make.log"
URL = "https://github.com/openwrt/openwrt.git"
RT = "target/linux/realtek"
GEN = "target/linux/generic"
DTS_FILE = f"{RT}/dts/rtl9303_tplink_tl-st1008f-v2.dts"
DEVICE = "tplink_tl-st1008f-v2"
OUT_DIR = "bin/targets/realtek/rtl930x"
OUT_INITRAMFS = f"openwrt-realtek-rtl930x-{DEVICE}-initramfs-kernel.bin"
MIN_FREE_GB = 4  # owner limit (#73)
NICE = ["nice", "-n", "19", "ionice", "-c3"]

# --- step 1: 6.18 backports. OpenWrt patch name -> source. Status per patch: docs/OPENWRT-BUILD.md.
KERNEL_PATCHES = {
    "300-04-realtek-rtl930x-enable-dram-prefetch.patch": OURS,
    "300-05-realtek-rtl930x-hpt-freq-from-pll.patch": OURS,
    "300-06-realtek-rtl930x-tplink-mode-switch.patch": OURS,
    "300-07-realtek-spi-dirmap-read.patch": BACKPORT / "kernel",
    "300-11-realtek-rteth-tx-ring32-bql-xmit-more.patch": OURS,  # 300-12 builds on it
    "300-12-realtek-rteth-930x-nic-path.patch": BACKPORT / "kernel",
    "300-13-mips-highmem-lowmem-fast-paths.patch": OURS,
}
TREE_PATCH = BACKPORT / "openwrt-tree.patch"

# --- step 2: 7.3 testing kernel = our mainline port, same inputs as scripts/mainline_build_check.py
LINUX73 = ROOT / "tmp/linux-v7.3"
TAG73, VER73 = "v7.3-rc6", "7.3-rc6"
sys.path.insert(0, str(ROOT / "scripts"))
# read-only inputs, shared with the 7.3 port build so both stay the same set
from mainline_build_check import (OWRT as OWRT_PIN, OWRT_COMMIT, OWRT_FILES, OWRT_FILES_DIR,  # noqa: E402
                                  OWRT_VERBATIM, SHARED_FILES)

PENDING73 = ["700", "701"]  # generic pending-6.18 nft flowtable patches; apply on 7.3 (MAINLINE-PORT §8)
# generic hack-6.18 patches OpenWrt packages need on 7.3 (all apply as-is; status of the rest: docs/OPENWRT-BUILD.md)
HACK73 = ["910", "911", "940"]  # uevent + broadcast_uevent (gpio-button-hotplug); 940: non-empty modules.builtin (kmod packaging)
CONFIG73 = K73 / "config-7.3"
UP73 = False  # --up
# Port symbols config-7.3 must keep (drivers the 7.3 port boots with; mainline/st1008f-v2.config)
PORT73 = """CONFIG_HIGHMEM=y
CONFIG_PREEMPT_VOLUNTARY=y
# CONFIG_PREEMPT is not set
CONFIG_SMP=y
CONFIG_MIPS_MT_SMP=y
CONFIG_NR_CPUS=2
CONFIG_MIPS_RAW_APPENDED_DTB=y
CONFIG_GPIO_REALTEK_OTTO=y
CONFIG_PINCTRL_SINGLE=y
CONFIG_GPIO_PCA953X=y
CONFIG_I2C_RTL9300=y
CONFIG_I2C_GPIO=y
CONFIG_MFD_SYSCON=y
CONFIG_MIPS_PLATFORM_DEVICES=y
CONFIG_TPLINK_ST1008F_MODE_SWITCH=y
CONFIG_REALTEK_OTTO_WDT=y
CONFIG_SPI_MEM=y
CONFIG_MTD_SPI_NOR=y
CONFIG_MTD_OF_PARTS=y
CONFIG_NVMEM_LAYOUTS=y
CONFIG_NVMEM_LAYOUT_U_BOOT_ENV=y
CONFIG_NET_RTL838X=y
CONFIG_NET_DSA=y
CONFIG_NET_DSA_RTL83XX=y
CONFIG_NET_DSA_TAG_RTL_OTTO=y
CONFIG_REALTEK_OTTO_TABLE=y
CONFIG_PCS_RTL_OTTO=y
CONFIG_FWNODE_PCS=y
CONFIG_MDIO_REALTEK_OTTO=y
CONFIG_MDIO_REALTEK_OTTO_SERDES=y
# CONFIG_MDIO_REALTEK_RTL9300 is not set
CONFIG_PHYLINK=y
CONFIG_SFP=y
CONFIG_I2C_SMBUS=y
CONFIG_MDIO_SMBUS=y
CONFIG_THERMAL_OF=y
CONFIG_REALTEK_THERMAL=y
CONFIG_MIPS_CMDLINE_DTB_EXTEND=y
# CONFIG_MIPS_CMDLINE_FROM_DTB is not set
"""  # DTB_EXTEND: U-Boot bootargs (st1008f.mode, #73) appended to DT bootargs

SEED = f"""CONFIG_TARGET_realtek=y
CONFIG_TARGET_realtek_rtl930x=y
CONFIG_TARGET_realtek_rtl930x_DEVICE_{DEVICE}=y
CONFIG_TARGET_ROOTFS_INITRAMFS=y
CONFIG_AUTOREMOVE=y
CONFIG_PACKAGE_ip-full=y
CONFIG_PACKAGE_ip-bridge=y
CONFIG_PACKAGE_tcpdump-mini=y
CONFIG_PACKAGE_kmod-pktgen=y
"""  # + nat-bench switch-side tools (docs/NAT-OPS.md): a RAM boot cannot apk-add matching kmods

# Timeouts. Basis: this host (30 threads), -j8, nice 19; measured values in docs/OPENWRT-BUILD.md.
# Each = measured worst case x1.25 where measured, else the stated estimate. Expiry kills make, logs elapsed.
T_DEFCONFIG = 60       # defconfig incl. package-metadata scan: 9 s first run, 1 s after; ~1 min names a hang
T_DOWNLOAD = 600       # ~0.43 GB dl/ (first run); 600 s = 0.7 MB/s floor, names a stuck mirror
T_WORLD = 1800         # first full build (tools 7 + toolchain 8 + packages/kernel/images ~8 min) ~1400 s x1.25
T_KERNEL = 180         # --kernel-only 6.18: 132 s x1.25 (2026-10-12)
T_GIT = 300            # shallow clone/fetch of OpenWrt main: ~10 s; 300 s names a stuck remote
DISK_POLL_S = 30       # free-space check while make runs: >4 GB cannot go in 30 s at -j8


def log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%dT%H:%M:%S%z')}] {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def free_gb() -> float:
    s = os.statvfs(ROOT)
    return s.f_bavail * s.f_frsize / 1e9


def disk_abort(phase: str, gb: float, comment: bool) -> None:
    msg = f"build_openwrt: aborted during/before `{phase}`: {gb:.1f} GB free < {MIN_FREE_GB} GB limit"
    log("ABORT: " + msg)
    if comment:
        subprocess.run(["gh", "issue", "comment", "73", "-R", "awto-au/awto-tl-st1008f", "-b", msg],
                       timeout=30, check=False)  # one API call; 30 s names a hung gh


def disk_check(phase: str, comment: bool) -> None:
    gb = free_gb()
    log(f"disk: {gb:.1f} GB free before {phase}")
    if gb < MIN_FREE_GB:
        disk_abort(phase, gb, comment)
        sys.exit(3)


def run(cmd: list, timeout: float, cwd: Path = TREE, comment: bool = True) -> int:
    """Run under nice/ionice; output -> MAKE_LOG (+ tail into LOG on failure). 124 = timeout, 3 = disk."""
    cmd = NICE + [str(c) for c in cmd]
    log("run: " + " ".join(cmd))
    t0 = time.time()
    tail = collections.deque(maxlen=60)
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                         errors="replace", start_new_session=True)
    why = []

    def expire():
        why.append("timeout")
        os.killpg(p.pid, 9)

    def disk_watch():
        while p.poll() is None:
            if (gb := free_gb()) < MIN_FREE_GB:
                why.append("disk")
                os.killpg(p.pid, 9)
                disk_abort(" ".join(cmd[5:])[:80], gb, comment)
                return
            time.sleep(DISK_POLL_S)

    timer = threading.Timer(timeout, expire)
    timer.start()
    threading.Thread(target=disk_watch, daemon=True).start()
    with MAKE_LOG.open("a") as fh:
        for line in p.stdout:
            fh.write(line)
            fh.flush()
            tail.append(line)
    rc = p.wait()
    timer.cancel()
    if why:
        log(f"KILLED ({why[0]}): limit {timeout} s, elapsed {time.time() - t0:.0f} s: {' '.join(cmd[5:])}")
        return 124 if why[0] == "timeout" else 3
    log(f"exit {rc} ({time.time() - t0:.0f} s)")
    if rc:
        for line in tail:
            log("  | " + line.rstrip("\n"))
    return rc


def du_gb(p: Path) -> float:
    r = subprocess.run(["du", "-sb", str(p)], capture_output=True, text=True, timeout=300)  # ~1 M files
    return int(r.stdout.split()[0]) / 1e9 if r.returncode == 0 else -1


def git(*args, cwd=TREE, timeout=60) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
                          timeout=timeout).stdout.strip()


def clone(update: bool) -> None:
    if not (TREE / ".git").exists():
        if run(["git", "clone", "--depth", "1", URL, TREE], T_GIT, cwd=ROOT):
            sys.exit("clone failed")
    elif update:
        reset_overlay()
        if run(["git", "fetch", "--depth", "1", "origin", "main"], T_GIT) or \
                run(["git", "reset", "--hard", "FETCH_HEAD"], 60):
            sys.exit("update failed")
    log(f"OpenWrt main @ {git('log', '-1', '--format=%H %cI %s')}")


def reset_overlay() -> None:
    """Tracked target/linux back to git; untracked files we add there deleted (no other untracked content)."""
    git("checkout", "--", "target/linux", "include/image.mk")
    git("clean", "-fdq", "--", "target/linux")


def overlay_618() -> None:
    for name, src in KERNEL_PATCHES.items():
        shutil.copy2(src / name, TREE / RT / "patches-6.18" / name)
        log(f"overlay: {RT}/patches-6.18/{name} (from {src.relative_to(ROOT)})")
    r = subprocess.run(["git", "apply", "--whitespace=nowarn", str(TREE_PATCH)], cwd=TREE,
                       capture_output=True, text=True, timeout=30)
    if r.returncode:
        log(r.stderr)
        sys.exit(f"{TREE_PATCH.relative_to(ROOT)} does not apply to this OpenWrt main")
    log(f"overlay: {TREE_PATCH.relative_to(ROOT)} applied")


def tarball_73() -> None:
    """dl/linux-7.3-rc6.tar.gz from the local v7.3-rc6 tag (OpenWrt would fetch git.kernel.org); hash skip."""
    dst = TREE / f"dl/linux-{VER73}.tar.gz"
    if dst.exists():
        return
    dst.parent.mkdir(exist_ok=True)
    tmp = dst.with_suffix(".part")
    with tmp.open("wb") as fh:
        p = subprocess.Popen(["git", "archive", f"--prefix=linux-{VER73}/", "--format=tar", TAG73],
                             cwd=LINUX73, stdout=subprocess.PIPE)
        with gzip.GzipFile(fileobj=fh, mode="wb", compresslevel=6, mtime=0) as gz:
            shutil.copyfileobj(p.stdout, gz, 1 << 20)
        if p.wait(timeout=600):  # ~1.5 GB tar stream; gzip -6 at ~100 MB/s
            sys.exit("git archive of v7.3-rc6 failed")
    tmp.rename(dst)
    log(f"overlay: {dst.relative_to(TREE)} {dst.stat().st_size} B from {LINUX73.relative_to(ROOT)} {TAG73}")


def overlay_73() -> None:
    pin = git("rev-parse", "HEAD", cwd=OWRT_PIN)
    if pin != OWRT_COMMIT:
        sys.exit(f"tmp/openwrt is at {pin}; the 7.3 port's files/patches are against {OWRT_COMMIT}")
    (TREE / GEN / "kernel-7.3").write_text(
        f"LINUX_VERSION-7.3 = -rc6\nLINUX_KERNEL_HASH-{VER73} = skip\n")
    mk = TREE / RT / "Makefile"
    mk.write_text(mk.read_text().replace("KERNEL_PATCHVER:=6.18\n",
                                         "KERNEL_PATCHVER:=6.18\nKERNEL_TESTING_PATCHVER:=7.3\n"))
    pdir = TREE / RT / "patches-7.3"
    pdir.mkdir()
    for n in OWRT_VERBATIM:
        shutil.copy2(next((OWRT_PIN / "patches-6.18").glob(f"{n}-*.patch")), pdir)
    for p in sorted(OURS.glob("*.patch")):
        shutil.copy2(p, pdir)
    fdir = TREE / RT / "files-7.3"
    for rel in OWRT_FILES:
        src, dst = OWRT_FILES_DIR / rel, fdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
    for rel, src in SHARED_FILES.items():  # shared with U-Boot (#83); 300-20 includes it
        shutil.copy2(src, fdir / rel)
    for kind, names in (("pending", PENDING73), ("hack", HACK73)):
        gdir = TREE / GEN / f"{kind}-7.3"
        gdir.mkdir()
        for n in names:
            shutil.copy2(next((TREE / GEN / f"{kind}-6.18").glob(f"{n}-*.patch")), gdir)
    if CONFIG73.exists():
        cfg = CONFIG73.read_text()
        if UP73:  # one VPE, as `./dev.py build-kernel --up` (the 7.3 runs tested on the board)
            cfg = override(cfg, (ROOT / "mainline/st1008f-v2-up.config").read_text())
        (TREE / RT / "rtl930x/config-7.3").write_text(cfg)
        if missing := [ln for ln in PORT73.splitlines() if ln.startswith("CONFIG_") and ln not in CONFIG73.read_text().splitlines()]:
            log(f"WARN: config-7.3 lacks PORT73 lines {missing}: run with --regen-config")
    # 7.3 dtc dropped the graph_child_address check: `-Wno-graph_child_address` is a FATAL ERROR there
    im = TREE / "include/image.mk"
    im.write_text(im.read_text().replace("  -Wno-graph_child_address \\\n", ""))
    # mainline DTS: 1-cell interrupts + mainline rtl930x.dtsi (OpenWrt's dtsi in the same dir would shadow it)
    dts = (ROOT / "mainline/tplink-tl-st1008f-v2.dts").read_text()
    (TREE / DTS_FILE).write_text(dts.replace('#include "rtl930x.dtsi"', '#include "realtek/rtl930x.dtsi"'))
    tarball_73()
    log(f"overlay: 7.3 testing kernel: {len(list(pdir.iterdir()))} patches, files-7.3 ({len(OWRT_FILES)} paths), "
        f"pending-7.3 {PENDING73}, hack-7.3 {HACK73}, config-7.3 {'from ' + str(CONFIG73.relative_to(ROOT)) if CONFIG73.exists() else 'MISSING'}")


def override(cfg: str, frag: str) -> str:
    """cfg with every symbol set in frag replaced (or added) by frag's line."""
    sym = re.compile(r"^(?:# )?(CONFIG_\w+)[= ]")
    new = {m[1]: ln for ln in frag.splitlines() if (m := sym.match(ln.strip()))}
    out = [ln for ln in cfg.splitlines() if not ((m := sym.match(ln)) and m[1] in new)]
    return "\n".join(out + list(new.values())) + "\n"


def overlay(kernel: str, none: bool) -> None:
    reset_overlay()
    if none:
        log("overlay: none (--no-overlay): stock OpenWrt main")
        return
    overlay_73() if kernel == "7.3" else overlay_618()


DEFAULT_BOOT = ROOT / "openwrt/default-boot"


def default_boot_files(on: bool) -> str:
    """--default-boot: openwrt/default-boot/files -> buildroot files/ (image overlay) + diffconfig lines.
    Without it the buildroot files/ is removed: images never carry a stale overlay."""
    dst = TREE / "files"
    shutil.rmtree(dst, ignore_errors=True)
    if not on:
        return ""
    shutil.copytree(DEFAULT_BOOT / "files", dst, symlinks=True)
    log(f"default-boot: files/ ({sum(1 for _ in dst.rglob('*'))} paths) + diffconfig")
    return "".join(ln + "\n" for ln in (DEFAULT_BOOT / "diffconfig").read_text().splitlines()
                   if ln.startswith("CONFIG_"))


def config(kernel: str, dboot: str = "") -> int:
    # 7.3: PREEMPT_NONE needs ARCH_NO_PREEMPT; OpenWrt's default KERNEL_PREEMPT_NONE would leave full
    # PREEMPT. Voluntary = the model the 7.3 port boots with (mainline/st1008f-v2.config).
    extra = "CONFIG_TESTING_KERNEL=y\nCONFIG_KERNEL_PREEMPT_VOLUNTARY=y\n" if kernel == "7.3" else ""
    extra += dboot
    (TREE / ".config").write_text(SEED + extra)
    rc = run(["make", "defconfig"], T_DEFCONFIG)
    if rc:
        return rc
    cfg = (TREE / ".config").read_text()
    want = [f"CONFIG_TARGET_realtek_rtl930x_DEVICE_{DEVICE}=y"] + extra.split()
    if miss := [w for w in want if w not in cfg]:
        log(f"FAIL: defconfig dropped {miss}")
        return 1
    return 0


def kernel_dir() -> Path:
    dirs = sorted(d for d in (TREE / "build_dir").glob("target-*/linux-realtek_rtl930x/linux-7.3*") if d.is_dir())
    if not dirs:
        sys.exit("no prepared 7.3 kernel tree; run with --prepare-only first")
    return dirs[-1]


def regen_config_73(jobs: str) -> int:
    """config-7.3 = OpenWrt generic+rtl930x config-6.18 + PORT73, olddefconfig'd in the patched 7.3 tree."""
    ldir = kernel_dir()
    merged = subprocess.run([str(TREE / "scripts/kconfig.pl"), "+", str(TREE / GEN / "config-6.18"),
                             str(TREE / RT / "rtl930x/config-6.18")], capture_output=True, text=True,
                            check=True, timeout=30).stdout  # local text merge, <1 s
    out = TREE / "tmp/config-7.3-regen"
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    (out / ".config").write_text(merged + PORT73)
    cc = sorted((TREE / "staging_dir").glob("toolchain-*/bin/*-openwrt-linux-musl-gcc"))
    cross = str(cc[-1])[:-3] if cc else ""
    # in-tree (OpenWrt builds there, O= is refused); KCONFIG_CONFIG keeps the tree's own .config untouched
    rc = run(["env", f"STAGING_DIR={TREE / 'staging_dir'}", "make", "-C", ldir, "ARCH=mips",
              f"CROSS_COMPILE={cross}", f"KCONFIG_CONFIG={out / '.config'}", "olddefconfig"], 60)  # ~5 s
    if rc:
        return rc
    got = dict(re.findall(r"^(CONFIG_\w+)=(.*)$", (out / ".config").read_text(), re.M))
    bad = [ln for ln in PORT73.splitlines() if (m := re.match(r"(CONFIG_\w+)=(.*)", ln)) and got.get(m[1]) != m[2]]
    if bad:
        log(f"FAIL: port symbols dropped by olddefconfig: {bad}")
        return 1
    keep = [ln for ln in (out / ".config").read_text().splitlines()
            if ln.startswith(("CONFIG_", "# CONFIG_")) and not re.match(
                r"#? ?CONFIG_(CC_|GCC_|CLANG_|LD_|AS_|RUSTC_|PAHOLE_|TOOLS_SUPPORT|INITRAMFS_|LLD_)", ln)]
    # symbols olddefconfig dropped for unmet deps that kmod overrides enable later (NF_TABLES=m ->
    # NF_TABLES_IPV4=y): keep OpenWrt's 6.18 line, as OpenWrt's raw config files do
    sym = re.compile(r"^(?:# )?(CONFIG_\w+)[= ]")
    have = {m[1] for ln in keep if (m := sym.match(ln))}
    # not for choice members: 7.3 PREEMPT_NONE needs ARCH_NO_PREEMPT; its 6.18 "=y" is invalid there
    keep += [ln for ln in merged.splitlines()
             if (m := sym.match(ln)) and m[1] not in have and not m[1].startswith("CONFIG_PREEMPT")]
    CONFIG73.parent.mkdir(parents=True, exist_ok=True)
    CONFIG73.write_text("\n".join(sorted(set(keep), key=lambda s: s.lstrip("# "))) + "\n")
    shutil.copy2(CONFIG73, TREE / RT / "rtl930x/config-7.3")
    log(f"config-7.3: {len(keep)} lines -> {CONFIG73.relative_to(ROOT)}")
    return 0


def prune() -> None:
    """Drop tools/toolchain build dirs once installed: their stamps live in staging_dir (~5.5 GB, #73 disk)."""
    for bdir, stamp in [("host", "staging_dir/host/stamp/.tools_compile_*"),
                        ("toolchain-*", "staging_dir/toolchain-*/stamp/.gcc_final_installed")]:
        if not list(TREE.glob(stamp)):
            continue
        for d in (TREE / "build_dir").glob(bdir):
            shutil.rmtree(d, ignore_errors=True)
            log(f"pruned build_dir/{d.name}")


def outputs(kernel: str) -> int:
    init = TREE / OUT_DIR / OUT_INITRAMFS
    if not init.exists():
        log(f"FAIL: no {init.relative_to(TREE)}")
        return 1
    TFTP.mkdir(parents=True, exist_ok=True)
    # openwrt-ours = 7.3 (default-boot RAM test, docs/DEFAULT-BOOT.md); openwrt-ours-6.18 = step 1
    name = "openwrt-ours" + ("" if kernel == "7.3" else "-6.18")
    dst = TFTP / f"{name}-initramfs.bin"
    shutil.copy2(init, dst)
    rc = subprocess.run([sys.executable, str(ROOT / "scripts/uimage_std_magic.py"), str(dst),
                         str(TFTP / f"{name}-initramfs-std.bin")], timeout=10).returncode  # <1 s
    for f in sorted((TREE / OUT_DIR).glob(f"*{DEVICE}*")):
        log(f"output: {f.name} {f.stat().st_size} B")
    log(f"tftp: {dst.name} (Realtek magic) + {name}-initramfs-std.bin (std magic)")
    return rc


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--kernel", choices=["6.18", "7.3"], default="6.18",
                    help="6.18 = OpenWrt kernel + backports (step 1); 7.3 = our mainline port (step 2)")
    ap.add_argument("--kernel-only", action="store_true",
                    help="re-patch + rebuild the kernel and images only (needs one full build first)")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--update", action="store_true", help="fetch the newest OpenWrt main first")
    ap.add_argument("--prepare-only", action="store_true",
                    help="stop after the kernel tree is unpacked + patched (patch rebase work)")
    ap.add_argument("--regen-config", action="store_true",
                    help="7.3: rebuild openwrt/kernel-7.3/config-7.3 in the prepared tree, then stop")
    ap.add_argument("--up", action="store_true", help="7.3: one VPE (merge mainline/st1008f-v2-up.config)")
    ap.add_argument("--no-overlay", action="store_true", help="stock OpenWrt main (baseline / rebase base)")
    ap.add_argument("--no-comment", action="store_true", help="no #73 comment on a disk abort")
    ap.add_argument("--default-boot", action="store_true",
                    help="image with openwrt/default-boot files/ + diffconfig (modes, DHCP + fallback, bootok)")
    a = ap.parse_args()
    comment = not a.no_comment
    global UP73
    UP73 = a.up
    t0 = time.time()
    log(f"=== build_openwrt kernel {a.kernel}{' UP' if a.up else ''} {'kernel-only' if a.kernel_only else 'full'} "
        f"-j{a.jobs} ===")
    disk_check("clone", comment)
    clone(a.update)
    overlay(a.kernel, a.no_overlay)
    disk_check("config", comment)
    if config(a.kernel, default_boot_files(a.default_boot)):
        return 1
    j = f"-j{a.jobs}"
    if a.regen_config:
        return regen_config_73(j)
    if a.prepare_only:
        disk_check("prepare", comment)
        rc = run(["make", j, "tools/install", "toolchain/install", "target/linux/clean",
                  "target/linux/prepare"], T_WORLD, comment=comment)
        prune()
        return rc
    if not a.kernel_only:
        disk_check("download", comment)
        if run(["make", j, "download"], T_DOWNLOAD, comment=comment):
            return 1
        disk_check("world", comment)
        rc = run(["make", j, "world"], T_WORLD, comment=comment)
        prune()
        if rc:
            return 1
    else:
        disk_check("kernel", comment)
        if run(["make", j, "target/linux/clean", "target/linux/compile", "target/linux/install"], T_KERNEL,
               comment=comment):
            return 1
    rc = outputs(a.kernel)
    log(f"done in {time.time() - t0:.0f} s; tree {du_gb(TREE):.1f} GB; {free_gb():.1f} GB free")
    return rc


if __name__ == "__main__":
    sys.exit(main())
