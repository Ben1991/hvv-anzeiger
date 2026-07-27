import unittest

from hvv_display.models import Route, Station


class ModelsTest(unittest.TestCase):
    def test_station_requires_resolved_geofox_id(self) -> None:
        station = Station("Test", "Hamburg", (Route("1", "Ziel"),))
        with self.assertRaisesRegex(ValueError, "noch keine Geofox-ID"):
            station.as_geofox_name()


if __name__ == "__main__":
    unittest.main()
