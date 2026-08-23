from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Route:
    line: str
    destination: str
    line_id: str | None = None
    product: str | None = None
    filter_mode: str | None = None
    filter_station_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LineOption:
    line_id: str
    name: str
    product: str
    product_label: str
    carrier: str = ""


@dataclass(frozen=True)
class LineRouteOption:
    line_id: str
    label: str
    station_ids: tuple[str, ...]
    stations: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Station:
    name: str
    city: str
    routes: tuple[Route, ...]
    station_id: str | None = None
    label: str = ""

    def as_geofox_name(self) -> dict[str, str]:
        if not self.station_id:
            raise ValueError(f"Haltestelle {self.name!r} hat noch keine Geofox-ID")
        return {
            "name": self.name,
            "city": self.city,
            "id": self.station_id,
            "type": "STATION",
        }


@dataclass(frozen=True)
class Departure:
    line: str
    destination: str
    departure_time: datetime
    delay_seconds: int = 0
    cancelled: bool = False
    station_label: str = ""
    product: str | None = None
