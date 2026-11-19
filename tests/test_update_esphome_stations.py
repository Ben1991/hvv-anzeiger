"""Tests for editing the private station substitution in an ESPHome profile."""

from __future__ import annotations

import importlib.util
import json
import re
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "update_esphome_stations.py"
SPEC = importlib.util.spec_from_file_location("update_esphome_stations", SCRIPT)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load the ESPHome station updater")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class UpdateEspHomeStationsTest(unittest.TestCase):
    def test_replaces_only_the_station_json_and_round_trips_apostrophes(self):
        profile = (
            "substitutions:\n  hvv_stations_json: '[]'\n"
            "packages:\n  core: !include packages/core.yaml\n"
        )
        stations = [
            {
                "name": "O'Brienstraße",
                "city": "Hamburg",
                "id": "Master:123",
                "label": "OB",
                "routes": [{"line": "3", "destination": "Hauptbahnhof"}],
            }
        ]
        updated = MODULE._replace_stations(profile, stations)
        self.assertIn("packages:\n  core: !include packages/core.yaml", updated)
        match = re.search(r"hvv_stations_json: '(.*)'$", updated, re.MULTILINE)
        self.assertIsNotNone(match)
        scalar = match.group(1)
        self.assertEqual(json.loads(scalar.replace("''", "'")), stations)

    def test_requires_explicit_stop_id_and_unique_short_labels(self):
        stations = [
            {"name": "Stop", "city": "Hamburg", "id": "", "label": "S", "routes": []}
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stations.json"
            path.write_text(json.dumps(stations), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "id"):
                MODULE._load_stations(path)


if __name__ == "__main__":
    unittest.main()
