#!/usr/bin/env python3
"""Host-only checks for debug_soak classification."""

import unittest

import debug_soak


class DebugSoakTest(unittest.TestCase):
    def test_only_stp_guard_failure_is_classified_as_guard_power_cut(self):
        self.assertTrue(debug_soak.stp_guard_power_cut(
            "FAIL: bridge STP not enabled in 90 s: lan* down + relay off (#19)"))
        self.assertFalse(debug_soak.stp_guard_power_cut(
            "software reboot timed out; relay off: power cycle fallback"))
        self.assertFalse(debug_soak.stp_guard_power_cut("boot_log_check exit 2"))


if __name__ == "__main__":
    unittest.main()
