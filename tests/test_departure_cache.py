from __future__ import annotations

import hashlib
import hmac
import json
import os
import stat
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hvv_display.config import load_config
from hvv_display.departure_cache import (
    MAX_CACHE_BYTES,
    DepartureCache,
    departure_source,
)
from hvv_display.freshness import departures_for_display
from hvv_display.geofox import HAMBURG_TZ
from hvv_display.models import Departure


class DepartureCacheTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "var" / "departures.json"
        self.cache = DepartureCache(self.path)
        self.config = load_config(Path(__file__).parents[1] / "config.example.json")
        self.source = departure_source(self.config)
        self.fetched_at = datetime(2026, 11, 14, 10, 0, tzinfo=HAMBURG_TZ)
        self.departures = [
            Departure(
                "21",
                "U Niendorf Nord",
                self.fetched_at + timedelta(minutes=4),
                delay_seconds=60,
                station_label="R",
                product="bus",
            )
        ]

    def tearDown(self) -> None:
        self.directory.cleanup()

    def _write_signed_envelope(self, update) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        payload = {key: value for key, value in envelope.items() if key != "signature"}
        update(payload)
        encoded = json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        signature = hmac.new(self.cache.key_path.read_bytes(), encoded, hashlib.sha256)
        envelope = {**payload, "signature": signature.hexdigest()}
        self.path.write_text(json.dumps(envelope), encoding="utf-8")
        self.path.chmod(0o600)

    def test_snapshot_survives_a_new_cache_instance_with_private_files(self) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        self.assertEqual(self.cache._create_key(), self.cache._create_key())
        loaded = DepartureCache(self.path).load(self.source, now=self.fetched_at)

        self.assertIsNotNone(loaded)
        if loaded is None:
            self.fail("saved snapshot did not load")
        self.assertEqual(loaded.departures, self.departures)
        self.assertEqual(loaded.fetched_at, self.fetched_at)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.cache.key_path.stat().st_mode), 0o600)
        serialized = self.path.read_text(encoding="utf-8")
        self.assertNotIn("GEOFOX_PASSWORD", serialized)
        self.assertNotIn("credentials.env", serialized)

    def test_stale_snapshot_is_shown_only_until_the_configured_age(self) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        loaded = self.cache.load(
            self.source, now=self.fetched_at + timedelta(minutes=6)
        )
        if loaded is None:
            self.fail("saved snapshot did not load")

        still_visible = departures_for_display(
            loaded.departures,
            now=self.fetched_at + timedelta(minutes=4, seconds=59),
            last_updated=loaded.fetched_at,
            stale=True,
            max_stale_age_minutes=5,
        )
        expired = departures_for_display(
            loaded.departures,
            now=self.fetched_at + timedelta(minutes=5),
            last_updated=loaded.fetched_at,
            stale=True,
            max_stale_age_minutes=5,
        )

        self.assertEqual(still_visible, self.departures)
        self.assertEqual(expired, [])

    def test_configuration_change_rejects_another_station_snapshot(self) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        changed = load_config(Path(__file__).parents[1] / "config.example.json")
        changed = type(changed)(
            api=changed.api,
            display=changed.display,
            night_shutdown=changed.night_shutdown,
            stations=changed.stations[:-1],
        )

        self.assertIsNone(self.cache.load(departure_source(changed)))

    def test_modified_payload_is_rejected_without_crashing(self) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        envelope["departures"][0]["destination"] = "Manipuliert"
        self.path.write_text(json.dumps(envelope), encoding="utf-8")

        with self.assertLogs("hvv_display.departure_cache", level="WARNING"):
            self.assertIsNone(self.cache.load(self.source))

    def test_invalid_and_oversized_cache_files_are_ignored(self) -> None:
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{broken", encoding="utf-8")
        self.path.chmod(0o600)
        self.assertIsNone(self.cache.load(self.source))
        self.path.write_bytes(b"[" * 2000 + b"]" * 2000)
        self.path.chmod(0o600)
        self.assertIsNone(self.cache.load(self.source))
        self.path.write_bytes(b"x" * (MAX_CACHE_BYTES + 1))
        self.path.chmod(0o600)
        self.assertIsNone(self.cache.load(self.source))
        fake_metadata = type(
            "FileMetadata",
            (),
            {
                "st_mode": self.path.stat().st_mode,
                "st_nlink": 1,
                "st_uid": os.getuid() if hasattr(os, "getuid") else 0,
                "st_size": 0,
            },
        )()
        with patch("hvv_display.departure_cache.os.fstat", return_value=fake_metadata):
            self.assertIsNone(self.cache.load(self.source))

    def test_cache_symlink_hardlink_and_permissive_file_are_rejected(self) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        saved = self.path.read_bytes()
        link = self.path.with_name("link.json")
        if os.name != "nt":
            link.symlink_to(self.path)
            self.assertIsNone(DepartureCache(link).load(self.source))
            link.unlink()

        hard_link = self.path.with_name("hard-link.json")
        os.link(self.path, hard_link)
        self.assertIsNone(DepartureCache(hard_link).load(self.source))
        hard_link.unlink()

        self.path.chmod(0o644)
        if os.name != "nt":
            self.assertIsNone(self.cache.load(self.source))
        self.path.write_bytes(saved)
        self.path.chmod(0o600)

    def test_missing_or_invalid_key_rejects_the_snapshot(self) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        self.cache.key_path.unlink()
        self.assertIsNone(self.cache.load(self.source))
        self.cache.key_path.write_bytes(b"bad")
        self.cache.key_path.chmod(0o600)
        self.assertIsNone(self.cache.load(self.source))

    def test_future_timestamps_and_invalid_fingerprints_are_rejected(self) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        self.assertIsNone(
            self.cache.load(
                self.source,
                now=self.fetched_at - timedelta(minutes=1),
            )
        )
        self.assertIsNone(self.cache.load("invalid"))
        with self.assertRaises(ValueError):
            self.cache.save(self.departures, self.fetched_at, "invalid")

    def test_write_failure_keeps_the_previous_atomic_snapshot(self) -> None:
        self.cache.save(self.departures, self.fetched_at, self.source)
        original = self.path.read_bytes()
        with patch(
            "hvv_display.departure_cache.tempfile.mkstemp",
            side_effect=OSError("disk is read-only"),
        ):
            with self.assertRaises(OSError):
                self.cache.save(
                    self.departures,
                    self.fetched_at + timedelta(minutes=1),
                    self.source,
                )
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_signed_snapshot_fields_are_rejected(self) -> None:
        updates = [
            lambda payload: payload.update(schema_version=2),
            lambda payload: payload.update(departures={}),
            lambda payload: payload.update(departures=[None]),
            lambda payload: payload["departures"][0].update(line=3),
            lambda payload: payload["departures"][0].update(line=""),
            lambda payload: payload["departures"][0].update(line="x" * 161),
            lambda payload: payload["departures"][0].update(line="\x01"),
            lambda payload: payload["departures"][0].update(station_label=3),
            lambda payload: payload["departures"][0].update(departure_time=3),
            lambda payload: payload["departures"][0].update(departure_time="x" * 65),
            lambda payload: payload["departures"][0].update(
                departure_time="2026-11-14T10:00:00"
            ),
            lambda payload: payload["departures"][0].update(delay_seconds=True),
            lambda payload: payload["departures"][0].update(cancelled=1),
            lambda payload: payload.update(departures=[{}] * 31),
            lambda payload: payload.update(fetched_at=3),
            lambda payload: payload.update(fetched_at="2026-11-14T10:00:00"),
        ]
        for update in updates:
            with self.subTest(update=update):
                self._write_signed_envelope(update)
                self.assertIsNone(self.cache.load(self.source))

    def test_bad_signature_and_wrong_cache_directory_are_rejected(self) -> None:
        self._write_signed_envelope(lambda payload: None)
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        envelope["signature"] = "bad"
        self.path.write_text(json.dumps(envelope), encoding="utf-8")
        self.path.chmod(0o600)
        self.assertIsNone(self.cache.load(self.source))

        if os.name != "nt":
            self.path.parent.chmod(0o775)
            with self.assertRaises(OSError):
                self.cache.save(self.departures, self.fetched_at, self.source)
            self.path.parent.chmod(0o700)

    def test_owner_and_private_directory_validation(self) -> None:
        if os.name == "nt":
            self.skipTest("Unix owner metadata is not available on Windows")
        self.cache.save(self.departures, self.fetched_at, self.source)
        with patch(
            "hvv_display.departure_cache._owner_uid",
            return_value=os.getuid() + 1,
        ):
            self.assertIsNone(self.cache.load(self.source))
            with self.assertRaises(OSError):
                self.cache.save(self.departures, self.fetched_at, self.source)

    def test_key_write_and_atomic_replace_failures_clean_up_temporary_files(
        self,
    ) -> None:
        with patch(
            "hvv_display.departure_cache.os.fsync",
            side_effect=OSError("disk error"),
        ):
            with self.assertRaises(OSError):
                self.cache.save(self.departures, self.fetched_at, self.source)
        self.assertFalse(self.cache.key_path.exists())

        self.cache.save(self.departures, self.fetched_at, self.source)
        before = self.path.read_bytes()
        with patch(
            "hvv_display.departure_cache.os.replace",
            side_effect=OSError("rename error"),
        ):
            with self.assertRaises(OSError):
                self.cache.save(self.departures, self.fetched_at, self.source)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.path.parent.glob("*.tmp")), [])

    def test_save_rejects_invalid_metadata_and_unserializable_size(self) -> None:
        with self.assertRaises(ValueError):
            self.cache.save(self.departures, datetime(2026, 11, 14), self.source)
        with self.assertRaises(ValueError):
            self.cache.save(self.departures * 31, self.fetched_at, self.source)
        with patch("hvv_display.departure_cache.MAX_CACHE_BYTES", 10):
            with self.assertRaises(ValueError):
                self.cache.save(self.departures, self.fetched_at, self.source)

    def test_private_file_rejects_wrong_owner(self) -> None:
        if os.name == "nt":
            self.skipTest("Unix owner metadata is not available on Windows")
        self.cache.save(self.departures, self.fetched_at, self.source)
        with patch(
            "hvv_display.departure_cache._owner_uid",
            return_value=os.getuid() + 1,
        ):
            self.assertIsNone(self.cache.load(self.source))


if __name__ == "__main__":
    unittest.main()
