"""Tests for the maintenance window fixture."""

from __future__ import annotations

import unittest

from maintenance_window.window import is_clock_string_in_window


class MaintenanceWindowTests(unittest.TestCase):
    def test_overnight_window_includes_after_midnight_times(self) -> None:
        self.assertTrue(
            is_clock_string_in_window("00:30", "23:00", "02:00")
        )

    def test_overnight_window_includes_late_evening_times(self) -> None:
        self.assertTrue(
            is_clock_string_in_window("23:15", "23:00", "02:00")
        )

    def test_same_day_window_excludes_out_of_range_time(self) -> None:
        self.assertFalse(
            is_clock_string_in_window("18:30", "15:00", "18:00")
        )


if __name__ == "__main__":
    unittest.main()
