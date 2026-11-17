import errno
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hvv_display.install_state import (
    activate_install,
    copy_install_state,
    main,
    publish_unit,
    relocate_entrypoints,
    rollback_install,
)


@unittest.skipUnless(os.name == "posix", "Linux descriptor-relative file boundary")
class InstallStateTest(unittest.TestCase):
    def test_atomic_activation_keeps_complete_new_live_tree_and_old_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            app, stage = Path(directory) / "app", Path(directory) / "stage"
            stage.mkdir()
            (stage / "version").write_text("first")
            activate_install(app, stage)
            self.assertEqual((app / "version").read_text(), "first")
            stage.mkdir()
            (stage / "version").write_text("second")
            activate_install(app, stage)
            self.assertEqual((app / "version").read_text(), "second")
            self.assertEqual(
                (Path(directory) / "app.previous/version").read_text(), "first"
            )
            rollback_install(app, Path(directory) / "app.previous")
            self.assertEqual((app / "version").read_text(), "first")

    def test_failed_activation_preserves_old_tree_without_nonatomic_fallback(self):
        (self.app / "version").write_text("old")
        (self.staging / "version").write_text("new")
        with patch("hvv_display.install_state.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                activate_install(self.app, self.staging)
        self.assertEqual((self.app / "version").read_text(), "old")
        self.assertEqual((self.staging / "version").read_text(), "new")
        with patch("hvv_display.install_state.ctypes.CDLL") as libc:
            libc.return_value.renameat2.return_value = -1
            with patch(
                "hvv_display.install_state.ctypes.get_errno", return_value=errno.EIO
            ):
                with self.assertRaises(OSError):
                    activate_install(self.app, self.staging)
        self.assertEqual((self.app / "version").read_text(), "old")
        backup = self.app.with_name(self.app.name + ".previous")
        backup.mkdir()
        with self.assertRaises(ValueError):
            activate_install(self.app, self.staging)
        link = self.app.with_name("link")
        link.symlink_to(self.app)
        with self.assertRaises(ValueError):
            rollback_install(link, self.staging)

    def test_entrypoint_relocation_never_follows_python_links(self):
        binary = self.staging / ".venv/bin"
        binary.mkdir(parents=True)
        entry = binary / "hvv-preview"
        entry.write_text(f"#!{self.staging}/.venv/bin/python\nprint('ok')\n")
        (binary / "python").symlink_to(self.victim)
        (binary / "directory").mkdir()
        (binary / "unrelated").write_text("unchanged")
        relocate_entrypoints(self.app, self.staging)
        self.assertTrue(entry.read_text().startswith(f"#!{self.app}/.venv/bin/python"))
        self.assertEqual((binary / "unrelated").read_text(), "unchanged")
        self.assert_victim_unchanged()

    def test_unit_publication_is_atomic_and_removes_only_own_staging_file(self):
        source, destination = self.staging / "unit", self.app / "unit"
        source.write_text("new complete unit")
        destination.write_text("old complete unit")
        with patch("hvv_display.install_state.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                publish_unit(source, destination)
        self.assertEqual(destination.read_text(), "old complete unit")
        self.assertEqual(list(self.app.glob(".hvv-unit-*")), [])
        publish_unit(source, destination)
        self.assertEqual(destination.read_text(), "new complete unit")
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o644)
        source.chmod(0o600)
        publish_unit(source, destination, preserve=True)
        self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
        with (
            patch("hvv_display.install_state.os.geteuid", return_value=0),
            patch("hvv_display.install_state.os.fchown") as owner,
        ):
            publish_unit(source, destination, preserve=True)
        owner.assert_called_once()

    def test_installer_cli_dispatches_preparation_and_activation(self):
        for flag, function in (
            ("--activate", "activate_install"),
            ("--relocate", "relocate_entrypoints"),
            ("--publish-unit", "publish_unit"),
            ("--rollback", "rollback_install"),
            ("--restore-file", "publish_unit"),
            (None, "copy_install_state"),
        ):
            args = ["install_state", str(self.app), str(self.staging)]
            if flag:
                args.append(flag)
            with (
                patch.object(sys, "argv", args),
                patch("hvv_display.install_state." + function) as action,
            ):
                main()
            if flag == "--restore-file":
                action.assert_called_once_with(self.app, self.staging, preserve=True)
            else:
                action.assert_called_once_with(self.app, self.staging)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.app = root / "application"
        self.staging = root / "private-staging"
        self.app.mkdir()
        self.runtime = self.app / "var"
        self.runtime.mkdir()
        self.staging.mkdir(mode=0o700)
        (self.staging / "var").mkdir()
        self.victim = root / "protected"
        self.victim.write_bytes(b"protected contents")
        self.victim.chmod(0o600)
        self.original = self.victim.stat()

    def assert_victim_unchanged(self):
        self.assertEqual(self.victim.read_bytes(), b"protected contents")
        current = self.victim.stat()
        self.assertEqual(current.st_mode, self.original.st_mode)
        self.assertEqual(current.st_uid, self.original.st_uid)

    def test_official_alias_preserves_config_backups_and_password(self):
        (self.runtime / "config.json").write_text('{"stations": []}')
        (self.app / "config.json").symlink_to("var/config.json")
        backups = self.runtime / "config-backups"
        backups.mkdir(mode=0o700)
        (backups / "old.json").write_bytes(b"existing private backup")
        (self.runtime / "web.env").write_bytes(b"existing individual hash")
        copy_install_state(self.app, self.staging)
        self.assertEqual((self.staging / "config.json").read_text(), '{"stations": []}')
        self.assertEqual(
            (self.staging / "var/config-backups/old.json").read_bytes(),
            b"existing private backup",
        )
        self.assertEqual(
            (self.staging / "var/web.env").read_bytes(), b"existing individual hash"
        )
        self.assertEqual(stat.S_IMODE(self.staging.stat().st_mode), 0o700)

    def test_legacy_regular_configuration_and_missing_install(self):
        (self.app / "config.json").write_bytes(b"legacy config")
        copy_install_state(self.app, self.staging)
        self.assertEqual((self.staging / "config.json").read_bytes(), b"legacy config")
        copy_install_state(self.app / "missing", self.staging)

    def test_external_config_alias_is_rejected_without_disclosure(self):
        (self.app / "config.json").symlink_to(self.victim)
        with self.assertRaises(ValueError):
            copy_install_state(self.app, self.staging)
        self.assertFalse((self.staging / "config.json").exists())
        self.assert_victim_unchanged()

    def test_runtime_link_and_preview_link_are_rejected(self):
        for name in ("config.json", "install-preview.png"):
            with self.subTest(name=name):
                link = self.runtime / name
                link.symlink_to(self.victim)
                try:
                    with self.assertRaises(ValueError):
                        copy_install_state(self.app, self.staging)
                    self.assertFalse((self.staging / "var" / name).exists())
                    self.assert_victim_unchanged()
                finally:
                    link.unlink()

    def test_directory_link_fifo_and_hardlink_are_rejected(self):
        link = self.runtime / "directory-link"
        link.symlink_to(self.victim.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            copy_install_state(self.app, self.staging)
        link.unlink()
        fifo = self.runtime / "fifo"
        os.mkfifo(fifo)
        with self.assertRaises(ValueError):
            copy_install_state(self.app, self.staging)
        fifo.unlink()
        os.link(self.victim, self.runtime / "hardlink")
        with self.assertRaises(ValueError):
            copy_install_state(self.app, self.staging)
        self.assert_victim_unchanged()

    def test_regular_file_swapped_after_stat_is_not_followed(self):
        original = self.runtime / "config.json"
        original.write_bytes(b"regular")
        real_open = os.open

        def swap(name, flags, *args, **kwargs):
            if name == "config.json" and flags & os.O_NONBLOCK:
                original.unlink()
                original.symlink_to(self.victim)
            return real_open(name, flags, *args, **kwargs)

        with patch("hvv_display.install_state.os.open", side_effect=swap):
            with self.assertRaises(OSError):
                copy_install_state(self.app, self.staging)
        self.assertFalse((self.staging / "var/config.json").exists())
        self.assert_victim_unchanged()

    def test_runtime_directory_link_is_not_followed(self):
        self.runtime.rmdir()
        self.runtime.symlink_to(self.victim.parent, target_is_directory=True)
        with self.assertRaises(OSError):
            copy_install_state(self.app, self.staging)
        self.assert_victim_unchanged()
