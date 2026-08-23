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
            (Path(__file__).parents[1] / "config.example.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        self.credentials = root / "credentials.env"
        self.credentials.write_text(
            "GEOFOX_USER=test\nGEOFOX_PASSWORD=secret\n", encoding="utf-8"
        )
        self.app = WebApplication(self.config, self.credentials, root / "stations.json")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_settings_uses_automatic_station_search_and_readonly_geofox_id(
        self,
    ) -> None:
        page = self.app.settings().decode("utf-8")
        self.assertIn("Vorschläge erscheinen automatisch", page)
        self.assertIn('data-station-field="id"', page)
        self.assertIn("readonly", page)
        self.assertIn("scheduleStationSearch", page)
        self.assertIn("Geofox wird abgefragt", page)
        self.assertIn("Richtung oder Zielstation?", page)
        self.assertIn("Verfügbare Linien laden", page)
        self.assertIn("data-line-options", page)
        self.assertIn("data-route-configs", page)
        self.assertIn("/api/line-routes?station_id=", page)
        self.assertIn("Zu Zielstation", page)
        self.assertIn("Richtung oder Zielstation festlegen", page)

    def test_station_search_validates_lengths_before_geofox_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "zu lang"):
            self.app.station_suggestions("x" * 121, "Hamburg")
        with self.assertRaisesRegex(ValueError, "mindestens zwei"):
            self.app.station_suggestions("x", "Hamburg")

    def test_line_suggestions_are_station_specific_and_cached(self) -> None:
        lines = [
            {
                "id": "line:5",
                "name": "5",
                "type": "BUS",
                "carrierNameShort": "HHA",
                "sublines": [
                    {
                        "vehicleType": "BUS",
                        "stationSequence": [{"id": "Master:1"}],
                    }
                ],
            },
            {
                "id": "line:S1",
                "name": "S1",
                "type": "SBAHN",
                "sublines": [
                    {
                        "vehicleType": "SBAHN",
                        "stationSequence": [{"id": "Master:2"}],
                    }
                ],
            },
        ]
        with patch.object(self.app, "_client") as client:
            client.return_value.list_lines.return_value = lines
            first = self.app.line_suggestions("Master:1")
            second = self.app.line_suggestions("Master:1")
        self.assertEqual(first, second)
        self.assertEqual(first[0]["productLabel"], "Bus")
        client.return_value.list_lines.assert_called_once_with()

        with self.assertRaisesRegex(ValueError, "ungültig"):
            self.app.line_suggestions("bad\nstation")

    def test_line_route_suggestions_and_target_stations_use_cached_catalog(
        self,
    ) -> None:
        lines = [
            {
                "id": "line:U2",
                "name": "U2",
                "type": "TRAIN",
                "sublines": [
                    {
                        "vehicleType": "UBAHN",
                        "stationSequence": [
                            {"id": "Master:1", "name": "Jungfernstieg"},
                            {"id": "Master:2", "name": "Niendorf Markt"},
                            {"id": "Master:3", "name": "Niendorf Nord"},
                        ],
                    }
                ],
            }
        ]
        with patch.object(self.app, "_client") as client:
            client.return_value.list_lines.return_value = lines
            routes = self.app.line_route_suggestions("Master:1", "line:U2")
            stations = self.app.line_station_suggestions(
                "Master:1", "line:U2", "Nord"
            )
        self.assertEqual(routes[0]["label"], "Richtung Niendorf Nord")
        self.assertEqual(stations, [{"id": "Master:3", "name": "Niendorf Nord"}])
        client.return_value.list_lines.assert_called_once_with()

    def test_station_config_is_revalidated_and_enriched_before_save(self) -> None:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        raw["stations"] = [
            {
                "name": "Jungfernstieg",
                "city": "Hamburg",
                "id": "Master:1",
                "label": "J",
                "routes": [{"line": "5", "destination": "Hauptbahnhof"}],
            }
        ]
        matches = [
            {
                "name": "Jungfernstieg",
                "city": "Hamburg",
                "id": "Master:1",
                "combinedName": "Hamburg, Jungfernstieg",
                "serviceTypes": ["BUS", "UBAHN", "SBAHN"],
            }
        ]
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.return_value = matches
            validated = self.app.validate_station_config(
                raw,
                user="test",
                password="secret",  # noqa: S106
            )
        self.assertEqual(
            validated["stations"][0]["serviceTypes"], ["BUS", "UBAHN", "SBAHN"]
        )
        self.assertEqual(validated["stations"][0]["id"], "Master:1")

    def test_multimodal_line_route_is_checked_against_geofox_catalog(self) -> None:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        raw["stations"] = [
            {
                "name": "Jungfernstieg",
                "city": "Hamburg",
                "id": "Master:1",
                "label": "J",
                "routes": [
                    {
                        "line_id": "line:U2",
                        "line": "untrusted",
                        "filter_mode": "destination",
                        "filter_station_ids": ["Master:2"],
                    }
                ],
            }
        ]
        matches = [{"name": "Jungfernstieg", "city": "Hamburg", "id": "Master:1"}]
        lines = [
            {
                "id": "line:U2",
                "name": "U2",
                "sublines": [
                    {
                        "vehicleType": "UBAHN",
                        "stationSequence": [
                            {"id": "Master:1", "name": "Jungfernstieg"},
                            {"id": "Master:2", "name": "Niendorf Markt"},
                        ],
                    }
                ],
            }
        ]
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.return_value = matches
            client.return_value.list_lines.return_value = lines
            validated = self.app.validate_station_config(
                raw, user="test", password="secret"  # noqa: S106
            )
        route = validated["stations"][0]["routes"][0]
        self.assertEqual(route, {
            "line_id": "line:U2",
            "line": "U2",
            "product": "UBAHN",
            "filter_mode": "destination",
            "filter_station_ids": ["Master:2"],
            "destination": "Niendorf Markt",
        })

        raw["stations"][0]["routes"][0]["line_id"] = "line:missing"
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.return_value = matches
            client.return_value.list_lines.return_value = lines
            with self.assertRaisesRegex(ValueError, "nicht verfügbar"):
                self.app.validate_station_config(
                    raw, user="test", password="secret"  # noqa: S106
                )

    def test_settings_preserves_multimodal_filter_selection_data(self) -> None:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        raw["stations"][0]["routes"] = [
            {
                "line_id": "line:U2",
                "line": "U2",
                "product": "UBAHN",
                "filter_mode": "destination",
                "filter_station_ids": ["Master:2"],
                "destination": "Niendorf Markt",
            }
        ]
        self.config.write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )

        page = self.app.settings().decode("utf-8")

        self.assertIn('&quot;filterMode&quot;: &quot;destination&quot;', page)
        self.assertIn('&quot;filterStationIds&quot;: [&quot;Master:2&quot;]', page)

    def test_station_config_rejects_unselected_or_stale_station(self) -> None:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        raw["stations"][0].pop("id", None)
        with patch.object(self.app, "_client"):
            with self.assertRaisesRegex(ValueError, "Geofox-Vorschlag auswählen"):
                self.app.validate_station_config(
                    raw,
                    user="test",
                    password="secret",  # noqa: S106
                )

        raw = json.loads(self.config.read_text(encoding="utf-8"))
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.return_value = []
            with self.assertRaisesRegex(
                ValueError, "findet die ausgewählte Haltestelle nicht mehr"
            ):
                self.app.validate_station_config(
                    raw,
                    user="test",
                    password="secret",  # noqa: S106
                )

    def test_geofox_error_is_not_treated_as_invalid_station(self) -> None:
        raw = json.loads(self.config.read_text(encoding="utf-8"))
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.side_effect = GeofoxError(
                "Geofox ist aktuell nicht erreichbar.",
                kind="temporary",
                http_status=503,
            )
            with self.assertRaises(GeofoxError):
                self.app.validate_station_config(
                    raw,
                    user="test",
                    password="secret",  # noqa: S106
                )


if __name__ == "__main__":
    unittest.main()
