from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .models import Route, Station
from .time_display import MINUTE_UNITS, TIME_MODES

MAX_ROUTE_FILTER_STATIONS = 200


class ConfigError(ValueError):
    """Raised when the local configuration is incomplete or invalid."""


@dataclass(frozen=True)
class ApiConfig:
    base_url: str
    version: int
    refresh_seconds: int
    request_timeout_seconds: float
    max_departures: int
    max_time_offset_minutes: int
    max_stale_age_minutes: int


@dataclass(frozen=True)
class DisplayConfig:
    spi_port: int
    spi_device: int
    gpio_dc: int
    gpio_reset: int
    rotate: int
    bus_speed_hz: int
    bgr: bool
    time_mode: str = "countdown"
    minute_unit: str = "min"


@dataclass(frozen=True)
class NightShutdownConfig:
    enabled: bool
    start: time
    end: time


@dataclass(frozen=True)
class AppConfig:
    api: ApiConfig
    display: DisplayConfig
    night_shutdown: NightShutdownConfig
    stations: tuple[Station, ...]


def _required(data: dict[str, Any], key: str, section: str) -> Any:
    if key not in data:
        raise ConfigError(f"Pflichtfeld {section}.{key} fehlt")
    return data[key]


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{field} muss true oder false sein")
    return value


def _geofox_base_url(value: Any) -> str:
    base_url = str(value).rstrip("/")
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise ConfigError("api.base_url ist keine gültige URL") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "gti.geofox.de"
        or port not in (None, 443)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError(
            "api.base_url muss eine HTTPS-URL auf gti.geofox.de ohne "
            "Zugangsdaten, Query oder Fragment sein"
        )
    return base_url


