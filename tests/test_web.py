import base64
import errno
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hvv_display.geofox import HAMBURG_TZ
from hvv_display.models import Departure
from hvv_display.web import (
    WebApplication,
    _departure_payload,
    hardware_status,
    hash_web_password,
    load_credentials,
    make_handler,
    save_config,
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

    def test_config_save_falls_back_when_systemd_blocks_temporary_sibling(self) -> None:
        raw_config = {
            "api": {"base_url": "https://gti.geofox.de/gti/public/v1", "version": 63},
            "display": {"rotate": 2},
            "stations": [],
        }
        with patch(
            "hvv_display.web.tempfile.NamedTemporaryFile",
            side_effect=OSError(errno.EROFS, "Read-only file system"),
        ):
            save_config(self.config, raw_config)
        self.assertEqual(
            self.config.read_text(encoding="utf-8"),
            json.dumps(raw_config, ensure_ascii=False, indent=2) + "\n",
        )

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
        self.assertTrue(verify_web_password("new-password", application.access_token))
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

    def test_settings_exposes_one_global_time_display_configuration(self) -> None:
        settings = self.app.settings().decode("utf-8")
        self.assertIn('id="display.time_mode"', settings)
        self.assertIn('value="departure_time"', settings)
        self.assertIn('id="display.minute_unit"', settings)
        self.assertIn("syncTimeDisplayControls", settings)

    def test_settings_exposes_an_accessible_station_label_checkbox(self) -> None:
        settings = self.app.settings().decode("utf-8")
        self.assertIn('id="display.show_station_label"', settings)
        self.assertIn('type="checkbox"', settings)
        self.assertIn("Haltestellen-Label anzeigen", settings)
        self.assertIn("Bei mehreren Haltestellen", settings)
        self.assertIn("control.type==='checkbox'?control.checked", settings)

    def test_departure_payload_uses_the_shared_time_formatter(self) -> None:
        now = datetime(2026, 7, 27, 18, 35, tzinfo=HAMBURG_TZ)
        departure = Departure("21", "Ziel", now + timedelta(minutes=7, seconds=30))
        countdown = _departure_payload([departure], now, minute_unit="m")[0]
        clock = _departure_payload(
            [departure], now, time_mode="departure_time", minute_unit="none"
        )[0]
        self.assertEqual(countdown["display_time"], "8 m")
        self.assertEqual(countdown["minutes"], 8)
        self.assertEqual(clock["display_time"], "18:42")
        self.assertEqual(clock["time_mode"], "departure_time")

        hidden = _departure_payload(
            [departure], now, show_station_label=False
        )[0]
        self.assertEqual(hidden["station"], "")
        self.assertEqual(hidden["line"], departure.line)
        self.assertEqual(hidden["destination"], departure.destination)

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

    def test_dashboard_uses_shared_safe_line_style_and_escapes_line_text(self) -> None:
        with patch.object(
            self.app,
            "departures",
            return_value=(
                [
                    {
                        "line": "<script>alert(1)</script>",
                        "product": "unknown",
                        "station": "",
                        "destination": "Ziel",
                        "time": "12:04",
                        "minutes": 4,
                        "delay_seconds": 0,
                        "cancelled": False,
                    }
                ],
                None,
            ),
        ), patch(
            "hvv_display.web.hardware_status",
            return_value={"cpu": "", "ram": "", "storage": ""},
        ):
            dashboard = self.app.dashboard().decode("utf-8")
        self.assertIn("line-badge-neutral", dashboard)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", dashboard)
        self.assertNotIn("<script>alert(1)</script>", dashboard)

    def test_display_mode_is_reload_safe_responsive_and_read_only(self) -> None:
        with patch.object(
            self.app,
            "departures",
            return_value=(
                [
                    {
                        "line": "<script>alert(1)</script>",
                        "product": "bus",
                        "station": "R",
                        "destination": "Ziel <b>West</b>",
                        "time": "12:04",
                        "display_time": "in 4 min",
                        "minutes": 4,
                        "delay_seconds": 0,
                        "cancelled": False,
                    }
                ],
                None,
            ),
        ):
            display = self.app.display().decode("utf-8")
        self.assertIn('<body class="display-page">', display)
        self.assertIn('data-display-mode', display)
        self.assertIn('<meta http-equiv="refresh" content="15">', display)
        self.assertIn("line-badge-bus", display)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", display)
        self.assertIn("Ziel &lt;b&gt;West&lt;/b&gt;", display)
        self.assertNotIn("<script>alert(1)</script>", display)
        self.assertNotIn("/settings", display)
        self.assertNotIn("/system/restart", display)
        self.assertNotIn("csrf_token", display)

    def test_display_mode_distinguishes_error_and_empty_states(self) -> None:
        with patch.object(
            self.app, "departures", return_value=([], "Geofox ist nicht erreichbar")
        ):
            error_display = self.app.display().decode("utf-8")
        self.assertIn('class="notice"', error_display)
        self.assertIn('class="empty"', error_display)

        with patch.object(self.app, "departures", return_value=([], None)):
            empty_display = self.app.display().decode("utf-8")
        self.assertNotIn('class="notice"', empty_display)
        self.assertIn('class="empty"', empty_display)

    def test_display_route_requires_authentication_and_sets_security_headers(
        self,
    ) -> None:
        application = WebApplication(
            self.config,
            self.credentials,
            Path(self.directory.name),
            access_token=hash_web_password("test-web-password"),
        )
        with patch.object(application, "display", return_value=b"display"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(application))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with self.assertRaises(HTTPError) as denied:
                    urlopen(f"{base_url}/display")  # noqa: S310
                self.assertEqual(denied.exception.code, 401)

                auth = "Basic " + base64.b64encode(
                    b"hvv-anzeiger:test-web-password"
                ).decode()
                request = Request(  # noqa: S310
                    f"{base_url}/display", headers={"Authorization": auth}
                )
                with urlopen(request) as response:  # noqa: S310
                    self.assertEqual(response.read(), b"display")
                    self.assertEqual(
                        response.headers["Content-Security-Policy"],
                        "default-src 'none'; style-src 'unsafe-inline'; "
                        "script-src 'unsafe-inline'; img-src 'self' data:; "
                        "connect-src 'self'; base-uri 'none'; form-action 'self'; "
                        "frame-ancestors 'none'",
                    )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

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
