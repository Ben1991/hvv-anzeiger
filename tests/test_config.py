import json
import tempfile
import unittest
from pathlib import Path

from hvv_display.config import ConfigError, load_config


class ConfigTest(unittest.TestCase):
    def write_config(self, raw: dict, directory: str) -> Path:
        path = Path(directory) / "config.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return path

    def test_example_config_is_valid(self) -> None:
        config = load_config("config.example.json")
        self.assertEqual(config.api.refresh_seconds, 15)
        self.assertEqual(
            [route.line for route in config.stations[0].routes],
            ["186", "184", "384"],
        )
        self.assertEqual(
            [station.station_id for station in config.stations],
            ["Master:82039", "Master:82015"],
        )

    def test_refresh_below_limit_is_rejected(self) -> None:
        raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        raw["api"]["refresh_seconds"] = 5
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError):
                load_config(self.write_config(raw, directory))

    def test_visible_departure_limit_is_rejected_outside_display_capacity(self) -> None:
        original = json.loads(
            Path("config.example.json").read_text(encoding="utf-8")
        )
        for invalid_value in (0, 6):
            with self.subTest(max_departures=invalid_value):
                raw = json.loads(json.dumps(original))
                raw["api"]["max_departures"] = invalid_value
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaises(ConfigError):
                        load_config(self.write_config(raw, directory))

    def test_invalid_rotation_is_rejected(self) -> None:
        raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        raw["display"]["rotate"] = 4
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError):
                load_config(self.write_config(raw, directory))

    def test_empty_station_list_is_rejected(self) -> None:
        raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        raw["stations"] = []
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError):
                load_config(self.write_config(raw, directory))


if __name__ == "__main__":
    unittest.main()
