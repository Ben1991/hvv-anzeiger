import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hvv_display.install_state import copy_install_state


@unittest.skipUnless(os.name == "posix", "Linux descriptor-relative file boundary")
class InstallStateTest(unittest.TestCase):
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
