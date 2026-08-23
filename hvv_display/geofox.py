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

from .models import Departure, LineOption, LineRouteOption, Route, Station

LOG = logging.getLogger(__name__)
HAMBURG_TZ = ZoneInfo("Europe/Berlin")
MAX_RESPONSE_BYTES = 1024 * 1024
# listLines contains every line and, for the station picker, every subline
# sequence. It is substantially larger than normal Geofox responses, but it
# remains bounded to avoid turning the cache request into an unbounded read.
MAX_LINE_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_RETRY_AFTER_SECONDS = 3600
MAX_LINE_OPTIONS = 200
MAX_ROUTE_STATIONS = 200
MAX_ROUTE_STATION_SUGGESTIONS = 80
_VEHICLE_LABELS = {
    "UBAHN": "U-Bahn",
    "SBAHN": "S-Bahn",
    "ABAHN": "A-Bahn",
    "AKN": "AKN",
    "RBAHN": "Regionalbahn",
    "FBAHN": "Fernbahn",
    "ZUG": "Bahn",
    "TRAIN": "Bahn",
    "BUS": "Bus",
    "STADTBUS": "Stadtbus",
    "REGIONALBUS": "Regionalbus",
    "METROBUS": "MetroBus",
    "SCHNELLBUS": "SchnellBus",
    "NACHTBUS": "NachtBus",
    "XPRESSBUS": "XpressBus",
    "AST": "Anruf-Sammeltaxi",
    "SCHIFF": "Fähre",
    "FAEHRE": "Fähre",
}


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


