import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hvv_display.geofox import GeofoxError
from hvv_display.web import WebApplication


class StationManagementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.config = root / "config.json"
        self.config.write_text(
            (Path(__file__).parents[1] / "config.example.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.credentials = root / "credentials.env"
        self.credentials.write_text("GEOFOX_USER=test\nGEOFOX_PASSWORD=secret\n", encoding="utf-8")
        self.app = WebApplication(self.config, self.credentials, root / "stations.json")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_settings_uses_automatic_station_search_and_readonly_geofox_id(self) -> None:
        page = self.app.settings().decode("utf-8")
        self.assertIn("Vorschläge erscheinen automatisch", page)
        self.assertIn('data-station-field="id"', page)
        self.assertIn("readonly", page)
        self.assertIn("scheduleStationSearch", page)
        self.assertIn("Geofox wird abgefragt", page)
        self.assertIn("Richtung oder Zielstation?", page)

    def test_station_search_validates_lengths_before_geofox_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "zu lang"):
            self.app.station_suggestions("x" * 121, "Hamburg")
        with self.assertRaisesRegex(ValueError, "mindestens zwei"):
            self.app.station_suggestions("x", "Hamburg")

    def test_station_config_is_revalidated_and_enriched_before_save(self) -> None:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        raw["stations"] = [{
            "name": "Jungfernstieg",
            "city": "Hamburg",
            "id": "Master:1",
            "label": "J",
            "routes": [{"line": "5", "destination": "Hauptbahnhof"}],
        }]
        matches = [{
            "name": "Jungfernstieg",
            "city": "Hamburg",
            "id": "Master:1",
            "combinedName": "Hamburg, Jungfernstieg",
            "serviceTypes": ["BUS", "UBAHN", "SBAHN"],
        }]
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.return_value = matches
            validated = self.app.validate_station_config(raw, user="test", password="secret")
        self.assertEqual(validated["stations"][0]["serviceTypes"], ["BUS", "UBAHN", "SBAHN"])
        self.assertEqual(validated["stations"][0]["id"], "Master:1")

    def test_station_config_rejects_unselected_or_stale_station(self) -> None:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        raw["stations"][0].pop("id", None)
        with patch.object(self.app, "_client"):
            with self.assertRaisesRegex(ValueError, "Geofox-Vorschlag auswählen"):
                self.app.validate_station_config(raw, user="test", password="secret")

        raw = json.loads(self.config.read_text(encoding="utf-8"))
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.return_value = []
            with self.assertRaisesRegex(ValueError, "findet die ausgewählte Haltestelle nicht mehr"):
                self.app.validate_station_config(raw, user="test", password="secret")

    def test_geofox_error_is_not_treated_as_invalid_station(self) -> None:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.side_effect = GeofoxError(
                "Geofox ist aktuell nicht erreichbar.", kind="temporary", http_status=503
            )
            with self.assertRaises(GeofoxError):
                self.app.validate_station_config(raw, user="test", password="secret")


if __name__ == "__main__":
    unittest.main()
