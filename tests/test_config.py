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
        self.assertEqual([station.label for station in config.stations], ["W", "R"])

    def test_refresh_below_limit_is_rejected(self) -> None:
        raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        raw["api"]["refresh_seconds"] = 5
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ConfigError):
                load_config(self.write_config(raw, directory))

    def test_visible_departure_limit_is_rejected_outside_display_capacity(self) -> None:
        original = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
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

    def test_duplicate_station_labels_are_rejected(self) -> None:
        raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        raw["stations"][1]["label"] = raw["stations"][0]["label"]
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ConfigError, "eindeutig"):
                load_config(self.write_config(raw, directory))

    def test_string_boolean_is_rejected(self) -> None:
        raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        raw["display"]["bgr"] = "false"
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ConfigError, "true oder false"):
                load_config(self.write_config(raw, directory))

    def test_missing_file_and_invalid_json_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with self.assertRaisesRegex(ConfigError, "nicht gefunden"):
                load_config(missing)

            invalid = Path(directory) / "invalid.json"
            invalid.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "Ungültiges JSON"):
                load_config(invalid)

    def test_root_sections_are_required(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for raw in ({}, [], {"api": {}, "display": {}}):
                with self.subTest(raw=raw):
                    with self.assertRaisesRegex(ConfigError, "benötigt"):
                        load_config(self.write_config(raw, directory))

    def test_required_nested_fields_are_rejected(self) -> None:
        original = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        mutations = (
            lambda raw: raw["api"].pop("base_url"),
            lambda raw: raw["stations"][0].pop("name"),
            lambda raw: raw["stations"][0]["routes"][0].pop("line"),
            lambda raw: raw["stations"][0]["routes"][0].pop("destination"),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                raw = json.loads(json.dumps(original))
                mutate(raw)
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(ConfigError, "Pflichtfeld"):
                        load_config(self.write_config(raw, directory))

    def test_non_positive_numeric_values_are_rejected(self) -> None:
        original = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        cases = (
            ("api", "request_timeout_seconds"),
            ("api", "max_time_offset_minutes"),
            ("api", "max_stale_age_minutes"),
            ("display", "bus_speed_hz"),
        )
        for section, field in cases:
            with self.subTest(field=f"{section}.{field}"):
                raw = json.loads(json.dumps(original))
                raw[section][field] = 0
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(ConfigError, "größer als 0"):
                        load_config(self.write_config(raw, directory))

    def test_station_label_length_and_empty_routes_are_rejected(self) -> None:
        original = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        for label in (" ", "LANG"):
            with self.subTest(label=label):
                raw = json.loads(json.dumps(original))
                raw["stations"][0]["label"] = label
                with tempfile.TemporaryDirectory() as directory:
                    with self.assertRaisesRegex(ConfigError, "1 und 3"):
                        load_config(self.write_config(raw, directory))

        raw = json.loads(json.dumps(original))
        raw["stations"][0]["routes"] = []
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ConfigError, "darf nicht leer"):
                load_config(self.write_config(raw, directory))

    def test_optional_values_use_defaults(self) -> None:
        raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        for field in (
            "version",
            "refresh_seconds",
            "request_timeout_seconds",
            "max_departures",
            "max_time_offset_minutes",
            "max_stale_age_minutes",
        ):
            raw["api"].pop(field, None)
        for field in (
            "spi_port",
            "spi_device",
            "gpio_dc",
            "gpio_reset",
            "rotate",
            "bus_speed_hz",
            "bgr",
        ):
            raw["display"].pop(field, None)
        raw["stations"][0].pop("label")
        raw["stations"][0].pop("city")
        with tempfile.TemporaryDirectory() as directory:
            config = load_config(self.write_config(raw, directory))
        self.assertEqual(config.api.version, 63)
        self.assertEqual(config.api.max_stale_age_minutes, 5)
        self.assertEqual(config.display.bus_speed_hz, 16_000_000)
        self.assertEqual(config.stations[0].label, "W")
        self.assertEqual(config.stations[0].city, "Hamburg")


if __name__ == "__main__":
    unittest.main()
