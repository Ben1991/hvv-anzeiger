import unittest
from datetime import datetime, timedelta

from hvv_display.geofox import HAMBURG_TZ
from hvv_display.models import Departure
from hvv_display.render import render_board


class RenderTest(unittest.TestCase):
    def test_render_has_display_dimensions(self) -> None:
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        image = render_board(
            [Departure("186", "S Othmarschen", now + timedelta(minutes=3))],
            now=now,
        )
        self.assertEqual(image.size, (320, 240))
        self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
