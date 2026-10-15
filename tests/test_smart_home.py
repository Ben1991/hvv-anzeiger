import base64
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from hvv_display.config import load_config
from hvv_display.geofox import HAMBURG_TZ, GeofoxError
from hvv_display.models import Departure
from hvv_display.smart_home import MAX_DISPLAY_BYTES, smart_home_payload
from hvv_display.web import (
    WebApplication,
    _departure_payload,
    hash_web_password,
    make_handler,
)

ROOT = Path(__file__).resolve().parents[1]


class SmartHomeTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.path = root / "config.json"
        self.raw = json.loads(
            (ROOT / "config.example.json").read_text(encoding="utf-8")
        )
        self.raw["night_shutdown"]["enabled"] = False
        self.write_config()
        self.config = load_config(self.path)
        self.now = datetime(2026, 10, 15, 12, 0, tzinfo=HAMBURG_TZ)
        self.app = WebApplication(self.path, root / "credentials", root / "stations")
        self.client = Mock()
        self.client.departure_list.return_value = self.departures()
        self.app._client = Mock(return_value=self.client)
        self.resolve = patch("hvv_display.web.resolve_stations", return_value=())
        self.resolve.start()
        self.addCleanup(self.resolve.stop)
        self.clock = patch("hvv_display.web.datetime")
        self.fake_clock = self.clock.start()
        self.fake_clock.now.return_value = self.now
        self.addCleanup(self.clock.stop)

    def write_config(self):
        self.path.write_text(json.dumps(self.raw), encoding="utf-8")

    def departures(self):
        return [
            Departure("U3", "Barmbek", self.now, station_label="W"),
            Departure(
                "S3",
                "Altona",
                self.now + timedelta(minutes=5),
                delay_seconds=120,
                cancelled=True,
            ),
        ]

    def test_real_cache_is_shared_by_web_and_multiple_displays(self):
        first = self.app.smart_home()
        self.app.departure_view()
        self.app.smart_home()
        self.assertEqual(self.client.departure_list.call_count, 1)
        self.assertEqual(first["state"], "ok")
        display = json.loads(first["display_payload"])
        self.assertEqual(display["schema_version"], 1)
        self.assertEqual(display["departures"][0]["background"], 0xF4C20D)
        self.assertEqual(first["departures"][0]["display_time"], "sofort")
        self.assertEqual(first["departures"][1]["display_time"], "AUS")
        self.assertEqual(display["departures"][1]["delay_seconds"], 120)
        self.assertEqual(display["valid_for_seconds"], 300)

    def test_failures_preserve_rows_then_expire_without_renewing_lease(self):
        self.app.smart_home()
        self.app._next_fetch = 0
        self.client.departure_list.side_effect = GeofoxError("secret internal error")
        self.fake_clock.now.return_value = self.now + timedelta(seconds=60)
        stale = self.app.smart_home()
        display = json.loads(stale["display_payload"])
        self.assertEqual(stale["state"], "stale")
        self.assertEqual(len(display["departures"]), 2)
        self.assertEqual(display["valid_for_seconds"], 240)
        self.assertNotIn("secret", json.dumps(stale))
        self.fake_clock.now.return_value = self.now + timedelta(seconds=300)
        expired = self.app.smart_home()
        self.assertEqual(expired["state"], "expired")
        self.assertEqual(expired["departures"], [])
        self.assertEqual(json.loads(expired["display_payload"])["departures"], [])
        self.assertEqual(self.client.departure_list.call_count, 2)

    def test_night_pauses_fetches_and_resumes_at_end(self):
        self.raw["night_shutdown"] = {"enabled": True, "start": "21:00", "end": "06:30"}
        self.write_config()
        self.fake_clock.now.return_value = self.now.replace(hour=23)
        night = self.app.smart_home()
        self.assertEqual(night["state"], "night")
        self.assertTrue(night["night_shutdown"])
        self.app._client.assert_not_called()
        self.fake_clock.now.return_value = self.now.replace(hour=6, minute=30)
        self.assertEqual(self.app.smart_home()["state"], "ok")
        self.app._client.assert_called_once()

    def test_invalid_config_and_no_initial_data_are_explicit(self):
        self.client.departure_list.side_effect = GeofoxError("no credentials")
        self.assertEqual(self.app.smart_home()["state"], "unavailable")
        self.path.write_text("{}", encoding="utf-8")
        payload = self.app.smart_home()
        self.assertEqual(payload["state"], "unavailable")
        self.assertEqual(payload["departures"], [])

    def test_empty_success_and_oversize_guard(self):
        self.client.departure_list.return_value = []
        empty = self.app.smart_home()
        self.assertEqual(empty["state"], "ok")
        self.assertEqual(empty["departures"], [])
        with patch("hvv_display.smart_home.MAX_DISPLAY_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "protocol limit"):
                self.app.smart_home()

    def test_protocol_limits_and_all_time_modes(self):
        for mode in ("countdown", "departure_time"):
            for unit in ("min", "m", "none"):
                self.raw["display"]["time_mode"] = mode
                self.raw["display"]["minute_unit"] = unit
                self.raw["display"]["show_station_label"] = False
                self.write_config()
                display = json.loads(self.app.smart_home()["display_payload"])
                self.assertEqual(display["time_mode"], mode)
                self.assertEqual(display["minute_unit"], unit)
                self.assertEqual(display["departures"][0]["station"], "")
        rows = _departure_payload(
            [Departure("界" * 200, "😀" * 200, self.now, station_label="😀" * 200)]
            * 50,
            self.now,
        )
        payload = smart_home_payload(
            {"departures": rows, "data_age_seconds": 0}, self.config, self.now
        )
        self.assertLessEqual(
            len(payload["display_payload"].encode()), MAX_DISPLAY_BYTES
        )
        self.assertEqual(len(json.loads(payload["display_payload"])["departures"]), 5)

    def test_http_transports_require_authentication_and_return_same_snapshot(self):
        self.app.access_token = hash_web_password("integration-test-password")
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        encoded = base64.b64encode(b"hvv-anzeiger:integration-test-password")
        auth = "Basic " + encoded.decode()
        results = []
        for route in ("/api/smart-home", "/api/esphome"):
            with self.assertRaises(HTTPError) as denied:
                urlopen(base + route)  # noqa: S310
            self.assertEqual(denied.exception.code, 401)
            req = Request(base + route, headers={"Authorization": auth})  # noqa: S310
            with urlopen(req) as response:  # noqa: S310
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                results.append(json.load(response))
        self.assertEqual(json.loads(results[0]["display_payload"]), results[1])
        self.assertEqual(self.client.departure_list.call_count, 1)
