import base64
import hashlib
import hmac
import unittest
import urllib.error
from datetime import datetime
from unittest.mock import patch

from hvv_display.geofox import (
    HAMBURG_TZ,
    GeofoxClient,
    GeofoxError,
    normalize,
    route_matches,
)
from hvv_display.models import Route, Station


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]


class GeofoxClientTest(unittest.TestCase):
    def setUp(self) -> None:
        GeofoxClient._global_last_request_at = 0.0
        GeofoxClient._global_retry_until = 0.0

    def test_signature_is_hmac_sha1_base64_of_exact_body(self) -> None:
        client = GeofoxClient("https://example.test", "user", "secret")
        body = client.encode_body({"version": 63, "name": "Straße"})
        expected = base64.b64encode(
            hmac.new(b"secret", body, hashlib.sha1).digest()
        ).decode("ascii")
        self.assertEqual(client.signature(body), expected)
        self.assertIn("Straße".encode(), body)

    def test_route_matching_handles_spelling_variants(self) -> None:
        routes = (Route("384", "Elbgaustrasse"),)
        self.assertTrue(route_matches("384", "S Elbgaustraße", routes))
        self.assertFalse(route_matches("184", "S Elbgaustraße", routes))
        self.assertEqual(normalize("Recknitzstraße"), "recknitzstrasse")

    def test_find_stations_returns_service_types_for_follow_up_flow(self) -> None:
        response = FakeResponse(
            b'{"returnCode":"OK","results":[{"type":"STATION","id":"Master:1",'
            b'"name":"Jungfernstieg","city":"Hamburg","combinedName":"Hamburg, '
            b'Jungfernstieg",'
            b'"serviceTypes":["BUS","UBAHN","SBAHN"]}]}'
        )
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: response,
        )
        result = client.find_stations("Jungfernstieg", "Hamburg")
        self.assertEqual(result[0]["id"], "Master:1")
        self.assertEqual(result[0]["serviceTypes"], ["BUS", "UBAHN", "SBAHN"])

    def test_http_200_with_geofox_error_is_not_success(self) -> None:
        response = FakeResponse(
            b'{"returnCode":"ERROR_CN_TOO_MANY","errorDevInfo":"internal stack"}'
        )
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: response,
        )
        with self.assertRaises(GeofoxError) as raised:
            client.find_stations("Ha", "Hamburg")
        self.assertEqual(raised.exception.return_code, "ERROR_CN_TOO_MANY")
        self.assertEqual(raised.exception.kind, "validation")
        self.assertNotIn("internal stack", str(raised.exception))

    def test_error_text_is_sanitized_and_dev_info_is_hidden(self) -> None:
        response = FakeResponse(
            b'{"returnCode":"ERROR_TEXT","errorText":"Ung\u00fcltig\\n'
            b'bitte pr\u00fcfen",'
            b'"errorDevInfo":"secret internal details"}'
        )
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: response,
        )
        with self.assertRaises(GeofoxError) as raised:
            client.find_stations("Test", "Hamburg")
        self.assertNotIn("secret internal details", str(raised.exception))
        self.assertNotIn("\n", str(raised.exception))

    def test_429_exposes_retry_after_and_updates_global_backoff(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.test", 429, "Too Many", {"Retry-After": "3"}, None
        )
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
        )
        with self.assertRaises(GeofoxError) as raised:
            client.find_stations("Test", "Hamburg")
        self.assertEqual(raised.exception.retry_after_seconds, 3)
        self.assertEqual(raised.exception.http_status, 429)
        self.assertGreater(GeofoxClient._global_retry_until, 0)

    def test_rate_limit_is_shared_across_client_instances(self) -> None:
        response = FakeResponse(b'{"returnCode":"OK","results":[]}')
        first = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=1.05,
            urlopen=lambda *_args, **_kwargs: response,
        )
        second = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=1.05,
            urlopen=lambda *_args, **_kwargs: response,
        )
        with (
            patch("hvv_display.geofox.time.sleep") as sleep,
            patch(
                "hvv_display.geofox.time.monotonic",
                side_effect=[10.0, 10.0, 10.2, 11.25],
            ),
        ):
            first.find_stations("Test", "Hamburg")
            second.find_stations("Test", "Hamburg")
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], 0.85, places=2)

    def test_departures_are_filtered_and_sorted(self) -> None:
        response = FakeResponse(
            b'{"returnCode":"OK","departures":['
            b'{"line":{"name":"186","direction":"S Othmarschen"},'
            b'"timeOffset":9,"delay":120},'
            b'{"line":{"name":"1","direction":"Anderswo"},"timeOffset":2},'
            b'{"line":{"name":"21","direction":"U Niendorf Nord"},'
            b'"station":{"id":"Master:2"},"timeOffset":4},'
            b'{"line":{"name":"21","direction":"U Niendorf Nord"},'
            b'"station":{"id":"Master:1"},"timeOffset":1}]}'
        )
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: response,
        )
        stations = (
            Station(
                "Weistritzstraße",
                "Hamburg",
                (Route("186", "S Othmarschen"),),
                "Master:1",
            ),
            Station(
                "Recknitzstraße",
                "Hamburg",
                (Route("21", "U Niendorf Nord"),),
                "Master:2",
            ),
        )
        now = datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ)
        result = client.departure_list(stations, now=now)
        self.assertEqual([departure.line for departure in result], ["21", "186"])
        self.assertEqual(result[0].departure_time.strftime("%H:%M"), "12:04")
        self.assertEqual(result[1].departure_time.strftime("%H:%M"), "12:11")

    def test_offset_uses_real_minutes_across_daylight_saving_change(self) -> None:
        response = FakeResponse(
            b'{"returnCode":"OK","departures":[{"line":{"name":"21",'
            b'"direction":"U Niendorf Nord"},"timeOffset":60}]}'
        )
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: response,
        )
        station = Station(
            "Recknitzstraße", "Hamburg", (Route("21", "U Niendorf Nord"),), "Master:2"
        )
        now = datetime(2026, 3, 29, 1, 30, tzinfo=HAMBURG_TZ)
        result = client.departure_list((station,), now=now)
        self.assertEqual(result[0].departure_time.strftime("%H:%M %z"), "03:30 +0200")


if __name__ == "__main__":
    unittest.main()
