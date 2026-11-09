#!/usr/bin/env python3
"""Host-only checks for debug_soak classification."""

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import debug_soak


class DebugSoakTest(unittest.TestCase):
    def test_only_stp_guard_failure_is_classified_as_guard_power_cut(self):
        self.assertTrue(debug_soak.stp_guard_power_cut(
            "FAIL: bridge STP not enabled in 90 s: lan* down + relay off (#19)"))
        self.assertFalse(debug_soak.stp_guard_power_cut(
            "software reboot timed out; relay off: power cycle fallback"))
        self.assertFalse(debug_soak.stp_guard_power_cut("boot_log_check exit 2"))

    def test_reset_requires_a_ram_boot_before_the_linux_banner(self):
        earlier = b"Linux version flash\nU-Boot 2011.12\n"
        ram = b"[TX 12:00:00] 'bootm 0x84f00000\\r'\nLinux version ram\n"
        self.assertIsNone(debug_soak.reset_in(earlier + ram))
        self.assertIsNotNone(debug_soak.reset_in(earlier + ram + b"U-Boot 2011.12\n"))
        failed_ram = b"[TX 12:00:00] 'bootm 0x84f00000\\r'\nU-Boot 2011.12\nLinux version flash\n"
        self.assertIsNone(debug_soak.linux_after_bootm(failed_ram))

    def test_failed_ram_boot_is_not_mistaken_for_a_held_flash_boot(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            serial = root / "serial.log"
            serial.write_bytes(b"")
            args = SimpleNamespace(image="openwrt-ours-6.18-debug", bootargs="", verbose_console=False,
                                   procd_watch=False, hold=120)

            def ramload(*_args, stdout, **_kwargs):
                serial.write_bytes(b"Linux version flash\n")
                stdout.write("TIMEOUT waiting for rtk network on\n")
                return SimpleNamespace(returncode=1)

            with mock.patch.object(debug_soak, "SER", serial), \
                 mock.patch.object(debug_soak.subprocess, "run", side_effect=ramload), \
                 mock.patch.object(debug_soak, "ssh_uptime") as uptime:
                result = debug_soak.one_run(args, 1, root)
            self.assertEqual(result["result"], "SETUP-FAIL (RAM Linux not observed)")
            uptime.assert_not_called()

    def test_held_run_records_watchdog_and_log_capture_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            serial = root / "serial.log"
            serial.write_bytes(b"")
            args = SimpleNamespace(image="openwrt-ours-6.18-debug", bootargs="", verbose_console=False,
                                   procd_watch=False, hold=120)

            def run(cmd, **kwargs):
                if "ramload" in cmd:
                    serial.write_bytes(b"[TX 12:00:00] 'bootm 0x84f00000\\r'\nLinux version ram\n")
                    return SimpleNamespace(returncode=0)
                if cmd[0] == "ssh":
                    return SimpleNamespace(returncode=0, stdout="watchdog* \n", stderr="")
                return SimpleNamespace(returncode=1)

            with mock.patch.object(debug_soak, "SER", serial), \
                 mock.patch.object(debug_soak.subprocess, "run", side_effect=run), \
                 mock.patch.object(debug_soak, "ssh_uptime", return_value=150):
                result = debug_soak.one_run(args, 1, root)
            self.assertEqual(result["result"], "HELD")
            self.assertEqual(result["watchdogs_error"], "watchdog query returned no devices")
            self.assertEqual(result["switch_logs_rc"], 1)

    def test_exit_status_reports_failed_checks_and_incomplete_runs(self):
        cases = [
            ("HELD", 0, 0, "", 0),
            ("HELD", 2, 0, "", 1),
            ("HELD", 0, 1, "", 1),
            ("HELD", 0, 0, "watchdog query timed out", 1),
            ("NO-SSH", 0, 0, "", 1),
            ("SETUP-FAIL", 1, 0, "", 1),
            ("RESET", 0, 0, "", 3),
        ]
        for result, ramload_rc, logs_rc, watchdogs_error, expected in cases:
            with self.subTest(result=result, ramload_rc=ramload_rc, logs_rc=logs_rc,
                              watchdogs_error=watchdogs_error), tempfile.TemporaryDirectory() as tmp:
                run = {"run": 1, "result": result, "ramload_rc": ramload_rc, "switch_logs_rc": logs_rc,
                       "setup_error": "", "watchdogs_error": watchdogs_error, "blackbox_at_boot": ""}
                with mock.patch.object(debug_soak, "ROOT", Path(tmp)), \
                     mock.patch.object(debug_soak, "one_run", return_value=run), \
                     mock.patch.object(sys, "argv", ["debug_soak.py", "--runs", "1"]), \
                     contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(debug_soak.main(), expected)

    def test_nonpositive_runs_and_hold_are_rejected(self):
        for option in ("--runs", "--hold"):
            with self.subTest(option=option), \
                 mock.patch.object(sys, "argv", ["debug_soak.py", option, "0"]), \
                 mock.patch.object(debug_soak, "one_run") as one_run, \
                 contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as exc:
                    debug_soak.main()
                self.assertEqual(exc.exception.code, 2)
                one_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
