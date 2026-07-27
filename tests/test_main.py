import unittest
from argparse import Namespace
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hvv_display.config import load_config
from hvv_display.geofox import HAMBURG_TZ, GeofoxError
from hvv_display.main import MAX_REFRESH_BACKOFF_SECONDS, refresh_delay, run
from hvv_display.models import Departure


class MainTest(unittest.TestCase):
    def test_normal_refresh_interval_is_used_after_success(self) -> None:
        self.assertEqual(refresh_delay(15, 0), 15)

    def test_failures_use_bounded_exponential_backoff(self) -> None:
        self.assertEqual(refresh_delay(15, 1), 30)
        self.assertEqual(refresh_delay(15, 2), 60)
        self.assertEqual(refresh_delay(15, 3), 120)
        self.assertEqual(refresh_delay(15, 20), MAX_REFRESH_BACKOFF_SECONDS)

    def test_once_mode_renders_a_complete_successful_cycle(self) -> None:
        config = load_config("config.example.json")
        now = datetime.now(HAMBURG_TZ)

        class SuccessfulClient:
            def departure_list(self, *_args, **_kwargs):
                return [
                    Departure(
                        "21",
                        "U Niendorf Nord",
                        now + timedelta(minutes=3),
                        station_label="R",
                    )
                ]

        with TemporaryDirectory() as directory:
            output = Path(directory) / "board.png"
            arguments = Namespace(
                config="config.example.json",
                cache=str(Path(directory) / "stations.json"),
                once=True,
                output=str(output),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=SuccessfulClient()),
                patch(
                    "hvv_display.main.resolve_stations",
                    return_value=config.stations,
                ),
                patch("hvv_display.main.signal.signal"),
            ):
                result = run()

            self.assertEqual(result, 0)
            self.assertTrue(output.is_file())

    def test_once_mode_renders_stale_state_after_api_failure(self) -> None:
        config = load_config("config.example.json")

        class FailingClient:
            def departure_list(self, *_args, **_kwargs):
                raise GeofoxError("vorübergehend nicht erreichbar")

        with TemporaryDirectory() as directory:
            output = Path(directory) / "board.png"
            arguments = Namespace(
                config="config.example.json",
                cache=str(Path(directory) / "stations.json"),
                once=True,
                output=str(output),
            )
            with (
                patch("hvv_display.main._arguments", return_value=arguments),
                patch("hvv_display.main.GeofoxClient", return_value=FailingClient()),
                patch(
                    "hvv_display.main.resolve_stations",
                    return_value=config.stations,
                ),
                patch("hvv_display.main.signal.signal"),
            ):
                result = run()

            self.assertEqual(result, 1)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
