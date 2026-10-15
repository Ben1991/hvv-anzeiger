import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hvv_display.web import load_web_password_hash, main


class WebEnvironmentTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "web.env"

    def test_missing_empty_and_unrelated_files_do_not_disable_authentication(self):
        self.assertIsNone(load_web_password_hash(self.path))
        for text in ("", "# comment\nOTHER=value\n", "HVV_WEB_PASSWORD_HASH=\n"):
            self.path.write_text(text)
            self.assertIsNone(load_web_password_hash(self.path))

    def test_hash_dollars_are_literal_and_quotes_are_supported(self):
        hashed = "pbkdf2-sha256$600000$literal-salt$literal-digest"
        for value in (hashed, f"'{hashed}'", f'"{hashed}"'):
            self.path.write_text(f"HVV_WEB_PASSWORD_HASH={value}\n")
            self.assertEqual(load_web_password_hash(self.path), hashed)

    def test_ambiguous_or_oversized_files_fail_closed(self):
        for text in ("HVV_WEB_PASSWORD_HASH=a\nHVV_WEB_PASSWORD_HASH=b", "a" * 8193):
            self.path.write_text(text)
            with self.assertRaises(ValueError):
                load_web_password_hash(self.path)

    def test_container_startup_reads_file_and_explicit_hash_takes_precedence(self):
        self.path.write_text("HVV_WEB_PASSWORD_HASH=from-file\n")
        for extra, expected in (
            ({}, "from-file"),
            ({"HVV_WEB_PASSWORD_HASH": "explicit"}, "explicit"),
        ):
            with (
                patch.dict(
                    os.environ,
                    {"HVV_WEB_ENV_FILE": str(self.path), **extra},
                    clear=True,
                ),
                patch("sys.argv", ["hvv-web"]),
                patch("hvv_display.web.run") as run,
            ):
                main()
                self.assertEqual(run.call_args.kwargs["access_token"], expected)
