import json
import tempfile
import unittest
from pathlib import Path

from hvv_display.models import Route, Station
from hvv_display.stations import resolve_stations


class FakeClient:
    def __init__(self, station_id: str = "Master:99") -> None:
        self.station_id = station_id
        self.calls: list[tuple[str, str]] = []

    def find_station(self, name: str, city: str) -> dict[str, str]:
        self.calls.append((name, city))
        return {"id": self.station_id}


class StationResolutionTest(unittest.TestCase):
    def station(self, station_id=None) -> Station:
        return Station(
            "Teststraße",
            "Hamburg",
            (Route("21", "U Niendorf Nord"),),
            station_id,
        )

    def test_configured_id_needs_no_lookup_or_cache(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "stations.json"
            result = resolve_stations(client, (self.station("Master:1"),), cache)
            self.assertEqual(result[0].station_id, "Master:1")
            self.assertEqual(client.calls, [])
            self.assertFalse(cache.exists())

    def test_cached_id_is_reused(self) -> None:
        client = FakeClient()
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "stations.json"
            cache.write_text(
                json.dumps({"hamburg|teststrasse": "Master:2"}),
                encoding="utf-8",
            )
            result = resolve_stations(client, (self.station(),), cache)
            self.assertEqual(result[0].station_id, "Master:2")
            self.assertEqual(client.calls, [])

    def test_missing_id_is_resolved_and_persisted(self) -> None:
        client = FakeClient("Master:3")
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "nested" / "stations.json"
            result = resolve_stations(client, (self.station(),), cache)
            self.assertEqual(result[0].station_id, "Master:3")
            self.assertEqual(client.calls, [("Teststraße", "Hamburg")])
            persisted = json.loads(cache.read_text(encoding="utf-8"))
            self.assertEqual(persisted["hamburg|teststrasse"], "Master:3")

    def test_valid_json_with_wrong_shape_is_ignored(self) -> None:
        client = FakeClient("Master:4")
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "stations.json"
            cache.write_text("[]", encoding="utf-8")
            result = resolve_stations(client, (self.station(),), cache)
            self.assertEqual(result[0].station_id, "Master:4")


if __name__ == "__main__":
    unittest.main()
