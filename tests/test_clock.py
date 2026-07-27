import subprocess
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from unittest.mock import Mock

from hvv_display.clock import in_night_shutdown, time_is_synchronized
from hvv_display.geofox import HAMBURG_TZ


class ClockTest(unittest.TestCase):
    def test_sync_marker_avoids_external_command(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "synchronized"
            marker.touch()
            run = Mock()
            self.assertTrue(time_is_synchronized(marker=marker, run=run))
            run.assert_not_called()

    def test_timedatectl_states_and_unknown_results(self) -> None:
        missing = Path("/definitely/missing/time-sync-marker")
        cases = (
            (subprocess.CompletedProcess([], 0, "yes\n", ""), True),
            (subprocess.CompletedProcess([], 0, "no\n", ""), False),
            (subprocess.CompletedProcess([], 0, "unexpected\n", ""), None),
            (subprocess.CompletedProcess([], 1, "", "failed"), None),
        )
        for result, expected in cases:
            with self.subTest(stdout=result.stdout, returncode=result.returncode):
                self.assertIs(
                    time_is_synchronized(
                        marker=missing,
                        run=Mock(return_value=result),
                    ),
                    expected,
                )

    def test_missing_timedatectl_is_unknown(self) -> None:
        self.assertIsNone(
            time_is_synchronized(
                marker=Path("/definitely/missing/time-sync-marker"),
                run=Mock(side_effect=FileNotFoundError),
            )
        )

    def test_night_window_handles_midnight_and_daytime_ranges(self) -> None:
        overnight_start = time(21, 0)
        overnight_end = time(6, 30)
        for hour, minute, expected in (
            (20, 59, False),
            (21, 0, True),
            (0, 0, True),
            (6, 29, True),
            (6, 30, False),
        ):
            with self.subTest(hour=hour, minute=minute):
                now = datetime(
                    2026,
                    7,
                    27,
                    hour,
                    minute,
                    tzinfo=HAMBURG_TZ,
                )
                self.assertEqual(
                    in_night_shutdown(now, overnight_start, overnight_end),
                    expected,
                )

        noon = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        self.assertTrue(in_night_shutdown(noon, time(9), time(17)))
        self.assertFalse(in_night_shutdown(noon, time(13), time(17)))


if __name__ == "__main__":
    unittest.main()
