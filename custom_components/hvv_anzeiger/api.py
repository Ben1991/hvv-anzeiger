"""Bounded response handling for the local HVV-Anzeiger API."""

from __future__ import annotations

import ipaddress
import json
from typing import Any
from urllib.parse import urlsplit

MAX_API_RESPONSE_BYTES = 1_048_576
API_RESPONSE_CHUNK_BYTES = 65_536


class ApiResponseTooLarge(ValueError):
    """The backend returned more bytes than the integration accepts."""


def build_discovered_url(hostname: str, port: int, scheme: str) -> str:
    """Build the discovery URL from the advertised hostname, preserving TLS SNI."""
    host = hostname.rstrip(".")
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if scheme not in {"http", "https"}:
        scheme = "https"
    return f"{scheme}://{host}:{port}"


def is_secure_url(url: str) -> bool:
    """Allow HTTPS remotely and HTTP only for an explicit loopback endpoint."""
    parsed = urlsplit(url)
    if parsed.scheme == "https":
        return bool(parsed.hostname)
    if parsed.scheme != "http" or not parsed.hostname:
        return False
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


async def read_json_response(response: Any) -> Any:
    """Read a complete JSON response while bounding memory use."""
    body = bytearray()
    async for chunk in response.content.iter_chunked(API_RESPONSE_CHUNK_BYTES):
        body.extend(chunk)
        if len(body) > MAX_API_RESPONSE_BYTES:
            raise ApiResponseTooLarge("Antwort des HVV-Anzeigers ist zu groß")
    return json.loads(body)
