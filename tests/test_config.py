import json
import tempfile
import unittest
from pathlib import Path

from hvv_display.config import ConfigError, load_config


class ConfigTest(unittest.TestCase):
    def test_example_config_is_valid(self) -> None:
        config = load_config("config.example.json")
        self.assertEqual(config.api.refresh_seconds, 15)
        self.assertEqual([route.line for route in config.stations[0].routes], ["186", "184", "384"])

    def test_refresh_below_limit_is_rejected(self) -> None:
        raw = json.loads(Path("config.example.json").read_text(encoding="utf-8"))
        raw["api"]["refresh_seconds"] = 5
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path)


if __name__ == "__main__":
    unittest.main()
