import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from hvv_display.geofox import HAMBURG_TZ
from hvv_display.models import Departure
from hvv_display.render import (
    RED,
    _fit_text,
    _font,
    _status_text,
    board_state_key,
    get_line_style,
    line_style_css,
    render_board,
)


class RenderTest(unittest.TestCase):
    def test_render_has_display_dimensions(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        image = render_board(
            [Departure("186", "S Othmarschen", now + timedelta(minutes=3))],
            now=now,
        )
        self.assertEqual(image.size, (320, 240))
        self.assertEqual(image.mode, "RGB")

    def test_time_display_modes_change_the_rendered_departure_label(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        departure = Departure("21", "Ziel", now + timedelta(minutes=7))
        countdown = render_board([departure], now=now, minute_unit="min")
        short_unit = render_board([departure], now=now, minute_unit="m")
        no_unit = render_board([departure], now=now, minute_unit="none")
        clock = render_board([departure], now=now, time_mode="departure_time")
        self.assertNotEqual(countdown.tobytes(), short_unit.tobytes())
        self.assertNotEqual(short_unit.tobytes(), no_unit.tobytes())
        self.assertNotEqual(no_unit.tobytes(), clock.tobytes())

    def test_board_state_uses_the_configured_time_format(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        departure = Departure("21", "Ziel", now + timedelta(minutes=7))
        state = board_state_key(
            [departure],
            now=now,
            last_updated=now,
            stale=False,
            error_message=None,
            wifi_is_connected=True,
            max_rows=5,
            time_mode="departure_time",
        )
        self.assertIn("12:07", state[1][0])

    def test_line_styles_cover_hvv_modes_and_safe_fallback(self) -> None:
        expected = {
            ("5", "BUS"): ("bus", "pointed"),
            ("U2", None): ("u2", "rectangle"),
            ("U3", "UBAHN"): ("u3", "rectangle"),
            ("U4", None): ("u4", "rectangle"),
            ("S1", "SBAHN"): ("sbahn", "circle"),
            ("S2", None): ("s2", "circle"),
            ("S3", None): ("s3", "circle"),
            ("S5", None): ("s5", "circle"),
            ("S7", None): ("s7", "circle"),
            ("A1", None): ("akn", "circle"),
            ("RE1", None): ("regional", "rectangle"),
            ("RB81", "REGIONAL"): ("regional", "rectangle"),
            ("Fähre", "FERRY"): ("ferry", "pointed"),
            ("X10", None): ("xpress", "pointed"),
            ("N42", None): ("night", "pointed"),
            ("future-value", "unknown"): ("neutral", "rounded"),
            ("", None): ("neutral", "rounded"),
        }
        for input_values, style_values in expected.items():
            with self.subTest(input_values=input_values):
                style = get_line_style(*input_values)
                self.assertEqual((style.token, style.shape), style_values)

        self.assertEqual(get_line_style("5", "METROBUS").token, "bus")
        self.assertEqual(get_line_style("U9", None).token, "u1")
        self.assertEqual(get_line_style("S9", None).token, "sbahn")
        self.assertEqual(get_line_style("10", "AKN").token, "akn")
        self.assertEqual(get_line_style("10", "A").token, "akn")
        self.assertEqual(get_line_style("10", "U").token, "u1")
        self.assertEqual(get_line_style("10", "S").token, "sbahn")
        self.assertEqual(get_line_style("10", "FAEHRE").token, "ferry")
        self.assertEqual(get_line_style("10", "XPRESSBUS").token, "xpress")
        self.assertEqual(get_line_style("10", "NACHTBUS").token, "night")
        self.assertEqual(
            get_line_style("<script>alert(1)</script>", None).token, "neutral"
        )
        self.assertEqual(get_line_style("unknown", "unknown").token, "neutral")

    def test_line_style_css_contains_only_allowlisted_classes(self) -> None:
        css = line_style_css()
        self.assertIn(".line-badge-u2{", css)
        self.assertIn("background:#d52b2f", css)
        self.assertIn(".line-badge-neutral{", css)

    def test_line_badges_render_each_shape_and_long_values_safely(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        departures = [
            Departure("5", "Bus", now + timedelta(minutes=1), product="BUS"),
            Departure("U2", "U-Bahn", now + timedelta(minutes=2)),
            Departure("S1", "S-Bahn", now + timedelta(minutes=3)),
            Departure(
                "<script>alert(1)</script>", "Fallback", now + timedelta(minutes=4)
            ),
        ]
        image = render_board(departures, now=now, max_rows=4)
        self.assertEqual(image.size, (320, 240))

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
        self.assertEqual(
            _status_text(
                wifi_is_connected=False,
                stale=True,
                last_updated=now,
                time_is_synchronized=False,
            ),
            "ZEIT NICHT SYNCHRON",
        )

    def test_status_text_covers_wifi_stale_and_current_states(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        self.assertEqual(
            _status_text(
                wifi_is_connected=False,
                stale=False,
                last_updated=None,
            ),
            "KEIN WLAN",
        )
        self.assertEqual(
            _status_text(
                wifi_is_connected=True,
                stale=True,
                last_updated=now,
            ),
            "DATEN VERALTET · 12:00",
        )
        self.assertEqual(
            _status_text(
                wifi_is_connected=None,
                stale=True,
                last_updated=None,
            ),
            "DATEN VERALTET",
        )
        self.assertIsNone(
            _status_text(
                wifi_is_connected=True,
                stale=False,
                last_updated=now,
            )
        )

    def test_unsynchronized_time_has_visible_priority(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        image = render_board(
            [],
            now=now,
            stale=True,
            error_message="Systemzeit ist noch nicht synchronisiert",
            wifi_is_connected=False,
            time_is_synchronized=False,
        )
        self.assertEqual(image.getpixel((0, 239)), (213, 43, 47))
        self.assertIn(
            "ZEIT NICHT SYNCHRON",
            board_state_key(
                [],
                now=now,
                last_updated=None,
                stale=True,
                error_message="time",
                wifi_is_connected=False,
                max_rows=5,
                time_is_synchronized=False,
            ),
        )

    def test_board_state_changes_only_when_visible_content_changes(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, 5, tzinfo=HAMBURG_TZ)
        departures = [Departure("21", "U Niendorf Nord", now + timedelta(minutes=3))]

        def key(at: datetime, *, stale: bool = False) -> tuple[object, ...]:
            return board_state_key(
                departures,
                now=at,
                last_updated=now,
                stale=stale,
                error_message=None,
                wifi_is_connected=True,
                max_rows=5,
            )

        self.assertEqual(key(now), key(now + timedelta(seconds=10)))
        self.assertNotEqual(key(now), key(now + timedelta(minutes=1)))
        self.assertNotEqual(key(now), key(now, stale=True))

    def test_board_state_represents_cancellation_and_empty_error(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        cancelled = Departure(
            "21",
            "U Niendorf Nord",
            now + timedelta(minutes=3),
            cancelled=True,
        )
        cancelled_key = board_state_key(
            [cancelled],
            now=now,
            last_updated=now,
            stale=False,
            error_message="ignored while rows are visible",
            wifi_is_connected=True,
            max_rows=5,
        )
        empty_error_key = board_state_key(
            [],
            now=now,
            last_updated=None,
            stale=True,
            error_message="offline",
            wifi_is_connected=True,
            max_rows=5,
        )
        self.assertIn("AUS", cancelled_key[1][0])
        self.assertFalse(cancelled_key[2])
        self.assertTrue(empty_error_key[2])

    def test_cancelled_and_immediate_departures_render_differently(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        immediate = render_board(
            [Departure("21", "Ziel", now - timedelta(seconds=1))],
            now=now,
        )
        cancelled = render_board(
            [Departure("21", "Ziel", now, cancelled=True)],
            now=now,
        )
        self.assertNotEqual(immediate.tobytes(), cancelled.tobytes())

    def test_long_text_is_shortened_with_ellipsis(self) -> None:
        draw = ImageDraw.Draw(Image.new("RGB", (100, 30)))
        text, _font_object = _fit_text(
            draw,
            "Ein außergewöhnlich langes Fahrtziel",
            35,
            start_size=18,
            min_size=12,
        )
        self.assertTrue(text.endswith("…"))
        self.assertNotEqual(text, "Ein außergewöhnlich langes Fahrtziel")

    def test_font_falls_back_and_is_cached(self) -> None:
        fallback = ImageFont.load_default(size=13)
        _font.cache_clear()
        with (
            patch("hvv_display.render.Path.is_file", return_value=False),
            patch("hvv_display.render.ImageFont.truetype", side_effect=OSError),
            patch(
                "hvv_display.render.ImageFont.load_default",
                return_value=fallback,
            ) as load_default,
        ):
            self.assertIs(_font(13), fallback)
            self.assertIs(_font(13), fallback)
        load_default.assert_called_once_with(size=13)
        self.assertGreaterEqual(_font.cache_info().hits, 1)
        _font.cache_clear()


if __name__ == "__main__":
    unittest.main()
