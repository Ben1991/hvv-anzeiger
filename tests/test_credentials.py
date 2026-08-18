import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hvv_display.credentials import load_credentials


class CredentialsTest(unittest.TestCase):
    def test_file_values_are_unquoted_and_environment_fills_missing_file(self) -> None:
        with TemporaryDirectory() as directory:
            credentials = Path(directory) / "credentials.env"
            credentials.write_text(
                "GEOFOX_USER='file-user'\n"
                "GEOFOX_PASSWORD=\"file-password\"\n"
                "OTHER=value\n"
                "INVALID\n",
                encoding="utf-8",
            )
            self.assertEqual(
                load_credentials(credentials),
                {
                    "GEOFOX_USER": "file-user",
                    "GEOFOX_PASSWORD": "file-password",
                },
            )

            with patch.dict(
                os.environ,
                {
                    "GEOFOX_USER": "environment-user",
                    "GEOFOX_PASSWORD": "environment-password",
                },
                clear=True,
            ):
                self.assertEqual(
                    load_credentials(Path(directory) / "missing.env"),
                    {
                        "GEOFOX_USER": "environment-user",
                        "GEOFOX_PASSWORD": "environment-password",
                    },
                )


if __name__ == "__main__":
    unittest.main()
