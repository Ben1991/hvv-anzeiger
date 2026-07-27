from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Route, Station


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


@dataclass(frozen=True)
class DisplayConfig:
    spi_port: int
    spi_device: int
    gpio_dc: int
    gpio_reset: int
    rotate: int
    bus_speed_hz: int
    bgr: bool


@dataclass(frozen=True)
class AppConfig:
    api: ApiConfig
    display: DisplayConfig
    stations: tuple[Station, ...]


def _required(data: dict[str, Any], key: str, section: str) -> Any:
    if key not in data:
        raise ConfigError(f"Pflichtfeld {section}.{key} fehlt")
    return data[key]


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
        stations_raw = raw["stations"]
    except (KeyError, TypeError) as exc:
        raise ConfigError("Konfiguration benötigt api, display und stations") from exc

    api = ApiConfig(
        base_url=str(_required(api_raw, "base_url", "api")).rstrip("/"),
        version=int(api_raw.get("version", 63)),
        refresh_seconds=int(api_raw.get("refresh_seconds", 15)),
        request_timeout_seconds=float(api_raw.get("request_timeout_seconds", 8)),
        max_departures=int(api_raw.get("max_departures", 5)),
        max_time_offset_minutes=int(api_raw.get("max_time_offset_minutes", 90)),
    )
    if api.refresh_seconds < 15:
        raise ConfigError("api.refresh_seconds muss mindestens 15 sein")
    if not 1 <= api.max_departures <= 5:
        raise ConfigError("api.max_departures muss zwischen 1 und 5 liegen")

    display = DisplayConfig(
        spi_port=int(display_raw.get("spi_port", 0)),
        spi_device=int(display_raw.get("spi_device", 0)),
        gpio_dc=int(display_raw.get("gpio_dc", 24)),
        gpio_reset=int(display_raw.get("gpio_reset", 25)),
        rotate=int(display_raw.get("rotate", 0)),
        bus_speed_hz=int(display_raw.get("bus_speed_hz", 16_000_000)),
        bgr=bool(display_raw.get("bgr", False)),
    )
    if display.rotate not in (0, 1, 2, 3):
        raise ConfigError("display.rotate muss 0, 1, 2 oder 3 sein")

    stations: list[Station] = []
    for index, station_raw in enumerate(stations_raw):
        routes = tuple(
            Route(
                line=str(_required(route, "line", f"stations[{index}].routes")),
                destination=str(
                    _required(route, "destination", f"stations[{index}].routes")
                ),
            )
            for route in _required(station_raw, "routes", f"stations[{index}]")
        )
        stations.append(
            Station(
                name=str(_required(station_raw, "name", f"stations[{index}]")),
                city=str(station_raw.get("city", "Hamburg")),
                station_id=station_raw.get("id"),
                routes=routes,
            )
        )

    if not stations:
        raise ConfigError("Mindestens eine Haltestelle muss konfiguriert sein")
    return AppConfig(api=api, display=display, stations=tuple(stations))
