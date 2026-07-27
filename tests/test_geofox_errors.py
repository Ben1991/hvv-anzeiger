import io
import unittest
import urllib.error

from hvv_display.geofox import GeofoxClient, GeofoxError


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self) -> bytes:
        return self.body


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


if __name__ == "__main__":
    unittest.main()