def route_matches(
    line_name: str,
    direction: str,
    routes: tuple[Route, ...],
    line_id: str | None = None,
) -> bool:
    normalized_direction = normalize(direction)
    for route in routes:
        expected = normalize(route.destination)
        if route.line_id and line_id and route.line_id != line_id:
            continue
        if normalize(line_name) != normalize(route.line):
            continue
        if route.filter_station_ids:
            return True
        if not expected or (
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


def _vehicle_code(value: Any) -> str:
    if isinstance(value, dict):
        value = (
            value.get("simpleType")
            or value.get("vehicleType")
            or value.get("shortInfo")
            or ""
        )
    return str(value or "").strip().upper().replace("-", "_").replace(" ", "_")


def _safe_vehicle_product(value: Any) -> str:
    code = _vehicle_code(value).replace("_", "")
    return code if code in _VEHICLE_LABELS else "UNKNOWN"


def vehicle_type_label(value: Any) -> str:
    code = _safe_vehicle_product(value)
    return _VEHICLE_LABELS.get(code, "Unbekanntes Verkehrsmittel")


def line_options_for_station(
    lines: Any, station_id: str
) -> tuple[LineOption, ...]:
    options: list[LineOption] = []
    seen: set[str] = set()
    for raw_line in lines if isinstance(lines, list) else []:
        if not isinstance(raw_line, dict) or raw_line.get("exists") is False:
            continue
        line_id = _safe_external_text(raw_line.get("id"), 160)
        line_name = _safe_external_text(raw_line.get("name"), 80)
        if not line_id or not line_name or line_id in seen:
            continue
        sublines = raw_line.get("sublines")
        if not isinstance(sublines, list):
            continue
        for subline in sublines:
            if not isinstance(subline, dict):
                continue
            sequence = subline.get("stationSequence")
            if not isinstance(sequence, list) or not any(
                isinstance(stop, dict) and str(stop.get("id", "")) == station_id
                for stop in sequence
            ):
                continue
            raw_product = _vehicle_code(
                subline.get("vehicleType") or raw_line.get("type")
            )
            product = _safe_vehicle_product(raw_product) if raw_product else "UNKNOWN"
            if product == "UNKNOWN":
                LOG.warning("Linie %s hat kein bekanntes Verkehrsmittel", line_name)
            options.append(
                LineOption(
                    line_id=line_id,
                    name=line_name,
                    product=product,
                    product_label=vehicle_type_label(product),
                    carrier=_safe_external_text(
                        raw_line.get("carrierNameShort")
                        or raw_line.get("carrierNameLong"),
                        80,
                    ),
                )
            )
            seen.add(line_id)
            break
        if len(options) >= MAX_LINE_OPTIONS:
            LOG.warning(
                "Linienliste für Haltestelle auf %d Einträge begrenzt",
                MAX_LINE_OPTIONS,
            )
            break
    return tuple(options)


def line_route_options_for_station(
    lines: Any, line_id: str, station_id: str
) -> tuple[LineRouteOption, ...]:
    """Return each downstream line branch available from a station."""
    raw_lines = lines if isinstance(lines, list) else []
    matching_line = next(
        (
            raw_line
            for raw_line in raw_lines
            if isinstance(raw_line, dict)
            and raw_line.get("exists") is not False
            and _safe_external_text(raw_line.get("id"), 160) == line_id
        ),
        None,
    )
    if matching_line is None:
        return ()
    options: list[LineRouteOption] = []
    seen: set[tuple[str, ...]] = set()
    sublines = matching_line.get("sublines")
    if not isinstance(sublines, list):
        return ()
    for subline in sublines:
        if not isinstance(subline, dict):
            continue
        sequence = subline.get("stationSequence")
        if not isinstance(sequence, list):
            continue
        stops = [
            (
                _safe_external_text(stop.get("id"), 160),
                _safe_external_text(stop.get("name"), 120),
            )
            for stop in sequence
            if isinstance(stop, dict) and stop.get("id")
        ]
        for index, (stop_id, _stop_name) in enumerate(stops):
            if stop_id != station_id:
                continue
            # Geofox evaluates stationIDs against the downstream direction.
            # Keeping the source station here would make every departure match.
            downstream = stops[index + 1 : index + 1 + MAX_ROUTE_STATIONS]
            downstream_ids = tuple(stop[0] for stop in downstream)
            if not downstream_ids or downstream_ids in seen:
                continue
            seen.add(downstream_ids)
            end_name = downstream[-1][1] or downstream[-1][0]
            options.append(
                LineRouteOption(
                    line_id=line_id,
                    label=f"Richtung {end_name}",
                    station_ids=downstream_ids,
                    stations=tuple(downstream),
                )
            )
            if len(options) >= MAX_LINE_OPTIONS:
                LOG.warning(
                    "Richtungsoptionen für Linie %s auf %d Einträge begrenzt",
                    line_id,
                    MAX_LINE_OPTIONS,
                )
                return tuple(options)
    return tuple(options)


def line_route_stations(
    options: tuple[LineRouteOption, ...], query: str = ""
) -> tuple[dict[str, str], ...]:
    """Return bounded, deduplicated downstream station suggestions."""
    normalized_query = normalize(query) if query else ""
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()
    for option in options:
        for station_id, name in option.stations:
            if station_id in seen or (
                normalized_query and normalized_query not in normalize(name)
            ):
                continue
            seen.add(station_id)
            suggestions.append({"id": station_id, "name": name})
            if len(suggestions) >= MAX_ROUTE_STATION_SUGGESTIONS:
                return tuple(suggestions)
    return tuple(suggestions)


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


def _http_error_body(exc: urllib.error.HTTPError) -> dict[str, Any] | None:
    """Read and validate a bounded Geofox JSON body from an HTTP error."""
    try:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
    except (OSError, ValueError):
        return None
    if len(raw) > MAX_RESPONSE_BYTES:
        return None
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(result, dict) or not isinstance(result.get("returnCode"), str):
        return None
    return result


class GeofoxClient:
    # Geofox rate limits apply to the application, not to a Python object. The
    # web UI creates clients for different operations, therefore all instances
    # share one request lock and one request timestamp.
    _global_request_lock = threading.Lock()
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
            with cls._global_rate_lock:
                cls._global_retry_until = max(
                    cls._global_retry_until, time.monotonic() + seconds
                )

    def _post(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        max_response_bytes: int = MAX_RESPONSE_BYTES,
    ) -> dict[str, Any]:
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
        # Waiting and the actual request must be one critical section. Waiting
        # alone leaves a gap in which another client can send concurrently
        # while the first request is still in flight.
        with type(self)._global_request_lock:
            self._wait_for_rate_limit()
            try:
                with self._urlopen(request, timeout=self.timeout) as response:
                    raw = response.read(max_response_bytes + 1)
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
                if exc.code == 400:
                    result = _http_error_body(exc)
                    if result is not None:
                        body_error = _return_code_error(result)
                        raise GeofoxError(
                            str(body_error),
                            retry_after_seconds=retry_after,
                            kind=body_error.kind,
                            http_status=exc.code,
                            return_code=body_error.return_code,
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

        if len(raw) > max_response_bytes:
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

    def list_lines(self) -> list[dict[str, Any]]:
        result = self._post(
            "listLines",
            {
                "language": "de",
                "version": self.version,
                "dataReleaseID": "",
                "modificationTypes": ["MAIN", "SEQUENCE"],
                "withSublines": True,
            },
            max_response_bytes=MAX_LINE_RESPONSE_BYTES,
        )
        lines = result.get("lines")
        if lines is None:
            lines = []
        if not isinstance(lines, list):
            raise GeofoxError("Geofox liefert keine gültige Linienliste")
        return lines

    def line_options(self, station_id: str) -> tuple[LineOption, ...]:
        return line_options_for_station(self.list_lines(), station_id)

    def line_route_options(
        self, station_id: str, line_id: str
    ) -> tuple[LineRouteOption, ...]:
        return line_route_options_for_station(self.list_lines(), line_id, station_id)

    def line_route_stations(
        self, station_id: str, line_id: str, query: str = ""
    ) -> tuple[dict[str, str], ...]:
        options = self.line_route_options(station_id, line_id)
        return line_route_stations(options, query)

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
            "useRealtime": True,
        }
        filters = []
        seen_filter_keys: set[tuple[str, tuple[str, ...]]] = set()
        for station in stations:
            for route in station.routes:
                if not route.line_id:
                    continue
                station_ids = tuple(route.filter_station_ids)
                filter_key = (route.line_id, station_ids)
                if filter_key in seen_filter_keys:
                    continue
                seen_filter_keys.add(filter_key)
                entry: dict[str, Any] = {
                    "serviceID": route.line_id,
                    "serviceName": route.line,
                }
                if station_ids:
                    entry["stationIDs"] = list(station_ids)
                filters.append(entry)
        if filters:
            payload["filter"] = filters
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
            response_line_id = (
                _safe_external_text(line.get("id"), 160)
                if line.get("id")
                else None
            )
            product = _safe_vehicle_product(
                line.get("type") or line.get("vehicleType")
            )
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
                    if route_matches(
                        line_name,
                        direction,
                        selected_station.routes,
                        response_line_id,
                    )
                    else []
                )
            else:
                matching_stations = [
                    station
                    for station in stations
                    if route_matches(
                        line_name, direction, station.routes, response_line_id
                    )
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
                    product=product or None,
                )
            )
        return sorted(departures, key=lambda departure: departure.departure_time)
