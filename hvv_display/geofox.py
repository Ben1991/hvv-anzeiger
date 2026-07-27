from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
import unicodedata
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .models import Departure, Route, Station

LOG = logging.getLogger(__name__)
HAMBURG_TZ = ZoneInfo("Europe/Berlin")


class GeofoxError(RuntimeError):
    """A safe, user-displayable Geofox error."""


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


class GeofoxClient:
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
            raise GeofoxError("GEOFOX_USER und GEOFOX_PASSWORD müssen gesetzt sein")
        self.base_url = base_url.rstrip("/")
        self.user = user
        self._password = password.encode("utf-8")
        self.version = version
        self.timeout = timeout
        self.min_request_interval = min_request_interval
        self._urlopen = urlopen
        self._last_request_at = 0.0
        self._rate_lock = threading.Lock()

    @staticmethod
    def encode_body(payload: dict[str, Any]) -> bytes:
        return json.dumps(
            payload, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    def signature(self, body: bytes) -> str:
        digest = hmac.new(self._password, body, hashlib.sha1).digest()
        return base64.b64encode(digest).decode("ascii")

    def _wait_for_rate_limit(self) -> None:
        with self._rate_lock:
            remaining = self.min_request_interval - (
                time.monotonic() - self._last_request_at
            )
            if remaining > 0:
                time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def _post(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = self.encode_body(payload)
        trace_id = str(uuid.uuid4())
        request = urllib.request.Request(
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
                raw = response.read()
        except urllib.error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")[:300]
            LOG.error(
                "Geofox HTTP %s, Trace-ID %s: %s", exc.code, trace_id, details
            )
            if exc.code == 401:
                raise GeofoxError("Geofox-Zugangsdaten wurden abgelehnt") from exc
            if exc.code == 429:
                raise GeofoxError("Geofox-Anfragelimit erreicht") from exc
            raise GeofoxError(f"Geofox antwortet mit HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            LOG.error("Geofox nicht erreichbar, Trace-ID %s: %s", trace_id, exc)
            raise GeofoxError("Geofox ist nicht erreichbar") from exc

        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            LOG.error("Ungültige Geofox-Antwort, Trace-ID %s", trace_id)
            raise GeofoxError("Geofox liefert eine ungültige Antwort") from exc
        if not isinstance(result, dict):
            raise GeofoxError("Geofox liefert kein Antwortobjekt")
        if result.get("returnCode") != "OK":
            developer_info = str(result.get("errorDevInfo", ""))[:300]
            LOG.error(
                "Geofox returnCode=%s, Trace-ID %s: %s",
                result.get("returnCode"),
                trace_id,
                developer_info,
            )
            message = result.get("errorText") or result.get("returnCode") or "Unbekannt"
            raise GeofoxError(f"Geofox-Fehler: {message}")
        return result

    def find_station(self, name: str, city: str = "Hamburg") -> dict[str, str]:
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
        candidates = [
            candidate
            for candidate in (result.get("results") or [])
            if candidate.get("type") == "STATION" and candidate.get("id")
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
        if not matches:
            raise GeofoxError(f"Haltestelle {city}, {name} wurde nicht gefunden")
        if len(matches) > 1:
            names = ", ".join(str(item.get("combinedName")) for item in matches[:3])
            raise GeofoxError(
                f"Haltestelle {name} ist nicht eindeutig ({names}); "
                "ID in config.json setzen"
            )
        station = matches[0]
        return {
            "name": str(station.get("name") or name),
            "city": str(station.get("city") or city),
            "id": str(station["id"]),
            "type": "STATION",
        }

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
            station.station_id: station
            for station in stations
            if station.station_id
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
