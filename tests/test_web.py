import base64
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from hvv_display.geofox import HAMBURG_TZ
from hvv_display.models import Departure
from hvv_display.web import (
    WebApplication,
    hardware_status,
    hash_web_password,
    load_credentials,
    save_credentials,
    verify_web_password,
)


class WebApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.config = root / "config.json"
        self.config.write_text(
            (Path(__file__).parents[1] / "config.example.json").read_text(
                encoding="utf-8"
            ),
            encoding="utf-8",
        )
        self.credentials = root / "var" / "credentials.env"
        self.app = WebApplication(self.config, self.credentials, root / "stations.json")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_credentials_are_saved_securely_and_password_is_not_rendered(self) -> None:
        save_credentials(self.credentials, "application-id", "secret-value")
        self.assertEqual(
            load_credentials(self.credentials)["GEOFOX_USER"], "application-id"
        )
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(self.credentials.stat().st_mode), 0o600)
        settings = self.app.settings().decode("utf-8")
        self.assertIn("application-id", settings)
        self.assertNotIn("secret-value", settings)

    def test_credentials_reject_environment_file_record_injection(self) -> None:
        with self.assertRaisesRegex(ValueError, "keine Zeilenumbrüche"):
            save_credentials(self.credentials, "application-id", "secret\nHTTPS_PROXY=http://attacker")

    def test_settings_and_dashboard_include_csrf_tokens(self) -> None:
        settings = self.app.settings().decode("utf-8")
        dashboard = self.app.dashboard().decode("utf-8")
        self.assertIn(f'name="csrf_token" value="{self.app.csrf_token}"', settings)
        self.assertIn(f'name="csrf_token" value="{self.app.csrf_token}"', dashboard)
        self.assertIn('name="web_password"', settings)

    def test_web_password_is_saved_with_restricted_permissions_and_used_immediately(
        self,
    ) -> None:
        web_env = Path(self.directory.name) / "var" / "web.env"
        application = WebApplication(
            self.config,
            self.credentials,
            Path(self.directory.name),
            access_token=hash_web_password("hvv-anzeiger"),
            web_env_path=web_env,
        )
        application.save_web_password("new-password")
        self.assertEqual(application.access_token, "new-password")
        self.assertIn("HVV_WEB_PASSWORD_HASH=", web_env.read_text())
        self.assertTrue(verify_web_password("new-password", application.access_token))
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(web_env.stat().st_mode), 0o600)

    def test_remote_access_requires_a_bearer_token(self) -> None:
        with self.assertRaisesRegex(ValueError, "HVV_WEB_PASSWORD_HASH"):
            from hvv_display.web import run

            run(  # noqa: S104
                host="0.0.0.0",  # noqa: S104
                config=str(self.config),
                credentials=str(self.credentials),
            )

    def test_remote_access_accepts_browser_basic_auth_with_web_token(self) -> None:
        from hvv_display.web import WebApplication

        test_password = "test-web-password"  # noqa: S105
        application = WebApplication(
            self.config,
            self.credentials,
            Path(self.directory.name),
            access_token=hash_web_password(test_password),
        )
        header = "Basic " + base64.b64encode(
            f"hvv-anzeiger:{test_password}".encode()
        ).decode()
        self.assertTrue(application.authorize({"Authorization": header}))
        self.assertFalse(
            application.authorize({"Authorization": "Basic aHZ2LWFuemVpZ2VyOndyb25n"})
        )

    def test_settings_contains_every_config_section_and_explanations(self) -> None:
        settings = self.app.settings().decode("utf-8")
        for section in ("api", "display", "night_shutdown", "stations"):
            self.assertIn(section, settings)
        self.assertIn("Bedienbare Felder", settings)
        self.assertIn("Sekunden zwischen Abfragen", settings)

    def test_dashboard_contains_departures_hardware_status_and_restart_action(
        self,
    ) -> None:
        now = datetime.now(HAMBURG_TZ).replace(second=0, microsecond=0)
        departure = Departure(
            "21", "U Niendorf Nord", now + timedelta(minutes=4), station_label="R"
        )
        with patch.object(self.app, "departures", return_value=([{
            "line": departure.line,
            "destination": departure.destination,
            "station": departure.station_label,
            "time": departure.departure_time.strftime("%H:%M"),
            "minutes": 4,
            "delay_seconds": 0,
            "cancelled": False,
        }], None)), patch("hvv_display.web.hardware_status", return_value={
            "cpu": "12% Auslastung", "ram": "40% belegt", "storage": "80% frei"
        }):
            dashboard = self.app.dashboard().decode("utf-8")
        self.assertIn("U Niendorf Nord", dashboard)
        self.assertIn("12% Auslastung", dashboard)
        self.assertIn("System neu starten", dashboard)
        self.assertIn("/system/restart", dashboard)

    def test_restart_uses_non_interactive_sudo(self) -> None:
        result = type("Result", (), {"returncode": 0})()
        with patch("hvv_display.web.subprocess.run", return_value=result) as run:
            WebApplication.restart_system()
        run.assert_called_once_with(
            ["/usr/bin/sudo", "-n", "systemctl", "reboot"],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_hardware_status_has_expected_keys(self) -> None:
        self.assertEqual(set(hardware_status()), {"cpu", "ram", "storage"})

    def test_station_suggestions_use_geofox_candidates_without_exposing_credentials(
        self,
    ) -> None:
        candidates = [{
            "name": "Markt",
            "city": "Hamburg",
            "id": "Master:1",
            "combinedName": "Hamburg, Markt",
        }]
        with patch("hvv_display.web.GeofoxClient") as client_class:
            client_class.return_value.find_stations.return_value = candidates
            self.assertEqual(
                self.app.station_suggestions("Markt", "Hamburg"), candidates
            )
            client_class.return_value.find_stations.assert_called_once_with(
                "Markt", "Hamburg"
            )
        with self.assertRaisesRegex(ValueError, "mindestens zwei"):
            self.app.station_suggestions("M", "Hamburg")


if __name__ == "__main__":
    unittest.main()
