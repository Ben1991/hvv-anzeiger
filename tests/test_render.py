import unittest
from datetime import datetime, timedelta

from hvv_display.geofox import HAMBURG_TZ
from hvv_display.models import Departure
from hvv_display.render import RED, _status_text, render_board


class RenderTest(unittest.TestCase):
    def test_render_has_display_dimensions(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        image = render_board(
            [Departure("186", "S Othmarschen", now + timedelta(minutes=3))],
            now=now,
        )
        self.assertEqual(image.size, (320, 240))
        self.assertEqual(image.mode, "RGB")

    def test_stale_state_has_red_status_bar(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        image = render_board(
            [],
            now=now,
            last_updated=now - timedelta(minutes=2),
            stale=True,
            error_message="Geofox ist nicht erreichbar",
        )
        self.assertEqual(image.getpixel((0, 239)), (213, 43, 47))
        self.assertEqual(RED, "#d52b2f")

    def test_only_configured_number_of_rows_is_rendered(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        departures = [
            Departure("21", f"Ziel {index}", now + timedelta(minutes=index + 1))
            for index in range(6)
        ]
        limited = render_board(departures, now=now, max_rows=5)
        expected = render_board(departures[:5], now=now, max_rows=5)
        self.assertEqual(limited.tobytes(), expected.tobytes())

    def test_station_label_changes_the_rendered_row(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        without_label = render_board(
            [Departure("21", "U Niendorf Nord", now + timedelta(minutes=3))],
            now=now,
        )
        with_label = render_board(
            [
                Departure(
                    "21",
                    "U Niendorf Nord",
                    now + timedelta(minutes=3),
                    station_label="R",
                )
            ],
            now=now,
        )
        self.assertNotEqual(without_label.tobytes(), with_label.tobytes())

    def test_disconnected_wifi_has_visible_red_status_bar(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        connected = render_board(
            [Departure("21", "U Niendorf Nord", now + timedelta(minutes=3))],
            now=now,
            last_updated=now,
            wifi_is_connected=True,
        )
        disconnected = render_board(
            [Departure("21", "U Niendorf Nord", now + timedelta(minutes=3))],
            now=now,
            last_updated=now,
            wifi_is_connected=False,
        )
        self.assertNotEqual(connected.tobytes(), disconnected.tobytes())
        self.assertEqual(disconnected.getpixel((0, 239)), (213, 43, 47))
        self.assertEqual(
            _status_text(
                wifi_is_connected=False,
                stale=True,
                last_updated=now,
            ),
            "KEIN WLAN · STAND 12:00",
        )


if __name__ == "__main__":
    unittest.main()
