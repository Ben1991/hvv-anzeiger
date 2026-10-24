"""Web input boundaries, HTTP contracts and recoverable failures."""

# ruff: noqa: S105, S106 - synthetic credentials used only in isolated tests

import base64
import io
import json
import sys
import unittest
from http.client import HTTPConnection
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hvv_display import web
from hvv_display.config import ConfigError
from hvv_display.geofox import GeofoxError


class WebBoundariesTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.config = self.root / "config.json"
        self.config.write_bytes(Path("config.example.json").read_bytes())
        self.raw = json.loads(self.config.read_bytes())
        self.app = web.WebApplication(
            self.config,
            self.root / "credentials.env",
            self.root / "stations.json",
            web_env_path=self.root / "web.env",
        )

    def start_server(self):
        server = web.WebServer(("127.0.0.1", 0), web.make_handler(self.app))
        thread = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()

        def stop():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

        self.addCleanup(stop)
        self.port = server.server_port

    def request(self, path, values=None, *, body=None, headers=None):
        from urllib.parse import urlencode

        if values is not None:
            body = urlencode(values)
        connection = HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request(
                "POST" if body is not None else "GET",
                path,
                body=body,
                headers=headers or {},
            )
            response = connection.getresponse()
            return response.status, response.read(), dict(response.headers)
        finally:
            connection.close()

    def test_validation_messages_identify_the_affected_controls(self):
        for message, expected in (
            ("Anwendungs-ID fehlt", {"user", "password"}),
            ("Webpasswort fehlt", {"web_password"}),
            ("api.version ungültig", {"api.version"}),
            ("Haltestelle 0 ungültig", set()),
            ("Haltestelle 2 ungültig", {"stations[1]"}),
            ("Haltestelle 2 Linie fehlt", {"stations[1]", "stations[1].routes"}),
        ):
            with self.subTest(message=message):
                self.assertEqual(set(web._settings_field_errors(message)), expected)

    def test_malformed_auth_and_password_records_are_rejected(self):
        for encoded in ("broken", "pbkdf2-sha256$invalid$YQ==$YQ=="):
            self.assertFalse(web.verify_web_password("password", encoded))
        self.app.access_token = "unused"
        for value in ("!", base64.b64encode(b"\xff").decode(), "bm9jb2xvbg=="):
            self.assertFalse(self.app.authorize({"Authorization": "Basic " + value}))
        for password in ("", "a\nb", 'a"b'):
            with self.assertRaises(ValueError):
                self.app.save_web_password(password)
        for user, password in (("", "x"), ("x", "")):
            with self.assertRaises(ValueError):
                web.save_credentials(self.app.credentials_path, user, password)
        with patch.object(Path, "replace", side_effect=OSError("disk failed")):
            with self.assertRaises(OSError):
                web.save_credentials(self.app.credentials_path, "user", "password")
        self.assertEqual(list(self.root.glob(".credentials.env.*")), [])

    def test_raw_config_and_reboot_failures(self):
        self.assertEqual(self.app.raw_config(), self.raw)
        self.config.write_text("[]")
        with self.assertRaises(ConfigError):
            self.app.raw_config()
        with patch.object(
            web.subprocess, "run", return_value=SimpleNamespace(returncode=1)
        ):
            with self.assertRaisesRegex(OSError, "abgelehnt"):
                self.app.restart_system()

    def test_hardware_failures_and_malformed_delay_have_safe_fallbacks(self):
        with (
            patch.object(web.os, "cpu_count", return_value=None),
            patch.object(web.os, "getloadavg", side_effect=OSError, create=True),
            patch.object(Path, "read_text", side_effect=OSError),
            patch.object(web.shutil, "disk_usage", side_effect=OSError),
        ):
            self.assertEqual(set(web.hardware_status().values()), {"nicht verfügbar"})
        with (
            patch.object(web.os, "getloadavg", return_value=(1, 0, 0), create=True),
            patch.object(
                Path,
                "read_text",
                return_value="MemTotal: 2048 kB\nOther: 1\nMemAvailable: 1024 kB",
            ),
        ):
            self.assertIn("50%", web.hardware_status()["ram"])
        rows = web._departure_rows([{"line": "5", "delay_seconds": "invalid"}])
        self.assertNotIn("Verspätung:", rows)

    def test_service_clock_and_night_notices(self):
        with (
            patch.object(self.app, "departures", return_value=([], None)),
            patch.object(
                self.app,
                "health",
                return_value={
                    "snapshot_available": True,
                    "night_shutdown": True,
                    "clock_synchronized": None,
                },
            ),
        ):
            self.assertIn(
                "Gerätezeit nicht bestätigt", self.app.departure_view()["state"]
            )
        with (
            patch.object(self.app, "departures", return_value=([], None)),
            patch.object(
                self.app,
                "health",
                return_value={
                    "snapshot_available": True,
                    "night_shutdown": False,
                    "clock_synchronized": True,
                },
            ),
        ):
            self.assertEqual(self.app.departure_view()["state"], "Daten aktuell.")

    def test_departure_source_tracks_credentials_file_changes(self):
        client = Mock()
        client.departure_list.return_value = []
        with (
            patch.object(self.app, "_client", return_value=client),
            patch.object(web, "resolve_stations", return_value=[]),
        ):
            self.assertEqual(self.app.departures()[0], [])
            self.app.credentials_path.write_text("GEOFOX_USER=user\n")
            self.assertEqual(self.app.departures()[0], [])
        self.assertEqual(client.departure_list.call_count, 2)

    def test_station_identifiers_are_checked_before_requests(self):
        for value in ("", "x" * 161, "a\nb"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    self.app.line_suggestions(value)
                with self.assertRaises(ValueError):
                    self.app.line_route_suggestions(value, "line")
        with self.assertRaises(ValueError):
            self.app.line_station_suggestions("station", "line", "x" * 121)
        with patch.object(self.app, "_client") as client:
            client.return_value.list_lines.return_value = []
            for method in (
                self.app.line_route_suggestions,
                self.app.line_station_suggestions,
            ):
                self.app._line_catalog = None
                for _ in range(2):
                    with self.assertRaisesRegex(ValueError, "nicht verfügbar"):
                        method("station", "line")

    def test_station_config_rejects_missing_and_wrong_structures(self):
        with patch.object(self.app, "_client") as client:
            client.return_value.find_stations.return_value = [
                {"id": "s", "name": "Station", "city": "Hamburg"},
            ]
            cases = [
                None,
                [],
                [None],
                [{"name": "x" * 121, "id": "s"}],
                [{"name": "Station", "id": "s", "routes": []}],
                [{"name": "Station", "id": "s", "routes": [None]}],
            ]
            for stations in cases:
                with self.subTest(stations=stations):
                    with self.assertRaises(ValueError):
                        self.app.validate_station_config(
                            {"stations": stations}, user="u", password="p"
                        )

    def test_direction_and_destination_filters_are_resolved_and_validated(self):
        option = SimpleNamespace(line_id="l", name="5", product="BUS")
        route = SimpleNamespace(
            station_ids=("a", "b"),
            label="Richtung B",
            stations=(("a", "A"), ("b", "B")),
        )
        with (
            patch.object(self.app, "_client") as client,
            patch.object(web, "line_options_for_station", return_value=[option]),
            patch.object(web, "line_route_options_for_station", return_value=[route]),
        ):
            client.return_value.find_stations.return_value = [
                {"id": "s", "name": "S", "city": "Hamburg"}
            ]
            base = {
                "line_id": "l",
                "filter_mode": "direction",
                "filter_station_ids": ["a", "b"],
            }

            def validate(routes):
                return self.app.validate_station_config(
                    {"stations": [{"name": "S", "id": "s", "routes": routes}]},
                    user="u",
                    password="p",
                )

            self.assertEqual(
                validate([base.copy()])["stations"][0]["routes"][0]["destination"],
                "Richtung B",
            )
            self.assertEqual(
                len(
                    validate([base.copy(), {"line": "manual"}])["stations"][0]["routes"]
                ),
                2,
            )
            for changed in (
                {"filter_mode": "invalid"},
                {"filter_station_ids": []},
                {"filter_station_ids": ["unknown"]},
                {"filter_mode": "destination"},
                {"filter_mode": "destination", "filter_station_ids": ["unknown"]},
            ):
                with self.subTest(changed=changed):
                    with self.assertRaises(ValueError):
                        validate([base | changed])
            with self.assertRaisesRegex(ValueError, "Filter benötigt"):
                validate([base.copy(), {"filter_mode": "direction"}])

    def test_preview_formats_optional_boolean_and_indexed_values(self):
        preview = {
            "current_invalid": True,
            "changes": [
                {"field": "stations[0].id", "before": None, "after": "x"},
                {"field": "display.bgr", "before": False, "after": True},
            ],
        }
        page = self.app.config_preview_page("token", preview).decode()
        for value in ("Nicht gesetzt", "Ja", "Nein", "Haltestellen → 1", "beschädigt"):
            self.assertIn(value, page)

    def test_thread_start_failure_releases_capacity(self):
        server = web.WebServer(
            ("127.0.0.1", 0), web.make_handler(self.app), max_workers=1
        )
        self.addCleanup(server.server_close)
        with patch(
            "http.server.ThreadingHTTPServer.process_request", side_effect=RuntimeError
        ):
            with self.assertRaises(RuntimeError):
                server.process_request(Mock(), ("127.0.0.1", 1))
        self.assertTrue(server._workers.acquire(blocking=False))
        server._workers.release()

    def test_form_size_and_legacy_encoding_boundaries(self):
        handler = object.__new__(web.make_handler(self.app))
        for value, error in (
            ("bad", ValueError),
            ("-1", ValueError),
            ("11", OverflowError),
        ):
            handler.headers = {"Content-Length": value}
            with self.assertRaises(error):
                handler._form_values(10)
        handler.headers = {"Content-Length": "3"}
        handler.rfile = io.BytesIO(b"x=\xff")
        self.assertEqual(handler._form_values(10), {"x": ["ÿ"]})

    def test_suggestion_routes_return_success_and_classified_failures(self):
        self.start_server()
        for path, method, key in (
            ("/api/stations?q=Station", "station_suggestions", "stations"),
            ("/api/lines?station_id=s", "line_suggestions", "lines"),
            (
                "/api/line-routes?station_id=s&line_id=l",
                "line_route_suggestions",
                "routes",
            ),
            (
                "/api/line-stations?station_id=s&line_id=l",
                "line_station_suggestions",
                "stations",
            ),
        ):
            with self.subTest(path=path):
                with patch.object(self.app, method, return_value=[{"id": "safe"}]):
                    status, body, _ = self.request(path)
                    self.assertEqual(status, 200)
                    self.assertEqual(json.loads(body)[key], [{"id": "safe"}])
                for error, expected in (
                    (ValueError("invalid"), 400),
                    (
                        GeofoxError("limited", http_status=429, retry_after_seconds=7),
                        429,
                    ),
                    (GeofoxError("auth", http_status=401), 502),
                    (GeofoxError("temporary", kind="temporary"), 503),
                    (GeofoxError("server", http_status=500), 503),
                    (GeofoxError("invalid"), 400),
                ):
                    with patch.object(self.app, method, side_effect=error):
                        status, body, headers = self.request(path)
                        self.assertEqual(status, expected)
                        self.assertEqual(json.loads(body)[key], [])
                        if expected == 429:
                            self.assertEqual(headers["Retry-After"], "7")

    def test_page_routes_and_unknown_paths(self):
        self.start_server()
        with patch.object(
            self.app,
            "departure_view",
            return_value={"departures": [], "board_html": "safe"},
        ):
            for path in ("/api/departures", "/api/display"):
                self.assertEqual(self.request(path)[0], 200)
        for path in ("/settings", "/settings?saved=1", "/config-backup?saved=1"):
            self.assertEqual(self.request(path)[0], 200)
        with patch.object(self.app, "dashboard", return_value=b"dashboard"):
            self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/unknown")[0], 404)
        self.assertEqual(self.request("/unknown", {})[0], 404)

    def test_config_preview_rejects_neither_or_both_sources(self):
        self.start_server()
        values = {"csrf_token": self.app.csrf_token}
        self.assertEqual(self.request("/config/preview", values)[0], 400)
        both = values | {"backup_id": "backup.json", "config_data": "{}"}
        self.assertEqual(self.request("/config/preview", both)[0], 400)

    def test_restart_http_success_failure_size_and_csrf(self):
        self.start_server()
        with patch.object(self.app, "restart_system") as restart:
            self.assertEqual(
                self.request("/system/restart", {"csrf_token": self.app.csrf_token})[0],
                200,
            )
            restart.assert_called_once_with()
        with patch.object(self.app, "restart_system", side_effect=OSError("denied")):
            self.assertEqual(
                self.request("/system/restart", {"csrf_token": self.app.csrf_token})[0],
                403,
            )
        self.assertEqual(self.request("/system/restart", {})[0], 403)
        self.assertEqual(self.request("/system/restart", body="x" * 4097)[0], 413)

    def test_settings_http_preserves_credentials_and_reports_failures(self):
        self.start_server()
        values = {
            "csrf_token": self.app.csrf_token,
            "config_json": json.dumps(self.raw),
            "user": "u",
            "password": "p",
        }
        with patch.object(
            self.app, "validate_station_config", side_effect=lambda raw, **kwargs: raw
        ):
            self.assertEqual(self.request("/settings", values)[0], 303)
            self.assertIn("GEOFOX_PASSWORD=p", self.app.credentials_path.read_text())
            values["password"] = ""
            self.assertEqual(self.request("/settings", values)[0], 303)
            values["user"] = "changed"
            self.assertEqual(self.request("/settings", values)[0], 303)
            self.assertIn("GEOFOX_USER=changed", self.app.credentials_path.read_text())
            with patch.object(self.app, "save_web_password") as save:
                self.assertEqual(
                    self.request("/settings", values | {"web_password": "new"})[0], 303
                )
                save.assert_called_once_with("new")
            for override in (
                {"config_json": "[]"},
                {"config_json": "invalid"},
                {"csrf_token": "bad"},
            ):
                self.assertEqual(self.request("/settings", values | override)[0], 400)
            self.assertEqual(
                self.request("/settings", values | {"config_revision": "stale"})[0], 409
            )
        with patch.object(
            self.app,
            "validate_station_config",
            side_effect=GeofoxError("limited", http_status=429),
        ):
            self.assertEqual(self.request("/settings", values)[0], 429)
        self.assertEqual(
            self.request("/settings", body="x" * (web.MAX_FORM_BYTES + 1))[0], 413
        )

    def test_run_closes_server_for_normal_and_interrupted_shutdown(self):
        for tls, interruption in ((False, None), (True, KeyboardInterrupt)):
            with (
                patch.object(web, "WebServer") as server,
                patch.object(web.ssl, "SSLContext") as context,
            ):
                server.return_value.serve_forever.side_effect = interruption
                web.run(
                    "127.0.0.1",
                    0,
                    tls_certfile="cert" if tls else None,
                    tls_keyfile="key" if tls else None,
                )
                server.return_value.server_close.assert_called_once_with()
                if tls:
                    context.return_value.load_cert_chain.assert_called_once_with(
                        "cert", "key"
                    )
        with self.assertRaisesRegex(ValueError, "gemeinsam"):
            web.run(tls_certfile="cert")

    def test_cli_passes_arguments_to_server(self):
        with (
            patch.object(sys, "argv", ["hvv-web", "--port", "1234"]),
            patch.object(web, "run") as run,
        ):
            web.main()
        self.assertEqual(run.call_args.args[1], 1234)


if __name__ == "__main__":
    unittest.main()
