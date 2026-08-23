from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import math
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .models import Departure, Route, Station

LOG = logging.getLogger(__name__)
HAMBURG_TZ = ZoneInfo("Europe/Berlin")
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_RETRY_AFTER_SECONDS = 3600


class GeofoxError(RuntimeError):
    """A safe, user-displayable Geofox error."""

    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int | None = None,
        kind: str = "technical",
        http_status: int | None = None,
        return_code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.kind = kind
        self.http_status = http_status
        self.return_code = return_code


def _retry_after_seconds(value: Any, *, now: datetime | None = None) -> int | None:
    if value is None:
        return None
    raw = str(value).strip()
    try:
        seconds = int(raw)
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            reference = now or datetime.now(timezone.utc)
            seconds = math.ceil((retry_at - reference).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
    if seconds <= 0:
        return None
    return min(seconds, MAX_RETRY_AFTER_SECONDS)


def normalize(value: str) -> str:
    value = value.casefold().replace("ß", "ss")
    return " ".join(
        "".join(
            character
            for character in unicodedata.normalize("NFKD", value)
            if not unicodedata.combining(character)
        ).split()
    )


def route_matches(line_name: str, direction: str, routes: tuple[Route, ...]) -> bool:
    normalized_direction = normalize(direction)
    for route in routes:
        expected = normalize(route.destination)
        if normalize(line_name) == normalize(route.line) and (
            expected in normalized_direction or normalized_direction in expected
        ):
            return True
    return False


def _https_base_url(value: str) -> str:
    base_url = value.rstrip("/")
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise GeofoxError("Geofox-Basis-URL ist ungültig") from exc
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise GeofoxError("Geofox-Basis-URL muss eine sichere HTTPS-URL sein")
    return base_url


def _safe_external_text(value: Any, limit: int = 160) -> str:
    return "".join(
        character if character.isprintable() else " " for character in str(value)
    ).strip()[:limit]


def _return_code_error(result: dict[str, Any]) -> GeofoxError:
    code = _safe_external_text(result.get("returnCode") or "UNKNOWN", 80)
    user_messages = {
        "ERROR_CN_TOO_MANY": "Zu viele Treffer – bitte genauer eingeben.",
        "ERROR_COMM": "Geofox ist aktuell nicht erreichbar.",
        "START_NOT_FOUND": "Haltestelle wurde nicht gefunden.",
        "DEST_NOT_FOUND": "Zielstation wurde nicht gefunden.",
        "VIA_NOT_FOUND": "Zwischenhaltestelle wurde nicht gefunden.",
        "FORCED_START_NOT_FOUND": "Haltestelle wurde nicht eindeutig gefunden.",
        "FORCED_DEST_NOT_FOUND": "Zielstation wurde nicht eindeutig gefunden.",
    }
    if code == "ERROR_TEXT":
        text = _safe_external_text(
            result.get("errorText") or "Geofox meldet einen Fehler"
        )
        return GeofoxError(text, kind="validation", return_code=code)
    if code in user_messages:
        kind = "temporary" if code == "ERROR_COMM" else "validation"
        return GeofoxError(user_messages[code], kind=kind, return_code=code)
    return GeofoxError("Geofox meldet einen unbekannten Fehler.", return_code=code)


class GeofoxClient:
    # Geofox rate limits apply to the application, not to a Python object. The
    # web UI creates clients for different operations, therefore all instances
    # share one serialization lock and one request timestamp.
    _global_rate_lock = threading.Lock()
    _global_last_request_at = 0.0
    _global_retry_until = 0.0

    def __init__(
        self,
        base_url: str,
        user: str,
        password: str,
        *,
        version: int = 63,
        timeout: float = 8,
        min_request_interval: float = 1.05,
        urlopen: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if not user or not password:
            raise GeofoxError(
                "GEOFOX_USER und GEOFOX_PASSWORD müssen gesetzt sein",
                kind="credentials",
                http_status=401,
            )
        self.base_url = _https_base_url(base_url)
        self.user = user
        self._password = password.encode("utf-8")
        self.version = version
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self._urlopen = urlopen

    @staticmethod
    def encode_body(payload: dict[str, Any]) -> bytes:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )

    def signature(self, body: bytes) -> str:
        digest = hmac.new(self._password, body, hashlib.sha1).digest()
        return base64.b64encode(digest).decode("ascii")

    def _wait_for_rate_limit(self) -> None:
        with self._global_rate_lock:
            now = time.monotonic()
            wait_until = max(
                self._global_retry_until,
                self._global_last_request_at + self.min_request_interval,
            )
            remaining = wait_until - now
            if remaining > 0:
                time.sleep(remaining)
            type(self)._global_last_request_at = time.monotonic()

    @classmethod
    def _apply_retry_after(cls, seconds: int | None) -> None:
        if seconds:
            cls._global_retry_until = max(
                cls._global_retry_until, time.monotonic() + seconds
            )

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = self.encode_body(payload)
        trace_id = str(uuid.uuid4())
        request = urllib.request.Request(  # noqa: S310
            f"{self.base_url}/{method}",
            data=body,
            method="POST",
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json;charset=UTF-8",
                "geofox-auth-type": "HmacSHA1",
                "geofox-auth-user": self.user,
                "geofox-auth-signature": self.signature(body),
                "X-Platform": "mobile",
                "X-TraceId": trace_id,
                "User-Agent": "hvv-anzeiger/0.1",
            },
        )
        self._wait_for_rate_limit()
        try:
            with self._urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as exc:
            LOG.error("Geofox HTTP %s, Trace-ID %s", exc.code, trace_id)
            retry_after = _retry_after_seconds(exc.headers.get("Retry-After"))
            if exc.code == 429:
                self._apply_retry_after(retry_after)
                raise GeofoxError(
                    "Geofox-Anfragelimit erreicht – bitte später erneut versuchen.",
                    retry_after_seconds=retry_after,
                    kind="rate_limit",
                    http_status=429,
                ) from exc
            if exc.code in (401, 403):
                raise GeofoxError(
                    "Geofox-Zugangsdaten oder Berechtigungen wurden abgelehnt.",
                    kind="credentials",
                    http_status=exc.code,
                ) from exc
            if exc.code in (500, 503):
                raise GeofoxError(
                    "Geofox ist aktuell nicht erreichbar.",
                    kind="temporary",
                    http_status=exc.code,
                ) from exc
            raise GeofoxError(
                f"Geofox antwortet mit HTTP {exc.code}", http_status=exc.code
            ) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            LOG.error("Geofox nicht erreichbar, Trace-ID %s", trace_id)
            raise GeofoxError(
                "Geofox ist aktuell nicht erreichbar.", kind="temporary"
            ) from exc

        if len(raw) > MAX_RESPONSE_BYTES:
            LOG.error("Geofox-Antwort zu groß, Trace-ID %s", trace_id)
            raise GeofoxError("Geofox liefert eine zu große Antwort")

        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            LOG.error("Ungültige Geofox-Antwort, Trace-ID %s", trace_id)
            raise GeofoxError("Geofox liefert eine ungültige Antwort") from exc
        if not isinstance(result, dict):
            raise GeofoxError("Geofox liefert kein Antwortobjekt")
        if result.get("returnCode") != "OK":
            LOG.error(
                "Geofox returnCode=%s, Trace-ID %s",
                _safe_external_text(result.get("returnCode"), 80),
                trace_id,
            )
            raise _return_code_error(result)
        return result

    def find_station(self, name: str, city: str = "Hamburg") -> dict[str, Any]:
        matches = self.find_stations(name, city)
        if not matches:
            raise GeofoxError(
                f"Haltestelle {city}, {name} wurde nicht gefunden", kind="validation"
            )
        if len(matches) > 1:
            names = ", ".join(str(item.get("combinedName")) for item in matches[:3])
            raise GeofoxError(
                f"Haltestelle {name} ist nicht eindeutig ({names}); bitte auswählen.",
                kind="validation",
            )
        station = matches[0]
        return {
            "name": str(station.get("name") or name),
            "city": str(station.get("city") or city),
            "id": str(station["id"]),
            "type": "STATION",
            "serviceTypes": list(station.get("serviceTypes") or []),
        }

    def find_stations(self, name: str, city: str = "Hamburg") -> list[dict[str, Any]]:
        result = self._post(
            "checkName",
            {
                "version": self.version,
                "language": "de",
                "theName": {"name": name, "city": city, "type": "STATION"},
                "maxList": 10,
                "coordinateType": "EPSG_4326",
            },
        )
        raw_results = result.get("results") or []
        if not isinstance(raw_results, list):
            raise GeofoxError("Geofox liefert keine gültige Haltestellenliste")
        candidates = [
            candidate
            for candidate in raw_results
            if isinstance(candidate, dict)
            and candidate.get("type") == "STATION"
            and candidate.get("id")
        ]
        target_name = normalize(name)
        target_city = normalize(city)
        exact = [
            candidate
            for candidate in candidates
            if normalize(str(candidate.get("name", ""))) == target_name
            and (
                not candidate.get("city")
                or normalize(str(candidate.get("city"))) == target_city
            )
        ]
        matches = exact or [
            candidate
            for candidate in candidates
            if target_name in normalize(str(candidate.get("combinedName", "")))
        ]
        return [
            {
                "name": _safe_external_text(station.get("name") or name, 120),
                "city": _safe_external_text(station.get("city") or city, 80),
                "id": _safe_external_text(station["id"], 160),
                "combinedName": _safe_external_text(
                    station.get("combinedName") or station.get("name") or name, 200
                ),
                "serviceTypes": [
                    _safe_external_text(item, 40)
                    for item in (station.get("serviceTypes") or [])
                    if isinstance(item, (str, int))
                ][:20],
            }
            for station in matches[:10]
        ]

    def departure_list(
        self,
        stations: tuple[Station, ...],
        *,
        now: datetime | None = None,
        max_list: int = 30,
        max_time_offset: int = 90,
    ) -> list[Departure]:
        reference = (now or datetime.now(HAMBURG_TZ)).astimezone(HAMBURG_TZ)
        reference = reference.replace(second=0, microsecond=0)
        station_names = [station.as_geofox_name() for station in stations]
        payload: dict[str, Any] = {
            "version": self.version,
            "language": "de",
            "time": {
                "date": reference.strftime("%d.%m.%Y"),
                "time": reference.strftime("%H:%M"),
            },
            "maxList": max_list,
            "maxTimeOffset": max_time_offset,
            "serviceTypes": ["BUS"],
            "useRealtime": True,
        }
        if len(station_names) == 1:
            payload["station"] = station_names[0]
        else:
            payload["stations"] = station_names

        result = self._post("departureList", payload)
        stations_by_id = {
            station.station_id: station for station in stations if station.station_id
        }
        departures: list[Departure] = []
        raw_departures = result.get("departures") or []
        if not isinstance(raw_departures, list):
            raise GeofoxError("Geofox liefert keine gültige Abfahrtsliste")
        for raw in raw_departures:
            if not isinstance(raw, dict):
                LOG.warning("Ungültiger Eintrag in der Abfahrtsliste ignoriert")
                continue
            line = raw.get("line") or {}
            if not isinstance(line, dict):
                LOG.warning("Abfahrt ohne gültige Linienangabe ignoriert")
                continue
            line_name = str(line.get("name", ""))
            direction = str(line.get("direction", ""))
            response_station = raw.get("station") or {}
            response_station_id = (
                response_station.get("id")
                if isinstance(response_station, dict)
                else None
            )
            selected_station = stations_by_id.get(response_station_id)
            if selected_station:
                matching_stations = (
                    [selected_station]
                    if route_matches(line_name, direction, selected_station.routes)
                    else []
                )
            else:
                matching_stations = [
                    station
                    for station in stations
                    if route_matches(line_name, direction, station.routes)
                ]
            if not matching_stations:
                continue
            try:
                offset = int(raw["timeOffset"])
                delay_seconds = int(raw.get("delay") or 0)
            except (KeyError, TypeError, ValueError):
                LOG.warning("Abfahrt ohne gültige Zeitangabe ignoriert")
                continue
            departure_time = (
                reference.astimezone(timezone.utc)
                + timedelta(minutes=offset, seconds=delay_seconds)
            ).astimezone(HAMBURG_TZ)
            departures.append(
                Departure(
                    line=line_name,
                    destination=direction,
                    departure_time=departure_time,
                    delay_seconds=delay_seconds,
                    cancelled=bool(raw.get("cancelled", False)),
                    station_label=(
                        matching_stations[0].label
                        if len(matching_stations) == 1
                        else ""
                    ),
                )
            )
        return sorted(departures, key=lambda departure: departure.departure_time)
