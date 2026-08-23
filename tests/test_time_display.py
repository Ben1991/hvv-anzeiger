import unittest
from datetime import datetime, timedelta

from hvv_display.geofox import HAMBURG_TZ
from hvv_display.time_display import format_departure_time, minutes_until


class TimeDisplayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 7, 27, 18, 35, tzinfo=HAMBURG_TZ)

    def test_countdown_uses_effective_time_and_never_goes_negative(self) -> None:
        self.assertEqual(
            minutes_until(self.now + timedelta(seconds=61), self.now), 2
        )
        self.assertEqual(minutes_until(self.now - timedelta(seconds=1), self.now), 0)
        self.assertEqual(
            format_departure_time(
                self.now + timedelta(minutes=7), self.now, minute_unit="min"
            ),
            "7 min",
        )

    def test_all_countdown_units_and_zero_are_supported(self) -> None:
        departure = self.now + timedelta(seconds=1)
        self.assertEqual(
            format_departure_time(departure, self.now, minute_unit="min"), "1 min"
        )
        self.assertEqual(
            format_departure_time(departure, self.now, minute_unit="m"), "1 m"
        )
        self.assertEqual(
            format_departure_time(departure, self.now, minute_unit="none"), "1"
        )
        self.assertEqual(
            format_departure_time(self.now, self.now, minute_unit="none"), "0"
        )

    def test_departure_time_and_cancelled_variants_use_same_effective_time(
        self,
    ) -> None:
        departure = self.now + timedelta(minutes=7, seconds=30)
        self.assertEqual(
            format_departure_time(
                departure, self.now, time_mode="departure_time", minute_unit="m"
            ),
            "18:42",
        )
        self.assertEqual(
            format_departure_time(
                departure,
                self.now,
                time_mode="departure_time",
                cancelled=True,
            ),
            "AUS",
        )


if __name__ == "__main__":
    unittest.main()
