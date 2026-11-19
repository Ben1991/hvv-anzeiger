"""Keep the Pi service and ESP32 firmware installation paths independent."""

import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]


class PlatformIsolationTest(unittest.TestCase):
    def test_pi_installer_never_copies_or_rewrites_esphome_state(self):
        installer = (ROOT / "install.sh").read_text(encoding="utf-8")
        update = (ROOT / "update.sh").read_text(encoding="utf-8")

        for script in (installer, update):
            self.assertNotIn('"$SOURCE_DIR/esphome"', script)
            self.assertNotIn('"$SCRIPT_DIR/esphome"', script)
        self.assertIn('"$SOURCE_DIR/hvv_display"', installer)
        self.assertIn('"$SOURCE_DIR/systemd"', installer)

    def test_esp32_setup_only_targets_local_esphome_files(self):
        setup = (ROOT / "scripts" / "setup-esphome.ps1").read_text(encoding="utf-8")

        self.assertIn(
            "$secretFile = Join-Path $repoRoot 'esphome\\secrets.yaml'", setup
        )
        self.assertIn(
            '$localProfile = Join-Path $repoRoot "esphome\\$BoardProfile.local.yaml"',
            setup,
        )
        for pi_only_operation in ("systemctl", "/opt/hvv-anzeiger", "install.sh"):
            self.assertNotIn(pi_only_operation, setup)

    def test_firmware_protocol_snapshot_comes_from_shared_backend_payload(self):
        snapshot_source = (ROOT / "tests" / "firmware" / "make_snapshot.py").read_text(
            encoding="utf-8"
        )
        board_source = (ROOT / "esphome" / "hvv_board.h").read_text(encoding="utf-8")

        self.assertIn("smart_home_payload", snapshot_source)
        self.assertIn('"display_payload"', snapshot_source)
        self.assertIn("schema_version", board_source)
        self.assertIn('root["time_mode"]', board_source)
        self.assertIn('item["departure_epoch"]', board_source)

    def test_cyd_profiles_keep_the_same_landscape_rotation(self):
        for profile in ("hvv-cyd.yaml", "hvv-cyd-ha.yaml"):
            with self.subTest(profile=profile):
                source = (ROOT / "esphome" / profile).read_text(encoding="utf-8")
                self.assertIn("display_rotation: '90'", source)


if __name__ == "__main__":
    unittest.main()