def _clock_time(value: Any, field: str) -> time:
    raw = str(value)
    if re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw) is None:
        raise ConfigError(f"{field} muss als HH:MM angegeben werden")
    return time.fromisoformat(raw)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path)
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Konfiguration nicht gefunden: {config_path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Ungültiges JSON in {config_path}: {exc}") from exc

    try:
        api_raw = raw["api"]
        display_raw = raw["display"]
        night_raw = raw.get("night_shutdown", {})
        stations_raw = raw["stations"]
    except (KeyError, TypeError) as exc:
        raise ConfigError("Konfiguration benötigt api, display und stations") from exc

    api = ApiConfig(
        base_url=_geofox_base_url(_required(api_raw, "base_url", "api")),
        version=int(api_raw.get("version", 63)),
        refresh_seconds=int(api_raw.get("refresh_seconds", 15)),
        request_timeout_seconds=float(api_raw.get("request_timeout_seconds", 8)),
        max_departures=int(api_raw.get("max_departures", 5)),
        max_time_offset_minutes=int(api_raw.get("max_time_offset_minutes", 90)),
        max_stale_age_minutes=int(api_raw.get("max_stale_age_minutes", 5)),
    )
    if api.refresh_seconds < 15:
        raise ConfigError("api.refresh_seconds muss mindestens 15 sein")
    if not 1 <= api.max_departures <= 5:
        raise ConfigError("api.max_departures muss zwischen 1 und 5 liegen")
    if api.request_timeout_seconds <= 0:
        raise ConfigError("api.request_timeout_seconds muss größer als 0 sein")
    if api.max_time_offset_minutes <= 0:
        raise ConfigError("api.max_time_offset_minutes muss größer als 0 sein")
    if api.max_stale_age_minutes <= 0:
        raise ConfigError("api.max_stale_age_minutes muss größer als 0 sein")

    display = DisplayConfig(
        spi_port=int(display_raw.get("spi_port", 0)),
        spi_device=int(display_raw.get("spi_device", 0)),
        gpio_dc=int(display_raw.get("gpio_dc", 24)),
        gpio_reset=int(display_raw.get("gpio_reset", 25)),
        rotate=int(display_raw.get("rotate", 0)),
        bus_speed_hz=int(display_raw.get("bus_speed_hz", 16_000_000)),
        bgr=_boolean(display_raw.get("bgr", False), "display.bgr"),
        time_mode=str(display_raw.get("time_mode", "countdown")).strip(),
        minute_unit=str(display_raw.get("minute_unit", "min")).strip(),
    )
    if display.rotate not in (0, 1, 2, 3):
        raise ConfigError("display.rotate muss 0, 1, 2 oder 3 sein")
    if display.bus_speed_hz <= 0:
        raise ConfigError("display.bus_speed_hz muss größer als 0 sein")
    if display.time_mode not in TIME_MODES:
        raise ConfigError(
            "display.time_mode muss countdown oder departure_time sein"
        )
    if display.minute_unit not in MINUTE_UNITS:
        raise ConfigError("display.minute_unit muss min, m oder none sein")

    night_shutdown = NightShutdownConfig(
        enabled=_boolean(
            night_raw.get("enabled", False),
            "night_shutdown.enabled",
        ),
        start=_clock_time(
            night_raw.get("start", "21:00"),
            "night_shutdown.start",
        ),
        end=_clock_time(
            night_raw.get("end", "06:30"),
            "night_shutdown.end",
        ),
    )
    if night_shutdown.start == night_shutdown.end:
        raise ConfigError(
            "night_shutdown.start und night_shutdown.end müssen verschieden sein"
        )

    stations: list[Station] = []
    for index, station_raw in enumerate(stations_raw):
        station_name = str(_required(station_raw, "name", f"stations[{index}]"))
        label = str(station_raw.get("label") or station_name[:1]).strip().upper()
        if not 1 <= len(label) <= 3:
            raise ConfigError(
                f"stations[{index}].label muss zwischen 1 und 3 Zeichen lang sein"
            )
        routes = tuple(
            _route_from_raw(route, f"stations[{index}].routes")
            for route in _required(station_raw, "routes", f"stations[{index}]")
        )
        if not routes:
            raise ConfigError(f"stations[{index}].routes darf nicht leer sein")
        stations.append(
            Station(
                name=station_name,
                city=str(station_raw.get("city", "Hamburg")),
                station_id=station_raw.get("id"),
                routes=routes,
                label=label,
            )
        )

    if not stations:
        raise ConfigError("Mindestens eine Haltestelle muss konfiguriert sein")
    labels = [station.label for station in stations]
    if len(labels) != len(set(labels)):
        raise ConfigError("stations[].label muss pro Haltestelle eindeutig sein")
    return AppConfig(
        api=api,
        display=display,
        night_shutdown=night_shutdown,
        stations=tuple(stations),
    )


def _route_from_raw(route: Any, section: str) -> Route:
    if not isinstance(route, dict):
        raise ConfigError(f"{section} muss Objekte enthalten")
    line = str(_required(route, "line", section)).strip()
    if "destination" not in route and "line_id" not in route:
        _required(route, "destination", section)
    line_id = route.get("line_id")
    line_id = str(line_id).strip() if line_id is not None else None
    destination = str(route.get("destination", "")).strip()
    if not line or (not destination and not line_id):
        raise ConfigError(f"{section}.destination oder line_id muss gesetzt sein")
    product = route.get("product")
    filter_mode = route.get("filter_mode")
    filter_mode = str(filter_mode).strip() if filter_mode is not None else None
    if filter_mode == "":
        filter_mode = None
    if filter_mode not in (None, "direction", "destination"):
        raise ConfigError(
            f"{section}.filter_mode muss direction oder destination sein"
        )
    raw_filter_station_ids = route.get("filter_station_ids", [])
    if not isinstance(raw_filter_station_ids, (list, tuple)):
        raise ConfigError(f"{section}.filter_station_ids muss eine Liste sein")
    if len(raw_filter_station_ids) > MAX_ROUTE_FILTER_STATIONS:
        raise ConfigError(
            f"{section}.filter_station_ids enthält zu viele Haltestellen"
        )
    filter_station_ids = tuple(
        str(station_id).strip()
        for station_id in raw_filter_station_ids
        if str(station_id).strip()
    )
    if filter_mode and not filter_station_ids:
        raise ConfigError(
            f"{section}.filter_station_ids muss für einen Filter gesetzt sein"
        )
    if filter_station_ids and not filter_mode:
        raise ConfigError(
            f"{section}.filter_mode muss für filter_station_ids gesetzt sein"
        )
    return Route(
        line=line,
        destination=destination,
        line_id=line_id or None,
        product=str(product).strip() if product is not None else None,
        filter_mode=filter_mode,
        filter_station_ids=filter_station_ids,
    )
