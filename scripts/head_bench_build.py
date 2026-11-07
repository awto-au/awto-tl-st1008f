#!/usr/bin/env python3
"""head_bench_build — plain bench kernel from the COMMITTED series (git HEAD), isolated from the working tree.

- Exports HEAD (git archive) to tmp/headbuild/repo; the working-tree patches/scripts are not read.
- OpenWrt files/patches come from tmp/zcsync/openwrt-old (target/linux/realtek of the commit HEAD is against).
- Kernel tree: own worktree tmp/headbuild/linux at the pinned tag; out dir tmp/headbuild/out.
- Result: tmp/tftp/mainline-7.4-rc1.bin (+ -std copy). Log tmp/logs/head_bench_build.log
    python3 scripts/head_bench_build.py [--jobs 8]
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "tmp/headbuild"  # --work overrides (parallel isolated builds)
LOG = ROOT / "tmp/logs/head_bench_build.log"
TAG = "v7.4-rc1"


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as fh:
        fh.write(line + "\n")


def sh(cmd, cwd=ROOT, **kw):
    r = subprocess.run(cmd, cwd=cwd, **kw)
    if r.returncode:
        sys.exit(f"FAIL rc {r.returncode}: {' '.join(map(str, cmd))}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--jobs", default="8")
    ap.add_argument("--old", default="tmp/zcsync/openwrt-old", help="dir holding target/linux/realtek of the base commit")
    ap.add_argument("--work", default=None, help="isolated work dir (default tmp/headbuild)")
    ap.add_argument("--extra-patch", action="append", default=[], help="working-tree patch added on top of the HEAD series")
    ap.add_argument("--image", default="mainline-7.4-rc1", help="tmp/tftp/<name>.bin (+ -std copy)")
    ap.add_argument("--skip", action="append", default=[], metavar="PREFIX", help="leave out series patches by name prefix (e.g. 300-43)")
    ap.add_argument("--apply-only", action="store_true", help="export + apply the series, no build")
    a = ap.parse_args()
    global WORK
    WORK = ROOT / a.work if a.work else WORK
    repo, lin = WORK / "repo", WORK / "linux"
    shutil.rmtree(repo, ignore_errors=True)
    repo.mkdir(parents=True)
    sh(f"git archive HEAD | tar -x -C {repo}", shell=True)
    (repo / "tmp").mkdir()
    (repo / "tmp/openwrt").symlink_to(ROOT / a.old)
    for d in ("busybox", "openwrt-24.10.7-ipk"):  # gitignored downloads the bench initramfs needs
        (repo / "sources" / d).symlink_to(ROOT / "sources" / d)
    (repo / "tmp/selftest").symlink_to(ROOT / "tmp/selftest")  # built by build_selftest.py (not in git)
    (repo / "tmp/linux-store").symlink_to((ROOT / "tmp/linux-store").resolve())
    if not lin.exists():
        sh(["git", "-C", str(ROOT / "tmp/linux-store"), "worktree", "add", "--detach", str(lin), TAG])
    for x in a.extra_patch:
        shutil.copy2(ROOT / x, repo / "openwrt/patches" / Path(x).name)
    sh(["git", "-C", str(lin), "checkout", "-f", TAG])
    sh(["git", "-C", str(lin), "clean", "-fdq"])
    log(f"HEAD {subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, text=True).strip()}; "
        f"patches: {sorted(p.name for p in (repo / 'openwrt/patches').glob('*.patch'))[-3:]} ...")
    drv = (
        "import sys; sys.path.insert(0, 'scripts'); import mainline_build_check as m; "
        "m.owrt_commit = lambda: m.OWRT_COMMIT; m.main()"
    )
    out = WORK / "out"
    r = subprocess.run([sys.executable, "-c", drv, "--tree", str(lin), "--out", str(out), "--bench", "--jobs", a.jobs]
                       + (["--apply-only"] if a.apply_only else []) + [x for p in a.skip for x in ("--skip", p)],
                       cwd=repo)
    log(f"mainline_build_check exit {r.returncode}")
    if r.returncode:
        return r.returncode
    if a.apply_only:
        return 0
    dst = ROOT / f"tmp/tftp/{a.image}.bin"
    r = subprocess.run([sys.executable, str(ROOT / "scripts/mainline_uimage.py"), "--vmlinux", str(out / "vmlinux"), "--dtb",
                        str(out / "arch/mips/boot/dts/realtek/tplink-tl-st1008f-v2.dtb"), "--out", str(dst)])
    log(f"mainline_uimage exit {r.returncode} -> {dst.relative_to(ROOT)}")
    if r.returncode == 0:
        shutil.copy2(dst, dst.with_name(f"{a.image}-std.bin"))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
