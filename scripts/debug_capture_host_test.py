#!/usr/bin/env python3
"""Host-only checks for debug log capture."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import st1008_ramload as ramload
import switch_console
import switch_logs


class DebugCaptureTest(unittest.TestCase):
    def test_verbose_console_is_enabled_only_when_requested(self):
        for verbose in (False, True):
            with self.subTest(verbose=verbose):
                con = mock.Mock()
                def set_mgmt_ip(_con, _ip):
                    commands = [call.args[0] for call in con.run.call_args_list]
                    self.assertNotIn("dmesg -n 8", commands)  # kernel lines would garble the mgmt echo checks
                with mock.patch.object(ramload, "log"), \
                     mock.patch.object(ramload, "set_mgmt_ip", side_effect=set_mgmt_ip):
                    ramload.openwrt_stp(con, mgmt_ip="192.168.25.56", verbose_console=verbose)
                commands = [call.args[0] for call in con.run.call_args_list]
                self.assertEqual("dmesg -n 8" in commands, verbose)
                if verbose:
                    self.assertGreater(commands.index("dmesg -n 8"), commands.index("cat $B/stp_state"))

    def test_long_openwrt_line_is_refused_before_sending(self):
        con = ramload.Console.__new__(ramload.Console)
        con.send = con.send_checked = mock.Mock()
        with self.assertRaises(ValueError):
            con.run("x" * (ramload.OW_LINE_MAX + 1), ramload.OW_PROMPT, 1, "long")
        con.send.assert_not_called()

    def test_ow_script_sends_short_heredoc_lines(self):
        con = ramload.Console.__new__(ramload.Console)
        con.run = mock.Mock()
        con.ow_script("/tmp/pw", ramload.PROCD_WATCH, "procd watch")
        sent = [call.args[0] for call in con.run.call_args_list]
        self.assertEqual(sent[0], "cat >/tmp/pw <<'E'")
        self.assertEqual(sent[-1], "E")
        self.assertTrue(all(len(line) <= ramload.OW_LINE_MAX for line in sent))
        with self.assertRaises(ValueError):
            con.ow_script("/tmp/x", "y" * (ramload.OW_LINE_MAX + 1), "too long")

    def test_follow_saves_output_and_reports_disconnect(self):
        for disconnect in (False, True):
            with self.subTest(disconnect=disconnect), tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)

                def run(cmd, *, stdin, stdout, stderr, text, timeout):
                    stdout.write("st1008f-capture-ready\nsystem log line\n")
                    if disconnect:
                        stderr.write("connection lost\n")
                        return SimpleNamespace(returncode=255)
                    raise subprocess.TimeoutExpired(cmd, timeout)

                with mock.patch.object(switch_logs.subprocess, "run", side_effect=run), \
                     mock.patch.object(switch_logs, "log") as log:
                    rc = switch_logs.follow_logread("192.168.25.56", [], out, 3)
                self.assertEqual((out / "logread-follow.txt").read_text(),
                                 "st1008f-capture-ready\nsystem log line\n")
                self.assertEqual(rc, 1 if disconnect else 0)
                if disconnect:
                    self.assertIn("connection lost", str(log.call_args_list))

    def test_follow_requires_readiness_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with mock.patch.object(switch_logs.subprocess, "run",
                                   side_effect=subprocess.TimeoutExpired("ssh", 3)), \
                 mock.patch.object(switch_logs, "log") as log:
                self.assertEqual(switch_logs.follow_logread("192.168.25.56", [], out, 3), 1)
            self.assertIn("readiness marker", str(log.call_args_list))

    def test_failed_logs_only_snapshot_preserves_partial_output(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as tmp:
                result = SimpleNamespace(returncode=1, stdout="partial dmesg\n", stderr="logread failed\n")
                error = subprocess.TimeoutExpired("ssh", 20, output=b"partial dmesg\n", stderr=b"logread failed\n")
                with mock.patch.object(switch_logs, "OUT", Path(tmp)), \
                     mock.patch.object(switch_logs.time, "strftime", return_value="test"), \
                     mock.patch.object(switch_logs.subprocess, "run", return_value=result,
                                       side_effect=error if timeout else None) as run, \
                     mock.patch.object(switch_logs, "log"), \
                     mock.patch.object(sys, "argv", ["switch_logs", "--ip", "192.168.25.56", "--logs-only"]):
                    self.assertEqual(switch_logs.main(), 1)
                out = Path(tmp) / "192.168.25.56-test"
                self.assertEqual((out / "snapshot-partial.txt").read_text(), "partial dmesg\n")
                self.assertEqual((out / "snapshot.stderr").read_text(), "logread failed\n")
                self.assertEqual(run.call_args.args[0][-1], switch_logs.REMOTE_LOGS)

    def test_console_capture_waits_for_each_prompt(self):
        with tempfile.TemporaryDirectory() as tmp:
            con = mock.Mock()
            con.size.side_effect = [0, 10, 20]
            dmesg = "dmesg && echo __CAPTURE_DMESG_DONE__\r\nkernel line\r\n__CAPTURE_DMESG_DONE__\r\n"
            logread = ("logread && echo __CAPTURE_LOGREAD_DONE__\r\nsystem line\r\n"
                       "__CAPTURE_LOGREAD_DONE__\r\nroot@OpenWrt:~# ")
            reads = []

            def echo_since(mark):
                reads.append(mark)
                return (dmesg if reads.count(10) == 1 else dmesg + "root@OpenWrt:~# ") if mark == 10 else logread

            def send_checked(command):
                if command.startswith("logread"):
                    self.assertGreaterEqual(reads.count(10), 2)

            con.echo_since.side_effect = echo_since
            con.send_checked.side_effect = send_checked
            with mock.patch.object(ramload, "Console", return_value=con), \
                 mock.patch.object(switch_console, "LOG_OUT", Path(tmp)), \
                 mock.patch.object(switch_console.time, "strftime", return_value="test"), \
                 mock.patch.object(switch_console.time, "sleep"):
                self.assertEqual(switch_console.capture_logs(), 0)
            out = Path(tmp) / "console-test"
            self.assertEqual((out / "dmesg.txt").read_text(), "kernel line\n")
            self.assertEqual((out / "logread.txt").read_text(), "system line\n")
            con.send.assert_called_once_with("\x03", cr=False)
            con.run.assert_called_once_with("dmesg -n 8", ramload.OW_PROMPT, 3,
                                            "console loglevel 8", checked=True)


if __name__ == "__main__":
    unittest.main()
