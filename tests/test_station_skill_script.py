import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT
    / ".agents"
    / "skills"
    / "adjust-hvv-stations"
    / "scripts"
    / "update_stations.py"
)


class StationSkillScriptTest(unittest.TestCase):
    def _run(self, *args: str) -> subprocess.CompletedProcess[str]:
        # The executable and script path are repository-controlled test fixtures.
        return subprocess.run(  # noqa: S603
            [sys.executable, str(SCRIPT), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_preview_replaces_only_stations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            stations_path = Path(directory) / "stations.json"
            stations_path.write_text(
                json.dumps(
                    [
                        {
                            "name": "Teststraße",
                            "city": "Hamburg",
                            "label": "T",
                            "routes": [
                                {
                                    "line": "1",
                                    "destination": "Testzentrum",
                                }
                            ],
                        }
                    ]
                ),
                encoding="utf-8",
            )
            result = self._run(
                "--config",
                "config.example.json",
                "--stations-file",
                str(stations_path),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        preview = json.loads(result.stdout)
        original = json.loads(
            (ROOT / "config.example.json").read_text(encoding="utf-8")
        )
        self.assertEqual(preview["api"], original["api"])
        self.assertEqual(preview["display"], original["display"])
        self.assertEqual(preview["night_shutdown"], original["night_shutdown"])
        self.assertEqual(preview["stations"][0]["name"], "Teststraße")
        self.assertNotIn("id", preview["stations"][0])

    def test_write_creates_backup_and_valid_configuration(self) -> None:
        original = json.loads(
            (ROOT / "config.example.json").read_text(encoding="utf-8")
        )
        replacement = {
            "stations": [
                {
                    "name": "Neue Haltestelle",
                    "label": "NH",
                    "routes": [{"line": "2", "destination": "Neues Ziel"}],
                }
            ]
        }
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            config_path = Path(directory) / "config.json"
            stations_path = Path(directory) / "stations.json"
            config_path.write_text(json.dumps(original), encoding="utf-8")
            stations_path.write_text(json.dumps(replacement), encoding="utf-8")

            result = self._run(
                "--config",
                str(config_path),
                "--stations-file",
                str(stations_path),
                "--write",
            )

            backups = list(Path(directory).glob("config.json.bak-*"))
            updated = json.loads(config_path.read_text(encoding="utf-8"))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Konfiguration aktualisiert", result.stdout)
        self.assertEqual(len(backups), 1)
        self.assertEqual(updated["stations"], replacement["stations"])

    def test_invalid_station_input_is_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            config_path = Path(directory) / "config.json"
            stations_path = Path(directory) / "stations.json"
            original = (ROOT / "config.example.json").read_text(encoding="utf-8")
            config_path.write_text(original, encoding="utf-8")
            stations_path.write_text("[]", encoding="utf-8")

            result = self._run(
                "--config",
                str(config_path),
                "--stations-file",
                str(stations_path),
                "--write",
            )

            unchanged = config_path.read_text(encoding="utf-8")
            backups = list(Path(directory).glob("config.json.bak-*"))

        self.assertEqual(result.returncode, 2)
        self.assertIn("nicht leeres JSON-Array", result.stderr)
        self.assertEqual(unchanged, original)
        self.assertEqual(backups, [])


if __name__ == "__main__":
    unittest.main()
