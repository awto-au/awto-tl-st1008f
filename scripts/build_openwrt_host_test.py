#!/usr/bin/env python3
"""Host-only checks for diagnostic OpenWrt images."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import build_openwrt as build


class DebugBuildTest(unittest.TestCase):
    def test_debug_checks_are_applied_to_both_kernel_targets(self):
        for kernel, version in (("6.18", "6.18"), ("mainline", "7.4")):
            with self.subTest(kernel=kernel), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                cfg = root / build.RT / f"rtl930x/config-{version}"
                cfg.parent.mkdir(parents=True)
                cfg.write_text("# CONFIG_DEBUG_LIST is not set\nCONFIG_SMP=y\n")
                with mock.patch.object(build, "TREE", root), mock.patch.object(build, "DEBUG73", True), \
                     mock.patch.object(build, "PV", "7.4"), mock.patch.object(build, "reset_overlay"), \
                     mock.patch.object(build, "overlay_618"), mock.patch.object(build, "overlay_73"), \
                     mock.patch.object(build, "log"):
                    build.overlay(kernel, False, [])
                self.assertIn("CONFIG_DEBUG_LIST=y", cfg.read_text())
                self.assertIn("CONFIG_DEBUG_OBJECTS=y", cfg.read_text())
                self.assertNotIn("# CONFIG_DEBUG_LIST is not set", cfg.read_text())
                self.assertIn("CONFIG_SMP=y", cfg.read_text())

    def test_debug_and_clean_are_refused_before_build_changes(self):
        with mock.patch.object(sys, "argv", ["build_openwrt.py", "--debug", "--clean"]), \
             mock.patch.object(build, "clone", side_effect=AssertionError("build started")), \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            with self.assertRaises(SystemExit) as exc:
                build.main()
        self.assertEqual(exc.exception.code, 2)
        self.assertIn("--debug and --clean are incompatible", stderr.getvalue())

    def test_debug_outputs_are_verified_and_do_not_replace_normal_images(self):
        for missing_check in (False, True):
            with self.subTest(missing_check=missing_check), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                tree, tftp = root / "tree", root / "tftp"
                output = tree / build.OUT_DIR
                output.mkdir(parents=True)
                (output / build.OUT_INITRAMFS).write_bytes(b"debug-image")
                kernel = tree / "build_dir/target-mips/linux-realtek_rtl930x/linux-6.18.60"
                kernel.mkdir(parents=True)
                config = build.DEBUG_CFG + build.DEBUG_OWRT_CFG.replace("CONFIG_KERNEL_", "CONFIG_")
                config += "CONFIG_LOCKDEP=y\nCONFIG_STACKPROTECTOR_STRONG=y\n"
                if missing_check:
                    config = config.replace("CONFIG_SLUB_DEBUG_ON=y\n", "")
                (kernel / ".config").write_text(config)
                (kernel.parent / "vmlinux.debug").write_bytes(b"unstripped-kernel")
                (kernel.parent / "vmlinux-initramfs.debug").write_bytes(b"unstripped-ram-kernel")
                (tree / ".config").write_text("openwrt-config\n")
                old_kernel = kernel.with_name("linux-7.4-rc1")
                old_kernel.mkdir()
                (old_kernel / ".config").write_text("old-build\n")
                tftp.mkdir()
                normal = tftp / "openwrt-ours-6.18-initramfs.bin"
                normal.write_bytes(b"known-good")
                with mock.patch.object(build, "ROOT", root), mock.patch.object(build, "TREE", tree), \
                     mock.patch.object(build, "TFTP", tftp), mock.patch.object(build, "DEBUG73", True), \
                     mock.patch.object(build, "FLASH73", False), mock.patch.object(build, "TAG", ""), \
                     mock.patch.object(build, "log") as log, \
                     mock.patch.object(build.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                    rc = build.outputs("6.18")
                self.assertEqual(normal.read_bytes(), b"known-good")
                debug = tftp / "openwrt-ours-6.18-debug-initramfs.bin"
                if missing_check:
                    self.assertEqual(rc, 1)
                    self.assertFalse(debug.exists())
                    self.assertIn("CONFIG_SLUB_DEBUG_ON=y", str(log.call_args_list))
                else:
                    self.assertEqual(rc, 0)
                    self.assertEqual(debug.read_bytes(), b"debug-image")
                    saved = root / "debug/openwrt-ours-6.18-debug"
                    self.assertEqual((saved / "vmlinux").read_bytes(), b"unstripped-kernel")
                    self.assertEqual((saved / "vmlinux-initramfs").read_bytes(), b"unstripped-ram-kernel")
                    self.assertEqual((saved / "kernel.config").read_text(), config)


if __name__ == "__main__":
    unittest.main()
