import io
import unittest
import urllib.error
from datetime import datetime
from unittest.mock import patch

from hvv_display.geofox import (
    HAMBURG_TZ,
    MAX_RESPONSE_BYTES,
    GeofoxClient,
    GeofoxError,
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


class GeofoxErrorTest(unittest.TestCase):
    def client_for(self, response: bytes) -> GeofoxClient:
        return GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: FakeResponse(response),
        )

    def test_credentials_are_required(self) -> None:
        with self.assertRaisesRegex(GeofoxError, "GEOFOX_USER"):
            GeofoxClient("https://example.test", "", "")

    def test_http_401_has_safe_message(self) -> None:
        error = urllib.error.HTTPError(
            "https://example.test/departureList",
            401,
            "Unauthorized",
            {},
            io.BytesIO(b'{"errorDevInfo":"secret backend details"}'),
        )
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
        )

        with self.assertRaisesRegex(GeofoxError, "Zugangsdaten wurden abgelehnt"):
            client._post("departureList", {})

    def test_http_rate_limit_and_server_errors_have_safe_messages(self) -> None:
        cases = ((429, "Anfragelimit"), (503, "HTTP 503"))
        for code, message in cases:
            with self.subTest(code=code):
                error = urllib.error.HTTPError(
                    "https://example.test/departureList",
                    code,
                    "Error",
                    {},
                    io.BytesIO(b"backend details"),
                )
                client = GeofoxClient(
                    "https://example.test",
                    "user",
                    "secret",
                    min_request_interval=0,
                    urlopen=lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
                )
                with self.assertRaisesRegex(GeofoxError, message):
                    client._post("departureList", {})

    def test_network_errors_have_safe_message(self) -> None:
        client = GeofoxClient(
            "https://example.test",
            "user",
            "secret",
            min_request_interval=0,
            urlopen=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                urllib.error.URLError("offline")
            ),
        )
        with self.assertRaisesRegex(GeofoxError, "nicht erreichbar"):
            client._post("departureList", {})

    def test_rate_limit_waits_only_for_remaining_interval(self) -> None:
        client = self.client_for(b'{"returnCode":"OK"}')
        client.min_request_interval = 1.0
        client._last_request_at = 10.0
        with (
            patch("hvv_display.geofox.time.monotonic", side_effect=[10.25, 11.25]),
            patch("hvv_display.geofox.time.sleep") as sleep,
        ):
            client._wait_for_rate_limit()
        sleep.assert_called_once_with(0.75)
        self.assertEqual(client._last_request_at, 11.25)

    def test_api_error_uses_user_message(self) -> None:
        client = self.client_for(
            b'{"returnCode":"ERROR_TEXT","errorText":"Haltestelle ung\\u00fcltig",'
            b'"errorDevInfo":"internal"}'
        )
        with self.assertRaisesRegex(GeofoxError, "Haltestelle ungültig"):
            client._post("departureList", {})

    def test_invalid_json_is_rejected(self) -> None:
        client = self.client_for(b"<html>not json</html>")
        with self.assertRaisesRegex(GeofoxError, "ungültige Antwort"):
            client._post("departureList", {})

    def test_non_object_json_is_rejected(self) -> None:
        client = self.client_for(b"[]")
        with self.assertRaisesRegex(GeofoxError, "kein Antwortobjekt"):
            client._post("departureList", {})

    def test_oversized_response_is_rejected_before_json_parsing(self) -> None:
        client = self.client_for(b"x" * (MAX_RESPONSE_BYTES + 1))
        with self.assertRaisesRegex(GeofoxError, "zu große Antwort"):
            client._post("departureList", {})

    def test_invalid_departure_collection_is_rejected(self) -> None:
        client = self.client_for(
            b'{"returnCode":"OK","departures":{"unexpected":"object"}}'
        )
        station = Station(
            "Test",
            "Hamburg",
            (Route("1", "Ziel"),),
            "Master:1",
            "T",
        )
        with self.assertRaisesRegex(GeofoxError, "Abfahrtsliste"):
            client.departure_list((station,))

    def test_station_search_rejects_ambiguous_exact_matches(self) -> None:
        client = self.client_for(
            b'{"returnCode":"OK","results":['
            b'{"type":"STATION","id":"Master:1","name":"Markt",'
            b'"city":"Hamburg","combinedName":"Hamburg, Markt"},'
            b'{"type":"STATION","id":"Master:2","name":"Markt",'
            b'"city":"Hamburg","combinedName":"Hamburg, Markt (Nord)"}]}'
        )
        with self.assertRaisesRegex(GeofoxError, "nicht eindeutig"):
            client.find_station("Markt", "Hamburg")

    def test_station_search_returns_unique_exact_match(self) -> None:
        client = self.client_for(
            b'{"returnCode":"OK","results":['
            b'{"type":"STATION","id":"Master:82015","name":"Recknitzstra\\u00dfe",'
            b'"city":"Hamburg","combinedName":"Recknitzstra\\u00dfe"}]}'
        )
        result = client.find_station("Recknitzstraße", "Hamburg")
        self.assertEqual(result["id"], "Master:82015")

    def test_station_search_rejects_missing_station(self) -> None:
        client = self.client_for(
            b'{"returnCode":"OK","results":['
            b'{"type":"ADDRESS","id":"Address:1","name":"Markt"}]}'
        )
        with self.assertRaisesRegex(GeofoxError, "nicht gefunden"):
            client.find_station("Markt", "Hamburg")

    def test_station_search_uses_combined_name_and_fallback_values(self) -> None:
        client = self.client_for(
            b'{"returnCode":"OK","results":['
            b'{"type":"STATION","id":"Master:1",'
            b'"combinedName":"Hamburg, Markt Nord"}]}'
        )
        self.assertEqual(
            client.find_station("Markt", "Hamburg"),
            {
                "name": "Markt",
                "city": "Hamburg",
                "id": "Master:1",
                "type": "STATION",
            },
        )

    def test_malformed_departures_are_ignored(self) -> None:
        client = self.client_for(
            b'{"returnCode":"OK","departures":['
            b'"invalid",'
            b'{"line":"invalid","timeOffset":1},'
            b'{"line":{"name":"1","direction":"Other"},"timeOffset":1},'
            b'{"line":{"name":"1","direction":"Ziel"}},'
            b'{"line":{"name":"1","direction":"Ziel"},"timeOffset":"bad"},'
            b'{"line":{"name":"1","direction":"Ziel"},"timeOffset":2,'
            b'"delay":30,"cancelled":true}]}'
        )
        station = Station(
            "Test",
            "Hamburg",
            (Route("1", "Ziel"),),
            "Master:1",
            "T",
        )
        result = client.departure_list(
            (station,),
            now=datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ),
        )
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0].cancelled)
        self.assertEqual(result[0].delay_seconds, 30)

    def test_ambiguous_station_mapping_omits_label(self) -> None:
        client = self.client_for(
            b'{"returnCode":"OK","departures":['
            b'{"line":{"name":"1","direction":"Ziel"},"timeOffset":2}]}'
        )
        stations = (
            Station("A", "Hamburg", (Route("1", "Ziel"),), "Master:1", "A"),
            Station("B", "Hamburg", (Route("1", "Ziel"),), "Master:2", "B"),
        )
        result = client.departure_list(
            stations,
            now=datetime(2026, 7, 27, 12, 0, tzinfo=HAMBURG_TZ),
        )
        self.assertEqual(result[0].station_label, "")


if __name__ == "__main__":
    unittest.main()
