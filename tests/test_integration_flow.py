import unittest
from datetime import datetime
from pathlib import Path

from hvv_display.config import load_config
from hvv_display.geofox import HAMBURG_TZ, GeofoxClient
from hvv_display.render import render_board

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


class IntegrationFlowTest(unittest.TestCase):
    def test_documented_response_flows_from_api_to_display(self) -> None:
        fixture = (ROOT / "tests/fixtures/departure_list.json").read_bytes()
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: FakeResponse(fixture),
        )
        config = load_config(ROOT / "config.example.json")
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)

        departures = client.departure_list(config.stations, now=now)
        image = render_board(
            departures,
            now=now,
            last_updated=now,
            max_rows=config.api.max_departures,
        )

        self.assertEqual(
            [departure.line for departure in departures],
            ["21", "186", "184", "384"],
        )
        self.assertEqual(
            [departure.station_label for departure in departures],
            ["R", "W", "W", "W"],
        )
        self.assertEqual(
            [departure.departure_time.strftime("%H:%M") for departure in departures],
            ["12:03", "12:05", "12:10", "12:12"],
        )
        self.assertTrue(departures[-1].cancelled)
        self.assertEqual(image.size, (320, 240))
        self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
