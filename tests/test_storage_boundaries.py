"""Storage failure recovery and cross-platform locking contracts."""

import base64
import io
import json
import os
import stat
import sys
import unittest
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hvv_display import config, geofox, install_state
from hvv_display import config_backup as backup


def os_adapter():
    """Keep real flag integers while replacing selected OS calls in tests."""
    adapter = Mock(wraps=os)
    for name in dir(os):
        if name.isupper():
            setattr(adapter, name, getattr(os, name))
    adapter.O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
    return adapter


class StorageBoundariesTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / "config.json"
        self.original = Path("config.example.json").read_bytes()
        self.path.write_bytes(self.original)
        self.raw = json.loads(self.original)
        self.store = backup.ConfigStore(self.path)

    def test_config_shape_and_conversion_errors_are_user_errors(self):
        for key, value in (("api", []), ("stations", {}), ("stations", [None])):
            with self.subTest(key=key, value=value):
                with self.assertRaises(config.ConfigError):
                    config.config_from_dict(self.raw | {key: value})
        raw = deepcopy(self.raw)
        raw["api"]["version"] = float("inf")
        with self.assertRaises(config.ConfigError):
            config.config_from_dict(raw)

    def test_http_error_bodies_are_bounded_and_validated(self):
        for value in (
            b"x" * (geofox.MAX_RESPONSE_BYTES + 1),
            b"[]",
            b'{"returnCode":1}',
        ):
            self.assertIsNone(
                geofox._http_error_body(Mock(read=Mock(return_value=value)))
            )
        self.assertIsNone(geofox._http_error_body(Mock(read=Mock(side_effect=OSError))))

    def test_backup_input_size_types_and_schema_migration_are_validated(self):
        with self.assertRaises(config.ConfigError):
            backup._read(self.path, limit=1)
        with self.assertRaises(config.ConfigError):
            backup._fields([], {}, strict=True)
        with self.assertRaises(config.ConfigError):
            backup._project_config(
                [], strict=True, fields={}, station_fields={}, route_fields={}
            )
        with self.assertRaises(config.ConfigError):
            backup.migrate_config(1, {"api": {}})
        with self.assertRaises(config.ConfigError):
            backup._fields({"name": "\ud800"}, {"name": str}, strict=True)
        raw = deepcopy(self.raw)
        raw["stations"][0]["routes"][0]["filter_station_ids"] = [1]
        with self.assertRaises(config.ConfigError):
            backup.redact_config(raw)
        # A future schema must fail closed until every intermediate migration exists.
        with patch.object(backup, "CURRENT_SCHEMA_VERSION", 2):
            with self.assertRaisesRegex(config.ConfigError, "Schemamigration"):
                backup.migrate_config(1, self.raw)
            with patch.dict(backup.SCHEMA_UPGRADERS, {1: lambda raw: raw}):
                self.assertEqual(
                    backup.migrate_config(1, self.raw)["api"]["base_url"],
                    self.raw["api"]["base_url"],
                )

    def test_best_effort_cleanup_and_directory_sync_failures(self):
        with patch.object(Path, "unlink", side_effect=OSError):
            with self.assertLogs(backup.LOG, level="WARNING"):
                backup._discard(self.path)
        simulated = os_adapter()
        simulated.name = "posix"
        simulated.open.side_effect = OSError
        with patch.object(backup, "os", simulated):
            with self.assertLogs(backup.LOG, level="WARNING"):
                backup._sync_directory(self.root)
        simulated.name = "nt"
        with patch.object(backup, "os", simulated):
            backup._sync_directory(self.root)
        self.assertEqual(simulated.open.call_count, 1)

    def test_locking_both_platforms_root_owner_retry_and_unlock_failure(self):
        for platform in ("posix", "nt"):
            with self.subTest(platform=platform):
                simulated = os_adapter()
                simulated.name = platform
                simulated.geteuid = Mock(return_value=0)
                simulated.chown = Mock()
                simulated.fchown = Mock()
                windows = SimpleNamespace(
                    LK_NBLCK=1,
                    LK_UNLCK=2,
                    locking=Mock(side_effect=[OSError(), None, OSError()]),
                )
                unix = SimpleNamespace(
                    LOCK_EX=1,
                    LOCK_NB=2,
                    LOCK_UN=4,
                    flock=Mock(side_effect=[OSError(), None, OSError()]),
                )
                with (
                    patch.object(backup, "os", simulated),
                    patch.dict(sys.modules, {"msvcrt": windows, "fcntl": unix}),
                    patch.object(backup.time, "sleep") as sleep,
                ):
                    with self.assertLogs(backup.LOG, level="WARNING"):
                        with self.store.locked():
                            self.assertTrue((self.store.backups / ".lock").is_file())
                    sleep.assert_called_once_with(0.05)
                simulated.close.assert_called_once()

    def test_nonregular_lock_and_abandoned_directories_are_not_treated_as_files(self):
        simulated = os_adapter()
        simulated.name = "nt"
        simulated.fstat.return_value = SimpleNamespace(st_mode=stat.S_IFDIR)
        with patch.object(backup, "os", simulated):
            with self.assertRaisesRegex(config.ConfigError, "Sperrdatei"):
                with self.store.locked():
                    self.fail("must not acquire nonregular lock")
        abandoned = self.root / ".hvv-config-abandoned.tmp"
        abandoned.mkdir()
        with self.store.locked():
            self.assertTrue(abandoned.is_dir())

    def test_temporary_file_root_ownership_and_write_cleanup(self):
        simulated = os_adapter()
        simulated.name = "posix"
        simulated.geteuid = Mock(return_value=0)
        simulated.fchown = Mock()
        with patch.object(backup, "os", simulated):
            temporary = backup._temporary(self.root, b"data", (123, 456))
        self.assertEqual(temporary.read_bytes(), b"data")
        self.assertEqual(simulated.fchown.call_args.args[1:], (123, 456))
        temporary.unlink()

    def test_disappearing_and_nonregular_backup_entries_are_ignored(self):
        self.store.backups.mkdir(parents=True)
        name = "backup-20260101T000000000000Z-aaaaaaaaaaaa.json"
        candidate = self.store.backups / name
        candidate.mkdir()
        self.assertEqual(self.store.list_backups(), [])
        with patch.object(Path, "lstat", side_effect=FileNotFoundError):
            self.assertEqual(self.store.list_backups(), [])

    def test_corrupt_private_and_oversized_historical_snapshots(self):
        self.store.backups.mkdir(parents=True)
        name = "backup-20260101T000000000000Z-aaaaaaaaaaaa.json"
        target = self.store.backups / name
        for record in (
            {"format": backup.PRIVATE_FORMAT},
            {
                "format": backup.PRIVATE_FORMAT,
                "payload_base64": "!",
                "schema_version": 1,
            },
            {
                "format": backup.PRIVATE_FORMAT,
                "payload_base64": base64.b64encode(b"{}").decode(),
                "schema_version": True,
            },
            {
                "format": backup.PRIVATE_FORMAT,
                "payload_base64": base64.b64encode(
                    b"x" * (backup.MAX_CONFIG_BYTES + 1)
                ).decode(),
                "schema_version": 1,
            },
        ):
            target.write_text(json.dumps(record))
            with self.assertRaisesRegex(config.ConfigError, "beschädigt"):
                self.store.backup_payload(name)
        target.write_bytes(b"x" * (backup.MAX_CONFIG_BYTES + 1))
        with self.assertRaisesRegex(config.ConfigError, "zu groß"):
            self.store.backup_payload(name)

    def test_cli_backup_export_preview_and_io_error(self):
        def cli(*args):
            with (
                patch.object(
                    sys, "argv", ["backup", "--config", str(self.path), *args]
                ),
                patch("sys.stdout", new_callable=io.StringIO) as output,
            ):
                result = backup.main()
            return result, output.getvalue()

        result, output = cli("backup")
        self.assertEqual(result, 0)
        name = output.strip()
        for args in (
            ("backups",),
            ("preview", "--backup", name),
            ("export", "--backup", name),
        ):
            self.assertEqual(cli(*args)[0], 0)
        destination = self.root / "export.json"
        self.assertEqual(cli("export", "--output", str(destination))[0], 0)
        self.assertEqual(
            backup.import_config(destination.read_bytes())["api"]["base_url"],
            self.raw["api"]["base_url"],
        )
        self.assertEqual(cli("export", "--output", str(destination))[0], 2)


