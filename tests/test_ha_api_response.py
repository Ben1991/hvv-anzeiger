"""Tests for bounded, complete JSON reads used by the HA integration."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

API_PATH = Path(__file__).parents[1] / "custom_components" / "hvv_anzeiger" / "api.py"
SPEC = importlib.util.spec_from_file_location("hvv_ha_api", API_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("Could not load the Home Assistant API helper")
API = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(API)


class ChunkedContent:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.iterated = 0

    async def iter_chunked(self, chunk_size: int):
        self.asserted_chunk_size = chunk_size
        for chunk in self.chunks:
            self.iterated += 1
            yield chunk


class FakeResponse:
    def __init__(self, chunks: list[bytes]) -> None:
        self.content = ChunkedContent(chunks)


class HomeAssistantApiResponseTest(unittest.IsolatedAsyncioTestCase):
    async def test_reads_all_chunks_before_decoding(self) -> None:
        response = FakeResponse([b'{"schema_', b'version":1}'])

        result = await API.read_json_response(response)

        self.assertEqual(result, {"schema_version": 1})
        self.assertEqual(response.content.iterated, 2)
        self.assertEqual(
            response.content.asserted_chunk_size, API.API_RESPONSE_CHUNK_BYTES
        )

    async def test_rejects_cumulative_size_over_limit(self) -> None:
        response = FakeResponse([b" " * 600_000, b" " * 500_000])

        with self.assertRaises(API.ApiResponseTooLarge):
            await API.read_json_response(response)

        self.assertEqual(response.content.iterated, 2)

    def test_discovered_url_uses_advertised_hostname(self) -> None:
        self.assertEqual(
            API.build_discovered_url("hvv.example.net.", 8080, "https"),
            "https://hvv.example.net:8080",
        )
        self.assertEqual(
            API.build_discovered_url("fe80::1", 8080, "https"),
            "https://[fe80::1]:8080",
        )

    def test_cleartext_is_limited_to_loopback(self) -> None:
        self.assertTrue(API.is_secure_url("http://localhost:8080"))
        self.assertTrue(API.is_secure_url("http://[::1]:8080"))
        self.assertFalse(API.is_secure_url("http://hvv-anzeiger.local:8080"))
        self.assertFalse(API.is_secure_url("http://192.168.1.20:8080"))
        self.assertTrue(API.is_secure_url("https://hvv.example.net:8080"))


if __name__ == "__main__":
    unittest.main()
