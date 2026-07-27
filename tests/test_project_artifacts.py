import os
import stat
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class ProjectArtifactTest(unittest.TestCase):
    def test_readme_screenshot_exists_with_display_dimensions(self) -> None:
        screenshot = ROOT / "docs" / "hvv-anzeiger-preview.png"
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/hvv-anzeiger-preview.png", readme)
        with Image.open(screenshot) as image:
            self.assertEqual(image.size, (320, 240))

    def test_installer_is_executable_and_syntax_is_checked_by_ci(self) -> None:
        installer = ROOT / "install.sh"
        mode = installer.stat().st_mode
        self.assertTrue(mode & stat.S_IXUSR)
        self.assertTrue(os.access(installer, os.X_OK))
        diagnostic = ROOT / "diagnose.sh"
        self.assertTrue(diagnostic.stat().st_mode & stat.S_IXUSR)
        self.assertTrue(os.access(diagnostic, os.X_OK))

    def test_systemd_service_uses_protected_environment_file(self) -> None:
        service = (ROOT / "systemd" / "hvv-anzeiger.service").read_text(
            encoding="utf-8"
        )
        self.assertIn("EnvironmentFile=/etc/hvv-anzeiger.env", service)
        self.assertIn("Restart=on-failure", service)
        self.assertIn("After=network-online.target time-sync.target", service)
        self.assertNotIn("GEOFOX_PASSWORD=", service)


if __name__ == "__main__":
    unittest.main()
