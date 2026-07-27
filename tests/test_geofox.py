import base64
import hashlib
import hmac
import unittest
from datetime import datetime

from hvv_display.geofox import HAMBURG_TZ, GeofoxClient, normalize, route_matches
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

    def test_departures_are_filtered_and_sorted(self) -> None:
        response = FakeResponse(
            b'{"returnCode":"OK","departures":['
            b'{"line":{"name":"186","direction":"S Othmarschen"},'
            b'"timeOffset":9,"delay":120},'
            b'{"line":{"name":"1","direction":"Anderswo"},"timeOffset":2},'
            b'{"line":{"name":"21","direction":"U Niendorf Nord"},'
            b'"station":{"id":"Master:2"},"timeOffset":4},'
            b'{"line":{"name":"21","direction":"U Niendorf Nord"},'
            b'"station":{"id":"Master:1"},"timeOffset":1}'
            b"]}"
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
            b'{"returnCode":"OK","departures":['
            b'{"line":{"name":"21","direction":"U Niendorf Nord"},'
            b'"timeOffset":60}]}'
        )
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: response,
        )
        station = Station(
            "Recknitzstraße",
            "Hamburg",
            (Route("21", "U Niendorf Nord"),),
            "Master:2",
        )
        now = datetime(2026, 3, 29, 1, 30, tzinfo=HAMBURG_TZ)

        result = client.departure_list((station,), now=now)

        self.assertEqual(result[0].departure_time.strftime("%H:%M %z"), "03:30 +0200")


if __name__ == "__main__":
    unittest.main()
