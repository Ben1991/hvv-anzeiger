import json
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hvv_display import config_backup as backups
from hvv_display.config import (
    ApiConfig,
    ConfigError,
    DisplayConfig,
    NightShutdownConfig,
    config_from_dict,
)
from hvv_display.models import Route, Station

FIXTURES = Path(__file__).parent / "fixtures" / "config-backups"


class BackupCompatibilityTest(unittest.TestCase):
    def test_every_published_schema_keeps_its_reader_fixture_and_upgrade_path(self):
        published = set(range(1, backups.CURRENT_SCHEMA_VERSION + 1))
        self.assertEqual(set(backups.SCHEMA_READERS), published)
        self.assertEqual(set(backups.SCHEMA_FIELDS), published)
        self.assertEqual(
            set(backups.SCHEMA_UPGRADERS), published - {backups.CURRENT_SCHEMA_VERSION}
        )
        fixtures = {
            int(path.name.split("-")[0][1:])
            for path in FIXTURES.glob("v*-minimal.json")
        }
        self.assertEqual(fixtures, published)
        for version in published:
            source = json.loads(
                (FIXTURES / f"v{version}-minimal.json").read_text(encoding="utf-8")
            )
            expected = json.loads(
                (FIXTURES / f"v{version}-expected.json").read_text(encoding="utf-8")
            )
            self.assertEqual(source["schema_version"], version)
            schema_fields, station_fields, route_fields = backups.SCHEMA_FIELDS[version]
            for section, fields in schema_fields.items():
                self.assertEqual(set(expected[section]), set(fields))
            for station in expected["stations"]:
                self.assertEqual(
                    set(station), set(station_fields) | {"routes", "serviceTypes"}
                )
                for route in station["routes"]:
                    self.assertEqual(
                        set(route), set(route_fields) | {"filter_station_ids"}
                    )
            self.assertEqual(
                backups.SCHEMA_READERS[version](source["config"], strict=True), expected
            )
            config_from_dict(backups.import_config(json.dumps(source).encode()))

    def test_new_configuration_fields_require_an_explicit_schema_change(self):
        fields, stations, routes = backups.SCHEMA_FIELDS[backups.CURRENT_SCHEMA_VERSION]
        self.assertEqual(backups.FIELDS, fields)
        self.assertEqual(backups.STATION_FIELDS, stations)
        self.assertEqual(backups.ROUTE_FIELDS, routes)
        for section, model in (
            ("api", ApiConfig),
            ("display", DisplayConfig),
            ("night_shutdown", NightShutdownConfig),
        ):
            self.assertEqual(set(fields[section]), set(model.__dataclass_fields__))
        self.assertEqual(
            set(stations) | {"routes"},
            {
                "id" if name == "station_id" else name
                for name in Station.__dataclass_fields__
            },
        )
        self.assertEqual(
            set(routes) | {"filter_station_ids"}, set(Route.__dataclass_fields__)
        )

    def test_future_release_and_changed_defaults_preserve_v1_meaning(self):
        source = json.loads((FIXTURES / "v1-minimal.json").read_text(encoding="utf-8"))
        expected = json.loads(
            (FIXTURES / "v1-expected.json").read_text(encoding="utf-8")
        )
        reader_v1 = backups.SCHEMA_READERS[1]
        upgrades = []

        def future_reader(raw, *, strict):
            result = reader_v1(raw, strict=strict)
            if "refresh_seconds" not in raw["api"]:
                result["api"]["refresh_seconds"] = 45
            return result

        def upgrade_one(data):
            upgrades.append(1)
            return deepcopy(data)

        with (
            patch.object(backups, "__version__", "99.0.0"),
            patch.object(backups, "CURRENT_SCHEMA_VERSION", 2),
            patch.object(backups, "SCHEMA_READERS", {1: reader_v1, 2: future_reader}),
            patch.object(backups, "SCHEMA_UPGRADERS", {1: upgrade_one}),
        ):
            restored = backups.import_config(json.dumps(source).encode())
            self.assertEqual(restored, expected)
            self.assertEqual(config_from_dict(restored).api.refresh_seconds, 15)
            self.assertEqual(upgrades, [1])
            source["schema_version"] = 2
            self.assertEqual(
                config_from_dict(
                    backups.import_config(json.dumps(source).encode())
                ).api.refresh_seconds,
                45,
            )

    def test_private_backup_version_and_unwrapped_legacy_snapshot_are_readable(self):
        fixture = json.loads((FIXTURES / "v1-minimal.json").read_text(encoding="utf-8"))
        expected = json.loads(
            (FIXTURES / "v1-expected.json").read_text(encoding="utf-8")
        )
        with TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps(fixture["config"]))
            store = backups.ConfigStore(path)
            name = store.backup()
            record = json.loads((store.backups / name).read_text(encoding="utf-8"))
            self.assertEqual(record["format"], backups.PRIVATE_FORMAT)
            self.assertEqual(record["schema_version"], 1)
            with patch.object(backups, "__version__", "99.0.0"):
                self.assertEqual(store.backup_candidate(name), expected)
            legacy = "backup-20260101T000000000000Z-000000000000.json"
            (store.backups / legacy).write_text(json.dumps(fixture["config"]))
            self.assertEqual(store.backup_candidate(legacy), expected)
            record["schema_version"] = 999
            (store.backups / name).write_text(json.dumps(record))
            with self.assertRaises(ConfigError):
                store.backup_candidate(name)

    def test_legacy_config_json_backup_can_be_imported_without_a_version_header(self):
        source = json.loads((FIXTURES / "v1-minimal.json").read_text(encoding="utf-8"))
        expected = json.loads(
            (FIXTURES / "v1-expected.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            backups.import_config(json.dumps(source["config"]).encode()), expected
        )
