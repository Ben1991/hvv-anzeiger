import base64
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hvv_display.freshness import departures_for_display
from hvv_display.geofox import HAMBURG_TZ, GeofoxError
from hvv_display.models import Departure
from hvv_display.web import WebApplication, hash_web_password, make_handler


class KioskTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / "config.json"
        self.raw = json.loads(Path("config.example.json").read_text())
        self.raw["api"].update(refresh_seconds=15, max_stale_age_minutes=1)
        self.config.write_text(json.dumps(self.raw), encoding="utf-8")
        self.app = WebApplication(
            self.config, self.root / "credentials.env", self.root / "stations.json"
        )
        self.now = datetime(2026, 10, 12, 12, 0, tzinfo=HAMBURG_TZ)
        self.departure = Departure(
            "U2",
            "Sehr langes Ziel",
            self.now + timedelta(minutes=4),
            delay_seconds=90,
            station_label="Station",
        )
        self.client = Mock()
        self.client.departure_list.return_value = [self.departure]
        self.clock = self.enterContext(patch("hvv_display.web.datetime"))
        self.clock.now.return_value = self.now
        self.monotonic = self.enterContext(
            patch("hvv_display.web.time.monotonic", return_value=0)
        )
        self.enterContext(patch.object(self.app, "_client", return_value=self.client))
        self.enterContext(patch("hvv_display.web.resolve_stations", return_value=[]))

    def advance(self, seconds):
        self.clock.now.return_value = self.now + timedelta(seconds=seconds)
        self.monotonic.return_value = seconds

    def test_shared_web_snapshot_limits_fetches_and_regenerates_time(self):
        initial = self.app.departure_view()
        self.assertEqual(initial["data_age_seconds"], 0)
        self.assertIn('datetime="2026-10-12T12:04:00+02:00"', initial["board_html"])
        self.assertIn("Verspätung: +2 min", initial["board_html"])
        self.app.dashboard()
        self.app.display()
        self.assertEqual(self.client.departure_list.call_count, 1)
        self.advance(15)
        self.app.departure_view()
        self.assertEqual(self.client.departure_list.call_count, 2)

    def test_failure_keeps_last_success_and_expires_with_hardware_rule(self):
        self.app.departure_view()
        self.client.departure_list.side_effect = GeofoxError(
            "secret password must not leak"
        )
        self.advance(15)
        failed = self.app.departure_view()
        self.assertTrue(failed["stale"])
        self.assertEqual(failed["retry_in_seconds"], 30)
        self.assertEqual(failed["departures"][0]["line"], "U2")
        self.assertNotIn("secret", json.dumps(failed))
        self.advance(20)
        self.app.departure_view()
        self.assertEqual(self.client.departure_list.call_count, 2)
        self.advance(60)
        expired = self.app.departure_view()
        self.assertEqual(expired["departures"], [])
        self.assertTrue(expired["expired"])
        self.assertIsNotNone(expired["last_updated"])
        self.assertEqual(
            departures_for_display(
                [self.departure],
                now=self.now + timedelta(seconds=60),
                last_updated=self.now,
                stale=True,
                max_stale_age_minutes=1,
            ),
            [],
        )
        self.client.departure_list.side_effect = None
        self.advance(121)
        self.assertFalse(self.app.departure_view()["stale"])

    def test_rate_limit_wait_is_shared_and_cannot_be_bypassed_by_reload(self):
        self.client.departure_list.side_effect = GeofoxError(
            "limited", http_status=429, retry_after_seconds=600
        )
        self.assertEqual(self.app.departure_view()["retry_in_seconds"], 600)
        self.advance(300)
        self.app.display()
        self.app.dashboard()
        self.assertEqual(self.client.departure_list.call_count, 1)

    def test_changed_configuration_does_not_show_previous_station_snapshot(self):
        self.app.departure_view()
        self.raw["stations"][0]["name"] = "Andere Station"
        self.config.write_text(json.dumps(self.raw), encoding="utf-8")
        self.client.departure_list.side_effect = OSError("secret file path")
        view = self.app.departure_view()
        self.assertEqual(view["departures"], [])
        self.assertIsNone(view["last_updated"])
        self.assertNotIn("secret", json.dumps(view))
        self.config.write_text("invalid", encoding="utf-8")
        self.assertIn("Konfiguration", self.app.departure_view()["state"])

    def test_simultaneous_readers_share_one_fetch_and_independent_payloads(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            views = list(pool.map(lambda _: self.app.departure_view(), range(8)))
        self.assertEqual(self.client.departure_list.call_count, 1)
        views[0]["departures"][0]["line"] = "changed"
        self.assertEqual(views[1]["departures"][0]["line"], "U2")

    def test_cancelled_and_malicious_text_is_semantic_and_escaped(self):
        self.client.departure_list.return_value = [
            Departure("<script>x</script>", "<b>Ziel</b>", self.now, cancelled=True)
        ]
        html = self.app.display().decode()
        self.assertIn('<ul class="departure-list">', html)
        self.assertIn("Ausfall", html)
        self.assertIn("&lt;b&gt;Ziel&lt;/b&gt;", html)
        self.assertNotIn("<script>x</script>", html)
        self.assertNotIn('http-equiv="refresh"', html)
        self.assertEqual(html.count('aria-live="polite"'), 1)
        self.assertNotIn("localStorage", html)
        self.assertNotIn("/settings", html)

    def test_display_fragment_requires_same_authentication_as_display(self):
        self.app.access_token = hash_web_password("kiosk-test-password")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            for path in ("/display", "/api/display", "/api/departures"):
                url = f"http://127.0.0.1:{server.server_port}{path}"
                with self.assertRaises(HTTPError) as refused:
                    urlopen(url)  # noqa: S310
                self.assertEqual(refused.exception.code, 401)
                token = base64.b64encode(b"hvv-anzeiger:kiosk-test-password").decode()
                with urlopen(
                    Request(url, headers={"Authorization": "Basic " + token})
                ) as response:  # noqa: S310
                    self.assertEqual(response.status, 200)
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