class InstallStateBoundaryTest(unittest.TestCase):
    def test_missing_runtime_missing_config_and_alias_without_runtime(self):
        for mode in ("regular", "missing", "alias"):
            with self.subTest(mode=mode):
                metadata = SimpleNamespace(
                    st_mode=stat.S_IFLNK if mode == "alias" else stat.S_IFREG
                )
                with (
                    patch.object(
                        install_state,
                        "_directory",
                        side_effect=[10, FileNotFoundError()],
                    ),
                    patch.object(
                        install_state.os,
                        "stat",
                        side_effect=FileNotFoundError() if mode == "missing" else None,
                        return_value=metadata,
                    ),
                    patch.object(
                        install_state.os, "readlink", return_value="var/config.json"
                    ),
                    patch.object(install_state.os, "close") as close,
                    patch.object(install_state, "_copy_file") as copy,
                ):
                    if mode == "alias":
                        with self.assertRaisesRegex(
                            ValueError, "ohne Datenverzeichnis"
                        ):
                            install_state.copy_install_state(
                                Path("app"), Path("staging")
                            )
                    else:
                        install_state.copy_install_state(Path("app"), Path("staging"))
                        self.assertEqual(copy.call_count, int(mode == "regular"))
                    close.assert_called_once_with(10)

    def test_installer_cli_passes_paths(self):
        with (
            patch.object(sys, "argv", ["install-state", "app", "staging"]),
            patch.object(install_state, "copy_install_state") as copy,
        ):
            install_state.main()
        copy.assert_called_once_with(Path("app"), Path("staging"))
