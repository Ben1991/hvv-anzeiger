# ruff: noqa: S105
# Deliberately synthetic credentials exercise the export allowlist.
import io
import json
import os
import stat
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
from unittest.mock import patch

from hvv_display.config import ConfigError, config_from_dict, load_config
from hvv_display.config_backup import (
    FORMAT,
    MAX_BACKUPS,
    MAX_CONFIG_BYTES,
    ConfigConflict,
    ConfigStore,
    configuration_diff,
    export_config,
    import_config,
    main,
)


class ConfigBackupTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "config.json"
        self.original = Path("config.example.json").read_bytes()
        self.path.write_bytes(self.original)
        self.raw = json.loads(self.original)
        self.store = ConfigStore(self.path)

    def changed(self, rotate=2):
        raw = deepcopy(self.raw)
        raw["display"]["rotate"] = rotate
        return raw

    def cli(self, *args):
        with (
            patch.object(
                sys, "argv", ["config-backup", "--config", str(self.path), *args]
            ),
            patch("sys.stdout", new_callable=io.StringIO) as output,
        ):
            result = main()
        return result, output.getvalue()

    def test_export_allowlist_removes_secrets_at_every_level(self):
        raw = deepcopy(self.raw)
        raw["GEOFOX_USER"] = "fake-application-id"
        raw["web_password_hash"] = "fake-web-hash"
        raw["api"]["password"] = "fake-api-secret"
        raw["display"]["private_path"] = "/private/path"
        raw["stations"][0]["password"] = "fake-station-secret"
        raw["stations"][0]["routes"][0]["token"] = "fake-route-secret"
        exported = export_config(raw)
        for secret in (
            "fake-application-id",
            "fake-web-hash",
            "fake-api-secret",
            "/private/path",
            "fake-station-secret",
            "fake-route-secret",
        ):
            self.assertNotIn(secret.encode(), exported)
        self.assertEqual(
            config_from_dict(import_config(exported)), config_from_dict(self.raw)
        )
        self.assertEqual(json.loads(exported)["format"], FORMAT)
        self.assertEqual(json.loads(exported)["schema_version"], 1)

    def test_foreign_incompatible_oversized_duplicate_and_invalid_files_rejected(self):
        for payload in (
            b"invalid",
            b'{"bad":NaN}',
            b"\xff",
            b"[]",
            b"{}",
            b" " * (MAX_CONFIG_BYTES + 1),
            b'{"format":"hvv-anzeiger-config","schema_version":1,"schema_version":2,"config":{}}',
            b"[" * 2000 + b"]" * 2000,
            export_config(self.raw).decode().encode("utf-16"),
        ):
            with self.subTest(payload=payload[:30]):
                with self.assertRaises(ConfigError):
                    import_config(payload)
        envelope = json.loads(export_config(self.raw))
        for key, value in (
            ("schema_version", 2),
            ("schema_version", True),
            ("format", "other-product"),
            ("password", "untrusted"),
        ):
            with self.subTest(key=key, value=value):
                candidate = envelope | {key: value}
                with self.assertRaises(ConfigError):
                    import_config(json.dumps(candidate).encode())

    def test_import_rejects_unknown_secret_fields_and_nested_wrong_types(self):
        for mutate in (
            lambda raw: raw.update({"credentials": {"password": "secret"}}),
            lambda raw: raw["api"].update({"application_id": "secret"}),
            lambda raw: raw["stations"][0].update({"token": "secret"}),
            lambda raw: raw["stations"][0]["routes"][0].update({"token": "secret"}),
            lambda raw: raw["display"].update({"rotate": True}),
            lambda raw: raw["stations"][0].update({"serviceTypes": [{}]}),
            lambda raw: raw["stations"][0]["routes"][0].update(
                {"filter_station_ids": [{}]}
            ),
            lambda raw: raw.update({"stations": {}}),
            lambda raw: raw.update({"api": []}),
            lambda raw: raw["stations"][0].update({"name": "\ud800"}),
        ):
            raw = deepcopy(self.raw)
            mutate(raw)
            with self.subTest(raw=raw):
                with self.assertRaises(ConfigError):
                    import_config(
                        json.dumps(
                            {"format": FORMAT, "schema_version": 1, "config": raw}
                        ).encode()
                    )

    def test_import_and_startup_share_full_semantic_validation(self):
        for mutate in (
            lambda raw: raw["display"].update({"rotate": 99}),
            lambda raw: raw["api"].update({"refresh_seconds": 1}),
            lambda raw: raw["api"].update({"base_url": "http://evil.example"}),
            lambda raw: raw["night_shutdown"].update({"end": "99:00"}),
            lambda raw: raw.update({"stations": []}),
        ):
            raw = deepcopy(self.raw)
            mutate(raw)
            with self.assertRaises(ConfigError):
                config_from_dict(raw)
            with self.assertRaises(ConfigError):
                import_config(
                    json.dumps(
                        {"format": FORMAT, "schema_version": 1, "config": raw}
                    ).encode()
                )

    def test_preview_is_read_only_and_diff_reports_old_and_new_values(self):
        before = self.path.stat().st_mtime_ns
        candidate = self.changed()
        preview = self.store.preview(candidate)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.path.stat().st_mtime_ns, before)
        self.assertFalse(self.store.backups.exists())
        self.assertEqual(
            preview["changes"], [{"field": "display.rotate", "before": 0, "after": 2}]
        )
        self.assertFalse(preview["current_invalid"])
        self.assertEqual(
            configuration_diff({}, {"stations": [{"id": None}]}),
            [{"field": "stations[0].id", "before": None, "after": None}],
        )

    def test_apply_creates_private_backup_and_restore_saves_current_before_replacement(
        self,
    ):
        preview = self.store.preview(self.changed())
        backup = self.store.apply(
            self.changed(), expected_revision=preview["base_revision"]
        )
        self.assertEqual(self.store.backup_payload(backup), self.original)
        self.assertEqual(load_config(self.path).display.rotate, 2)
        restore = self.store.backup_candidate(backup)
        restored = self.store.apply(
            restore, expected_revision=self.store.base_revision()
        )
        self.assertEqual(load_config(self.path).display.rotate, 0)
        self.assertEqual(
            json.loads(self.store.backup_payload(restored))["display"]["rotate"], 2
        )
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.store.backups.stat().st_mode), 0o700)
            self.assertEqual(
                stat.S_IMODE((self.store.backups / backup).stat().st_mode), 0o600
            )
            self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertIsNone(self.store.apply(restore))

    def test_failed_atomic_replace_and_failed_fsync_preserve_active_bytes(self):
        real_replace = os.replace

        def fail_target(source, target):
            if Path(target) == self.store.path:
                raise PermissionError("simulated")
            return real_replace(source, target)

        with patch("hvv_display.config_backup.os.replace", side_effect=fail_target):
            with self.assertRaises(PermissionError):
                self.store.apply(self.changed())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(
            self.store.backup_payload(self.store.list_backups()[0]), self.original
        )
        with patch("hvv_display.config_backup.os.fsync", side_effect=OSError):
            with self.assertRaises(OSError):
                self.store.apply(self.changed())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob(".hvv-config-*.tmp")), [])

    def test_backup_failure_aborts_change_and_history_is_bounded(self):
        with patch.object(self.store, "_backup", side_effect=PermissionError):
            with self.assertRaises(PermissionError):
                self.store.apply(self.changed())
        self.assertEqual(self.path.read_bytes(), self.original)
        for index in range(MAX_BACKUPS + 3):
            self.store.apply(self.changed(index % 4))
        self.assertEqual(len(self.store.list_backups()), MAX_BACKUPS)

    def test_concurrent_writers_with_same_revision_cannot_overwrite_each_other(self):
        expected = self.store.base_revision()
        ready = Barrier(2)

        def write(rotate):
            ready.wait(timeout=2)
            try:
                ConfigStore(self.path).apply(
                    self.changed(rotate), expected_revision=expected
                )
                return "applied"
            except ConfigConflict:
                return "conflict"

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(write, [1, 2]))
        self.assertCountEqual(results, ["applied", "conflict"])
        self.assertEqual(len(self.store.list_backups()), 1)
        self.assertIn(load_config(self.path).display.rotate, (1, 2))

    def test_abandoned_staging_files_are_cleaned_and_corrupt_current_can_be_restored(
        self,
    ):
        backup = self.store.backup()
        self.path.write_bytes(b"broken-json")
        orphan = self.root / ".hvv-config-abandoned.tmp"
        orphan.write_bytes(b"partial")
        candidate = self.store.backup_candidate(backup)
        preview = self.store.preview(candidate)
        self.assertTrue(preview["current_invalid"])
        damaged = self.store.apply(
            candidate, expected_revision=preview["base_revision"]
        )
        self.assertEqual(load_config(self.path).display.rotate, 0)
        self.assertEqual(self.store.backup_payload(damaged), b"broken-json")
        self.assertFalse(orphan.exists())
        with self.assertRaises(ConfigError):
            self.store.backup_candidate(damaged)

    def test_backup_ids_and_regular_file_checks_prevent_path_escape(self):
        for name in (
            "../config.json",
            "/etc/passwd",
            "..\\config.json",
            "credentials.env",
            "backup-other.json",
        ):
            with self.assertRaises(ConfigError):
                self.store.backup_payload(name)
        with self.assertRaises(ConfigError):
            ConfigStore(self.root).current()

    @unittest.skipIf(os.name == "nt", "Unix symlink permissions")
    def test_installed_config_alias_survives_atomic_restore(self):
        target = self.root / "var" / "config.json"
        target.parent.mkdir()
        self.path.rename(target)
        self.path.symlink_to("var/config.json")
        store = ConfigStore(self.path)
        store.apply(self.changed())
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(load_config(self.path).display.rotate, 2)
        self.assertEqual(store.backups, target.parent / "config-backups")

    def test_cli_export_preview_confirmation_apply_and_changed_candidate(self):
        exported = self.root / "export.json"
        self.assertEqual(self.cli("export", "--output", str(exported))[0], 0)
        self.assertEqual(
            config_from_dict(import_config(exported.read_bytes())),
            config_from_dict(self.raw),
        )
        self.assertEqual(self.cli("export", "--output", str(exported))[0], 2)
        exported.write_bytes(export_config(self.changed()))
        result, output = self.cli("preview", "--file", str(exported))
        self.assertEqual(result, 0)
        preview = json.loads(output)
        args = [
            "apply",
            "--file",
            str(exported),
            "--base-revision",
            preview["base_revision"],
            "--candidate-revision",
            preview["candidate_revision"],
        ]
        self.assertEqual(self.cli(*args)[0], 2)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(self.cli(*args, "--confirm")[0], 0)
        self.assertEqual(self.cli(*args, "--confirm")[0], 3)
        exported.write_bytes(export_config(self.changed(3)))
        self.assertEqual(self.cli(*args, "--confirm")[0], 3)
        self.assertEqual(load_config(self.path).display.rotate, 2)
        backup = self.store.list_backups()[0]
        self.assertEqual(self.cli("preview", "--backup", backup)[0], 0)
        self.assertEqual(
            config_from_dict(
                import_config(self.cli("export", "--backup", backup)[1].encode())
            ),
            config_from_dict(self.raw),
        )
        self.assertEqual(len(json.loads(self.cli("backups")[1])), 1)
        self.assertEqual(self.cli("backup")[0], 0)

    def test_export_of_private_legacy_snapshot_is_redacted(self):
        raw = self.raw | {"credentials": {"password": "private-snapshot-secret"}}
        self.path.write_text(json.dumps(raw), encoding="utf-8")
        backup = self.store.apply(self.changed())
        result, output = self.cli("export", "--backup", backup)
        self.assertEqual(result, 0)
        self.assertNotIn("private-snapshot-secret", output)
        self.assertEqual(
            config_from_dict(import_config(output.encode())), config_from_dict(self.raw)
        )

    @unittest.skipIf(os.name == "nt", "Unix ownership")
    def test_root_cli_preserves_configuration_owner_for_service_access(self):
        owner = self.path.stat()
        with (
            patch("os.geteuid", return_value=0),
            patch("os.fchown") as file_owner,
            patch("os.chown") as directory_owner,
        ):
            self.store.apply(self.changed())
        self.assertEqual(file_owner.call_count, 3)
        for call in file_owner.call_args_list:
            self.assertEqual(call.args[1:], (owner.st_uid, owner.st_gid))
        directory_owner.assert_any_call(self.store.backups, owner.st_uid, owner.st_gid)

    def test_lock_timeout_rejects_change_and_large_export_is_bounded(self):
        with self.store.locked():
            with patch("hvv_display.config_backup.time.monotonic", side_effect=[0, 3]):
                with self.assertRaises(ConfigConflict):
                    ConfigStore(self.path).apply(self.changed())
        self.assertEqual(self.path.read_bytes(), self.original)
        too_large = self.changed()
        too_large["stations"][0]["name"] = "x" * MAX_CONFIG_BYTES
        with self.assertRaises(ConfigError):
            export_config(too_large)

    def test_interrupted_write_preserves_active_file_and_cleans_staging(self):
        with patch.object(self.store, "_backup", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.store.apply(self.changed())
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.root.glob(".hvv-config-*.tmp")), [])

    def test_other_configuration_files_have_separate_backup_histories(self):
        self.store.backup()
        alternate = self.root / "other.json"
        alternate.write_bytes(self.original)
        other = ConfigStore(alternate)
        other.backup()
        self.assertNotEqual(other.backups, self.store.backups)
        self.assertEqual(len(other.list_backups()), 1)
        self.assertEqual(len(self.store.list_backups()), 1)


if __name__ == "__main__":
    unittest.main()
